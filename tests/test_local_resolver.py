"""Konflikty rzeczywistego uv na kontrolowanych wheelach, bez indeksu paczek."""

import base64
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from procutil import run_bounded

from exelent.cli import run_build
from exelent.models import BuildResult
from exelent.runtime import noop_progress

pytestmark = pytest.mark.slow


def _wheel(folder, name, version, requires=()):
    stem = name.replace("-", "_")
    info = f"{stem}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    metadata += "".join(f"Requires-Dist: {requirement}\n" for requirement in requires)
    files = {
        f"{stem}.py": b"VALUE = 42\n",
        f"{info}/METADATA": metadata.encode(),
        f"{info}/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for path, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        writer.writerow([path, f"sha256={digest}", len(content)])
    writer.writerow([f"{info}/RECORD", "", ""])
    files[f"{info}/RECORD"] = record.getvalue().encode()
    with zipfile.ZipFile(folder / f"{stem}-{version}-py3-none-any.whl", "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)


@pytest.mark.parametrize("case", ["pins", "transitive", "valid"])
def test_local_resolution_controls_whether_backend_can_run(tmp_path, monkeypatch, case):
    from exelent.runtime import env

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _wheel(wheels, "exelent-test-tool", "1.0")
    _wheel(wheels, "exelent-test-core", "1.0")
    _wheel(wheels, "exelent-test-core", "2.0")
    _wheel(wheels, "exelent-test-alpha", "1.0", ["exelent-test-core==1.0"])
    _wheel(wheels, "exelent-test-beta", "1.0", ["exelent-test-core==2.0"])
    monkeypatch.setenv("UV_NO_INDEX", "1")
    monkeypatch.setenv("UV_FIND_LINKS", str(wheels))
    # Narzędzie pakowania zastępuje lokalny wheel; instalacja i resolver uv
    # są prawdziwe. Ten test sprawdza bramkę środowiska, a nie PyInstaller.
    monkeypatch.setattr(env, "PYINSTALLER_SPEC", "exelent-test-tool==1.0")
    requirements = {
        "pins": "exelent-test-core==1.0\nexelent-test-core==2.0\n",
        "transitive": "exelent-test-alpha==1.0\nexelent-test-beta==1.0\n",
        "valid": "exelent-test-alpha==1.0\nexelent-test-core<2\n",
    }[case]
    source = tmp_path / "source"
    source.mkdir()
    (source / "requirements.txt").write_text(requirements, encoding="utf-8")
    (source / "main.py").write_text("print('CONTROLLED')\n", encoding="utf-8")
    seen = []

    class Backend:
        def build(self, plan, build_env, progress, cancel):
            probe = run_bounded(
                [
                    build_env.python,
                    "-c",
                    (
                        "import importlib.metadata as m,json; "
                        "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions()}))"
                    ),
                ],
                timeout=30,
            )
            assert probe.returncode == 0, probe.stderr
            seen.append(json.loads(probe.stdout))
            return BuildResult(ok=True, artifact=Path(plan.dest_dir) / "controlled.exe")

    result = run_build(source, noop_progress, backend=Backend(), dest_dir=tmp_path / "out")
    if case == "valid":
        assert result.ok, result.issues
        assert len(seen) == 1
        assert seen[0]["exelent-test-core"] == "1.0"
        assert seen[0]["exelent-test-alpha"] == "1.0"
    else:
        assert not result.ok
        assert "requirements_conflict" in {issue.code for issue in result.issues}, result.issues
        assert seen == [], "backend nie może użyć środowiska po konflikcie resolvera"
