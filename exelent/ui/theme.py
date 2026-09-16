"""Theme. A single token palette generates the QSS stylesheet.

Accent color and corner radii are defined once and used everywhere — the
difference between an intentional appearance and default Qt.
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
/* The `QWidget` rule above gives labels an OPAQUE window background, so every
   label on a card or drop zone cut out a dark rectangle. This is visible only
   when rendered; the stylesheet text itself is valid. */
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
/* Without this rule `setEnabled(False)` changes NOTHING visually: the sheet
   sets background and text colors directly, leaving Qt nothing to dim. A
   disabled "Create EXE" looked active, so users clicked a dead button instead
   of reading the problem. This targets only `#Primary`, currently the only
   button the application disables. */
QPushButton#Primary:disabled {{ background: {surface_alt}; color: {text_muted}; }}
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
    """Whether Windows is configured to use a dark theme.

    If the registry cannot be read, choose dark: it is the default on newer
    installations, so a wrong guess is less conspicuous.
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
