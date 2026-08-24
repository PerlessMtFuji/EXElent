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


def _fake_uv_zip_bytes(content: bytes = b"prawdziwa zawartosc uv.exe") -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("uv-x86_64-pc-windows-msvc/uv.exe", content)
    return buffer.getvalue()


def test_interrupted_download_leaves_no_partial_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = bootstrap.uv_path()
    payload = _fake_uv_zip_bytes()
    monkeypatch.setattr(bootstrap, "_download", lambda url, progress: payload)

    def failing_replace(_src, _dst):
        raise OSError("symulowane zerwanie polaczenia w polowie zapisu")

    monkeypatch.setattr(bootstrap.os, "replace", failing_replace)

    with pytest.raises(bootstrap.UvDownloadError):
        bootstrap.ensure_uv(noop_progress)

    assert not target.exists()
    assert target.parent.exists()
    assert list(target.parent.glob(".uv-download-*")) == []


def test_ensure_uv_raises_typed_error_with_issue_code(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(
        bootstrap,
        "_download",
        lambda url, progress: (_ for _ in ()).throw(OSError("brak sieci")),
    )

    with pytest.raises(bootstrap.UvDownloadError) as exc_info:
        bootstrap.ensure_uv(noop_progress)

    assert exc_info.value.issue.code == "uv_download_failed"


def test_ensure_uv_retries_download_after_prior_interruption(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = bootstrap.uv_path()
    payload = _fake_uv_zip_bytes()
    calls = {"n": 0}

    def fake_download(url, progress):
        calls["n"] += 1
        return payload

    monkeypatch.setattr(bootstrap, "_download", fake_download)

    real_replace = bootstrap.os.replace
    state = {"fail_next": True}

    def flaky_replace(src, dst):
        if state["fail_next"]:
            state["fail_next"] = False
            raise OSError("symulowane zerwanie polaczenia w polowie zapisu")
        return real_replace(src, dst)

    monkeypatch.setattr(bootstrap.os, "replace", flaky_replace)

    with pytest.raises(bootstrap.UvDownloadError):
        bootstrap.ensure_uv(noop_progress)
    assert not target.exists()

    result = bootstrap.ensure_uv(noop_progress)

    assert result == target
    assert target.exists()
    assert calls["n"] == 2
