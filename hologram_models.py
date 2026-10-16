"""hologram_models.py — object library for J.A.R.V.I.S.'s holographic projector.

`get_model("car")` returns a model dict the viewer can render part-by-part.
Covers a large built-in vocabulary plus keyword heuristics, a colour override
("a red car"), and a final fallback that asks the AI builder (hologram_gen).
"""
import re
import json
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent / "hologram_models"

COLOR_WORDS = {
    "red": "red", "blue": "blue", "green": "green", "gold": "gold",
    "golden": "gold", "yellow": "gold", "orange": "amber", "amber": "amber",
    "purple": "violet", "violet": "violet", "black": "gray", "grey": "gray",
    "white": "white",
}


def _p(name, shape, size, pos, color="cyan", hot=False, axis="y", dir=None, rot=None):
    d = {"name": name, "shape": shape, "size": [float(x) for x in size],
         "pos": [float(x) for x in pos], "color": color, "hot": bool(hot), "axis": axis}
    if dir:
        d["dir"] = [float(x) for x in dir]
    if rot:
        d["rot"] = [float(x) for x in rot]
    return d


def _m(name, kind, parts, explode=None):
    m = {"name": name, "kind": kind, "parts": parts}
    if explode:
        m["explode"] = float(explode)
    return m


def _wheel(name, pos, r=0.42, h=0.34):
    return _p(name, "cyl", [r, h], pos, color="gray", axis="x")


# ==========================================================================
#  VEHICLES
# ==========================================================================
def car():
    p = [_p("Body", "box", [4.4, 0.9, 1.9], [0, 0.95, 0]),
         _p("Cabin", "box", [2.2, 0.8, 1.7], [-0.2, 1.7, 0]),
         _p("Windshield", "box", [0.12, 0.7, 1.6], [-1.32, 1.7, 0], "white", True),
         _wheel("Wheel FL", [1.5, 0.45, 1.0]), _wheel("Wheel FR", [1.5, 0.45, -1.0]),
         _wheel("Wheel RL", [-1.5, 0.45, 1.0]), _wheel("Wheel RR", [-1.5, 0.45, -1.0]),
         _p("Headlight L", "box", [0.12, 0.24, 0.4], [2.2, 0.95, 0.6], "white", True),
         _p("Headlight R", "box", [0.12, 0.24, 0.4], [2.2, 0.95, -0.6], "white", True),
         _p("Spoiler", "box", [0.2, 0.35, 1.7], [-2.2, 1.35, 0])]
    return _m("Car", "vehicle", p, 2.6)


def truck():
    p = [_p("Cargo", "box", [3.4, 2.0, 2.0], [-1.2, 1.6, 0]),
         _p("Cab", "box", [2.0, 1.6, 2.0], [1.7, 1.4, 0]),
         _p("Chassis", "box", [5.6, 0.4, 1.8], [0, 0.5, 0]),
         _p("Stack", "cyl", [0.12, 1.6], [0.9, 2.4, -0.9], "gray")]
    for i, (x, z) in enumerate([(2.1, 1.0), (2.1, -1.0), (-1.0, 1.0), (-1.0, -1.0), (-2.2, 1.0), (-2.2, -1.0)]):
        p.append(_wheel(f"Wheel {i+1}", [x, 0.5, z], 0.5, 0.36))
    return _m("Truck", "vehicle", p, 3.0)


def bus():
    p = [_p("Body", "box", [6.0, 2.4, 2.2], [0, 1.7, 0]),
         _p("Window Strip", "box", [5.4, 0.7, 2.26], [-0.2, 2.2, 0], "white", True),
         _p("Windscreen", "box", [0.12, 1.2, 1.9], [3.0, 1.9, 0], "white", True)]
    for i, (x, z) in enumerate([(2.0, 1.1), (2.0, -1.1), (-2.0, 1.1), (-2.0, -1.1)]):
        p.append(_wheel(f"Wheel {i+1}", [x, 0.55, z], 0.55, 0.4))
    return _m("Bus", "vehicle", p, 3.2)


def motorcycle():
    p = [_wheel("Wheel Front", [1.1, 0.5, 0], 0.5, 0.2),
         _wheel("Wheel Rear", [-1.1, 0.5, 0], 0.5, 0.2),
         _p("Frame", "box", [1.8, 0.4, 0.35], [0, 1.0, 0]),
         _p("Engine", "box", [0.9, 0.7, 0.7], [0, 0.9, 0], "gray"),
         _p("Seat", "box", [0.9, 0.25, 0.5], [-0.5, 1.25, 0]),
         _p("Fuel Tank", "box", [0.8, 0.4, 0.5], [0.4, 1.25, 0]),
         _p("Handlebar", "cyl", [0.06, 1.0], [1.2, 1.5, 0], "gray", axis="z"),
         _p("Headlight", "sphere", [0.22, 0.22, 0.22], [1.35, 1.35, 0], "white", True)]
    return _m("Motorcycle", "vehicle", p, 2.0)


def bicycle():
    p = [_wheel("Wheel Front", [1.0, 0.55, 0], 0.55, 0.09),
         _wheel("Wheel Rear", [-1.0, 0.55, 0], 0.55, 0.09),
         _p("Frame", "box", [1.7, 0.12, 0.12], [0, 0.9, 0]),
         _p("Seat Tube", "cyl", [0.08, 0.7], [-0.7, 0.95, 0], "gray"),
         _p("Saddle", "box", [0.5, 0.12, 0.22], [-0.7, 1.3, 0]),
         _p("Handlebar Post", "cyl", [0.08, 0.7], [0.7, 0.95, 0], "gray"),
         _p("Handlebar", "cyl", [0.05, 0.7], [0.7, 1.3, 0], "gray", axis="z")]
    return _m("Bicycle", "vehicle", p, 2.0)


def train():
    p = [_p("Boiler", "cyl", [0.9, 4.4], [-0.6, 1.3, 0], axis="x"),
         _p("Cab", "box", [1.6, 1.6, 1.8], [1.9, 1.4, 0]),
         _p("Chimney", "cyl", [0.3, 1.0], [-2.2, 2.3, 0], "gray", axis="y"),
         _p("Chimney Top", "cone", [0.42, 0.5], [-2.2, 3.0, 0], "gray"),
         _p("Cowcatcher", "pyramid", [1.4, 0.8, 1.8], [-2.9, 0.6, 0], rot=[0, 90, 0])]
    for i, x in enumerate([-1.8, -0.9, 0.0, 0.9, 1.8]):
        p.append(_wheel(f"Driver {i+1}", [x, 0.45, 0.75], 0.45, 0.16))
        p.append(_wheel(f"Driver {i+1}b", [x, 0.45, -0.75], 0.45, 0.16))
    return _m("Steam Train", "vehicle", p, 3.0)


