"""ro update / ro doctor: 설치 방식에 맞춰 업데이트하고 환경을 점검한다.

체크아웃(.git이 있는 저장소)이면 main 브랜치에 있을 때만 git pull --ff-only(작업 브랜치·worktree는 건드리지 않음), uv tool 설치본이면 uv tool upgrade, pipx 설치본이면 pipx upgrade.
사용자가 명령을 실행했을 때만 동작하며, 실행하는 명령을 먼저 출력한다.
"""
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE = "ro-pet"
OLD_PACKAGES = ("ro-bot", "rog-bot")  # 이전 패키지 이름. 이 이름의 설치본은 upgrade로 새 이름을 받지 못한다
ROOT = Path(__file__).resolve().parent.parent
TOOLS = ("claude", "agy")  # ro doctor가 설치 여부만 보는 도구
UPDATE_BRANCH = "main"


def _branch():
    """체크아웃의 현재 브랜치 이름. 분리된 HEAD·오류면 None."""
    try:
        p = subprocess.run(["git", "-C", str(ROOT), "symbolic-ref", "--quiet", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() or None


def update_command():
    """(명령, 설명). 자동 업데이트가 불가능하면 (None, 안내)."""
    if (ROOT / ".git").exists():
        branch = _branch()
        if branch != UPDATE_BRANCH:  # 작업 브랜치에 main을 당겨 오면 의도와 다른 곳이 바뀐다
            return None, (f"저장소 체크아웃이 {UPDATE_BRANCH}이 아닌 {branch or '분리된 HEAD'}에 있어 업데이트하지 않았습니다. "
                          f"{UPDATE_BRANCH} 체크아웃에서 `ro update`를 실행하거나 이 브랜치는 직접 git으로 갱신하세요.")
        return ["git", "-C", str(ROOT), "pull", "--ff-only"], "저장소 체크아웃(main)"
    if Path(sys.prefix).name in OLD_PACKAGES:  # uv(…/uv/tools/<pkg>)·pipx(…/venvs/<pkg>) 모두 설치 폴더 이름이 패키지 이름
        old_name = Path(sys.prefix).name
        return None, (f"패키지 이름이 {old_name}에서 {PACKAGE}로 바뀌어 자동 업데이트할 수 없습니다. "
                      "README의 설치 한 줄(install.sh)을 다시 실행하면 이전 설치를 지우고 새 이름으로 설치합니다"
                      "(~/.ro 기록은 그대로).")
    if "/uv/tools/" in sys.prefix and shutil.which("uv"):
        return ["uv", "tool", "upgrade", PACKAGE], "uv tool 설치본"
    if shutil.which("pipx"):
        return ["pipx", "upgrade", PACKAGE], "pipx 설치본"
    return None, "uv·pipx 설치본을 찾지 못했습니다. 설치한 방식(uv tool·pipx·pip 등)으로 직접 업그레이드하세요."


def update(runner=subprocess.run):
    cmd, why = update_command()
    if cmd is None:
        print(why)
        return 1
    print(f"{why}: {' '.join(cmd)}", flush=True)  # 하위 명령 출력보다 먼저 보이게
    return runner(cmd).returncode


def doctor(app_dirs=None):
    from . import engines, handoff   # 갈아타기·connect와 같은 도구 기준(/Applications/*.app 포함)
    print(f"python {sys.version.split()[0]}")
    app_dirs = engines.APP_DIRS if app_dirs is None else app_dirs
    by_id = {entry["id"]: entry for entry in engines.ENGINES}
    missing = 0
    for e in TOOLS:
        entry = by_id.get(e, {})
        found = shutil.which(entry.get("cli", e)) or engines._find_app(entry.get("apps", ()), app_dirs)
        missing += not found
        print(f"- {e}: {found or '미설치'}")
    words = {"ok": "읽기 정상", "partial": "일부만 읽음 — 형식이 바뀌었을 수 있어요", "unreadable": "형식을 못 읽음 — ro update 필요"}
    for eid, state in handoff.check():
        print(f"- 갈아타기 기록({handoff.NAMES[eid]}): {words[state]}")
    return 0 if missing < len(TOOLS) else 1
