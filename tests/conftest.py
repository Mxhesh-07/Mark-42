"""Shared fixtures.

The tests cover the pure, cross-platform logic (agent/, memory helpers and the
voice_id helpers). Nothing here may import torch, playwright or a Windows-only
package, so the suite runs unchanged on Linux in CI.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Never touch real kill-switch, audit or approval state, and never leak
    rate-limit/breaker/role/metrics state between tests."""
    from agent import (approval, approval_rules, audit, breaker, crash, degrade,
                       devices, initiative, judgement, metrics, policy, ratelimit,
                       roles, trace)
    from core import self as self_model
    from memory import sql_memory

    monkeypatch.setattr(policy, "KILL_FILE", tmp_path / "AUTONOMY_OFF")
    monkeypatch.setattr(approval_rules, "RULES_PATH", tmp_path / "approval_rules.json")
    monkeypatch.setattr(devices, "CONFIG_PATH", tmp_path / "devices.json")
    monkeypatch.setattr(audit, "LOG_PATH", tmp_path / "audit_log.jsonl")
    monkeypatch.setattr(approval, "KEY_PATH", tmp_path / "approval.key")
    monkeypatch.setattr(approval, "USED_PATH", tmp_path / "approval_used.json")
    monkeypatch.setattr(crash, "CRASH_DIR", tmp_path / "crashes")
    monkeypatch.setattr(judgement, "CONFIG_PATH", tmp_path / "judgement.json")
    monkeypatch.setattr(initiative, "POLICY_PATH", tmp_path / "autonomy.json")
    monkeypatch.setattr(self_model, "STATE_PATH", tmp_path / "self.json")
    monkeypatch.setattr(sql_memory, "BASE_DIR", tmp_path)
    monkeypatch.setattr(sql_memory, "DB_PATH", tmp_path / "jarvis.db")
    audit._LAST_HASH = ""
    approval.reset_for_tests()
    approval_rules.reset_for_tests()
    devices.reset_for_tests()
    policy._killed.clear()
    roles.clear()
    ratelimit.reset()
    breaker.reset()
    metrics.reset()
    trace.reset()
    degrade.reset()
    judgement.reset_session()
    initiative.reset()
    self_model.reset_for_tests()
    yield
    audit._LAST_HASH = ""
    approval.reset_for_tests()
    approval_rules.reset_for_tests()
    devices.reset_for_tests()
    policy._killed.clear()
    roles.clear()
    ratelimit.reset()
    breaker.reset()
    metrics.reset()
    trace.reset()
    degrade.reset()
    judgement.reset_session()
    initiative.reset()
    self_model.reset_for_tests()


@pytest.fixture
def policy_file(tmp_path, monkeypatch):
    """Point agent.policy at a throwaway autonomy.json and reset its cache."""
    from agent import policy

    path = tmp_path / "autonomy.json"
    path.write_text(json.dumps(policy.DEFAULT_POLICY), encoding="utf-8")
    monkeypatch.setattr(policy, "POLICY_PATH", path)
    policy._cache = None
    policy._cache_mtime = -1.0
    yield path
    policy._cache = None
    policy._cache_mtime = -1.0


@pytest.fixture
def write_policy(policy_file):
    """Rewrite the throwaway policy file and drop the cache."""

    def _write(data: dict) -> None:
        from agent import policy
        policy_file.write_text(json.dumps(data), encoding="utf-8")
        policy._cache = None
        policy._cache_mtime = -1.0

    return _write


@pytest.fixture
def judgement_file(tmp_path, monkeypatch):
    """Point agent.judgement at a throwaway judgement.json."""
    from agent import judgement

    path = tmp_path / "judgement.json"
    path.write_text(json.dumps(judgement.DEFAULT_CONFIG), encoding="utf-8")
    monkeypatch.setattr(judgement, "CONFIG_PATH", path)
    yield path
