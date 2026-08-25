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


def test_bare_access_denied_is_neutral_not_antivirus():
    # Reviewer finding: a bare WinError 5 unrelated to the build output
    # (e.g. a locked *input* file) must not be diagnosed as antivirus
    # interference — that sends the user to disable their antivirus for
    # nothing. It should surface as the neutral access_denied instead.
    log = (
        r"PermissionError: [WinError 5] Access is denied: "
        r"'C:\Users\foo\Documents\readonly_input.csv'"
    )
    codes = _codes(log)
    assert "access_denied" in codes
    assert "antivirus_blocked" not in codes


def test_genuine_antivirus_case_does_not_also_report_access_denied():
    # When the more specific antivirus_blocked pattern fires (access-denied
    # AND the path is under dist), the neutral fallback must not also show
    # up for the same underlying event.
    log = r"PermissionError: [WinError 5] Access is denied: 'C:\\...\\dist\\Program.exe'"
    codes = _codes(log)
    assert "antivirus_blocked" in codes
    assert "access_denied" not in codes


def test_file_in_use_is_recognised():
    log = (
        "OSError: [WinError 32] The process cannot access the file "
        r"because it is being used by another process: 'dist\\Program.exe'"
    )
    codes = _codes(log)
    assert "file_in_use" in codes
    assert "antivirus_blocked" not in codes


def test_file_in_use_suppresses_access_denied():
    log = (
        "OSError: [WinError 32] The process cannot access the file "
        "because it is being used by another process"
    )
    codes = _codes(log)
    assert "file_in_use" in codes
    assert "access_denied" not in codes


def test_errno_28_boundary_does_not_match_errno_280():
    log = "OSError: [Errno 280] Some unrelated protocol error"
    assert "disk_full" not in _codes(log)


def test_winerror_206_boundary_does_not_match_winerror_2065():
    log = "OSError: [WinError 2065] Some unrelated network error"
    assert "path_too_long" not in _codes(log)


def test_sslerror_boundary_does_not_match_inside_longer_identifier():
    log = "MySSLErrorWrapper: an unrelated internal failure occurred"
    assert "ssl_proxy" not in _codes(log)


def test_sslerror_boundary_matches_as_standalone_identifier():
    log = "requests.exceptions.SSLError: HTTPSConnectionPool(host='pypi.org', port=443)"
    assert "ssl_proxy" in _codes(log)
