"""ro pro 먼저 다가가기 배선: 상황(scenarios)을 보고 펫의 nudge()로 알리고, 수락하면 확인 카드(staging)를 연다.

pet.PetRuntime이 pro일 때만 만든다. 주기 확인은 tick()(펫이 30초마다 부름), 앞 창 문서는 on_ax()로 받는다.
같은 대상은 한 번만 알린다(메모리). 파일을 옮기는 일은 모두 staging 카드에서 사용자가 고른 것만 한다.
"""
import os
import subprocess
import threading
import time
from pathlib import Path

from . import config, mapper, organize, profile, scenarios, staging, storage, tact

TICK = 30
INSTALL_EVERY = 5 * 60
DISK_EVERY = 10 * 60
WAIT_FOR_PAUSE = 10 * 60   # 입력 중이면 이만큼은 다음 확인으로 미룬다(바로 1단계로 써 버리지 않게)


def _short(name, n=36):
    return name if len(name) <= n else name[:n - 1] + "…"


class ProWatch:
    def __init__(self, runtime, downloads="~/Downloads", runner=subprocess.run, free=scenarios.free_bytes):
        self.rt = runtime
        self.downloads = downloads
        self.runner = runner
        self.free = free
        self.stage = staging.Stage(runtime.home, runtime.log_dir, runner=runner)
        self.seek = scenarios.SeekWatch()
        self.context_watch = scenarios.ContextSwitchWatch()
        self.show = None                 # 펫 화면이 열어야 할 카드 id
        self._notice = (None, 0.0)       # 잠깐 보여 줄 결과 한 줄(문구, 끝나는 시각)
        self._seen = set()
        self._waiting = {}               # 대상 → 처음 알리려던 시각
        self._last = {"install": 0.0, "disk": 0.0, "disk_day": None}
        self._lock = threading.Lock()
        self.recovered = self._recover()
        runtime.nudge_handlers.update({
            "dmg_installed": self._on_installer,
            "disk_low": self._on_disk,
            "old_version": self._on_old_version,
            "find_lost": self._on_find_lost,
            "archive_unpacked": self._on_archive,
            "duplicate_found": self._on_duplicate,
            "download_burst": self._on_download_burst,
            "context_switch": self._on_context_switch,
        })

    def _ready(self, key, now):
        """주기 확인으로 찾은 것은 사용자가 잠깐 손을 뗄 때 알린다. 10분 넘게 바쁘면 그때는 1단계로 낸다."""
        first = self._waiting.setdefault(key, now)
        if self.rt.tact._busy(now) == "입력 중" and now - first < WAIT_FOR_PAUSE:
            return False
        self._waiting.pop(key, None)
        return True

    def _recover(self):
        """지난번에 끝나지 않은 배치(강제 종료·크래시)를 파일 상태를 보고 되돌린다. 펫이 시작할 때 한 번."""
        from . import journal, log
        try:
            res = journal.recover(self.rt.home)
        except Exception:   # 복구가 실패해도 펫은 뜬다. 다음 시작 때 다시 해 본다
            return []
        if res:
            log.append("journal_recover", f"끝나지 않은 배치 {len(res)}개 되돌림",
                       {"batches": len(res), "restored": sum(r[1] for r in res)}, log_dir=self.rt.log_dir)
            self.notice = f"지난번에 끝나지 않은 정리 {len(res)}건을 되돌렸어요"
        return res

    # ---- 감지 ----
    def tick(self, now=None):
        now = time.time() if now is None else now
        if not self.rt.tact.consented():
            return
        if self._waiting or now - self._last["install"] >= INSTALL_EVERY:
            self._last["install"] = now
            for it in scenarios.installed_installers(self.downloads, now=now):
                key = ("installer", it["path"])
                if key in self._seen:
                    continue
                if not self._ready(key, now):
                    break
                app = it["app"][:-4] if it["app"].endswith(".app") else it["app"]
                dec, _ = self.rt.nudge("dmg_installed", f"{_short(app, 24)} 앱이 설치돼 있어요 · {_short(Path(it['path']).name)} 남음",
                                       "설치 파일 격리", data={"path": it["path"]}, folder=self.downloads, now=now)
                if dec != tact.QUIET:
                    self._seen.add(key)
                break                     # 한 번에 하나만
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if (now - self._last["disk"] >= DISK_EVERY or ("disk", day) in self._waiting) and self._last["disk_day"] != day:
            self._last["disk"] = now
            free = self.free()
            if free < scenarios.DISK_LOW and self._ready(("disk", day), now):
                dec, _ = self.rt.nudge("disk_low", f"시동 디스크 남은 공간 {free / 1024 ** 3:.1f}GB", "정리 후보 보기",
                                       data={"free": free}, now=now)
                if dec != tact.QUIET:
                    self._last["disk_day"] = day
        # 다운로드 묶음 도착(TactGate.flush)
        for burst in self.rt.tact.flush(now=now):
            paths = burst.get("paths") or []
            if len(paths) < 2:
                continue
            key = ("burst", burst["folder"], len(paths), int(burst["last"]))
            if key in self._seen or not self._ready(key, now):
                continue
            dec, _ = self.rt.nudge("download_burst", f"다운로드에 새 파일 {len(paths)}개가 들어왔어요", "정리 후보 보기",
                                   data={"folder": burst["folder"], "paths": paths}, folder=burst["folder"], now=now)
            if dec != tact.QUIET:
                self._seen.add(key)
            break
        # 이미 풀린 압축 파일(.zip) 잔존
        for arc in scenarios.unpacked_archives(self.downloads, now=now):
            key = ("archive", arc["path"])
            if key in self._seen or not self._ready(key, now):
                continue
            dec, _ = self.rt.nudge("archive_unpacked",
                                   f"{_short(Path(arc['path']).name, 26)} 압축이 이미 풀려 있어요",
                                   "압축 원본 격리", data=arc, folder=self.downloads, now=now)
            if dec != tact.QUIET:
                self._seen.add(key)
            break
        # 다운로드 중복 사본 감지
        dups = [d for d in scenarios.duplicate_downloads(self.downloads, now=now) if ("dup", d["path"]) not in self._seen]
        if dups:
            key = ("dup", dups[0]["path"])
            if self._ready(key, now):
                dec, _ = self.rt.nudge("duplicate_found",
                                       f"다운로드에 중복 사본 {len(dups)}개가 있어요",
                                       "중복 정리 카드", data={"items": dups}, folder=self.downloads, now=now)
                if dec != tact.QUIET:
                    for d in dups:
                        self._seen.add(("dup", d["path"]))

    def on_front(self, app_name, now=None):
        """앞 앱 전환 시 AI 도구 간 작업 전환을 감지한다(비밀 앱은 TactGate가 이미 걸렀다)."""
        now = time.time() if now is None else now
        if not self.rt.tact.consented() or (self.rt.tact.front and self.rt.tact.front.get("private")):
            return None
        hit = self.context_watch.on_app(app_name, now=now)
        if not hit:
            return None
        return self.rt.nudge("context_switch",
                             f"{hit['from']}에서 {hit['to']}(으)로 도구를 바꿨어요",
                             "인수인계 보기", data=hit, now=now)

    def on_ax(self, ev, front_app, now=None):
        doc = ev.get("document")
        if not isinstance(doc, str) or not doc.startswith("/"):
            return None
        now = time.time() if now is None else now
        if not os.path.isdir(doc):
            self.stage.open_docs[doc] = now          # 열린 문서는 확인 카드에서 옮기지 않는다
        if not self.rt.tact.consented():
            return None
        if front_app == "Finder":
            if os.path.isdir(doc):
                hit = self.seek.on_folder(doc, now)
                if hit:
                    return self.rt.nudge("find_lost", f"2분 동안 폴더를 {hit['switches']}번 오가셨어요", "파일 찾기",
                                         data={}, folder=hit["last"], now=now)
            return None
        key = ("doc", doc)
        if key in self._seen:
            return None
        newer = scenarios.newer_version(doc)
        if newer:
            res = self.rt.nudge("old_version", f"같은 폴더에 더 새 판이 있어요 · {_short(Path(newer).name)}",
                                "새 판 보기", data={"path": newer}, now=now)
            if res and res[0] != tact.QUIET:
                self._seen.add(key)
            return res
        self._seen.add(key)
        return None

    # ---- 수락하면 ----
    def _on_installer(self, data, promoted=False):
        p = Path(data["path"])
        try:
            item = staging.item("quarantine", p, 0.95, "이름이 맞는 앱이 설치돼 있음", size=p.stat().st_size)
            cid = self.stage.open("installer", "dmg_installed", [item], [p.parent], "설치 파일 격리")
        except (staging.StageError, OSError) as e:
            self.notice = str(e)
            return
        if promoted:                     # ⌥R로 승격하면 바로 하지 않고 카드를 연다
            self.show = cid
            return
        try:                             # 1건 격리는 토스트 버튼 한 번으로 한다(저널로 되돌릴 수 있다)
            res = self.stage.apply(cid, [1], approve=True)
            self.notice = "설치 파일을 격리했어요 · 되돌리기는 카드에서" if res["moved"] else "격리하지 못했어요"
        except staging.StageError as e:
            self.notice = str(e)
        self.show = cid

    def _build_disk_card(self, trigger="disk_low"):
        items = []
        proj_roots = mapper.default_roots(self.rt.home)
        for b in storage.dead_builds(roots=proj_roots, budget=30.0):
            items.append(staging.item("quarantine", b["path"], 0.95,
                                      f"{b['project']} · {b['idle_days']}일 안 바뀜 · 다시 만들 수 있음", size=b["bytes"]))
        for it in scenarios.installed_installers(self.downloads):
            items.append(staging.item("quarantine", it["path"], 0.9, f"{it['app']} 설치됨", size=it["bytes"]))
        for it in scenarios.evict_candidates():
            items.append(staging.item("evict", it["path"], 0.75,
                                      f"{it['idle_days']}일 안 씀 · iCloud에 남고 이 Mac 사본만 내보냄", size=it["bytes"]))
        if not items:
            return None
        roots = {str(Path(it["path"]).parent) for it in items}
        return self.stage.open("disk", trigger, items, sorted(roots), "용량 정리 후보")

    def _on_disk(self, data, promoted=False):
        try:
            cid = self._build_disk_card("disk_low")
        except staging.StageError as e:
            self.notice = str(e)
            return
        if cid is None:
            self.notice = "지금 치울 만한 후보를 찾지 못했어요"
            return
        self.show = cid

    def _build_organize_card(self, root=None, dest_root=None):
        src_root = root or self.rt.organize_root
        dst_root = dest_root or self.rt.organize_dest
        plan = organize.scan(src_root, dst_root, home=self.rt.home)
        items, roots = [], {plan["root"], plan["dest_root"]}
        for it in plan["items"]:
            action = it.get("action", "move")
            if action == "keep":
                continue
            reason = (it.get("reasons") or ["분류"])[0]
            if action == "quarantine":
                conf = 0.75 if it.get("review") else 0.95
                items.append(staging.item("quarantine", it["path"], conf, reason, size=it.get("size")))
            elif action == "move":
                dst_p = Path(it["dest"])
                conf = 0.75 if it.get("review") else float(it.get("confidence", 0.75))
                items.append(staging.item("move", it["path"], conf, reason, dest=dst_p.parent,
                                          size=it.get("size"), dest_name=dst_p.name))
                if it.get("learned_dir"):
                    roots.add(str(Path(it["learned_dir"]).resolve()))
        if not items:
            return None
        # 허용 루트에 대상 상위 폴더가 실제 존재해야 Journal V2가 수락한다
        dest_root_p = Path(plan["dest_root"])
        dest_root_p.mkdir(parents=True, exist_ok=True)
        return self.stage.open("organize", "manual_organize", items, sorted(roots), "파일 정리 후보", proactive=False)

    def _on_old_version(self, data, promoted=False):
        self._reveal(data["path"])

    def _on_find_lost(self, data, promoted=False):
        self.rt.send_host({"cmd": "palette"})

    def _on_archive(self, data, promoted=False):
        """풀린 압축 원본은 승인 없이 옮기지 않고 확인 카드(staging)를 열어 사용자가 1-클릭 승인/되돌리기 하게 한다."""
        p = Path(data["path"])
        try:
            it = staging.item("quarantine", p, 0.95, "같은 이름의 폴더가 풀려 있음", size=p.stat().st_size)
            self.show = self.stage.open("archive", "archive_unpacked", [it], [p.parent], "압축 원본 격리")
        except (staging.StageError, OSError) as e:
            self.notice = str(e)

    def _on_duplicate(self, data, promoted=False):
        """중복 파일 묶음을 확인 카드(staging)로 열어 승인 전에는 파일을 건드리지 않는다."""
        raw_items = data.get("items") or ([data] if data.get("path") else [])
        items, roots = [], set()
        for d in raw_items:
            p = Path(d["path"])
            if not p.exists():
                continue
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            items.append(staging.item("quarantine", p, 0.95, "내용이 같은 중복 사본", size=sz))
            roots.add(str(p.parent))
        if not items:
            self.notice = "지금 치울 만한 후보를 찾지 못했어요"
            return
        try:
            self.show = self.stage.open("duplicate", "duplicate_found", items, sorted(roots), "중복 정리 카드")
        except staging.StageError as e:
            self.notice = str(e)

    def _on_download_burst(self, data, promoted=False):
        """다운로드 유입 묶음 정리: 확인 카드(staging)만 열고 승인 전에는 이동하지 않는다."""
        folder = data.get("folder") or self.downloads
        try:
            cid = self._build_organize_card(root=folder)
        except staging.StageError as e:
            self.notice = str(e)
            return
        if cid is None:
            self.notice = "지금 정리할 파일이 없어요"
            return
        self.show = cid

    def _on_context_switch(self, data, promoted=False):
        """AI 도구 전환 시 명령 팔레트를 열어 인수인계를 바로 확인하게 한다(쓰기 없음)."""
        self.rt.send_host({"cmd": "palette"})

    def _reveal(self, path):
        try:
            self.runner(["open", "-R", str(path)], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.notice = "Finder에서 보여 주지 못했어요"

    # ---- 펫 API ----
    def api(self, data):
        op = data.get("op")
        cid = str(data.get("id") or "")
        try:
            if op == "view":
                view = self.stage.view(cid)
                if view is None:
                    return {"ok": False, "error": "카드가 없거나 시간이 지났어요."}
                if self.show == cid:
                    self.show = None
                return {"ok": True, "card": view}
            if op == "apply":
                res = self.stage.apply(cid, data.get("picks"), data.get("approve") is True)
                return {"ok": True, "moved": len(res["moved"]), "evicted": len(res["evicted"]),
                        "skipped": [s[1] for s in res["skipped"]], "undo": bool(res["batch"])}
            if op == "disk":
                cid = self._build_disk_card("manual_disk")
                if cid is None:
                    return {"ok": False, "error": "지금 치울 만한 후보를 찾지 못했어요"}
                return {"ok": True, "card": self.stage.view(cid)}
            if op == "organize":
                cid = self._build_organize_card(data.get("root"), data.get("dest_root"))
                if cid is None:
                    return {"ok": False, "error": "지금 정리할 파일이 없어요"}
                return {"ok": True, "card": self.stage.view(cid)}
            if op == "hint_accept":
                with self.rt._lock:
                    hint = self.rt.hint
                    self.rt.hint = None
                if not hint:
                    return {"ok": False, "error": "지금 확인할 힌트가 없어요."}
                self.rt.tact.record(hint["trigger"], "accepted", level=1)
                handler = self.rt.nudge_handlers.get(hint["trigger"])
                if handler:
                    handler(hint.get("data") or {}, True)
                view = self.stage.view(self.show) if self.show else None
                if view is not None:
                    self.show = None
                return {"ok": True, "card": view, "notice": self.notice}
            if op == "hint_dismiss":
                with self.rt._lock:
                    self.rt.hint = None
                return {"ok": True}
            if op == "undo":
                res = self.stage.undo(cid)
                return {"ok": True, "restored": res["restored"], "files": res["files"], "skipped": len(res["skipped"])}
        except (staging.StageError, ValueError, OSError) as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "알 수 없는 요청이에요."}

    NOTICE_SECONDS = 20

    @property
    def notice(self):
        text, until = self._notice
        return text if time.time() < until else None

    @notice.setter
    def notice(self, text):
        self._notice = (text, time.time() + self.NOTICE_SECONDS)

    def snapshot(self):
        cfg = config.load(self.rt.home)
        return {"card": self.show, "notice": self.notice, "ax": self.rt.ax_trusted,
                "learning": cfg.get(profile.CONSENT) is True, "nudges": cfg.get("pro_nudges") is True}


def run_forever(watch, stop, every=TICK):
    while not stop.wait(every):
        try:
            watch.tick()
        except Exception:   # 감시 한 번 때문에 펫이 멈추지 않는다
            continue