def helicopter():
    p = [_p("Body", "sphere", [1.1, 0.9, 1.6], [0, 1.6, 0], "cyan"),
         _p("Cockpit", "sphere", [0.7, 0.7, 0.7], [0, 1.7, 1.2], "white", True),
         _p("Tail", "cyl", [0.22, 2.6], [0, 1.6, -2.2], "gray", axis="z"),
         _p("Tail Rotor", "cyl", [0.6, 0.06], [0, 1.7, -3.5], "gray", axis="x"),
         _p("Tail Fin", "box", [0.1, 0.9, 0.6], [0, 2.1, -3.4]),
         _p("Mast", "cyl", [0.12, 0.6], [0, 2.6, 0], "gray"),
         _p("Main Rotor", "cyl", [2.6, 0.05], [0, 2.9, 0], "gray", axis="y"),
         _p("Skid L", "box", [2.0, 0.08, 0.12], [0, 0.6, 0.7]),
         _p("Skid R", "box", [2.0, 0.08, 0.12], [0, 0.6, -0.7])]
    return _m("Helicopter", "vehicle", p, 3.0)


def airplane():
    p = [_p("Fuselage", "cyl", [0.7, 6.0], [0, 1.6, 0], axis="z"),
         _p("Nose", "cone", [0.7, 1.2], [0, 1.6, 3.5], axis="z"),
         _p("Wing L", "box", [4.6, 0.18, 1.4], [-2.4, 1.5, 0.2]),
         _p("Wing R", "box", [4.6, 0.18, 1.4], [2.4, 1.5, 0.2]),
         _p("Tail Wing", "box", [2.0, 0.15, 0.8], [0, 1.7, -2.9]),
         _p("Tail Fin", "box", [0.15, 1.2, 1.0], [0, 2.3, -2.9]),
         _p("Engine L", "cyl", [0.35, 1.2], [-1.6, 1.2, 0.4], "gray", axis="z"),
         _p("Engine R", "cyl", [0.35, 1.2], [1.6, 1.2, 0.4], "gray", axis="z"),
         _p("Cockpit", "sphere", [0.5, 0.45, 0.9], [0, 1.9, 2.2], "white", True)]
    return _m("Airplane", "vehicle", p, 3.4)


def rocket():
    p = [_p("Body", "cyl", [0.85, 5.2], [0, 2.8, 0], axis="y"),
         _p("Nose Cone", "cone", [0.85, 1.8], [0, 6.3, 0], axis="y"),
         _p("Window", "sphere", [0.28, 0.28, 0.28], [0, 5.0, 0.8], "white", True),
         _p("Fin L", "box", [0.12, 1.4, 1.2], [-0.9, 1.0, 0.5]),
         _p("Fin R", "box", [0.12, 1.4, 1.2], [0.9, 1.0, 0.5]),
         _p("Fin Back", "box", [1.2, 1.4, 0.12], [0, 1.0, -0.9]),
         _p("Flame", "cone", [0.7, 1.6], [0, -0.9, 0], "amber", True, axis="y", rot=[180, 0, 0])]
    return _m("Rocket", "vehicle", p, 3.4)


def ship():
    p = [_p("Hull", "box", [6.0, 1.1, 2.2], [0, 0.8, 0]),
         _p("Bow", "cone", [1.1, 1.6], [3.6, 0.8, 0], rot=[0, 0, -90], axis="y"),
         _p("Deck", "box", [4.4, 0.2, 2.0], [-0.4, 1.45, 0]),
         _p("Cabin", "box", [1.6, 1.0, 1.6], [-1.8, 2.0, 0], "white", True),
         _p("Funnel", "cyl", [0.3, 1.0], [-1.0, 2.5, 0], "gray"),
         _p("Mast", "cyl", [0.08, 2.4], [1.6, 2.6, 0], "gray")]
    return _m("Ship", "vehicle", p, 3.2)


def submarine():
    p = [_p("Hull", "sphere", [1.0, 1.0, 4.0], [0, 1.4, 0]),
         _p("Sail", "box", [0.5, 1.0, 1.4], [0, 2.5, 0.2]),
         _p("Periscope", "cyl", [0.06, 1.0], [0, 3.2, 0.2], "gray"),
         _p("Propeller", "cyl", [0.8, 0.08], [0, 1.4, -4.2], "gray", axis="z"),
         _p("Fin Top", "box", [0.1, 0.8, 0.7], [0, 2.2, -3.4]),
         _p("Fin L", "box", [0.7, 0.1, 0.7], [-0.6, 1.4, -3.4]),
         _p("Fin R", "box", [0.7, 0.1, 0.7], [0.6, 1.4, -3.4])]
    return _m("Submarine", "vehicle", p, 3.0)


def tank():
    p = [_p("Hull", "box", [4.2, 1.2, 2.4], [0, 1.1, 0]),
         _p("Turret", "sphere", [1.0, 0.7, 1.1], [0, 2.0, 0]),
         _p("Barrel", "cyl", [0.16, 3.0], [0, 2.1, 2.2], "gray", axis="z"),
         _p("Track L", "box", [4.6, 1.0, 0.55], [0, 0.6, 1.3], "gray"),
         _p("Track R", "box", [4.6, 1.0, 0.55], [0, 0.6, -1.3], "gray")]
    return _m("Tank", "vehicle", p, 3.0)


def drone():
    p = [_p("Body", "box", [1.0, 0.3, 1.0], [0, 1.5, 0]),
         _p("Camera", "sphere", [0.2, 0.2, 0.2], [0, 1.2, 0], "white", True)]
    for i, (x, z) in enumerate([(1.0, 1.0), (1.0, -1.0), (-1.0, 1.0), (-1.0, -1.0)]):
        p.append(_p(f"Arm {i+1}", "box", [1.2, 0.08, 0.08], [x / 2, 1.5, z / 2], rot=[0, 45 if x * z > 0 else -45, 0]))
        p.append(_p(f"Rotor {i+1}", "cyl", [0.6, 0.04], [x, 1.65, z], "gray", axis="y"))
    return _m("Drone", "vehicle", p, 2.6)


# ==========================================================================
#  BUILDINGS
# ==========================================================================
def house():
    p = [_p("Walls", "box", [4.0, 2.0, 3.0], [0, 1.0, 0]),
         _p("Roof", "pyramid", [4.6, 1.6, 3.6], [0, 2.8, 0]),
         _p("Door", "box", [0.1, 1.2, 0.8], [2.0, 0.6, 0.4]),
         _p("Window L", "box", [0.1, 0.7, 0.8], [2.0, 1.2, -0.9], "white", True),
         _p("Window R", "box", [0.8, 0.7, 0.1], [0.6, 1.2, 1.5], "white", True),
         _p("Chimney", "box", [0.5, 1.2, 0.5], [-1.2, 3.0, -0.6], "gray")]
    return _m("House", "building", p, 3.2)


def building():
    p = [_p("Tower", "box", [3.0, 8.0, 3.0], [0, 4.0, 0]),
         _p("Roof", "box", [3.2, 0.3, 3.2], [0, 8.15, 0], "gray"),
         _p("Antenna", "cyl", [0.06, 1.4], [0, 9.0, 0], "gray")]
    for i in range(6):
        y = 1.0 + i * 1.2
        p.append(_p(f"Windows {i+1} L", "box", [0.1, 0.6, 2.4], [-1.52, y, 0], "white", True))
        p.append(_p(f"Windows {i+1} R", "box", [0.1, 0.6, 2.4], [1.52, y, 0], "white", True))
    return _m("Skyscraper", "building", p, 4.0)


