"""Tier 2 D1-D3 - SQLite memory store."""

import pytest

from memory import sql_memory


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A throwaway database for each test."""
    monkeypatch.setattr(sql_memory, "BASE_DIR", tmp_path)
    monkeypatch.setattr(sql_memory, "DB_PATH", tmp_path / "jarvis.db")
    return sql_memory


def test_schema_is_created_and_versioned(store):
    assert store.schema_version() == store.SCHEMA_VERSION


def test_remember_and_recall(store):
    store.remember("user.name", "Mahesh", source="user", confidence=0.9)
    rec = store.recall("user.name")
    assert rec["value"] == "Mahesh"
    assert rec["source"] == "user"
    assert rec["confidence"] == pytest.approx(0.9)


def test_restating_raises_confidence(store):
    store.remember("user.city", "Pune", confidence=0.5)
    store.remember("user.city", "Pune", confidence=0.5)
    assert store.recall("user.city")["confidence"] > 0.5


def test_an_empty_key_is_rejected(store):
    with pytest.raises(ValueError):
        store.remember("   ", "x")


def test_values_may_be_structured(store):
    store.remember("prefs", {"theme": "dark", "volume": 0.5})
    assert store.recall("prefs")["value"].startswith("{")


def test_an_expired_record_is_not_recalled(store):
    store.remember("temp", "x", ttl_s=0.01)
    import time

    time.sleep(0.05)
    assert store.recall("temp") is None


def test_search_matches_keys_values_and_tags(store):
    store.remember("user.city", "Pune", tags=["profile"])
    store.remember("user.job", "engineer")
    assert {r["key"] for r in store.search("pune")} == {"user.city"}
    assert {r["key"] for r in store.search("profile")} == {"user.city"}
    assert {r["key"] for r in store.search("engineer")} == {"user.job"}


def test_forget_removes_a_record(store):
    store.remember("gone", "1")
    assert store.forget("gone") is True
    assert store.recall("gone") is None


def test_forget_all_is_the_subject_control(store):
    store.remember("a", "1")
    store.remember("b", "2")
    assert store.forget_all() == 2
    assert store.all_records() == []


def test_prune_drops_expired_records(store):
    store.remember("temp", "x", ttl_s=0.01)
    store.remember("keep", "y")
    import time

    time.sleep(0.05)
    assert store.prune() == 1
    assert {r["key"] for r in store.all_records()} == {"keep"}


def test_as_dict_returns_the_legacy_shape(store):
    store.remember("user.name", "Mahesh")
    store.remember("prefs", {"theme": "dark"})
    legacy = store.as_dict()
    assert legacy["user.name"] == "Mahesh"
    assert legacy["prefs"] == {"theme": "dark"}


def test_stats_reports_the_shape(store):
    store.remember("a", "1")
    s = store.stats()
    assert s["total"] == 1 and s["live"] == 1


def test_migrations_are_idempotent(store):
    store.remember("a", "1")
    # Opening again must not re-run migration 1 or lose data.
    assert store.schema_version() == store.SCHEMA_VERSION
    assert store.recall("a") is not None
