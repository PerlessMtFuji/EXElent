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


def test_package_without_init_is_put_on_its_own_path(tmp_path):
    """Folder bez `__init__.py`: modul zostaje `main`, ale jego katalog trafia
    na `--paths`, wiec `import main` sie udaje — inaczej bylby `No module
    named main`."""
    _touch(tmp_path / "pkg" / "main.py", "print(1)")
    spec = resolve_entry(tmp_path, Path("pkg/main.py"))
    assert spec.run_module == "main"
    assert spec.roots == (tmp_path / "pkg",)