def castle():
    p = [_p("Keep", "box", [3.0, 3.0, 3.0], [0, 1.5, 0]),
         _p("Gate", "box", [0.7, 1.4, 0.1], [0, 0.7, 1.52]),
         _p("Wall", "box", [8.0, 1.6, 0.6], [0, 0.8, 3.0])]
    for i, x in enumerate([-3.4, 3.4]):
        p.append(_p(f"Tower {i+1}", "cyl", [0.9, 3.0], [x, 1.5, 3.0]))
        p.append(_p(f"Turret {i+1}", "cone", [1.1, 1.0], [x, 3.5, 3.0], "gray"))
    p.append(_p("Keep Roof", "pyramid", [3.2, 1.4, 3.2], [0, 3.7, 0]))
    return _m("Castle", "building", p, 3.6)


def tower():
    p = [_p("Shaft", "cyl", [1.0, 7.0], [0, 3.5, 0]),
         _p("Balcony", "cyl", [1.4, 0.2], [0, 6.6, 0]),
         _p("Top", "cone", [1.3, 1.6], [0, 7.8, 0], "gray"),
         _p("Window", "box", [0.4, 0.6, 0.1], [0, 4.0, 1.0], "white", True)]
    return _m("Tower", "building", p, 3.6)


def lighthouse():
    p = [_p("Base", "cyl", [1.3, 0.6], [0, 0.3, 0]),
         _p("Tower", "cone", [1.1, 6.0], [0, 3.3, 0]),
         _p("Gallery", "cyl", [1.1, 0.25], [0, 6.3, 0]),
         _p("Lamp", "sphere", [0.55, 0.55, 0.55], [0, 6.9, 0], "white", True),
         _p("Roof", "cone", [0.7, 0.8], [0, 7.6, 0], "gray")]
    return _m("Lighthouse", "building", p, 3.4)


def bridge():
    p = [_p("Deck", "box", [9.0, 0.4, 3.0], [0, 2.0, 0]),
         _p("Tower L", "box", [0.6, 4.6, 3.4], [-3.0, 3.0, 0]),
         _p("Tower R", "box", [0.6, 4.6, 3.4], [3.0, 3.0, 0])]
    for i in range(-2, 3):
        p.append(_p(f"Cable {i+1}", "box", [0.08, 0.08, 3.0], [i * 1.1, 3.6, 0], "gray"))
    p.append(_p("Pillar L", "cyl", [0.4, 2.0], [-4.4, 1.0, 0], "gray"))
    p.append(_p("Pillar R", "cyl", [0.4, 2.0], [4.4, 1.0, 0], "gray"))
    return _m("Bridge", "building", p, 4.0)


def factory():
    p = [_p("Hall", "box", [6.0, 2.4, 3.0], [0, 1.2, 0]),
         _p("Roof", "box", [6.2, 0.2, 3.2], [0, 2.5, 0], "gray")]
    for i, x in enumerate([-1.8, 1.8]):
        p.append(_p(f"Chimney {i+1}", "cyl", [0.35, 3.0], [x, 4.0, 0], "gray"))
    p.append(_p("Tank", "cyl", [0.9, 1.4], [2.4, 1.0, 1.4], "gray"))
    return _m("Factory", "building", p, 3.6)


# ==========================================================================
#  NATURE
# ==========================================================================
def tree():
    p = [_p("Trunk", "cyl", [0.35, 3.0], [0, 1.5, 0], "gray"),
         _p("Foliage 1", "sphere", [1.6, 1.6, 1.6], [0, 3.6, 0]),
         _p("Foliage 2", "sphere", [1.2, 1.2, 1.2], [0.9, 4.3, 0.3]),
         _p("Foliage 3", "sphere", [1.1, 1.1, 1.1], [-0.8, 4.1, -0.4])]
    return _m("Tree", "nature", p, 3.0)


def flower():
    p = [_p("Stem", "cyl", [0.08, 3.0], [0, 1.5, 0], "green"),
         _p("Leaf L", "sphere", [0.5, 0.12, 0.28], [-0.45, 1.6, 0], "green"),
         _p("Leaf R", "sphere", [0.5, 0.12, 0.28], [0.45, 2.1, 0], "green"),
         _p("Center", "sphere", [0.35, 0.35, 0.35], [0, 3.1, 0], "gold", True)]
    for i in range(6):
        import math as _math
        a = _math.radians(i * 60)
        p.append(_p(f"Petal {i+1}", "sphere", [0.32, 0.14, 0.32],
                    [0.6 * _math.cos(a), 3.1, 0.6 * _math.sin(a)], "red"))
    return _m("Flower", "nature", p, 2.2)


def cactus():
    p = [_p("Trunk", "cyl", [0.4, 3.0], [0, 1.5, 0], "green"),
         _p("Arm L", "cyl", [0.22, 1.4], [-0.6, 2.2, 0], "green", axis="y"),
         _p("Arm L2", "cyl", [0.22, 0.8], [-1.0, 2.6, 0], "green", axis="x"),
         _p("Arm R", "cyl", [0.22, 1.2], [0.6, 1.9, 0], "green", axis="y"),
         _p("Arm R2", "cyl", [0.22, 0.7], [0.95, 2.2, 0], "green", axis="x")]
    return _m("Cactus", "nature", p, 2.6)


def mushroom():
    p = [_p("Stem", "cyl", [0.35, 1.4], [0, 0.7, 0], "white"),
         _p("Cap", "sphere", [1.2, 0.8, 1.2], [0, 1.6, 0], "red"),
         _p("Spot 1", "sphere", [0.18, 0.18, 0.18], [0.5, 1.9, 0.3], "white"),
         _p("Spot 2", "sphere", [0.14, 0.14, 0.14], [-0.4, 1.8, -0.3], "white")]
    return _m("Mushroom", "nature", p, 2.0)


def mountain():
    p = [_p("Mountain", "cone", [2.6, 4.0], [0, 2.0, 0], "gray", axis="y"),
         _p("Snow Cap", "cone", [0.9, 1.2], [0, 3.4, 0], "white", axis="y")]
    return _m("Mountain", "nature", p, 2.6)


def volcano():
    p = [_p("Mountain", "cone", [2.6, 3.6], [0, 1.8, 0], "gray", axis="y"),
         _p("Crater", "cyl", [0.5, 0.6], [0, 3.6, 0], "amber", True, axis="y"),
         _p("Lava", "cone", [0.35, 1.0], [0, 4.4, 0], "red", True, axis="y")]
    return _m("Volcano", "nature", p, 2.6)


def cloud():
    p = [_p("Puff 1", "sphere", [1.2, 1.0, 1.2], [-1.0, 2.0, 0]),
         _p("Puff 2", "sphere", [1.5, 1.2, 1.5], [0.2, 2.2, 0]),
         _p("Puff 3", "sphere", [1.1, 0.9, 1.1], [1.4, 2.0, 0]),
         _p("Puff 4", "sphere", [1.0, 0.8, 1.0], [0.2, 2.9, 0])]
    return _m("Cloud", "nature", p, 2.6)


def planet():
    p = [_p("Planet", "sphere", [2.2, 2.2, 2.2], [0, 2.2, 0], "blue"),
         _p("Land 1", "sphere", [0.6, 0.6, 0.6], [1.0, 2.9, 0.8], "green"),
         _p("Land 2", "sphere", [0.5, 0.5, 0.5], [-1.1, 1.6, 0.7], "green"),
         _p("Ring 1", "sphere", [2.0, 0.1, 2.0], [0, 2.2, 0], "white", True)]
    return _m("Planet", "nature", p, 3.0)


