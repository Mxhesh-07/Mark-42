import re


def extract_memory(text: str):
    memories = {}

    # Name
    m = re.search(r"my name is ([a-zA-Z ]+)", text, re.I)
    if m:
        memories.setdefault("identity", {})
        memories["identity"]["name"] = m.group(1).strip()

    # Likes
    m = re.search(r"i like (.+)", text, re.I)
    if m:
        memories.setdefault("preferences", {})
        memories["preferences"]["interest"] = m.group(1).strip()

    # Favorite
    m = re.search(r"my favorite (.+) is (.+)", text, re.I)
    if m:
        memories.setdefault("preferences", {})
        memories["preferences"][m.group(1).replace(" ", "_")] = m.group(2)

    return memories