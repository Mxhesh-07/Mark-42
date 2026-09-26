import json
from pathlib import Path


class AIMemory:
    def __init__(self):
        self.memory_file = Path("memory/memories.json")

        self.data = {
            "user": {},
            "preferences": [],
            "projects": [],
            "notes": []
        }

        self.load()

    def load(self):
        if self.memory_file.exists():
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except:
                pass

    def save(self):
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