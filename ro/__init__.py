"""ro: 도구에 종속되지 않는 하나의 캐릭터."""
from . import fsguard as _fsguard

# 어떤 진입점(ro CLI·펫·python -m ro.*)이든 iCloud 파일을 몰래 내려받지 않게 프로세스 시작 때 막는다.
_fsguard.disable_materialization()
