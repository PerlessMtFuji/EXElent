# EXElent — poprawki UI: plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Naprawić siedem zgłoszeń z pierwszych testów EXElenta: tryb jednoplikowy, nawigację wstecz, realny postęp pobierania z prędkością i ETA, okno zgody przed pobieraniem, odsłonięcie postaci wyniku, oznaczenie rekomendacji i uczciwe szacowanie rozmiaru.

**Architecture:** Rdzeń (czysty Python, bez Qt) dostaje trzy nowe moduły — `Progress` jako jedyny kształt postępu, parser linii zdarzeń uv, oraz moduł rozmiarów łączący `uv pip install --dry-run` z PyPI JSON API. Warstwa `ui` dostaje dwa okna dialogowe, wątek preflight i wzbogacony `FactRow`. Kierunek zależności bez zmian: `ui` → rdzeń, nigdy odwrotnie.

**Tech Stack:** Python 3.12, PySide6 (Qt), pytest + pytest-qt, ruff, uv 0.8.17, PyInstaller 6.16.0.

**Spec:** `docs/superpowers/specs/2026-08-28-exelent-ui-poprawki-design.md`

## Global Constraints

Każde zadanie dziedziczy poniższe. Wartości przepisane dosłownie ze specyfikacji i z `pyproject.toml`.

- **Rdzeń nie importuje Qt.** Żaden plik poza `exelent/ui/` nie może importować `PySide6`, `PyQt5` ani `PyQt6`. Pilnuje `tests/test_layering.py`.
- **Rdzeń nigdy nie zwraca tekstu dla użytkownika** — zwraca `Issue` z kodem, a zdanie powstaje w `exelent/i18n/`.
- **Każdy nowy kod `Issue` i każda nowa faza postępu musi mieć zdanie w OBU katalogach** (`exelent/i18n/pl.py` i `exelent/i18n/en.py`). Pilnuje `tests/i18n/test_translations.py::test_both_catalogs_have_identical_keys` oraz `::test_every_issue_code_the_core_can_produce_is_translated`.
- **Inwentarz i18n skanuje AST rdzenia** (`tests/i18n/inventory.py`). Kod `Issue` składany dynamicznie musi być zadeklarowany w `DECLARED_DYNAMIC_ISSUES`, faza dynamiczna w `DECLARED_DYNAMIC_PHASES`, a `data` niebędące literalnym słownikiem — w `DECLARED_DATA`.
- **Struktury danych są niemutowalne:** `@dataclass(frozen=True)`.
- **Żadnej sieci w testach.** Odpowiedzi PyPI i wyjście uv wchodzą do testów jako nagrane fixture'y.
- **ruff:** `line-length = 100`, `target-version = "py312"`. Po każdym zadaniu: `.venv/Scripts/python.exe -m ruff check exelent tests` oraz `... -m ruff format --check exelent tests`.
- **Wersje przypięte, nigdy „latest":** `UV_VERSION = "0.8.17"`, `TARGET_PYTHON = "3.12"`, `PYINSTALLER_SPEC = "pyinstaller==6.16.0"`.
- **Komunikaty commitów bez znaków diakrytycznych** — tak wygląda cała dotychczasowa historia repozytorium (np. `fix: anulowanie nie jest awaria, jedno zrodlo prawdy o kopii roboczej`). Treść plików źródłowych i katalogów i18n diakrytyki używa normalnie.
- **Interpreter do wszystkich komend:** `.venv/Scripts/python.exe`.
- **Gałąź bazowa:** `master`.

### Punkt wyjścia

Zmierzony przed rozpoczęciem: `pytest -m "not slow"` → **503 przechodzące, 1 padający**. Padający to `tests/build/test_build_backend.py::test_cancel_during_silent_subprocess_returns_promptly`, który asertuje czas ścienny `elapsed < 3.0`; osobno na bezczynnej maszynie przechodzi 5/5 w 0,7–1,1 s. To niestabilność wrażliwa na obciążenie. **Nie rozluźniaj tego progu.** Zadanie 11 przepisuje kod, którego ten test dotyczy — tam jest osobny krok na przebieg pod obciążeniem.

---

## Struktura plików

**Nowe pliki rdzenia:**

| Plik | Odpowiedzialność |
|---|---|
| `exelent/settings.py` | odczyt/zapis `settings.json`, wyłącznie wartości skalarne |
| `exelent/runtime/progress.py` | `Progress` — jedyny kształt postępu w całym programie |
| `exelent/runtime/uvlog.py` | linia tekstu uv → typowane zdarzenie; zero wiedzy o tym, kto ją czyta |
| `exelent/deps/sizes.py` | tabela wkładów do EXE, rozmiary kół z PyPI, rozwiązanie zależności przez `--dry-run` |

**Nowe pliki UI:**

| Plik | Odpowiedzialność |
|---|---|
| `exelent/ui/format.py` | formatowanie rozmiarów i czasu — jedno źródło dla czterech miejsc |
| `exelent/ui/preflight.py` | `QThread` liczący rozmiar pobierania dla ekranu 2 |
| `exelent/ui/dialog_download.py` | okno zgody przed pobieraniem |
| `exelent/ui/dialog_settings.py` | okno ustawień |

**Nowe pliki testowe:** `tests/ui/test_rows.py`, `tests/ui/test_format.py`, `tests/ui/test_preflight.py`, `tests/ui/test_dialogs.py`, `tests/runtime/test_uvlog.py`, `tests/runtime/test_progress.py`, `tests/deps/test_sizes.py`, `tests/test_settings.py`, `tests/deps/fixtures/` (nagrane odpowiedzi PyPI i wyjście uv).

**Kolejność.** Specyfikacja §12 stawia rozmiary (§7) przed protokołem postępu (§8), ale rozpoznawanie wyjścia `--dry-run` używa tego samego parsera co pasek postępu. Parser (zadanie 9) idzie więc **przed** rozwiązywaniem zależności (zadanie 17). Reszta kolejności ze specyfikacji zostaje.

---

### Task 1: FactRow — rekomendacja i link „przywróć zalecane"

**Files:**
- Modify: `exelent/ui/rows.py`
- Modify: `exelent/i18n/pl.py`, `exelent/i18n/en.py`
- Test: `tests/ui/test_rows.py` (nowy)

**Interfaces:**
- Consumes: nic.
- Produces: `FactRow.set_recommended(value: str) -> None`, `FactRow.restore_requested` (`Signal()`), `FactRow.restore_visible() -> bool`. Zadanie 2 na nich stoi.

`FactRow` nie wie, jak ustawić wartość w edytorze — lista rozwijana, pole tekstowe i przycisk robią to inaczej. Dlatego wiersz tylko **zgłasza** chęć przywrócenia sygnałem, a ustawia ekran 2. Wiersz porównuje napisy (`value_text()`), bo to jedyne, co widzi niezależnie od typu edytora.

- [ ] **Step 1: Dopisz klucz `review_restore` do obu katalogów**

W `exelent/i18n/pl.py`, w sekcji „ekran 2":

```python
    "review_restore": "przywróć zalecane",
```

W `exelent/i18n/en.py`, w tej samej sekcji:

```python
    "review_restore": "restore recommended",
```

- [ ] **Step 2: Napisz padający test**

Utwórz `tests/ui/test_rows.py`:

```python
"""Wiersz faktu: znacznik pewnosci, rekomendacja, link powrotu.

Rekomendacja odpowiada na pytanie, ktore uzytkownik zadaje sobie pol godziny
pozniej: "co program wybral sam, zanim to zmienilem". Wiersz porownuje NAPISY,
bo to jedyne, co widzi niezaleznie od tego, czy edytorem jest lista, pole
tekstowe czy przycisk.
"""

import pytest
from PySide6.QtWidgets import QComboBox

from exelent.ui.rows import FactRow


@pytest.fixture
def combo_row(qtbot):
    combo = QComboBox()
    combo.addItem("Program w oknie (zalecane)", "windowed")
    combo.addItem("Program konsolowy", "console")
    row = FactRow("Rodzaj programu", combo)
    qtbot.addWidget(row)
    return row, combo


def test_link_is_hidden_when_nothing_is_recommended(combo_row):
    row, _combo = combo_row
    assert row.restore_visible() is False


def test_link_is_hidden_while_the_value_matches_the_recommendation(combo_row):
    row, _combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    assert row.restore_visible() is False


def test_link_appears_when_the_user_picks_something_else(combo_row):
    row, combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    combo.setCurrentIndex(1)
    assert row.restore_visible() is True


def test_link_disappears_again_when_the_value_comes_back(combo_row):
    row, combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    combo.setCurrentIndex(1)
    combo.setCurrentIndex(0)
    assert row.restore_visible() is False


def test_clicking_the_link_asks_the_screen_instead_of_setting_the_value(qtbot, combo_row):
    """Wiersz nie umie ustawic wartosci w dowolnym edytorze — ma o to poprosic.

    Gdyby probowal sam, musialby znac QComboBox, QLineEdit i QPushButton, czyli
    dokladnie te wiedze, ktorej `value_text()` celowo unika.
    """
    row, combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    combo.setCurrentIndex(1)
    with qtbot.waitSignal(row.restore_requested, timeout=1000):
        row.restore_button().click()
    assert combo.currentIndex() == 1  # wiersz NIE ustawil nic sam
```

- [ ] **Step 3: Uruchom test i potwierdź, że pada**

Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_rows.py -v`
Expected: FAIL — `AttributeError: 'FactRow' object has no attribute 'restore_visible'`

- [ ] **Step 4: Zaimplementuj**

W `exelent/ui/rows.py` zamień zawartość klasy na poniższą (import `Signal` i `QPushButton` dochodzi do listy importów, `t` z `exelent.i18n`):

```python
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from exelent.i18n import t

CERTAIN = "✓"
UNCERTAIN = "?"

# Sygnaly zmiany, ktore moze miec edytor. Kolejnosc ma znaczenie: `QComboBox`
# ma OBA, a `currentIndexChanged` jest wierniejszy — `textChanged` nie istnieje
# na liscie, za to `QLineEdit` ma tylko jego.
_CHANGE_SIGNALS = ("currentIndexChanged", "textChanged")


class FactRow(QWidget):
    restore_requested = Signal()

    def __init__(self, caption: str, editor: QWidget) -> None:
        super().__init__()
        self._marker = QLabel(CERTAIN)
        self._marker.setFixedWidth(18)
        self._caption = QLabel(caption, objectName="Muted")
        self._caption.setMinimumWidth(150)
        self._editor = editor
        self._recommended: str | None = None

        self._restore = QPushButton(t("review_restore"), objectName="Link")
        self._restore.setVisible(False)
        self._restore.clicked.connect(self.restore_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(12)
        layout.addWidget(self._marker)
        layout.addWidget(self._caption)
        layout.addWidget(editor, stretch=1)
        layout.addWidget(self._restore)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        for name in _CHANGE_SIGNALS:
            signal = getattr(editor, name, None)
            if signal is not None:
                signal.connect(self._sync_restore)
                break

    def set_certain(self, certain: bool) -> None:
        """Znacznik pewności. `?` nie jest ozdobą: analiza, która nie wie,
        mówi to wprost, a zdanie z tym samym rozpoznaniem stoi w ostrzeżeniach
        ekranu — użytkownik dostaje sygnał i jego wyjaśnienie.

        Pewność jest NIEZALEŻNA od rekomendacji: mówi, czy analiza wiedziała,
        a nie czy użytkownik coś zmienił. Jeden symbol na dwa znaczenia był
        wariantem odrzuconym w specyfikacji.
        """
        self._marker.setText(CERTAIN if certain else UNCERTAIN)

    def set_recommended(self, value: str) -> None:
        """Zapamiętuje, co zaproponowała analiza. Ustalane RAZ, przy wczytaniu.

        Rekomendacja przeliczana po każdej zmianie użytkownika goniłaby jego
        wybór i nigdy nie zapaliłaby linku — czyli nie byłaby rekomendacją.
        """
        self._recommended = value
        self._sync_restore()

    def _sync_restore(self, *_args) -> None:
        # `*_args` bo Qt poda numer indeksu albo nowy tekst, zaleznie od tego,
        # ktory sygnal edytora sie podpial.
        differs = self._recommended is not None and self.value_text() != self._recommended
        self._restore.setVisible(differs)

    def restore_visible(self) -> bool:
        """Czy link jest POKAZANY jako element wiersza.

        Świadomie nie `isVisible()`: ono mówi o widoczności NA EKRANIE i oddaje
        False dla wszystkiego, dopóki okno nie zostało pokazane — czyli w
        każdym teście. Ten sam błąd zjadł już `_toggle_advanced` i `_toggle_log`
        (patrz ich komentarze).
        """
        return not self._restore.isHidden()

    def restore_button(self) -> QPushButton:
        return self._restore

    def marker(self) -> str:
        return self._marker.text()

    def caption_text(self) -> str:
        return self._caption.text()

    def value_text(self) -> str:
        """To, co w tym wierszu widać jako wartość — bez względu na to, czy
        edytorem jest lista, pole tekstowe czy przycisk."""
        for getter in ("currentText", "text"):
            method = getattr(self._editor, getter, None)
            if callable(method):
                return method()
        return ""
```

- [ ] **Step 5: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_rows.py tests/ui/test_screen_review.py tests/i18n -v`
Expected: PASS (wszystkie)

- [ ] **Step 6: Lint i commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
.venv/Scripts/python.exe -m ruff format --check exelent tests
git add exelent/ui/rows.py exelent/i18n/pl.py exelent/i18n/en.py tests/ui/test_rows.py
git commit -m "feat: wiersz faktu pamieta rekomendacje i oferuje powrot do niej"
```

---

### Task 2: Ekran 2 — postać wyniku na karcie, rekomendacje, koniec „Zaawansowanych"

**Files:**
- Modify: `exelent/ui/screen_review.py`
- Modify: `exelent/i18n/pl.py`, `exelent/i18n/en.py` (usunięcie `review_advanced`)
- Test: `tests/ui/test_screen_review.py`

**Interfaces:**
- Consumes: `FactRow.set_recommended`, `FactRow.restore_requested`, `FactRow.restore_visible` (zadanie 1).
- Produces: `ReviewScreen.row_mode` (`FactRow`) — zadanie 19 dopisuje pod nim rozmiar pobierania.

Dopisek „(zalecane)" jest **wyłącznie etykietą**. `currentData()` musi nadal oddawać `AppKind`/`OutputMode`/`Path`, bo `_emit_plan` już raz przewrócił się na tym, że Qt oddaje dane pozycji jako goły napis — i wtedy użytkownik dostawał czarną konsolę za każdym oknem.

- [ ] **Step 1: Napisz padające testy**

Dopisz do `tests/ui/test_screen_review.py`:

```python
def test_output_mode_is_visible_without_clicking_anything(screen, tmp_path):
    """Postac wyniku to informacja o tym, co uzytkownik dostanie na koncu.

    Schowana pod przelacznikiem "Zaawansowane" byla widoczna tylko dla tych,
    ktorzy i tak wiedza, czego szukac.
    """
    _load(screen, tmp_path, {"main.py": "print('x')\n"})
    assert screen.row_mode.caption_text() == t("review_mode")
    assert screen.row_mode.isHidden() is False


def test_the_advanced_panel_is_gone_entirely(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "print('x')\n"})
    assert not hasattr(screen, "advanced_toggle")
    assert "review_advanced" not in CATALOGS[current_language()]


def test_recommended_item_is_labelled_but_data_stays_typed(screen, tmp_path):
    """Dopisek jest ETYKIETA. `currentData()` ma nadal oddawac enum.

    Regresja tego rodzaju nie widac na ekranie: plan po cichu dostaje napis
    zamiast `AppKind` i uzytkownik, ktory wybral okno, dostaje czarna konsole.
    """
    _load(screen, tmp_path, {"main.py": "import tkinter\ntkinter.Tk()\n"})
    assert "(" in screen.kind_combo.currentText()
    assert screen.kind_combo.currentData() in (AppKind.WINDOWED, AppKind.CONSOLE)
    assert isinstance(screen.mode_combo.currentData(), OutputMode)


def test_restore_link_returns_the_recommended_value(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "print('x')\n"})
    recommended = screen.kind_combo.currentText()
    other = 1 - screen.kind_combo.currentIndex()
    screen.kind_combo.setCurrentIndex(other)
    assert screen.row_kind.restore_visible() is True

    screen.row_kind.restore_button().click()
    assert screen.kind_combo.currentText() == recommended
    assert screen.row_kind.restore_visible() is False
```

- [ ] **Step 2: Uruchom testy i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_screen_review.py -v -k "output_mode or advanced_panel or recommended_item or restore_link"`
Expected: FAIL — `AttributeError: 'ReviewScreen' object has no attribute 'row_mode'`

- [ ] **Step 3: Usuń panel zaawansowany i wstaw wiersz postaci wyniku**

W `exelent/ui/screen_review.py` usuń stałe `COLLAPSED` i `EXPANDED`, metody `_show_advanced` i `_toggle_advanced` oraz cały blok budujący `self.advanced` i `self.advanced_toggle`. W `__init__`, po `self.row_icon`, dodaj:

```python
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(t("mode_onefile"), OutputMode.ONEFILE)
        self.mode_combo.addItem(t("mode_onedir"), OutputMode.ONEDIR)
        self.row_mode = FactRow(t("review_mode"), self.mode_combo)
```

Zmień pętlę budującą kartę tak, by objęła piąty wiersz:

```python
        for row in (self.row_entry, self.row_kind, self.row_name, self.row_icon, self.row_mode):
            card_layout.addWidget(row)
```

W układzie zewnętrznym usuń `outer.addWidget(self.advanced_toggle, ...)` i `outer.addWidget(self.advanced)`.

- [ ] **Step 4: Dodaj etykietowanie rekomendacji i podłącz przywracanie**

Dodaj na poziomie modułu:

```python
def _mark_recommended(combo: QComboBox, index: int) -> None:
    """Dopisuje „(zalecane)" do etykiety pozycji, NIE ruszając jej danych.

    `setItemText` zmienia wyłącznie napis; `itemData` zostaje tym, czym było.
    To rozróżnienie jest jedyną rzeczą, która dzieli ten ekran od regresji, w
    której `currentData()` oddaje napis i program konsolowy udaje okienkowy.
    """
    if index < 0:
        return
    combo.setItemText(index, f"{combo.itemText(index)} {t('review_recommended_suffix')}")
```

W `__init__`, po utworzeniu wierszy, podłącz przywracanie:

```python
        for row, combo in (
            (self.row_entry, self.entry_combo),
            (self.row_kind, self.kind_combo),
            (self.row_mode, self.mode_combo),
        ):
            row.restore_requested.connect(
                lambda _checked=False, r=row, c=combo: c.setCurrentIndex(
                    max(c.findText(r.recommended_text() or ""), 0)
                )
            )
```

