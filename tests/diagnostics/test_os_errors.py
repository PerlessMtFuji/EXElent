"""`map_os_error` — diagnoza WYJATKU systemu, nie logu PyInstallera.

Osobna tabela istnieje, bo bazowe prawdopodobienstwo jest inne. Ten sam
WinError 1920 w logu builda (na artefakcie w `dist`) najczesciej znaczy
antywirusa — Task 14 rozstrzygnal to trzema rundami. Ale przy CZYTANIU
plikow zrodlowych uzytkownika ten sam kod najczesciej znaczy plik trzymany
tylko w chmurze (OneDrive Files On-Demand jest wlaczone domyslnie), a rada
"wylacz antywirusa" jest wtedy pewna siebie i BLEDNA.
"""

from exelent.diagnostics.patterns import explain_log, map_os_error
from exelent.models import Severity


def _codes(exc, **kwargs) -> list[str]:
    return [issue.code for issue in map_os_error(exc, **kwargs)]


def _oserror(winerror: int, strerror: str, filename: str = r"C:\projekt\main.py"):
    return PermissionError(13, strerror, filename, winerror)


def test_cloud_only_file_is_named_as_such_not_as_antivirus():
    exc = _oserror(
        1920,
        "The file cannot be accessed by the system",
        r"C:\Users\Ala\OneDrive\projekt\main.py",
    )
    codes = _codes(exc, in_cloud=True)
    assert "cloud_file_unavailable" in codes
    assert "antivirus_blocked" not in codes, "rada 'wylacz antywirusa' przy pliku z chmury"


def test_cloud_file_issue_carries_the_file_name():
    exc = _oserror(1920, "The file cannot be accessed by the system", r"C:\OneDrive\p\dane.py")
    issue = map_os_error(exc, in_cloud=True)[0]
    assert issue.severity is Severity.BLOCKER
    assert issue.data.get("file") == "dane.py"


def test_the_same_code_outside_the_cloud_stays_neutral():
    """Bez dowodu na chmure nie zgadujemy — mowimy tylko, ze Windows odmowil."""
    exc = _oserror(1920, "The file cannot be accessed by the system")
    codes = _codes(exc, in_cloud=False)
    assert codes == ["access_denied"]


def test_an_explicit_cloud_message_is_enough_on_its_own():
    """Tak jak przy antywirusie w Tasku 14: gdy Windows sam nazwal przyczyne,
    drugi dowod niczego nie rozstrzyga, a produkuje falszywe negatywy."""
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
    """Puste znaczy "nie wiem" — `run_build` zamienia to na `unexpected_error`.
    Zmyslona diagnoza jest gorsza niz uczciwe "cos poszlo nie tak"."""
    assert _codes(OSError(999, "Cos zupelnie nowego")) == []


def test_no_exception_can_ever_be_diagnosed_as_antivirus():
    """Straznik na przyszlosc: `antivirus_blocked` wymaga dowodu z logu builda
    (artefakt w `dist`), ktorego wyjatek z czytania plikow zrodlowych nie ma."""
    candidates = [
        _oserror(225, "Operation did not complete successfully because the file contains a virus"),
        _oserror(1920, "The file cannot be accessed by the system"),
        _oserror(5, "Access is denied", r"C:\projekt\dist\main.exe"),
    ]
    for exc in candidates:
        assert "antivirus_blocked" not in _codes(exc, in_cloud=True)
        assert "antivirus_blocked" not in _codes(exc, in_cloud=False)


def test_the_build_log_table_is_untouched():
    """Decyzja Taska 14 dla LOGOW zostaje — to inna sytuacja i inne dowody."""
    log = r"PermissionError: [WinError 1920] cannot be accessed: 'C:\b\dist\Program.exe'"
    assert "antivirus_blocked" in {i.code for i in explain_log(log)}


def test_filename_may_be_missing():
    exc = OSError(1920, "The file cannot be accessed by the system")
    assert map_os_error(exc, in_cloud=True)[0].data.get("file") in (None, "")


def test_a_folder_named_like_the_cloud_is_not_evidence_of_the_cloud():
    """Wzorzec chmury opisuje TRESC komunikatu Windows, a nie sciezke. Sciezka
    jest tekstem uzytkownika: katalog "cloud file notes" nie ma prawa przykryc
    diagnozy, ktora system podal wprost i ktora jest rozrozniajaca."""
    exc = OSError(28, "No space left on device", r"C:\dane\cloud file notes.py")
    assert _codes(exc) == ["disk_full"]


def test_a_locked_file_keeps_its_diagnosis_inside_a_cloudish_folder():
    exc = _oserror(
        32, "The process cannot access the file because it is being used", r"C:\cloud sync\a.py"
    )
    assert _codes(exc) == ["file_in_use"]


def test_a_path_alone_never_promotes_itself_to_a_cloud_diagnosis():
    exc = _oserror(5, "Access is denied", r"C:\Users\Ala\Cloud Files\projekt\main.py")
    assert _codes(exc) == ["access_denied"]


def test_a_filename_that_is_not_text_does_not_break_the_diagnosis():
    """`OSError.filename` bywa bajtami — diagnoza ma dzialac, a nie rzucac."""
    exc = PermissionError(13, "Access is denied", rb"C:\projekt\main.py", 5)
    assert _codes(exc) == ["access_denied"]
