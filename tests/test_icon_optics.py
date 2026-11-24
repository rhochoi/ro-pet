"""아이콘 광학 보정 검증(Track A):
1. (사이트 파비콘은 앱 아이콘과 같은 파일이라 tests/test_site.py가 같음을 검사한다)
2. assets/icon/ro.svg 두 눈 종횡비 1.15 ~ 1.55 및 캡슐 반경(rx = width / 2) 검증
3. 16 / 32 / 64px 실물 래스터 이미지에서 두 눈이 뭉개지지 않고 분리 성분(connected components) 정확히 2개로 검출되는지 검증
4. assets/icon/ro.icns 및 다중 해상도 PNG(16~1024px) 유효성 검증
"""
from collections import deque
import shutil
import struct
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RO_SVG = ROOT / "assets/icon/ro.svg"
RO_ICNS = ROOT / "assets/icon/ro.icns"
SIZES = (16, 32, 64, 128, 256, 512, 1024)


def png_dimensions(path: Path) -> tuple[int, int]:
    """PNG IHDR 헤더(첫 24바이트)만 읽어 (width, height)를 반환한다(대용량 튜플 배열 미할당)."""
    with open(path, "rb") as f:
        hdr = f.read(24)
    if len(hdr) < 24 or hdr[:8] != b"\x89PNG\r\n\x1a\n" or hdr[12:16] != b"IHDR":
        raise ValueError(f"유효한 PNG 헤더가 아님: {path}")
    w, h = struct.unpack(">II", hdr[16:24])
    return w, h


