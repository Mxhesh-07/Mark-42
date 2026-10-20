# 0019 — The build describes itself, and the release is checked

Date: 2026-10-20

Status: accepted

## Context

The project had no version. The health endpoint hard-coded `JarvisHealth/1.0`,
each subsystem kept a private `VERSION = 1` for its own file format, and a
release had no name. That is survivable while there is one user, and it stops
working the moment anyone has to answer "which build is this?" — which is the
first question in every crash report and every update check.

Packaging was a `setup.py` that pip-installed the requirements and a `spec` file
that did not exist. There was nothing that could produce a bundle, and nothing
that could check one.

The pressure that shaped the design is that PyInstaller is a heavy,
platform-specific dependency which is not installed on the development machine
and cannot be. A build script that can only be exercised by running the build is
a script that is first executed when a tag has already been pushed, which is the
worst possible time to find out a path is wrong.

## Decision

**The version lives in one place, and it is `pyproject.toml`.**
`agent/version.py` reads `[project] version` (via `tomllib` on 3.11+, or a
one-line regex on 3.10) and falls back to a constant only if the file is
unreadable. The *format* version of each subsystem's on-disk file stays separate
and private: a schema bump is not a release, and conflating them is how a
migration becomes unwritable. `snapshot()` reports both, so a bug report carries
all of it at once.

**The build is split so that only the freeze needs PyInstaller.** `plan()` says
what the bundle will be called, what goes in it and what is missing. `spec_text()`
renders the spec from `plan()`, so the data list and the excludes cannot drift
from the part under test. `build()` is the only function that imports PyInstaller,
and it refuses cleanly when it is absent rather than half-writing a bundle.
`--plan` and `--spec` work on a machine with no PyInstaller at all.

**The spec is generated, not hand-kept.** A hand-written spec is a second copy of
the file list that nothing checks; it goes stale silently and the bundle ships
without `core/`, which means the app starts and cannot find its own prompt.

**`config/` is staged before it is collected.** PyInstaller collects a directory
wholesale, so pointing it at `config/` would publish `api_keys.json` in the
release — the exact mistake this project has rules about everywhere else.
`stage_config()` copies `config/` into a staging directory minus the credentials
and runtime state, keeping the `*.example.json` templates, because the templates
are how a user is told what to write.

**`verify()` is the check that exists to fail.** It takes a finished bundle and
reports the executable missing, a data directory missing, a manifest that does
not match the source version, or a credential in the bundle. The credential check
is run against the bundle rather than against the staging directory that fed it:
"the release does not contain a key" is then a property of a directory rather
than a promise about a script.

The release workflow builds on a tag, verifies, greps the bundle for credential
filenames as a second independent check, writes the manifest, packages a zip, and
refuses to publish if the tag does not match `pyproject.toml`.

## Consequences

- One version, and every artefact agrees on it: the manifest, the zip name, the
  health endpoint's report, and the tag. A mismatch fails the release.
- `agent/build.py` is covered by tests that never import PyInstaller: 45 of them
  cover the version, the plan, staging, the spec, the manifest and `verify()` —
  including a bundle with a credential planted in it, because the only way to
  know a check works is to feed it the failure it exists to catch.
- `DATA_DIRS` names only directories that are actually in the repository. Naming
  an `assets/` nobody created made `verify()` fail a correct build, and a check
  that cries wolf is a check people learn to ignore. (This was caught by the
  tests, not by reading the code.)
- The spec is not committed. It embeds the absolute staging path, so it is
  machine-specific by construction; `*.spec`, `dist/` and `build/` are ignored.
- Real artefacts, code signing (E4) and the installer (E2) remain out of reach
  from a development machine and are tracked as such.
