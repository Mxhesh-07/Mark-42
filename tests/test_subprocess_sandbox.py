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
