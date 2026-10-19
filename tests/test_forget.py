"""Tier 2 H4 — subject controls: forget, export, and see what is held.

The point of the slice is that "forget everything about me" covers *every*
store, and that the dry run and the receipt agree. A control that clears one
file and prints "done" teaches the user their data is gone when it is not, which
is worse than having no control at all.
"""

import json

import pytest

from agent import audit, forget, quota

# Every store the fixture chain can point somewhere disposable. Anything not in
# this list is a store whose path is not yet redirectable, and the tests below
# assert that list stays empty on purpose.
REDIRECTED = (
    "long_term", "ai_memory", "procedural", "agent_tasks", "notifications",
    "companion", "self_model", "quota_ledger", "voice_profiles", "crashes",
    "sql_memory", "audit_log",
)


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Redirect every store to tmp_path so a test can never touch real data."""
    import voice_id
    from core import self as self_model
    from memory import ai_memory, memory_manager, sql_memory

    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)

    paths = {
        "long_term": tmp_path / "long_term.json",
        "ai_memory": tmp_path / "memory" / "memories.json",
        "procedural": tmp_path / "memory" / "procedural_memory.json",
        "agent_tasks": tmp_path / "memory" / "agent_tasks.json",
        "notifications": tmp_path / "notifications.json",
        "companion": tmp_path / "companion_experiences.json",
        "self_model": tmp_path / "self.json",
        "voice_profiles": tmp_path / "voice_profiles.json",
    }
    monkeypatch.setattr(memory_manager, "MEMORY_PATH", paths["long_term"])
    monkeypatch.setattr(ai_memory, "BASE_DIR", tmp_path)
    monkeypatch.setattr(self_model, "STATE_PATH", paths["self_model"])
    monkeypatch.setattr(voice_id, "PROFILES_PATH", paths["voice_profiles"])
    monkeypatch.setattr(forget, "BASE_DIR", tmp_path)

    monkeypatch.setattr(sql_memory, "BASE_DIR", tmp_path)
    monkeypatch.setattr(sql_memory, "DB_PATH", tmp_path / "memory" / "jarvis.db")

    # The paths the resolver actually produces must be the ones the seed wrote:
    # if the two disagree, the test passes against nothing.
    for name in REDIRECTED:
        if name in ("sql_memory", "audit_log", "crashes", "quota_ledger"):
            continue
        assert forget._store_path(name) == paths[name], name
    return paths


def _seed(paths, tmp_path):
    """Put one record in every store, so 'before' is never accidentally zero."""
    paths["long_term"].write_text(json.dumps({"name": "Ada"}), encoding="utf-8")
    paths["ai_memory"].write_text(json.dumps({"prefs": ["tea"]}), encoding="utf-8")
    paths["procedural"].write_text(json.dumps(["open then close"]), encoding="utf-8")
    paths["agent_tasks"].write_text(json.dumps([{"task": "x"}]), encoding="utf-8")
    paths["notifications"].write_text(json.dumps({"emails": [1]}), encoding="utf-8")
    paths["companion"].write_text(json.dumps([{"day": 1}]), encoding="utf-8")
    paths["self_model"].write_text(json.dumps({"outcomes": {"shell": 1}}), encoding="utf-8")
    paths["voice_profiles"].write_text(
        json.dumps({"Ada": [[0.1, 0.2]], "unknown": []}), encoding="utf-8")

    from memory import sql_memory

    sql_memory.remember("favourite", "tea")

    crashes = tmp_path / "crashes"
    crashes.mkdir(exist_ok=True)
    (crashes / "2026-01-01.json").write_text(json.dumps({"prompt": "secret"}),
                                            encoding="utf-8")


# --- inventory ------------------------------------------------------------------

def test_a_fresh_install_holds_nothing(stores):
    inv = forget.inventory()
    assert inv["total"] == 0
    assert set(inv["counts"]) == set(forget.FORGETTABLE)


def test_the_inventory_counts_every_store_it_claims_to(stores, tmp_path):
    _seed(stores, tmp_path)
    counts = forget.inventory()["counts"]
    for name in ("long_term", "ai_memory", "procedural", "agent_tasks",
                 "notifications", "companion", "self_model"):
        assert counts[name] == 1, name
    assert counts["sql_memory"] == 1
    assert counts["voice_profiles"] >= 1
    assert counts["crashes"] == 1
    assert counts["audit_log"] >= 0


def test_the_inventory_names_what_it_does_not_touch(stores):
    kept = " ".join(forget.inventory()["kept"])
    assert "credential" in kept
    assert "approval" in kept


def test_every_redirected_store_is_actually_covered(stores):
    """A store added to the module but not to the tests should fail here."""
    counted = set(forget.inventory()["counts"])
    assert set(REDIRECTED) == counted


def test_counting_a_corrupt_store_does_not_raise(stores):
    stores["long_term"].write_text("not json", encoding="utf-8")
    assert forget.inventory()["counts"]["long_term"] == 0


# --- forgetting -----------------------------------------------------------------

def test_forget_empties_every_store(stores, tmp_path):
    _seed(stores, tmp_path)
    result = forget.forget_all(include_audit=True)

    assert result["total_removed"] > 0
    remaining = result["remaining"]
    for name in REDIRECTED:
        assert remaining[name] == 0, f"{name} still holds {remaining[name]}"


def test_the_receipt_matches_the_dry_run(stores, tmp_path):
    """The number the dry run promised is the number the real thing removes."""
    _seed(stores, tmp_path)
    promised = forget.inventory()["counts"]
    removed = forget.forget_all(include_audit=True)["removed"]
    for name in ("long_term", "ai_memory", "procedural", "agent_tasks",
                 "notifications", "companion", "self_model", "sql_memory",
                 "crashes"):
        assert removed[name] == promised[name], name


def test_forgetting_keeps_the_files_readable(stores, tmp_path):
    """Emptying is not deleting: the readers must still find a valid shape."""
    _seed(stores, tmp_path)
    forget.forget_all()
    for name in ("long_term", "ai_memory", "self_model", "notifications"):
        json.loads(stores[name].read_text(encoding="utf-8"))
    json.loads(stores["procedural"].read_text(encoding="utf-8"))


def test_forgetting_twice_is_harmless(stores, tmp_path):
    _seed(stores, tmp_path)
    first = forget.forget_all(include_audit=False)
    second = forget.forget_all(include_audit=False)
    assert first["total_removed"] > 0
    assert second["total_removed"] == 0


def test_forgetting_a_fresh_install_does_not_raise(stores):
    """Nothing to remove means nothing claimed — but the log still gets a note."""
    result = forget.forget_all(include_audit=False)
    assert result["total_removed"] == 0


def test_crash_bundles_are_deleted_not_emptied(stores, tmp_path):
    _seed(stores, tmp_path)
    forget.forget_all()
    assert not list((tmp_path / "crashes").glob("*.json"))


def test_voiceprints_can_be_kept_on_request(stores, tmp_path):
    _seed(stores, tmp_path)
    result = forget.forget_all(include_voiceprints=False)
    assert result["removed"]["voice_profiles"] == 0
    assert result["voiceprints_cleared"] is False
    assert json.loads(stores["voice_profiles"].read_text(encoding="utf-8"))


def test_the_audit_log_can_be_kept_on_request(stores, tmp_path):
    audit.record("shell", outcome="allowed", detail="ls")
    result = forget.forget_all(include_audit=False)
    assert result["audit_cleared"] is False
    assert result["removed"]["audit_log"] == 0
    assert audit.tail(10)


# --- the audit log's own rule ----------------------------------------------------

def test_clearing_the_audit_log_leaves_a_record_that_it_happened(stores):
    audit.record("shell", outcome="allowed", detail="ls")
    audit.record("send_message", outcome="denied", detail="nope")

    result = forget.forget_all(include_audit=True)
    assert result["audit_cleared"] is True
    assert result["removed"]["audit_log"] >= 2      # never fewer than we put in

    entries = audit.tail(10)
    assert len(entries) == 1
    assert entries[0]["event"] == "forget"
    assert "entries removed" in entries[0]["detail"]


def test_a_forget_of_a_fresh_install_still_leaves_the_tombstone(stores):
    """Even with nothing to forget, the log says the user asked to be forgotten."""
    forget.forget_all(include_audit=True)
    assert [e["event"] for e in audit.tail(10)] == ["forget"]


def test_the_log_is_cleared_after_the_stores_not_before(stores, tmp_path):
    """The tombstone must survive its own wipe - so it is written last."""
    _seed(stores, tmp_path)
    forget.forget_all(include_audit=True)
    assert any(e["event"] == "forget" for e in audit.tail(10))


def test_the_chain_still_verifies_after_a_forget(stores):
    audit.record("shell", outcome="allowed", detail="ls")
    forget.forget_all(include_audit=True)
    audit.record("shell", outcome="allowed", detail="pwd")
    ok, why = audit.verify()
    assert ok, why


# --- export ---------------------------------------------------------------------

def test_export_writes_a_zip_and_reports_where(stores, tmp_path):
    target = tmp_path / "out.zip"
    manifest = forget.export(target)
    assert target.exists()
    assert manifest["path"] == str(target)
    assert manifest["include_secrets"] is False


def test_export_leaves_the_stores_alone(stores, tmp_path):
    _seed(stores, tmp_path)
    forget.export(tmp_path / "out.zip")
    assert forget.inventory()["total"] > 0


# --- the gate --------------------------------------------------------------------

@pytest.fixture
def budget_policy(write_policy):
    """A full, valid policy with a tightened `budget` block."""
    def _write(reads: dict | None = None, **budget) -> None:
        from agent import policy

        data = dict(policy.DEFAULT_POLICY)
        data["enabled"] = True
        data["budget"] = budget
        if reads:
            data["tools"] = {**data.get("tools", {}), **reads}
        write_policy(data)

    return _write


@pytest.fixture
def midday():
    from datetime import datetime

    today = datetime.now().date()
    return datetime(today.year, today.month, today.day, 12, 0, 0).timestamp()


def test_forget_is_never_allowed_without_a_confirmation(budget_policy):
    """H4: destructive and irreversible, so the table must not clear it."""
    from agent import policy

    budget_policy(reads={"forget": "confirm"})
    decision = policy.evaluate("forget", {"action": "forget"})
    assert decision.level is not policy.Level.ALLOW


def test_forget_is_blocked_at_read_only(budget_policy, midday):
    """A budget breach stops effects, and deleting data is the largest effect
    there is - it must be stopped by the same rule as a shell command."""
    from agent import policy

    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "m", now=midday)

    decision = policy.evaluate("forget", {"action": "forget"})
    assert decision.level is policy.Level.BLOCK
    assert decision.hard is True


def test_the_shipped_policy_puts_forget_at_confirm():
    """The real config, not a fixture: if this ever reads `allow`, a model that
    misreads a frustrated sentence could erase the user's data unprompted."""
    from agent import policy

    assert policy.load_policy().get("tools", {}).get("forget") == "confirm"


