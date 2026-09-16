"""Shared user-state isolation for UI tests (A14).

The window reads durable user state from `%LOCALAPPDATA%\\EXElent`: the saved
language (`settings.json`), recent projects, and logs. Without isolation, the
interface-language test passed or failed depending on what a developer had
clicked before—a saved "pl" preference overrode the patched `system_language`.

Giving the saved preference priority over the system language is correct and
remains unchanged. The fix is to keep tests from seeing unrelated saved state:
every UI test receives its own empty state directory.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_state(tmp_path_factory, monkeypatch):
    state = tmp_path_factory.mktemp("localappdata")
    monkeypatch.setenv("LOCALAPPDATA", str(state))
