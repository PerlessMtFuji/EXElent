"""Spakowany produkt buduje i waliduje następny EXE na izolowanym Pythonie 3.12."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from procutil import run_bounded

pytestmark = pytest.mark.slow


def test_frozen_product_cold_bootstrap_validation_and_rebuild(tmp_path, monkeypatch):
    configured = os.environ.get("EXELENT_TEST_EXE")
    if not configured:
        pytest.skip("EXELENT_TEST_EXE musi wskazywać zbudowany produkt")
    product = Path(configured).resolve()
    assert product.is_file(), product

    state = tmp_path / "state"
    monkeypatch.setenv("LOCALAPPDATA", str(state))
    for variable, folder in (
        ("UV_CACHE_DIR", "uv-cache"),
        ("UV_PYTHON_INSTALL_DIR", "python"),
        ("UV_PYTHON_BIN_DIR", "python-bin"),
    ):
        location = tmp_path / folder
        assert not location.exists()
        monkeypatch.setenv(variable, str(location))
    monkeypatch.setenv("UV_PYTHON_PREFERENCE", "only-managed")
    monkeypatch.setenv("UV_NO_CONFIG", "1")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    (tmp_path / "context.json").write_text(
        json.dumps({"developer_python": sys.version, "product": str(product), "target": "3.12"}),
        encoding="utf-8",
    )

    source = tmp_path / "źródła ze spacjami"
    source.mkdir()
    original = (
        "import sys\n"
        "from pathlib import Path\n"
        "Path('proof.txt').write_text('SELF-BUILD-OK ' + sys.version, encoding='utf-8')\n"
    )
    (source / "main.py").write_text(original, encoding="utf-8")

    def build(label):
        report = tmp_path / f"{label}.json"
        run = run_bounded(
            [
                product,
                "--cli",
                source,
                "--name",
                "Probe",
                "--out",
                tmp_path / "out",
                "--report",
                report,
            ],
            timeout=900,
            cwd=tmp_path,
        )
        assert report.is_file(), (run.returncode, run.stdout, run.stderr)
        result = json.loads(report.read_text(encoding="utf-8"))
        if result["log_path"]:
            shutil.copyfile(result["log_path"], tmp_path / f"{label}.log")
        return run, result

    run, first = build("cold")
    assert run.returncode == 0 and first["ok"], first
    exe = Path(first["executable_path"])
    assert not (exe.parent / "proof.txt").exists(), "build wykonał kod wejściowy"
    child = run_bounded([exe], timeout=120, cwd=tmp_path)
    assert child.returncode == 0, (child.stdout, child.stderr)
    proof = (exe.parent / "proof.txt").read_bytes()
    assert proof.startswith(b"SELF-BUILD-OK 3.12."), proof
    assert list((tmp_path / "python").glob("cpython-3.12*"))
    assert (tmp_path / "uv-cache").is_dir()
    previous_exe = exe.read_bytes()

    # ast.parse przepuszcza return poza funkcją; ma go zatrzymać walidator
    # z zamrożonego produktu, zanim uruchomi się PyInstaller.
    (source / "bad.py").write_text("return 1\n", encoding="utf-8")
    (source / "main.py").write_text("import bad\n" + original, encoding="utf-8")
    run, invalid = build("invalid")
    assert run.returncode == 1 and not invalid["ok"], invalid
    issue = next(i for i in invalid["issues"] if i["code"] == "target_syntax_error")
    assert issue["data"]["file"] == "bad.py", issue
    assert str(issue["data"]["line"]) == "1", issue
    assert invalid["artifact"] is None and invalid["log_path"] is None

    (source / "bad.py").unlink()
    (source / "main.py").write_text(original, encoding="utf-8")
    run, second = build("warm")
    assert run.returncode == 0 and second["ok"], second
    second_exe = Path(second["executable_path"])
    assert second_exe != exe
    child = run_bounded([second_exe], timeout=120, cwd=tmp_path)
    assert child.returncode == 0, (child.stdout, child.stderr)
    assert (second_exe.parent / "proof.txt").read_bytes().startswith(b"SELF-BUILD-OK 3.12.")
    assert exe.read_bytes() == previous_exe
    assert (exe.parent / "proof.txt").read_bytes() == proof
    assert list(source.iterdir()) == [source / "main.py"]
    assert (source / "main.py").read_text(encoding="utf-8") == original
