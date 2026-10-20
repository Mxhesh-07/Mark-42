"""One version for the whole project (Tier 2 E1).

Before this module the version lived nowhere: the health endpoint hard-coded
`JarvisHealth/1.0`, each subsystem had its own private `VERSION = 1` for its own
on-disk format, and a release had no name. That is fine until you have to answer
"which build is this?" — which is exactly the question an issue report, a crash
bundle and an update check all start with.

`pyproject.toml` → `[project] version` is the source of truth, because that is
where every Python tool looks first. This module reads it without a TOML parser
fallback chain: Python 3.11+ has `tomllib`, and for 3.10 the version is picked up
from a one-line regex, which is a smaller dependency than `tomli` for a single
string.

The *format* version of each subsystem's on-disk file stays separate and stays
private to that subsystem — a schema bump is not a release, and conflating the
two is how you end up unable to write a migration. `snapshot()` reports them
together so a bug report can carry all of it at once.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

VERSION = "0.1.0"          # fallback only; pyproject.toml wins when readable


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
PYPROJECT = BASE_DIR / "pyproject.toml"


def _from_pyproject(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    if sys.version_info >= (3, 11):
        try:
            import tomllib

            data = tomllib.loads(text)
            found = data.get("project", {}).get("version")
            if isinstance(found, str) and found:
                return found
        except Exception:
            pass

    # Fallback for 3.10 and for a pyproject we failed to parse: the `[project]`
    # table is small and the version is a bare quoted string.
    match = re.search(
        r"^\s*version\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
    return match.group(1) if match else None


def version() -> str:
    """The release version, from pyproject.toml, else `VERSION`."""
    found = _from_pyproject(PYPROJECT)
    return found or VERSION


def git_sha(*, short: bool = True) -> str | None:
    """The commit this build came from, when the build is from a checkout.

    Fails quietly: an installed build has no git, and that is not an error.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short" if short else "HEAD", "HEAD"],
            cwd=str(BASE_DIR), capture_output=True, text=True, timeout=5,
            check=False,
        )
    except Exception:
        return None
    sha = (out.stdout or "").strip()
    return sha or None


def release_name() -> str:
    """`v0.1.0` — the tag a release is published under."""
    return f"v{version()}"


# Subsystem on-disk formats. Reported, never conflated with the release version.
_FORMAT_MODULES = (
    ("audit", "agent.audit"),
    ("quota", "agent.quota"),
    ("forget", "agent.forget"),
    ("sql_memory", "memory.sql_memory"),
    ("backup", "memory.backup"),
)


def formats() -> dict:
    """`{subsystem: file-format version}` for each store that has one.

    Only subsystems with a real on-disk format constant are listed. Audit entries
    and backup manifests carry their version inside the record itself, so there is
    nothing to read here and they are reported as `None` rather than invented.
    """
    out: dict = {}
    for name, module in _FORMAT_MODULES:
        try:
            mod = __import__(module, fromlist=["_"])
        except Exception:
            out[name] = None
            continue
        found = None
        for attr in ("VERSION", "SCHEMA_VERSION", "FORMAT_VERSION"):
            value = getattr(mod, attr, None)
            if isinstance(value, int):
                found = value
                break
        out[name] = found
    return out


def snapshot() -> dict:
    """Everything a bug report needs to identify the build."""
    return {
        "version": version(),
        "release": release_name(),
        "git": git_sha(),
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "formats": formats(),
    }


def _cli(argv=None) -> int:
    import json

    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--version":
        print(version())
        return 0
    if argv and argv[0] == "--release":
        print(release_name())
        return 0
    print(json.dumps(snapshot(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
