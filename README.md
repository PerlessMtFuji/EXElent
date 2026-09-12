# EXElent

**Turn a folder of Python code into a Windows program you can hand to anyone.**

You point EXElent at a folder. It reads the code, works out how to start it,
and produces a Windows application. By default, the result is a folder:
share the **whole folder**, including its libraries and data. The recipient
double-clicks the `.exe` inside — they do not install Python or open a terminal,
they do not have to know what any of this is.

![EXElent](docs/screenshot.png)

*The interface follows your Windows language: Polish and English are both
built in.*

## Who this is for

You have some Python code — maybe you wrote it, maybe someone wrote it for
you, maybe it has been sitting on your disk for years — and you want to give
it to a person who will not install anything. That is the whole problem
EXElent solves.

You do not need to use a command line to use EXElent. It has a window.

Code kept in `.txt` files works too. That is common when the code was sent
over email or chat, and EXElent handles it without you renaming anything.

## Download and run

1. Go to the [releases page](https://github.com/exelent-app/exelent/releases/latest).
2. Download `EXElent.exe`.
3. Double-click it. There is nothing to install.

### Windows and antivirus warnings

EXElent is unsigned. If Windows or your antivirus warns about a download,
check where the file came from and what the alert says before running it.
EXElent cannot establish that an alert is a false positive or that the input
program is safe. Packaging succeeds independently of that assessment.

## What EXElent does to your folder

Nothing. It copies your code somewhere else and works on the copy, so the
folder you point it at is exactly as you left it — no new files, no `build`
or `dist` directories, nothing moved. The finished `.exe` is placed in a new
folder next to your project, or on your Desktop.

The build copies the plan's file inventory and checks content hashes. A changed
or missing inventoried file blocks the build; analyze again after editing.
Later builds use a free output name, keeping the previous application and its data.

## Output, data and supported input

The recommended **folder (ONEDIR)** mode keeps relative reads and writes next
to the executable. Run it from a location where you have write permission.
**Single file (ONEFILE)** is an explicit choice: relative writes also use the
EXE directory, but bundled resources are extracted elsewhere. Programs that
read bundled data through relative paths should use folder mode. Code that
explicitly writes into an extraction directory can still lose those files.

EXElent accepts Python scripts, `.pyw`, ordinary packages (including
`__main__.py` and supported `src/` layouts), and Python code in TXT, including
UTF-16. Correct Python is preserved before attempting text cleanup.
Review ambiguous text conversions, the entry point and detected dependencies.
Static analysis cannot discover every computed import, plugin or runtime path;
manual module selection may be needed. Resource discovery uses recognized
extensions, including images, JSON, TOML and HTML; arbitrary custom formats
and resource selection still need further work.

A successful build means **the application was packaged**, with any warnings
still relevant. EXElent checks syntax with the target Python before packaging;
it does not automatically run your program to verify its behavior. Test the
result yourself before sharing it.

## Network and cache

Builds target Windows with Python 3.12. EXElent downloads uv, a managed Python
and required packages. Subsequent builds can reuse downloaded files, although
they create isolated build environments. The current preflight still requires
access to PyPI; a fully offline build is not yet supported or guaranteed.

## Building it yourself

You only need this if you want to change EXElent or do not want to download a
binary. It requires Python and a command line.

```
pip install -e .[dev] pyinstaller==6.16.0
python build_exelent.py
```

The result is `dist/EXElent.exe`. To run the program from source without
packaging it:

```
python -m exelent
```

There is also a command-line entry point for the build logic alone, without
the window — it is a developer tool and speaks in error codes, not sentences:

```
python -m exelent.cli <folder>
```

The packaged application exposes the same adapter. Since it is a windowed
executable, use a report file to receive the result (including warnings):

```powershell
$job = Start-Process .\EXElent.exe -ArgumentList '--cli "C:\My project" --report "C:\result.json"' -Wait -PassThru
$job.ExitCode
```

The report parent directory must already exist. `artifact` identifies what to
share, and `executable_path` identifies the program to run.

To run the tests:

```
pytest -m "not slow"
```

The tests marked `slow` build real `.exe` files and take minutes.

```powershell
pytest tests/test_golden_builds.py tests/test_local_resolver.py -m slow -v
$env:EXELENT_TEST_EXE = (Resolve-Path dist/EXElent.exe).Path
pytest tests/test_product_smoke.py -m slow -v --basetemp=build/product-smoke
```

The product smoke test uses fresh EXElent state, uv cache and managed Python
directories, rejects invalid code through the frozen validator, then builds
and runs a Python 3.12 program twice. Cache locations follow the
[uv environment-variable contract](https://docs.astral.sh/uv/reference/environment/).
This verifies controlled fixtures; it does not replace manual GUI review.

## When something goes wrong

If a build fails, EXElent shows you what it thinks went wrong and offers two
buttons: one saves a report file, the other opens a prefilled bug report on
GitHub. Using that button is the most useful thing you can do, because the
report carries the log.

You can also open an issue by hand at
[github.com/exelent-app/exelent](https://github.com/exelent-app/exelent/issues).

## License

MIT — see [LICENSE](LICENSE). Do what you like with it.
