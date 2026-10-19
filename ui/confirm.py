"""The confirmation modal (Tier 4 W6).

``policy.py`` returns ``confirm`` and the executor fails closed when nobody
answers — correct, but the user then sees nothing happen at all, which makes the
project's best safety work invisible. This module puts it on screen.

Design constraints, in order of importance:

1. **Deny is the default.** The Deny button holds focus, the window close button
   denies, a timeout denies (30 s), and a broken or missing UI denies. Nothing
   here can approve by accident.
2. **The Tk event loop is never blocked.** ``ask`` is called from the executor's
   worker thread; the dialog is built on the Tk thread via ``root.after`` and the
   worker waits on an :class:`threading.Event`. The Tk thread only builds a
   window.
3. **Headless fails closed.** No Tk, no display, no answer → DENY.
4. **"Always allow" writes a narrow rule** (:mod:`agent.approval_rules`), and is
   not even offered when there is nothing narrow to bind to.
5. **Exactly one audit entry per decision**, naming the outcome and why.

The content builder is pure data, so the interesting half of this module is
testable without a display.
"""

from __future__ import annotations

import json
import sys
import threading

APPROVE = "approve"
DENY = "deny"
ALWAYS = "always"
DECISIONS = (APPROVE, DENY, ALWAYS)

DEFAULT_TIMEOUT_S = 30.0

_BUTTONS = (
    (DENY, "Deny", True),          # default focus
    (APPROVE, "Approve once", False),
    (ALWAYS, "Always allow this", False),
)


def _effect_for(tool: str, params: dict) -> str:
    try:
        from agent import approval

        return str(approval.effect_for(tool, params))
    except Exception:
        return str(tool)


