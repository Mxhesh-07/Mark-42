"""Tier 3.25 — small drawn icons for buttons that a glyph renders poorly.

The HUD used text like the backspace glyph on a button. These icons are drawn
with Pillow (already a dependency) so they scale cleanly, need no asset files and
can be recoloured. `pil_icon` is pure and returns a PIL image; `tk_icon` wraps it
for Tk once a root exists.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

NAMES = ("backspace", "mic", "send", "settings", "close", "kill", "hologram")


def _canvas(size: int, color: str) -> tuple[Image.Image, ImageDraw.ImageDraw, float]:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), size / 24.0


def pil_icon(name: str, size: int = 22, color: str = "#00d4ff") -> Image.Image:
    size = max(8, int(size))
    img, d, s = _canvas(size, color)
    w = max(1, int(round(2 * s)))

    def line(points, width=w):
        d.line([(int(x * s), int(y * s)) for x, y in points], fill=color, width=width)

    if name == "backspace":
        line([(7, 5), (2, 12), (7, 19)])
        line([(7, 5), (21, 5), (21, 19), (7, 19)])
        line([(11, 9), (17, 15)])
        line([(17, 9), (11, 15)])
    elif name == "mic":
        d.rounded_rectangle((int(9 * s), int(3 * s), int(15 * s), int(14 * s)),
                            radius=int(3 * s), fill=color)
        line([(5, 11), (5, 13), (19, 13), (19, 11)])
        line([(12, 16), (12, 20)])
        line([(8, 20), (16, 20)])
    elif name == "send":
        line([(3, 12), (21, 3), (14, 21), (11, 13), (3, 12)])
    elif name == "settings":
        d.ellipse((int(5 * s), int(5 * s), int(19 * s), int(19 * s)),
                  outline=color, width=w)
        d.ellipse((int(10 * s), int(10 * s), int(14 * s), int(14 * s)), fill=color)
        for a, b in (((12, 1), (12, 5)), ((12, 19), (12, 23)),
                     ((1, 12), (5, 12)), ((19, 12), (23, 12))):
            line([a, b])
    elif name == "close":
        line([(5, 5), (19, 19)])
        line([(19, 5), (5, 19)])
    elif name == "kill":
        d.ellipse((int(4 * s), int(4 * s), int(20 * s), int(20 * s)),
                  outline=color, width=w)
        line([(12, 2), (12, 12)], width=max(w, int(round(3 * s))))
    elif name == "hologram":
        line([(12, 2), (21, 7), (21, 17), (12, 22), (3, 17), (3, 7), (12, 2)])
        line([(3, 7), (12, 12), (21, 7)])
        line([(12, 12), (12, 22)])
    else:
        raise ValueError(f"unknown icon: {name}")
    return img


def tk_icon(root, name: str, size: int = 22, color: str = "#00d4ff"):
    """Return a Tk image kept alive by `root` (Tk otherwise garbage-collects it)."""
    try:
        from PIL import ImageTk
    except Exception:
        return None
    image = ImageTk.PhotoImage(pil_icon(name, size, color), master=root)
    cache = getattr(root, "_icon_cache", None)
    if cache is None:
        cache = []
        try:
            root._icon_cache = cache
        except Exception:
            pass
    cache.append(image)
    return image