Dopisz do `FactRow` w `exelent/ui/rows.py` odczyt rekomendacji (ekran musi wiedzieć, dokąd wracać):

```python
    def recommended_text(self) -> str | None:
        return self._recommended
```

- [ ] **Step 5: Ustaw rekomendacje w `load()`**

W `exelent/ui/screen_review.py`, w metodzie `load`, zaraz po wypełnieniu każdej listy:

```python
        self.entry_combo.clear()
        for candidate in analysis.entry_candidates:
            self.entry_combo.addItem(_label_for(analysis.root, candidate.path), candidate.path)
        _mark_recommended(self.entry_combo, 0)
        self.entry_combo.setCurrentIndex(0 if analysis.entry_candidates else -1)
        self.row_entry.set_recommended(self.entry_combo.currentText())
        self.row_entry.set_certain(analysis.entry_certain and bool(analysis.entry_candidates))
```

```python
        kind_index = max(self.kind_combo.findData(analysis.app_kind), 0)
        _mark_recommended(self.kind_combo, kind_index)
        self.kind_combo.setCurrentIndex(kind_index)
        self.row_kind.set_recommended(self.kind_combo.currentText())
        self.row_kind.set_certain(analysis.app_kind_certain)
```

```python
        mode_index = max(self.mode_combo.findData(analysis.output_mode), 0)
        _mark_recommended(self.mode_combo, mode_index)
        self.mode_combo.setCurrentIndex(mode_index)
        self.row_mode.set_recommended(self.mode_combo.currentText())
```

`load()` bywa wołane drugi raz w tej samej sesji, a `_mark_recommended` dopisuje sufiks do istniejącej etykiety. Dla `kind_combo` i `mode_combo`, których pozycje powstają raz w `__init__`, sufiks by się **skleił dwa razy**. Zresetuj więc ich etykiety na początku `load()`:

```python
        # Etykiety list o stalej zawartosci wracaja do postaci bazowej, bo
        # `_mark_recommended` DOPISUJE sufiks — drugi projekt w tej samej sesji
        # dostawalby "Program w oknie (zalecane) (zalecane)".
        self.kind_combo.setItemText(0, t("kind_windowed"))
        self.kind_combo.setItemText(1, t("kind_console"))
        self.mode_combo.setItemText(0, t("mode_onefile"))
        self.mode_combo.setItemText(1, t("mode_onedir"))
```

- [ ] **Step 6: Dodaj klucz sufiksu, usuń klucz panelu**

W `exelent/i18n/pl.py`: usuń `"review_advanced"`, dodaj `"review_recommended_suffix": "(zalecane)",`.
W `exelent/i18n/en.py`: usuń `"review_advanced"`, dodaj `"review_recommended_suffix": "(recommended)",`.

- [ ] **Step 7: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/ui tests/i18n -v`
Expected: PASS

- [ ] **Step 8: Lint i commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
.venv/Scripts/python.exe -m ruff format --check exelent tests
git add exelent/ui/screen_review.py exelent/ui/rows.py exelent/i18n tests/ui/test_screen_review.py
git commit -m "feat: postac wyniku na karcie, rekomendacje widoczne i odwracalne"
```

---

### Task 3: Powrót z ekranu 2 na ekran 1

**Files:**
- Modify: `exelent/ui/screen_review.py`, `exelent/ui/app.py`
- Modify: `exelent/i18n/pl.py`, `exelent/i18n/en.py`
- Test: `tests/ui/test_screen_review.py`, `tests/ui/test_app_shell.py`

**Interfaces:**
- Consumes: `MainWindow.go_to`, `DropScreen.refresh_recent` (istniejące).
- Produces: `ReviewScreen.back_requested` (`Signal()`).

- [ ] **Step 1: Napisz padające testy**

Do `tests/ui/test_screen_review.py`:

```python
def test_back_button_emits_instead_of_navigating(qtbot, screen, tmp_path):
    """Ekran nie wie o istnieniu innych ekranow — zglasza zamiar sygnalem.

    To ta sama zasada, ktora trzyma `build_requested`: kolejnosc ekranow zna
    wylacznie okno.
    """
    _load(screen, tmp_path, {"main.py": "print('x')\n"})
    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        screen.back_button.click()
```

Do `tests/ui/test_app_shell.py`:

```python
def test_back_from_review_returns_to_the_drop_screen(qtbot, tmp_path):
    from exelent.ui.app import SCREEN_DROP, SCREEN_REVIEW, MainWindow

    project = tmp_path / "projekt"
    project.mkdir()
    (project / "main.py").write_text("print('x')\n", encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    window.screen_drop.folder_chosen.emit(project)
    assert window.stack.currentIndex() == SCREEN_REVIEW

    window.screen_review.back_button.click()
    assert window.stack.currentIndex() == SCREEN_DROP
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_screen_review.py::test_back_button_emits_instead_of_navigating tests/ui/test_app_shell.py::test_back_from_review_returns_to_the_drop_screen -v`
Expected: FAIL — `AttributeError: 'ReviewScreen' object has no attribute 'back_requested'`

- [ ] **Step 3: Zaimplementuj w ekranie 2**

W `exelent/ui/screen_review.py`, w klasie, obok istniejącego sygnału:

```python
    build_requested = Signal(object)
    back_requested = Signal()
```

W `__init__`, obok przycisku budowania:

```python
        self.back_button = QPushButton(t("review_back"), objectName="Link")
        self.back_button.clicked.connect(self.back_requested)
```

W układzie zewnętrznym zamień samotny `addWidget(self.build_button, ...)` na wiersz z obydwoma przyciskami:

```python
        actions = QHBoxLayout()
        actions.addWidget(self.back_button)
        actions.addStretch(1)
        actions.addWidget(self.build_button)
        outer.addLayout(actions)
```

- [ ] **Step 4: Podepnij w oknie**

W `exelent/ui/app.py`, w `__init__`, obok istniejącego połączenia:

```python
        self.screen_review.build_requested.connect(self._on_build_requested)
        self.screen_review.back_requested.connect(self._on_back_to_drop)
```

I metoda:

```python
    def _on_back_to_drop(self) -> None:
        """Powrót na start bez budowania.

        Lista ostatnich jest odświeżana, bo projekt wybrany przed chwilą już do
        niej trafił (`DropScreen._choose` woła `recent.remember` przed emisją),
        a ekran 1 czytał ją ostatnio przy uruchamianiu programu.
        """
        self.screen_drop.refresh_recent()
        self.go_to(SCREEN_DROP)
```

- [ ] **Step 5: Dodaj klucz**

`exelent/i18n/pl.py`: `"review_back": "← Wstecz",`
`exelent/i18n/en.py`: `"review_back": "← Back",`

- [ ] **Step 6: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/ui tests/i18n -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/ui/screen_review.py exelent/ui/app.py exelent/i18n tests/ui
git commit -m "feat: powrot z ekranu przegladu na ekran wyboru zrodla"
```

---

### Task 4: Powrót z ekranu 3 do ustawień i blokada cofania w trakcie budowania

**Files:**
- Modify: `exelent/ui/screen_build.py`, `exelent/ui/app.py`
- Modify: `exelent/i18n/pl.py`, `exelent/i18n/en.py`
- Test: `tests/ui/test_screen_build.py`, `tests/ui/test_app_shell.py`

**Interfaces:**
- Consumes: `BuildWorker.is_running()` (istnieje), `ReviewScreen.load` (istnieje).
- Produces: `BuildScreen.back_to_review` (`Signal()`).

Powrót nie może kosztować ponownego skanu katalogu, więc `ReviewScreen` po prostu **nie jest czyszczony** — jest widgetem długożyjącym i trzyma ostatnią analizę w `self._analysis`. Przycisk pojawia się tylko w stanach *nie udało się* i *przerwane*; po sukcesie właściwą akcją jest istniejące „Zrób następny program".

- [ ] **Step 1: Napisz padające testy**

Do `tests/ui/test_screen_build.py` (istnieją tam już helpery budujące `BuildResult` — użyj tych samych):

```python
def test_back_to_review_offered_after_failure(qtbot, screen):
    screen.on_finished(BuildResult(ok=False, issues=(Issue("disk_full", Severity.BLOCKER),)))
    assert screen.back_button.isHidden() is False


def test_back_to_review_offered_after_cancel(qtbot, screen):
    screen.on_finished(BuildResult(ok=False, issues=(Issue("build_cancelled", Severity.INFO),)))
    assert screen.back_button.isHidden() is False


def test_back_to_review_not_offered_after_success(qtbot, screen, tmp_path):
    artifact = tmp_path / "Program.exe"
    artifact.write_bytes(b"x" * 2048)
    screen.on_finished(BuildResult(ok=True, artifact=artifact, size_bytes=2048))
    assert screen.back_button.isHidden() is True


def test_back_button_is_hidden_while_running(qtbot, screen, tmp_path):
    """Kazdy stan ma OKRESLAC caly ekran, a nie dokladac sie do poprzedniego.

    Ten sam blad zjadl juz "Zglos na GitHubie", ktory zostawal po porazce na
    ekranie przerwania — patrz `_hide_all_actions`.
    """
    screen.on_finished(BuildResult(ok=False, issues=(Issue("disk_full", Severity.BLOCKER),)))
    screen.start(_plan(tmp_path))
    assert screen.back_button.isHidden() is True
```

Do `tests/ui/test_app_shell.py`:

```python
def test_going_back_is_blocked_while_a_build_runs(qtbot, tmp_path, monkeypatch):
    """Drugi build w trakcie pierwszego jest odrzucany przez `BuildWorker`
    po cichu — uzytkownik zobaczylby ekran postepu, ktory nigdy nie ruszy."""
    from exelent.ui.app import SCREEN_BUILD, MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window.worker, "is_running", lambda: True)
    window.go_to(SCREEN_BUILD)

    window.screen_build.back_to_review.emit()
    assert window.stack.currentIndex() == SCREEN_BUILD
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_screen_build.py tests/ui/test_app_shell.py -v -k "back"`
Expected: FAIL — `AttributeError: 'BuildScreen' object has no attribute 'back_button'`

- [ ] **Step 3: Zaimplementuj w ekranie 3**

W `exelent/ui/screen_build.py`:

```python
class BuildScreen(QWidget):
    restart_requested = Signal()
    back_to_review = Signal()
```

W `__init__`, obok pozostałych przycisków:

```python
        self.back_button = QPushButton(t("build_back_to_review"))
        self.back_button.clicked.connect(self.back_to_review)
```

Dopisz `self.back_button` do krotki w `_hide_all_actions` **oraz** do pętli budującej `actions` (przed `self.cancel_button`). W `_show_cancelled` i `_show_failure` dodaj:

```python
        self.back_button.setVisible(True)
```

W `_show_success` **nie** dodawaj nic — `_hide_all_actions` zdejmuje przycisk na wejściu każdego stanu, więc po sukcesie zostaje ukryty bez dodatkowej linijki.

- [ ] **Step 4: Podepnij w oknie z blokadą**

W `exelent/ui/app.py`, w `__init__`:

```python
        self.screen_build.restart_requested.connect(self._on_restart)
        self.screen_build.back_to_review.connect(self._on_back_to_review)
```

I metoda:

```python
    def _on_back_to_review(self) -> None:
        """Powrót na ekran 2 z ZACHOWANĄ analizą.

        Ekran 2 jest widgetem długożyjącym i trzyma ostatnią `ProjectAnalysis`
        w swoim polu, więc poprawienie nazwy po nieudanym buildzie nie kosztuje
        ponownego skanu katalogu.

        Blokada przy trwającym buildzie nie jest ostrożnością na wyrost:
        `BuildWorker.start` odrzuca drugi build po cichu, więc użytkownik
        dostałby ekran postępu, który nigdy nie ruszy.
        """
        if self.worker.is_running():
            return
        self.go_to(SCREEN_REVIEW)
```

Zabezpiecz tą samą blokadą `_on_back_to_drop` z zadania 3 i `_on_restart`:

```python
        if self.worker.is_running():
            return
```

- [ ] **Step 5: Dodaj klucz**

`exelent/i18n/pl.py`: `"build_back_to_review": "← Wróć do ustawień",`
`exelent/i18n/en.py`: `"build_back_to_review": "← Back to settings",`

- [ ] **Step 6: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/ui tests/i18n -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/ui/screen_build.py exelent/ui/app.py exelent/i18n tests/ui
git commit -m "feat: powrot do ustawien po nieudanym buildzie, cofanie zablokowane w trakcie"
```

---

### Task 5: `single_file` w modelach i `scan_single_file`

**Files:**
- Modify: `exelent/models.py`, `exelent/analysis/scanner.py`
- Test: `tests/analysis/test_scanner.py`

**Interfaces:**
- Consumes: `looks_like_python` (istnieje w `scanner.py`).
- Produces: `ScanResult.single_file: Path | None`, `ProjectAnalysis.single_file: Path | None`, `scan_single_file(path: Path) -> ScanResult`.

Katalog nadrzędny **nie jest projektem**, więc leżące w nim `requirements.txt`, `icon.png` czy pliki danych nie mają z upuszczonym plikiem nic wspólnego i nie trafiają do wyniku.

- [ ] **Step 1: Napisz padające testy**

Do `tests/analysis/test_scanner.py`:

```python
def test_single_file_scan_ignores_everything_around_it(tmp_path):
    """Uzytkownik wskazal PLIK. Katalog nadrzedny to Pobrane, nie projekt."""
    (tmp_path / "test.py").write_text("print('x')\n", encoding="utf-8")
    (tmp_path / "cudzy.py").write_text("print('obcy')\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (tmp_path / "icon.ico").write_bytes(b"\x00")
    (tmp_path / "dane.csv").write_text("a,b\n", encoding="utf-8")

    result = scan_single_file(tmp_path / "test.py")

    assert result.single_file == tmp_path / "test.py"
    assert result.root == tmp_path
    assert result.py_files == (tmp_path / "test.py",)
    assert result.requirements is None
    assert result.icon_files == ()
    assert result.data_files == ()


def test_single_file_scan_routes_txt_through_the_same_check(tmp_path):
    """Plik .txt z kodem to sciezka flagowa produktu — musi trafic do
    kandydatow do konwersji, a nie do danych."""
    (tmp_path / "test.txt").write_text("import sys\nprint('x')\n", encoding="utf-8")

    result = scan_single_file(tmp_path / "test.txt")

    assert result.text_candidates == (tmp_path / "test.txt",)
    assert result.py_files == ()


def test_single_file_scan_of_plain_text_finds_no_code(tmp_path):
    (tmp_path / "notatka.txt").write_text("kup mleko\n", encoding="utf-8")

    result = scan_single_file(tmp_path / "notatka.txt")

    assert result.py_files == ()
    assert result.text_candidates == ()
```

Dopisz import `scan_single_file` do nagłówka pliku testowego.

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/analysis/test_scanner.py -v -k single_file`
Expected: FAIL — `ImportError: cannot import name 'scan_single_file'`

- [ ] **Step 3: Dodaj pola do modeli**

W `exelent/models.py`, w `ScanResult`, po `truncated`:

```python
    single_file: Path | None = None
```

W `ProjectAnalysis`, po `issues`:

```python
    single_file: Path | None = None
    extra_sources: tuple[Path, ...] = ()
