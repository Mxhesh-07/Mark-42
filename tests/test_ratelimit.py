"""Per-tool rate limits (A9)."""

import json

from agent import policy, ratelimit
from agent.policy import Level


def _write(write_policy, **rate_limits):
    data = json.loads(json.dumps(policy.DEFAULT_POLICY))
    # `global` is a keyword, so tests pass it as `global_`.
    data["rate_limits"] = {(k[:-1] if k.endswith("_") else k): v
                           for k, v in rate_limits.items()}
    write_policy(data)


def test_burst_allows_then_denies(policy_file, write_policy):
    _write(write_policy,
           default={"per_minute": 60, "burst": 3},
           global_={"per_minute": 600, "burst": 100})
    results = [ratelimit.check("web_search")[0] for _ in range(4)]
    assert results == [True, True, True, False]


def test_the_reason_names_the_tool_and_limit(policy_file, write_policy):
    _write(write_policy,
           default={"per_minute": 60, "burst": 1},
           global_={"per_minute": 600, "burst": 100})
    ratelimit.check("web_search")
    allowed, why = ratelimit.check("web_search")
    assert allowed is False and "rate limit" in why and "web_search" in why


def test_global_budget_denies_across_tools(policy_file, write_policy):
    _write(write_policy,
           default={"per_minute": 600, "burst": 100},
           global_={"per_minute": 600, "burst": 2})
    assert ratelimit.check("a")[0] is True
    assert ratelimit.check("b")[0] is True
    assert ratelimit.check("c")[0] is False


def test_per_tool_override_wins(policy_file, write_policy):
    _write(write_policy,
           default={"per_minute": 600, "burst": 50},
           global_={"per_minute": 6000, "burst": 500},
           tools={"web_search": {"per_minute": 60, "burst": 1}})
    assert ratelimit.check("web_search")[0] is True
    assert ratelimit.check("web_search")[0] is False
    # A different tool still gets the generous default.
    assert ratelimit.check("send_message")[0] is True


def test_reset_clears_the_buckets(policy_file, write_policy):
    _write(write_policy,
           default={"per_minute": 60, "burst": 1},
           global_={"per_minute": 600, "burst": 100})
    assert ratelimit.check("web_search")[0] is True
    assert ratelimit.check("web_search")[0] is False
    ratelimit.reset()
    assert ratelimit.check("web_search")[0] is True


def test_the_gate_enforces_the_limit(policy_file, write_policy):
    _write(write_policy,
           default={"per_minute": 60, "burst": 1},
           global_={"per_minute": 600, "burst": 100})
    assert policy.evaluate("web_search", {}).level is Level.ALLOW
    assert policy.evaluate("web_search", {}).level is Level.BLOCK
