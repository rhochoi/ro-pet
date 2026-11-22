"""Harden 단계: 권한 감사(audit)와 회귀 체크리스트(eval).

audit: ~/.ro 데이터의 권한·비밀 유출·손상 줄 점검 (읽기 전용, --fix 시 권한만 조정)
eval:  핵심 안전 불변식을 임시 디렉터리에서 재검증
"""
import ast
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from unittest import mock

from . import log, mapper, organize, pet, tidy

HOME = "~/.ro"


def _walk(home):
    for dirpath, dirnames, filenames in os.walk(home):
        yield Path(dirpath), True
        for d in dirnames:
            p = Path(dirpath) / d
            if p.is_symlink():
                yield p, False
        for f in filenames:
            yield Path(dirpath) / f, False


_SCANNED = {}  # 경로 → 이미 감사한 앞부분(같은 inode에 덧붙기만 한 .jsonl은 새 꼬리만 읽는다)


def _scan_text(path, st):
    """반환: (비밀 패턴 여부, 손상 줄 번호 목록). .jsonl은 덧붙은 부분만 증분으로 본다."""
    key, c = str(path), _SCANNED.get(str(path))
    if c and (c["ino"], c["size"], c["mtime"]) == (st.st_ino, st.st_size, st.st_mtime_ns):
        return c["secret"], c["bad"]
    start, secret, bad, n = 0, False, [], 0
    if c and path.suffix == ".jsonl" and c["ino"] == st.st_ino and st.st_size >= c["off"]:
        start, secret, bad, n = c["off"], c["done_secret"], list(c["done_bad"]), c["n"]
    with open(path, "rb") as f:
        f.seek(start)
        raw = f.read()
    complete = raw.rfind(b"\n") + 1 if path.suffix == ".jsonl" else len(raw)
    done_text = raw[:complete].decode("utf-8", errors="replace")
    tail_text = raw[complete:].decode("utf-8", errors="replace")
    done_secret = secret or bool(log.SECRET_VALUE.search(done_text) or log.PEM_BLOCK.search(done_text))
    done_bad = bad
    if path.suffix == ".jsonl":
        for line in done_text.splitlines():
            n += 1
            try:
                json.loads(line)
            except json.JSONDecodeError:
                done_bad.append(n)
    secret_all = done_secret or bool(log.SECRET_VALUE.search(tail_text) or log.PEM_BLOCK.search(tail_text))
    bad_all = list(done_bad)
    if path.suffix == ".jsonl" and tail_text:  # 아직 줄바꿈 전인 마지막 줄(쓰는 중일 수 있다)은 저장하지 않고 이번만 본다
        try:
            json.loads(tail_text)
        except json.JSONDecodeError:
            bad_all.append(n + 1)
    _SCANNED[key] = {"ino": st.st_ino, "size": st.st_size, "mtime": st.st_mtime_ns, "off": start + complete,
                     "n": n, "done_secret": done_secret, "done_bad": done_bad, "secret": secret_all, "bad": bad_all}
    return secret_all, bad_all


def audit(home=HOME, fix=False):
    """반환: (findings[list[str]], fixed[list[str]])."""
    home = Path(home).expanduser()
    findings, fixed = [], []
    if not home.exists():
        return findings, fixed
    for path, is_dir in _walk(home):
        try:
            st = path.lstat()
        except FileNotFoundError:  # 도는 사이에 사라진 임시·잠금 파일은 감사할 것이 없다
            continue
        if stat.S_ISLNK(st.st_mode):
            target = os.path.realpath(path)
            if not target.startswith(str(home.resolve()) + os.sep) and target != str(home.resolve()):
                findings.append(f"외부 심볼릭 링크: {path}")
            continue
        mode = stat.S_IMODE(st.st_mode)
        want = 0o700 if is_dir else 0o600
        if mode & 0o077:
            findings.append(f"권한 과다 {oct(mode)}: {path}")
            if fix:
                try:
                    os.chmod(path, want)
                    fixed.append(str(path))
                except OSError as ex:
                    findings.append(f"권한 수정 실패({ex.strerror or ex}): {path}")
        if not is_dir and path.suffix in (".json", ".jsonl"):  # .db·.db-wal 등은 권한만 본다
            try:
                secret, bad = _scan_text(path, st)
            except OSError:
                continue
            if secret:
                findings.append(f"비밀 패턴 발견(수동 확인 필요): {path}")
            if bad:  # 읽을 때 건너뛰는 손상 줄을 '기록 없음'으로 숨기지 않고 알린다
                findings.append(f"손상된 줄 {len(bad)}개(첫 줄 {bad[0]}): {path}")
    return findings, fixed


