"""A4 - network egress control."""

from agent import egress, policy
from agent.policy import Level


def test_host_of_handles_urls_hosts_and_ports():
    assert egress.host_of("https://Example.COM/path?q=1") == "example.com"
    assert egress.host_of("example.com:8080") == "example.com"
    assert egress.host_of("user@example.com") == "example.com"
    assert egress.host_of("  ") == ""
    assert egress.host_of(None) == ""


def test_private_targets_are_recognised():
    assert egress.is_private_host("localhost")
    assert egress.is_private_host("127.0.0.1")
    assert egress.is_private_host("192.168.1.10")
    assert egress.is_private_host("10.0.0.5")
    assert egress.is_private_host("169.254.169.254")
    assert egress.is_private_host("something.internal")
    assert not egress.is_private_host("api.github.com")


def test_public_host_is_allowed_by_default(policy_file):
    ok, _ = egress.check("https://api.github.com/repos")
    assert ok


def test_private_host_is_refused_by_default(policy_file):
    ok, why = egress.check("http://localhost:11434/api")
    assert not ok
    assert "SSRF" in why or "private" in why


def test_denylist_wins_over_everything(policy_file, write_policy):
    data = policy.DEFAULT_POLICY | {"egress": {"deny": ["example.com"]}}
    write_policy(data)
    ok, why = egress.check("https://example.com/")
    assert not ok and "denylist" in why


def test_allowlist_restricts_to_listed_hosts(policy_file, write_policy):
    data = policy.DEFAULT_POLICY | {"egress": {"allow": ["github.com"]}}
    write_policy(data)
    assert egress.check("https://api.github.com/")[0]
    assert not egress.check("https://example.com/")[0]


def test_allowlist_can_reach_private_hosts_deliberately(policy_file, write_policy):
    data = policy.DEFAULT_POLICY | {"egress": {"allow": ["localhost"]}}
    write_policy(data)
    assert egress.check("http://localhost:11434/")[0]


def test_disabled_egress_control_allows_private(policy_file, write_policy):
    data = policy.DEFAULT_POLICY | {"egress": {"enabled": False}}
    write_policy(data)
    assert egress.check("http://127.0.0.1/")[0]


def test_destinations_reads_url_keys_emails_and_free_text():
    params = {
        "url": "https://a.example.com/x",
        "to": "someone@b.example.net",
        "note": "see https://c.example.org/page for details",
        "action": "read",
    }
    hosts = {egress.host_of(d) for d in egress.destinations(params)}
    assert hosts == {"a.example.com", "b.example.net", "c.example.org"}


def test_guard_passes_a_call_with_no_destinations(policy_file):
    assert egress.guard("web_search", {"query": "cats"})[0]


def test_gate_blocks_a_private_destination(policy_file):
    decision = policy.evaluate("browser_control", {"action": "go_to", "url": "http://127.0.0.1/admin"})
    assert decision.level is Level.BLOCK
    assert decision.hard


def test_gate_allows_a_public_destination(policy_file):
    assert policy.evaluate("browser_control", {"action": "go_to", "url": "https://example.com"}).level is Level.ALLOW
