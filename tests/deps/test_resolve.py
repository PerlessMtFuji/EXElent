from pathlib import Path

from exelent.deps.resolve import resolve_dependencies, resolve_extra_modules
from exelent.models import Severity


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


# --- A07: pyproject.toml (PEP 621) ---


def test_pyproject_dependencies_are_read(tmp_path):
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        '[project]\nname = "x"\ndependencies = ["requests>=2.0", "rich"]\n',
        encoding="utf-8",
    )
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"requests>=2.0", "rich"}


def test_pyproject_build_system_requires_are_not_runtime_deps(tmp_path):
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        '[build-system]\nrequires = ["setuptools>=61", "wheel"]\n'
        '[project]\nname = "x"\ndependencies = ["rich"]\n',
        encoding="utf-8",
    )
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"rich"}


def test_pyproject_marker_for_other_platform_is_excluded(tmp_path):
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        '[project]\nname = "x"\ndependencies = ["pyobjc; sys_platform == \'darwin\'"]\n',
        encoding="utf-8",
    )
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert deps == ()


def test_import_not_in_empty_pyproject_deps_is_supplemented(tmp_path):
    # `dependencies = []` bywa scaffoldingiem (kod dla laika generuje AI), nie
    # deklaracja "zero zaleznosci". Import spoza niego dopisujemy ze sladem, bo
    # inaczej EXE wita "No module named requests" (A07).
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[project]\nname = "x"\ndependencies = []\n', encoding="utf-8")
    issues: list = []
    deps = resolve_dependencies(_s("import requests"), set(), pyproject_path=pp, issues=issues)
    assert _names(deps) == {"requests"}
    assert "dependency_not_declared" in {i.code for i in issues}


def test_pyproject_dynamic_dependencies_fall_back_to_imports(tmp_path):
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[project]\nname = "x"\ndynamic = ["dependencies"]\n', encoding="utf-8")
    issues: list = []
    deps = resolve_dependencies(_s("import rich"), set(), pyproject_path=pp, issues=issues)
    assert _names(deps) == {"rich"}
    assert "pyproject_dynamic_deps" in {i.code for i in issues}


def test_pyproject_without_project_table_falls_back_to_imports(tmp_path):
    # Np. projekt Poetry (deps w [tool.poetry]) — nie znamy tego formatu, wiec
    # spadamy do skanu importow zamiast oddawac pusta liste.
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[tool.poetry]\nname = "x"\n', encoding="utf-8")
    deps = resolve_dependencies(_s("import rich"), set(), pyproject_path=pp)
    assert _names(deps) == {"rich"}


# --- A07: pyproject.toml (Poetry [tool.poetry.dependencies]) ---


def _poetry(tmp_path: Path, body: str) -> Path:
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[tool.poetry.dependencies]\n" + body, encoding="utf-8")
    return pp