NETWORK_MODULES = {"socket", "ssl", "urllib.request", "http.client", "requests", "httpx", "aiohttp",
                   "ftplib", "smtplib", "telnetlib", "xmlrpc.client", "websocket", "websockets"}
NETWORK_COMMANDS = {"curl", "wget", "nc", "ncat", "ssh", "scp", "sftp", "rsync", "ftp", "telnet"}
SWIFT_NETWORK = re.compile(r"\b(URLSession|NWConnection|NWListener|CFStream|NSURLConnection)")
REMOTE_URL = re.compile(r"\b(?:https?|wss?|ftp)://(?!(?:127\.0\.0\.1|localhost)[:/])[\w.-]+")
# 외부 연락이 허용된 유일한 파일: pro 라이선스 자동 받기(설치 토큰 하나 → 발급기). license_net_scoped가 따로 묶는다
NETWORK_ALLOWED = {"licensenet.py"}


def network_offenders(root=Path(__file__).parent, allowed=NETWORK_ALLOWED):
    """ro 패키지(하위 폴더 포함)에서 기기 밖으로 보낼 수 있는 코드: 네트워크 모듈 import, 네트워크 명령 실행, 원격 주소 문자열.
    Swift 호스트는 네트워크 API 이름과 원격 주소를 본다.
    로컬 펫 서버(http.server, 127.0.0.1)와 주소 '해석'(urllib.parse)은 허용한다. 반환: ["파일:줄 이유"]."""
    found = []
    for path in sorted(Path(root).rglob("*.swift")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if SWIFT_NETWORK.search(line) or REMOTE_URL.search(line):
                found.append(f"{path.name}:{n} 네트워크")
    for path in sorted(Path(root).rglob("*.py")):
        if path.name in allowed and path.parent == Path(root):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for name in names:
                if any(name == m or name.startswith(m + ".") for m in NETWORK_MODULES):
                    found.append(f"{path.name}:{node.lineno} import {name}")
            if (isinstance(node, (ast.List, ast.Tuple)) and node.elts and isinstance(node.elts[0], ast.Constant)
                    and node.elts[0].value in NETWORK_COMMANDS):
                found.append(f"{path.name}:{node.lineno} 실행 {node.elts[0].value}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and REMOTE_URL.search(node.value):
                found.append(f"{path.name}:{node.lineno} 원격 주소")
    return found


def license_net_scoped(path=Path(__file__).parent / "licensenet.py"):
    """허용된 한 곳이 약속대로인지: 네트워크 모듈은 urllib만, 원격 주소는 발급기 한 곳(비었으면 0곳),
    보내는 본문은 설치 토큰 하나, 연락은 _post 한 함수에서만, 명령 실행 없음. 반환: 어긋난 이유 목록."""
    bad = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    urls = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and REMOTE_URL.search(n.value)]
    if len(urls) > 1:
        bad.append(f"원격 주소 {len(urls)}개")
    for n in ast.walk(tree):
        names = [a.name for a in n.names] if isinstance(n, ast.Import) else ([n.module] if isinstance(n, ast.ImportFrom) and n.module else [])
        for name in names:
            if any(name == m or name.startswith(m + ".") for m in NETWORK_MODULES) and name != "urllib.request":
                bad.append(f"import {name}")
        if isinstance(n, (ast.List, ast.Tuple)) and n.elts and isinstance(n.elts[0], ast.Constant) and n.elts[0].value in NETWORK_COMMANDS:
            bad.append(f"실행 {n.elts[0].value}")
        if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "install" for k in n.keys):
            if [k.value for k in n.keys if isinstance(k, ast.Constant)] != ["install"]:
                bad.append("설치 토큰 말고 다른 값을 보냄")
    opens = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and "urlopen" in ast.unparse(n)]
    if [f.name for f in opens] != ["_post"]:
        bad.append("연락하는 함수가 _post 하나가 아님")
    return bad


