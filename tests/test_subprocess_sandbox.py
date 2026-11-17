"""A11 - restricted subprocess execution."""

import os
import subprocess
import sys

import pytest

from agent import subprocess_sandbox


def test_credential_looking_names_are_detected():
    assert subprocess_sandbox.is_secret_name("GEMINI_API_KEY")
    assert subprocess_sandbox.is_secret_name("MY_TOKEN")
    assert subprocess_sandbox.is_secret_name("DB_PASSWORD")
    assert not subprocess_sandbox.is_secret_name("PATH")
    assert not subprocess_sandbox.is_secret_name("USERNAME")


def test_restricted_env_drops_secrets_and_keeps_the_essentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "supersecret")
    monkeypatch.setenv("SOME_TOKEN", "abc")
    env = subprocess_sandbox.restricted_env()
    assert "GEMINI_API_KEY" not in env
    assert "SOME_TOKEN" not in env
    assert env.get("JARVIS_SANDBOX") == "1"
    if "PATH" in os.environ:
        assert "PATH" in env


def test_restricted_env_can_be_extended(monkeypatch):
    env = subprocess_sandbox.restricted_env({"EXTRA": "1"})
    assert env["EXTRA"] == "1"


def test_a_child_cannot_read_a_stripped_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    script = tmp_path / "child.py"
    script.write_text(
        "import os\n"
        "print(os.environ.get('GEMINI_API_KEY', 'MISSING'))\n",
        encoding="utf-8",
    )
    result = subprocess_sandbox.run_python_file(script, timeout=60)
    assert result.returncode == 0
    assert "super-secret-value" not in result.stdout
    assert "MISSING" in result.stdout


def test_a_child_runs_in_a_scratch_directory(tmp_path):
    script = tmp_path / "child.py"
    script.write_text("import os\nprint(os.getcwd())\n", encoding="utf-8")
    result = subprocess_sandbox.run_python_file(script, timeout=60)
    assert result.returncode == 0
    assert os.path.dirname(str(script)) not in result.stdout


def test_a_failing_child_reports_its_exit_code(tmp_path):
    script = tmp_path / "child.py"
    script.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    result = subprocess_sandbox.run_python_file(script, timeout=60)
    assert result.returncode == 3


def test_a_runaway_child_is_killed(tmp_path):
    script = tmp_path / "child.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess_sandbox.run_python_file(script, timeout=2)


def test_status_reports_the_containment():
    status = subprocess_sandbox.status()
    assert status["restricted_env"] is True
    assert status["scratch_cwd"] is True
    assert isinstance(status["job_objects"], bool)


def test_python_is_the_interpreter_used(tmp_path):
    script = tmp_path / "child.py"
    script.write_text("import sys\nprint(sys.executable)\n", encoding="utf-8")
    result = subprocess_sandbox.run_python_file(script, timeout=60)
    assert os.path.basename(sys.executable) in result.stdout


# --- run_argv / spawn_argv: the same containment for shell commands ----------

def test_run_argv_captures_output_and_exit_code():
    result = subprocess_sandbox.run_argv(
        [sys.executable, "-c", "import sys; print('ok'); sys.exit(3)"], timeout=60
    )
    assert result.stdout.strip() == "ok"
    assert result.returncode == 3


def test_run_argv_strips_credentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    result = subprocess_sandbox.run_argv(
        [sys.executable, "-c",
         "import os; print(os.environ.get('GEMINI_API_KEY', 'MISSING'))"],
        timeout=60,
    )
    assert result.stdout.strip() == "MISSING"
    assert "super-secret-value" not in result.stdout


def test_run_argv_runs_in_the_given_directory(tmp_path):
    target = tmp_path / "here.txt"
    target.write_text("x", encoding="utf-8")
    result = subprocess_sandbox.run_argv(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        cwd=tmp_path, timeout=60,
    )
    assert os.path.samefile(result.stdout.strip(), tmp_path)


def test_run_argv_timeout_kills_the_child():
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess_sandbox.run_argv(
            [sys.executable, "-c", "import time; time.sleep(30)"], timeout=2
        )


def test_run_argv_refuses_an_empty_command():
    with pytest.raises(ValueError):
        subprocess_sandbox.run_argv([])


def test_spawn_argv_starts_a_process_with_the_restricted_env(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "super-secret-value")
    child = subprocess_sandbox.spawn_argv(
        [sys.executable, "-c",
         "import os,sys; sys.exit(0 if 'DB_PASSWORD' not in os.environ else 9)"]
    )
    assert child.wait(timeout=60) == 0
