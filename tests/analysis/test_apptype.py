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


# --- Fix Round 1/5: detect_output_mode broadened to err toward ONEDIR ---


def test_sqlite_connect_counts_as_writing():
    code = "import sqlite3\nsqlite3.connect('db.sqlite')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_logging_filehandler_counts_as_writing():
    code = "import logging\nlogging.FileHandler('app.log')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_logging_rotating_filehandler_counts_as_writing():
    code = "import logging.handlers\nlogging.handlers.RotatingFileHandler('app.log')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_logging_timed_rotating_filehandler_counts_as_writing():
    code = "import logging.handlers\nlogging.handlers.TimedRotatingFileHandler('app.log')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_logging_basicconfig_with_filename_counts_as_writing():
    code = "import logging\nlogging.basicConfig(filename='app.log')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_shutil_copy_counts_as_writing():
    code = "import shutil\nshutil.copy('a', 'b')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_shutil_copy2_counts_as_writing():
    code = "import shutil\nshutil.copy2('a', 'b')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_shutil_copyfile_counts_as_writing():
    code = "import shutil\nshutil.copyfile('a', 'b')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_shutil_copytree_counts_as_writing():
    code = "import shutil\nshutil.copytree('a', 'b')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_shutil_move_counts_as_writing():
    code = "import shutil\nshutil.move('a', 'b')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_shutil_make_archive_counts_as_writing():
    code = "import shutil\nshutil.make_archive('out', 'zip', 'src')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_to_json_counts_as_writing():
    code = "df.to_json('a.json')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_to_parquet_counts_as_writing():
    code = "df.to_parquet('a.parquet')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_to_pickle_counts_as_writing():
    code = "df.to_pickle('a.pkl')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_to_html_counts_as_writing():
    code = "df.to_html('a.html')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_to_sql_counts_as_writing():
    code = "df.to_sql('table', conn)"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_to_feather_counts_as_writing():
    code = "df.to_feather('a.feather')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_zipfile_write_mode_counts_as_writing():
    code = "import zipfile\nzipfile.ZipFile('out.zip', 'w')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_tarfile_write_mode_counts_as_writing():
    code = "import tarfile\ntarfile.open('out.tar', 'w')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_os_makedirs_counts_as_writing():
    code = "import os\nos.makedirs('out')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_os_mkdir_counts_as_writing():
    code = "import os\nos.mkdir('out')"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_path_mkdir_counts_as_writing():
    code = "from pathlib import Path\nPath('out').mkdir()"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_open_with_variable_mode_counts_as_writing():
    code = "m = 'r'\nopen('f', m)"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_open_with_variable_mode_kwarg_counts_as_writing():
    code = "m = 'r'\nopen('f', mode=m)"
    assert detect_output_mode(_s(code)) is OutputMode.ONEDIR


def test_read_only_program_still_gets_onefile():
    code = (
        "import json\n"
        "from pathlib import Path\n"
        "open('dane.json').read()\n"
        "json.load(open('dane.json'))\n"
        "Path('dane.json').read_text()\n"
    )
    assert detect_output_mode(_s(code)) is OutputMode.ONEFILE
