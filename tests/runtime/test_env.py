import pytest

from exelent.runtime import env, noop_progress


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
    installed: list[str] = []

    def fake_run(uv, args, *, cwd=None):
        if args[:2] == ["pip", "install"]:
            installed.extend(args[2:])

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(env, "run_uv", fake_run)
    env.create_build_env(tmp_path / "src", [], noop_progress)
    assert any(item.startswith("pyinstaller==") for item in installed)


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