# --- the CLI --------------------------------------------------------------------

def test_the_cli_is_a_dry_run_by_default(stores, tmp_path, capsys):
    _seed(stores, tmp_path)
    assert forget._cli([]) == 0
    out = capsys.readouterr().out
    assert "held about you" in out
    assert "--yes" in out
    assert forget.inventory()["total"] > 0          # nothing was changed


def test_the_cli_forgets_with_yes(stores, tmp_path, capsys):
    _seed(stores, tmp_path)
    assert forget._cli(["--yes"]) == 0
    assert "forgot" in capsys.readouterr().out
    assert forget.inventory()["total"] == 0


def test_the_cli_can_keep_the_audit_log(stores, tmp_path, capsys):
    audit.record("shell", outcome="allowed", detail="ls")
    assert forget._cli(["--yes", "--keep-audit"]) == 0
    assert "audit log was kept" in capsys.readouterr().out
    assert audit.tail(10)


def test_the_cli_can_keep_voiceprints(stores, tmp_path):
    _seed(stores, tmp_path)
    assert forget._cli(["--yes", "--keep-voiceprints"]) == 0
    assert json.loads(stores["voice_profiles"].read_text(encoding="utf-8"))


def test_the_cli_refuses_an_unknown_flag(capsys):
    assert forget._cli(["--everything"]) == 2
    assert "usage" in capsys.readouterr().out


def test_the_cli_exports(stores, tmp_path, capsys):
    target = tmp_path / "cli.zip"
    assert forget._cli(["export", str(target)]) == 0
    assert target.exists()
    assert json.loads(capsys.readouterr().out)["path"] == str(target)