```

`extra_sources` to moduły lokalne dociągnięte w zadaniu 6; deklarujemy je tutaj, żeby kształt modelu ustalić raz.

- [ ] **Step 4: Zaimplementuj `scan_single_file`**

W `exelent/analysis/scanner.py`, po `scan_directory`:

```python
def scan_single_file(path: Path) -> ScanResult:
    """Skan dla pojedynczego pliku wskazanego przez użytkownika.

    `root` to katalog nadrzędny, bo ścieżki względne w kodzie użytkownika i
    `work_dir_for` potrzebują punktu odniesienia — ale katalog NIE jest
    projektem. Leżące w nim `requirements.txt`, ikona czy pliki danych należą
    do czegoś innego (najczęściej: do folderu Pobrane) i wciągnięcie ich byłoby
    tą samą pomyłką, przed którą ta funkcja broni.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    py: tuple[Path, ...] = ()
    texts: tuple[Path, ...] = ()

    if suffix in {".py", ".pyw"}:
        py = (path,)
    elif suffix == ".txt" and looks_like_python(_read_head(path)):
        texts = (path,)

    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    return ScanResult(
        root=path.parent,
        py_files=py,
        text_candidates=texts,
        file_count=1,
        total_bytes=size,
        single_file=path,
    )
```

- [ ] **Step 5: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/analysis tests/test_models.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/models.py exelent/analysis/scanner.py tests/analysis/test_scanner.py
git commit -m "feat: skan pojedynczego pliku bez wciagania katalogu nadrzednego"
```

---

### Task 6: Domknięcie modułów lokalnych i jego limit

**Files:**
- Modify: `exelent/analysis/scanner.py`
- Modify: `exelent/constants.py`
- Test: `tests/analysis/test_scanner.py`

**Interfaces:**
- Consumes: `scan_single_file` (zadanie 5).
- Produces: `local_import_closure(entry: Path, root: Path, limit: int) -> tuple[tuple[Path, ...], bool]` — krotka plików (bez pliku wejściowego) i flaga „limit przekroczony".

Skrypt importujący sąsiedni `helper.py` musi działać, inaczej tryb jednoplikowy psuje przypadki, które dziś działają.

- [ ] **Step 1: Napisz padające testy**

```python
def test_local_import_closure_follows_neighbours_transitively(tmp_path):
    (tmp_path / "main.py").write_text("import helper\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("import util\n", encoding="utf-8")
    (tmp_path / "util.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "obcy.py").write_text("Y = 2\n", encoding="utf-8")

    found, truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=50)

    assert set(found) == {tmp_path / "helper.py", tmp_path / "util.py"}
    assert truncated is False


def test_local_import_closure_resolves_packages(tmp_path):
    (tmp_path / "main.py").write_text("from pakiet import rzecz\n", encoding="utf-8")
    (tmp_path / "pakiet").mkdir()
    (tmp_path / "pakiet" / "__init__.py").write_text("rzecz = 1\n", encoding="utf-8")

    found, _truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=50)

    assert found == (tmp_path / "pakiet" / "__init__.py",)


def test_local_import_closure_ignores_installed_packages(tmp_path):
    """`requests` nie lezy obok pliku, wiec nie jest modulem lokalnym —
    to zaleznosc do zainstalowania, a tym zajmuje sie `resolve_dependencies`."""
    (tmp_path / "main.py").write_text("import requests\nimport os\n", encoding="utf-8")

    found, _truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=50)

    assert found == ()


def test_local_import_closure_survives_a_cycle(tmp_path):
    (tmp_path / "main.py").write_text("import a\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("import b\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import a\n", encoding="utf-8")

    found, _truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=50)

    assert set(found) == {tmp_path / "a.py", tmp_path / "b.py"}


def test_local_import_closure_stops_at_the_limit(tmp_path):
    """Limit chroni przed wciagnieciem polowy katalogu Pobrane przez lancuch
    importow. Po jego przekroczeniu zostaje sam plik wskazany."""
    (tmp_path / "main.py").write_text("import m0\n", encoding="utf-8")
    for i in range(10):
        nxt = f"import m{i + 1}\n" if i < 9 else "X = 1\n"
        (tmp_path / f"m{i}.py").write_text(nxt, encoding="utf-8")

    found, truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=3)

    assert truncated is True
    assert found == ()


def test_local_import_closure_ignores_unparsable_files(tmp_path):
    (tmp_path / "main.py").write_text("import zepsuty\n", encoding="utf-8")
    (tmp_path / "zepsuty.py").write_text("def (\n", encoding="utf-8")

    found, truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=50)

    assert found == (tmp_path / "zepsuty.py",)
    assert truncated is False
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/analysis/test_scanner.py -v -k closure`
Expected: FAIL — `NameError: name 'local_import_closure' is not defined`

- [ ] **Step 3: Dodaj stałą limitu**

W `exelent/constants.py`:

```python
# Ile plikow wolno dociagnac lancuchowi importow lokalnych w trybie
# jednoplikowym. Limit istnieje po to, zeby jeden `import` w skrypcie
# upuszczonym z Pobranych nie wciagnal polowy tego katalogu.
MAX_SINGLE_FILE_IMPORTS = 50
```

- [ ] **Step 4: Zaimplementuj**

W `exelent/analysis/scanner.py`:

```python
def _local_target(root: Path, name: str) -> Path | None:
    """Ścieżka modułu lokalnego o tej nazwie albo None, gdy go tu nie ma."""
    module = root / f"{name}.py"
    if module.is_file():
        return module
    package = root / name / "__init__.py"
    if package.is_file():
        return package
    return None


def _imported_names(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Plik z bledem skladni nadal moze byc czescia projektu; po prostu nie
        # wiemy, co importuje. To nie jest powod, zeby go pominac.
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.append(node.module.split(".")[0])
    return names


def local_import_closure(
    entry: Path,
    root: Path,
    limit: int = MAX_SINGLE_FILE_IMPORTS,
) -> tuple[tuple[Path, ...], bool]:
    """Moduły lokalne, których potrzebuje `entry`, wraz z ich własnymi.

    Zwraca `(pliki_bez_entry, przekroczono_limit)`. Po przekroczeniu limitu
    wynikiem jest PUSTA krotka, a nie obcięta lista: wciągnięcie losowej
    połowy łańcucha importów dałoby EXE, które wywala się u odbiorcy na
    brakującym module — czyli awarię gorszą i późniejszą niż uczciwe
    „nie dam rady, zostaje sam plik".
    """
    seen: set[Path] = {entry}
    queue = [entry]
    found: list[Path] = []

    while queue:
        current = queue.pop(0)
        for name in _imported_names(_read_head(current, limit=1_000_000)):
            target = _local_target(root, name)
            if target is None or target in seen:
                continue
            if len(found) >= limit:
                return (), True
            seen.add(target)
            found.append(target)
            queue.append(target)

    return tuple(found), False
```

Dopisz `MAX_SINGLE_FILE_IMPORTS` do importów z `exelent.constants` na górze pliku.

- [ ] **Step 5: Podłącz domknięcie do `scan_single_file`**

W `scan_single_file`, przed `return`:

```python
    extra, truncated = local_import_closure(path, path.parent)
    if py:
        py = (path, *extra)
    elif texts:
        # Plik glowny jest kandydatem do konwersji, ale jego sasiedzi to juz
        # zwykly Python — nie przepuszczamy ich przez konwersje.
        py = extra
```

i przekaż do `ScanResult` `truncated=truncated`.

- [ ] **Step 6: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/analysis -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/analysis/scanner.py exelent/constants.py tests/analysis/test_scanner.py
git commit -m "feat: tryb jednoplikowy dociaga moduly lokalne z twardym limitem"
```

---

### Task 7: `analyze_project` wybiera tryb, ekran 1 przekazuje plik, „Ostatnie" przyjmuje pliki

**Files:**
- Modify: `exelent/analysis/project.py`, `exelent/ui/screen_drop.py`, `exelent/ui/recent.py`, `exelent/ui/screen_review.py`
- Modify: `exelent/i18n/pl.py`, `exelent/i18n/en.py`
- Test: `tests/analysis/test_project.py`, `tests/ui/test_screen_drop.py`, `tests/ui/test_recent.py`

**Interfaces:**
- Consumes: `scan_single_file`, `local_import_closure` (zadania 5–6).
- Produces: `analyze_project(path)` akceptujące plik; `ProjectAnalysis.single_file` i `.extra_sources` wypełnione.

- [ ] **Step 1: Napisz padające testy**

Do `tests/analysis/test_project.py`:

```python
def test_analyze_of_a_single_file_ignores_the_neighbours(tmp_path):
    (tmp_path / "test.txt").write_text("print('czesc')\n", encoding="utf-8")
    (tmp_path / "cudzy_projekt.py").write_text("import torch\n", encoding="utf-8")

    analysis = analyze_project(tmp_path / "test.txt")

    assert analysis.single_file == tmp_path / "test.txt"
    assert [d.package for d in analysis.dependencies] == []
    assert analysis.entry is not None


def test_analyze_of_a_single_file_reports_pulled_in_modules(tmp_path):
    (tmp_path / "main.py").write_text("import helper\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("X = 1\n", encoding="utf-8")

    analysis = analyze_project(tmp_path / "main.py")

    assert analysis.extra_sources == (tmp_path / "helper.py",)


def test_analyze_of_a_directory_is_unchanged(tmp_path):
    root = tmp_path / "projekt"
    root.mkdir()
    (root / "main.py").write_text("print('x')\n", encoding="utf-8")

    analysis = analyze_project(root)

    assert analysis.single_file is None
    assert analysis.extra_sources == ()
```

Do `tests/ui/test_recent.py`:

```python
def test_recent_keeps_single_files(tmp_path, monkeypatch):
    """Po wprowadzeniu trybu jednoplikowego filtr `is_dir()` cicho gubilby
    kazdy wpis bedacy plikiem."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    script = tmp_path / "test.py"
    script.write_text("print('x')\n", encoding="utf-8")

    recent.remember(script)

    assert script.resolve() in recent.load_recent()
```

Do `tests/ui/test_screen_drop.py` (użyj istniejącego w tym pliku helpera tworzącego `QMimeData` z URL-em):

```python
def test_dropping_a_file_selects_the_file_not_its_folder(qtbot, tmp_path):
    script = tmp_path / "test.txt"
    script.write_text("print('x')\n", encoding="utf-8")
    screen = DropScreen()
    qtbot.addWidget(screen)

    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        screen.dropEvent(_drop_event(script))

    assert blocker.args[0] == script
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/analysis/test_project.py tests/ui/test_recent.py tests/ui/test_screen_drop.py -v -k "single_file or neighbours or pulled_in or unchanged or keeps_single or selects_the_file"`
Expected: FAIL

- [ ] **Step 3: Rozwidl `analyze_project`**

W `exelent/analysis/project.py`, na początku funkcji:

```python
def analyze_project(root: Path) -> ProjectAnalysis:
    source = Path(root)
    if source.is_dir():
        scan = scan_directory(source)
    else:
        scan = scan_single_file(source)
    root = scan.root
    issues: list[Issue] = []
```

Zamień komunikat o obciętym skanie tak, by tryb jednoplikowy mówił swoje zdanie:

```python
    if scan.truncated:
        if scan.single_file is not None:
            issues.append(Issue("single_file_too_many", Severity.WARNING))
        else:
            issues.append(
                Issue("scan_truncated", Severity.WARNING, {"files": str(scan.file_count)})
            )
```

W zwracanym `ProjectAnalysis` dodaj:

```python
        single_file=scan.single_file,
        extra_sources=tuple(p for p in scan.py_files if p != scan.single_file),
```

oraz zmień `suggested_name`, żeby dla pliku brał jego nazwę bez rozszerzenia, a nie nazwę katalogu Pobrane:

```python
        suggested_name=scan.single_file.stem if scan.single_file else root.name,
```

Ta sama zmiana dotyczy wcześniejszego `return` na ścieżce „brak Pythona" — tam też podmień `suggested_name=root.name` na tę samą formę.

- [ ] **Step 4: Popraw ekran 1 i „Ostatnie"**

W `exelent/ui/screen_drop.py` zamień `_folder_from` na:

```python
def _source_from(mime) -> Path | None:
    """Ścieżka wskazana przez upuszczone dane albo None, gdy to nie ścieżka.

    Plik NIE jest zamieniany na katalog nadrzędny. Poprzednia wersja robiła
    `path.parent` i przez to `test.txt` upuszczony z Pobranych wybierał całe
    Pobrane — łącznie z kopiowaniem ich do katalogu roboczego.

    Wszystko, co nie jest ścieżką lokalną (link przeciągnięty z przeglądarki,
    zaznaczony tekst), nadal odrzucamy jawnie: pusty `toLocalFile()` po
    `Path(...)` daje katalog bieżący, więc cicha tolerancja kończyłaby się
    analizą przypadkowego miejsca.
    """
    for url in mime.urls():
        local = url.toLocalFile()
        if not local:
            continue
        return Path(local)
    return None
```

Podmień oba użycia (`dragEnterEvent`, `dropEvent`) na `_source_from`.

W `exelent/ui/recent.py`, w `load_recent`, zamień warunek:

```python
        if path.exists() and path not in result:
```

- [ ] **Step 5: Pokaż dociągnięte pliki na ekranie 2**

W `exelent/ui/screen_review.py`, w `__init__`, pod kartą:

```python
        self.extra_label = QLabel("", objectName="Muted")
        self.extra_label.setWordWrap(True)
        self.extra_label.setVisible(False)
```

dodaj `outer.addWidget(self.extra_label)` zaraz po `outer.addWidget(card)`, a w `load()`:

```python
        extra = ", ".join(p.name for p in analysis.extra_sources)
        self.extra_label.setText(t("single_file_extra", files=extra) if extra else "")
        self.extra_label.setVisible(bool(extra))
```

- [ ] **Step 6: Dodaj klucze**

`exelent/i18n/pl.py`:

```python
    "single_file_extra": "Dołączam też: {files}",
    "single_file_too_many": (
        "Ten plik wciąga bardzo wiele innych plików z tego samego folderu. "
        "Buduję sam wskazany plik — jeśli to za mało, wskaż cały folder z programem."
    ),
```

`exelent/i18n/en.py`:

```python
    "single_file_extra": "Also including: {files}",
    "single_file_too_many": (
        "This file pulls in a great many other files from the same folder. "
        "Building just the file you picked — if that is not enough, point me at the whole folder."
    ),
```

- [ ] **Step 7: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests -m "not slow" -q`
Expected: PASS (poza znaną niestabilnością czasową z §11a, jeśli maszyna jest obciążona)

- [ ] **Step 8: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/analysis/project.py exelent/ui exelent/i18n tests
git commit -m "feat: upuszczony plik jest projektem, nie pretekstem do wziecia katalogu"
```

---

### Task 8: Kopia robocza i katalog roboczy dla trybu jednoplikowego

**Files:**
- Modify: `exelent/models.py`, `exelent/planning.py`, `exelent/build/workspace.py`, `exelent/runtime/paths.py`
- Test: `tests/build/test_workspace.py`, `tests/runtime/test_paths.py`, `tests/test_planning.py`

**Interfaces:**
- Consumes: `ProjectAnalysis.single_file`, `.extra_sources` (zadanie 7).
- Produces: `BuildPlan.single_file: Path | None`; `work_dir_for(source, single_file=None)`.

To jest domknięcie zgłoszenia 1. Bez tego kroku `materialize_workspace` nadal robi `copytree` całego katalogu Pobrane, a naprawa ekranu 1 jest kosmetyką.

- [ ] **Step 1: Napisz padające testy**

Do `tests/build/test_workspace.py`:

```python
def test_single_file_workspace_copies_only_the_relevant_files(tmp_path, monkeypatch):
    """Bez tego `copytree` kopiuje CALE Pobrane do %LOCALAPPDATA%."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    downloads = tmp_path / "Pobrane"
    downloads.mkdir()
    (downloads / "test.py").write_text("import helper\n", encoding="utf-8")
    (downloads / "helper.py").write_text("X = 1\n", encoding="utf-8")
    (downloads / "wielki_film.mp4").write_bytes(b"x" * 5000)
    (downloads / "cudzy.py").write_text("Y = 2\n", encoding="utf-8")

    plan = _plan(
        root=downloads,
        entry=downloads / "test.py",
        single_file=downloads / "test.py",
        extra=(downloads / "helper.py",),
    )
    workspace = materialize_workspace(plan, {})

    assert (workspace / "test.py").exists()
    assert (workspace / "helper.py").exists()
    assert not (workspace / "wielki_film.mp4").exists()
    assert not (workspace / "cudzy.py").exists()
```

Do `tests/runtime/test_paths.py`:

```python
def test_two_files_in_one_folder_get_different_work_dirs(tmp_path, monkeypatch):
    """Bez tego drugi build kasuje srodowisko pierwszego — `path_hash` jest
    jedyna rzecza, ktora te przebiegi rozdziela."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    a = work_dir_for(tmp_path, single_file=tmp_path / "a.py")
    b = work_dir_for(tmp_path, single_file=tmp_path / "b.py")
    assert a != b


def test_directory_work_dir_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert work_dir_for(tmp_path) == work_dir_for(tmp_path, single_file=None)
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/build/test_workspace.py tests/runtime/test_paths.py -v -k "single_file or different_work_dirs or unchanged"`
Expected: FAIL — `TypeError: work_dir_for() got an unexpected keyword argument 'single_file'`

- [ ] **Step 3: Dodaj pola do `BuildPlan` i przekaż je w `make_plan`**

W `exelent/models.py`, w `BuildPlan`:

```python
    single_file: Path | None = None
    extra_sources: tuple[Path, ...] = ()
```

W `exelent/planning.py`, w `make_plan`, w zwracanym `BuildPlan`:

```python
        single_file=analysis.single_file,
        extra_sources=analysis.extra_sources,
```

- [ ] **Step 4: Rozróżnij katalog roboczy**

W `exelent/runtime/paths.py`:

```python
def work_dir_for(source: Path, single_file: Path | None = None) -> Path:
    """Katalog roboczy dla tego przebiegu.

    W trybie jednoplikowym hashujemy PLIK, nie katalog. Inaczej `a.py` i
    `b.py` leżące w Pobranych dzielą jeden katalog roboczy i drugi build
    kasuje środowisko pierwszego — a `path_hash` jest jedyną rzeczą, która
    te przebiegi rozdziela.
    """
    return state_dir() / "b" / path_hash(single_file or source)
```

- [ ] **Step 5: Ogranicz kopię roboczą**

W `exelent/build/workspace.py`:

```python
def workspace_for(root: Path, single_file: Path | None = None) -> Path:
    return work_dir_for(root, single_file) / "src"


