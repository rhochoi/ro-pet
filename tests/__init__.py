"""테스트 공통 설정: AI 도구 연결(ro.engines)은 실제 ~/.claude·~/.codex·~/.gemini·~/.ro 대신 빈 임시 홈을 본다.
펫 서버를 띄우는 테스트도 시작할 때 연결 상태를 묻기 때문에 패키지 단위로 정한다."""
import atexit
import os
import shutil
import tempfile

from ro import engines

engines.HOME = tempfile.mkdtemp(prefix="ro-test-home-")
atexit.register(shutil.rmtree, engines.HOME, True)

# 펫의 기본 에디션은 V1 꾸미기("mini")다. 기능 테스트는 전체("pro") 에디션으로 돌리고,
# 꾸미기 에디션은 tests/test_pet_edition.py가 edition="mini"으로 따로 확인한다.
os.environ.setdefault("RO_EDITION", "pro")
