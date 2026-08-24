from pathlib import Path

from exelent.analysis.apptype import (
    collect_code_issues,
    collect_hidden_imports,
    detect_app_kind,
    detect_output_mode,
)
from exelent.models import AppKind, OutputMode


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


def test_read_only_program_gets_onefile():
    assert detect_output_mode(_s("open('dane.json').read()")) is OutputMode.ONEFILE


def test_writing_program_gets_onedir():
    assert detect_output_mode(_s("open('wynik.txt', 'w').write('x')")) is OutputMode.ONEDIR


def test_json_dump_counts_as_writing():
    code = "import json\njson.dump({}, open('a.json','w'))"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_savefig_counts_as_writing():
    code = "import matplotlib.pyplot as plt\nplt.savefig('wykres.png')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


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
