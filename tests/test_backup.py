"""Tier 2 D4 - backup and restore of runtime state."""

import zipfile

import pytest

from memory import backup


@pytest.fixture
def fake_state(tmp_path, monkeypatch):
    """A fake install directory with some runtime files."""
    monkeypatch.setattr(backup, "BASE_DIR", tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "core").mkdir()
    (tmp_path / "memory" / "long_term.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "memory" / "audit_log.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "config" / "autonomy.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "api_keys.json").write_text('{"gemini_api_key": "secret"}',
                                                       encoding="utf-8")
    return tmp_path


def test_export_writes_the_state_files(fake_state, tmp_path):
    dest = tmp_path / "out.zip"
    manifest = backup.export_backup(dest)
    assert "memory/long_term.json" in manifest["included"]
    with zipfile.ZipFile(dest) as zf:
        assert "memory/long_term.json" in zf.namelist()
        assert backup.MANIFEST_NAME in zf.namelist()


def test_secrets_are_excluded_by_default(fake_state, tmp_path):
    dest = tmp_path / "out.zip"
    manifest = backup.export_backup(dest)
    assert "config/api_keys.json" not in manifest["included"]
    with zipfile.ZipFile(dest) as zf:
        assert "config/api_keys.json" not in zf.namelist()


def test_secrets_can_be_included_on_request(fake_state, tmp_path):
    dest = tmp_path / "out.zip"
    manifest = backup.export_backup(dest, include_secrets=True)
    assert "config/api_keys.json" in manifest["included"]


def test_missing_files_are_reported_not_fatal(fake_state, tmp_path):
    dest = tmp_path / "out.zip"
    manifest = backup.export_backup(dest)
    assert "voice_profiles.json" in manifest["missing"]


def test_read_manifest_round_trips(fake_state, tmp_path):
    dest = tmp_path / "out.zip"
    backup.export_backup(dest)
    manifest = backup.read_manifest(dest)
    assert manifest["version"] == 1
    assert manifest["include_secrets"] is False


def test_restore_puts_the_files_back(fake_state, tmp_path, monkeypatch):
    dest = tmp_path / "out.zip"
    backup.export_backup(dest)

    restore_root = tmp_path / "restore"
    restore_root.mkdir()
    monkeypatch.setattr(backup, "BASE_DIR", restore_root)
    result = backup.restore_backup(dest)

    assert "memory/long_term.json" in result["restored"]
    assert (restore_root / "memory" / "long_term.json").read_text(encoding="utf-8") == '{"a": 1}'


def test_restore_refuses_paths_outside_the_allowlist(fake_state, tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../pwned.txt", "boom")
        zf.writestr("memory/long_term.json", '{"a": 2}')
    result = backup.restore_backup(evil)
    assert "../../pwned.txt" in result["skipped"]
    assert not (tmp_path.parent / "pwned.txt").exists()


def test_info_subcommand_reports_the_manifest(fake_state, tmp_path, capsys):
    dest = tmp_path / "out.zip"
    backup.export_backup(dest)
    assert backup._cli(["info", str(dest)]) == 0
    assert "included" in capsys.readouterr().out
