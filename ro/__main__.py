import sys

from .license import apply_edition_from_license

apply_edition_from_license()  # 번들 앱: 키로 에디션을 정한다(다른 모듈이 RO_EDITION을 읽기 전에)

from .cli import main  # noqa: E402

try:
    raise SystemExit(main())
except KeyboardInterrupt:
    print("중단했습니다.", file=sys.stderr)
    raise SystemExit(130)

