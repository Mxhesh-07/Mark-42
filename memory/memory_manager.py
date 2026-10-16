import json
from threading import RLock
from pathlib import Path
import sys

import memory


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = get_base_dir()
MEMORY_PATH = BASE_DIR / "memory" / "long_term.json"
_lock       = RLock()

MAX_VALUE_LENGTH = 300  

def _empty_memory():
    return {
        "identity": {},
        "preferences": {},
        "relationships": {},
        "projects": {},
        "goals": {},
        "important_dates": {},
        "skills": {},
        "notes": {},
        "personality_profile": {}
    }

def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()

    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            return _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()


def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return

    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False

    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue

        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            if isinstance(value, dict) and "value" in value:
                entry = {"value": _truncate_value(str(value["value"]))}
            else:
                entry = {"value": _truncate_value(str(value))}

            if key not in target or target[key] != entry:
                target[key] = entry
                changed = True

    return changed


def update_memory(memory_update: dict) -> dict:

    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()

    # Hold the lock across the whole read-modify-write so concurrent
    # background updates can't clobber each other. _lock is re-entrant,
    # so the nested load_memory()/save_memory() calls are safe.
    with _lock:
        memory = load_memory()

        if _recursive_update(memory, memory_update):
            save_memory(memory)
            print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")

    return memory



def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    def _val(entry):
        # Entries are usually {"value": ...} but may be raw scalars.
        if isinstance(entry, dict):
            return entry.get("value")
        return entry

    # Identity
    identity = memory.get("identity", {})
    if isinstance(identity, dict):
        name = _val(identity.get("name"))
        age  = _val(identity.get("age"))
        bday = _val(identity.get("birthday"))
        city = _val(identity.get("city"))
    else:
        name = age = bday = city = None
    if name: lines.append(f"Name: {name}")
    if age:  lines.append(f"Age: {age}")
    if bday: lines.append(f"Birthday: {bday}")
    if city: lines.append(f"City: {city}")

    prefs = memory.get("preferences", {})
    if isinstance(prefs, dict):
        for i, (key, entry) in enumerate(prefs.items()):
            if i >= 5:
                break
            val = _val(entry)
            if val:
                lines.append(f"{key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    if isinstance(rels, dict):
        for i, (key, entry) in enumerate(rels.items()):
            if i >= 5:
                break
            val = _val(entry)
            if val:
                lines.append(f"{key.title()}: {val}")

    notes = memory.get("notes", {})
    if isinstance(notes, dict):
        for i, (key, entry) in enumerate(notes.items()):
            if i >= 5:
                break
            val = _val(entry)
            if val:
                lines.append(f"{key}: {val}")

    # Projects
    projects = memory.get("projects", {})
    if isinstance(projects, dict):
        for key, entry in projects.items():
            val = _val(entry)
            if val:
                lines.append(f"Project: {val}")

    # Personality
    personality = memory.get("personality_profile", {})
    if isinstance(personality, dict):
        for key, entry in personality.items():
            val = _val(entry)
            if val:
                lines.append(f"Assistant Style: {val}")

    if not lines:
        return ""

    result = "[USER MEMORY]\n" + "\n".join(f"- {l}" for l in lines)
    if len(result) > 800:
        result = result[:797] + "…"

    return result + "\n"