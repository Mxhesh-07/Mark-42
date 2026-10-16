"""
Procedural memory — remember HOW a goal was accomplished, not just facts.

The rest of the memory package stores declarative facts ("the user's name is
Mahesh"). This module stores *procedures*: the sequence of tool actions that
actually succeeded for a given kind of goal. When a similar goal comes back,
the executor can start from the proven trajectory instead of planning from
scratch — which is both faster and more reliable.

Storage: memory/procedural_memory.json (gitignored runtime data).

Matching is deliberately dependency-free (stdlib only) and based on token
overlap, so it works offline and needs no embeddings.
"""

import json
import re
import sys
import threading
import time
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR   = get_base_dir()
STORE_PATH = BASE_DIR / "memory" / "procedural_memory.json"

MAX_ENTRIES           = 200   # keep the store bounded
SIMILARITY_THRESHOLD  = 0.72  # how alike two goals must be to reuse a plan
MIN_TOKENS            = 2     # ignore goals that are too short to match safely

_STOPWORDS = {
    "a", "an", "the", "and", "or", "to", "of", "for", "in", "on", "at", "with",
    "my", "me", "i", "you", "your", "please", "then", "that", "this", "it",
    "is", "are", "be", "do", "does", "can", "could", "would", "should", "will",
    "from", "into", "onto", "about", "as", "by", "up", "out", "using", "use",
}

_lock = threading.Lock()


# --- goal normalisation -------------------------------------------------------

def _tokenize(goal: str) -> list[str]:
    """Lowercase word tokens, minus stopwords and noise, lightly stemmed."""
    words = re.findall(r"[a-z0-9]+", (goal or "").lower())
    toks = []
    for w in words:
        if w in _STOPWORDS or len(w) < 2:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]          # crude singularisation
        toks.append(w)
    return toks


def _similarity(a: list[str], b: list[str]) -> float:
    """Overlap score in [0, 1]; 1.0 means the same token set."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter  = len(sa & sb)
    if not inter:
        return 0.0
    # Dice coefficient — kinder than Jaccard when one goal is wordier.
    return (2.0 * inter) / (len(sa) + len(sb))


# --- storage ------------------------------------------------------------------

def _empty() -> dict:
    return {"entries": [], "version": 1}


def _load() -> dict:
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            return _empty()
        return data
    except FileNotFoundError:
        return _empty()
    except Exception as e:
        print(f"[ProcMemory] ⚠️ Could not read store ({e}) — starting fresh")
        return _empty()


def _save(data: dict) -> None:
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_PATH.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(STORE_PATH)
    except Exception as e:
        print(f"[ProcMemory] ⚠️ Could not save store: {e}")


def _prune(entries: list[dict]) -> list[dict]:
    """Keep the most valuable, most recent entries."""
    def score(e: dict):
        uses = e.get("uses", 1) or 1
        wins = e.get("successes", 1)
        return (wins / uses, e.get("updated", 0))
    entries.sort(key=score, reverse=True)
    return entries[:MAX_ENTRIES]


# --- public API ---------------------------------------------------------------

def find_plan(goal: str) -> list[dict] | None:
    """
    Return a previously-successful action list for a similar goal, or None.

    A successful hit also bumps the entry's usage counter (so popular
    procedures survive pruning).
    """
    toks = _tokenize(goal)
    if len(toks) < MIN_TOKENS:
        return None

    with _lock:
        data = _load()
        best, best_sim = None, 0.0
        for entry in data.get("entries", []):
            sim = _similarity(toks, entry.get("tokens", []))
            if sim > best_sim:
                best, best_sim = entry, sim

        if best is None or best_sim < SIMILARITY_THRESHOLD:
            return None

        best["uses"] = best.get("uses", 1) + 1
        best["last_used"] = time.time()
        _save(data)

    print(f"[ProcMemory] ♻️ Reusing a known procedure "
          f"(match {best_sim:.0%}) for: {goal[:60]}")
    return [dict(a) for a in best.get("actions", [])] or None


def save_success(goal: str, actions: list[dict]) -> None:
    """Record the action sequence that successfully achieved `goal`."""
    actions = [a for a in (actions or []) if isinstance(a, dict) and a.get("tool")]
    if not actions:
        return

    toks = _tokenize(goal)
    if len(toks) < MIN_TOKENS:
        return

    with _lock:
        data = _load()
        entries = data.get("entries", [])

        target, best_sim = None, 0.0
        for entry in entries:
            sim = _similarity(toks, entry.get("tokens", []))
            if sim > best_sim:
                target, best_sim = entry, sim

        now = time.time()
        if target is not None and best_sim >= SIMILARITY_THRESHOLD:
            target["actions"]   = actions
            target["uses"]      = target.get("uses", 1) + 1
            target["successes"] = target.get("successes", 0) + 1
            target["updated"]   = now
            print(f"[ProcMemory] 📚 Updated a known procedure "
                  f"(match {best_sim:.0%}, {len(actions)} actions)")
        else:
            entries.append({
                "key":       " ".join(sorted(set(toks))),
                "goal":      goal[:300],
                "tokens":    toks,
                "actions":   actions,
                "uses":      1,
                "successes": 1,
                "created":   now,
                "updated":   now,
            })
            print(f"[ProcMemory] 🆕 Learned a new procedure "
                  f"({len(actions)} actions) for: {goal[:60]}")

        data["entries"] = _prune(entries)
        _save(data)


def note_failure(goal: str) -> None:
    """Record that a similar goal did NOT succeed (lowers reuse priority)."""
    toks = _tokenize(goal)
    if len(toks) < MIN_TOKENS:
        return
    with _lock:
        data = _load()
        for entry in data.get("entries", []):
            if _similarity(toks, entry.get("tokens", [])) >= SIMILARITY_THRESHOLD:
                entry["uses"] = entry.get("uses", 1) + 1
                entry["updated"] = time.time()
        _save(data)


def stats() -> dict:
    """Small summary for diagnostics / the UI."""
    with _lock:
        entries = _load().get("entries", [])
    return {
        "procedures":     len(entries),
        "total_uses":     sum(e.get("uses", 0) for e in entries),
        "total_successes": sum(e.get("successes", 0) for e in entries),
    }


def forget_all() -> None:
    """Wipe the store (exposed for maintenance/testing)."""
    with _lock:
        _save(_empty())
    print("[ProcMemory] 🧹 Procedure store cleared")
