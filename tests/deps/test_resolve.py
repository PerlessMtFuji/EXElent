from pathlib import Path

from exelent.deps.resolve import resolve_dependencies


def _s(code: str) -> dict[Path, str]:
    return {Path("main.py"): code}


def _names(deps) -> set[str]:
    return {d.package for d in deps}


def test_stdlib_is_filtered_out():
    deps = resolve_dependencies(_s("import os, sys, json, pathlib"), set())
    assert deps == ()


def test_local_modules_are_filtered_out():
    deps = resolve_dependencies(_s("import util\nimport requests"), {"util"})
    assert _names(deps) == {"requests"}


def test_alias_map_translates_import_to_package():
    code = "import cv2\nimport PIL\nimport sklearn\nimport yaml\nimport bs4"
    deps = resolve_dependencies(_s(code), set())
    assert _names(deps) == {
        "opencv-python",
        "pillow",
        "scikit-learn",
        "PyYAML",
        "beautifulsoup4",
    }


def test_unknown_module_passes_through_unchanged():
    deps = resolve_dependencies(_s("import rich"), set())
    assert _names(deps) == {"rich"}


def test_submodule_import_uses_top_level_name():
    deps = resolve_dependencies(_s("from PIL import Image"), set())
    assert _names(deps) == {"pillow"}


def test_relative_import_is_ignored():
    deps = resolve_dependencies(_s("from . import helper"), set())
    assert deps == ()


def test_try_except_import_is_optional():
    code = "try:\n    import numpy\nexcept ImportError:\n    numpy = None"
    deps = resolve_dependencies(_s(code), set())
    assert [d.optional for d in deps] == [True]


def test_heavy_package_is_flagged():
    deps = resolve_dependencies(_s("import torch"), set())
    assert [d.heavy for d in deps] == [True]


def test_requirements_takes_precedence():
    deps = resolve_dependencies(_s("import requests"), set(), "requests==2.31.0\nrich\n")
    assert _names(deps) == {"requests==2.31.0", "rich"}


def test_requirements_comments_and_blanks_ignored():
    deps = resolve_dependencies(_s(""), set(), "# komentarz\n\nrequests\n")
    assert _names(deps) == {"requests"}


def test_result_is_sorted_and_deduplicated():
    code = "import requests\nimport requests\nimport rich"
    deps = resolve_dependencies(_s(code), set())
    assert [d.package for d in deps] == ["requests", "rich"]


def test_alias_collision_dedupes_to_one_package_not_optional():
    code = (
        "import matplotlib.pyplot as plt\n"
        "try:\n"
        "    from mpl_toolkits.mplot3d import Axes3D\n"
        "except ImportError:\n"
        "    Axes3D = None\n"
    )
    deps = resolve_dependencies(_s(code), set())
    assert len(deps) == 1
    assert deps[0].package == "matplotlib"
    assert deps[0].optional is False


def test_win32_alias_collision_dedupes():
    code = "import win32com\nimport win32api"
    deps = resolve_dependencies(_s(code), set())
    assert len(deps) == 1
    assert deps[0].package == "pywin32"


def test_alias_collision_optional_when_all_guarded():
    code = (
        "try:\n"
        "    import win32com\n"
        "except ImportError:\n"
        "    win32com = None\n"
        "try:\n"
        "    import win32api\n"
        "except ImportError:\n"
        "    win32api = None\n"
    )
    deps = resolve_dependencies(_s(code), set())
    assert len(deps) == 1
    assert deps[0].package == "pywin32"
    assert deps[0].optional is True


def test_direct_reference_requirement_passes_through_unchanged():
    deps = resolve_dependencies(_s(""), set(), "git+https://github.com/x/y.git\n")
    assert _names(deps) == {"git+https://github.com/x/y.git"}


def test_plain_requirement_still_parses():
    deps = resolve_dependencies(_s(""), set(), "requests==2.31.0\n")
    assert _names(deps) == {"requests==2.31.0"}


# --- A07: poprawne parsowanie manifestu ---


def test_version_constraint_with_spaces_is_kept():
    """`requests >= 2.0` (ze spacjami) gubilo wersje w prostym regexie."""
    deps = resolve_dependencies(_s(""), set(), "requests >= 2.0\n")
    assert _names(deps) == {"requests>=2.0"}


def test_marker_for_other_platform_is_excluded():
    """Marker macOS nie instaluje paczki na docelowym Windowsie (A07)."""
    deps = resolve_dependencies(_s(""), set(), 'pyobjc; sys_platform == "darwin"\n')
    assert deps == ()


def test_marker_for_windows_is_kept():
    deps = resolve_dependencies(_s(""), set(), 'pywin32; sys_platform == "win32"\n')
    assert _names(deps) == {"pywin32"}


def test_extras_are_preserved():
    deps = resolve_dependencies(_s(""), set(), "uvicorn[standard]>=0.20\n")
    assert _names(deps) == {"uvicorn[standard]>=0.20"}


def test_recursive_requirements_are_followed(tmp_path):
    (tmp_path / "base.txt").write_text("rich\n", encoding="utf-8")
    main = tmp_path / "requirements.txt"
    main.write_text("-r base.txt\nrequests\n", encoding="utf-8")
    deps = resolve_dependencies(_s(""), set(), requirements_path=main)
    assert _names(deps) == {"rich", "requests"}


def test_recursive_requirements_cycle_does_not_hang(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("-r b.txt\nrich\n", encoding="utf-8")
    b.write_text("-r a.txt\nrequests\n", encoding="utf-8")
    deps = resolve_dependencies(_s(""), set(), requirements_path=a)
    assert _names(deps) == {"rich", "requests"}


def test_non_import_error_guard_is_not_optional():
    """`try: import x except ValueError` NIE czyni importu opcjonalnym (A07)."""
    code = "try:\n    import numpy\nexcept ValueError:\n    numpy = None\n"
    deps = resolve_dependencies(_s(code), set())
    assert [d.optional for d in deps] == [False]


def test_import_fallback_keeps_the_primary_required():
    """`try: import orjson / except ImportError: import simplejson` — przynajmniej
    jedna galaz musi byc zainstalowana. orjson (podstawowy) zostaje wymagany,
    simplejson jest opcjonalnym fallbackiem (A07)."""
    code = (
        "try:\n"
        "    import orjson\n"
        "except ImportError:\n"
        "    import simplejson\n"
    )
    deps = resolve_dependencies(_s(code), set())
    by_name = {d.package: d.optional for d in deps}
    assert by_name["orjson"] is False
    assert by_name["simplejson"] is True
