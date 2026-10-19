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
    """Never touch the real kill-switch file or leak rate-limit state."""
    from agent import policy, ratelimit

    monkeypatch.setattr(policy, "KILL_FILE", tmp_path / "AUTONOMY_OFF")
    policy._killed.clear()
    ratelimit.reset()
    yield
    policy._killed.clear()
    ratelimit.reset()


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