def materialize_workspace(plan: BuildPlan, converted: Mapping[str, str]) -> Path:
    workspace = workspace_for(plan.root, plan.single_file)
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.parent.mkdir(parents=True, exist_ok=True)

    if plan.single_file is not None:
        # Katalog nadrzedny NIE jest projektem. `copytree` skopiowalby tu cale
        # Pobrane — z filmami wlacznie — do %LOCALAPPDATA%.
        workspace.mkdir(parents=True, exist_ok=True)
        for source in (plan.single_file, *plan.extra_sources):
            target = workspace / source.relative_to(plan.root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    else:
        shutil.copytree(
            plan.root,
            workspace,
            ignore=shutil.ignore_patterns(*EXCLUDED_DIRS, ".*"),
            dirs_exist_ok=False,
        )

    for name, code in converted.items():
        (workspace / name).write_text(code, encoding="utf-8")

    return workspace
```

- [ ] **Step 6: Znajdź i popraw pozostałe wywołania**

Run: `grep -rn "workspace_for\|work_dir_for" exelent/ tests/ --include=*.py`

Każde wywołanie w `exelent/build/pyinstaller.py` musi przekazać `plan.single_file`, inaczej build uruchomi się w katalogu bez kodu — dokładnie ta awaria, przed którą chroni docstring `workspace_for`.

- [ ] **Step 7: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests -m "not slow" -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent tests
git commit -m "fix: kopia robocza trybu jednoplikowego nie kopiuje calego katalogu Pobrane"
```

---

### Task 9: Parser linii zdarzeń uv

**Files:**
- Create: `exelent/runtime/uvlog.py`
- Create: `tests/runtime/test_uvlog.py`
- Create: `tests/runtime/fixtures/uv_install.txt`, `tests/runtime/fixtures/uv_python_install.txt`, `tests/runtime/fixtures/uv_dry_run.txt`

**Interfaces:**
- Consumes: nic.
- Produces: `UvEvent` (`@dataclass(frozen=True)` z polami `kind: str`, `name: str`, `size_bytes: int`, `count: int`), `parse_line(line: str) -> UvEvent | None`, stałe `DOWNLOAD_START`, `DOWNLOAD_DONE`, `RESOLVED`, `WOULD_DOWNLOAD`, `PREPARED`, `INSTALLED`, `PACKAGE`.

Formaty **zmierzone na uv 0.8.17**, nie założone. Fixture'y są dosłownym zapisem tego, co wypisał prawdziwy uv.

- [ ] **Step 1: Zapisz fixture'y**

`tests/runtime/fixtures/uv_install.txt` — dosłownie:

```
Using Python 3.12.11 environment at: probe-venv
Resolved 1 package in 477ms
Downloading pillow (6.9MiB)
 Downloading pillow
Prepared 1 package in 1.25s
Installed 1 package in 54ms
 + pillow==12.3.0
```

`tests/runtime/fixtures/uv_python_install.txt` — dosłownie:

```
Downloading cpython-3.11.13-windows-x86_64-none (download) (24.3MiB)
 Downloading cpython-3.11.13-windows-x86_64-none (download)
Installed Python 3.11.13 in 9.86s
 + cpython-3.11.13-windows-x86_64-none (python3.11.exe)
```

`tests/runtime/fixtures/uv_dry_run.txt` — dosłownie:

```
Using Python 3.12.11 environment at: probe-venv
Resolved 14 packages in 18ms
Would download 8 packages
Would install 14 packages
 + contourpy==1.3.3
 + cycler==0.12.1
 + fonttools==4.63.0
 + kiwisolver==1.5.1
 + matplotlib==3.11.1
 + numpy==2.5.2
 + packaging==26.3
 + pandas==3.0.5
 + pillow==12.3.0
 + pyparsing==3.3.2
 + python-dateutil==2.9.0.post0
 + scipy==1.18.1
 + six==1.17.0
 + tzdata==2026.3
```

- [ ] **Step 2: Napisz padające testy**

`tests/runtime/test_uvlog.py`:

```python
"""Parser wyjscia uv. Wszystkie formaty ZMIERZONE na uv 0.8.17, nie zalozone.

Ten plik jest jedynym miejscem, ktore wie, jak uv mowi. Kazdy format tutaj
pochodzi z prawdziwego przebiegu zapisanego w `fixtures/` — bo parser oparty
na wyobrazeniu o wyjsciu narzedzia psuje sie cicho, przy pierwszej zmianie
wersji, i objawia sie paskiem postepu, ktory stoi.
"""

from pathlib import Path

import pytest

from exelent.runtime.uvlog import (
    DOWNLOAD_DONE,
    DOWNLOAD_START,
    PACKAGE,
    PREPARED,
    RESOLVED,
    WOULD_DOWNLOAD,
    parse_line,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _events(name: str):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return [e for e in (parse_line(line) for line in text.splitlines()) if e is not None]


def test_download_start_carries_name_and_size():
    event = parse_line("Downloading pillow (6.9MiB)")
    assert event.kind == DOWNLOAD_START
    assert event.name == "pillow"
    assert event.size_bytes == int(6.9 * 1024**2)


def test_download_completion_has_a_leading_space_and_no_size():
    event = parse_line(" Downloading pillow")
    assert event.kind == DOWNLOAD_DONE
    assert event.name == "pillow"


def test_python_download_name_contains_parentheses():
    """Naiwny regex bierze `(download)` za rozmiar i wywraca sie.

    Wzorzec musi kotwiczyc sie na OSTATNIM nawiasie i wymagac w nim jednostki.
    """
    event = parse_line("Downloading cpython-3.11.13-windows-x86_64-none (download) (24.3MiB)")
    assert event.kind == DOWNLOAD_START
    assert event.name == "cpython-3.11.13-windows-x86_64-none (download)"
    assert event.size_bytes == int(24.3 * 1024**2)


def test_python_download_completion_keeps_the_parenthesised_name():
    event = parse_line(" Downloading cpython-3.11.13-windows-x86_64-none (download)")
    assert event.kind == DOWNLOAD_DONE
    assert event.name == "cpython-3.11.13-windows-x86_64-none (download)"


@pytest.mark.parametrize(
    ("line", "kind", "count"),
    [
        ("Resolved 14 packages in 18ms", RESOLVED, 14),
        ("Resolved 1 package in 477ms", RESOLVED, 1),
        ("Would download 8 packages", WOULD_DOWNLOAD, 8),
        ("Prepared 1 package in 1.25s", PREPARED, 1),
        ("Prepared 12 packages in 3.4s", PREPARED, 12),
    ],
)
def test_counting_lines_accept_singular_and_plural(line, kind, count):
    """uv pisze "1 package" i "12 packages" — wzorzec musi przyjac obie formy."""
    event = parse_line(line)
    assert event.kind == kind
    assert event.count == count


def test_package_line_carries_name_and_version():
    event = parse_line(" + python-dateutil==2.9.0.post0")
    assert event.kind == PACKAGE
    assert event.name == "python-dateutil==2.9.0.post0"


@pytest.mark.parametrize(
    "line",
    [
        "",
        "Using Python 3.12.11 environment at: probe-venv",
        "Would install 14 packages",
        " + cpython-3.11.13-windows-x86_64-none (python3.11.exe)",
        "cos zupelnie nieznanego",
    ],
)
def test_unknown_lines_return_none_and_never_raise(line):
    """Postep jest ozdoba. Parser, ktory rzuca, zabija build."""
    assert parse_line(line) is None


def test_all_units_are_powers_of_1024():
    assert parse_line("Downloading a (1KiB)").size_bytes == 1024
    assert parse_line("Downloading a (1MiB)").size_bytes == 1024**2
    assert parse_line("Downloading a (1GiB)").size_bytes == 1024**3


def test_real_install_transcript(): 
    kinds = [e.kind for e in _events("uv_install.txt")]
    assert kinds == [RESOLVED, DOWNLOAD_START, DOWNLOAD_DONE, PREPARED, PACKAGE]


def test_real_dry_run_transcript_yields_every_pinned_package():
    events = _events("uv_dry_run.txt")
    would = [e for e in events if e.kind == WOULD_DOWNLOAD]
    packages = [e.name for e in events if e.kind == PACKAGE]
    assert would[0].count == 8
    assert len(packages) == 14
    assert "scipy==1.18.1" in packages


def test_small_packages_produce_no_download_lines():
    """ZMIERZONE: `six` i `packaging` z --no-cache nie daly ani jednej linii
    `Downloading`. Suma liczona z tych linii bylaby systematycznie zanizona,
    dlatego calosc bierzemy z PyPI, a `Prepared` jest sygnalem 100%.
    """
    text = "Resolved 2 packages in 372ms\nPrepared 2 packages in 239ms\n"
    events = [e for e in (parse_line(line) for line in text.splitlines()) if e]
    assert not any(e.kind == DOWNLOAD_START for e in events)
```

- [ ] **Step 3: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_uvlog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exelent.runtime.uvlog'`

- [ ] **Step 4: Zaimplementuj**

`exelent/runtime/uvlog.py`:

```python
"""Linie, którymi uv opowiada o swojej pracy → typowane zdarzenia.

To jedyne miejsce w programie, które wie, jak uv mówi. Wszystkie wzorce
pochodzą ze ZMIERZONEGO wyjścia uv 0.8.17 na potoku (nie na terminalu — na
potoku uv nie rysuje pasków, tylko drukuje linie zdarzeń).

Parser nigdy nie rzuca. Postęp jest ozdobą; wyjątek stąd zabiłby build,
którego jedyną winą było nietypowe zdanie w logu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DOWNLOAD_START = "download_start"
DOWNLOAD_DONE = "download_done"
RESOLVED = "resolved"
WOULD_DOWNLOAD = "would_download"
PREPARED = "prepared"
INSTALLED = "installed"
PACKAGE = "package"

_UNITS = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}

# Rozmiar jest w OSTATNIM nawiasie linii, a nie w pierwszym: nazwa
# interpretera zawiera własny nawias — zmierzone:
#   "Downloading cpython-3.11.13-windows-x86_64-none (download) (24.3MiB)"
# Wzorzec zakotwiczony na pierwszym nawiasie brał "(download)" za rozmiar.
_START = re.compile(r"^Downloading (?P<name>.+?) \((?P<size>[\d.]+)(?P<unit>KiB|MiB|GiB)\)$")
_DONE = re.compile(r"^ +Downloading (?P<name>.+?)$")
_RESOLVED = re.compile(r"^Resolved (?P<count>\d+) packages? in ")
_WOULD = re.compile(r"^Would download (?P<count>\d+) packages?$")
_PREPARED = re.compile(r"^Prepared (?P<count>\d+) packages? in ")
_INSTALLED = re.compile(r"^Installed (?P<count>\d+) packages? in ")
# Pozycja wyniku to "nazwa==wersja". Instalacja interpretera drukuje w tym
# samym kształcie "cpython-... (python3.11.exe)", co pakietem nie jest.
_PACKAGE = re.compile(r"^ \+ (?P<name>[^\s]+==[^\s]+)$")


@dataclass(frozen=True)
class UvEvent:
    kind: str
    name: str = ""
    size_bytes: int = 0
    count: int = 0


def parse_line(line: str) -> UvEvent | None:
    """Jedna linia uv → zdarzenie albo None, gdy jej nie znamy."""
    stripped = line.rstrip("\r\n")

    match = _START.match(stripped)
    if match:
        size = float(match["size"]) * _UNITS[match["unit"]]
        return UvEvent(DOWNLOAD_START, name=match["name"], size_bytes=int(size))

    match = _PACKAGE.match(stripped)
    if match:
        return UvEvent(PACKAGE, name=match["name"])

    # PO `_PACKAGE`, bo obie zaczynają się od spacji i tylko kolejność je dzieli.
    match = _DONE.match(stripped)
    if match:
        return UvEvent(DOWNLOAD_DONE, name=match["name"])

    for pattern, kind in (
        (_RESOLVED, RESOLVED),
        (_WOULD, WOULD_DOWNLOAD),
        (_PREPARED, PREPARED),
        (_INSTALLED, INSTALLED),
    ):
        match = pattern.match(stripped)
        if match:
            return UvEvent(kind, count=int(match["count"]))

    return None
```

- [ ] **Step 5: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_uvlog.py tests/test_layering.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/runtime/uvlog.py tests/runtime
git commit -m "feat: parser wyjscia uv na zmierzonych formatach 0.8.17"
```

---

### Task 10: `Progress` jako jedyny kształt postępu (i naprawa inwentarza i18n)

**Files:**
- Create: `exelent/runtime/progress.py`, `tests/runtime/test_progress.py`
- Modify: `exelent/runtime/__init__.py`, `exelent/runtime/bootstrap.py`, `exelent/runtime/env.py`, `exelent/build/pyinstaller.py`, `exelent/cli.py`, `exelent/ui/worker.py`, `exelent/ui/screen_build.py`
- Modify: `tests/i18n/inventory.py`
- Test: `tests/runtime/test_progress.py`, `tests/i18n/test_translations.py`

**Interfaces:**
- Consumes: nic.
- Produces: `Progress` (`frozen`, pola `phase: str`, `fraction: float`, `done_bytes: int = 0`, `total_bytes: int = 0`, `speed_bps: float = 0.0`, `eta_s: float | None = None`), `ProgressFn = Callable[[Progress], None]`, `noop_progress(update: Progress) -> None`.

**Uwaga o strażniku i18n.** Po tej zmianie `progress("faza", ...)` staje się `progress(Progress(phase="faza", ...))`, więc `inventory.phase_keys()` przestaje widzieć fazy w `node.args[0]`. Test `test_every_progress_phase_is_translated` **oślepnie** (przejdzie, bo zbiór faz stanie się pusty), ale `test_dynamic_progress_sites_are_declared` **padnie głośno**, bo każde miejsce zostanie uznane za dynamiczne. Ten drugi test jest tu jedynym sygnałem, że skan przestał rozumieć kod — nie wyciszaj go dopisaniem miejsc do `DECLARED_DYNAMIC_PHASES`. Naprawa polega na nauczeniu skanera nowego kształtu.

- [ ] **Step 1: Napisz padający test struktury**

`tests/runtime/test_progress.py`:

```python
"""Postep jako jeden obiekt.

Para (faza, ulamek) nie miala gdzie zmiescic bajtow ani predkosci, a dolozenie
pieciu argumentow opcjonalnych dalo by sygnature, ktorej nikt nie umie wypelnic
w polowie. Jeden obiekt jest uczciwszy.
"""

import pytest

from exelent.runtime import noop_progress
from exelent.runtime.progress import Progress


def test_progress_is_immutable():
    update = Progress(phase="analyze", fraction=0.5)
    with pytest.raises(Exception):
        update.fraction = 0.9


def test_byte_fields_default_to_zero_for_phases_that_download_nothing():
    """Pakowanie PyInstallerem nic nie pobiera. Pusty licznik bajtow pod
    paskiem bylby gorszy niz jego brak, wiec ekran pozna to po zerze."""
    update = Progress(phase="package", fraction=0.5)
    assert update.total_bytes == 0
    assert update.done_bytes == 0
    assert update.eta_s is None


def test_noop_progress_accepts_the_object():
    assert noop_progress(Progress(phase="analyze", fraction=0.0)) is None
```

- [ ] **Step 2: Uruchom i potwierdź, że pada**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_progress.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exelent.runtime.progress'`

- [ ] **Step 3: Utwórz strukturę**

`exelent/runtime/progress.py`:

```python
"""Jeden kształt postępu dla całego programu.

Pola bajtowe są zerowe dla faz, które nic nie pobierają (pakowanie
PyInstallerem). Warstwa prezentacji poznaje to po `total_bytes == 0` i wtedy
nie pokazuje drugiej linijki — pusty licznik megabajtów pod paskiem jest
gorszy niż jego brak.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Progress:
    phase: str
    fraction: float
    done_bytes: int = 0
    total_bytes: int = 0
    speed_bps: float = 0.0
    eta_s: float | None = None
```

`exelent/runtime/__init__.py`:

```python
from collections.abc import Callable

from exelent.runtime.progress import Progress

ProgressFn = Callable[[Progress], None]
"""Wywoływane z jednym `Progress`. Kod fazy tłumaczy warstwa UI."""


def noop_progress(update: Progress) -> None:
    return None


__all__ = ["Progress", "ProgressFn", "noop_progress"]
```

- [ ] **Step 4: Przeprowadź migrację wszystkich wywołań**

Run: `grep -rn "progress(" exelent/ --include=*.py`

Zamień każde `progress("faza", ulamek)` na `progress(Progress(phase="faza", fraction=ulamek))`. Miejsca do zmiany:
- `exelent/runtime/bootstrap.py:79` — w `_download`
- `exelent/runtime/env.py:68,71,78,91` — cztery fazy `create_build_env`
- `exelent/build/pyinstaller.py` — miejsce przepisujące wartości z `PHASES`
- `exelent/cli.py` — `_print_progress` i `_Progress.stage`

`_print_progress` w `cli.py`:

```python
def _print_progress(update: Progress) -> None:
    print(f"[{update.fraction * 100:5.1f}%] {update.phase}", flush=True)
```

`_Progress.stage` w `cli.py` — zachowaj OBIE własności (sklejenie skal i monotoniczność), przenosząc pola bajtowe bez zmian:

```python
    def stage(self, start: float, end: float) -> ProgressFn:
        def report(update: Progress) -> None:
            value = start + (end - start) * min(max(update.fraction, 0.0), 1.0)
            self._highest = max(self._highest, value)
            self._report(replace(update, fraction=self._highest))

        return report
```

`dataclasses.replace` jest już importowane w `cli.py`.

- [ ] **Step 5: Przeprowadź migrację warstwy UI**

`exelent/ui/worker.py` — sygnał niesie obiekt:

```python
class _Job(QObject):
    progress = Signal(object)
    finished = Signal(object)


class BuildWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
```

`exelent/ui/screen_build.py`:

```python
    def on_progress(self, update) -> None:
        self.phase_label.setText(t(update.phase))
        self.bar.setValue(int(update.fraction * 100))
```

(Druga linijka z bajtami dochodzi w zadaniu 13 — tutaj tylko utrzymujemy dotychczasowe zachowanie.)

- [ ] **Step 6: Napraw inwentarz i18n**

W `tests/i18n/inventory.py` dodaj helper i przełącz na niego obie funkcje faz:

```python
def _phase_of(node: ast.Call) -> str | None:
    """Faza z wywolania `progress(...)` — w obu ksztaltach.

    Do zadania 10 faza byla pierwszym argumentem: `progress("analyze", 0.3)`.
    Teraz siedzi w obiekcie: `progress(Progress(phase="analyze", ...))`.
    Bez tego skan przestaje widziec fazy, `test_every_progress_phase_is_translated`
    slepnie na pustym zbiorze, a jedynym sygnalem zostaje
    `test_dynamic_progress_sites_are_declared`.
    """
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Call) and getattr(first.func, "id", None) == "Progress":
        for keyword in first.keywords:
            if keyword.arg == "phase":
                return _literal_str(keyword.value)
        return _literal_str(first.args[0]) if first.args else None
    return _literal_str(first)


def phase_keys() -> set[str]:
    literal = {
        phase
        for _where, node in _calls("progress")
        if (phase := _phase_of(node)) is not None
    }
    return literal | set(PHASES.values())


def dynamic_phase_sites() -> set[str]:
    return {where for where, node in _calls("progress") if _phase_of(node) is None}
```

- [ ] **Step 7: Udowodnij, że strażnik nadal widzi**

Dopisz do `tests/i18n/test_translations.py`:

```python
def test_the_inventory_still_sees_progress_phases():
    """Sonda nad skanem faz: pusty zbior przechodzilby kazdy test
    kompletnosci, wiec brak fazy przestalby cokolwiek znaczyc."""
    phases = phase_keys()
    assert "install_packages" in phases, "faza z env.py wypadla z inwentarza"
    assert len(phases) > 8, f"inwentarz faz nagle schudl do {len(phases)}"
```

Ręcznie zweryfikuj czerwień: tymczasowo usuń klucz `"install_packages"` z `exelent/i18n/pl.py`, uruchom `pytest tests/i18n -v` i potwierdź, że `test_every_progress_phase_is_translated` **pada**. Przywróć klucz.

- [ ] **Step 8: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests -m "not slow" -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent tests
git commit -m "refactor: postep jako jeden obiekt, inwentarz i18n uczy sie nowego ksztaltu"
```

---

### Task 11: `create_build_env` czyta uv na żywo i liczy bajty

**Files:**
- Modify: `exelent/runtime/env.py`
- Test: `tests/runtime/test_env.py`

**Interfaces:**
- Consumes: `Progress` (zadanie 10), `parse_line` i stałe z `uvlog` (zadanie 9).
- Produces: `create_build_env(..., total_download_bytes: int = 0)` — zadanie 20 podaje tam sumę policzoną przez preflight.

`subprocess.run(capture_output=True)` buforuje całe wyjście do zakończenia procesu, więc na żywo nie ma czego pokazywać. Zamiana na `Popen` musi zachować pełny tekst dla `explain_log` oraz `CREATE_NO_WINDOW` — bez niej użytkownikowi GUI mignie okno konsoli.

- [ ] **Step 1: Napisz padające testy**

Do `tests/runtime/test_env.py`:

```python
def test_install_reports_bytes_as_uv_finishes_downloads(monkeypatch, tmp_path):
    """Licznik rosnie na zdarzeniu ZAKONCZENIA pobrania — uv nie raportuje
    bajtow w locie na potoku."""
    transcript = [
        "Resolved 2 packages in 18ms",
        "Downloading pillow (6.9MiB)",
        "Downloading numpy (11.9MiB)",
        " Downloading pillow",
        " Downloading numpy",
        "Prepared 2 packages in 3.4s",
    ]
    seen: list[Progress] = []
    _run_fake_uv(monkeypatch, tmp_path, transcript)

    create_build_env(
        tmp_path,
        ["pillow", "numpy"],
        seen.append,
        total_download_bytes=int(18.8 * 1024**2),
    )

    byte_updates = [u for u in seen if u.total_bytes > 0]
    assert byte_updates, "zadna aktualizacja nie niosla bajtow"
    assert byte_updates[-1].done_bytes >= int(18.0 * 1024**2)


def test_prepared_line_forces_the_download_phase_to_full(monkeypatch, tmp_path):
    """uv MILCZY przy malych paczkach (zmierzone: six, packaging), wiec suma
    z linii `Downloading` nigdy nie dobilaby do calosci."""
    transcript = ["Resolved 2 packages in 372ms", "Prepared 2 packages in 239ms"]
    seen: list[Progress] = []
    _run_fake_uv(monkeypatch, tmp_path, transcript)

    create_build_env(tmp_path, ["six"], seen.append, total_download_bytes=5_000_000)

    final = [u for u in seen if u.phase == "install_packages"][-1]
    assert final.done_bytes == final.total_bytes


def test_full_stderr_still_reaches_explain_log_on_failure(monkeypatch, tmp_path):
    """Strumieniowanie nie moze zjesc tekstu, ktorego potrzebuje diagnostyka."""
    transcript = ["error: Failed to fetch", "caused by: certificate verify failed"]
    _run_fake_uv(monkeypatch, tmp_path, transcript, returncode=1, fail_venv=True)

    with pytest.raises(BuildEnvError) as caught:
        create_build_env(tmp_path, [], noop_progress)

    assert any(i.code == "ssl_proxy" for i in caught.value.issues)
```

Dopisz helper `_run_fake_uv` na górze pliku testowego — podmienia `run_uv` i `_stream_uv` na atrapy oddające podany zapis, bez uruchamiania procesu:

```python
def _run_fake_uv(monkeypatch, tmp_path, transcript, returncode=0, fail_venv=False):
    """Atrapa uv oddajaca gotowy zapis. ZADNEGO procesu i zadnej sieci."""
    import exelent.runtime.env as env_module

    (tmp_path / "venv" / "Scripts").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(env_module, "ensure_uv", lambda progress: tmp_path / "uv.exe")

    def fake_run_uv(uv, args, *, cwd=None):
        code = 1 if (fail_venv and args and args[0] == "venv") else 0
        return subprocess.CompletedProcess(args, code, "", "\n".join(transcript))

    def fake_stream_uv(uv, args, on_line, *, cwd=None):
        for line in transcript:
            on_line(line)
        return returncode, "\n".join(transcript)

    monkeypatch.setattr(env_module, "run_uv", fake_run_uv)
    monkeypatch.setattr(env_module, "_stream_uv", fake_stream_uv)
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_env.py -v -k "bytes or prepared or explain_log"`
Expected: FAIL — `AttributeError: module 'exelent.runtime.env' has no attribute '_stream_uv'`

- [ ] **Step 3: Dodaj strumieniowe uruchamianie uv**

W `exelent/runtime/env.py`:

```python
def _stream_uv(
    uv: Path,
    args: Sequence[str],
    on_line: Callable[[str], None],
    *,
    cwd: Path | None = None,
) -> tuple[int, str]:
    """Uruchamia uv i oddaje jego stderr linia po linii, na żywo.

    `subprocess.run(capture_output=True)` buforuje całe wyjście do zakończenia
    procesu — przy instalacji trwającej minuty oznaczało to pasek postępu,
    który stoi, a potem skacze na koniec.

    Pełny tekst i tak zbieramy: `explain_log` potrzebuje go w całości, bo błąd
    potrafi paść wcześnie i tylko odbić się echem na końcu.

    `--color never` to tania polisa. Zmierzone wyjście na potoku nie zawierało
    sekwencji ANSI, ale regex, który się o nie przewróci, psuje pasek w sposób
    trudny do zauważenia.

    `CREATE_NO_WINDOW` zostaje: bez niej użytkownikowi GUI mignie czarne okno
    konsoli przy każdym wywołaniu uv.
    """
    collected: list[str] = []
    process = subprocess.Popen(
        [str(uv), *args, "--color", "never"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd else None,
        creationflags=CREATE_NO_WINDOW,
    )
    assert process.stderr is not None
    for line in process.stderr:
        collected.append(line.rstrip("\n"))
        on_line(line)
    process.wait()
    return process.returncode, "\n".join(collected)
```

Dopisz `from collections.abc import Callable, Sequence` do importów.

- [ ] **Step 4: Dodaj księgowanie bajtów**

W `exelent/runtime/env.py`:

```python
class _DownloadTally:
    """Ile już pobrano, jak szybko i ile zostało.

    uv na potoku raportuje ZAKOŃCZENIE pobrania, nie bajty w locie, więc
    licznik rósłby skokami — przy paczce wielkości `torch` byłby to jeden skok
    po kilkunastu minutach stania. Dlatego w obrębie paczek trwających
    interpolujemy po zaobserwowanej prędkości, z przycięciem na 95% ich
    rozmiaru: pasek, który dobił do końca i stoi, kłamie bardziej niż pasek
    stojący w 95%.

    Suma pochodzi z PyPI, a nie z linii uv — ZMIERZONE: uv nie drukuje
    `Downloading` dla małych paczek, więc suma z linii byłaby zaniżona i pasek
    nigdy nie dobiłby do końca.
    """

    _INFLIGHT_CAP = 0.95
    _SMOOTHING = 0.3

    def __init__(self, total_bytes: int) -> None:
        self._total = total_bytes
        self._done = 0
        self._sizes: dict[str, int] = {}
        self._inflight: dict[str, float] = {}
        self._speed = 0.0
        self._started = time.monotonic()
        self._last_tick = self._started

    def reset(self, total_bytes: int) -> None:
        """Nowa suma dla nowego pobrania.

        Instalacja interpretera poznaje swoj rozmiar dopiero z linii uv, wiec
        licznik musi umiec przyjac sume PO utworzeniu. Wolanie `__init__`
        wprost byloby tym samym, tylko bez nazwy.
        """
        self._total = total_bytes
        self._done = 0
        self._sizes.clear()
        self._inflight.clear()
        self._speed = 0.0
        self._started = time.monotonic()

    def start(self, name: str, size_bytes: int) -> None:
        self._sizes[name] = size_bytes
        self._inflight[name] = time.monotonic()

    def finish(self, name: str) -> None:
        self._done += self._sizes.get(name, 0)
        self._inflight.pop(name, None)
        self._tick()

    def complete(self) -> None:
        """`Prepared N packages` — wszystkie pobrania skończone, cokolwiek
        naliczyliśmy po drodze."""
        self._done = self._total
        self._inflight.clear()

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed = now - self._started
        if elapsed <= 0:
            return
        instant = self._done / elapsed
        # Srednia wykladnicza: zerwane lacze ma byc widac jako spadek, a nie
        # jako stala sprzed minuty.
        self._speed = instant if self._speed == 0.0 else (
            self._SMOOTHING * instant + (1 - self._SMOOTHING) * self._speed
        )
        self._last_tick = now

    def snapshot(self) -> tuple[int, int, float, float | None]:
        done = float(self._done)
        if self._speed > 0:
            for name, started in self._inflight.items():
                guessed = self._speed * (time.monotonic() - started)
                done += min(guessed, self._sizes.get(name, 0) * self._INFLIGHT_CAP)
        done = min(int(done), self._total) if self._total else int(done)
        remaining = max(self._total - done, 0)
        eta = remaining / self._speed if self._speed > 0 and self._total else None
        return done, self._total, self._speed, eta
```

Dopisz `import time` do importów.

- [ ] **Step 5: Połącz to w `create_build_env`**

Zamień krok instalacji paczek:

```python
def create_build_env(
    source: Path,
    packages: Sequence[str],
    progress: ProgressFn,
    *,
    python_version: str = TARGET_PYTHON,
    total_download_bytes: int = 0,
) -> BuildEnv:
    ...
    progress(Progress(phase="install_packages", fraction=0.5))
    wanted = [PYINSTALLER_SPEC, *packages]
    tally = _DownloadTally(total_download_bytes)

    def on_line(line: str) -> None:
        event = parse_line(line)
        if event is None:
            return
        if event.kind == DOWNLOAD_START:
            tally.start(event.name, event.size_bytes)
        elif event.kind == DOWNLOAD_DONE:
            tally.finish(event.name)
        elif event.kind == PREPARED:
            tally.complete()
        done, total, speed, eta = tally.snapshot()
        fraction = 0.5 + 0.5 * (done / total) if total else 0.5
        progress(
            Progress(
                phase="install_packages",
                fraction=fraction,
                done_bytes=done,
                total_bytes=total,
                speed_bps=speed,
                eta_s=eta,
            )
        )

    returncode, _text = _stream_uv(uv, ["pip", "install", "--python", str(python), *wanted], on_line)

    failed: list[str] = []
    if returncode != 0:
        # Instalacja hurtowa padla — probujemy pojedynczo, zeby jedna zla nazwa
        # paczki nie zabila calego builda.
        for spec in wanted:
            single = run_uv(uv, ["pip", "install", "--python", str(python), spec])
            if single.returncode != 0:
                failed.append(spec)

    done, total, speed, _eta = tally.snapshot()
    progress(
        Progress(
            phase="install_packages",
            fraction=1.0,
            done_bytes=total or done,
            total_bytes=total,
            speed_bps=speed,
        )
    )
    return BuildEnv(uv=uv, venv=venv, python=python, failed_packages=tuple(failed))
```

- [ ] **Step 6: Uruchom testy, w tym te wrażliwe na czas**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime tests/build -v`
Expected: PASS

Teraz przebieg pod obciążeniem — §11a specyfikacji ostrzega, że ta zmiana leży w kodzie anulowania podprocesu:

Run: `for i in 1 2 3 4 5; do .venv/Scripts/python.exe -m pytest -q tests/build/test_build_backend.py::test_cancel_during_silent_subprocess_returns_promptly; done`
Expected: 5/5 PASS. **Jeśli któryś padnie — nie ruszaj progu `elapsed < 3.0`.** Zbadaj, czy strumieniowe czytanie stderr nie blokuje wyjścia z pętli po anulowaniu; `for line in process.stderr` czeka na kolejną linię i przy zabitym procesie potrafi zawisnąć.

- [ ] **Step 7: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/runtime/env.py tests/runtime/test_env.py
git commit -m "feat: instalacja paczek raportuje bajty, predkosc i pozostaly czas"
```

---

### Task 12: Pobieranie uv i interpretera przez ten sam licznik

**Files:**
- Modify: `exelent/runtime/bootstrap.py`, `exelent/runtime/env.py`
- Test: `tests/runtime/test_bootstrap.py`

**Interfaces:**
- Consumes: `Progress`, `_DownloadTally`, `parse_line` (zadania 9–11).
- Produces: nic nowego.

`_download` w `bootstrap.py` zna `Content-Length` i czyta po 64 KB, więc ma bajty **dokładne** — wystarczy je przekazać. `uv python install` używa tego samego formatu linii co instalacja paczek (zmierzone), więc obsługuje go ten sam parser.

- [ ] **Step 1: Napisz padające testy**

```python
def test_uv_download_reports_real_bytes(monkeypatch, tmp_path):
    """`_download` zna Content-Length i czyta porcjami — bajty sa dokladne,
    nie zgadywane."""
    payload = b"x" * (300 * 1024)
    seen: list[Progress] = []
    _fake_urlopen(monkeypatch, payload)

    bootstrap._download(UV_URL, seen.append)

    assert seen[-1].total_bytes == len(payload)
    assert seen[-1].done_bytes == len(payload)
    assert seen[-1].phase == "download_uv"


def test_python_install_reports_bytes_through_the_same_parser(monkeypatch, tmp_path):
    """ZMIERZONE: `uv python install` drukuje ten sam ksztalt linii, tylko
    nazwa zawiera nawias — `cpython-... (download) (24.3MiB)`."""
    transcript = [
        "Downloading cpython-3.12.11-windows-x86_64-none (download) (24.3MiB)",
        " Downloading cpython-3.12.11-windows-x86_64-none (download)",
    ]
    seen: list[Progress] = []
    _run_fake_uv(monkeypatch, tmp_path, transcript)

    create_build_env(tmp_path, [], seen.append)

    python_phase = [u for u in seen if u.phase == "install_python"]
    assert python_phase and python_phase[-1].total_bytes > 0
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_bootstrap.py -v -k "real_bytes or same_parser"`
Expected: FAIL

- [ ] **Step 3: Zaimplementuj w `bootstrap._download`**

```python
def _download(url: str, progress: ProgressFn) -> bytes:
    buffer = io.BytesIO()
    started = time.monotonic()
    with urllib.request.urlopen(url, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        read = 0
        while chunk := response.read(64 * 1024):
            buffer.write(chunk)
            read += len(chunk)
            elapsed = time.monotonic() - started
            speed = read / elapsed if elapsed > 0 else 0.0
            remaining = max(total - read, 0)
            progress(
                Progress(
                    phase="download_uv",
                    fraction=read / total if total else 0.0,
                    done_bytes=read,
                    total_bytes=total,
                    speed_bps=speed,
                    eta_s=remaining / speed if speed > 0 and total else None,
                )
            )
    return buffer.getvalue()
```

Dopisz `import time` oraz import `Progress`.

- [ ] **Step 4: Przepuść instalację interpretera przez parser**

W `exelent/runtime/env.py` zamień wywołanie `uv python install`:

```python
    python_tally = _DownloadTally(0)

    def on_python_line(line: str) -> None:
        event = parse_line(line)
        if event is None:
            return
        if event.kind == DOWNLOAD_START:
            # Interpreter jest jednym pobraniem i uv podaje jego rozmiar
            # wprost — suma bierze sie wiec z tej linii, nie z PyPI.
            python_tally.reset(event.size_bytes)
            python_tally.start(event.name, event.size_bytes)
        elif event.kind == DOWNLOAD_DONE:
            python_tally.finish(event.name)
        done, total, speed, eta = python_tally.snapshot()
        progress(
            Progress(
                phase="install_python",
                fraction=0.3 * (done / total) if total else 0.0,
                done_bytes=done,
                total_bytes=total,
                speed_bps=speed,
                eta_s=eta,
            )
        )

    progress(Progress(phase="install_python", fraction=0.0))
    installed_code, installed_text = _stream_uv(
        uv, ["python", "install", python_version], on_python_line
    )
```

`_env_failure` przyjmuje dziś dwa `CompletedProcess`. Zmień jego sygnaturę na `(installed_code: int, installed_text: str, created)` i zachowaj obie własności opisane w jego docstringu: winny jest krok **pierwszy** z tych, które padły, a niezerowy kod z samego `uv python install` **nie** jest powodem do przerwania.

- [ ] **Step 5: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/runtime tests/runtime
git commit -m "feat: pobieranie uv i interpretera raportuje bajty tym samym licznikiem"
```

---

### Task 13: Formatowanie i druga linijka na ekranie budowania

**Files:**
- Create: `exelent/ui/format.py`, `tests/ui/test_format.py`
- Modify: `exelent/ui/screen_build.py`
- Modify: `exelent/i18n/pl.py`, `exelent/i18n/en.py`
- Test: `tests/ui/test_screen_build.py`

**Interfaces:**
- Consumes: `Progress` (zadanie 10).
- Produces: `human_size(bytes: int) -> str`, `human_speed(bps: float) -> str`, `human_duration(seconds: float) -> str`. Zadania 19–20 używają `human_size`.

`_human_size` jest dziś prywatne w `screen_build.py`. Cztery niezależne formatowania megabajtów (ekran 2, ekran 3, dwa okna) rozjadą się co do zaokrąglenia, więc funkcja przenosi się do wspólnego modułu.

- [ ] **Step 1: Napisz padające testy**

`tests/ui/test_format.py`:

```python
"""Jedno zrodlo formatowania rozmiarow i czasu.

Cztery niezalezne implementacje "ile to megabajtow" rozjada sie co do
zaokraglenia, a uzytkownik zobaczy 26,0 MB w oknie i 26 MB na ekranie obok.
"""

import pytest

from exelent.ui.format import human_duration, human_size, human_speed


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0 KB"), (512, "1 KB"), (1024, "1 KB"), (1024**2, "1.0 MB"), (26 * 1024**2, "26.0 MB")],
)
def test_human_size(value, expected):
    assert human_size(value) == expected


def test_human_speed_reads_per_second():
    assert human_speed(4.2 * 1024**2) == "4.2 MB/s"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(9, "9 s"), (75, "1 min 15 s"), (3600, "60 min 0 s")],
)
def test_human_duration(seconds, expected):
    assert human_duration(seconds) == expected
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_format.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exelent.ui.format'`

- [ ] **Step 3: Utwórz moduł**

`exelent/ui/format.py`:

```python
"""Rozmiary i czasy po ludzku. Jedyne miejsce, które je formatuje."""

from __future__ import annotations


def human_size(size_bytes: int) -> str:
    megabytes = size_bytes / 1024**2
    if megabytes >= 1:
        return f"{megabytes:.1f} MB"
    return f"{size_bytes / 1024:.0f} KB"


def human_speed(bytes_per_second: float) -> str:
    return f"{human_size(int(bytes_per_second))}/s"


def human_duration(seconds: float) -> str:
    total = int(seconds)
    if total < 60:
        return f"{total} s"
    return f"{total // 60} min {total % 60} s"
```

- [ ] **Step 4: Napisz padające testy ekranu 3**

Do `tests/ui/test_screen_build.py`:

```python
def test_byte_line_appears_only_while_something_is_downloading(qtbot, screen):
    """Pusty licznik megabajtow pod paskiem przy pakowaniu bylby gorszy niz
    jego brak, wiec ekran pozna to po `total_bytes == 0`."""
    screen.on_progress(Progress(phase="package", fraction=0.4))
    assert screen.bytes_label.isHidden() is True

    screen.on_progress(
        Progress(
            phase="install_packages",
            fraction=0.6,
            done_bytes=128 * 1024**2,
            total_bytes=210 * 1024**2,
            speed_bps=4.2 * 1024**2,
            eta_s=20,
        )
    )
    assert screen.bytes_label.isHidden() is False
    text = screen.bytes_label.text()
    assert "128.0 MB" in text and "210.0 MB" in text and "4.2 MB/s" in text and "20 s" in text


def test_byte_line_omits_eta_when_speed_is_unknown(qtbot, screen):
    screen.on_progress(
        Progress(phase="install_packages", fraction=0.1, done_bytes=0, total_bytes=1024**2)
    )
    assert screen.bytes_label.isHidden() is False
    assert "None" not in screen.bytes_label.text()
```

- [ ] **Step 5: Zaimplementuj drugą linijkę**

W `exelent/ui/screen_build.py`, w `__init__`, pod paskiem:

```python
        self.bytes_label = QLabel("", objectName="Muted")
        self.bytes_label.setVisible(False)
```

oraz `outer.addWidget(self.bytes_label)` zaraz po `outer.addWidget(self.bar)`.

```python
    def on_progress(self, update) -> None:
        self.phase_label.setText(t(update.phase))
        self.bar.setValue(int(update.fraction * 100))
        self._show_bytes(update)

    def _show_bytes(self, update) -> None:
        """Druga linijka tylko wtedy, gdy naprawdę coś się pobiera."""
        if not update.total_bytes:
            self.bytes_label.setVisible(False)
            return
        parts = [
            t(
                "progress_bytes",
                done=human_size(update.done_bytes),
                total=human_size(update.total_bytes),
            )
        ]
        if update.speed_bps > 0:
            parts.append(human_speed(update.speed_bps))
        if update.eta_s is not None:
            parts.append(t("progress_eta", eta=human_duration(update.eta_s)))
        self.bytes_label.setText(" · ".join(parts))
        self.bytes_label.setVisible(True)
```

W `_show_running` dodaj `self.bytes_label.setVisible(False)`, żeby drugi build nie zaczynał z licznikiem poprzedniego. Zamień lokalne `_human_size` na import z `exelent.ui.format` i usuń prywatną funkcję z końca pliku.

- [ ] **Step 6: Dodaj klucze**

`exelent/i18n/pl.py`:

```python
    "progress_bytes": "{done} z {total}",
    "progress_eta": "zostało {eta}",
```

`exelent/i18n/en.py`:

```python
    "progress_bytes": "{done} of {total}",
    "progress_eta": "{eta} left",
```

- [ ] **Step 7: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/ui tests/i18n -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/ui exelent/i18n tests/ui
git commit -m "feat: ekran budowania pokazuje megabajty, predkosc i pozostaly czas"
```

---

### Task 14: Tabela wkładów do EXE zastępuje płaską flagę „heavy"

**Files:**
- Create: `exelent/deps/sizes.py`, `tests/deps/test_sizes.py`
- Modify: `exelent/deps/aliases.py`, `exelent/deps/resolve.py`, `exelent/analysis/project.py`, `exelent/ui/screen_review.py`, `exelent/cli.py`
- Modify: `exelent/i18n/pl.py`, `exelent/i18n/en.py`

**Interfaces:**
- Consumes: `Dependency` (istnieje).
- Produces: `Contribution` (`frozen`, pola `low_mb: int`, `high_mb: int`, `measured: str`), `EXE_CONTRIBUTION: dict[str, Contribution]`, `estimate_exe_size(packages) -> tuple[int, int, tuple[str, ...]]`, `HEAVY_THRESHOLD_MB`, `LARGE_WARNING_MB = 300`.

Przyczyna zgłoszenia 7: `heavy` to flaga boolowska na zbiorze 12 nazw, a zdanie jest stałym tekstem — **nigdzie w tej ścieżce nie ma arytmetyki**. Skrypt z matplotlib dostaje to samo zdanie co skrypt z torch.

**Zejście na `Severity.INFO` wymaga zmiany w dwóch miejscach, inaczej nowy komunikat zniknie z ekranu zamiast zastąpić stary:** `screen_review.load` filtruje dziś `if i.severity is not Severity.INFO`, a `cli.run_build` przenosi dalej wszystko poza BLOCKERem (INFO przechodzi — tu zmiany nie trzeba).

- [ ] **Step 1: Napisz padające testy**

`tests/deps/test_sizes.py`:

```python
"""Rozmiar EXE to nie rozmiar pobierania.

PyInstaller wyrzuca z paczki to, czego kod nie dotyka — i wlasnie dlatego
skrypt z matplotlib, pandas i scipy dal 26 MB przy ostrzezeniu o "kilkuset
megabajtach". Widelki mowia prawde, ktorej jedna liczba nie umie powiedziec.
"""

import re

from exelent.deps.sizes import EXE_CONTRIBUTION, LARGE_WARNING_MB, estimate_exe_size


def test_estimate_returns_a_range_not_a_single_number():
    low, high, heaviest = estimate_exe_size(["matplotlib", "pandas", "scipy"])
    assert low < high
    assert heaviest[0] in {"scipy", "pandas", "matplotlib"}


def test_estimate_ignores_packages_we_have_not_measured():
    """Paczka spoza tabeli nie ma wkladu ZGADYWANEGO. Zgadywanie jest tym,
    co wywolalo zgloszenie 7."""
    low_alone, high_alone, _ = estimate_exe_size(["pandas"])
    low_with, high_with, _ = estimate_exe_size(["pandas", "jakas-mala-paczka"])
    assert (low_alone, high_alone) == (low_with, high_with)


def test_no_packages_means_no_estimate():
    assert estimate_exe_size([]) == (0, 0, ())


def test_heaviest_packages_come_first():
    _low, _high, heaviest = estimate_exe_size(["matplotlib", "scipy"])
    assert heaviest == ("scipy", "matplotlib")


def test_every_entry_declares_where_its_number_came_from():
    """Wpis bez zrodla to liczba wzieta z sufitu — dokladnie to, na co
    skarzy sie zgloszenie 7."""
    for package, contribution in EXE_CONTRIBUTION.items():
        assert contribution.measured, f"{package} nie mowi, skad ma swoje liczby"
        assert contribution.measured == "tymczasowe" or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", contribution.measured
        ), f"{package}: `measured` ma byc data albo slowem 'tymczasowe'"


def test_large_threshold_matches_the_spec():
    assert LARGE_WARNING_MB == 300
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/deps/test_sizes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exelent.deps.sizes'`

- [ ] **Step 3: Utwórz moduł z tabelą**

`exelent/deps/sizes.py`:

```python
"""Ile to zajmie: w EXE i w pobieraniu. To dwie różne liczby.

Rozmiar POBIERANIA jest dokładny — bierze się z rozwiązanych wersji i z PyPI
(zadania 16–17). Rozmiar EXE jest szacunkiem z widełkami, bo PyInstaller
wyrzuca z paczki to, czego kod nie dotyka: ten sam `pandas` waży inaczej w
skrypcie czytającym jeden CSV, a inaczej w programie używającym połowy API.

Zgłoszenie 7 mówi dokładnie o tym, że liczby wzięte z sufitu wprowadzają w
błąd. Dlatego każdy wpis niesie `measured` — datę pomiaru albo słowo
„tymczasowe". Zadanie 15 zamienia wszystkie „tymczasowe" na daty.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# Powyżej tylu megabajtów górnych widełek rozmiar przestaje być informacją,
# a staje się ostrzeżeniem (razem z uwagą o dłuższym budowaniu).
LARGE_WARNING_MB = 300

# Powyżej tylu megabajtów górnego wkładu paczka jest „ciężka" — to zastępuje
# dawny płaski `HEAVY_PACKAGES`.
HEAVY_THRESHOLD_MB = 15


@dataclass(frozen=True)
class Contribution:
    """Wkład paczki do gotowego EXE, w megabajtach.

    `measured` to data pomiaru w formacie `YYYY-MM-DD` albo słowo
    „tymczasowe". Test `test_every_entry_declares_where_its_number_came_from`
    pilnuje, że pole nigdy nie jest puste — liczba bez źródła jest tym,
    przeciwko czemu ten moduł powstał.
    """

    low_mb: int
    high_mb: int
    measured: str


# WSZYSTKIE wpisy sa TYMCZASOWE do czasu wykonania zadania 15.
EXE_CONTRIBUTION: dict[str, Contribution] = {
    "torch": Contribution(300, 900, "tymczasowe"),
    "tensorflow": Contribution(250, 700, "tymczasowe"),
    "transformers": Contribution(60, 200, "tymczasowe"),
    "scipy": Contribution(30, 70, "tymczasowe"),
    "opencv-python": Contribution(35, 70, "tymczasowe"),
    "matplotlib": Contribution(15, 40, "tymczasowe"),
    "pandas": Contribution(20, 45, "tymczasowe"),
    "numpy": Contribution(15, 30, "tymczasowe"),
    "PySide6": Contribution(40, 120, "tymczasowe"),
    "PyQt5": Contribution(40, 110, "tymczasowe"),
    "PyQt6": Contribution(40, 110, "tymczasowe"),
    "librosa": Contribution(20, 50, "tymczasowe"),
    "moviepy": Contribution(15, 40, "tymczasowe"),
}


def is_heavy(package: str) -> bool:
    entry = EXE_CONTRIBUTION.get(package)
    return entry is not None and entry.high_mb >= HEAVY_THRESHOLD_MB


def estimate_exe_size(packages: Iterable[str]) -> tuple[int, int, tuple[str, ...]]:
    """Widełki rozmiaru EXE i najcięższe paczki, od największej.

    Paczka spoza tabeli nie dokłada NIC — nie zgadujemy jej wkładu. Zgadywanie
    jest dokładnie tym, co wywołało zgłoszenie 7.
    """
    known = [(name, EXE_CONTRIBUTION[name]) for name in packages if name in EXE_CONTRIBUTION]
    if not known:
        return 0, 0, ()
    low = sum(c.low_mb for _name, c in known)
    high = sum(c.high_mb for _name, c in known)
    heaviest = tuple(name for name, _c in sorted(known, key=lambda p: -p[1].high_mb))
    return low, high, heaviest
```

- [ ] **Step 4: Usuń `HEAVY_PACKAGES` i przełącz `resolve.py`**

W `exelent/deps/aliases.py` usuń cały blok `HEAVY_PACKAGES`.
W `exelent/deps/resolve.py` zamień import na `from exelent.deps.sizes import is_heavy` i oba miejsca `heavy=base in HEAVY_PACKAGES` / `heavy=package in HEAVY_PACKAGES` na `heavy=is_heavy(base)` / `heavy=is_heavy(package)`.

- [ ] **Step 5: Zamień Issue w `analyze_project`**

W `exelent/analysis/project.py`:

```python
    heavy_packages = [dep.package for dep in dependencies if dep.heavy]
    low, high, heaviest = estimate_exe_size(heavy_packages)
    if heaviest:
        issues.append(
            Issue(
                "size_estimate_large" if high >= LARGE_WARNING_MB else "size_estimate",
                Severity.WARNING if high >= LARGE_WARNING_MB else Severity.INFO,
                {"low": str(low), "high": str(high), "packages": ", ".join(heaviest[:3])},
            )
        )
```

- [ ] **Step 6: Pokaż INFO na ekranie 2**

W `exelent/ui/screen_review.py`, w `load`, rozdziel ostrzeżenia od informacji — INFO ma **inny objectName**, żeby nie udawało ostrzeżenia:

```python
        warnings = [describe(i) for i in analysis.issues if i.severity is Severity.WARNING]
        notes = [describe(i) for i in analysis.issues if i.severity is Severity.INFO]
        self.warnings_label.setText("\n".join(warnings))
        self.warnings_label.setVisible(bool(warnings))
        self.notes_label.setText("\n".join(notes))
        self.notes_label.setVisible(bool(notes))
```

Dodaj `self.notes_label = QLabel("", objectName="Muted")` z `setWordWrap(True)` i `setVisible(False)` obok `warnings_label`, i wstaw do układu tuż za nim.

- [ ] **Step 7: Dodaj klucze, usuń stary**

Usuń `"heavy_packages"` z obu katalogów. Dodaj do `pl.py`:

```python
    "size_estimate": "Gotowy program zajmie około {low}–{high} MB. Najwięcej miejsca zajmą: {packages}.",
    "size_estimate_large": (
        "Gotowy program zajmie około {low}–{high} MB, a budowanie potrwa dłużej niż zwykle. "
        "Najwięcej miejsca zajmą: {packages}."
    ),
```

Do `en.py`:

```python
    "size_estimate": "The finished program will take about {low}–{high} MB. Largest: {packages}.",
    "size_estimate_large": (
        "The finished program will take about {low}–{high} MB and will take longer than usual "
        "to build. Largest: {packages}."
    ),
```

- [ ] **Step 8: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests -m "not slow" -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent tests
git commit -m "feat: szacunek rozmiaru EXE w widelkach zamiast stalego 'kilkaset MB'"
```

---

### Task 15: Zmierzenie tabeli wkładów

**Files:**
- Create: `tests/test_exe_contribution_measurement.py`
- Modify: `exelent/deps/sizes.py` (wypełnienie `measured` datami)
- Modify: `tests/deps/test_sizes.py`

**Interfaces:**
- Consumes: `EXE_CONTRIBUTION`, `run_build` (istnieje).
- Produces: tabela z realnymi liczbami.

To jest zadanie **pomiarowe**, nie kodujące. Zastąpienie jednego sufitu drugim nie byłoby naprawą zgłoszenia 7.

- [ ] **Step 1: Napisz skrypt pomiarowy jako test `slow`**

`tests/test_exe_contribution_measurement.py`:

```python
"""Pomiar wkladu paczek do EXE. Uruchamiany recznie, nie w CI.

    pytest tests/test_exe_contribution_measurement.py -m slow -s

Buduje minimalny skrypt-swiadek dla kazdej paczki z tabeli i drukuje realny
wklad = rozmiar EXE ze swiadkiem minus rozmiar EXE pustego skryptu. Wynik
przepisuje sie RECZNIE do `EXE_CONTRIBUTION` razem z dzisiejsza data.

Trwa dziesiatki minut i pobiera gigabajty. Dlatego `slow`.
"""

import pytest

from exelent.cli import run_build
from exelent.deps.sizes import EXE_CONTRIBUTION

# Import + JEDNO realne uzycie. Sam import bywa wycinany przez PyInstallera
# jako martwy, a wtedy pomiar klamie w dol.
WITNESSES = {
    "numpy": "import numpy\nprint(numpy.zeros(3).sum())\n",
    "pandas": "import pandas\nprint(pandas.DataFrame({'a': [1]}).sum())\n",
    "scipy": "import scipy.signal\nprint(scipy.signal.butter(2, 0.3))\n",
    "matplotlib": (
        "import matplotlib\nmatplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\nplt.plot([1, 2])\nplt.savefig('o.png')\n"
    ),
    "opencv-python": "import cv2\nimport numpy\nprint(cv2.cvtColor(numpy.zeros((2, 2, 3), 'uint8'), cv2.COLOR_BGR2GRAY).shape)\n",
    "PySide6": "from PySide6.QtCore import QObject\nprint(QObject())\n",
    "PyQt5": "from PyQt5.QtCore import QObject\nprint(QObject())\n",
    "PyQt6": "from PyQt6.QtCore import QObject\nprint(QObject())\n",
    "librosa": "import librosa\nprint(librosa.__version__)\n",
    "moviepy": "import moviepy\nprint(moviepy.__version__)\n",
    "transformers": "import transformers\nprint(transformers.__version__)\n",
    "torch": "import torch\nprint(torch.zeros(3).sum())\n",
    "tensorflow": "import tensorflow\nprint(tensorflow.__version__)\n",
}


def _build_size_mb(tmp_path, name: str, code: str) -> float:
    project = tmp_path / name.replace("-", "_")
    project.mkdir(parents=True)
    (project / "main.py").write_text(code, encoding="utf-8")
    result = run_build(project)
    assert result.ok, f"{name}: build padl — {[i.code for i in result.issues]}"
    return result.size_bytes / 1024**2


@pytest.mark.slow
def test_measure_every_entry_in_the_table(tmp_path):
    baseline = _build_size_mb(tmp_path, "baseline", "print('x')\n")
    print(f"\nBAZA (pusty skrypt): {baseline:.1f} MB\n")

    for package in sorted(EXE_CONTRIBUTION):
        code = WITNESSES.get(package)
        if code is None:
            print(f"{package}: BRAK swiadka — dopisz go przed pomiarem")
            continue
        size = _build_size_mb(tmp_path, package, code)
        print(f"{package}: {size - baseline:.1f} MB (EXE {size:.1f} MB)")


def test_every_table_entry_has_a_witness():
    """Wpis bez swiadka nigdy nie zostanie zmierzony i na zawsze zostanie
    liczba z sufitu."""
    missing = sorted(set(EXE_CONTRIBUTION) - set(WITNESSES))
    assert missing == [], f"brak skryptu-swiadka dla: {missing}"
```

- [ ] **Step 2: Uruchom pomiar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exe_contribution_measurement.py -m slow -s`
Expected: wypisane realne wkłady dla każdej paczki.

Paczka, której build padnie (np. `tensorflow` bez zgodnego koła), zostaje w tabeli z adnotacją `measured="tymczasowe"` i **musi** zostać wymieniona w podsumowaniu commita — nie udawaj, że została zmierzona.

- [ ] **Step 3: Przepisz wyniki do tabeli**

Dla każdej zmierzonej paczki ustaw `low_mb` na zaokrąglony wynik w dół, `high_mb` na wynik pomiaru powiększony o zapas na kod używający większej części API (proponowane: `+60%`, zaokrąglone w górę), a `measured` na dzisiejszą datę `YYYY-MM-DD`.

- [ ] **Step 4: Zaostrz test**

W `tests/deps/test_sizes.py` zamień test na wersję wymagającą daty dla zmierzonych i wypisującą pozostałe:

```python
def test_measured_entries_carry_a_real_date():
    provisional = sorted(
        name for name, c in EXE_CONTRIBUTION.items() if c.measured == "tymczasowe"
    )
    for name, contribution in EXE_CONTRIBUTION.items():
        if contribution.measured != "tymczasowe":
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", contribution.measured), name
    # Ten assert ma zostac czerwony, dopoki ktos nie zmierzy reszty.
    assert provisional == [], f"niezmierzone wpisy: {provisional}"
```

- [ ] **Step 5: Sprawdź szacunek na skrypcie ze zgłoszenia**

Zbuduj skrypt z matplotlib, pandas i scipy (ten, który dał 26 MB) i potwierdź, że mieści się w widełkach:

Run: `.venv/Scripts/python.exe -m exelent <katalog-ze-skryptem-testowym>`
Expected: rozmiar wyniku mieści się między `low` a `high` z komunikatu `size_estimate`.

**To jest kryterium sukcesu całej specyfikacji.** Jeśli nie trafia, popraw widełki, a nie test.

- [ ] **Step 6: Commit**

```bash
git add exelent/deps/sizes.py tests/deps/test_sizes.py tests/test_exe_contribution_measurement.py
git commit -m "fix: tabela wkladow do EXE zmierzona na prawdziwych buildach"
```

---

### Task 16: Rozmiary kół z PyPI

**Files:**
- Modify: `exelent/deps/sizes.py`
- Create: `tests/deps/fixtures/pypi_scipy.json`, `tests/deps/fixtures/pypi_pure.json`, `tests/deps/fixtures/pypi_sdist_only.json`
- Test: `tests/deps/test_sizes.py`

**Interfaces:**
- Consumes: nic.
- Produces: `wheel_size(payload: dict) -> int`, `download_size(specs: Sequence[str], timeout: float = 5.0) -> int`.

Zmierzone na żywym PyPI: `scipy 1.18.1` → 35,0 MB, `numpy 2.5.2` → 11,9 MB, `matplotlib 3.11.1` → 8,9 MB.

- [ ] **Step 1: Zapisz fixture'y**

Utwórz `tests/deps/fixtures/pypi_scipy.json` (przycięty do tego, co czytamy):

```json
{"urls": [
  {"packagetype": "sdist", "filename": "scipy-1.18.1.tar.gz", "size": 30000000},
  {"packagetype": "bdist_wheel", "filename": "scipy-1.18.1-cp311-cp311-win_amd64.whl", "size": 34000000},
  {"packagetype": "bdist_wheel", "filename": "scipy-1.18.1-cp312-cp312-win_amd64.whl", "size": 36700160},
  {"packagetype": "bdist_wheel", "filename": "scipy-1.18.1-cp312-cp312-manylinux_x86_64.whl", "size": 41000000}
]}
```

`tests/deps/fixtures/pypi_pure.json`:

```json
{"urls": [
  {"packagetype": "bdist_wheel", "filename": "six-1.17.0-py2.py3-none-any.whl", "size": 11053}
]}
```

`tests/deps/fixtures/pypi_sdist_only.json`:

```json
{"urls": [
  {"packagetype": "sdist", "filename": "stara-paczka-1.0.tar.gz", "size": 90000}
]}
```

- [ ] **Step 2: Napisz padające testy**

```python
def test_wheel_size_prefers_the_matching_windows_wheel():
    """Kolo dla innej wersji Pythona albo innego systemu to nie nasze kolo."""
    payload = json.loads((FIXTURES / "pypi_scipy.json").read_text(encoding="utf-8"))
    assert wheel_size(payload) == 36700160


def test_wheel_size_falls_back_to_a_pure_python_wheel():
    payload = json.loads((FIXTURES / "pypi_pure.json").read_text(encoding="utf-8"))
    assert wheel_size(payload) == 11053


def test_wheel_size_falls_back_to_sdist_as_a_last_resort():
    payload = json.loads((FIXTURES / "pypi_sdist_only.json").read_text(encoding="utf-8"))
    assert wheel_size(payload) == 90000


def test_wheel_size_of_empty_payload_is_zero():
    assert wheel_size({"urls": []}) == 0


def test_download_size_degrades_quietly_when_pypi_is_unreachable(monkeypatch):
    """Rozmiar pobierania jest WYGODA, a nie powodem, dla ktorego build ma
    nie ruszyc — ta sama zasada, ktora rzadzi `recent.py`."""
    import exelent.deps.sizes as sizes_module

    def boom(spec, timeout):
        raise OSError("brak sieci")

    monkeypatch.setattr(sizes_module, "_fetch_release", boom)
    assert download_size(["scipy==1.18.1", "numpy==2.5.2"]) == 0
```

- [ ] **Step 3: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/deps/test_sizes.py -v -k "wheel_size or download_size"`
Expected: FAIL — `ImportError: cannot import name 'wheel_size'`

- [ ] **Step 4: Zaimplementuj**

Do `exelent/deps/sizes.py`:

```python
import json
import urllib.request
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from exelent.constants import TARGET_PYTHON

# Znacznik ABI koła, którego naprawdę użyje build: CPython w wersji docelowej,
# 64-bitowy Windows. Koło dla innej wersji albo innego systemu opisuje plik,
# którego nigdy nie pobierzemy.
_TAG = f"cp{TARGET_PYTHON.replace('.', '')}"
_PLATFORM = "win_amd64"
_PYPI = "https://pypi.org/pypi/{name}/{version}/json"
_MAX_PARALLEL = 8


def wheel_size(payload: dict) -> int:
    """Rozmiar pliku, który uv naprawdę pobierze dla tej wersji.

    Kolejność prób: koło dla naszego ABI i systemu → koło uniwersalne
    (`py3-none-any`) → archiwum źródłowe. Nierozpoznany kształt odpowiedzi
    daje zero, a nie wyjątek: brak liczby jest do przeżycia, wyjątek w tle
    ekranu 2 nie.
    """
    urls = payload.get("urls") or []
    wheels = [u for u in urls if u.get("packagetype") == "bdist_wheel"]
    for candidate in wheels:
        name = candidate.get("filename", "")
        if _TAG in name and _PLATFORM in name:
            return int(candidate.get("size") or 0)
    for candidate in wheels:
        if "none-any" in candidate.get("filename", ""):
            return int(candidate.get("size") or 0)
    for candidate in urls:
        if candidate.get("packagetype") == "sdist":
            return int(candidate.get("size") or 0)
    return 0


def _fetch_release(spec: str, timeout: float) -> dict:
    name, _, version = spec.partition("==")
    with urllib.request.urlopen(_PYPI.format(name=name, version=version), timeout=timeout) as r:
        return json.load(r)


def download_size(specs: Sequence[str], timeout: float = 5.0) -> int:
    """Łączny rozmiar pobierania dla przypiętych `nazwa==wersja`.

    Zapytania idą równolegle, bo osiem kolejnych rundtripów do PyPI zajęłoby
    tyle, że ekran 2 zdążyłby się znudzić. KAŻDA porażka jest cicha i daje
    zero — wtedy warstwa wyżej sięga po szacunek z tabeli.
    """

    def one(spec: str) -> int:
        try:
            return wheel_size(_fetch_release(spec, timeout))
        except (OSError, ValueError, KeyError):
            return 0

    if not specs:
        return 0
    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, len(specs))) as pool:
        return sum(pool.map(one, specs))
