"""Tier 3.13 / T3.15 / T3.10 — HUD support data.

Pure functions the window calls to fill the status strip, the audit view and
the kill-switch control. Keeping them out of `JarvisUI` means they can be
tested without Tk, and a failing subsystem shows as "unavailable" instead of
taking the window down.
"""

from __future__ import annotations


def status_snapshot() -> dict:
    """Provider/model, quota, degradation and queue depth for the status strip."""
    out = {"provider": "gemini", "model": "", "quota": "", "mode": "FULL",
           "queue": 0, "breakers": 0, "recording": False}

    try:
        from agent import quota

        out["quota"] = quota.describe()
        out["mode"] = str((quota.status().get("degradation") or {}).get("mode", "FULL"))
    except Exception:
        out["quota"] = "quota unavailable"

    try:
        import gemini_util

        stats = gemini_util.stats()
        chain = stats.get("chain") or []
        out["model"] = chain[0] if chain else ""
        out["breakers"] = len([b for b in stats.get("breakers", [])
                               if str(b.get("state", "")).lower() == "open"])
        cooling = stats.get("cooling") or {}
        if cooling:
            out["model"] = f"{out['model']} ({len(cooling)} cooling)"
    except Exception:
        pass

    try:
        from agent import task_queue

        out["queue"] = int(task_queue.get_queue().pending_count())
    except Exception:
        try:
            from agent import metrics

            out["queue"] = int(metrics.snapshot().get("queue_depth", 0))
        except Exception:
            out["queue"] = 0

    try:
        from ui import JarvisUI

        out["recording"] = bool(JarvisUI.recording_indicator().get("recording"))
    except Exception:
        out["recording"] = False

    return out


def status_text(state: dict | None = None) -> str:
    """One compact line; every field is optional by construction."""
    s = state or status_snapshot()
    parts = [f"{s.get('provider', '')}".strip(), str(s.get("model") or "model?")]
    if s.get("mode"):
        parts.append(str(s["mode"]))
    if s.get("queue"):
        parts.append(f"queue {s['queue']}")
    if s.get("breakers"):
        parts.append(f"breakers {s['breakers']}")
    if s.get("recording"):
        parts.append("REC")
    return "  |  ".join(part for part in parts if part)


def audit_lines(limit: int = 40) -> list[str]:
    """Recent audit entries as one-line strings (newest last)."""
    try:
        from agent import audit

        rows = audit.tail(limit)
        lines = []
        for row in rows:
            ts = str(row.get("ts") or row.get("time") or "")[:19]
            tool = str(row.get("tool") or row.get("event") or row.get("action") or "")
            outcome = str(row.get("outcome") or row.get("decision") or "")
            detail = str(row.get("detail") or "")
            line = "  ".join(part for part in (ts, tool, outcome) if part)
            if detail:
                line = f"{line}  — {detail}" if line else detail
            lines.append(line)
        return lines
    except Exception:
        return []


def kill_state() -> dict:
    try:
        from agent import policy

        engaged = bool(policy.kill_requested())
        return {"engaged": engaged,
                "label": "KILL SWITCH ENGAGED — actions blocked" if engaged
                         else "Autonomy active"}
    except Exception:
        return {"engaged": True, "label": "policy unavailable — actions fail closed"}


def engage_kill(reason: str = "HUD control") -> dict:
    """Engage the switch. This is the one action that must never fail open."""
    try:
        from agent import policy

        policy.engage_kill_switch(reason)
        return {"ok": True, "engaged": True, "reason": reason}
    except Exception as exc:
        return {"ok": False, "engaged": True, "reason": str(exc)}


def release_kill() -> dict:
    try:
        from agent import policy

        policy.disengage_kill_switch()
        return {"ok": True, "engaged": bool(policy.kill_requested())}
    except Exception as exc:
        return {"ok": False, "engaged": True, "reason": str(exc)}
