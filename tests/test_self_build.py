"""EXElent packaging itself.

The plan's tests asserted string presence in a file (`"--noupx" in text`).
Such a test also passes for a comment or a flag in a dead branch — the
same class of weak assertion that survived five tasks in this project.
Here we measure the actual ARGUMENT LIST that PyInstaller will receive.
"""

from __future__ import annotations

import sys
from pathlib import Path

import build_exelent
from exelent.constants import APP_NAME, PYINSTALLER_SPEC

# Anchored to the repository directory, not the current directory: the test
# must measure the release file, not wherever someone ran pytest from.
REPO = Path(build_exelent.__file__).parent
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "release.yml"


def _make_root(tmp_path: Path) -> Path:
    (tmp_path / "exelent").mkdir()
    (tmp_path / "exelent" / "__main__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_command_disables_upx(tmp_path):
    assert "--noupx" in build_exelent.build_command(_make_root(tmp_path))


def test_command_builds_one_windowed_file(tmp_path):
    command = build_exelent.build_command(_make_root(tmp_path))
    assert "--onefile" in command
    assert "--windowed" in command


def test_command_names_the_program_after_app_name(tmp_path):
    command = build_exelent.build_command(_make_root(tmp_path))
    assert command[command.index("--name") + 1] == APP_NAME


def test_command_runs_pyinstaller_from_the_running_interpreter(tmp_path):
    command = build_exelent.build_command(_make_root(tmp_path))
    assert command[:3] == [sys.executable, "-m", "PyInstaller"]


def test_command_packs_the_package_entry_point(tmp_path):
    root = _make_root(tmp_path)
    assert command_last(root) == str(root / "exelent" / "__main__.py")


def command_last(root: Path) -> str:
    return build_exelent.build_command(root)[-1]


def test_icon_is_used_when_the_file_exists(tmp_path):
    root = _make_root(tmp_path)
    icon = root / "assets" / f"{APP_NAME.lower()}.ico"
    icon.parent.mkdir()
    icon.write_bytes(b"")
    command = build_exelent.build_command(root)
    assert command[command.index("--icon") + 1] == str(icon)


def test_no_icon_flag_when_the_file_is_missing(tmp_path):
    assert "--icon" not in build_exelent.build_command(_make_root(tmp_path))


def test_output_lands_outside_the_source_package(tmp_path):
    root = _make_root(tmp_path)
    command = build_exelent.build_command(root)
    assert command[command.index("--distpath") + 1] == str(root / "dist")


def test_release_workflow_pins_the_same_pyinstaller_as_the_core():
    assert PYINSTALLER_SPEC in RELEASE_WORKFLOW.read_text(encoding="utf-8")


def test_release_workflow_uploads_the_file_the_script_produces():
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert f"dist/{APP_NAME}.exe" in text


# --- README and the program must send the user to the same place ---


def test_readme_points_at_the_same_repository_as_the_report_button():
    """After a failed build, the program offers to file a report on GitHub.

    If the README pointed elsewhere, half the users would write in a place
    nobody reads — and the divergence of those two addresses is invisible
    until someone manually compares them.
    """
    from exelent.diagnostics.report import REPO_URL

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    # We check the DOWNLOAD LINK, not just any occurrence of the address
    # anywhere in the file: a mutant replacing only this link passed as long
    # as other mentions of the repository remained untouched.
    assert f"{REPO_URL}/releases/latest" in readme
    assert f"{REPO_URL}/issues" in readme
