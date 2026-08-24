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
