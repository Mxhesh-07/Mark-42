"""Atomic file writes (upgrade list D6).

State files are written to a temporary file in the same directory and then
os.replace()d into place. os.replace is atomic on the same filesystem on both
Windows and POSIX, so a crash, a full disk, or a killed process can never leave
a half-written JSON file behind - either the old contents or the new contents
are visible, never a truncated mix.
"""

import json
import os
import tempfile
from pathlib import Path


def write_text(path, text: str, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` atomically (temp file + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, data, *, indent: int = 2, encoding: str = "utf-8") -> None:
    write_text(path, json.dumps(data, indent=indent, ensure_ascii=False), encoding=encoding)
