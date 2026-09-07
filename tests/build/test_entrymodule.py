"""A03: kwalifikowana nazwa modulu wejsciowego i korzenie importow.

`plan.entry.stem` sprowadzalo `pkg/main.py` do `main`, wiec launcher robil
`runpy.run_module("main")`, a EXE umieralo na `ImportError: No module named
main`. Nazwa modulu musi byc liczona wzgledem korzenia importow, a ten korzen
trafic na `--paths`, zeby PyInstaller w ogole znalazl kod."""

from __future__ import annotations

from pathlib import Path

from exelent.build.entrymodule import resolve_entry


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_root_level_script_is_its_stem(tmp_path):
    _touch(tmp_path / "main.py", "print(1)")
    spec = resolve_entry(tmp_path, Path("main.py"))
    assert spec.run_module == "main"
    assert spec.collect_module == "main"
    assert spec.roots == (tmp_path,)


def test_package_module_is_dotted(tmp_path):
    _touch(tmp_path / "pkg" / "__init__.py")
    _touch(tmp_path / "pkg" / "main.py", "print(1)")
    spec = resolve_entry(tmp_path, Path("pkg/main.py"))
    assert spec.run_module == "pkg.main"
    assert spec.collect_module == "pkg.main"
    # Korzen importow to workspace — stad `pkg` jest widoczne jako pakiet.
    assert spec.roots == (tmp_path,)


def test_deeper_package_module_keeps_every_segment(tmp_path):
    _touch(tmp_path / "pkg" / "__init__.py")
    _touch(tmp_path / "pkg" / "sub" / "__init__.py")
    _touch(tmp_path / "pkg" / "sub" / "main.py", "print(1)")
    spec = resolve_entry(tmp_path, Path("pkg/sub/main.py"))
    assert spec.run_module == "pkg.sub.main"


def test_src_layout_roots_at_src(tmp_path):
    _touch(tmp_path / "src" / "pkg" / "__init__.py")
    _touch(tmp_path / "src" / "pkg" / "main.py", "print(1)")
    spec = resolve_entry(tmp_path, Path("src/pkg/main.py"))
    assert spec.run_module == "pkg.main"
    assert spec.roots == (tmp_path / "src",)


def test_package_run_via_dunder_main(tmp_path):
    """`python -m pkg`: runpy uruchamia `pkg`, ale zebrac trzeba `pkg.__main__`."""
    _touch(tmp_path / "pkg" / "__init__.py")
    _touch(tmp_path / "pkg" / "__main__.py", "print(1)")
    spec = resolve_entry(tmp_path, Path("pkg/__main__.py"))
    assert spec.run_module == "pkg"
    assert spec.collect_module == "pkg.__main__"
    assert spec.roots == (tmp_path,)


def test_lone_root_dunder_main_is_aliased_off_the_launcher_name(tmp_path):
    """Samotny `__main__.py` w korzeniu NIE moze uruchomic sie jako modul
    `__main__`: w zamrozonym EXE `__main__` to LAUNCHER, ktorego `__spec__`
    jest None. `runpy.run_module("__main__")` wola `find_spec("__main__")`,
    trafia na launcher i rzuca `ValueError: __main__.__spec__ is None` — build
    "sie udaje", a EXE konczy kodem 1. Kontrakt kieruje wtedy zbieranie i
    uruchomienie na bezpieczny alias, a plik do skopiowania niesie `alias` (B03).
    """
    _touch(tmp_path / "__main__.py", "print('hi')")
    spec = resolve_entry(tmp_path, Path("__main__.py"))
    assert spec.run_module != "__main__"
    assert spec.collect_module == spec.run_module
    assert spec.roots == (tmp_path,)
    assert spec.alias == (tmp_path / "__main__.py", tmp_path / f"{spec.run_module}.py")


def test_ordinary_entry_has_no_alias(tmp_path):
    """Alias to wylacznie ratunek dla samotnego `__main__.py`; zwykly skrypt i
    pakiet nie kopiuja niczego."""
    _touch(tmp_path / "main.py", "print(1)")
    assert resolve_entry(tmp_path, Path("main.py")).alias is None
    _touch(tmp_path / "pkg" / "__init__.py")
    _touch(tmp_path / "pkg" / "__main__.py", "print(1)")
    assert resolve_entry(tmp_path, Path("pkg/__main__.py")).alias is None


def test_package_without_init_is_put_on_its_own_path(tmp_path):
    """Folder bez `__init__.py`: modul zostaje `main`, ale jego katalog trafia
    na `--paths`, wiec `import main` sie udaje — inaczej bylby `No module
    named main`."""
    _touch(tmp_path / "pkg" / "main.py", "print(1)")
    spec = resolve_entry(tmp_path, Path("pkg/main.py"))
    assert spec.run_module == "main"
    assert spec.roots == (tmp_path / "pkg",)
