"""Tier 3.12 — notification centre.

`notifications.get_all_notifications()` already collects the data; this module
turns it into rows and a compact digest for the HUD, and is the one place that
knows how to mark things read. No network calls happen here — that belongs to
the monitor thread.
"""

from __future__ import annotations

KINDS = ("email", "whatsapp", "instagram")


def rows(raw: dict | None = None) -> list[dict]:
    if raw is None:
        try:
            import notifications

            raw = notifications.get_all_notifications()
        except Exception:
            raw = {}
    out: list[dict] = []
    for kind in KINDS:
        items = raw.get(kind) if isinstance(raw, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            out.append({
                "kind": kind,
                "id": str(item.get("id", "")),
                "title": str(item.get("subject") or item.get("title") or item.get("from") or ""),
                "unread": not bool(item.get("read")),
            })
    return out


def digest(raw: dict | None = None) -> str:
    counts = {kind: 0 for kind in KINDS}
    for row in rows(raw):
        if row["unread"]:
            counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    total = sum(counts.values())
    if not total:
        return "No unread notifications."
    parts = [f"{count} {kind}" for kind, count in counts.items() if count]
    return f"{total} unread: " + ", ".join(parts)


def mark_all_read(kind: str | None = None) -> bool:
    try:
        import notifications

        notifications.mark_all_read(kind)
        return True
    except Exception:
        return False


def notification_lines(limit: int = 20) -> list[str]:
    items = rows()
    lines = []
    for row in items[:max(1, int(limit))]:
        mark = "●" if row["unread"] else "○"
        lines.append(f"{mark} [{row['kind']}] {row['title']}")
    return lines