```

- [ ] **Step 5: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/deps -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/deps/sizes.py tests/deps
git commit -m "feat: dokladny rozmiar pobierania z PyPI dla przypietych wersji"
```

---

### Task 17: Rozwiązanie zależności przez `uv pip install --dry-run`

**Files:**
- Modify: `exelent/deps/sizes.py`
- Test: `tests/deps/test_sizes.py`

**Interfaces:**
- Consumes: `parse_line`, `PACKAGE`, `WOULD_DOWNLOAD` (zadanie 9), `download_size` (zadanie 16).
- Produces: `DownloadPlan` (`frozen`, pola `specs: tuple[str, ...]`, `would_download: int`, `total_bytes: int`), `resolve_download_plan(uv, python, packages, run_dry=None) -> DownloadPlan`.

`--dry-run` mówi nie tylko *co*, ale i *ile z tego brakuje w cache* — dlatego drugi build tego samego projektu uczciwie melduje „nic do pobrania" zamiast straszyć liczbą, która już leży na dysku.

- [ ] **Step 1: Napisz padające testy**

```python
def test_dry_run_yields_pinned_specs_and_the_missing_count():
    transcript = (FIXTURES.parent.parent / "runtime" / "fixtures" / "uv_dry_run.txt").read_text(
        encoding="utf-8"
    )
    plan = resolve_download_plan(
        uv=Path("uv.exe"),
        python=Path("python.exe"),
        packages=["matplotlib", "pandas", "scipy"],
        run_dry=lambda *_a, **_k: transcript,
        measure=lambda specs, **_k: 0,
    )
    assert plan.would_download == 8
    assert "scipy==1.18.1" in plan.specs
    assert len(plan.specs) == 14


def test_nothing_to_download_when_everything_is_cached():
    """Pytanie o zgode na pobranie zera megabajtow uczy klikac OK bez
    czytania — wiec ta liczba musi byc prawdziwa."""
    transcript = "Resolved 3 packages in 12ms\nWould download 0 packages\n + six==1.17.0\n"
    plan = resolve_download_plan(
        uv=Path("uv.exe"),
        python=Path("python.exe"),
        packages=["six"],
        run_dry=lambda *_a, **_k: transcript,
        measure=lambda specs, **_k: 999,
    )
    assert plan.would_download == 0
    assert plan.total_bytes == 0


def test_resolution_failure_degrades_to_an_empty_plan():
    def boom(*_args, **_kwargs):
        raise OSError("uv nie wystartowal")

    plan = resolve_download_plan(
        uv=Path("uv.exe"), python=Path("python.exe"), packages=["scipy"], run_dry=boom
    )
    assert plan.specs == ()
    assert plan.total_bytes == 0
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/deps/test_sizes.py -v -k dry_run`
Expected: FAIL — `ImportError: cannot import name 'resolve_download_plan'`

