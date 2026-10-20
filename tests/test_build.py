"""Tier 2 E1 — the packaging build: version, plan, spec, manifest, verify.

The build itself needs PyInstaller and a Windows host, so the tests aim at the
part that must be right *before* a tag is pushed: the version every artefact
agrees on, the data list, and the rule that a release never carries the user's
credentials. `verify()` is then tested against synthetic bundles, including the
one that has a credential in it — the only way to know the check works is to
feed it the failure it exists to catch.
"""

import json
from pathlib import Path

import pytest

from agent import build, version as version_mod


@pytest.fixture
def fake_tree(tmp_path, monkeypatch):
    """A source tree with a config/ the stager can copy."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "autonomy.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "api_keys.example.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "api_keys.json").write_text('{"gemini":"SECRET"}',
                                                       encoding="utf-8")
    (tmp_path / "config" / "devices.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "audio.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "__pycache__").mkdir()
    for name in ("core", "prompts"):
        (tmp_path / name).mkdir()
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    (tmp_path / "main.py").write_text("", encoding="utf-8")

    monkeypatch.setattr(version_mod, "BASE_DIR", tmp_path)
    monkeypatch.setattr(build, "base_dir", lambda: tmp_path)
    return tmp_path


def _make_bundle(root: Path, *, version=None, credential=False) -> Path:
    """A synthetic onedir bundle, shaped like the real one."""
    bundle = root / "dist" / build.BUNDLE_NAME
    bundle.mkdir(parents=True)
    (bundle / build.executable_name()).write_bytes(b"MZ")
    (bundle / "main.py").write_text("# frozen\n", encoding="utf-8")
    config = bundle / "config"
    config.mkdir()
    (config / "autonomy.json").write_text("{}", encoding="utf-8")
    if credential:
        (config / "api_keys.json").write_text('{"gemini":"SECRET"}', encoding="utf-8")
    for name in ("core", "prompts"):
        (bundle / name).mkdir()
    doc = {
        "manifest_version": 1,
        "name": build.BUNDLE_NAME,
        "version": version or version_mod.version(),
    }
    (bundle / build.MANIFEST_NAME).write_text(json.dumps(doc), encoding="utf-8")
    return bundle


# --- version ---------------------------------------------------------------------

def test_the_version_comes_from_pyproject():
    """One source of truth, and it is the file every other tool reads."""
    text = (version_mod.BASE_DIR / "pyproject.toml").read_text(encoding="utf-8")
    assert "version" in text
    assert version_mod.version() == version_mod._from_pyproject(version_mod.PYPROJECT)


def test_the_version_looks_like_a_version():
    parts = version_mod.version().split(".")
    assert len(parts) >= 2
    assert all(p.isdigit() for p in parts[:2])


def test_the_release_name_is_the_tag():
    assert version_mod.release_name() == f"v{version_mod.version()}"


def test_a_missing_pyproject_falls_back_instead_of_raising(tmp_path):
    assert version_mod._from_pyproject(tmp_path / "nope.toml") is None
    assert version_mod.VERSION


def test_format_versions_are_reported_separately_from_the_release():
    """A schema bump is not a release, and conflating them loses migrations."""
    snapshot = version_mod.snapshot()
    assert snapshot["version"] == version_mod.version()
    assert snapshot["formats"]["sql_memory"] == 1
    assert snapshot["formats"]["quota"] == 1


def test_the_snapshot_carries_what_a_bug_report_needs():
    snapshot = version_mod.snapshot()
    for key in ("version", "release", "git", "python", "frozen", "formats"):
        assert key in snapshot


def test_the_cli_prints_the_version(capsys):
    assert version_mod._cli(["--version"]) == 0
    assert capsys.readouterr().out.strip() == version_mod.version()


def test_the_cli_prints_the_release(capsys):
    assert version_mod._cli(["--release"]) == 0
    assert capsys.readouterr().out.strip() == version_mod.release_name()


# --- plan ------------------------------------------------------------------------

def test_the_plan_is_onedir(fake_tree):
    p = build.plan(fake_tree / "dist")
    assert p["bundle"].endswith(build.BUNDLE_NAME)
    assert p["name"] == build.BUNDLE_NAME
    assert p["executable"].endswith(build.executable_name())


def test_the_plan_lists_the_data_the_app_opens_by_path(fake_tree):
    p = build.plan(fake_tree / "dist")
    assert "config/" in p["datas"]
    assert "core/" in p["datas"]
    assert "prompts/" in p["datas"]


def test_the_plan_reports_what_is_missing_rather_than_guessing(fake_tree):
    (fake_tree / "core").rmdir()
    p = build.plan(fake_tree / "dist")
    assert "core/" in p["missing"]
    assert "core/" not in p["datas"]


def test_the_plan_names_the_files_that_must_never_ship(fake_tree):
    never = build.plan(fake_tree / "dist")["never_bundled"]
    assert "config/api_keys.json" in never
    assert "voice_profiles.json" in never
    assert "memory" in never


def test_the_plan_carries_the_version(fake_tree):
    p = build.plan(fake_tree / "dist")
    assert p["version"] == version_mod.version()
    assert p["release"] == version_mod.release_name()


# --- staging: the rule that matters most ------------------------------------------

def test_staging_keeps_the_credentials_out(fake_tree):
    target, skipped = build.stage_config(fake_tree / "dist")
    names = {p.name for p in target.iterdir()}
    assert "api_keys.json" not in names
    assert "devices.json" not in names
    assert "audio.json" not in names
    assert "api_keys.json" in skipped


def test_staging_keeps_the_example_templates(fake_tree):
    """The templates are how a user learns what to write."""
    target, _ = build.stage_config(fake_tree / "dist")
    names = {p.name for p in target.iterdir()}
    assert "api_keys.example.json" in names


def test_staging_keeps_the_tracked_config(fake_tree):
    target, _ = build.stage_config(fake_tree / "dist")
    names = {p.name for p in target.iterdir()}
    assert "autonomy.json" in names


def test_staging_drops_pycache(fake_tree):
    target, _ = build.stage_config(fake_tree / "dist")
    assert not (target / "__pycache__").exists()


def test_staging_does_not_modify_the_source_config(fake_tree):
    build.stage_config(fake_tree / "dist")
    assert (fake_tree / "config" / "api_keys.json").exists()


def test_staging_twice_does_not_duplicate(fake_tree):
    build.stage_config(fake_tree / "dist")
    target, _ = build.stage_config(fake_tree / "dist")
    assert len(list(target.iterdir())) == len(
        [p for p in (fake_tree / "config").iterdir() if p.is_file()
         and p.name not in build.CONFIG_STATE])


# --- the spec --------------------------------------------------------------------

def test_the_spec_collects_config_from_the_stage_not_the_source(fake_tree):
    """Pointing PyInstaller at the source config/ would publish the keys."""
    text = build.spec_text(fake_tree / "dist")
    stage = str(build.stage_dir(fake_tree / "dist")).replace("\\", "/")
    assert stage in text
    assert "('config/', 'config')" not in text


def test_the_spec_is_a_onedir_build(fake_tree):
    text = build.spec_text(fake_tree / "dist")
    assert "COLLECT(" in text
    assert "exclude_binaries=True" in text


def test_the_spec_excludes_the_heavy_unused_packages(fake_tree):
    text = build.spec_text(fake_tree / "dist")
    for name in ("matplotlib", "pandas", "IPython"):
        assert name in text


def test_the_spec_mentions_every_staged_data_directory(fake_tree):
    text = build.spec_text(fake_tree / "dist")
    for name in ("core", "prompts", "requirements.txt"):
        assert name in text


# --- manifest --------------------------------------------------------------------

def test_the_manifest_identifies_the_build(tmp_path):
    bundle = _make_bundle(tmp_path)
    doc = build.manifest(bundle)
    assert doc["manifest_version"] == 1
    assert doc["version"] == version_mod.version()
    assert doc["release"] == version_mod.release_name()
    assert doc["name"] == build.BUNDLE_NAME


def test_the_manifest_lists_files_with_hashes(tmp_path):
    bundle = _make_bundle(tmp_path)
    files = build.manifest(bundle)["files"]
    paths = {f["path"] for f in files}
    assert "main.py" in paths
    entry = next(f for f in files if f["path"] == "main.py")
    assert len(entry["sha256"]) == 64
    # Compared against the file itself, not a literal: `Path.write_text` translates
    # newlines on Windows, so the on-disk size is a property of the file, not of
    # the string that was handed to it.
    assert entry["size"] == (bundle / "main.py").stat().st_size


def test_the_manifest_uses_forward_slashes(tmp_path):
    """A manifest is read on another machine, so the separators are not local."""
    bundle = _make_bundle(tmp_path)
    (bundle / "sub").mkdir()
    (bundle / "sub" / "x.txt").write_text("x", encoding="utf-8")
    for entry in build.manifest(bundle)["files"]:
        assert "\\" not in entry["path"]


def test_the_manifest_can_skip_the_file_list(tmp_path):
    bundle = _make_bundle(tmp_path)
    assert "files" not in build.manifest(bundle, files=False)


def test_the_manifest_respects_the_file_cap(tmp_path):
    bundle = _make_bundle(tmp_path)
    assert len(build.manifest(bundle)["files"]) >= 1
    assert len(build.file_entries(bundle, limit=1)) == 1


def test_write_manifest_puts_it_in_the_bundle(tmp_path):
    bundle = _make_bundle(tmp_path)
    target = build.write_manifest(bundle)
    assert target == bundle / build.MANIFEST_NAME
    assert json.loads(target.read_text(encoding="utf-8"))["name"] == build.BUNDLE_NAME


# --- verify ----------------------------------------------------------------------

def test_a_well_formed_bundle_verifies(tmp_path):
    bundle = _make_bundle(tmp_path)
    ok, problems = build.verify(bundle)
    assert ok, problems


def test_a_missing_bundle_is_reported(tmp_path):
    ok, problems = build.verify(tmp_path / "nope")
    assert ok is False
    assert problems


def test_a_missing_executable_is_caught(tmp_path):
    bundle = _make_bundle(tmp_path)
    (bundle / build.executable_name()).unlink()
    ok, problems = build.verify(bundle)
    assert ok is False
    assert any("executable" in p for p in problems)


def test_a_missing_data_directory_is_caught(tmp_path):
    """The quiet failure: the app starts and cannot find its own prompt."""
    bundle = _make_bundle(tmp_path)
    for child in (bundle / "core").iterdir():
        child.unlink()
    (bundle / "core").rmdir()
    ok, problems = build.verify(bundle)
    assert ok is False
    assert any("core" in p for p in problems)


def test_a_shipped_credential_is_caught(tmp_path):
    """The check that exists because staging could regress."""
    bundle = _make_bundle(tmp_path, credential=True)
    ok, problems = build.verify(bundle)
    assert ok is False
    assert any("api_keys.json" in p for p in problems)


def test_a_version_mismatch_is_caught(tmp_path):
    bundle = _make_bundle(tmp_path, version="9.9.9")
    ok, problems = build.verify(bundle)
    assert ok is False
    assert any("9.9.9" in p for p in problems)


def test_a_missing_manifest_is_caught(tmp_path):
    bundle = _make_bundle(tmp_path)
    (bundle / build.MANIFEST_NAME).unlink()
    ok, problems = build.verify(bundle)
    assert ok is False
    assert any(build.MANIFEST_NAME in p for p in problems)


def test_a_corrupt_manifest_is_caught(tmp_path):
    bundle = _make_bundle(tmp_path)
    (bundle / build.MANIFEST_NAME).write_text("{not json", encoding="utf-8")
    ok, problems = build.verify(bundle)
    assert ok is False
    assert any("JSON" in p for p in problems)


def test_verifying_a_source_tree_is_flagged(tmp_path):
    """Pointing --verify at the repo would otherwise pass for the wrong reason."""
    tree = tmp_path / "src"
    tree.mkdir()
    (tree / "config").mkdir()
    for name in ("core", "prompts"):
        (tree / name).mkdir()
    (tree / build.executable_name()).write_bytes(b"MZ")
    (tree / build.MANIFEST_NAME).write_text(
        json.dumps({"name": build.BUNDLE_NAME, "version": version_mod.version()}),
        encoding="utf-8")
    ok, problems = build.verify(tree)
    assert ok is False
    assert any("source tree" in p for p in problems)


# --- the build entry point --------------------------------------------------------

def test_build_writes_the_spec_even_without_pyinstaller(fake_tree):
    """The plan and the spec are useful on a laptop; only the freeze needs CI."""
    result = build.build(fake_tree / "dist", spec=True)
    assert result["ok"] is True
    assert Path(result["spec"]).is_file()


def test_build_refuses_cleanly_without_pyinstaller(fake_tree, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _no_pyinstaller(name, *args, **kwargs):
        if name == "PyInstaller":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pyinstaller)
    result = build.build(fake_tree / "dist")
    assert result["ok"] is False
    assert "PyInstaller" in result["reason"]
    assert "plan" in result


# --- the CLI ----------------------------------------------------------------------

def test_the_cli_prints_a_plan(fake_tree, capsys, monkeypatch):
    monkeypatch.setattr(build, "plan", lambda *a, **k: {"version": "0.0.1"})
    assert build._cli(["--plan"]) == 0
    assert "0.0.1" in capsys.readouterr().out


def test_the_cli_verifies_and_reports_problems(tmp_path, capsys):
    bundle = _make_bundle(tmp_path, credential=True)
    assert build._cli(["--verify", str(bundle)]) == 1
    out = capsys.readouterr().out
    assert "problem" in out
    assert "api_keys.json" in out


def test_the_cli_verifies_a_good_bundle(tmp_path, capsys):
    bundle = _make_bundle(tmp_path)
    assert build._cli(["--verify", str(bundle)]) == 0
    assert "ok" in capsys.readouterr().out


def test_the_cli_needs_a_path_to_verify(capsys):
    assert build._cli(["--verify"]) == 2
    assert "usage" in capsys.readouterr().out


def test_the_cli_rejects_a_stray_flag(capsys):
    assert build._cli(["--everything"]) == 2
    assert "usage" in capsys.readouterr().out
