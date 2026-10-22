import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _default_data() -> dict:
    return {
        "user": {},
        "preferences": [],
        "projects": [],
        "notes": []
    }


class AIMemory:
    def __init__(self):
        # Resolve against the project root, not the current working
        # directory, so JARVIS launched from elsewhere still finds it.
        self.memory_file = BASE_DIR / "memory" / "memories.json"

        self.data = _default_data()
        self._ctx_cache = None
        self._ctx_mtime = None
        self.max_items = 50  # F5: cap context

        self.load()

    @staticmethod
    def _with_defaults(data):
        if not isinstance(data, dict):
            return _default_data()
        for key in _default_data():
            if key not in data:
                data[key] = _default_data()[key]
        return data

    def load(self):
        if self.memory_file.exists():
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    self.data = self._with_defaults(json.load(f))
                self._ctx_cache = None  # invalidate cache
                self._ctx_mtime = None
            except Exception:
                pass

    def save(self):
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)
        self._ctx_cache = None  # invalidate cache
        self._ctx_mtime = None

    def set_user_info(self, key, value):
        self.data["user"][key] = value
        self.save()

    def add_preference(self, text):
        if text not in self.data["preferences"]:
            self.data["preferences"].append(text)
            # prune low-value duplicates/overlong if needed
            if len(self.data["preferences"]) > self.max_items:
                self.data["preferences"] = self.data["preferences"][-self.max_items:]
            self.save()

    def add_project(self, project):
        if project not in self.data["projects"]:
            self.data["projects"].append(project)
            if len(self.data["projects"]) > self.max_items:
                self.data["projects"] = self.data["projects"][-self.max_items:]
            self.save()

    def remember(self, note):
        if note not in self.data["notes"]:
            self.data["notes"].append(note)
            if len(self.data["notes"]) > self.max_items:
                self.data["notes"] = self.data["notes"][-self.max_items:]
            self.save()

    def get_context(self, force: bool = False):
        try:
            mtime = self.memory_file.stat().st_mtime if self.memory_file.exists() else None
        except Exception:
            mtime = None
        if not force and self._ctx_cache is not None and self._ctx_mtime == mtime:
            return self._ctx_cache

        ctx = []
        data = self.data

        if data.get("user"):
            ctx.append("USER INFO:")
            # cap user items
            items = list(data["user"].items())[-self.max_items:]
            for k, v in items:
                ctx.append(f"{k}: {v}")

        if data.get("preferences"):
            ctx.append("\nPREFERENCES:")
            for p in data["preferences"][-self.max_items:]:
                ctx.append(f"- {p}")

        if data.get("projects"):
            ctx.append("\nPROJECTS:")
            for p in data["projects"][-self.max_items:]:
                ctx.append(f"- {p}")

        if data.get("notes"):
            ctx.append("\nMEMORIES:")
            # prune low-value: very short or generic notes? keep simple cap
            notes = data["notes"][-self.max_items:]
            for n in notes:
                ctx.append(f"- {n}")

        result = "\n".join(ctx)
        self._ctx_cache = result
        self._ctx_mtime = mtime
        return result