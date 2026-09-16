from pathlib import Path

from exelent.analysis.apptype import (
    collect_code_issues,
    collect_hidden_imports,
    detect_app_kind,
    package_submodule_collections,
)
from exelent.models import AppKind


def _s(code: str) -> dict[Path, str]:
    return {Path("main.py"): code}


def test_tkinter_means_windowed():
    kind, certain = detect_app_kind(_s("import tkinter\ntkinter.Tk().mainloop()"))
    assert kind is AppKind.WINDOWED and certain is True


def test_pyside_means_windowed():
    kind, _ = detect_app_kind(_s("from PySide6.QtWidgets import QApplication"))
    assert kind is AppKind.WINDOWED


def test_input_means_console():
    kind, certain = detect_app_kind(_s("name = input('podaj: ')\nprint(name)"))
    assert kind is AppKind.CONSOLE and certain is True


def test_gui_with_input_is_not_certain():
    kind, certain = detect_app_kind(_s("import tkinter\nx = input('?')"))
    assert kind is AppKind.WINDOWED and certain is False


def test_plain_script_defaults_to_console():
    kind, _ = detect_app_kind(_s("print('hello')"))
    assert kind is AppKind.CONSOLE


# Output mode (ONEFILE versus ONEDIR) is no longer inferred from source (B01).
# ONEDIR is always recommended, while the user chooses ONEFILE. Regression
# coverage lives in test_project.py (recommendation) and test_planning.py
# (manual ONEFILE constraint).


def test_type_checking_import_does_not_trigger_windowed():
    code = (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import tkinter\nprint('hello')\n"
    )
    kind, _ = detect_app_kind(_s(code))
    assert kind is AppKind.CONSOLE


def test_if_false_import_does_not_trigger_windowed():
    code = "if False:\n    import PyQt5\nprint('hello')\n"
    kind, _ = detect_app_kind(_s(code))
    assert kind is AppKind.CONSOLE


def test_flask_raises_server_issue():
    codes = {i.code for i in collect_code_issues(_s("from flask import Flask"))}
    assert "server_app" in codes


def test_ffmpeg_call_raises_external_tool_issue():
    code = "import subprocess\nsubprocess.run(['ffmpeg', '-i', 'a.mp4'])"
    issues = collect_code_issues(_s(code))
    tools = {i.data.get("tool") for i in issues if i.code == "external_tool"}
    assert "ffmpeg" in tools


def test_api_key_raises_secrets_issue():
    code = "API_KEY = 'sk-abcdefghijklmnopqrstuvwxyz0123456789'"
    codes = {i.code for i in collect_code_issues(_s(code))}
    assert "secrets_in_code" in codes


def test_literal_dynamic_import_becomes_hidden_import():
    code = "import importlib\nimportlib.import_module('requests')"
    assert "requests" in collect_hidden_imports(_s(code))


def test_variable_dynamic_import_raises_issue():
    code = "import importlib\nname = 'x'\nimportlib.import_module(name)"
    codes = {i.code for i in collect_code_issues(_s(code))}
    assert "dynamic_import_unresolved" in codes


# B01: __file__ / _MEIPASS heuristics warn without rewriting code


def test_dunder_file_raises_frozen_path_issue():
    code = "import os\nbase = os.path.dirname(__file__)\ndata = open(os.path.join(base, 'x'))"
    issues = collect_code_issues(_s(code))
    matching = [i for i in issues if i.code == "frozen_path_pattern"]
    assert len(matching) == 1
    assert matching[0].data["pattern"] == "__file__"


def test_sys_meipass_raises_frozen_path_issue():
    code = "import sys\nbase = sys._MEIPASS\nprint(base)"
    issues = collect_code_issues(_s(code))
    matching = [i for i in issues if i.code == "frozen_path_pattern"]
    assert len(matching) == 1
    assert matching[0].data["pattern"] == "_MEIPASS"


def test_getattr_meipass_raises_frozen_path_issue():
    code = "import sys\nbase = getattr(sys, '_MEIPASS', '.')\nprint(base)"
    issues = collect_code_issues(_s(code))
    matching = [i for i in issues if i.code == "frozen_path_pattern"]
    assert len(matching) == 1
    assert matching[0].data["pattern"] == "_MEIPASS"


def test_both_file_and_meipass_raise_separate_issues():
    code = "import sys, os\nif getattr(sys, '_MEIPASS', None):\n  p = sys._MEIPASS\nelse:\n  p = os.path.dirname(__file__)"
    issues = collect_code_issues(_s(code))
    patterns = sorted(i.data["pattern"] for i in issues if i.code == "frozen_path_pattern")
    assert set(patterns) == {"__file__", "_MEIPASS"}


def test_plain_code_has_no_frozen_path_issue():
    code = "x = 1\nprint(x)"
    issues = collect_code_issues(_s(code))
    assert not any(i.code == "frozen_path_pattern" for i in issues)


# --- package_submodule_collections ---


def test_scipy_triggers_array_api_compat_collection():
    result = package_submodule_collections({"scipy", "numpy"})
    assert "scipy._external.array_api_compat" in result


def test_unrelated_packages_trigger_no_collections():
    result = package_submodule_collections({"requests", "numpy", "pandas"})
    assert result == ()


def test_empty_imports_trigger_no_collections():
    assert package_submodule_collections(set()) == ()
