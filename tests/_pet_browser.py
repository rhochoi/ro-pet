"""Playwright Chromium 런치 도우미 — CI 외 환경에서 브라우저 바이너리 미설치 시 명확히 건너뛴다."""
import os
import unittest


def _in_ci():
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


def launch_chromium(pw):
    """Playwright Chromium을 실행하고, 로컬 개발 환경에서 미설치 오류면 SkipTest를 발생시킨다."""
    try:
        return pw.chromium.launch()
    except Exception as exc:
        msg = str(exc)
        if not _in_ci() and (
            "Executable doesn't exist" in msg
            or "Please run the following command" in msg
        ):
            raise unittest.SkipTest("Playwright Chromium 브라우저 미설치") from exc
        raise
