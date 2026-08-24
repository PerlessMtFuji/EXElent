# EXElent

**Status: work in progress.** EXElent is not usable yet — this repository currently
contains only the project skeleton (packaging, pinned tool versions, and CI). Do not
expect a working application at this stage.

## What is this?

EXElent is a Windows tool that turns a folder of Python code into a single `.exe`
file. You point it at a folder, and it produces a program that runs on any Windows
computer — no need to install Python, no need to open a command line.

## Who is this for?

People who have some Python code (perhaps written for them, or written a while ago)
and want to share it with someone else as a normal Windows program, without asking
that person to install anything or type any commands. EXElent itself has a graphical
interface — you never need to use a terminal to use it.

## Running from source

This project is not published yet, so the only way to try it is from source code,
and it requires familiarity with Python tooling.

1. Make sure you have Python 3.12 installed.
2. Get a copy of this repository.
3. Install it in editable mode with its development dependencies:

   ```
   pip install -e .[dev]
   ```

4. Once the command-line entry point exists (it does not yet — see the project
   status above), it will be runnable as:

   ```
   python -m exelent.cli --help
   ```

## License

EXElent is source-available under the [PolyForm Strict License 1.0.0](LICENSE).
You may use it for personal and other noncommercial purposes. You may not
redistribute it, sell it, or publish modified versions.

The EXE files you build with EXElent from your own code are yours to use,
share and sell, see the Additional Permission at the top of [LICENSE](LICENSE).

For any other use, including commercial use, contact the author.
