import pytest

from exelent.models import Severity
from exelent.runtime import bootstrap, noop_progress


def test_low_disk_space_is_a_blocker(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(bootstrap, "_free_bytes", lambda _p: 100)
    monkeypatch.setattr(bootstrap, "_has_network", lambda: True)
    issues = bootstrap.check_preconditions(need_network=True)
    assert any(i.code == "low_disk_space" and i.severity is Severity.BLOCKER for i in issues)


def test_missing_network_is_a_blocker(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(bootstrap, "_free_bytes", lambda _p: 10**12)
    monkeypatch.setattr(bootstrap, "_has_network", lambda: False)
    issues = bootstrap.check_preconditions(need_network=True)
    assert any(i.code == "no_network" for i in issues)


def test_network_not_checked_when_not_needed(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(bootstrap, "_free_bytes", lambda _p: 10**12)
    monkeypatch.setattr(bootstrap, "_has_network", lambda: pytest.fail("nie wolno sprawdzać"))
    assert bootstrap.check_preconditions(need_network=False) == ()


def test_ensure_uv_returns_cached_binary_without_download(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = bootstrap.uv_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"udawany uv")
    monkeypatch.setattr(bootstrap, "_download", lambda *a, **k: pytest.fail("nie pobieraj"))
    assert bootstrap.ensure_uv(noop_progress) == target


def test_ensure_uv_downloads_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    calls = []

    def fake_download(url, dest, progress):
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"pobrany uv")

    monkeypatch.setattr(bootstrap, "_download_and_extract_uv", fake_download)
    result = bootstrap.ensure_uv(noop_progress)
    assert result.exists() and len(calls) == 1
    assert bootstrap.UV_VERSION in calls[0]
