"""Measure package contributions to an EXE. Run manually, not in CI.

    pytest tests/test_exe_contribution_measurement.py -m slow -s

Build a minimal witness script for every package in the table and print its
actual contribution: witness EXE size minus empty-script EXE size. Copy the
result manually into `EXE_CONTRIBUTION` with today's date.

It takes tens of minutes and downloads gigabytes, hence the `slow` marker.
"""

import pytest

from exelent.cli import run_build
from exelent.deps.sizes import EXE_CONTRIBUTION

# Import plus one real use. PyInstaller may remove an unused import as dead
# code, which would understate the measurement.
WITNESSES = {
    "numpy": "import numpy\nprint(numpy.zeros(3).sum())\n",
    "pandas": "import pandas\nprint(pandas.DataFrame({'a': [1]}).sum())\n",
    "scipy": "import scipy.signal\nprint(scipy.signal.butter(2, 0.3))\n",
    "matplotlib": (
        "import matplotlib\nmatplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\nplt.plot([1, 2])\nplt.savefig('o.png')\n"
    ),
    "opencv-python": (
        "import cv2\nimport numpy\n"
        "print(cv2.cvtColor(numpy.zeros((2, 2, 3), 'uint8'), cv2.COLOR_BGR2GRAY).shape)\n"
    ),
    "PySide6": "from PySide6.QtCore import QObject\nprint(QObject())\n",
    "PyQt5": "from PyQt5.QtCore import QObject\nprint(QObject())\n",
    "PyQt6": "from PyQt6.QtCore import QObject\nprint(QObject())\n",
    "librosa": "import librosa\nprint(librosa.__version__)\n",
    "moviepy": "import moviepy\nprint(moviepy.__version__)\n",
    "transformers": "import transformers\nprint(transformers.__version__)\n",
    "torch": "import torch\nprint(torch.zeros(3).sum())\n",
    "tensorflow": "import tensorflow\nprint(tensorflow.__version__)\n",
}


def _build_size_mb(tmp_path, name: str, code: str) -> float:
    project = tmp_path / name.replace("-", "_")
    project.mkdir(parents=True)
    (project / "main.py").write_text(code, encoding="utf-8")
    result = run_build(project)
    assert result.ok, f"{name}: build failed — {[i.code for i in result.issues]}"
    return result.size_bytes / 1024**2


@pytest.mark.slow
def test_measure_every_entry_in_the_table(tmp_path):
    baseline = _build_size_mb(tmp_path, "baseline", "print('x')\n")
    print(f"\nBASELINE (empty script): {baseline:.1f} MB\n")

    for package in sorted(EXE_CONTRIBUTION):
        code = WITNESSES.get(package)
        if code is None:
            print(f"{package}: MISSING witness — add one before measuring")
            continue
        size = _build_size_mb(tmp_path, package, code)
        print(f"{package}: {size - baseline:.1f} MB (EXE {size:.1f} MB)")


def test_every_table_entry_has_a_witness():
    """An entry without a witness can never replace its unsupported guess."""
    missing = sorted(set(EXE_CONTRIBUTION) - set(WITNESSES))
    assert missing == [], f"missing witness scripts for: {missing}"