def sun():
    p = [_p("Core", "sphere", [1.8, 1.8, 1.8], [0, 2.4, 0], "gold", True)]
    import math as _math
    for i in range(8):
        a = _math.radians(i * 45)
        p.append(_p(f"Ray {i+1}", "box", [0.2, 0.2, 1.0],
                    [2.4 * _math.cos(a), 2.4, 2.4 * _math.sin(a)], "amber", True,
                    rot=[0, -i * 45, 0]))
    return _m("Sun", "nature", p, 2.6)


def moon():
    p = [_p("Moon", "sphere", [1.6, 1.6, 1.6], [0, 2.0, 0], "gray"),
         _p("Crater 1", "sphere", [0.3, 0.3, 0.3], [0.9, 2.5, 0.6], "gray"),
         _p("Crater 2", "sphere", [0.22, 0.22, 0.22], [-0.7, 1.7, 0.8], "gray")]
    return _m("Moon", "nature", p, 2.4)


def snowman():
    p = [_p("Base", "sphere", [1.2, 1.2, 1.2], [0, 1.2, 0], "white"),
         _p("Torso", "sphere", [0.9, 0.9, 0.9], [0, 3.0, 0], "white"),
         _p("Head", "sphere", [0.65, 0.65, 0.65], [0, 4.3, 0], "white"),
         _p("Nose", "cone", [0.12, 0.5], [0, 4.3, 0.7], "amber", axis="z"),
         _p("Scarf", "torus", [0.7, 0.12], [0, 3.6, 0], "red", axis="y")]
    return _m("Snowman", "nature", p, 2.6)


# ==========================================================================
#  ANIMALS
# ==========================================================================
def _quadruped(name, color, body=(1.8, 0.8, 0.7), head=(0.45, 0.45, 0.45),
               leg_r=0.13, leg_h=0.9, snout=None, ears=None, tail=True, neck=False):
    bx, by, bz = body
    p = [_p("Body", "cyl", [bz / 2, bx], [0, by / 2 + leg_h, 0], color, axis="z")]
    hy = by / 2 + leg_h + by * 0.35
    if neck:
        p.append(_p("Neck", "cyl", [bz * 0.3, 0.7], [0, hy + 0.3, bx * 0.55], color))
        hy += 0.5
        hz = bx * 0.7
    else:
        hz = bx * 0.62
    p.append(_p("Head", "sphere", list(head), [0, hy + 0.1, hz], color))
    if snout:
        p.append(_p("Snout", "box", snout, [0, hy, hz + head[2]], color))
    if ears == "cone":
        p.append(_p("Ear L", "cone", [0.16, 0.4], [-0.28, hy + 0.5, hz], color))
        p.append(_p("Ear R", "cone", [0.16, 0.4], [0.28, hy + 0.5, hz], color))
    elif ears == "round":
        p.append(_p("Ear L", "sphere", [0.2, 0.25, 0.1], [-0.35, hy + 0.45, hz], color))
        p.append(_p("Ear R", "sphere", [0.2, 0.25, 0.1], [0.35, hy + 0.45, hz], color))
    for i, (x, z) in enumerate([(bx * 0.34, bz / 2 + 0.1), (bx * 0.34, -bz / 2 - 0.1),
                                (-bx * 0.34, bz / 2 + 0.1), (-bx * 0.34, -bz / 2 - 0.1)]):
        p.append(_p(f"Leg {i+1}", "cyl", [leg_r, leg_h], [x, leg_h / 2, z], color, axis="y"))
    if tail:
        p.append(_p("Tail", "cyl", [0.08, 0.8], [0, by / 2 + leg_h + 0.2, -bx / 2 - 0.4], color,
                    axis="z", rot=[-40, 0, 0]))
    return p


def dog():
    p = _quadruped("Dog", "gold", body=(1.8, 0.8, 0.7), head=(0.45, 0.45, 0.5),
                   snout=[0.3, 0.3, 0.4], ears="cone")
    return _m("Dog", "animal", p, 2.2)


def cat():
    p = _quadruped("Cat", "gray", body=(1.5, 0.6, 0.55), head=(0.42, 0.42, 0.42),
                   leg_r=0.1, leg_h=0.7, snout=[0.24, 0.22, 0.3], ears="cone")
    return _m("Cat", "animal", p, 2.0)


def horse():
    p = _quadruped("Horse", "amber", body=(2.4, 1.0, 0.9), head=(0.42, 0.42, 0.6),
                   leg_r=0.12, leg_h=1.4, snout=[0.3, 0.3, 0.6], ears="cone", neck=True)
    return _m("Horse", "animal", p, 2.6)


def cow():
    p = _quadruped("Cow", "white", body=(2.4, 1.1, 0.95), head=(0.5, 0.5, 0.5),
                   leg_r=0.14, leg_h=1.1, snout=[0.5, 0.45, 0.4], ears="round", neck=True)
    p.append(_p("Horn L", "cone", [0.08, 0.3], [-0.2, 2.6, 1.3], "gray"))
    p.append(_p("Horn R", "cone", [0.08, 0.3], [0.2, 2.6, 1.3], "gray"))
    return _m("Cow", "animal", p, 2.8)


def elephant():
    p = _quadruped("Elephant", "gray", body=(2.8, 1.6, 1.4), head=(0.7, 0.7, 0.7),
                   leg_r=0.3, leg_h=1.3, ears="round")
    p.append(_p("Trunk", "cyl", [0.16, 1.2], [0, 1.6, 2.2], "gray", axis="y"))
    p.append(_p("Tusk L", "cone", [0.07, 0.5], [-0.3, 1.5, 2.0], "white"))
    p.append(_p("Tusk R", "cone", [0.07, 0.5], [0.3, 1.5, 2.0], "white"))
    return _m("Elephant", "animal", p, 3.0)


def rabbit():
    p = _quadruped("Rabbit", "white", body=(1.1, 0.7, 0.7), head=(0.4, 0.4, 0.4),
                   leg_r=0.1, leg_h=0.6)
    p.append(_p("Ear L", "cyl", [0.1, 0.9], [-0.18, 2.0, 0.5], "white", axis="y", rot=[20, 0, 0]))
    p.append(_p("Ear R", "cyl", [0.1, 0.9], [0.18, 2.0, 0.5], "white", axis="y", rot=[20, 0, 0]))
    return _m("Rabbit", "animal", p, 2.0)


def bird():
    p = [_p("Body", "sphere", [0.7, 0.7, 0.9], [0, 1.6, 0], "blue"),
         _p("Head", "sphere", [0.4, 0.4, 0.4], [0, 2.2, 0.7], "blue"),
         _p("Beak", "cone", [0.12, 0.4], [0, 2.15, 1.1], "amber", axis="z"),
         _p("Wing L", "box", [0.9, 0.08, 0.5], [-0.7, 1.7, 0], "blue", rot=[0, 0, 20]),
         _p("Wing R", "box", [0.9, 0.08, 0.5], [0.7, 1.7, 0], "blue", rot=[0, 0, -20]),
         _p("Tail", "box", [0.5, 0.08, 0.6], [0, 1.5, -0.9], "blue"),
         _p("Leg L", "cyl", [0.05, 0.4], [-0.2, 0.85, 0], "amber"),
         _p("Leg R", "cyl", [0.05, 0.4], [0.2, 0.85, 0], "amber")]
    return _m("Bird", "animal", p, 2.0)


