"""Path sandboxing for the tools that touch the filesystem (upgrade list A2).

``file_controller`` accepts arbitrary paths, so a prompt injection arriving from
a web page, an email or OCR text could point it anywhere on disk. This module
answers one question - "is this path inside an allowed root?" - and denies
anything else by default.

Roots live in ``config/autonomy.json``::

    "sandbox": { "enabled": true, "roots": ["~", "D:/work"] }

The check resolves symlinks and ``..`` *before* comparing, so neither can be
used to climb out of a root. The allowlist is read from config only - never from
the model - and edits take effect without a restart.
"""

from pathlib import Path

# Parameter names that may carry a filesystem path.
_PATH_KEYS = frozenset({
    "path", "file", "file_path", "filepath", "filename", "source", "src",
    "destination", "dest", "dst", "directory", "folder", "dir",
})

_DEFAULT = {"enabled": True, "roots": ["~"]}


def _cfg() -> dict:
    try:
        from agent import policy
        pol = policy.load_policy()
    except Exception:
        pol = {}
    cfg = pol.get("sandbox") if isinstance(pol, dict) else None
    out = dict(_DEFAULT)
    if isinstance(cfg, dict):
        out.update(cfg)
    return out


def enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def roots() -> list[Path]:
    out: list[Path] = []
    for r in _cfg().get("roots") or _DEFAULT["roots"]:
        try:
            out.append(Path(str(r)).expanduser().resolve())
        except Exception:
            continue
    return out


def check(path) -> tuple[bool, str]:
    """Return ``(allowed, reason)``. Denies by default."""
    if not enabled():
        return True, "sandbox disabled"
    if path is None or not str(path).strip():
        return False, "empty path"
    try:
        target = Path(str(path)).expanduser().resolve()
    except Exception as exc:  # pragma: no cover - platform specific
        return False, f"path could not be resolved ({exc})"
    for root in roots():
        if target == root or root in target.parents:
            return True, f"inside {root}"
    return False, "outside the allowed roots: " + ", ".join(str(r) for r in roots())


def paths_in(params) -> list[str]:
    """Every value in ``params`` whose key looks like a filesystem path."""
    if not isinstance(params, dict):
        return []
    return [v for k, v in params.items()
            if isinstance(k, str) and k.lower() in _PATH_KEYS
            and isinstance(v, str) and v.strip()]
