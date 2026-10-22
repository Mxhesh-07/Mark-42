"""Tier 2 E2/E3 — first-run wizard and signed auto-update."""

from __future__ import annotations

import base64
import json

import pytest

from agent import first_run, updater


# --- E2: first-run helpers ----------------------------------------------------

def test_first_run_is_not_complete_without_the_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(first_run, "FIRST_RUN", tmp_path / "first_run.json")
    monkeypatch.setattr(first_run, "API_KEYS", tmp_path / "api_keys.json")
    assert first_run.is_complete() is False


def test_first_run_completes_only_with_key_and_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(first_run, "FIRST_RUN", tmp_path / "first_run.json")
    monkeypatch.setattr(first_run, "API_KEYS", tmp_path / "api_keys.json")
    monkeypatch.setattr(first_run, "CONFIG_DIR", tmp_path)

    first_run.mark_complete()
    assert first_run.is_complete() is False          # no key yet

    first_run.save_api_key("k" * 40)
    assert first_run.is_complete() is True

    with pytest.raises(ValueError):
        first_run.save_api_key("   ")


def test_first_run_device_choice_matches_by_substring():
    devices = [{"index": 0, "name": "Speakers"}, {"index": 2, "name": "Microphone Array"}]
    assert first_run.choose_device("microphone", devices)["index"] == 2
    assert first_run.choose_device("nope", devices) is None
    assert first_run.choose_device("", devices) is None


# --- E3: updater -------------------------------------------------------------

def _keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return key, public_pem


def _manifest(key, **extra):
    manifest = {"version": "9.9.9", "url": "https://example.invalid/x.zip",
                "sha256": "0" * 64, "notes": "test"}
    manifest.update(extra)
    manifest["signature"] = base64.b64encode(key.sign(updater.canonical(manifest))).decode()
    return manifest


def test_updater_refuses_a_manifest_without_a_signature():
    assert updater.verify_signature({"version": "1.0.0"}) is False


def test_updater_refuses_a_tampered_manifest():
    key, pem = _keypair()
    manifest = _manifest(key)
    manifest["version"] = "1.0.0"
    assert updater.verify_signature(manifest, pem) is False


def test_updater_accepts_a_signed_manifest():
    key, pem = _keypair()
    assert updater.verify_signature(_manifest(key), pem) is True


def test_updater_check_reports_newer_signed_versions(tmp_path, monkeypatch):
    key, pem = _keypair()
    manifest = _manifest(key)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("JARVIS_UPDATE_KEY", pem.decode())

    result = updater.check(f"file://{path}", current="0.1.0")
    assert result["status"] == "ok"
    assert result["newer"] is True

    result = updater.check(f"file://{path}", current="99.0.0")
    assert result["status"] == "ok"
    assert result["newer"] is False


def test_updater_requires_https_for_remote_manifests():
    result = updater.check("http://example.com/manifest.json")
    assert result["status"] in ("error", "refused")
    assert result["status"] != "ok"


def test_updater_refuses_to_apply_from_a_source_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(updater, "UPDATE_DIR", tmp_path)
    (tmp_path / "x.zip").write_bytes(b"x")
    (tmp_path / "state.json").write_text(
        json.dumps({"path": str(tmp_path / "x.zip"), "version": "9.9.9"}),
        encoding="utf-8")
    monkeypatch.setattr(updater.sys, "frozen", False, raising=False)
    result = updater.apply_on_exit()
    assert result["status"] == "refused"
