"""Ten sam adapter CLI działa ze strumieniami konsoli i bez nich."""

import json
import sys

import pytest

from exelent import __main__ as entry
from exelent import cli
from exelent.models import BuildResult, Issue, Severity


@pytest.mark.parametrize("windowed", [False, True])
@pytest.mark.parametrize("ok", [False, True])
def test_product_cli_returns_result_and_preserves_issues(tmp_path, monkeypatch, windowed, ok):
    artifact = tmp_path / "out" if ok else None
    executable = tmp_path / "out" / "demo.exe" if ok else None
    issue = Issue(
        "target_syntax_error" if not ok else "manual_modules_added",
        Severity.BLOCKER if not ok else Severity.WARNING,
        {"file": "zażółć.py"},
    )
    calls = []

    def build(root, **kwargs):
        calls.append((root, kwargs))
        cli._print_progress(cli.Progress(phase="build", fraction=1.0))
        return BuildResult(ok=ok, artifact=artifact, executable_path=executable, issues=(issue,))

    monkeypatch.setattr(cli, "run_build", build)
    monkeypatch.setattr(cli, "register_session", lambda: None)
    monkeypatch.setattr(cli, "clean_stale_sessions", lambda: None)
    report = tmp_path / "report.json"
    if windowed:
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
    code = entry.main(["EXElent.exe", "--cli", str(tmp_path), "--report", str(report)])
    assert code == (0 if ok else 1)
    assert calls == [(tmp_path, {})]
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["ok"] is ok
    assert result["executable_path"] == (str(executable) if executable else None)
    assert result["issues"] == [
        {"code": issue.code, "severity": issue.severity.value, "data": {"file": "zażółć.py"}}
    ]


def test_default_entry_still_opens_gui(monkeypatch):
    from exelent.ui import app

    seen = []
    monkeypatch.setattr(app, "run_gui", lambda args: seen.append(args) or 0)
    assert entry.main(["EXElent.exe"]) == 0
    assert seen == [["EXElent.exe"]]
