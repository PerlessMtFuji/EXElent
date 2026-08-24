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