def fish():
    p = [_p("Body", "sphere", [0.5, 0.9, 1.6], [0, 1.6, 0], "cyan"),
         _p("Tail", "cone", [0.7, 0.9], [0, 1.6, -1.7], "cyan", axis="z", rot=[0, 0, 0]),
         _p("Dorsal Fin", "box", [0.06, 0.6, 0.7], [0, 2.4, 0], "cyan"),
         _p("Eye", "sphere", [0.12, 0.12, 0.12], [0.35, 1.8, 1.0], "white", True)]
    return _m("Fish", "animal", p, 2.2)


def whale():
    p = [_p("Body", "sphere", [1.2, 1.2, 3.2], [0, 1.6, 0], "blue"),
         _p("Tail", "cyl", [0.1, 1.8], [0, 1.6, -2.2], "blue", axis="y", rot=[90, 0, 0]),
         _p("Fin L", "box", [0.9, 0.1, 0.5], [-0.9, 1.2, 0.5], "blue"),
         _p("Fin R", "box", [0.9, 0.1, 0.5], [0.9, 1.2, 0.5], "blue"),
         _p("Eye", "sphere", [0.1, 0.1, 0.1], [0.9, 1.7, 2.0], "white", True)]
    return _m("Whale", "animal", p, 2.8)


def snake():
    p = []
    import math as _math
    for i in range(10):
        x = -2.0 + i * 0.45
        y = 0.6 + 0.5 * _math.sin(i * 1.1)
        p.append(_p(f"Segment {i+1}", "sphere", [0.32, 0.32, 0.32], [x, y, 0.5 * _math.cos(i * 1.1)], "green"))
    p.append(_p("Head", "sphere", [0.42, 0.32, 0.32], [2.4, 0.7 + 0.5 * _math.sin(11), 0.5 * _math.cos(11)], "green"))
    return _m("Snake", "animal", p, 2.6)


def turtle():
    p = [_p("Shell", "sphere", [1.0, 0.55, 1.2], [0, 1.2, 0], "green"),
         _p("Head", "sphere", [0.3, 0.3, 0.3], [0, 1.2, 1.4], "green"),
         _p("Leg FL", "cyl", [0.14, 0.5], [0.7, 0.7, 0.6], "green", axis="z"),
         _p("Leg FR", "cyl", [0.14, 0.5], [-0.7, 0.7, 0.6], "green", axis="z"),
         _p("Leg BL", "cyl", [0.14, 0.5], [0.7, 0.7, -0.6], "green", axis="z"),
         _p("Leg BR", "cyl", [0.14, 0.5], [-0.7, 0.7, -0.6], "green", axis="z"),
         _p("Tail", "cone", [0.1, 0.4], [0, 1.2, -1.4], "green", axis="z")]
    return _m("Turtle", "animal", p, 2.2)


def dinosaur():
    p = [_p("Body", "sphere", [0.9, 1.0, 1.8], [0, 2.0, 0], "green"),
         _p("Neck", "cyl", [0.3, 1.4], [0, 3.2, 1.4], "green", axis="y", rot=[30, 0, 0]),
         _p("Head", "sphere", [0.45, 0.45, 0.7], [0, 4.0, 2.2], "green"),
         _p("Tail", "cone", [0.5, 2.6], [0, 1.8, -2.6], "green", axis="z"),
         _p("Leg L", "cyl", [0.25, 1.4], [-0.7, 0.8, 0.4], "green"),
         _p("Leg R", "cyl", [0.25, 1.4], [0.7, 0.8, 0.4], "green")]
    for i in range(3):
        p.append(_p(f"Spike {i+1}", "cone", [0.18, 0.5], [0, 3.1, 0.4 - i * 0.7], "green"))
    return _m("Dinosaur", "animal", p, 3.0)


# ==========================================================================
#  OBJECTS / TECH
# ==========================================================================
def phone():
    p = [_p("Body", "box", [1.4, 2.8, 0.18], [0, 1.6, 0]),
         _p("Screen", "box", [1.24, 2.5, 0.05], [0, 1.6, 0.11], "white", True),
         _p("Camera", "sphere", [0.08, 0.08, 0.05], [0, 2.75, 0.11], "gray")]
    return _m("Phone", "device", p, 1.8)


def laptop():
    p = [_p("Base", "box", [3.0, 0.18, 2.1], [0, 0.6, 0]),
         _p("Keyboard", "box", [2.6, 0.04, 1.2], [0, 0.71, 0.3], "gray"),
         _p("Screen", "box", [3.0, 1.9, 0.12], [0, 1.55, -0.95], rot=[-20, 0, 0]),
         _p("Display", "box", [2.7, 1.6, 0.03], [0, 1.6, -0.86], "white", True, rot=[-20, 0, 0])]
    return _m("Laptop", "device", p, 2.2)


def computer():
    p = [_p("Tower", "box", [1.2, 2.4, 2.2], [-1.8, 1.2, 0], "gray"),
         _p("Monitor", "box", [3.0, 1.9, 0.12], [0.6, 2.0, 0]),
         _p("Screen", "box", [2.8, 1.7, 0.04], [0.6, 2.0, 0.09], "white", True),
         _p("Stand", "box", [0.5, 0.9, 0.5], [0.6, 1.0, 0], "gray"),
         _p("Base", "box", [2.0, 0.12, 1.2], [0.6, 0.55, 0], "gray"),
         _p("Keyboard", "box", [2.2, 0.1, 0.8], [0.6, 0.6, 1.0], "gray")]
    return _m("Computer", "device", p, 2.4)


def tv():
    p = [_p("Frame", "box", [4.0, 2.4, 0.2], [0, 2.0, 0], "gray"),
         _p("Screen", "box", [3.7, 2.1, 0.04], [0, 2.0, 0.12], "white", True),
         _p("Stand", "box", [0.6, 0.8, 0.4], [0, 0.6, 0], "gray"),
         _p("Foot", "box", [2.0, 0.12, 1.0], [0, 0.2, 0], "gray")]
    return _m("Television", "device", p, 2.4)


def camera():
    p = [_p("Body", "box", [2.4, 1.6, 1.0], [0, 1.6, 0], "gray"),
         _p("Lens", "cyl", [0.5, 0.7], [0, 1.6, 0.75], "gray", axis="z"),
         _p("Lens Glass", "cyl", [0.4, 0.06], [0, 1.6, 1.12], "white", True, axis="z"),
         _p("Flash", "box", [0.4, 0.25, 0.08], [-0.8, 2.1, 0.5], "white", True),
         _p("Shutter", "sphere", [0.12, 0.12, 0.12], [0.9, 2.15, 0.5], "gray")]
    return _m("Camera", "device", p, 2.0)


def clock():
    p = [_p("Face", "cyl", [1.4, 0.25], [0, 2.2, 0], axis="z"),
         _p("Hour Hand", "box", [0.09, 0.8, 0.06], [0, 2.5, 0.16]),
         _p("Minute Hand", "box", [0.6, 0.09, 0.06], [0.25, 2.2, 0.16], rot=[0, 0, 0]),
         _p("Center", "sphere", [0.1, 0.1, 0.1], [0, 2.2, 0.16], "gray"),
         _p("Leg L", "cyl", [0.08, 0.5], [-0.7, 0.9, 0], "gray", rot=[20, 0, 0]),
         _p("Leg R", "cyl", [0.08, 0.5], [0.7, 0.9, 0], "gray", rot=[20, 0, 0])]
    return _m("Clock", "object", p, 2.0)


