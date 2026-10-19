"""Sandboxed subprocess execution (A11).

`generated_code` / `code_helper` / `dev_agent` run model-written Python. Running
that child with the assistant's own environment means a bad generation can read
every API key the machine holds and write anywhere the user can. This module
runs such code with three cheap, real constraints:

* **No secrets in the environment.** Variables whose names look like credentials
  (``*KEY*``, ``*TOKEN*``, ``*SECRET*``, ``*PASSWORD*``, ``*CREDENTIAL*``, …) are
  removed before the child starts, so `os.environ["GEMINI_API_KEY"]` is empty.
* **A scratch working directory.** Relative paths land in a fresh temp folder
  rather than the user's home.
* **Resource limits (Windows).** The child is placed in a Job Object with a
  process-memory cap and kill-on-close, so a runaway allocation fails instead of
  taking the machine down, and closing the job kills any grandchildren.

This is containment, not a security boundary — the child still runs as the user.
It is the layer that keeps a *mistake* contained; the permission gate (ADR 0001)
is what keeps a hostile instruction from getting here at all.
"""

import os
import subprocess
import sys
import tempfile

# Substrings that mark a variable as a credential.
_SECRET_MARKERS = (
    "KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL",
    "AUTH", "SESSION", "COOKIE", "PRIVATE", "SIGNATURE",
)

DEFAULT_TIMEOUT_S = 120
DEFAULT_MEMORY_MB = 1024


def is_secret_name(name: str) -> bool:
    """True when an environment variable name looks like a credential."""
    upper = str(name or "").upper()
    return any(marker in upper for marker in _SECRET_MARKERS)


def restricted_env(extra: dict | None = None) -> dict:
    """The child's environment: everything except credential-looking variables."""
    env = {name: value for name, value in os.environ.items() if not is_secret_name(name)}
    env["JARVIS_SANDBOX"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONSTARTUP", None)
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def strips_env(names) -> bool:  # pragma: no cover - clarity helper for callers
    return all(is_secret_name(n) for n in names)


# --- Windows Job Objects ------------------------------------------------------

_JOB_OBJECT_LIMIT_ACTIVE_PROCESS    = 0x00000008
_JOB_OBJECT_LIMIT_PROCESS_MEMORY    = 0x00000100
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JobObjectExtendedLimitInformation  = 9


def _create_job(memory_mb: int | None, max_processes: int | None):
    """Create a Job Object with limits, or None when unsupported."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IOCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimits),
                ("IoInfo", _IOCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        info = _ExtendedLimits()
        flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if memory_mb:
            flags |= _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            info.ProcessMemoryLimit = int(memory_mb) * 1024 * 1024
        if max_processes:
            flags |= _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info.BasicLimitInformation.ActiveProcessLimit = int(max_processes)
        info.BasicLimitInformation.LimitFlags = flags
        ok = kernel32.SetInformationJobObject(
            handle, _JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(handle)
            return None
        return handle
    except Exception:
        return None


def _assign_to_job(job, process) -> bool:
    try:
        import ctypes

        handle = int(getattr(process, "_handle", 0) or 0)
        if not handle:
            return False
        return bool(ctypes.windll.kernel32.AssignProcessToJobObject(job, handle))
    except Exception:
        return False


def _close_job(job) -> None:
    try:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(job)
    except Exception:
        pass


# --- running ------------------------------------------------------------------

def run_python_file(
    path,
    *,
    timeout: int = DEFAULT_TIMEOUT_S,
    cwd=None,
    memory_mb: int | None = DEFAULT_MEMORY_MB,
    max_processes: int = 8,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run a Python file in a restricted child. Raises on timeout."""
    workdir = str(cwd) if cwd else tempfile.mkdtemp(prefix="jarvis-sandbox-")
    job = _create_job(memory_mb, max_processes)
    process = subprocess.Popen(
        [sys.executable, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(workdir),
        env=restricted_env(extra_env),
    )
    if job:
        _assign_to_job(job, process)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.communicate(timeout=10)
        except Exception:
            pass
        if job:
            _close_job(job)
        raise
    finally:
        if job:
            _close_job(job)
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def status() -> dict:
    return {
        "restricted_env": True,
        "secret_markers": list(_SECRET_MARKERS),
        "job_objects": os.name == "nt",
        "default_timeout_s": DEFAULT_TIMEOUT_S,
        "default_memory_mb": DEFAULT_MEMORY_MB,
        "scratch_cwd": True,
    }
