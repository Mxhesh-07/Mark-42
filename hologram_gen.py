"""hologram_gen.py — AI model builder for J.A.R.V.I.S.'s holographic projector.

Turns ANY object description ("a dragon", "a coffee machine", "the Eiffel Tower")
into a renderable part-list model by asking Gemini for a structured layout.

Free to use (reuses the project's Gemini API key). Results are cached in
hologram_models/<slug>.json so repeat requests are instant.
"""
import os
import re
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
API_FILE = CONFIG_DIR / "api_keys.json"
MODELS_DIR = BASE_DIR / "hologram_models"

# Kept in sync with hologram.py
SHAPES = ("box", "sphere", "cyl", "cone", "pyramid", "torus")
COLORS = ("cyan", "amber", "white", "red", "green", "blue", "gray", "gold", "violet")

_SCHEMA_HINT = """{
  "name": "Object name",
  "kind": "one word category",
  "parts": [
    {"name": "Part name", "shape": "box|sphere|cyl|cone|pyramid|torus",
     "size": [numbers], "pos": [x, y, z], "color": "cyan|red|gold|...",
     "hot": false, "axis": "x|y|z", "rot": [rx, ry, rz]}
  ]
}"""

_SYSTEM = (
    "You are a 3D wireframe modeller for a holographic display. Given an object, "
    "output ONLY a JSON model made of simple primitive parts, no prose. "
    "Centre the object around the origin, use Y as up, keep it 2-7 units tall, "
    "use 6-24 parts, and make the silhouette recognisable. "
    "size: box=[sx,sy,sz], sphere=[rx,ry,rz], cyl/cone=[radius,height], "
    "pyramid=[sx,sy,sz], torus=[R,r]. axis (x|y|z) orients cylinders/cones/torus. "
    "Hot parts (true) glow (lights, screens, eyes, engines). "
    "Use colours from: " + ", ".join(COLORS) + ". "
    "Schema: " + _SCHEMA_HINT
)


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return s[:48] or "object"


def _api_key():
    for env in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(env):
            return os.environ[env]
    try:
        data = json.loads(API_FILE.read_text(encoding="utf-8"))
        return data.get("gemini_api_key") or data.get("api_key")
    except Exception:
        return None


def _extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        text = text[a:b + 1]
    return json.loads(text)


def _sanitize(model, fallback_name):
    if not isinstance(model, dict):
        return None
    parts = model.get("parts")
    if not isinstance(parts, list) or not parts:
        return None
    clean = []
    for p in parts[:40]:
        if not isinstance(p, dict):
            continue
        shape = str(p.get("shape", "box")).lower()
        if shape not in SHAPES:
            shape = "box"
        try:
            size = [abs(float(x)) for x in p.get("size", [1, 1, 1])][:3]
            pos = [float(x) for x in p.get("pos", [0, 1, 0])][:3]
        except Exception:
            continue
        if len(size) == 2 and shape in ("cyl", "cone", "torus"):
            pass
        elif len(size) < 3 and shape in ("box", "sphere", "pyramid"):
            size = (size + [size[-1] if size else 1])[:3]
        if len(pos) < 3:
            pos = (pos + [0])[:3]
        color = str(p.get("color", "cyan")).lower()
        if color not in COLORS:
            color = "cyan"
        axis = str(p.get("axis", "y")).lower()
        if axis not in ("x", "y", "z"):
            axis = "y"
        item = {"name": str(p.get("name", "Part"))[:28], "shape": shape,
                "size": size, "pos": pos, "color": color,
                "hot": bool(p.get("hot", False)), "axis": axis}
        if isinstance(p.get("rot"), (list, tuple)) and len(p["rot"]) == 3:
            item["rot"] = [float(x) for x in p["rot"]]
        clean.append(item)
    if not clean:
        return None
    return {"name": str(model.get("name") or fallback_name)[:40],
            "kind": str(model.get("kind", "object"))[:24], "parts": clean}


def generate(prompt, use_cache=True):
    """Return a model dict for `prompt`, or None on failure."""
    if not prompt:
        return None
    slug = _slug(prompt)
    cache_file = MODELS_DIR / f"{slug}.json"
    if use_cache and cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    key = _api_key()
    if not key:
        return None
    try:
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Object to model: {prompt}",
            config=gtypes.GenerateContentConfig(
                system_instruction=_SYSTEM,
                response_mime_type="application/json",
                temperature=0.7,
            ),
        )
        model = _sanitize(_extract_json(resp.text or ""), prompt)
    except Exception as e:
        print(f"[hologram_gen] generate failed: {e}")
        return None

    if model:
        try:
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(model, indent=2), encoding="utf-8")
        except Exception:
            pass
    return model


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "a dragon"
    m = generate(q)
    print(json.dumps(m, indent=2)[:900] if m else "generation failed")