- [ ] **Step 3: Zaimplementuj**

```python
@dataclass(frozen=True)
class DownloadPlan:
    specs: tuple[str, ...] = ()
    would_download: int = 0
    total_bytes: int = 0


def _default_run_dry(uv: Path, python: Path, packages: Sequence[str]) -> str:
    from exelent.runtime.env import run_uv

    result = run_uv(
        uv,
        ["pip", "install", "--python", str(python), "--dry-run", "--color", "never", *packages],
    )
    return result.stderr or ""


def resolve_download_plan(
    uv: Path,
    python: Path,
    packages: Sequence[str],
    *,
    run_dry=None,
    measure=None,
) -> DownloadPlan:
    """Co naprawdę zostanie pobrane i ile to waży.

    `--dry-run` daje pełne drzewo z PRZYPIĘTYMI wersjami oraz liczbę paczek,
    których brakuje w cache. Bez tej drugiej liczby okno pytałoby o zgodę na
    pobranie stu megabajtów, które już leżą na dysku.

    Rozmiar liczymy tylko wtedy, gdy jest co pobierać. Każda porażka — brak
    uv, brak sieci, nieznany kształt wyjścia — daje pusty plan, a warstwa
    wyżej sięga po szacunek z tabeli.
    """
    runner = run_dry or _default_run_dry
    measurer = measure or download_size
    try:
        text = runner(uv, python, packages)
    except (OSError, ValueError):
        return DownloadPlan()

    specs: list[str] = []
    would = 0
    for line in text.splitlines():
        event = parse_line(line)
        if event is None:
            continue
        if event.kind == PACKAGE:
            specs.append(event.name)
        elif event.kind == WOULD_DOWNLOAD:
            would = event.count

    total = measurer(specs) if would else 0
    return DownloadPlan(specs=tuple(specs), would_download=would, total_bytes=total)
```

