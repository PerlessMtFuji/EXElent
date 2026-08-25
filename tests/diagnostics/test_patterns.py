from exelent.diagnostics.patterns import explain_log
from exelent.models import Severity


def _codes(log: str) -> set[str]:
    return {issue.code for issue in explain_log(log)}


def test_missing_package_is_recognised():
    log = "ERROR: No solution found when resolving dependencies for: nieistniejaca-paczka"
    assert "package_not_found" in _codes(log)


def test_missing_module_during_analysis():
    log = "ModuleNotFoundError: No module named 'cv2'"
    issues = explain_log(log)
    assert any(i.code == "module_not_found" and i.data.get("module") == "cv2" for i in issues)


def test_antivirus_deletion_is_recognised():
    log = r"PermissionError: [WinError 5] Access is denied: 'C:\\...\\dist\\Program.exe'"
    assert "antivirus_blocked" in _codes(log)


def test_long_path_is_recognised():
    log = "OSError: [WinError 206] The filename or extension is too long"
    assert "path_too_long" in _codes(log)


def test_ssl_proxy_is_recognised():
    log = "SSLError: certificate verify failed: unable to get local issuer certificate"
    assert "ssl_proxy" in _codes(log)


def test_out_of_disk_is_recognised():
    log = "OSError: [Errno 28] No space left on device"
    assert "disk_full" in _codes(log)


def test_recursion_limit_is_recognised():
    log = "RecursionError: maximum recursion depth exceeded"
    assert "recursion_limit" in _codes(log)


def test_unknown_log_produces_nothing():
    assert explain_log("cos zupelnie innego\nbez znanych wzorcow") == ()


def test_blockers_come_first():
    log = (
        "ModuleNotFoundError: No module named 'cv2'\nOSError: [Errno 28] No space left on device\n"
    )
    issues = explain_log(log)
    assert issues[0].severity is Severity.BLOCKER


def test_each_pattern_is_reported_once():
    log = "ModuleNotFoundError: No module named 'cv2'\n" * 5
    assert len(explain_log(log)) == 1