def watch():
    p = [_p("Case", "cyl", [0.8, 0.22], [0, 1.6, 0], axis="z"),
         _p("Dial", "cyl", [0.68, 0.04], [0, 1.6, 0.13], "white", True, axis="z"),
         _p("Strap T", "box", [0.5, 1.6, 0.12], [0, 2.8, 0]),
         _p("Strap B", "box", [0.5, 1.6, 0.12], [0, 0.4, 0])]
    return _m("Watch", "object", p, 1.8)


def lamp():
    p = [_p("Base", "cyl", [0.7, 0.2], [0, 0.1, 0], "gray"),
         _p("Pole", "cyl", [0.08, 2.8], [0, 1.5, 0], "gray"),
         _p("Shade", "cone", [1.0, 1.2], [0, 3.2, 0], "amber", axis="y", rot=[180, 0, 0]),
         _p("Bulb", "sphere", [0.25, 0.25, 0.25], [0, 2.9, 0], "white", True)]
    return _m("Lamp", "object", p, 2.2)


def chair():
    p = [_p("Seat", "box", [1.4, 0.15, 1.4], [0, 1.0, 0]),
         _p("Back", "box", [1.4, 1.6, 0.15], [0, 1.85, -0.62]),
         _p("Leg FL", "cyl", [0.07, 1.0], [0.55, 0.5, 0.55], "gray"),
         _p("Leg FR", "cyl", [0.07, 1.0], [-0.55, 0.5, 0.55], "gray"),
         _p("Leg BL", "cyl", [0.07, 1.0], [0.55, 0.5, -0.55], "gray"),
         _p("Leg BR", "cyl", [0.07, 1.0], [-0.55, 0.5, -0.55], "gray")]
    return _m("Chair", "object", p, 1.8)


def table():
    p = [_p("Top", "box", [3.0, 0.2, 1.8], [0, 1.5, 0])]
    for i, (x, z) in enumerate([(1.3, 0.75), (1.3, -0.75), (-1.3, 0.75), (-1.3, -0.75)]):
        p.append(_p(f"Leg {i+1}", "cyl", [0.09, 1.5], [x, 0.75, z], "gray"))
    return _m("Table", "object", p, 1.8)


def bed():
    p = [_p("Frame", "box", [4.0, 0.4, 2.2], [0, 0.7, 0], "gray"),
         _p("Mattress", "box", [3.8, 0.5, 2.0], [0, 1.15, 0], "white"),
         _p("Pillow", "box", [0.6, 0.25, 1.6], [-1.4, 1.5, 0], "white"),
         _p("Headboard", "box", [0.2, 1.4, 2.2], [-2.0, 1.3, 0])]
    return _m("Bed", "object", p, 2.4)


def book():
    p = [_p("Cover", "box", [2.6, 3.4, 0.2], [0, 1.9, 0], "red"),
         _p("Pages", "box", [2.5, 3.3, 0.3], [0, 1.9, 0], "white"),
         _p("Spine", "box", [0.15, 3.4, 0.45], [-1.3, 1.9, 0], "red")]
    return _m("Book", "object", p, 2.0)


def pen():
    p = [_p("Barrel", "cyl", [0.14, 2.4], [0, 1.2, 0], "blue", axis="y"),
         _p("Nib", "cone", [0.14, 0.4], [0, -0.2, 0], "gray", axis="y", rot=[180, 0, 0]),
         _p("Cap", "cyl", [0.16, 0.8], [0, 2.6, 0], "gray")]
    return _m("Pen", "object", p, 1.8)


def cup():
    p = [_p("Body", "cyl", [0.6, 1.4], [0, 1.0, 0], "white"),
         _p("Handle", "torus", [0.35, 0.1], [0.7, 1.1, 0], "white", axis="x")]
    return _m("Mug", "object", p, 1.6)


def bottle():
    p = [_p("Body", "cyl", [0.45, 1.8], [0, 0.9, 0], "green"),
         _p("Neck", "cyl", [0.2, 0.5], [0, 2.0, 0], "green"),
         _p("Cap", "cyl", [0.24, 0.25], [0, 2.35, 0], "white")]
    return _m("Bottle", "object", p, 1.6)


def key():
    p = [_p("Ring", "torus", [0.35, 0.09], [0, 1.8, 0], "gold", axis="z"),
         _p("Shaft", "cyl", [0.07, 1.6], [0, 0.9, 0], "gold", axis="y"),
         _p("Tooth 1", "box", [0.3, 0.14, 0.1], [0.15, 0.35, 0], "gold"),
         _p("Tooth 2", "box", [0.22, 0.14, 0.1], [0.12, 0.6, 0], "gold")]
    return _m("Key", "object", p, 1.6)


def guitar():
    p = [_p("Body", "sphere", [0.9, 1.1, 0.35], [0, 1.4, 0], "amber"),
         _p("Hole", "cyl", [0.22, 0.4], [0, 1.4, 0], "gray", axis="z"),
         _p("Neck", "box", [0.28, 2.2, 0.16], [0, 3.0, 0], "gray"),
         _p("Head", "box", [0.5, 0.5, 0.18], [0, 4.3, 0], "gray")]
    return _m("Guitar", "object", p, 2.2)


def piano():
    p = [_p("Body", "box", [4.0, 0.8, 1.6], [0, 1.6, 0]),
         _p("Keys", "box", [4.0, 0.12, 0.6], [0, 2.05, 0.6], "white", True),
         _p("Lid", "box", [4.0, 0.15, 0.5], [0, 2.0, -0.5]),
         _p("Leg L", "cyl", [0.1, 1.2], [-1.6, 0.6, 0.4], "gray"),
         _p("Leg R", "cyl", [0.1, 1.2], [1.6, 0.6, 0.4], "gray")]
    return _m("Piano", "object", p, 2.4)


def gun():
    p = [_p("Barrel", "cyl", [0.12, 2.2], [0, 1.5, 1.0], "gray", axis="z"),
         _p("Slide", "box", [0.35, 0.4, 1.6], [0, 1.6, 0.4], "gray"),
         _p("Grip", "box", [0.35, 1.0, 0.4], [0, 1.0, -0.35], rot=[20, 0, 0]),
         _p("Trigger Guard", "torus", [0.22, 0.05], [0, 1.2, 0.15], "gray", axis="x")]
    return _m("Gun", "object", p, 1.8)


def sword():
    p = [_p("Blade", "box", [0.16, 3.4, 0.06], [0, 3.0, 0], "white"),
         _p("Guard", "box", [1.0, 0.15, 0.2], [0, 1.25, 0], "gold"),
         _p("Grip", "cyl", [0.09, 0.9], [0, 0.8, 0], "gray"),
         _p("Pommel", "sphere", [0.14, 0.14, 0.14], [0, 0.3, 0], "gold")]
    return _m("Sword", "object", p, 2.4)


def shield():
    p = [_p("Disc", "cyl", [1.5, 0.25], [0, 1.8, 0], "blue", axis="z"),
         _p("Boss", "sphere", [0.35, 0.35, 0.35], [0, 1.8, 0.2], "gold"),
         _p("Ring", "torus", [1.5, 0.08], [0, 1.8, 0.05], "white", axis="z")]
    return _m("Shield", "object", p, 2.0)


