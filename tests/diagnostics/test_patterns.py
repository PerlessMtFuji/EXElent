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


def test_dist_info_directory_does_not_trigger_antivirus():
    # Regresja (runda 2): ".dist-info" jest wszechobecne w logach fazy
    # Analysis PyInstallera. Myslnik jest znakiem niebedacym znakiem slowa,
    # wiec \bdist\b dopasowuje sie WEWNATRZ "numpy-1.26.4.dist-info". Razem
    # z niepowiazanym WinError 5 na pliku uzytkownika dawalo to pewna i
    # bledna diagnoze "antywirus". Prawdziwa przyczyna: otwarty arkusz.
    log = (
        r"3421 INFO: Loading module hook 'hook-numpy.py' from "
        r"'C:\...\numpy-1.26.4.dist-info\...\hooks'"
        "\n"
        r"3600 PermissionError: [WinError 5] Access is denied: "
        r"'C:\Users\foo\Documents\input.xlsx'"
        "\n"
    )
    codes = _codes(log)
    assert "antivirus_blocked" not in codes
    assert "access_denied" in codes


def test_dist_info_on_the_same_line_as_access_denied_is_still_not_antivirus():
    # Dowod, ze wykluczenie "-info" jest nosne samo w sobie, niezaleznie od
    # zawezenia do jednej linii: jedyny token przypominajacy "dist" w calym
    # logu to ".dist-info" i lezy w TEJ SAMEJ linii co blad dostepu.
    log = (
        r"PermissionError: [WinError 5] Access is denied: "
        r"'C:\venv\Lib\site-packages\numpy-1.26.4.dist-info\RECORD'"
    )
    codes = _codes(log)
    assert "antivirus_blocked" not in codes
    assert "access_denied" in codes


def test_document_wide_dist_cooccurrence_is_not_antivirus():
    # Zwykla linia informacyjna wspominajaca katalog wyjsciowy nie moze
    # dostarczac "dowodu na dist" dla niepowiazanego bledu dostepu wiele
    # linii pozniej. Oba dowody musza pochodzic z tego samego zdarzenia.
    log = (
        r"1500 INFO: will output to dist\myapp\myapp.exe once complete"
        "\n"
        "2000 INFO: Analyzing hidden import 'pkg_resources'\n"
        "2500 INFO: Processing pre-safe import module hook urllib3\n"
        r"3600 PermissionError: [WinError 5] Access is denied: "
        r"'C:\Users\foo\Documents\raport.xlsx'"
        "\n"
    )
    codes = _codes(log)
    assert "antivirus_blocked" not in codes
    assert "access_denied" in codes


def test_access_denied_on_build_artifact_is_still_antivirus():
    # Pozytyw: blad dostepu dotyczy artefaktu builda pod dist, w tej samej
    # linii. To nadal jest antivirus_blocked i nadal tlumi neutralny kod.
    log = (
        "5000 INFO: Building EXE from EXE-00.toc completed successfully.\n"
        r"5001 PermissionError: [WinError 5] Access is denied: "
        r"'C:\proj\dist\myapp\myapp.exe'"
        "\n"
    )
    codes = _codes(log)
    assert "antivirus_blocked" in codes
    assert "access_denied" not in codes


def test_access_denied_on_build_artifact_with_forward_slashes():
    # Logi PyInstallera mieszaja separatory; "/dist/" musi liczyc sie tak
    # samo jak "\dist\".
    log = "PermissionError: [WinError 5] Access is denied: '/home/x/proj/dist/myapp'"
    codes = _codes(log)
    assert "antivirus_blocked" in codes
    assert "access_denied" not in codes


def test_dist_evidence_on_an_adjacent_line_stays_neutral():
    # Swiadomie wybrana granica: okno to dokladnie jedna linia. Gdy sciezka
    # do dist jest w sasiedniej linii, a nie w tej z bledem, nie mamy dowodu,
    # ze oba fakty dotycza tego samego zdarzenia — degradujemy do neutralnego
    # access_denied. Blad w te strone jest tani (mniej konkretne zdanie),
    # blad w druga strone kosztuje uzytkownika godzine na wylaczanie
    # antywirusa przy zupelnie innej przyczynie.
    log = (
        r"3000 INFO: Removing output directory C:\proj\dist\myapp"
        "\n"
        "3001 PermissionError: [WinError 5] Access is denied\n"
    )
    codes = _codes(log)
    assert "antivirus_blocked" not in codes
    assert "access_denied" in codes
