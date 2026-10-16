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
            except Exception:
                pass

    def save(self):
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)

    def set_user_info(self, key, value):
        self.data["user"][key] = value
        self.save()

    def add_preference(self, text):
        if text not in self.data["preferences"]:
            self.data["preferences"].append(text)
            self.save()

    def add_project(self, project):
        if project not in self.data["projects"]:
            self.data["projects"].append(project)
            self.save()

    def remember(self, note):
        if note not in self.data["notes"]:
            self.data["notes"].append(note)
            self.save()

    def get_context(self):
        ctx = []

        if self.data["user"]:
            ctx.append("USER INFO:")
            for k, v in self.data["user"].items():
                ctx.append(f"{k}: {v}")

        if self.data["preferences"]:
            ctx.append("\nPREFERENCES:")
            for p in self.data["preferences"]:
                ctx.append(f"- {p}")

        if self.data["projects"]:
            ctx.append("\nPROJECTS:")
            for p in self.data["projects"]:
                ctx.append(f"- {p}")

        if self.data["notes"]:
            ctx.append("\nMEMORIES:")
            for n in self.data["notes"]:
                ctx.append(f"- {n}")

        return "\n".join(ctx)