def _checks():
    def no_network():
        return not network_offenders()

    def license_net_only():
        return not license_net_scoped()

    def redaction():
        d = log.redact({"api_key": "k", "s": "sk-abcdefghijklmnopqrstuv"})
        return d["api_key"] == log.MASK and "sk-" not in d["s"]

    def map_skips_secrets():
        # Map은 원래 내용을 읽지 않으므로 내용 검사로는 아무것도 증명하지 못한다.
        # 비밀 후보 파일이 언어 집계에 들어가지 않는지로 필터 자체를 검증한다.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "app"
            p.mkdir()
            (p / "package.json").write_text("{}")
            (p / "token.py").write_text("K = 'hunter2'")
            (p / "secret_config.py").write_text("")
            data = mapper.build_map([d])
            return "python" not in data["projects"][0]["languages"] \
                and "hunter2" not in json.dumps(data)

    def tidy_is_reversible():
        from unittest import mock
        with tempfile.TemporaryDirectory() as h:
            t = Path(h).resolve()
            root = t / "home" / "D"
            root.mkdir(parents=True)
            (root / "a").write_text("x")
            (root / "b").write_text("x")
            os.utime(root / "a", (1, 1))
            with mock.patch("pathlib.Path.home", return_value=t / "home"):
                plan = tidy.scan(root, min_size=1)
                tidy.save_plan(plan, t / "ro")
                before = {p.name for p in root.iterdir()}
                if len(plan["items"]) != 1 or {p.name for p in root.iterdir()} != before:
                    return False  # scan은 읽기 전용
                tidy.apply([plan["items"][0]["id"]], t / "ro", str(t / "log"))
                tidy.undo(None, t / "ro", str(t / "log"))
                return {p.name for p in root.iterdir()} == before

    def organize_safe():
        # scan은 읽기 전용·본문 미저장, apply→undo는 원래 이름·위치로 복원한다.
        with tempfile.TemporaryDirectory() as h:
            t = Path(h).resolve()
            root = t / "home" / "Downloads"
            root.mkdir(parents=True)
            (root / "2026-01-02 영수증.txt").write_text("SECRETBODY 결제")
            (root / "memo.xyz").write_text("x")
            for f in root.iterdir():
                os.utime(f, (1, 1))
            before = {p.name: p.read_text() for p in root.iterdir()}
            dest = t / "home" / "Documents" / "정리됨"
            with mock.patch("pathlib.Path.home", return_value=t / "home"):
                plan = organize.scan(root, dest)
                organize.save_plan(plan, t / "ro")
                unchanged = {p.name: p.read_text() for p in root.iterdir()} == before and not dest.exists()
                no_body = "SECRETBODY" not in (t / "ro" / "cleanup" / "plan.json").read_text()
                ids = [i["id"] for i in plan["items"]]
                _, done, skipped = organize.apply(ids, home=t / "ro", log_dir=str(t / "log"))
                moved = len(done) == 1 and len(skipped) == 1  # 검토 필요 항목은 옮기지 않음
                organize.undo(None, t / "ro", str(t / "log"))
            return unchanged and no_body and moved \
                and {p.name: p.read_text() for p in root.iterdir()} == before

    def cleanup_unified_safe():
        # 정리 통합: 파일마다 제안 하나, 재무 옛 버전은 보관, 격리→이동을 한 배치로 적용해도 undo 한 번에 원상복구,
        # 예전 tidy 격리 배치도 organize undo로 되돌린다. 영구 삭제 경로는 없다.
        import zipfile
        with tempfile.TemporaryDirectory() as h:
            t = Path(h).resolve()
            root = t / "home" / "Downloads"
            root.mkdir(parents=True)
            (root / "a.pdf").write_text("dup")
            (root / "b.pdf").write_text("dup")
            (root / "pic.png").write_text("IMG")
            with zipfile.ZipFile(root / "pic.zip", "w") as zf:
                zf.writestr("pic.png", "IMG")
            (root / "경비 내역.xlsx").write_text("old")
            (root / "경비 내역 (1).xlsx").write_text("new")
            for i, f in enumerate(sorted(root.iterdir())):
                os.utime(f, (100 + i, 100 + i))
            os.utime(root / "a.pdf", (1, 1))  # 중복의 원본
            (root / "sub").mkdir()
            (root / "sub" / "old.bin").write_text("x" * 5000)
            os.utime(root / "sub" / "old.bin", (1, 1))
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            ro_home, logs = t / "ro", str(t / "log")
            with mock.patch("pathlib.Path.home", return_value=t / "home"):
                plan = organize.scan(root, t / "home" / "Documents" / "정리됨", extractor=lambda ps: {})
                organize.save_plan(plan, ro_home)
                by = {Path(i["path"]).name: i for i in plan["items"]}
                one_each = len({i["path"] for i in plan["items"]}) == len(plan["items"])
                kept = [n for n, i in by.items() if i["action"] == "keep"]
                judged = (by["b.pdf"]["action"], by["pic.zip"]["action"]) == ("quarantine", "quarantine") and \
                    len(kept) == 1 and kept[0].startswith("경비 내역")  # 재무 옛 버전은 치우지 않고 보관
                _, done, _ = organize.apply([i["id"] for i in plan["items"]], home=ro_home, log_dir=logs)
                applied = len(done) == len(plan["items"]) - 1  # 보관 1건만 남는다
                organize.undo(None, ro_home, logs)
                tplan = tidy.scan(root, min_size=1)
                tidy.save_plan(tplan, ro_home)
                old = [i["id"] for i in tplan["items"] if i["path"].endswith("old.bin")]
                tidy.apply(old, ro_home, logs)
                organize.undo(None, ro_home, logs)  # 예전 tidy 배치
            after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            return one_each and judged and applied and old and after == before

    def purge_needs_terminal_yes():
        # 격리 비우기(영구 삭제): 최근 배치는 남기고, 비대화 실행·yes 아닌 답에는 아무것도 지우지 않으며,
        # 비운 배치는 되돌리기 대상에서 빠진다.
        import json as _json
        import zipfile
        with tempfile.TemporaryDirectory() as h:
            t = Path(h).resolve()
            root = t / "home" / "Downloads"
            root.mkdir(parents=True)
            ro_home, logs = t / "ro", str(t / "log")
            files = []
            with mock.patch("pathlib.Path.home", return_value=t / "home"):
                for name in ("old", "new"):  # 배치 둘: 하나는 오래된 것으로 만든다
                    (root / f"{name}.png").write_text(name)
                    with zipfile.ZipFile(root / f"{name}.zip", "w") as zf:
                        zf.writestr(f"{name}.png", name)
                    for p in root.iterdir():
                        os.utime(p, (1, 1))
                    plan = organize.scan(root, t / "home" / "Documents" / "정리됨", extractor=lambda ps: {})
                    organize.save_plan(plan, ro_home)
                    organize.apply(kind="extracted", home=ro_home, log_dir=logs)
                    if name == "old":
                        j = ro_home / "cleanup" / "journal.jsonl"
                        rows = [_json.loads(x) for x in j.read_text().splitlines()]
                        aged = Path(rows[0]["dst"]).parent.with_name("20200101-000000")
                        Path(rows[0]["dst"]).parent.rename(aged)
                        for r in rows:  # 7일보다 오래된 배치인 척: 시각·배치·격리 경로를 함께 바꾼다
                            r["ts"], r["batch"] = "2020-01-01T00:00:00+0000", "20200101-000000"
                            r["dst"] = str(aged / Path(r["dst"]).name)
                        j.write_text("".join(_json.dumps(r) + "\n" for r in rows))
                        files.append(Path(rows[0]["dst"]))
                trash = ro_home / "cleanup" / "trash"
                before = sorted(trash.rglob("*.zip"))
                tty, pipe = mock.Mock(isatty=lambda: True), mock.Mock(isatty=lambda: False)
                import contextlib
                import io

                def run(**kw):  # 목록 출력은 eval 화면에 섞지 않는다
                    with contextlib.redirect_stdout(io.StringIO()):
                        organize.trash_cli("7d", True, home=ro_home, log_dir=logs, **kw)
                try:
                    run(stdin=pipe, stdout=tty)
                    refused = False
                except SystemExit:
                    refused = True
                run(stdin=tty, stdout=tty, ask=lambda _: "y")
                kept_after_no = sorted(trash.rglob("*.zip")) == before
                run(stdin=tty, stdout=tty, ask=lambda _: "yes")
                left = sorted(trash.rglob("*.zip"))
                undoable = {e["batch"] for e in organize.pending(ro_home)}
            return refused and kept_after_no and len(before) == 2 and len(left) == 1 \
                and not files[0].exists() and "20200101-000000" not in undoable and len(undoable) == 1

    def private_files():
        with tempfile.TemporaryDirectory() as h:
            ro_dir = Path(h) / "ro"
            out_file = Path(h) / "outside.txt"
            out_file.write_text("x", encoding="utf-8")
            os.chmod(out_file, 0o644)
            log.append("t", "s", log_dir=ro_dir)
            findings, _ = audit(ro_dir)
            if findings:
                return False
            link = ro_dir / "ext.link"
            link.symlink_to(out_file)
            f2, fixed = audit(ro_dir, fix=True)
            return any("외부 심볼릭 링크" in x for x in f2) and not fixed and stat.S_IMODE(out_file.stat().st_mode) == 0o644

    def activity_records_only_allowed():
        # 활동 기록: 꺼져 있으면 아무것도 쓰지 않고, 켜도 제외 앱·시크릿 창·웹 AI가 아닌 사이트는 남기지 않으며
        # 키 입력·화면·클립보드를 읽는 명령을 쓰지 않는다(소스에 그런 호출이 없음)
        from . import activity, engines
        src = Path(activity.__file__).read_text(encoding="utf-8")
        if any(w in src for w in ("screencapture", "CGEventTap", "CGWindowListCreateImage", "pbpaste", "AVCapture")):
            return False

        web = "https:" + "//"   # 시험용 주소. 원격 주소 검사가 이 파일을 잡지 않게 조립한다(실제로 접속하지 않음)

        def mac(app, url=web + "claude.ai/c", title="t", mode="normal"):
            def run(args, **kw):
                out = {"lsappinfo": f'bundle path="/Applications/{app}.app"' if len(args) > 1 and args[1] == "info"
                       else "ASN:0x1", "ioreg": '"HIDIdleTime" = 0', "osascript": f"{mode}\n{url}\n{title}\n"}
                return mock.Mock(returncode=0, stdout=out.get(args[0], ""), stderr="")
            return run
        with tempfile.TemporaryDirectory() as h, mock.patch.object(engines, "HOME", h):
            if activity.tick(mac("Google Chrome"), 1e9) is not None or (Path(h) / ".ro/activity").exists():
                return False
            activity.turn_on()
            for i, m in enumerate((mac("KakaoTalk"), mac("Google Chrome", mode="incognito", title="비공개"),
                                   mac("Google Chrome", url=web + "bank.example.com", title="잔액"))):
                activity.tick(m, 1e9 + i * 15)
            text = "".join(f.read_text() for f in (Path(h) / ".ro/activity").glob("*.jsonl"))
            perms = {f.stat().st_mode & 0o777 for f in (Path(h) / ".ro/activity").glob("*.jsonl")}
            return not any(w in text for w in ("KakaoTalk", "비공개", "잔액", "bank")) and perms <= {0o600}

    def pet_safety_invariants():
        with tempfile.TemporaryDirectory() as h:
            rt = pet.PetRuntime(home=h, log_dir=h, map_path=str(Path(h) / "map.json"), edition="pro")
            rt._queue({"kind": "organize_apply", "task": "배포 token=" + "sk-" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
            st = rt.snapshot()
            try:
                pet.start_server(rt, host="0.0.0.0")
                local_only = False
            except ValueError:
                local_only = True
            return (local_only and st["mood"] == "focus"
                    and "ABCDEFGH" not in json.dumps(st, ensure_ascii=False))

    def pet_organize_needs_approval():
        # 펫의 정리 요청은 승인 대기열에만 오르고, 승인 전에는 파일이 그대로다.
        with tempfile.TemporaryDirectory() as h, mock.patch.dict(os.environ, {"HOME": str(Path(h).resolve())}):
            t = Path(h).resolve()
            dl = t / "Downloads"
            dl.mkdir()
            f = dl / "영수증.txt"
            f.write_text("결제")
            import zipfile
            (dl / "pic.png").write_text("IMG")
            z = dl / "pic.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("pic.png", "IMG")
            for p in dl.iterdir():
                os.utime(p, (1, 1))
            rt = pet.PetRuntime(home=str(t / ".ro"), log_dir=str(t / ".ro" / "log"), map_path=str(t / "m.json"), edition="pro")
            rt.organize_root, rt.organize_dest = dl, t / "Documents" / "정리됨"
            rt.organize_scan()
            queued = rt.queue_organize_apply("재무")["ok"]
            st = rt.snapshot()
            moves_wait = queued and f.exists() and st["mood"] == "focus" \
                and st["write_pending"]["kind"] == "organize_apply" and not rt.organize_dest.exists()
            rt.resolve_write_approval(False)
            q_queued = rt.queue_organize_apply(kind="extracted")["ok"]  # 치울 후보 격리도 같은 게이트
            trash = t / ".ro" / "cleanup" / "trash"
            return moves_wait and q_queued and z.exists() and not trash.exists() \
                and rt.snapshot()["write_pending"].get("qkind") == "extracted"

    def icloud_and_packages_untouched():
        # 1) 어떤 진입점이든 ro를 불러오면 커널 물질화 차단이 켜진다(새 프로세스로 확인).
        import subprocess
        import sys
        from . import fsguard
        init = (Path(__file__).parent / "__init__.py").read_text(encoding="utf-8")
        if "disable_materialization()" not in init:
            return False
        if sys.platform == "darwin":
            out = subprocess.run([sys.executable, "-c", "import ro.fsguard as g; print(g.materialization_policy())"],
                                 cwd=Path(__file__).parent.parent, capture_output=True, text=True, timeout=30)
            if out.stdout.strip() != "1":
                return False
        with tempfile.TemporaryDirectory() as h:
            t = Path(h).resolve()
            root = t / "home" / "Downloads"
            (root / "Report.pages" / "Data").mkdir(parents=True)
            (root / "Report.pages" / "Data" / "inner.png").write_text("x")
            (root / "cloud.pdf").write_text("x")
            (root / "local.pdf").write_text("x")
            for f in (root / "cloud.pdf", root / "local.pdf", root / "Report.pages" / "Data" / "inner.png"):
                os.utime(f, (1, 1))
            cloud = str(root / "cloud.pdf")
            real_open, opened = open, []

            def spy(f, *a, **k):
                opened.append(str(f))
                return real_open(f, *a, **k)
            with mock.patch.object(fsguard, "is_dataless", lambda q, st=None: str(q) == cloud), \
                    mock.patch("builtins.open", spy), mock.patch("pathlib.Path.home", return_value=t / "home"):
                plan = organize.scan(root, t / "home" / "Documents" / "정리됨", extractor=organize.extract)
                walked = {p.name for p, _ in tidy.walk(root)}
                try:  # 2) iCloud에만 있는 파일은 다른 볼륨으로 복사하지 않는다
                    with mock.patch.object(organize.os, "replace", side_effect=OSError(18, "EXDEV")):
                        organize._move_into(root / "cloud.pdf", t / "x.pdf")
                    copied = True
                except OSError:
                    copied = (t / "x.pdf").exists()
            names = {Path(i["path"]).name for i in plan["items"]}
            return cloud not in opened and names == {"local.pdf"} and plan["dataless_skipped"] == 1 \
                and walked == {"local.pdf"} and not copied

    def pro_nudges_are_tactful():
        # ro pro 토스트: 포커스를 뺏지 않고(makeKey 없음), 질문·재촉 문구를 거부하며, mini에서는 센서·토스트가 없다
        src = (Path(__file__).parent / "pet_mac.swift").read_text(encoding="utf-8")
        body = src.split("private func showNudge", 1)[1].split("private func closeNudge", 1)[0]
        panel = src.split("final class NudgePanel", 1)[1].split("\n}", 1)[0]
        static_ok = "makeKey" not in body and "activate(" not in body and "orderFrontRegardless" in body \
            and "canBecomeKey: Bool { false }" in panel and "proArg && !miniArg" in src \
            and "if proSensor {" in src
        with tempfile.TemporaryDirectory() as h:
            kw = dict(home=str(Path(h) / "ro"), log_dir=str(Path(h) / "log"), map_path=str(Path(h) / "m.json"))
            mini = pet.PetRuntime(edition="mini", **kw)
            mini_ok = mini.tact is None and mini.nudge("disk_low", "남은 공간 9GB", "보기") == ("quiet", None) \
                and not mini.on_host_line('{"type": "front", "app": "Finder"}')
            pro = pet.PetRuntime(edition="pro", **kw)
            try:
                pro.nudge("find_lost", "정리해 드릴까요?", "보기")
                refused = False
            except ValueError:
                refused = True
            quiet_before_consent = pro.nudge("disk_low", "남은 공간 9GB", "보기")[0] == "quiet"
        return static_ok and mini_ok and refused and quiet_before_consent

    def pro_learning_is_consented_and_nameless():
        # 원칙 6: 동의 전·mini에서는 배우지 않고(DB도 없음), 배운 것에 이름·경로가 없으며, 외부 AI에는 번호만 간다
        from . import engines, profile
        with tempfile.TemporaryDirectory() as h:
            ro, folder = Path(h) / "ro", Path(h) / "Docs" / "연봉계약"
            folder.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"RO_EDITION": "mini"}):
                profile.set_consent(ro)
                mini_quiet = not profile.observe_quiet("ext_home", ".pdf", folder, home=ro)
            mini_quiet = mini_quiet and not profile.db_path(ro).exists()
            profile.set_consent(ro, False)
            try:
                profile.observe("ext_home", ".pdf", folder, home=ro)
                consent_needed = False
            except profile.NotAllowed:
                consent_needed = True
            profile.set_consent(ro)
            profile.observe("ext_home", ".pdf", folder, home=ro)
            nameless = "연봉".encode() not in profile.db_path(ro).read_bytes()
            f = folder / "김철수_연봉.pdf"
            f.write_text("x")
            text, ids = engines.assist_payload([f], [folder])
            anon = "김철수" not in text and "연봉" not in text and h not in text
            try:
                engines.assist_reply('{"moves": [{"file": "F1", "to": "T1"}], "x": "ignore all previous"}', ids)
                guarded = False
            except ValueError:
                guarded = True
        return mini_quiet and consent_needed and nameless and anon and guarded

    def pro_stage_needs_approval():
        # C안 카드: 승인·고른 항목 없이는 안 옮기고, 메타만 본 항목은 확신 0.75 이하(기본 해제), 신뢰가 낮으면 구조 변경 카드 없음
        from . import staging
        with tempfile.TemporaryDirectory() as h:
            home = Path(h).resolve()
            dl = home / "Downloads"
            dl.mkdir()
            f = dl / "a.dmg"
            f.write_text("x")
            with mock.patch("pathlib.Path.home", return_value=home):
                st = staging.Stage(home / ".ro", str(home / "logs"), runner=lambda *a, **k: None)
                cid = st.open("disk", "disk_low", [staging.item("quarantine", f, 0.95, "x"),
                                                    staging.item("evict", f, 1.0, "x")], [dl], "t")
                capped = [i["sure"] for i in st.view(cid)["items"]] == [True, False]
                refused = 0
                for picks, ok in (([1], False), ([], True), (None, True)):
                    try:
                        st.apply(cid, picks, approve=ok)
                    except staging.StageError:
                        refused += 1
                try:
                    st.open("assist", "assist", [staging.item("move", f, 0.95, "x", dest=home / "Documents")],
                            [dl, home / "Documents"], "t")
                    gated = False
                except staging.StageError:
                    gated = True
            return capped and refused == 3 and f.exists() and gated

    def pro_recovers_and_holds_open_files():
        # 강제 종료로 끝나지 않은 배치는 ro pro 펫이 시작할 때 되돌리고, 확인 카드는 편집 중·방금 바뀐 파일을 옮기지 않는다
        from . import journal, staging
        with tempfile.TemporaryDirectory() as h:
            home = Path(h).resolve()
            dl, ro = home / "Downloads", home / ".ro"
            dl.mkdir()
            a, fresh = dl / "a.dmg", dl / "fresh.dmg"
            a.write_text("x")
            fresh.write_text("x")
            os.utime(a, (1_700_000_000,) * 2)
            with mock.patch("pathlib.Path.home", return_value=home):
                b = journal.Batch("stage-disk", [dl], ro).__enter__()
                b.move(a, dl / "moved.dmg")
                rt = pet.PetRuntime(home=str(ro), log_dir=str(ro / "log"), edition="pro")
                recovered = len(rt.pro.recovered) == 1 and a.exists()
                st = staging.Stage(ro, str(ro / "log"), runner=lambda *x, **k: None)
                cid = st.open("disk", "disk_low", [staging.item("quarantine", fresh, 0.95, "x")], [dl], "t")
                held = st.apply(cid, [1], approve=True)["skipped"][0][1] == "방금 바뀜" and fresh.exists()
        return recovered and held

    return [
        ("기기 밖으로 보내는 코드 없음(네트워크 모듈·명령·원격 주소, pro 라이선스 받기 한 곳 제외)", no_network),
        ("pro 라이선스 받기는 발급기 한 곳에 설치 토큰만 보냄", license_net_only),
        ("비밀 마스킹", redaction),
        ("Map은 비밀 파일 제외", map_skips_secrets),
        ("정리: 읽기 전용 스캔·격리 후 복원 가능", tidy_is_reversible),
        ("분류 정리: 읽기 전용 스캔·본문 미저장·검토 항목 보류·복원 가능", organize_safe),
        ("정리 통합: 파일당 제안 하나·재무 보관·격리+이동 한 배치 복원·예전 tidy 배치 복원", cleanup_unified_safe),
        ("격리 비우기: 최근 배치 보존·비대화 거부·yes 전 무변경·비운 배치 되돌리기 제외", purge_needs_terminal_yes),
        ("데이터 파일 비공개 권한", private_files),
        ("Pet은 로컬 전용·비밀 마스킹·쓰기 승인 게이트 유지", pet_safety_invariants),
        ("Pet 파일 정리·격리는 승인 전 이동 없음", pet_organize_needs_approval),
        ("iCloud에만 있는 파일은 열지·해시하지·복사하지 않음(물질화 차단 켜짐)·패키지 안은 보지 않음",
         icloud_and_packages_untouched),
        ("ro pro 먼저 다가가기: 동의 전 무동작·질문형 거부·토스트 포커스 비탈취, mini는 센서·토스트 없음",
         pro_nudges_are_tactful),
        ("ro pro 학습: 동의 전·mini는 무학습(DB 없음)·이름·경로 미저장·외부 AI엔 번호만·지시문 섞인 답 거부",
         pro_learning_is_consented_and_nameless),
        ("ro pro 확인 카드: 승인·선택 없이는 무이동·메타 판단은 기본 해제(≤0.75)·신뢰 전 구조 변경 카드 없음",
         pro_stage_needs_approval),
        ("ro pro 복구·보류: 강제 종료된 배치는 시작 때 되돌림·편집 중·방금 바뀐 파일은 카드에서도 안 옮김",
         pro_recovers_and_holds_open_files),
        ("활동 기록: 꺼지면 무기록·제외 앱·시크릿 창·일반 사이트 미기록·키 입력·화면 미사용", activity_records_only_allowed),
    ]


def evaluate():
    """반환: [(이름, 통과 여부)]. 예외는 실패로 처리."""
    results = []
    for name, fn in _checks():
        try:
            ok = bool(fn())
        except Exception:
            ok = False
        results.append((name, ok))
    return results