def helmet():
    p = [_p("Dome", "sphere", [1.1, 1.2, 1.1], [0, 2.0, 0], "red"),
         _p("Faceplate", "box", [1.1, 0.9, 0.4], [0, 1.95, 0.85], "gold"),
         _p("Eye L", "box", [0.34, 0.1, 0.1], [-0.33, 2.15, 1.15], "white", True),
         _p("Eye R", "box", [0.34, 0.1, 0.1], [0.33, 2.15, 1.15], "white", True)]
    return _m("Helmet", "object", p, 2.0)


def robot():
    p = [_p("Head", "box", [1.2, 1.0, 1.2], [0, 3.4, 0]),
         _p("Eye L", "sphere", [0.14, 0.14, 0.14], [-0.3, 3.5, 0.65], "white", True),
         _p("Eye R", "sphere", [0.14, 0.14, 0.14], [0.3, 3.5, 0.65], "white", True),
         _p("Antenna", "cyl", [0.06, 0.5], [0, 4.15, 0], "gray"),
         _p("Antenna Ball", "sphere", [0.12, 0.12, 0.12], [0, 4.5, 0], "red", True),
         _p("Torso", "box", [1.8, 2.0, 1.0], [0, 1.8, 0]),
         _p("Arm L", "cyl", [0.22, 1.8], [-1.2, 1.9, 0], "gray"),
         _p("Arm R", "cyl", [0.22, 1.8], [1.2, 1.9, 0], "gray"),
         _p("Leg L", "cyl", [0.28, 1.6], [-0.5, 0.6, 0], "gray"),
         _p("Leg R", "cyl", [0.28, 1.6], [0.5, 0.6, 0], "gray")]
    return _m("Robot", "object", p, 2.6)


def person():
    p = [_p("Head", "sphere", [0.5, 0.6, 0.5], [0, 4.2, 0]),
         _p("Neck", "cyl", [0.2, 0.3], [0, 3.7, 0], "gray"),
         _p("Torso", "box", [1.4, 1.9, 0.8], [0, 2.7, 0]),
         _p("Arm L", "cyl", [0.18, 1.9], [-0.9, 2.7, 0], "gray"),
         _p("Arm R", "cyl", [0.18, 1.9], [0.9, 2.7, 0], "gray"),
         _p("Leg L", "cyl", [0.24, 1.9], [-0.35, 0.9, 0], "gray"),
         _p("Leg R", "cyl", [0.24, 1.9], [0.35, 0.9, 0], "gray")]
    return _m("Person", "human", p, 2.6)


def heart():
    p = [_p("Lobe L", "sphere", [0.9, 0.9, 0.7], [-0.6, 2.4, 0], "red"),
         _p("Lobe R", "sphere", [0.9, 0.9, 0.7], [0.6, 2.4, 0], "red"),
         _p("Tip", "cone", [1.1, 1.6], [0, 1.2, 0], "red", axis="y", rot=[180, 0, 0])]
    return _m("Heart", "biology", p, 2.2)


def brain():
    p = [_p("Left", "sphere", [0.9, 1.0, 1.2], [-0.45, 2.2, 0], "violet"),
         _p("Right", "sphere", [0.9, 1.0, 1.2], [0.45, 2.2, 0], "violet"),
         _p("Cerebellum", "sphere", [0.5, 0.4, 0.5], [0, 1.5, -0.7], "violet"),
         _p("Stem", "cyl", [0.18, 0.7], [0, 1.3, 0.3], "gray")]
    return _m("Brain", "biology", p, 2.2)


def ball():
    return _m("Ball", "object", [_p("Ball", "sphere", [1.2, 1.2, 1.2], [0, 1.2, 0])], 1.8)


def cube():
    return _m("Cube", "shape", [_p("Cube", "box", [2, 2, 2], [0, 1.0, 0])], 1.8)


def sphere():
    return _m("Sphere", "shape", [_p("Sphere", "sphere", [1.2, 1.2, 1.2], [0, 1.2, 0])], 1.8)


def pyramid():
    return _m("Pyramid", "shape", [_p("Pyramid", "pyramid", [2.4, 2.2, 2.4], [0, 1.1, 0])], 1.8)


def cone():
    return _m("Cone", "shape", [_p("Cone", "cone", [1.1, 2.2], [0, 1.1, 0])], 1.8)


def torus():
    return _m("Torus", "shape", [_p("Torus", "torus", [1.2, 0.4], [0, 1.0, 0])], 1.8)


def star():
    p = [_p("Core", "sphere", [0.5, 0.5, 0.5], [0, 1.6, 0], "gold", True)]
    import math as _math
    for i in range(5):
        a = _math.radians(i * 72)
        p.append(_p(f"Point {i+1}", "cone", [0.3, 1.2], [1.2 * _math.cos(a), 1.6, 1.2 * _math.sin(a)],
                    "gold", rot=[0, -i * 72, 90]))
    return _m("Star", "shape", p, 2.2)


def suit():
    p = [
        _p("Helmet", "sphere", [1.35, 1.55, 1.35], [0, 7.95, 0], "red"),
        _p("Faceplate", "box", [1.5, 1.15, 0.55], [0, 7.85, 1.02], "gold", dir=[0, 0.25, 1]),
        _p("Eye L", "box", [0.46, 0.14, 0.12], [-0.42, 8.12, 1.46], "white", True, dir=[-0.5, 0.2, 1]),
        _p("Eye R", "box", [0.46, 0.14, 0.12], [0.42, 8.12, 1.46], "white", True, dir=[0.5, 0.2, 1]),
        _p("Neck", "cyl", [0.5, 0.9], [0, 6.6, 0], "gold"),
        _p("Chest Plate", "box", [3.1, 3.3, 1.7], [0, 4.9, 0], "red"),
        _p("Arc Reactor", "cyl", [0.5, 0.28], [0, 5.35, 0.92], "white", True, axis="z", dir=[0, 0.15, 1]),
        _p("Abdomen", "box", [2.2, 1.7, 1.35], [0, 2.85, 0], "red"),
        _p("Pelvis", "box", [2.7, 1.5, 1.6], [0, 1.5, 0], "red"),
        _p("Spine", "box", [1.4, 3.0, 0.6], [0, 3.9, -0.72], "gold", dir=[0, 0.2, -1]),
        _p("Back Thruster", "box", [1.7, 2.5, 0.55], [0, 4.9, -1.05], "gold", dir=[0, 0.3, -1]),
        _p("Shoulder L", "sphere", [0.72, 0.72, 0.72], [-1.95, 5.7, 0], "red"),
        _p("Shoulder R", "sphere", [0.72, 0.72, 0.72], [1.95, 5.7, 0], "red"),
        _p("Upper Arm L", "cyl", [0.42, 2.3], [-2.05, 4.15, 0], "red"),
        _p("Upper Arm R", "cyl", [0.42, 2.3], [2.05, 4.15, 0], "red"),
        _p("Forearm L", "cyl", [0.4, 2.1], [-2.05, 2.15, 0], "red"),
        _p("Forearm R", "cyl", [0.4, 2.1], [2.05, 2.15, 0], "red"),
        _p("Gauntlet L", "box", [0.85, 1.05, 0.75], [-2.05, 0.75, 0], "red"),
        _p("Gauntlet R", "box", [0.85, 1.05, 0.75], [2.05, 0.75, 0], "red"),
        _p("Thigh L", "cyl", [0.6, 2.7], [-0.95, -0.7, 0], "red"),
        _p("Thigh R", "cyl", [0.6, 2.7], [0.95, -0.7, 0], "red"),
        _p("Knee L", "sphere", [0.52, 0.52, 0.52], [-0.95, -2.1, 0], "gold"),
        _p("Knee R", "sphere", [0.52, 0.52, 0.52], [0.95, -2.1, 0], "gold"),
        _p("Shin L", "cyl", [0.48, 2.7], [-0.95, -3.6, 0], "red"),
        _p("Shin R", "cyl", [0.48, 2.7], [0.95, -3.6, 0], "red"),
        _p("Boot L", "box", [1.15, 1.05, 2.1], [-0.95, -5.55, 0.35], "red"),
        _p("Boot R", "box", [1.15, 1.05, 2.1], [0.95, -5.55, 0.35], "red"),
    ]
    return _m("Iron Man Suit", "armour", p, 6.5)


