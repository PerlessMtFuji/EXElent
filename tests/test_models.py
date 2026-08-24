import dataclasses

import pytest

from exelent.models import AppKind, Dependency, Issue, OutputMode, Severity


def test_issue_is_frozen():
    issue = Issue(code="secrets_in_code", severity=Severity.WARNING)
    with pytest.raises(dataclasses.FrozenInstanceError):
        issue.code = "inne"


def test_issue_carries_data_for_translation():
    issue = Issue(code="missing_tool", severity=Severity.WARNING, data={"tool": "ffmpeg"})
    assert issue.data["tool"] == "ffmpeg"


def test_issue_has_no_human_text_field():
    fields = {f.name for f in dataclasses.fields(Issue)}
    assert "message" not in fields and "text" not in fields


def test_dependency_defaults():
    dep = Dependency(import_name="requests", package="requests")
    assert dep.optional is False and dep.heavy is False


def test_enums_are_string_valued():
    assert AppKind.WINDOWED.value == "windowed"
    assert OutputMode.ONEFILE.value == "onefile"