def content(tool: str, params: dict | None = None, assessment=None, *,
            effect: str = "", timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    """Everything the modal shows, as plain data.

    ``assessment`` is a :class:`agent.judgement.Assessment` when W2 produced one;
    its risk, classification and opinion are surfaced so the user decides with
    the same information the assistant had.
    """
    from agent import approval_rules

    params = params or {}
    narrowable = approval_rules.narrowable(tool, params)
    buttons = [{"id": bid, "label": label, "default": focus}
               for bid, label, focus in _BUTTONS
               if bid != ALWAYS or narrowable]

    target = ""
    found = approval_rules.target_of(tool, params)
    if found:
        target = found[1]

    risk = getattr(assessment, "risk", None)
    return {
        "tool": str(tool),
        "summary": effect or _effect_for(tool, params),
        "target": target,
        "risk": risk,
        "reversibility": getattr(assessment, "reversibility", ""),
        "blast_radius": getattr(assessment, "blast_radius", ""),
        "confidence": getattr(assessment, "confidence", None),
        "opinion": getattr(assessment, "opinion", None),
        "buttons": buttons,
        "timeout_s": float(timeout_s),
        "narrowable": narrowable,
    }


class Answer:
    """A decision plus why it was made."""

    __slots__ = ("decision", "reason")

    def __init__(self, decision: str, reason: str):
        self.decision = decision if decision in DECISIONS else DENY
        self.reason = reason

    @property
    def approved(self) -> bool:
        return self.decision in (APPROVE, ALWAYS)

    def as_dict(self) -> dict:
        return {"decision": self.decision, "reason": self.reason,
                "approved": self.approved}

    def __repr__(self) -> str:
        return f"Answer({self.decision!r}, {self.reason!r})"


def consult(tool: str, params: dict | None = None, assessment=None, *,
            effect: str = "", timeout_s: float = DEFAULT_TIMEOUT_S,
            show=None) -> Answer:
    """Show the modal (if there is one) and return the user's answer.

    ``show`` is ``show(panel, done) -> None``; ``done(decision)`` resolves the
    dialog. It defaults to the Tk dialog, and is injectable so the marshalling,
    the timeout and the coercion can be tested without a display.
    """
    params = params or {}
    panel = content(tool, params, assessment, effect=effect, timeout_s=timeout_s)
    offered = {button["id"] for button in panel["buttons"]}

    if show is None:
        show = _show_tk if _tk_available() else None

    if show is None:
        answer = Answer(DENY, "no UI available")
    else:
        answer = _run(panel, show, timeout_s)

    # Defence in depth: a sink that answers with something the user could not
    # have clicked (a stale "always", when the button was not offered) denies.
    if answer.decision not in offered:
        answer = Answer(DENY, f"{answer.decision} was not offered")

    _record(tool, params, panel, answer)

    if answer.decision == ALWAYS:
        from agent import approval_rules

        rule = approval_rules.build(tool, params)
        if rule is not None:
            approval_rules.add(rule)

    return answer


def ask(tool: str, params: dict | None = None, assessment=None, **kwargs) -> str:
    """The W6 interface: ``APPROVE`` | ``DENY`` | ``ALWAYS``."""
    return consult(tool, params, assessment, **kwargs).decision


def _run(panel: dict, show, timeout_s: float) -> Answer:
    """Marshal the dialog onto the UI thread and wait, bounded, for an answer."""
    done = threading.Event()
    outcome: list[Answer] = []
    guard = threading.Lock()

    def finish(decision) -> None:
        with guard:
            if done.is_set():
                return
            outcome.append(Answer(decision, "chosen"))
            done.set()

    try:
        show(panel, finish)
    except Exception as e:
        print(f"[Confirm] ⚠️ the confirmation dialog failed: {e}")
        return Answer(DENY, "dialog failed")

    if not done.wait(max(0.0, float(timeout_s))):
        return Answer(DENY, "timeout")
    return outcome[0]


def _record(tool: str, params: dict, panel: dict, answer: Answer) -> None:
    """Exactly one audit entry per decision."""
    try:
        from agent import audit

        audit.record("approval_ui", tool=tool, parameters=params,
                     level=answer.decision, outcome=answer.decision,
                     detail=f"{answer.reason}: {panel['summary']}"[:300])
    except Exception:
        pass


# --- the Tk dialog ------------------------------------------------------------

def _tk_available() -> bool:
    try:
        import tkinter  # noqa: F401

        return True
    except Exception:
        return False


def _root() -> object | None:
    """The app's Tk root, if the UI has already been created."""
    for module_name in ("__main__", "ui"):
        module = sys.modules.get(module_name)
        for attribute in ("root", "ROOT"):
            root = getattr(module, attribute, None) if module else None
            if root is not None and hasattr(root, "after"):
                return root
    return None


def _show_tk(panel: dict, done) -> None:
    """Build the dialog on the Tk thread. Any failure denies."""
    root = _root()
    if root is None:
        done(DENY)
        return

    def build() -> None:
        try:
            _build(root, panel, done)
        except Exception as e:
            print(f"[Confirm] ⚠️ could not build the dialog: {e}")
            done(DENY)

    try:
        root.after(0, build)
    except Exception:
        done(DENY)


def _build(root, panel: dict, done) -> None:
    import tkinter as tk

    window = tk.Toplevel(root)
    window.title("JARVIS needs your OK")
    window.attributes("-topmost", True)
    window.resizable(False, False)

    settled = {"yes": False}

    def choose(decision: str) -> None:
        if settled["yes"]:
            return
        settled["yes"] = True
        try:
            window.grab_release()
        except Exception:
            pass
        try:
            window.destroy()
        except Exception:
            pass
        done(decision)

    tk.Label(window, text=panel["summary"], wraplength=520, justify="left",
             anchor="w").pack(fill="x", padx=14, pady=(14, 6))

    details = []
    if panel["target"]:
        details.append(f"target: {panel['target']}")
    if panel["risk"] is not None:
        details.append(f"risk: {panel['risk']:.2f} "
                       f"({panel['reversibility']}, {panel['blast_radius']})")
    if panel["opinion"]:
        details.append(panel["opinion"])
    if details:
        tk.Label(window, text="\n".join(details), wraplength=520, justify="left",
                 anchor="w", fg="#555555").pack(fill="x", padx=14, pady=(0, 10))

    row = tk.Frame(window)
    row.pack(fill="x", padx=14, pady=(0, 6))
    buttons = {}
    for spec in panel["buttons"]:
        button = tk.Button(row, text=spec["label"], width=18,
                           command=lambda sid=spec["id"]: choose(sid))
        button.pack(side="left", padx=4)
        buttons[spec["id"]] = button

    default_id = next((b["id"] for b in panel["buttons"] if b["default"]), DENY)
    buttons.get(default_id, buttons.get(DENY)).focus_set()

    seconds = int(panel["timeout_s"])
    status = tk.Label(window, text=f"denies automatically in {seconds}s",
                      fg="#888888")
    status.pack(pady=(0, 12))

    remaining = {"left": seconds}

    def tick() -> None:
        if settled["yes"]:
            return
        remaining["left"] -= 1
        if remaining["left"] <= 0:
            choose(DENY)
            return
        status.config(text=f"denies automatically in {remaining['left']}s")
        window.after(1000, tick)

    window.protocol("WM_DELETE_WINDOW", lambda: choose(DENY))
    window.after(1000, tick)
    try:
        window.grab_set()
    except Exception:
        pass


# --- the executor's approver --------------------------------------------------

def ui_approver(root=None, *, timeout_s: float = DEFAULT_TIMEOUT_S):
    """An approver for the background agent: ``(tool, params, effect) -> bool``.

    Bound to the UI: a queued `confirm` now appears as a window and the answer is
    bound to the effect, instead of the task failing closed with nothing shown.
    """
    def approver(tool: str, params: dict, effect: str = "", assessment=None) -> bool:
        answer = consult(tool, params, assessment, effect=effect,
                         timeout_s=timeout_s,
                         show=None if root is None else
                         (lambda panel, done: _show_on(root, panel, done)))
        return answer.approved

    return approver


def _show_on(root, panel: dict, done) -> None:
    def build() -> None:
        try:
            _build(root, panel, done)
        except Exception as e:
            print(f"[Confirm] ⚠️ could not build the dialog: {e}")
            done(DENY)

    root.after(0, build)


def _cli(argv=None) -> int:
    from agent import approval_rules, console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    tool = argv[0] if argv else "file_controller"
    params = json.loads(argv[1]) if len(argv) > 1 else {"action": "delete",
                                                        "path": "C:/tmp/demo.txt"}
    panel = content(tool, params)
    print(json.dumps({"panel": panel, "narrow_rule": approval_rules.build(tool, params)},
                     indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
