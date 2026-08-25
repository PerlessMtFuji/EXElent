import pytest

from exelent.runtime import noop_progress
from exelent.runtime.env import create_build_env


@pytest.mark.slow
def test_real_env_has_tkinter_and_pyinstaller(tmp_path, monkeypatch):
    """Dowodzi najważniejszego założenia specyfikacji: CPython sprowadzony
    przez uv zawiera tkinter, którego oficjalny embeddable Python nie ma."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    src = tmp_path / "src"
    src.mkdir()
    build_env = create_build_env(src, [], noop_progress)

    assert build_env.python.exists()
    assert build_env.failed_packages == ()

    import subprocess

    check = subprocess.run(
        [str(build_env.python), "-c", "import tkinter, PyInstaller; print('ok')"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stderr
    assert "ok" in check.stdout
