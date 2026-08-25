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