def test_poetry_caret_becomes_pep440_range(tmp_path):
    pp = _poetry(tmp_path, 'python = "^3.12"\nrequests = "^2.28"\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    # `python` to wersja interpretera, nie pakiet — nie instalujemy jej.
    assert _names(deps) == {"requests<3.0.0,>=2.28"}


def test_poetry_tilde_becomes_pep440_range(tmp_path):
    pp = _poetry(tmp_path, 'pandas = "~1.5"\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"pandas<1.6.0,>=1.5"}


def test_poetry_bare_version_is_exact(tmp_path):
    # Poetry: goła wersja bez operatora znaczy DOKŁADNIE tę wersję (`==`).
    pp = _poetry(tmp_path, 'click = "8.1.0"\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"click==8.1.0"}


def test_poetry_wildcard_is_any_version(tmp_path):
    pp = _poetry(tmp_path, 'rich = "*"\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"rich"}


def test_poetry_explicit_range_passes_through(tmp_path):
    pp = _poetry(tmp_path, 'numpy = ">=1.24,<2.0"\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"numpy<2.0,>=1.24"}


def test_poetry_table_with_extras(tmp_path):
    pp = _poetry(tmp_path, 'uvicorn = {version = "^0.20", extras = ["standard"]}\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"uvicorn[standard]<0.21.0,>=0.20"}


def test_poetry_optional_dependency_is_not_installed(tmp_path):
    # Zależność opcjonalna w Poetry żyje za `extras` i nie wchodzi do domyślnej
    # instalacji — pomijamy ją. Jeśli kod naprawdę ją importuje, złapie ją skan
    # importów (i dopisze ze śladem).
    pp = _poetry(tmp_path, 'numpy = {version = "^1.24", optional = true}\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert deps == ()


def test_poetry_marker_for_windows_is_kept(tmp_path):
    pp = _poetry(tmp_path, 'pywin32 = {version = "^3", markers = "sys_platform == \'win32\'"}\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"pywin32<4.0.0,>=3"}


def test_poetry_marker_for_other_platform_is_excluded(tmp_path):
    pp = _poetry(tmp_path, 'pyobjc = {version = "*", markers = "sys_platform == \'darwin\'"}\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert deps == ()


def test_poetry_python_constraint_excludes_for_target(tmp_path):
    # `python = "<3.8"` na zależności = instaluj tylko dla starego Pythona.
    # Docelowy build to 3.12, więc ta zależność odpada.
    pp = _poetry(tmp_path, 'legacy = {version = "^1.0", python = "<3.8"}\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert deps == ()


def test_poetry_python_constraint_kept_when_target_matches(tmp_path):
    pp = _poetry(tmp_path, 'modern = {version = "^1.0", python = ">=3.8"}\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"modern<2.0.0,>=1.0"}


def test_poetry_git_dependency_becomes_direct_reference(tmp_path):
    pp = _poetry(tmp_path, 'mylib = {git = "https://github.com/x/y.git"}\n')
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"mylib @ git+https://github.com/x/y.git"}


def test_poetry_path_dependency_is_skipped(tmp_path):
    # Lokalnej ścieżki nie zainstalujemy w izolowanym środowisku builda; jeśli
    # kod ją importuje, skan importów i tak ją dopisze.
    pp = _poetry(tmp_path, 'local = {path = "../local"}\n')
    deps = resolve_dependencies(_s("import rich"), set(), pyproject_path=pp)
    assert _names(deps) == {"rich"}


def test_poetry_multiple_constraints_pick_matching_python(tmp_path):
    pp = _poetry(
        tmp_path,
        "django = [\n"
        '    {version = "^4.0", python = ">=3.8"},\n'
        '    {version = "^3.0", python = "<3.8"},\n'
        "]\n",
    )
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"django<5.0.0,>=4.0"}


def test_poetry_dependencies_are_authoritative(tmp_path):
    # Wersje z Poetry są autorytatywne: skan importów NIE nadpisuje ich gołą nazwą.
    pp = _poetry(tmp_path, 'python = "^3.12"\nrequests = "^2.28"\n')
    deps = resolve_dependencies(_s("import requests"), set(), pyproject_path=pp)
    assert _names(deps) == {"requests<3.0.0,>=2.28"}


def test_import_not_in_poetry_is_supplemented_with_trace(tmp_path):
    pp = _poetry(tmp_path, 'python = "^3.12"\nrich = "^13.0"\n')
    issues: list = []
    deps = resolve_dependencies(_s("import requests"), set(), pyproject_path=pp, issues=issues)
    assert _names(deps) == {"rich<14.0.0,>=13.0", "requests"}
    traces = [i for i in issues if i.code == "dependency_not_declared"]
    assert [i.data["package"] for i in traces] == ["requests"]


def test_poetry_only_python_is_authoritative_empty(tmp_path):
    # Sam `python` bez pakietów = autor nie deklaruje bibliotek. Import spoza
    # tego dopisujemy ze śladem, zamiast oddawać po cichu tylko skan.
    pp = _poetry(tmp_path, 'python = "^3.12"\n')
    issues: list = []
    deps = resolve_dependencies(_s("import requests"), set(), pyproject_path=pp, issues=issues)
    assert _names(deps) == {"requests"}
    assert "dependency_not_declared" in {i.code for i in issues}


def test_project_table_wins_over_poetry(tmp_path):
    # PEP 621 to standard; gdy jest tabela [project], Poetry jej nie przesłania.
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        '[project]\nname = "x"\ndependencies = ["rich"]\n'
        '[tool.poetry.dependencies]\npython = "^3.12"\nrequests = "^2.28"\n',
        encoding="utf-8",
    )
    deps = resolve_dependencies(_s(""), set(), pyproject_path=pp)
    assert _names(deps) == {"rich"}


def test_requirements_txt_wins_over_poetry(tmp_path):
    pp = _poetry(tmp_path, 'python = "^3.12"\nrequests = "^2.28"\n')
    req = tmp_path / "requirements.txt"
    req.write_text("httpx==0.27.0\n", encoding="utf-8")
    deps = resolve_dependencies(_s(""), set(), requirements_path=req, pyproject_path=pp)
    assert _names(deps) == {"httpx==0.27.0"}


def test_requirements_txt_wins_over_pyproject(tmp_path):
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[project]\nname = "x"\ndependencies = ["rich"]\n', encoding="utf-8")
    req = tmp_path / "requirements.txt"
    req.write_text("requests==2.31.0\n", encoding="utf-8")
    deps = resolve_dependencies(_s(""), set(), requirements_path=req, pyproject_path=pp)
    assert _names(deps) == {"requests==2.31.0"}


def test_unreadable_pyproject_is_reported_and_falls_back(tmp_path):
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project\nname = broken toml", encoding="utf-8")
    issues: list = []
    deps = resolve_dependencies(_s("import rich"), set(), pyproject_path=pp, issues=issues)
    assert _names(deps) == {"rich"}
    assert "pyproject_unreadable" in {i.code for i in issues}


def test_import_not_in_requirements_is_supplemented_with_trace():
    """Kod importuje pakiet spoza requirements.txt: dopisujemy go i zostawiamy
    slad (A07). Manifest wygenerowany przez AI dla laika bywa niekompletny, a
    cichy brak konczy sie EXE bez modulu."""
    issues: list = []
    deps = resolve_dependencies(_s("import requests"), set(), "rich\n", issues=issues)
    assert _names(deps) == {"rich", "requests"}
    traces = [i for i in issues if i.code == "dependency_not_declared"]
    assert [i.data["package"] for i in traces] == ["requests"]
    assert traces[0].severity is Severity.WARNING


def test_import_covered_by_alias_is_not_flagged():
    """Kod importuje PIL, manifest deklaruje Pillow — to ten sam pakiet po
    normalizacji nazwy dystrybucji, wiec nic nie dopisujemy i nie ostrzegamy."""
    issues: list = []
    deps = resolve_dependencies(_s("from PIL import Image"), set(), "Pillow\n", issues=issues)
    assert _names(deps) == {"Pillow"}
    assert "dependency_not_declared" not in {i.code for i in issues}


def test_import_not_in_pyproject_is_supplemented_with_trace(tmp_path):
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[project]\nname = "x"\ndependencies = ["rich"]\n', encoding="utf-8")
    issues: list = []
    deps = resolve_dependencies(_s("import requests"), set(), pyproject_path=pp, issues=issues)
    assert _names(deps) == {"rich", "requests"}
    assert "dependency_not_declared" in {i.code for i in issues}


def test_undeclared_optional_import_is_supplemented_as_optional():
    """Import w try/except spoza manifestu: dopisany, ale opcjonalny (kod radzi
    sobie z jego brakiem), wiec slad jest INFO, nie ostrzezeniem."""
    code = "try:\n    import numpy\nexcept ImportError:\n    numpy = None\n"
    issues: list = []
    deps = resolve_dependencies(_s(code), set(), "rich\n", issues=issues)
    added = [d for d in deps if d.package == "numpy"]
    assert added and added[0].optional is True
    trace = next(i for i in issues if i.code == "dependency_not_declared")
    assert trace.severity is Severity.INFO


def test_declared_but_unused_dependency_is_not_flagged():
    """Kierunek odwrotny wylaczony: pakiet w manifescie, ktorego kod nie
    importuje, zostaje na liscie i NIE jest zglaszany (za duzo false-positives:
    importy dynamiczne, pakiety-dane, wtyczki)."""
    issues: list = []
    deps = resolve_dependencies(_s("import os"), set(), "rich\n", issues=issues)
    assert _names(deps) == {"rich"}
    assert "dependency_not_declared" not in {i.code for i in issues}


# --- A07: reczne dopisanie modulow (importy niewidoczne dla skanu) ---


def test_extra_module_becomes_hidden_import_and_package():
    hidden, deps = resolve_extra_modules(["sklearn"], set())
    assert hidden == ("sklearn",)
    # Nazwa najwyzszego poziomu po aliasie -> pakiet do instalacji.
    assert _names(deps) == {"scikit-learn"}


def test_extra_dotted_module_is_kept_whole_and_top_level_installed():
    hidden, deps = resolve_extra_modules(["scipy.stats"], set())
    assert hidden == ("scipy.stats",)
    assert _names(deps) == {"scipy"}


def test_extra_stdlib_module_is_hidden_but_not_installed():
    hidden, deps = resolve_extra_modules(["json.decoder"], set())
    assert hidden == ("json.decoder",)
    assert deps == ()


def test_extra_local_module_is_hidden_but_not_installed():
    hidden, deps = resolve_extra_modules(["mypkg.plugin"], {"mypkg"})
    assert hidden == ("mypkg.plugin",)
    assert deps == ()


def test_extra_modules_dedupe_and_skip_blanks():
    hidden, deps = resolve_extra_modules(["rich", "  ", "", "rich"], set())
    assert hidden == ("rich",)
    assert _names(deps) == {"rich"}


# --- A07: cykl i brakujacy plik manifestu jako Issue ---


def test_missing_referenced_requirements_is_reported(tmp_path):
    main = tmp_path / "requirements.txt"
    main.write_text("-r nie-ma.txt\nrich\n", encoding="utf-8")
    issues: list = []
    deps = resolve_dependencies(_s(""), set(), requirements_path=main, issues=issues)
    assert _names(deps) == {"rich"}
    assert "requirements_missing" in {i.code for i in issues}


def test_requirements_cycle_is_reported(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("-r b.txt\nrich\n", encoding="utf-8")
    b.write_text("-r a.txt\nrequests\n", encoding="utf-8")
    issues: list = []
    deps = resolve_dependencies(_s(""), set(), requirements_path=a, issues=issues)
    assert _names(deps) == {"rich", "requests"}
    assert "requirements_cycle" in {i.code for i in issues}


def test_shared_requirements_diamond_is_not_a_cycle(tmp_path):
    common = tmp_path / "common.txt"
    common.write_text("rich\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("-r common.txt\nrequests\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("-r common.txt\nhttpx\n", encoding="utf-8")
    main = tmp_path / "requirements.txt"
    main.write_text("-r a.txt\n-r b.txt\n", encoding="utf-8")
    issues: list = []
    deps = resolve_dependencies(_s(""), set(), requirements_path=main, issues=issues)
    assert _names(deps) == {"rich", "requests", "httpx"}
    assert "requirements_cycle" not in {i.code for i in issues}


def test_non_import_error_guard_is_not_optional():
    """`try: import x except ValueError` NIE czyni importu opcjonalnym (A07)."""
    code = "try:\n    import numpy\nexcept ValueError:\n    numpy = None\n"
    deps = resolve_dependencies(_s(code), set())
    assert [d.optional for d in deps] == [False]


def test_import_fallback_keeps_the_primary_required():
    """`try: import orjson / except ImportError: import simplejson` — przynajmniej
    jedna galaz musi byc zainstalowana. orjson (podstawowy) zostaje wymagany,
    simplejson jest opcjonalnym fallbackiem (A07)."""
    code = "try:\n    import orjson\nexcept ImportError:\n    import simplejson\n"
    deps = resolve_dependencies(_s(code), set())
    by_name = {d.package: d.optional for d in deps}
    assert by_name["orjson"] is False
    assert by_name["simplejson"] is True


# --- B04: dynamiczne importy zasilają zależności -----------------------------


def test_hidden_import_feeds_dependency_with_alias():
    """B04: `importlib.import_module('PIL.Image')` musi dodać `pillow` do
    paczek do instalacji, nie tylko do hidden imports."""
    deps = resolve_dependencies(_s(""), set(), hidden_imports=("PIL.Image",))
    assert _names(deps) == {"pillow"}


def test_hidden_import_local_module_is_not_installed():
    """Dynamiczny import lokalnego modułu nie powinien trafiać na PyPI."""
    deps = resolve_dependencies(_s(""), {"mypkg"}, hidden_imports=("mypkg.sub",))
    assert _names(deps) == set()


def test_hidden_import_stdlib_is_not_installed():
    """Dynamiczny import ze stdlib nie powinien trafiać na PyPI."""
    deps = resolve_dependencies(_s(""), set(), hidden_imports=("json.decoder",))
    assert _names(deps) == set()


def test_hidden_imports_dedupe_with_static():
    """Dynamiczny i statyczny import tego samego pakietu nie duplikują."""
    code = "import requests\n"
    deps = resolve_dependencies(_s(code), set(), hidden_imports=("requests.auth",))
    packages = [d.package for d in deps]
    assert packages.count("requests") == 1


# --- B05: semantyka constraints i pierwszeństwo manifestów -------------------


def test_constraint_does_not_install_package(tmp_path):
    """B05: sam `-c constraints.txt` z pinem `numpy` NIE instaluje numpy —
    tylko ogranicza wersję, jeśli numpy jest wymagany skądinąd."""
    constraints = tmp_path / "constraints.txt"
    constraints.write_text("numpy==1.24.0\n", encoding="utf-8")
    main = tmp_path / "requirements.txt"
    main.write_text(f"-c {constraints.name}\nrequests\n", encoding="utf-8")
    deps = resolve_dependencies(_s(""), set(), requirements_path=main)
    assert _names(deps) == {"requests"}
    # numpy NIE powinno być w zależnościach.
    assert not any("numpy" in d.package for d in deps)


def test_constraint_restricts_version_of_existing_requirement(tmp_path):
    """B05: constraint ogranicza wersję paczki, która jest wymagana."""
    constraints = tmp_path / "constraints.txt"
    constraints.write_text("requests<3.0\n", encoding="utf-8")
    main = tmp_path / "requirements.txt"
    main.write_text(f"-c {constraints.name}\nrequests>=2.0\n", encoding="utf-8")
    deps = resolve_dependencies(_s(""), set(), requirements_path=main)
    assert len(deps) == 1
    # Specyfikator powinien zawierać OBA ograniczenia.
    assert ">=2.0" in deps[0].package
    assert "<3.0" in deps[0].package


def test_root_requirements_wins_over_nested(tmp_path):
    """B05: główny requirements.txt ma pierwszeństwo przed zagnieżdżonym."""
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "requirements.txt").write_text("requests==1.0.0\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests>=2.28\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("import requests\n", encoding="utf-8")

    from exelent.analysis.project import analyze_project

    result = analyze_project(tmp_path)
    dep = next(d for d in result.dependencies if "requests" in d.package)
    # Manifest z korzenia (>=2.28) musi wygrać nad zagnieżdżonym (==1.0.0).
    assert ">=2.28" in dep.package
    assert "==1.0.0" not in dep.package


def test_constraint_with_r_recursive_and_c(tmp_path):
    """B05: `-r` rozwija jako wymagania, `-c` jako ograniczenia — obie
    referencje mogą współistnieć."""
    (tmp_path / "base.txt").write_text("flask\n", encoding="utf-8")
    (tmp_path / "pins.txt").write_text("flask==2.3.0\n", encoding="utf-8")
    main = tmp_path / "requirements.txt"
    main.write_text("-r base.txt\n-c pins.txt\n", encoding="utf-8")
    deps = resolve_dependencies(_s(""), set(), requirements_path=main)
    assert len(deps) == 1
    assert "flask" in deps[0].package.lower()
    assert "==2.3.0" in deps[0].package


# --- B05: pochodzenie zależności (origin) ---


def test_manifest_dependency_has_origin_manifest():
    """B05: zależność z requirements.txt ma origin='manifest'."""
    deps = resolve_dependencies(_s(""), set(), "requests>=2.0\n")
    assert deps[0].origin == "manifest"


def test_import_dependency_has_origin_import():
    """B05: zależność wykryta ze skanu importów ma origin='import'."""
    deps = resolve_dependencies(_s("import requests"), set())
    assert deps[0].origin == "import"


def test_dynamic_import_dependency_has_origin_dynamic():
    """B05: zależność z dynamicznego importu ma origin='dynamic'."""
    deps = resolve_dependencies(_s(""), set(), hidden_imports=("PIL.Image",))
    dep = next(d for d in deps if d.package == "pillow")
    assert dep.origin == "dynamic"


def test_user_module_dependency_has_origin_user():
    """B05: moduł dopisany ręcznie ma origin='user'."""
    _, deps = resolve_extra_modules(["sklearn"], set())
    assert deps[0].origin == "user"


# --- B05: diagnostyka nieobsługiwanych opcji ---


def test_unsupported_option_in_manifest_is_reported(tmp_path):
    """B05: opcje takie jak -e, --hash zgłaszane jako Issue."""
    main = tmp_path / "requirements.txt"
    main.write_text("-e ./local\n--hash=sha256:abc\nrequests\n", encoding="utf-8")
    issues: list = []
    deps = resolve_dependencies(_s(""), set(), requirements_path=main, issues=issues)
    assert _names(deps) == {"requests"}
    unsupported = [i for i in issues if i.code == "requirements_unsupported_option"]
    assert len(unsupported) == 2
    options = {i.data["option"] for i in unsupported}
    assert "-e" in options
    assert "--hash=sha256:abc" in options


# --- B05: requires-python ---


def test_requires_python_mismatch_is_reported(tmp_path):
    """B05: requires-python spoza docelowego 3.12 daje ostrzeżenie."""
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        '[project]\nname = "x"\nrequires-python = "<3.10"\ndependencies = ["rich"]\n',
        encoding="utf-8",
    )
    issues: list = []
    resolve_dependencies(_s(""), set(), pyproject_path=pp, issues=issues)
    assert "requires_python_mismatch" in {i.code for i in issues}


def test_requires_python_matching_is_silent(tmp_path):
    """B05: requires-python obejmujące 3.12 nie daje ostrzeżenia."""
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.8"\ndependencies = ["rich"]\n',
        encoding="utf-8",
    )
    issues: list = []
    resolve_dependencies(_s(""), set(), pyproject_path=pp, issues=issues)
    assert "requires_python_mismatch" not in {i.code for i in issues}


def test_constraint_preserves_origin(tmp_path):
    """B05: constraint nakładany na manifest zachowuje origin='manifest'."""
    constraints = tmp_path / "constraints.txt"
    constraints.write_text("requests<3.0\n", encoding="utf-8")
    main = tmp_path / "requirements.txt"
    main.write_text(f"-c {constraints.name}\nrequests>=2.0\n", encoding="utf-8")
    deps = resolve_dependencies(_s(""), set(), requirements_path=main)
    assert deps[0].origin == "manifest"
