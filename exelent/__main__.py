"""GUI domyślnie; jawne --cli pozwala automatyzować również spakowany produkt."""

import os
import sys
from contextlib import ExitStack, redirect_stderr, redirect_stdout


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if argv[1:2] == ["--cli"]:
        from exelent.cli import main as run_cli

        # Bootloader --windowed nie udostępnia strumieni konsoli.
        # Wynik automatyzacji można odebrać przez --report.
        with ExitStack() as stack:
            if sys.stdout is None or sys.stderr is None:
                sink = stack.enter_context(open(os.devnull, "w", encoding="utf-8"))
                if sys.stdout is None:
                    stack.enter_context(redirect_stdout(sink))
                if sys.stderr is None:
                    stack.enter_context(redirect_stderr(sink))
            return run_cli(argv[2:])

    from exelent.ui.app import run_gui

    return run_gui(argv)


if __name__ == "__main__":
    raise SystemExit(main())
