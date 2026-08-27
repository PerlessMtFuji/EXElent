"""`python -m exelent` uruchamia GUI."""

import sys

from exelent.ui.app import run_gui

if __name__ == "__main__":
    raise SystemExit(run_gui(sys.argv))
