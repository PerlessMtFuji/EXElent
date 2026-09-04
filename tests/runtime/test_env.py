import subprocess
import sys
from pathlib import Path

import pytest

from exelent.runtime import Progress, env, noop_progress
from exelent.runtime.env import BuildEnvError, create_build_env


def _fake_stream_uv(returncode=0, calls=None, transcript=()):
    """Atrapa `_stream_uv` — oddaje gotowy zapis, bez procesu i bez sieci."""

    def fake(uv, args, on_line, *, cwd=None):
        if calls is not None:
            calls.append(list(args))
        for line in transcript:
            on_line(line)
        return returncode, "\n".join(transcript)

    return fake


def _run_fake_uv(monkeypatch, tmp_path, transcript, returncode=0, fail_venv=False):
    """Atrapa uv oddajaca gotowy zapis. ZADNEGO procesu i zadnej sieci."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(env, "ensure_uv", lambda _p: tmp_path / "uv.exe")

    def fake_run_uv(uv, args, *, cwd=None):
        code = 1 if (fail_venv and args and args[0] == "venv") else 0
        return subprocess.CompletedProcess(list(args), code, "", "\n".join(transcript))

    monkeypatch.setattr(env, "run_uv", fake_run_uv)
    monkeypatch.setattr(env, "_stream_uv", _fake_stream_uv(returncode, transcript=transcript))


def test_builds_expected_uv_command_sequence(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(env, "ensure_uv", lambda _p: tmp_path / "uv.exe")
    calls: list[list[str]] = []

    def fake_run(uv, args, *, cwd=None):
        calls.append(list(args))

        class Result:
            returncode = 0
            stdout = str(tmp_path / "venv" / "Scripts" / "python.exe")
            stderr = ""

        return Result()

    monkeypatch.setattr(env, "run_uv", fake_run)
    monkeypatch.setattr(env, "_stream_uv", _fake_stream_uv(calls=calls))
    result = env.create_build_env(tmp_path / "src", ["requests"], noop_progress)

    assert calls[0][:2] == ["python", "install"]
    assert "3.12" in calls[0]
    assert calls[1][0] == "venv"
    assert calls[2][:2] == ["pip", "install"]
    assert "requests" in calls[2]
    assert result.uv.name == "uv.exe"


def test_pyinstaller_is_always_installed(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(env, "ensure_uv", lambda _p: tmp_path / "uv.exe")
    installed: list[list[str]] = []

    def fake_run(uv, args, *, cwd=None):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(env, "run_uv", fake_run)
    monkeypatch.setattr(env, "_stream_uv", _fake_stream_uv(calls=installed))
    env.create_build_env(tmp_path / "src", [], noop_progress)
    assert any(item.startswith("pyinstaller==") for item in installed[0])


def test_optional_packages_do_not_abort_on_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(env, "ensure_uv", lambda _p: tmp_path / "uv.exe")

    def fake_run(uv, args, *, cwd=None):
        class Result:
            returncode = 1 if "nieistniejaca-paczka" in args else 0
            stdout = ""
            stderr = "No solution found"

        return Result()

    monkeypatch.setattr(env, "run_uv", fake_run)
    # Instalacja hurtowa pada — dopiero wtedy zaczyna sie proba pojedyncza.
    monkeypatch.setattr(env, "_stream_uv", _fake_stream_uv(returncode=1))
    result = env.create_build_env(tmp_path / "src", ["nieistniejaca-paczka"], noop_progress)
    assert "nieistniejaca-paczka" in result.failed_packages


# --- Critical C2: nieudany krok uv nie moze zwrocic zdrowo wygladajacego BuildEnv ---


def _uv_failing_on(match, stderr: str = "error: Failed to install"):
    """Podmiana `run_uv` wywracajaca dokladnie te wywolania, ktore wskaze `match`."""

    def fake_run(uv, args, *, cwd=None):
        broken = match(list(args))

        class Result:
            returncode = 1 if broken else 0
            stdout = ""

        Result.stderr = stderr if broken else ""
        return Result()

    return fake_run


def test_failed_venv_raises_instead_of_returning_a_broken_env(monkeypatch, tmp_path):
    """Bez tego `python.exe` nigdy nie powstaje, a awaria wychodzi cztery ramki
    dalej jako `FileNotFoundError [WinError 2]` z `Popen` w backendzie."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(env, "ensure_uv", lambda _p: tmp_path / "uv.exe")
    monkeypatch.setattr(env, "run_uv", _uv_failing_on(lambda a: a[0] == "venv"))

    with pytest.raises(env.BuildEnvError) as excinfo:
        env.create_build_env(tmp_path / "src", [], noop_progress)

    assert excinfo.value.issue.code == "env_setup_failed"
    assert excinfo.value.issue.data["step"] == "create_env"


