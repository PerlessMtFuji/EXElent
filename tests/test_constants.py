import re

from exelent import constants


def test_versions_are_exact_pins():
    assert re.fullmatch(r"\d+\.\d+\.\d+", constants.UV_VERSION)
    assert re.fullmatch(r"pyinstaller==\d+\.\d+(\.\d+)?", constants.PYINSTALLER_SPEC)


def test_target_python_is_not_latest():
    assert constants.TARGET_PYTHON == "3.12"


def test_scan_limits_match_spec():
    assert constants.MAX_SCAN_FILES == 3000
    assert constants.MAX_SCAN_BYTES == 500 * 1024 * 1024
