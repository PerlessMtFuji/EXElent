"""Stałe całego projektu. Wszystkie wersje przypięte — nigdy 'latest'."""

APP_NAME = "EXElent"
UV_VERSION = "0.8.17"
TARGET_PYTHON = "3.12"
PYINSTALLER_SPEC = "pyinstaller==6.16.0"

MAX_SCAN_FILES = 3000
MAX_SCAN_BYTES = 500 * 1024 * 1024
MIN_FREE_DISK_BYTES = 3 * 1024 * 1024 * 1024

# Ile plikow wolno dociagnac lancuchowi importow lokalnych w trybie
# jednoplikowym. Limit istnieje po to, zeby jeden `import` w skrypcie
# upuszczonym z Pobranych nie wciagnal polowy tego katalogu.
MAX_SINGLE_FILE_IMPORTS = 50

EXCLUDED_DIRS = frozenset(
    {
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "build",
        "dist",
        ".idea",
        ".vscode",
        "site-packages",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)
