from urllib.parse import parse_qs, urlparse

from exelent.diagnostics.report import github_issue_url, tail, write_report


def test_tail_returns_last_lines():
    log = "\n".join(f"linia {i}" for i in range(100))
    assert tail(log, 3) == "linia 97\nlinia 98\nlinia 99"


def test_tail_handles_short_log():
    assert tail("jedna linia", 40) == "jedna linia"


def test_issue_url_points_at_project_repo():
    url = github_issue_url("blad", "Program, onefile")
    assert urlparse(url).netloc == "github.com"
    assert "/issues/new" in urlparse(url).path


def test_issue_url_prefills_body_with_context():
    url = github_issue_url("BLAD-XYZ", "Kalkulator, onefile, python 3.12")
    body = parse_qs(urlparse(url).query)["body"][0]
    assert "BLAD-XYZ" in body and "Kalkulator" in body


def test_issue_url_truncates_huge_logs():
    url = github_issue_url("x" * 50_000, "Program")
    assert len(url) < 8000


def test_write_report_creates_readable_file(tmp_path):
    path = write_report("tresc logu", tmp_path / "raport.txt", "Program, onefile")
    text = path.read_text(encoding="utf-8")
    assert "tresc logu" in text and "Program, onefile" in text