Dopisz `from pathlib import Path` oraz `from exelent.runtime.uvlog import PACKAGE, WOULD_DOWNLOAD, parse_line`.

**Uwaga o warstwach:** `exelent/deps/sizes.py` importuje `run_uv` z `exelent.runtime.env` **wewnątrz funkcji**, a nie na górze modułu — `env.py` importuje `exelent.deps` pośrednio i import na poziomie modułu zamknąłby cykl. Uruchom `pytest tests/test_layering.py` po tej zmianie.

- [ ] **Step 4: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/deps tests/test_layering.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/deps/sizes.py tests/deps
git commit -m "feat: dokladny plan pobierania z uv --dry-run, z uwzglednieniem cache"
```

---

### Task 18: Trwałe ustawienia

**Files:**
- Create: `exelent/settings.py`, `tests/test_settings.py`

**Interfaces:**
- Consumes: `state_dir` (istnieje).
- Produces: `Settings` (`frozen`, pola `ask_before_download: bool = True`, `language: str | None = None`), `load_settings() -> Settings`, `save_settings(settings: Settings) -> None`.

Styl obronny skopiowany z `recent.py`, bo powody są te same: ustawienia to wygoda i nie mogą być powodem, dla którego program nie rusza.

- [ ] **Step 1: Napisz padające testy**

`tests/test_settings.py`:

```python
"""Ustawienia sa WYGODA i nie moga byc powodem, dla ktorego program nie rusza.

Ta sama zasada rzadzi `ui/recent.py`: uszkodzony plik oddaje wartosci domyslne,
a nieudany zapis nie przerywa pracy.
"""

import json

import pytest

from exelent.settings import Settings, load_settings, save_settings


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_defaults_when_nothing_was_ever_saved():
    settings = load_settings()
    assert settings.ask_before_download is True
    assert settings.language is None


def test_roundtrip():
    save_settings(Settings(ask_before_download=False, language="en"))
    assert load_settings() == Settings(ask_before_download=False, language="en")


def test_corrupt_file_gives_defaults_instead_of_crashing(tmp_path):
    path = tmp_path / "EXElent" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ to nie jest json", encoding="utf-8")
    assert load_settings() == Settings()


def test_a_json_list_is_not_settings(tmp_path):
    path = tmp_path / "EXElent" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(["czemu nie"]), encoding="utf-8")
    assert load_settings() == Settings()


def test_unknown_keys_are_ignored_and_missing_ones_filled_in(tmp_path):
    path = tmp_path / "EXElent" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"jakis_stary_klucz": 1, "language": "pl"}), encoding="utf-8")
    settings = load_settings()
    assert settings.language == "pl"
    assert settings.ask_before_download is True


def test_wrong_type_falls_back_to_the_default(tmp_path):
    path = tmp_path / "EXElent" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ask_before_download": "tak"}), encoding="utf-8")
    assert load_settings().ask_before_download is True