def test_the_interpreter_download_is_blamed_when_it_is_the_root_cause(monkeypatch, tmp_path):
    """Gdy padly oba kroki, winny jest ten pierwszy: venv nie mial z czego
    powstac. Wskazanie 'create_env' wyslaloby uzytkownika w zla strone."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(env, "ensure_uv", lambda _p: tmp_path / "uv.exe")
    monkeypatch.setattr(env, "run_uv", _uv_failing_on(lambda a: a[0] in {"venv", "python"}))

    with pytest.raises(env.BuildEnvError) as excinfo:
        env.create_build_env(tmp_path / "src", [], noop_progress)

    assert excinfo.value.issue.data["step"] == "install_python"


def test_failed_interpreter_download_alone_does_not_abort_the_build(monkeypatch, tmp_path):
    """`uv python install` potrafi zwrocic niezero, gdy zgodny Python juz jest
    w systemie. Skoro venv powstal, nie ma czego przerywac."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(env, "ensure_uv", lambda _p: tmp_path / "uv.exe")
    monkeypatch.setattr(env, "run_uv", _uv_failing_on(lambda a: a[:2] == ["python", "install"]))
    monkeypatch.setattr(env, "_stream_uv", _fake_stream_uv())

    result = env.create_build_env(tmp_path / "src", [], noop_progress)
    assert result.python.name == "python.exe"


def test_uv_stderr_is_diagnosed_not_shown_raw(monkeypatch, tmp_path):
    """Przyczyny z sekcji 8 specyfikacji (proxy z podmienionym certyfikatem,
    pelny dysk) siedza w stderr uv. Maja dojsc jako kody, nie jako angielski
    tekst narzedzia."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(env, "ensure_uv", lambda _p: tmp_path / "uv.exe")
    monkeypatch.setattr(
        env,
        "run_uv",
        _uv_failing_on(lambda a: a[0] == "venv", stderr="error: certificate verify failed"),
    )

    with pytest.raises(env.BuildEnvError) as excinfo:
        env.create_build_env(tmp_path / "src", [], noop_progress)

    assert "ssl_proxy" in [i.code for i in excinfo.value.issues]


def test_two_files_in_one_folder_get_separate_environments(monkeypatch, tmp_path):
    """Kazdy plik w Pobranych dostaje wlasny venv.

    `work_dir_for` bez `single_file` daje obu plikom ten sam katalog, wiec
    build drugiego kasuje srodowisko pierwszego — a uzytkownik widzi tylko
    to, ze program, ktory dopiero co dzialal, przestal sie budowac.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(env, "ensure_uv", lambda _p: tmp_path / "uv.exe")

    def fake_run(uv, args, *, cwd=None):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(env, "run_uv", fake_run)
    monkeypatch.setattr(env, "_stream_uv", _fake_stream_uv())
    downloads = tmp_path / "Pobrane"
    a = env.create_build_env(downloads, [], noop_progress, single_file=downloads / "a.py")
    b = env.create_build_env(downloads, [], noop_progress, single_file=downloads / "b.py")
    assert a.venv != b.venv


# --- Zadanie 11: instalacja paczek liczy bajty na zywo ---


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


def test_stream_uv_hands_over_lines_while_running_and_keeps_the_whole_text(tmp_path):
    """Jedyny test dotykajacy prawdziwego procesu.

    Pozostale podmieniaja `_stream_uv` w calosci, wiec bez tego sam strumien
    — a wiec cale zadanie — nie bylby sprawdzony nigdy.
    """
    script = (
        "import sys\n"
        "for i in range(3):\n"
        "    print(f'linia {i}', file=sys.stderr, flush=True)\n"
        "sys.exit(7)\n"
    )
    seen: list[str] = []

    code, text = env._stream_uv(Path(sys.executable), ["-c", script], seen.append)

    assert code == 7
    assert [line.strip() for line in seen] == ["linia 0", "linia 1", "linia 2"]
    assert text == "linia 0\nlinia 1\nlinia 2"