def decode_png_rgba(path: Path):
    """표준 라이브러리(zlib·struct)만으로 8-bit PNG(RGB/RGBA)의 픽셀 배열 (width, height, rows)을 읽는다."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"유효한 PNG 시그니처가 아님: {path}")
    pos = 8
    width = height = bit_depth = color_type = None
    idat = bytearray()
    while pos < len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, comp, filt, interlace = struct.unpack(">IIBBBBB", chunk)
            if bit_depth != 8 or color_type not in (2, 6) or interlace != 0:
                raise ValueError(f"지원하지 않는 PNG 포맷: depth={bit_depth}, color={color_type}, interlace={interlace}")
        elif ctype == b"IDAT":
            idat.extend(chunk)
        elif ctype == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    bpp = 4 if color_type == 6 else 3
    stride = width * bpp
    rows = []
    prev = bytearray(stride)
    idx = 0
    for _ in range(height):
        ftype = raw[idx]
        idx += 1
        cur = bytearray(raw[idx:idx + stride])
        idx += stride
        if ftype == 1:  # Sub
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                cur[i] = (cur[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[i] = (cur[i] + pr) & 0xFF
        prev = cur
        row = []
        for x in range(width):
            off = x * bpp
            r, g, b = cur[off], cur[off + 1], cur[off + 2]
            a = cur[off + 3] if bpp == 4 else 255
            row.append((r, g, b, a))
        rows.append(row)
    return width, height, rows


def luminance(rgb):
    r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def detect_eye_components(rows, x_range, y_range, lum_threshold=0.58):
    """머리 영역(x_range, y_range) 안에서 밝은 머리 바탕 대비 어두운 눈 픽셀의 4-연결 성분 개수를 구한다."""
    h = len(rows)
    w = len(rows[0]) if h else 0
    x0, x1 = max(0, int(w * x_range[0])), min(w, int(round(w * x_range[1])))
    y0, y1 = max(0, int(h * y_range[0])), min(h, int(round(h * y_range[1])))
    dark = set()
    for y in range(y0, y1):
        for x in range(x0, x1):
            if luminance(rows[y][x]) < lum_threshold:
                dark.add((x, y))
    visited = set()
    components = []
    for pt in sorted(dark):
        if pt in visited:
            continue
        comp = []
        q = deque([pt])
        visited.add(pt)
        while q:
            cx, cy = q.popleft()
            comp.append((cx, cy))
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if (nx, ny) in dark and (nx, ny) not in visited:
                    visited.add((nx, ny))
                    q.append((nx, ny))
        components.append(comp)
    return components


class IconOpticsTest(unittest.TestCase):
    def test_ro_svg_eye_aspect_ratio_and_capsule_curvature(self):
        tree = ET.parse(RO_SVG)
        root = tree.getroot()
        rects = [el for el in root.iter() if el.tag.endswith("rect")]
        eye_rects = [
            r for r in rects
            if r.attrib.get("fill", "").upper() == "#1A1917"
            and float(r.attrib.get("width", "0")) < 200
        ]
        self.assertEqual(len(eye_rects), 2, "ro.svg에는 두 눈이 있어야 합니다")
        for r in eye_rects:
            w = float(r.attrib["width"])
            h = float(r.attrib["height"])
            rx = float(r.attrib.get("rx", "0"))
            ratio = h / w
            self.assertGreaterEqual(ratio, 1.15, f"ro.svg 눈 종횡비 과소: {ratio:.3f}")
            self.assertLessEqual(ratio, 1.55, f"ro.svg 눈 종횡비 과대: {ratio:.3f}")
            self.assertAlmostEqual(rx, w / 2, places=1, msg="ro.svg 눈은 완전한 캡슐(rx=width/2)이어야 합니다")
        # 왼눈이 오른눈보다 약간 큰 비대칭 개성 유지 확인
        w_left, h_left = float(eye_rects[0].attrib["width"]), float(eye_rects[0].attrib["height"])
        w_right, h_right = float(eye_rects[1].attrib["width"]), float(eye_rects[1].attrib["height"])
        self.assertGreater(w_left, w_right)
        self.assertGreater(h_left, h_right)

    def test_all_multi_resolution_pngs_exist_and_separate_two_eyes_at_16_32_64(self):
        for s in SIZES:
            png = ROOT / f"assets/icon/ro-{s}.png"
            self.assertTrue(png.is_file(), f"누락된 아이콘 PNG: {png.name}")
            w, h = png_dimensions(png)
            self.assertEqual((w, h), (s, s), f"{png.name} 해상도 불일치")
            if s in (16, 32, 64):
                _, _, rows = decode_png_rgba(png)
                # ro.svg 머리 안 눈 영역: x 42%~76%, y 41%~59%
                comps = detect_eye_components(rows, (0.42, 0.76), (0.41, 0.59), lum_threshold=0.62)
                self.assertEqual(
                    len(comps), 2,
                    f"ro-{s}.png 에서 두 눈 분리 성분이 2개가 아닙니다: 검출={len(comps)}개 ({comps})"
                )
                # 왼눈이 오른눈의 왼쪽에 위치하고 둘 사이 최소 1px 간격 보장
                left_xs = [x for x, _ in comps[0]]
                right_xs = [x for x, _ in comps[1]]
                self.assertLess(max(left_xs), min(right_xs), f"ro-{s}.png 두 눈의 가로 분리가 부족합니다")

    def test_ro_icns_is_valid_and_unpacks_all_standard_iconset_sizes(self):
        self.assertTrue(RO_ICNS.is_file(), "assets/icon/ro.icns 파일이 없습니다")
        raw = RO_ICNS.read_bytes()
        self.assertEqual(raw[:4], b"icns", "ro.icns 매직 헤더 불일치")
        total_len = struct.unpack(">I", raw[4:8])[0]
        self.assertEqual(total_len, len(raw), "ro.icns 헤더 길이와 실제 파일 크기 불일치")
        if shutil.which("iconutil"):
            with tempfile.TemporaryDirectory() as tmp:
                iconset = Path(tmp) / "unpacked.iconset"
                r = subprocess.run(["iconutil", "--convert", "iconset", str(RO_ICNS), "--output", str(iconset)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                expected = {
                    "icon_16x16.png", "icon_16x16@2x.png",
                    "icon_32x32.png", "icon_32x32@2x.png",
                    "icon_128x128.png", "icon_128x128@2x.png",
                    "icon_256x256.png", "icon_256x256@2x.png",
                    "icon_512x512.png", "icon_512x512@2x.png",
                }
                self.assertTrue(expected.issubset({p.name for p in iconset.iterdir()}))

    def test_menubar_template_icon_eye_optics_at_1x_and_2x(self):
        import math
        import re

        swift = (ROOT / "ro/pet_mac.swift").read_text(encoding="utf-8")
        self.assertIn("let er = min(e.width / 2, e.height / 2)", swift)
        matches = re.findall(
            r"NSRect\(x:\s*hd\.minX\s*\+\s*([0-9.]+),\s*y:\s*hd\.minY\s*\+\s*hd\.height\s*\*\s*([0-9.]+),\s*width:\s*([0-9.]+),\s*height:\s*hd\.height\s*\*\s*([0-9.]+)\)",
            swift,
        )
        self.assertEqual(len(matches), 2, f"pet_mac.swift makeIcon 기본 눈 2개 정의가 필요합니다: {matches}")
        head_h = 5.0
        for px in (1.0, 2.0):
            snapped = []
            for x_off, y_k, w_pt, h_k in matches:
                raw_w = float(w_pt)
                raw_h = head_h * float(h_k)
                w = max(1.0 / px, round(raw_w * px) / px)
                h = max(1.0 / px, math.floor(raw_h * px) / px)
                snapped.append((w * px, h * px, h / w))
            if px == 2.0:
                for w_px, h_px, ratio in snapped:
                    self.assertGreaterEqual(ratio, 1.15, f"2x 메뉴바 아이콘 눈 종횡비 과소: {ratio:.3f}")
                    self.assertLessEqual(ratio, 1.55, f"2x 메뉴바 아이콘 눈 종횡비 과대: {ratio:.3f}")
            else:
                for w_px, h_px, _ in snapped:
                    self.assertGreaterEqual(h_px, 2.0, "1x 메뉴바 아이콘에서 눈이 1×1 점으로 뭉개지면 안 됩니다")


if __name__ == "__main__":
    unittest.main()
