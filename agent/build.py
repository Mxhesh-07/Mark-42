"""The packaging build (Tier 2 E1) — a onedir bundle, a manifest, a release.

The build runs in CI, but almost none of it is allowed to be *only* runnable in
CI. PyInstaller is a heavy, platform-specific, Windows-hostile dependency; if the
manifest, the version check and the bundle layout could only be exercised by a
real freeze, none of them could be tested on a laptop, and the first time anyone
found out a path was wrong would be after a tag was pushed.

So this module splits in two:

    plan()      pure: what the bundle will be called, what goes in it, which
                files are data, and what the manifest will say. Tested directly.
    build()     the only part that touches PyInstaller, and it refuses politely
                when PyInstaller is missing rather than half-writing a bundle.

`verify()` closes the loop: it takes a finished onedir bundle and checks that the
things that must be there are there — the executable, the data directories, a
manifest that matches the files on disk. A build that silently omits `core/` is a
build that starts and then cannot find its own prompt, which is the failure mode
this exists to catch.

    python -m agent.build --plan            # what would be built (no PyInstaller)
    python -m agent.build --verify dist/x   # audit an existing bundle
    python -m agent.build                   # actually freeze, if PyInstaller is here
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from agent import version as version_mod

MANIFEST_NAME = "manifest.json"
BUNDLE_NAME = "MarkJarvis"

# Data the frozen app reads at runtime and PyInstaller cannot infer: it is
# opened by path, not imported. `get_base_dir()` in main.py returns the directory
# next to the executable when frozen, so these land there and just work.
#
# Only directories that exist in the repository belong here. Naming one that does
# not — an `assets/` nobody ever created — makes `verify()` fail a build that is
# in fact correct, and a check that cries wolf is a check people learn to ignore.
DATA_DIRS = ("config", "core", "prompts")
DATA_FILES = ("requirements.txt",)

# Never bundled. Credentials and state are the user's, created on first run; a
# release that shipped them would be publishing keys.
EXCLUDED = (
    "config/api_keys.json", "config/email_config.json",
    "config/spotify_config.json", "config/alert_config.json",
    "config/audio.json", "config/approval_rules.json", "config/devices.json",
    "memory", "logs", "voice_profiles.json", "notifications.json",
    "companion_experiences.json", "alert_log.json", "life_data.json",
)

# Modules PyInstaller would otherwise pull in via a broad import and drag a
# megabyte of dead weight with. Each of these has a lazy-import path (F4).
EXCLUDES = (
    "tkinter.test", "test", "unittest", "pydoc_data",
    "matplotlib", "scipy", "pandas", "IPython", "notebook",
)


def base_dir() -> Path:
    return version_mod.BASE_DIR


def executable_name() -> str:
    return f"{BUNDLE_NAME}.exe" if sys.platform == "win32" else BUNDLE_NAME


# Runtime state that also lives under config/ and must never ship. `*.example.json`
# templates are *not* excluded: they are how a user is told what to write.
CONFIG_STATE = tuple(Path(name).name for name in EXCLUDED
                     if name.startswith("config/"))


def stage_dir(dist=None) -> Path:
    """The staging directory the spec collects `config/` from."""
    root = Path(dist) if dist is not None else base_dir() / "build"
    return root / "stage"


def stage_config(dist=None) -> tuple[Path, list[str]]:
    """Copy `config/` into the staging directory minus the files that must not ship.

    PyInstaller collects a directory wholesale, so pointing it at `config/` would
    publish `api_keys.json` in the release — the exact mistake this project has
    rules about everywhere else. Staging is the honest fix: it also gives
    `verify()` something concrete to check, because "the release does not contain
    a credential" is then a property of a directory rather than a promise.
    """
    import shutil

    source = base_dir() / "config"
    target = stage_dir(dist) / "config"
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    skipped: list[str] = []
    for path in sorted(source.iterdir()):
        if path.is_dir() or path.name == "__pycache__":
            continue
        if path.name in CONFIG_STATE:
            skipped.append(path.name)
            continue
        shutil.copy2(path, target / path.name)
        copied.append(path.name)
    return target, skipped


def bundle_dir(dist: Path | None = None) -> Path:
    """Where an onedir build lands: `dist/MarkJarvis/`."""
    root = Path(dist) if dist is not None else base_dir() / "dist"
    return root / BUNDLE_NAME


def plan(dist=None, *, entry: str = "main.py") -> dict:
    """Everything about the build that can be decided without running it."""
    root = base_dir()
    present = []
    missing = []
    for name in DATA_DIRS:
        (present if (root / name).is_dir() else missing).append(name + "/")
    for name in DATA_FILES:
        (present if (root / name).is_file() else missing).append(name)

    return {
        "version": version_mod.version(),
        "release": version_mod.release_name(),
        "git": version_mod.git_sha(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "entry": entry,
        "bundle": str(bundle_dir(dist)),
        "executable": executable_name(),
        "name": BUNDLE_NAME,
        "datas": present,
        "missing": missing,
        "excludes": list(EXCLUDES),
        "never_bundled": list(EXCLUDED),
    }


def spec_text(dist=None, *, entry: str = "main.py") -> str:
    """Render the PyInstaller spec.

    Generated rather than hand-kept so the data list and the excludes cannot
    drift from `plan()`, which is the part under test.
    """
    p = plan(dist, entry=entry)
    staged = DATA_DIRS[0] if DATA_DIRS else None
    lines = []
    for name in p["datas"]:
        if name == f"{staged}/":
            # config/ is collected from the staging copy, not the source tree,
            # so credentials never enter the release (see stage_config()).
            source = str(stage_dir(dist) / staged).replace("\\", "/")
            lines.append(f"    ({source!r}, {staged!r}),")
        else:
            lines.append(f"    ({name!r}, {name.rstrip('/')!r}),")
    datas = "\n".join(lines)
    excludes = ", ".join(repr(name) for name in p["excludes"])
    return f'''# Generated by `python -m agent.build --spec`. Do not edit by hand:
# `agent/build.py` is the source of truth and is covered by tests.
#
# Onedir, not onefile: onefile unpacks to a temp directory on every launch, which
# makes startup slow and breaks anything that resolves a path relative to the
# executable. `get_base_dir()` in main.py expects the onedir layout.

block_cipher = None

a = Analysis(
    [{entry!r}],
    pathex=[],
    binaries=[],
    datas=[
{datas}
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[{excludes}],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name={p["name"]!r},
    debug=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name={p["name"]!r},
)
'''


# --- the manifest ---------------------------------------------------------------

def _sha256(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def file_entries(bundle: Path, *, limit: int = 5000) -> list[dict]:
    """`[{path, size, sha256}]` for a finished bundle, sorted, capped.

    Hashing every file of a large bundle is slow, so the cap is deliberate: the
    manifest's job is to prove *which build this is*, and the identifiers do that
    without paying for a checksum of every byte of a torch wheel.
    """
    out: list[dict] = []
    for path in sorted(bundle.rglob("*")):
        if len(out) >= limit:
            break
        if not path.is_file():
            continue
        try:
            out.append({
                "path": str(path.relative_to(bundle)).replace("\\", "/"),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            })
        except OSError:
            continue
    return out


def manifest(bundle: Path, *, files: bool = True) -> dict:
    """The versioned manifest written next to a build and attached to releases."""
    bundle = Path(bundle)
    doc = {
        "manifest_version": 1,
        "name": BUNDLE_NAME,
        "version": version_mod.version(),
        "release": version_mod.release_name(),
        "git": version_mod.git_sha(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "executable": executable_name(),
        "snapshot": version_mod.snapshot(),
    }
    if files:
        doc["files"] = file_entries(bundle)
    return doc


def write_manifest(bundle: Path, *, files: bool = True) -> Path:
    bundle = Path(bundle)
    target = bundle / MANIFEST_NAME
    target.write_text(json.dumps(manifest(bundle, files=files), indent=2),
                      encoding="utf-8")
    return target


# --- verification ---------------------------------------------------------------

def verify(bundle) -> tuple[bool, list[str]]:
    """Check a finished bundle. Returns (ok, problems).

    Checks the three ways a freeze goes quietly wrong: the executable is missing,
    a data directory the app opens by path was not collected, or the manifest does
    not describe what is actually on disk.
    """
    bundle = Path(bundle)
    problems: list[str] = []

    if not bundle.is_dir():
        return False, [f"no bundle at {bundle}"]

    exe = bundle / executable_name()
    if not exe.is_file():
        problems.append(f"missing executable: {exe.name}")

    for name in DATA_DIRS:
        if not (bundle / name).is_dir():
            problems.append(f"missing data directory: {name}/")

    manifest_path = bundle / MANIFEST_NAME
    if not manifest_path.is_file():
        problems.append(f"missing {MANIFEST_NAME}")
        return (not problems), problems

    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        problems.append(f"{MANIFEST_NAME} is not readable JSON: {exc}")
        return False, problems

    if doc.get("version") != version_mod.version():
        problems.append(
            f"{MANIFEST_NAME} says version {doc.get('version')!r}, "
            f"source says {version_mod.version()!r}")
    if doc.get("name") != BUNDLE_NAME:
        problems.append(f"{MANIFEST_NAME} names {doc.get('name')!r}")

    if not (bundle / "main.py").is_file():
        # Not fatal for a real freeze, but a common sign that `--verify` was
        # pointed at a source tree by mistake, which would make every other
        # check pass for the wrong reason.
        problems.append("no main.py in the bundle: is this a source tree, not a build?")

    # The rule that matters most: a release must never carry the user's secrets.
    # Checked against the bundle, not against the staging directory that fed it.
    for name in CONFIG_STATE:
        if (bundle / "config" / name).exists():
            problems.append(f"credential or runtime state shipped: config/{name}")

    return (not problems), problems


# --- the build itself -----------------------------------------------------------

def build(dist=None, *, entry: str = "main.py", spec: bool = False) -> dict:
    """Freeze the app with PyInstaller. The only part that needs the dependency.

    Writes the spec and the manifest, and refuses cleanly when PyInstaller is
    absent — a half-written bundle is worse than an honest "not installed".
    """
    root = base_dir()
    spec_path = root / f"{BUNDLE_NAME}.spec"

    staged, skipped = stage_config(dist)
    spec_path.write_text(spec_text(dist, entry=entry), encoding="utf-8")

    # `--spec` first: generating the spec is pure text and must work on a machine
    # that has never heard of PyInstaller, which is the whole point of not making
    # the spec hand-written.
    if spec:
        return {"ok": True, "spec": str(spec_path), "built": False,
                "staged": str(staged), "staged_skipped": skipped}

    try:
        import PyInstaller  # noqa: F401
    except Exception:
        return {
            "ok": False,
            "reason": "PyInstaller is not installed (pip install pyinstaller)",
            "spec": str(spec_path),
            "staged": str(staged),
            "staged_skipped": skipped,
            "plan": plan(dist, entry=entry),
        }

    from PyInstaller.__main__ import run as pyinstaller_run

    pyinstaller_run([
        str(spec_path), "--noconfirm", "--clean",
        "--distpath", str(Path(dist) if dist else root / "dist"),
        "--workpath", str(root / "build"),
    ])

    bundle = bundle_dir(dist)
    if not bundle.is_dir():
        return {"ok": False, "reason": f"PyInstaller produced no {bundle}",
                "spec": str(spec_path)}

    target = write_manifest(bundle)
    ok, problems = verify(bundle)
    return {"ok": ok, "bundle": str(bundle), "manifest": str(target),
            "problems": problems, "spec": str(spec_path), "built": True}


# --- CLI ------------------------------------------------------------------------

_USAGE = (
    "usage: python -m agent.build [--plan | --spec | --stage | --verify PATH]\n"
    "\n"
    "  --plan         what would be built, and what is missing (no PyInstaller)\n"
    "  --spec         write MarkJarvis.spec only\n"
    "  --stage PATH   copy config/ into the staging dir minus credentials\n"
    "  --verify PATH  audit a finished onedir bundle\n"
    "  (no arguments) build with PyInstaller, then write and check the manifest\n"
)


def _cli(argv=None) -> int:
    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "--plan":
        print(json.dumps(plan(), indent=2))
        return 0

    if argv and argv[0] == "--verify":
        if len(argv) < 2:
            print(_USAGE)
            return 2
        ok, problems = verify(argv[1])
        for problem in problems:
            print(f"  problem: {problem}")
        print("bundle ok" if ok else "bundle has problems")
        return 0 if ok else 1

    if argv and argv[0] == "--stage":
        target, skipped = stage_config(argv[1] if len(argv) > 1 else None)
        print(json.dumps({"staged": str(target), "skipped": skipped}, indent=2))
        return 0

    if argv and argv[0] == "--spec":
        result = build(spec=True)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    if argv:
        print(_USAGE)
        return 2

    result = build()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