# ==========================================================================
#  BUILDERS / ALIASES
# ==========================================================================
BUILDERS = {
    "car": car, "truck": truck, "bus": bus, "motorcycle": motorcycle, "bicycle": bicycle,
    "train": train, "airplane": airplane, "helicopter": helicopter, "rocket": rocket,
    "ship": ship, "submarine": submarine, "tank": tank, "drone": drone,
    "house": house, "building": building, "castle": castle, "tower": tower,
    "lighthouse": lighthouse, "bridge": bridge, "factory": factory,
    "tree": tree, "flower": flower, "cactus": cactus, "mushroom": mushroom,
    "mountain": mountain, "volcano": volcano, "cloud": cloud, "planet": planet,
    "sun": sun, "moon": moon, "snowman": snowman,
    "dog": dog, "cat": cat, "horse": horse, "cow": cow, "elephant": elephant,
    "rabbit": rabbit, "bird": bird, "fish": fish, "whale": whale, "snake": snake,
    "turtle": turtle, "dinosaur": dinosaur,
    "phone": phone, "laptop": laptop, "computer": computer, "tv": tv, "camera": camera,
    "clock": clock, "watch": watch, "lamp": lamp, "chair": chair, "table": table,
    "bed": bed, "book": book, "pen": pen, "cup": cup, "bottle": bottle, "key": key,
    "guitar": guitar, "piano": piano, "gun": gun, "sword": sword, "shield": shield,
    "helmet": helmet, "robot": robot, "person": person, "heart": heart, "brain": brain,
    "ball": ball, "cube": cube, "sphere": sphere, "pyramid": pyramid, "cone": cone,
    "torus": torus, "star": star, "suit": suit,
}

ALIASES = {
    "automobile": "car", "sedan": "car", "suv": "car", "vehicle": "car", "taxi": "car",
    "lorry": "truck", "van": "bus", "bike": "bicycle", "motorbike": "motorcycle",
    "aeroplane": "airplane", "plane": "airplane", "jet": "airplane", "aircraft": "airplane",
    "chopper": "helicopter", "boat": "ship", "yacht": "ship", "vessel": "ship",
    "skyscraper": "building", "temple": "house", "home": "house", "hut": "house",
    "office": "building", "palm": "tree", "plant": "flower", "earth": "planet",
    "globe": "planet", "world": "planet", "saturn": "planet", "mars": "planet",
    "star": "star", "puppy": "dog", "kitten": "cat", "pussycat": "cat",
    "mobile": "phone", "smartphone": "phone", "iphone": "phone", "cellphone": "phone",
    "pc": "computer", "desktop": "computer", "monitor": "tv", "television": "tv",
    "mug": "cup", "coffee": "cup", "donut": "torus", "doughnut": "torus",
    "ring": "torus", "hoop": "torus", "circle": "torus", "orb": "sphere",
    "block": "cube", "box": "cube", "iron man": "suit", "ironman": "suit",
    "armor": "suit", "armour": "suit", "mark": "suit", "avenger": "suit",
    "human": "person", "man": "person", "woman": "person", "boy": "person", "girl": "person",
    "sun": "sun", "spike": "star",
}


def _clean(q):
    q = str(q or "").lower().strip()
    q = re.sub(r"^(please\s+)?(show|display|render|make|draw|build|create|project|hologram|holographic|give|see)\s+", "", q)
    q = re.sub(r"^(me\s+)?(a|an|the)\s+", "", q)
    q = re.sub(r"\s+(in|as)?\s*(3d|three d|hologram|holographic|holographically)\b.*$", "", q)
    return q.strip()


def get_model(query):
    q = _clean(query)
    color = None
    for word, cname in COLOR_WORDS.items():
        if re.search(rf"\b{word}\b", q):
            color = cname
            break

    model = None
    if q in BUILDERS:
        model = BUILDERS[q]()
    else:
        for alias in sorted(ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", q):
                model = BUILDERS[ALIASES[alias]]()
                break
    if model is None:
        for key in sorted(BUILDERS, key=len, reverse=True):
            if re.search(rf"\b{re.escape(key)}\b", q) or key in q:
                model = BUILDERS[key]()
                break
    if model is None:
        # ask the AI builder, then fall back to a generic placeholder
        try:
            import hologram_gen
            model = hologram_gen.generate(query)
        except Exception:
            model = None
    if model is None:
        model = _generic(query or "object")

    if color:
        for p in model.get("parts", []):
            if p.get("color") == "cyan" and not p.get("hot"):
                p["color"] = color
    return model


def _generic(query):
    label = (query or "object").title()[:18]
    p = [_p("Pedestal", "cyl", [1.4, 0.3], [0, 0.15, 0], "gray"),
         _p("Core", "sphere", [1.1, 1.1, 1.1], [0, 1.8, 0], "cyan", True),
         _p("Frame A", "torus", [1.5, 0.12], [0, 1.8, 0], "cyan", axis="z"),
         _p("Frame B", "torus", [1.5, 0.12], [0, 1.8, 0], "cyan", axis="x"),
         _p(f"{label} Node 1", "cube" if False else "box", [0.4, 0.4, 0.4], [1.9, 1.8, 0], "amber"),
         _p(f"{label} Node 2", "box", [0.4, 0.4, 0.4], [-1.9, 1.8, 0], "amber"),
         _p(f"{label} Node 3", "box", [0.4, 0.4, 0.4], [0, 1.8, 1.9], "amber"),
         _p(f"{label} Node 4", "box", [0.4, 0.4, 0.4], [0, 1.8, -1.9], "amber")]
    return _m(label, "unknown", p, 2.4)


def list_models():
    return sorted(BUILDERS.keys())


def save(model, name=None):
    """Write a model to hologram_models/<slug>.json and return the path."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(name or model.get("name", "object")).lower()).strip("_")[:48]
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    path = MODELS_DIR / f"{slug or 'object'}.json"
    path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    import sys
    import json as _json
    q = " ".join(sys.argv[1:]) or "car"
    m = get_model(q)
    print(f"{m['name']} ({m['kind']}) - {len(m['parts'])} parts")
    print(_json.dumps(m, indent=2)[:800])
