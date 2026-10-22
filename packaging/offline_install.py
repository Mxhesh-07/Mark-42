"""Tier 2 E6 — offline install path.

Two steps, both using only pip:

    python packaging/offline_install.py download [--dest vendor/wheels]
    python packaging/offline_install.py install  [--dest vendor/wheels]

`download` runs on a machine that has internet and produces a wheelhouse; copy
the repo (including the wheelhouse) to the offline machine and run `install`.
Because the wheelhouse is a directory of wheels, the offline machine needs no
network and no compiler — as long as it runs the same Python version and OS
family as the machine that downloaded.

This is deliberately a script rather than a separate requirements file: the
only thing that differs between online and offline is the pip flags, and having
one file means they cannot drift.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REQUIREMENTS = BASE_DIR / "requirements.txt"
DEFAULT_DEST = BASE_DIR / "vendor" / "wheels"


def download(dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "pip", "download",
        "-r", str(REQUIREMENTS),
        "--dest", str(dest),
        "--only-binary=:all:",
    ]
    print("[offline] " + " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("[offline] download failed. If a package has no wheel for this "
              "Python/OS, drop --only-binary=:all: (that package then needs a "
              "build toolchain on the download machine).", file=sys.stderr)
    return result.returncode


def install(dest: Path) -> int:
    if not dest.exists() or not any(dest.glob("*")):
        print(f"[offline] no wheels at {dest}; run 'download' first", file=sys.stderr)
        return 2
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--no-index",
        "--find-links", str(dest),
        "-r", str(REQUIREMENTS),
    ]
    print("[offline] " + " ".join(cmd))
    return subprocess.run(cmd).returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="offline install for MARK-42")
    parser.add_argument("action", choices=("download", "install"))
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args(argv)
    if args.action == "download":
        return download(args.dest)
    return install(args.dest)


if __name__ == "__main__":
    raise SystemExit(main())
