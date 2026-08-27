"""Motyw. Jedna paleta tokenów, z niej generowany arkusz QSS.

Kolor akcentu i promienie zaokrągleń zdefiniowane raz, użyte wszędzie — to jest
różnica między wyglądem przemyślanym a domyślnym Qt.
"""

from __future__ import annotations

PALETTE_DARK: dict[str, str] = {
    "bg": "#12131a",
    "surface": "#1b1d26",
    "surface_alt": "#232634",
    "text": "#f2f3f7",
    "text_muted": "#9aa0b4",
    "accent": "#6d7cff",
    "accent_hover": "#8290ff",
    "border": "#2d3142",
    "danger": "#ff6b6b",
    "success": "#4ade80",
}

PALETTE_LIGHT: dict[str, str] = {
    "bg": "#f6f7fb",
    "surface": "#ffffff",
    "surface_alt": "#eef0f7",
    "text": "#14161f",
    "text_muted": "#5d6377",
    "accent": "#4f5bd5",
    "accent_hover": "#3b46b8",
    "border": "#d8dbe8",
    "danger": "#d93a3a",
    "success": "#1f9d55",
}

_QSS = """
QWidget {{
    background: {bg};
    color: {text};
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    font-size: 14px;
}}
/* Reguła `QWidget` wyżej daje etykietom NIEPRZEZROCZYSTE tło okna, więc każdy
   napis na karcie albo w strefie zrzutu wycinał w niej ciemny prostokąt.
   Widać to wyłącznie w renderingu — arkusz jako napis jest poprawny. */
QLabel {{ background: transparent; }}
QLabel#Title {{ font-size: 26px; font-weight: 600; }}
QLabel#Muted {{ color: {text_muted}; }}
QFrame#Card {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 14px;
}}
QFrame#DropZone {{
    background: {surface};
    border: 2px dashed {border};
    border-radius: 20px;
}}
QFrame#DropZone[active="true"] {{ border-color: {accent}; background: {surface_alt}; }}
QPushButton {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 9px 18px;
}}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton#Primary {{
    background: {accent};
    border: none;
    color: #ffffff;
    font-weight: 600;
    padding: 12px 28px;
}}
QPushButton#Primary:hover {{ background: {accent_hover}; }}
QPushButton#Link {{
    background: transparent;
    border: none;
    color: {accent};
    padding: 2px 4px;
}}
QProgressBar {{
    background: {surface_alt};
    border: none;
    border-radius: 6px;
    height: 10px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 6px; }}
QPlainTextEdit {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 10px;
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 12px;
}}
QLineEdit, QComboBox {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 7px 10px;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {accent}; }}
"""


def build_stylesheet(dark: bool) -> str:
    palette = PALETTE_DARK if dark else PALETTE_LIGHT
    return _QSS.format(**palette)


def is_system_dark() -> bool:
    """Czy Windows jest ustawiony na motyw ciemny.

    Gdy rejestru nie da się przeczytać, wybieramy ciemny: to ustawienie
    domyślne w nowszych instalacjach, więc pomyłka jest mniej widoczna.
    """
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except OSError:
        return True
