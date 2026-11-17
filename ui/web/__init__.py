"""Web HUD bridge and state board.

``ui.web_ui.WebUI`` drives this package; nothing here imports Tk so the bridge
can also be run on its own for front-end work:

    python -m ui.web.bridge
"""

__all__ = ["Bridge", "WebState"]


def __getattr__(name):
    # Lazy so ``python -m ui.web.bridge`` does not import itself twice.
    if name == "Bridge":
        from ui.web.bridge import Bridge
        return Bridge
    if name == "WebState":
        from ui.web.state import WebState
        return WebState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