def test_failed_write_does_not_raise(monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("dysk tylko do odczytu")

    monkeypatch.setattr("pathlib.Path.write_text", boom)
    save_settings(Settings(ask_before_download=False))  # nie rzuca
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exelent.settings'`

- [ ] **Step 3: Zaimplementuj**

`exelent/settings.py`:

```python
"""Trwałe ustawienia użytkownika. Zwykły JSON, wyłącznie wartości skalarne.

Każda operacja jest bezpieczna w obie strony: uszkodzony albo niedostępny plik
oddaje wartości domyślne, a nieudany zapis nie przerywa pracy. Ustawienia są
wygodą, więc nie mogą być powodem, dla którego program nie rusza — dokładnie
jak lista ostatnich projektów.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from exelent.runtime.paths import state_dir


@dataclass(frozen=True)
class Settings:
    ask_before_download: bool = True
    language: str | None = None
    """`None` znaczy „idź za językiem systemu" — zachowuje dotychczasowe
    zachowanie dla każdego, kto niczego nie wybrał."""


def _file() -> Path:
    return state_dir() / "settings.json"


def load_settings() -> Settings:
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()

    default = Settings()
    ask = raw.get("ask_before_download", default.ask_before_download)
    language = raw.get("language", default.language)
    # Zly TYP jest tak samo mozliwy jak zly plik — recznie edytowany JSON
    # potrafi miec "tak" tam, gdzie ma byc true.
    return Settings(
        ask_before_download=ask if isinstance(ask, bool) else default.ask_before_download,
        language=language if isinstance(language, str) or language is None else default.language,
    )


def save_settings(settings: Settings) -> None:
    try:
        _file().parent.mkdir(parents=True, exist_ok=True)
        _file().write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
```

- [ ] **Step 4: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings.py tests/test_layering.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/settings.py tests/test_settings.py
git commit -m "feat: trwale ustawienia w stylu obronnym listy ostatnich projektow"
```

---

### Task 19: Preflight — ekran 2 pokazuje rozmiar pobierania

**Files:**
- Create: `exelent/ui/preflight.py`, `tests/ui/test_preflight.py`
- Modify: `exelent/ui/screen_review.py`, `exelent/ui/app.py`
- Modify: `exelent/i18n/pl.py`, `exelent/i18n/en.py`

**Interfaces:**
- Consumes: `resolve_download_plan`, `DownloadPlan` (zadanie 17), `uv_path` (istnieje w `bootstrap.py`).
- Produces: `PreflightWorker` z `finished = Signal(object)` (niesie `DownloadPlan`), metodami `start(packages)`, `stop()`, `plan()`.

Świadomy koszt: ekran 2 zaczyna dotykać sieci przy wejściu. Ograniczone do przypadku z zależnościami, w tle, nigdy nie blokujące budowania. Przy pierwszym uruchomieniu uv może jeszcze nie być na dysku — preflight **go nie pobiera**, to praca fazy budowania z własnym paskiem.

- [ ] **Step 1: Napisz padające testy**

`tests/ui/test_preflight.py`:

```python
"""Watek liczacy rozmiar pobierania dla ekranu 2.

Ekran nie moze sie zaciac na zapytaniu sieciowym, a jego porazka nie moze
zatrzymac budowania — to tylko liczba dla uzytkownika.
"""

from pathlib import Path

import pytest

from exelent.deps.sizes import DownloadPlan
from exelent.ui.preflight import PreflightWorker


@pytest.fixture
def worker(qtbot):
    w = PreflightWorker()
    yield w
    w.stop()


def test_no_dependencies_means_no_network_call(qtbot, worker, monkeypatch):
    called = []
    monkeypatch.setattr(worker, "_resolve", lambda packages: called.append(packages))
    with qtbot.waitSignal(worker.finished, timeout=2000) as blocker:
        worker.start([])
    assert called == []
    assert blocker.args[0].would_download == 0


def test_missing_uv_degrades_quietly(qtbot, worker, monkeypatch):
    """Preflight NIE pobiera uv — to praca fazy budowania, z wlasnym paskiem."""
    import exelent.ui.preflight as preflight_module

    monkeypatch.setattr(preflight_module, "uv_path", lambda: Path("nie-ma-mnie.exe"))
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(["scipy"])
    assert blocker.args[0] == DownloadPlan()


def test_result_reaches_the_signal(qtbot, worker, monkeypatch):
    expected = DownloadPlan(specs=("scipy==1.18.1",), would_download=1, total_bytes=36_700_160)
    monkeypatch.setattr(worker, "_resolve", lambda packages: expected)
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(["scipy"])
    assert blocker.args[0] == expected
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_preflight.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exelent.ui.preflight'`

- [ ] **Step 3: Zaimplementuj wątek**

`exelent/ui/preflight.py`:

```python
"""Ile trzeba będzie pobrać — policzone w tle, zanim użytkownik kliknie.

Rozwiązanie zależności woła uv i PyPI, więc nie może biec w wątku okna.
Wątek jest anulowalny i cicho degraduje: brak uv, brak sieci albo błąd PyPI
zostawia pusty plan, a ekran wraca do szacunku z tabeli.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QObject, QThread, Signal

from exelent.constants import TARGET_PYTHON
from exelent.deps.sizes import DownloadPlan, resolve_download_plan
from exelent.runtime.bootstrap import uv_path

_THREAD_QUIT_TIMEOUT_MS = 5000


class _Job(QObject):
    finished = Signal(object)

    def __init__(self, packages: Sequence[str], resolve) -> None:
        super().__init__()
        self._packages = list(packages)
        self._resolve = resolve

    def run(self) -> None:
        try:
            plan = self._resolve(self._packages)
        except Exception:  # noqa: BLE001 - liczba dla uzytkownika nie moze zabic okna
            plan = DownloadPlan()
        self.finished.emit(plan)


class PreflightWorker(QObject):
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._thread: QThread | None = None
        self._job: _Job | None = None
        self._plan = DownloadPlan()

    def plan(self) -> DownloadPlan:
        return self._plan

    def _resolve(self, packages: Sequence[str]) -> DownloadPlan:
        uv = uv_path()
        if not uv.exists():
            # Preflight NIE pobiera uv. To praca fazy budowania, ktora ma na to
            # wlasny pasek postepu — sciaganie 15 MB w tle ekranu 2, bez slowa
            # do uzytkownika, byloby niespodzianka.
            return DownloadPlan()
        python = uv.parent / "preflight-venv" / "Scripts" / "python.exe"
        return resolve_download_plan(uv=uv, python=python, packages=packages)

    def start(self, packages: Sequence[str]) -> None:
        self.stop()
        if not packages:
            self._plan = DownloadPlan()
            self.finished.emit(self._plan)
            return
        self._thread = QThread()
        self._job = _Job(packages, self._resolve)
        self._job.moveToThread(self._thread)
        self._job.finished.connect(self._on_done)
        self._thread.started.connect(self._job.run)
        self._thread.start()

    def _on_done(self, plan: DownloadPlan) -> None:
        self._plan = plan
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.quit()
            thread.wait(_THREAD_QUIT_TIMEOUT_MS)
        self._job = None
        self.finished.emit(plan)

    def stop(self) -> None:
        """Zatrzymuje trwające liczenie i CZEKA na wątek.

        Qt niszczy działający `QThread` przy wychodzeniu (abort), więc
        `MainWindow.closeEvent` musi to zawołać — tak samo jak robi to dla
        `BuildWorker.shutdown`.
        """
        thread = self._thread
        if thread is None:
            return
        thread.quit()
        thread.wait(_THREAD_QUIT_TIMEOUT_MS)
        self._thread = None
        self._job = None
```

- [ ] **Step 4: Podłącz do ekranu 2 i do okna**

W `exelent/ui/screen_review.py` dopisz do importow `from exelent.ui.format import human_size`, a w `__init__`, pod `deps_box`:

```python
        self.deps_size_label = QLabel("", objectName="Muted")
        deps_layout.addWidget(self.deps_size_label)
```

W `load()`, po ustawieniu `deps_label`:

```python
        self.deps_size_label.setText(t("download_checking") if packages else "")
```

I metoda przyjmująca wynik:

```python
    def show_download_plan(self, plan) -> None:
        """Wynik preflightu. Pusty plan zostawia pole puste — brak liczby jest
        lepszy niż liczba zmyślona."""
        if plan.would_download == 0 and not plan.specs:
            self.deps_size_label.setText("")
            return
        if plan.would_download == 0:
            self.deps_size_label.setText(t("download_nothing"))
            return
        self.deps_size_label.setText(
            t(
                "download_size",
                count=str(plan.would_download),
                size=human_size(plan.total_bytes),
            )
        )
```

W `exelent/ui/app.py`:

```python
        self.preflight = PreflightWorker()
        self.preflight.finished.connect(self.screen_review.show_download_plan)
```

W `_on_folder_chosen`, po `self.screen_review.load(...)`:

```python
        analysis = analyze_project(folder)
        self.screen_review.load(analysis)
        self.preflight.start([d.package for d in analysis.dependencies if not d.optional])
        self.go_to(SCREEN_REVIEW)
```

W `closeEvent`, przed `self.worker.shutdown()`:

```python
        self.preflight.stop()
```

W `_on_back_to_drop` dodaj `self.preflight.stop()` — wyjście z ekranu 2 zatrzymuje liczenie.

- [ ] **Step 5: Dodaj klucze**

`exelent/i18n/pl.py`:

```python
    "download_checking": "sprawdzam rozmiar…",
    "download_size": "{count} paczek — około {size} do pobrania",
    "download_nothing": "Wszystko już pobrane — budowanie ruszy od razu",
```

`exelent/i18n/en.py`:

```python
    "download_checking": "checking size…",
    "download_size": "{count} packages — about {size} to download",
    "download_nothing": "Everything is already downloaded — the build starts right away",
```

- [ ] **Step 6: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests/ui tests/i18n -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent/ui exelent/i18n tests/ui
git commit -m "feat: ekran przegladu liczy rozmiar pobierania w tle"
```

---

### Task 20: Okno zgody przed pobieraniem

**Files:**
- Create: `exelent/ui/dialog_download.py`, `tests/ui/test_dialogs.py`
- Modify: `exelent/ui/app.py`, `exelent/ui/worker.py`, `exelent/cli.py`, `exelent/runtime/env.py`
- Modify: `exelent/i18n/pl.py`, `exelent/i18n/en.py`

**Interfaces:**
- Consumes: `DownloadPlan` (17), `Settings`/`load_settings`/`save_settings` (18), `PreflightWorker.plan()` (19).
- Produces: `DownloadDialog(plan, parent=None)` z `dont_ask_again() -> bool`; `BuildPlan.total_download_bytes: int`.

Okno **nie** pojawia się, gdy wszystko jest w cache — pytanie o zgodę na pobranie zera megabajtów uczy użytkownika klikać „OK" bez czytania.

- [ ] **Step 1: Napisz padające testy**

`tests/ui/test_dialogs.py`:

```python
"""Okno zgody przed pobieraniem.

Pytanie o zgode na pobranie ZERA megabajtow uczy uzytkownika klikac OK bez
czytania — dlatego to okno musi umiec sie nie pokazac.
"""

import pytest

from exelent.deps.sizes import DownloadPlan
from exelent.settings import Settings, load_settings, save_settings
from exelent.ui.dialog_download import DownloadDialog, should_ask


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_no_question_when_everything_is_cached():
    assert should_ask(DownloadPlan(would_download=0), Settings()) is False


def test_no_question_when_the_user_turned_it_off():
    plan = DownloadPlan(would_download=8, total_bytes=100 * 1024**2)
    assert should_ask(plan, Settings(ask_before_download=False)) is False


def test_question_when_there_is_something_to_download():
    plan = DownloadPlan(would_download=8, total_bytes=100 * 1024**2)
    assert should_ask(plan, Settings()) is True


def test_dialog_shows_the_real_numbers(qtbot):
    plan = DownloadPlan(
        specs=("scipy==1.18.1", "numpy==2.5.2"), would_download=2, total_bytes=48 * 1024**2
    )
    dialog = DownloadDialog(plan)
    qtbot.addWidget(dialog)
    assert "48.0 MB" in dialog.summary_label.text()
    assert "2" in dialog.summary_label.text()
    assert "scipy" in dialog.packages_label.text()


def test_dont_ask_again_persists(qtbot):
    plan = DownloadPlan(would_download=1, total_bytes=1024**2)
    dialog = DownloadDialog(plan)
    qtbot.addWidget(dialog)
    dialog.dont_ask_checkbox.setChecked(True)
    dialog.accept()
    save_settings(Settings(ask_before_download=not dialog.dont_ask_again()))
    assert load_settings().ask_before_download is False
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_dialogs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exelent.ui.dialog_download'`

- [ ] **Step 3: Zaimplementuj okno**

`exelent/ui/dialog_download.py`:

```python
"""Zgoda na pobranie — z prawdziwą liczbą megabajtów.

Okno nie pojawia się, gdy nie ma czego pobierać. Pytanie o zgodę na pobranie
zera megabajtów uczy użytkownika klikać „OK" bez czytania, a wtedy przestaje
działać także wtedy, gdy naprawdę ma coś do powiedzenia.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from exelent.deps.sizes import DownloadPlan
from exelent.i18n import t
from exelent.settings import Settings
from exelent.ui.format import human_size

# Ile pozycji wymieniamy z nazwy. Pelna lista czternastu paczek to sciana
# tekstu, ktorej nikt nie czyta.
_NAMED = 3


def should_ask(plan: DownloadPlan, settings: Settings) -> bool:
    return bool(plan.would_download) and settings.ask_before_download


class DownloadDialog(QDialog):
    def __init__(self, plan: DownloadPlan, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("dialog_download_title"))

        self.summary_label = QLabel(
            t(
                "dialog_download_body",
                count=str(plan.would_download),
                size=human_size(plan.total_bytes),
            )
        )
        self.summary_label.setWordWrap(True)

        names = ", ".join(spec.split("==")[0] for spec in plan.specs[:_NAMED])
        self.packages_label = QLabel(names, objectName="Muted")
        self.packages_label.setWordWrap(True)

        self.dont_ask_checkbox = QCheckBox(t("dialog_download_dont_ask"))

        buttons = QDialogButtonBox()
        buttons.addButton(t("dialog_download_ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(t("dialog_download_cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.packages_label)
        layout.addWidget(self.dont_ask_checkbox)
        layout.addWidget(buttons)

    def dont_ask_again(self) -> bool:
        return self.dont_ask_checkbox.isChecked()
```

- [ ] **Step 4: Wepnij w start budowania**

W `exelent/ui/app.py` dopisz do importow:

```python
from dataclasses import replace

from PySide6.QtWidgets import QDialog

from exelent.settings import load_settings, save_settings
from exelent.ui.dialog_download import DownloadDialog, should_ask
```

i zamien metode:

```python
    def _on_build_requested(self, plan) -> None:
        """Ekran 3 czyszczony PRZED pokazaniem, build startuje po przejściu."""
        download = self.preflight.plan()
        settings = load_settings()
        if should_ask(download, settings):
            dialog = DownloadDialog(download, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return  # zostajemy na ekranie 2, nic nie ruszylo
            if dialog.dont_ask_again():
                save_settings(replace(settings, ask_before_download=False))

        plan = replace(plan, total_download_bytes=download.total_bytes)
        self.screen_build.start(plan)
        self.go_to(SCREEN_BUILD)
        self.worker.start(plan)
```

- [ ] **Step 5: Przeprowadź sumę do licznika bajtów**

W `exelent/models.py`, w `BuildPlan`:

```python
    total_download_bytes: int = 0
```

W `exelent/ui/worker.py`, w `_Job.run`, dopisz do wywołania `run_build`:

```python
                total_download_bytes=plan.total_download_bytes,
```

W `exelent/cli.py`, w `_build`, przekaż to dalej:

```python
    env = create_build_env(
        plan.root,
        plan.packages,
        scale.stage(0.0, ENV_PROGRESS_SHARE),
        total_download_bytes=plan.total_download_bytes,
    )
```

`make_plan` musi przyjąć `total_download_bytes` jako kolejny opcjonalny override — dopisz go do sygnatury i do zwracanego `BuildPlan`.

- [ ] **Step 6: Dodaj klucze**

`exelent/i18n/pl.py`:

```python
    "dialog_download_title": "Potrzebne dodatki",
    "dialog_download_body": (
        "Do zbudowania programu trzeba pobrać {count} paczek — około {size}. "
        "Pobieranie odbywa się raz; następne budowania będą szybsze."
    ),
    "dialog_download_ok": "Pobierz i buduj",
    "dialog_download_cancel": "Anuluj",
    "dialog_download_dont_ask": "Nie pytaj ponownie",
```

`exelent/i18n/en.py`:

```python
    "dialog_download_title": "Required extras",
    "dialog_download_body": (
        "Building this program needs {count} packages — about {size}. "
        "This happens once; later builds will be faster."
    ),
    "dialog_download_ok": "Download and build",
    "dialog_download_cancel": "Cancel",
    "dialog_download_dont_ask": "Do not ask again",
```

- [ ] **Step 7: Uruchom testy**

Run: `.venv/Scripts/python.exe -m pytest tests -m "not slow" -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
git add exelent tests
git commit -m "feat: okno zgody przed pobieraniem z prawdziwym rozmiarem"
```

---

### Task 21: Ustawienia z ekranu 1 i działający przełącznik języka

**Files:**
- Create: `exelent/ui/dialog_settings.py`
- Modify: `exelent/ui/screen_drop.py`, `exelent/ui/screen_review.py`, `exelent/ui/screen_build.py`, `exelent/ui/app.py`
- Modify: `exelent/i18n/pl.py`, `exelent/i18n/en.py`
- Test: `tests/ui/test_dialogs.py`, `tests/ui/test_app_shell.py`

**Interfaces:**
- Consumes: `Settings`, `load_settings`, `save_settings` (18), `MainWindow.set_language` i `language_changed` (istnieją).
- Produces: `SettingsDialog(settings, parent=None)` z `chosen() -> Settings`; `retranslate()` na każdym z trzech ekranów.

`language_changed` istnieje w kodzie i **nikt go dziś nie słucha** — jedyną drogą do angielskiej wersji jest zmiana języka systemu. Bez metod `retranslate` przełącznik zadziała dopiero po restarcie, co jest dokładnie tą klasą niespodzianki, którą ta specyfikacja usuwa.

- [ ] **Step 1: Napisz padające testy**

Do `tests/ui/test_dialogs.py`:

```python
def test_settings_dialog_reports_what_the_user_picked(qtbot):
    dialog = SettingsDialog(Settings(ask_before_download=True, language=None))
    qtbot.addWidget(dialog)
    dialog.ask_checkbox.setChecked(False)
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("en"))
    assert dialog.chosen() == Settings(ask_before_download=False, language="en")


def test_settings_dialog_offers_following_the_system(qtbot):
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    assert dialog.language_combo.findData(None) >= 0
```

Do `tests/ui/test_app_shell.py`:

```python
def test_language_switch_repaints_the_open_screens(qtbot):
    """`language_changed` istnial, ale nikt go nie sluchal — przelacznik
    dzialalby dopiero po restarcie programu."""
    from exelent.ui.app import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.set_language("pl")
    polish = window.screen_drop.headline.text()

    window.set_language("en")
    assert window.screen_drop.headline.text() != polish
    assert window.screen_drop.headline.text() == CATALOGS["en"]["drop_headline"]


def test_saved_language_wins_over_the_system_at_startup(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_settings(Settings(language="en"))

    from exelent.ui.app import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.screen_drop.headline.text() == CATALOGS["en"]["drop_headline"]
```

- [ ] **Step 2: Uruchom i potwierdź, że padają**

Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_dialogs.py tests/ui/test_app_shell.py -v -k "settings_dialog or language"`
Expected: FAIL

- [ ] **Step 3: Utwórz okno ustawień**

`exelent/ui/dialog_settings.py`:

```python
"""Ustawienia programu. Dwa przełączniki — i oba mają widoczny skutek."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
)

from exelent.i18n import t
from exelent.settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("settings_title"))

        self.ask_checkbox = QCheckBox(t("settings_ask_download"))
        self.ask_checkbox.setChecked(settings.ask_before_download)

        self.language_combo = QComboBox()
        # `None` znaczy "idz za systemem" — to zachowanie domyslne i musi dac
        # sie do niego wrocic, a nie tylko z niego wyjsc.
        self.language_combo.addItem(t("settings_language_system"), None)
        self.language_combo.addItem("Polski", "pl")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(max(self.language_combo.findData(settings.language), 0))

        form = QFormLayout()
        form.addRow(self.ask_checkbox)
        form.addRow(t("settings_language"), self.language_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def chosen(self) -> Settings:
        return Settings(
            ask_before_download=self.ask_checkbox.isChecked(),
            language=self.language_combo.currentData(),
        )
```

- [ ] **Step 4: Dodaj `retranslate` do trzech ekranów**

Każdy ekran dostaje metodę przepisującą swoje napisy z `t()`. W `screen_drop.py`:

```python
    def retranslate(self) -> None:
        """Przepisuje napisy po zmianie języka.

        Ekrany biorą teksty z `t()` w konstruktorze, więc bez tej metody
        przełącznik języka działałby dopiero po restarcie programu.
        """
        self.headline.setText(t("drop_headline"))
        self.browse.setText(t("drop_browse"))
        self.recent_label.setText(t("drop_recent"))
        self.settings_button.setToolTip(t("settings_title"))
```

Analogicznie w `screen_review.py` (nagłówek, podpisy wierszy, przyciski, tytuł dodatków) i `screen_build.py` (przyciski i etykieta fazy). Dla `ReviewScreen` po przepisaniu podpisów zawołaj ponownie `self.load(self._analysis)`, gdy analiza jest wczytana — pozycje list i dopiski „(zalecane)" też są tekstem.

`FactRow` potrzebuje do tego settera podpisu:

```python
    def set_caption(self, caption: str) -> None:
        self._caption.setText(caption)
```

- [ ] **Step 5: Dodaj koło zębate i podłącz wszystko w oknie**

W `screen_drop.py`, w `__init__`:

```python
        self.settings_button = QPushButton("⚙", objectName="Link")
        self.settings_button.setToolTip(t("settings_title"))
        self.settings_button.clicked.connect(self.settings_requested)
```

z sygnałem `settings_requested = Signal()` na klasie i przyciskiem wstawionym w prawym górnym rogu układu.

W `exelent/ui/app.py` dopisz `from exelent.ui.dialog_settings import SettingsDialog` do importow, a nastepnie:

```python
    def __init__(self) -> None:
        super().__init__()
        settings = load_settings()
        # Jezyk PIERWSZY, przed ekranami — patrz komentarz nizej. Wybor
        # zapisany bije jezyk systemu; `None` znaczy "idz za systemem".
        set_language(settings.language or system_language())
        ...
        self.screen_drop.settings_requested.connect(self._on_settings)
        self.language_changed.connect(self._retranslate)

    def _on_settings(self) -> None:
        dialog = SettingsDialog(load_settings(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.chosen()
        save_settings(chosen)
        self.set_language(chosen.language or system_language())

    def _retranslate(self, _lang: str) -> None:
        for screen in (self.screen_drop, self.screen_review, self.screen_build):
            screen.retranslate()
```

- [ ] **Step 6: Dodaj klucze**

`exelent/i18n/pl.py`:

```python
    "settings_title": "Ustawienia",
    "settings_ask_download": "Pytaj przed pobieraniem dodatków",
    "settings_language": "Język",
    "settings_language_system": "Jak w systemie",
```

`exelent/i18n/en.py`:

```python
    "settings_title": "Settings",
    "settings_ask_download": "Ask before downloading extras",
    "settings_language": "Language",
    "settings_language_system": "Same as system",
```

- [ ] **Step 7: Uruchom cały pakiet**

Run: `.venv/Scripts/python.exe -m pytest tests -m "not slow" -q`
Expected: PASS

- [ ] **Step 8: Sprawdź program ręcznie**

Run: `.venv/Scripts/python.exe -m exelent`

Przejdź całą ścieżkę ze zgłoszeń: przeciągnij pojedynczy plik `.txt` z Pobranych, sprawdź że wybrany jest plik (a nie katalog), cofnij się, wejdź w ustawienia, przełącz język i potwierdź, że okno zmienia się natychmiast.

- [ ] **Step 9: Commit**

```bash
.venv/Scripts/python.exe -m ruff check exelent tests
.venv/Scripts/python.exe -m ruff format --check exelent tests
git add exelent tests
git commit -m "feat: ustawienia z ekranu startowego i dzialajacy przelacznik jezyka"
```

---

## Mapa pokrycia specyfikacji

| Sekcja specyfikacji | Zadania |
|---|---|
| §4 tryb jednoplikowy | 5, 6, 7, 8 |
| §5 nawigacja wstecz | 3, 4 |
| §6 postać wyniku i rekomendacje | 1, 2 |
| §7.1 rozmiar pobierania | 16, 17 |
| §7.2 rozmiar EXE | 14 |
| §7.3 pomiar tabeli | 15 |
| §8.1 protokół postępu + inwentarz i18n | 10 |
| §8.2 parser uv i strumieniowanie | 9, 11 |
| §8.3 pułapki (małe paczki, interpreter) | 9, 11, 12 |
| §8.4 prędkość, ETA, interpolacja | 11, 13 |
| §9.1 magazyn ustawień | 18 |
| §9.2 okno przed pobieraniem | 20 |
| §9.3 ustawienia z ekranu 1 + język | 21 |
| §9.4 preflight | 19 |
| §10 komunikaty i wspólne formatowanie | 13 (moduł), reszta rozproszona po zadaniach |
| §11 testy | wbudowane w każde zadanie |
| §11a punkt wyjścia | 11 krok 6 |
