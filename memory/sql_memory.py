"""SQLite-backed memory (Tier 2 D1-D3).

The memory store used to be a handful of JSON files rewritten in place. This
module is the transactional replacement: one SQLite database, a versioned
schema (D2), and per-record provenance with confidence and TTL (D3).

Only the standard library is used (``sqlite3``), so the module imports on any
platform and in CI. Callers that still need the old dict shape get it from
``as_dict()``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
DB_PATH = BASE_DIR / "memory" / "jarvis.db"

# Bump this and add a block in _migrate() for every schema change.
SCHEMA_VERSION = 1


def _connect():
    import sqlite3 as _sqlite3

    (BASE_DIR / "memory").mkdir(parents=True, exist_ok=True)
    conn = _sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level="DEFERRED")
    conn.row_factory = _sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    _migrate(conn)
    return conn


def _migrate(conn) -> None:
    """Forward-only, numbered migrations (D2)."""
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    row = cur.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    version = row["v"] if row and row["v"] is not None else 0

    if version < 1:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'fact',
                source TEXT,
                confidence REAL DEFAULT 0.5,
                created_at REAL NOT NULL,
                last_used REAL,
                expires_at REAL,
                tags TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind)")
        cur.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (1)")

    conn.commit()


def schema_version() -> int:
    conn = _connect()
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return int(row["v"] or 0)
    finally:
        conn.close()


# --- memory records (D3: provenance) ------------------------------------------

DEFAULT_CONFIDENCE = 0.5
DEFAULT_TTL_S = 0.0  # 0 = never expires


def _now() -> float:
    return time.time()


def remember(
    key: str,
    value,
    *,
    kind: str = "fact",
    source: str = "assistant",
    confidence: float = DEFAULT_CONFIDENCE,
    ttl_s: float = DEFAULT_TTL_S,
    tags=None,
    path=None,
) -> int:
    """Insert or update a memory, with provenance.

    Re-stating a fact raises its confidence slightly and refreshes last_used,
    which is how repeated evidence outranks a single mention.
    """
    import json

    key = str(key).strip()
    if not key:
        raise ValueError("a memory needs a key")
    value_text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    now = _now()
    expires = now + float(ttl_s) if ttl_s else None
    tags_text = json.dumps([str(t) for t in tags], ensure_ascii=False) if tags else None

    conn = path or _connect()
    try:
        existing = conn.execute("SELECT confidence FROM memories WHERE key = ?", (key,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO memories (key, value, kind, source, confidence, created_at,"
                " last_used, expires_at, tags) VALUES (?,?,?,?,?,?,?,?,?)",
                (key, value_text, kind, source, float(confidence), now, now, expires, tags_text),
            )
        else:
            boosted = min(1.0, max(float(existing["confidence"] or 0.0), float(confidence)) + 0.05)
            conn.execute(
                "UPDATE memories SET value=?, kind=?, source=?, confidence=?, last_used=?,"
                " expires_at=?, tags=? WHERE key=?",
                (value_text, kind, source, boosted, now, expires, tags_text, key),
            )
        conn.commit()
        row = conn.execute("SELECT id FROM memories WHERE key = ?", (key,)).fetchone()
        return int(row["id"])
    finally:
        if path is None:
            conn.close()


def recall(key: str, *, path=None):
    conn = path or _connect()
    try:
        row = conn.execute(
            "SELECT * FROM memories WHERE key = ? AND (expires_at IS NULL OR expires_at > ?)",
            (str(key), _now()),
        ).fetchone()
        return dict(row) if row else None
    finally:
        if path is None:
            conn.close()


def all_records(*, path=None, limit: int = 0):
    conn = path or _connect()
    try:
        sql = ("SELECT * FROM memories WHERE expires_at IS NULL OR expires_at > ?"
               " ORDER BY last_used DESC")
        rows = conn.execute(sql, (_now(),)).fetchall()
        out = [dict(r) for r in rows]
        return out[:limit] if limit else out
    finally:
        if path is None:
            conn.close()


def search(text: str, *, path=None, limit: int = 20):
    """Substring search over keys, values and tags."""
    like = f"%{str(text).lower()}%"
    conn = path or _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM memories WHERE (expires_at IS NULL OR expires_at > ?) AND ("
            " lower(key) LIKE ? OR lower(value) LIKE ? OR lower(COALESCE(tags,'')) LIKE ?)"
            " ORDER BY confidence DESC, last_used DESC LIMIT ?",
            (_now(), like, like, like, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if path is None:
            conn.close()


def forget(key: str, *, path=None) -> bool:
    conn = path or _connect()
    try:
        cur = conn.execute("DELETE FROM memories WHERE key = ?", (str(key),))
        conn.commit()
        return cur.rowcount > 0
    finally:
        if path is None:
            conn.close()


def forget_all(*, path=None) -> int:
    """Subject control: forget everything (D5 / H4)."""
    conn = path or _connect()
    try:
        cur = conn.execute("DELETE FROM memories")
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        if path is None:
            conn.close()


def prune(*, path=None) -> int:
    """Drop expired and low-confidence stale records (D5)."""
    conn = path or _connect()
    try:
        cur = conn.execute(
            "DELETE FROM memories WHERE (expires_at IS NOT NULL AND expires_at <= ?)"
            " OR (confidence < 0.2)",
            (_now(),),
        )
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        if path is None:
            conn.close()


def as_dict(*, path=None) -> dict:
    """The legacy shape: key -> value."""
    import json

    out = {}
    for rec in all_records(path=path):
        value = rec.get("value")
        try:
            out[rec["key"]] = json.loads(value)
        except Exception:
            out[rec["key"]] = value
    return out


def stats(*, path=None) -> dict:
    conn = path or _connect()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]
        live = conn.execute(
            "SELECT COUNT(*) AS c FROM memories WHERE expires_at IS NULL OR expires_at > ?",
            (_now(),),
        ).fetchone()["c"]
        return {"version": schema_version(), "total": int(total), "live": int(live)}
    finally:
        if path is None:
            conn.close()
