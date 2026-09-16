"""`map_os_error` diagnoses an OS exception rather than a PyInstaller log.

A separate table exists because the prior probability differs. WinError 1920
in a build log for an artifact under `dist` usually indicates antivirus
interference, as task 14 established over three rounds. While reading a user's
source files, the same code usually means a cloud-only file because OneDrive
Files On-Demand is enabled by default. Antivirus advice would then be confidently
wrong.
"""

from exelent.diagnostics.patterns import explain_log, map_os_error
from exelent.models import Severity


def _codes(exc, **kwargs) -> list[str]:
    return [issue.code for issue in map_os_error(exc, **kwargs)]


def _oserror(winerror: int, strerror: str, filename: str = r"C:\project\main.py"):
    return PermissionError(13, strerror, filename, winerror)


def test_cloud_only_file_is_named_as_such_not_as_antivirus():
    exc = _oserror(
        1920,
        "The file cannot be accessed by the system",
        r"C:\Users\Alice\OneDrive\project\main.py",
    )
    codes = _codes(exc, in_cloud=True)
    assert "cloud_file_unavailable" in codes
    assert "antivirus_blocked" not in codes, "antivirus advice for a cloud-only file"


def test_cloud_file_issue_carries_the_file_name():
    exc = _oserror(1920, "The file cannot be accessed by the system", r"C:\OneDrive\p\data.py")
    issue = map_os_error(exc, in_cloud=True)[0]
    assert issue.severity is Severity.BLOCKER
    assert issue.data.get("file") == "data.py"


def test_the_same_code_outside_the_cloud_stays_neutral():
    """Without cloud evidence, do not guess; report only that Windows refused."""
    exc = _oserror(1920, "The file cannot be accessed by the system")
    codes = _codes(exc, in_cloud=False)
    assert codes == ["access_denied"]


def test_an_explicit_cloud_message_is_enough_on_its_own():
    """When Windows names the cause, requiring more evidence adds false negatives."""
    exc = _oserror(362, "The cloud file provider is not running")
    assert "cloud_file_unavailable" in _codes(exc, in_cloud=False)


def test_a_locked_file_keeps_its_own_diagnosis():
    exc = _oserror(32, "The process cannot access the file because it is being used")
    assert _codes(exc) == ["file_in_use"]


def test_a_full_disk_keeps_its_own_diagnosis():
    assert _codes(OSError(28, "No space left on device")) == ["disk_full"]


def test_a_too_long_path_keeps_its_own_diagnosis():
    assert _codes(_oserror(206, "The filename or extension is too long")) == ["path_too_long"]


def test_plain_access_denied_is_neutral():
    assert _codes(_oserror(5, "Access is denied")) == ["access_denied"]


def test_an_unrecognised_system_error_gets_no_invented_diagnosis():
    """Empty means unknown; `run_build` turns it into `unexpected_error`.

    An invented diagnosis is worse than an honest generic failure.
    """
    assert _codes(OSError(999, "Something completely new")) == []


def test_no_exception_can_ever_be_diagnosed_as_antivirus():
    """Guard that antivirus diagnosis requires build-log evidence under `dist`."""
    candidates = [
        _oserror(225, "Operation did not complete successfully because the file contains a virus"),
        _oserror(1920, "The file cannot be accessed by the system"),
        _oserror(5, "Access is denied", r"C:\project\dist\main.exe"),
    ]
    for exc in candidates:
        assert "antivirus_blocked" not in _codes(exc, in_cloud=True)
        assert "antivirus_blocked" not in _codes(exc, in_cloud=False)


def test_the_build_log_table_is_untouched():
    """Task 14's decision for logs remains because the evidence differs."""
    log = r"PermissionError: [WinError 1920] cannot be accessed: 'C:\b\dist\Program.exe'"
    assert "antivirus_blocked" in {i.code for i in explain_log(log)}


def test_filename_may_be_missing():
    exc = OSError(1920, "The file cannot be accessed by the system")
    assert map_os_error(exc, in_cloud=True)[0].data.get("file") in (None, "")


def test_a_folder_named_like_the_cloud_is_not_evidence_of_the_cloud():
    """The cloud pattern applies to Windows message text, not a user path.

    A directory named "cloud file notes" must not override a distinct diagnosis
    supplied explicitly by the system.
    """
    exc = OSError(28, "No space left on device", r"C:\data\cloud file notes.py")
    assert _codes(exc) == ["disk_full"]


def test_a_locked_file_keeps_its_diagnosis_inside_a_cloudish_folder():
    exc = _oserror(
        32, "The process cannot access the file because it is being used", r"C:\cloud sync\a.py"
    )
    assert _codes(exc) == ["file_in_use"]


def test_a_path_alone_never_promotes_itself_to_a_cloud_diagnosis():
    exc = _oserror(5, "Access is denied", r"C:\Users\Alice\Cloud Files\project\main.py")
    assert _codes(exc) == ["access_denied"]


def test_a_filename_that_is_not_text_does_not_break_the_diagnosis():
    """`OSError.filename` can be bytes; diagnosis must handle it without raising."""
    exc = PermissionError(13, "Access is denied", rb"C:\project\main.py", 5)
    assert _codes(exc) == ["access_denied"]
