"""
J.A.R.V.I.S. — Notification Tracker
Monitors email, WhatsApp, and Instagram.
Shows briefing when user opens laptop.
"""

import json
import time
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent
NOTIF_PATH = BASE_DIR / "notifications.json"
_lock = threading.RLock()

_running = False
_thread = None

# WhatsApp/Instagram checks launch a headless browser and time out when the
# user isn't logged in. Back them off after repeated failures, then retry
# once an hour so they self-heal if the user logs in later.
_MAX_FAILS = 3
_BACKOFF_SECONDS = 3600
_wa_fail_streak = 0
_ig_fail_streak = 0
_wa_disabled_until = 0.0
_ig_disabled_until = 0.0


def _load_data() -> dict:
    if not NOTIF_PATH.exists():
        return {
            "emails": [],
            "whatsapp": [],
            "instagram": [],
            "last_check": None,
            "seen_email_ids": [],
            "seen_whatsapp": [],
            "seen_instagram": [],
        }
    try:
        with open(NOTIF_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_data(data: dict) -> None:
    NOTIF_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(NOTIF_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def _decode_subject(raw) -> str:
    """Safely decode an email Subject header (handles None / encoded words)."""
    if not raw:
        return ""
    from email.header import decode_header
    try:
        parts = decode_header(raw)
        return "".join(
            p.decode(enc or "utf-8", errors="ignore") if isinstance(p, bytes) else p
            for p, enc in parts
        )
    except Exception:
        return str(raw)


def check_emails() -> list:
    """Check for new emails using Gmail API or IMAP."""
    try:
        import imaplib
        import email
        from email.header import decode_header

        with open(BASE_DIR / "config" / "email_config.json", "r", encoding="utf-8") as f:
            config = json.load(f)

        password = "".join(str(config.get("password", "")).split())
        host = config.get("imap_server") or config.get("server") or "imap.gmail.com"
        mail = imaplib.IMAP4_SSL(host, config.get("imap_port", 993))
        mail.login(config["email"], password)
        mail.select("inbox")

        _, messages = mail.search(None, "UNSEEN")
        email_ids = messages[0].split()

        data = _load_data()
        new_emails = []

        for eid in email_ids[-10:]:
            if eid.decode() in data.get("seen_email_ids", []):
                continue

            _, msg_data = mail.fetch(eid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            subject = _decode_subject(msg.get("Subject"))

            sender = msg["From"]
            date = msg["Date"]

            email_obj = {
                "id": eid.decode(),
                "subject": subject,
                "from": sender,
                "date": date,
                "received_at": datetime.now().isoformat(),
                "type": "email",
                "read": False,
            }
            new_emails.append(email_obj)

        mail.logout()
        return new_emails

    except Exception as e:
        print(f"[Notif] Email check failed: {e}")
        return []


def check_whatsapp() -> list:
    """Check WhatsApp Web for new messages using Playwright."""
    global _wa_fail_streak, _wa_disabled_until

    if time.time() < _wa_disabled_until:
        return []

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://web.whatsapp.com", timeout=30000)

                page.wait_for_selector('[data-testid="chat-list"]', timeout=10000)

                chats = page.query_selector_all('[data-testid="chat-list"] [data-testid="chat-item"]')
                data = _load_data()
                new_messages = []

                for chat in chats[:10]:
                    try:
                        name_el = chat.query_selector('[data-testid="chat-list-name"]')
                        name = name_el.inner_text() if name_el else "Unknown"

                        preview_el = chat.query_selector('[data-testid="chat-list-preview"]')
                        preview = preview_el.inner_text() if preview_el else ""

                        time_el = chat.query_selector('[data-testid="chat-list-time"]')
                        msg_time = time_el.inner_text() if time_el else ""

                        msg_hash = f"{name}:{preview}:{msg_time}"
                        if msg_hash in data.get("seen_whatsapp", []):
                            continue

                        msg_obj = {
                            "id": f"wa_{len(data.get('seen_whatsapp', [])) + 1}",
                            "from": name,
                            "preview": preview,
                            "time": msg_time,
                            "received_at": datetime.now().isoformat(),
                            "type": "whatsapp",
                            "read": False,
                        }
                        new_messages.append(msg_obj)
                    except Exception:
                        continue

                _wa_fail_streak = 0
                return new_messages
            finally:
                browser.close()

    except Exception as e:
        _wa_fail_streak += 1
        if _wa_fail_streak >= _MAX_FAILS:
            _wa_disabled_until = time.time() + _BACKOFF_SECONDS
            print(
                f"[Notif] WhatsApp check paused for 1h after {_wa_fail_streak} "
                "failures (WhatsApp Web not logged in?)"
            )
        else:
            print(f"[Notif] WhatsApp check failed: {e}")
        return []


def check_instagram() -> list:
    """Check Instagram for new notifications using Playwright."""
    global _ig_fail_streak, _ig_disabled_until

    if time.time() < _ig_disabled_until:
        return []

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://www.instagram.com", timeout=30000)

                page.wait_for_selector('a[href="/accounts/activity/"]', timeout=10000)
                page.click('a[href="/accounts/activity/"]')

                page.wait_for_selector('[role="dialog"]', timeout=5000)
                items = page.query_selector_all('[role="dialog"] [role="button"]')

                data = _load_data()
                new_notifs = []

                for item in items[:10]:
                    try:
                        text = item.inner_text()
                        if not text:
                            continue

                        notif_hash = f"ig:{text[:50]}"
                        if notif_hash in data.get("seen_instagram", []):
                            continue

                        notif_obj = {
                            "id": f"ig_{len(data.get('seen_instagram', [])) + 1}",
                            "text": text,
                            "received_at": datetime.now().isoformat(),
                            "type": "instagram",
                            "read": False,
                        }
                        new_notifs.append(notif_obj)
                    except Exception:
                        continue

                return new_notifs
            finally:
                browser.close()

    except Exception as e:
        _ig_fail_streak += 1
        if _ig_fail_streak >= _MAX_FAILS:
            _ig_disabled_until = time.time() + _BACKOFF_SECONDS
            print(
                f"[Notif] Instagram check paused for 1h after {_ig_fail_streak} "
                "failures (not logged in?)"
            )
        else:
            print(f"[Notif] Instagram check failed: {e}")
        return []


def get_all_notifications() -> dict:
    """Get all unread notifications."""
    data = _load_data()

    emails = [e for e in data.get("emails", []) if not e.get("read", False)]
    whatsapp = [w for w in data.get("whatsapp", []) if not w.get("read", False)]
    instagram = [i for i in data.get("instagram", []) if not i.get("read", False)]

    return {
        "total": len(emails) + len(whatsapp) + len(instagram),
        "emails": emails,
        "whatsapp": whatsapp,
        "instagram": instagram,
        "last_updated": data.get("last_check", None),
    }


def mark_as_read(notif_type: str, notif_id: str) -> bool:
    """Mark a notification as read."""
    key = {"email": "emails", "whatsapp": "whatsapp", "instagram": "instagram"}[notif_type]
    with _lock:
        data = _load_data()
        for item in data.get(key, []):
            if item["id"] == notif_id:
                item["read"] = True
                _save_data(data)
                return True
        return False


def mark_all_read(notif_type: str = None) -> None:
    """Mark all notifications as read."""
    with _lock:
        data = _load_data()
        if notif_type:
            key = {"email": "emails", "whatsapp": "whatsapp", "instagram": "instagram"}[notif_type]
            for item in data.get(key, []):
                item["read"] = True
        else:
            for key in ["emails", "whatsapp", "instagram"]:
                for item in data.get(key, []):
                    item["read"] = True
        _save_data(data)


def briefing() -> str:
    """Generate notification briefing."""
    data = _load_data()
    emails = [e for e in data.get("emails", []) if not e.get("read", False)]
    whatsapp = [w for w in data.get("whatsapp", []) if not w.get("read", False)]
    instagram = [i for i in data.get("instagram", []) if not i.get("read", False)]

    lines = [f"Notifications Briefing ({datetime.now().strftime('%H:%M')})", ""]

    if emails:
        lines.append(f"Email ({len(emails)} new):")
        for e in emails[:5]:
            lines.append(f"  - {e['subject'][:50]} (from {e['from'][:30]})")
        lines.append("")

    if whatsapp:
        lines.append(f"WhatsApp ({len(whatsapp)} new):")
        for w in whatsapp[:5]:
            lines.append(f"  - {w['from']}: {w['preview'][:50]}")
        lines.append("")

    if instagram:
        lines.append(f"Instagram ({len(instagram)} new):")
        for i in instagram[:5]:
            lines.append(f"  - {i['text'][:50]}")
        lines.append("")

    if not emails and not whatsapp and not instagram:
        lines.append("No new notifications. All clear.")

    return "\n".join(lines)


def _background_check():
    """Background thread that checks notifications periodically."""
    global _running
    while _running:
        try:
            emails = check_emails()
            whatsapp = check_whatsapp()
            instagram = check_instagram()

            with _lock:
                data = _load_data()

                if emails:
                    data.setdefault("emails", []).extend(emails)
                    for e in emails:
                        data.setdefault("seen_email_ids", []).append(e["id"])

                if whatsapp:
                    data.setdefault("whatsapp", []).extend(whatsapp)
                    for w in whatsapp:
                        data.setdefault("seen_whatsapp", []).append(f"{w['from']}:{w['preview']}:{w['time']}")

                if instagram:
                    data.setdefault("instagram", []).extend(instagram)
                    for i in instagram:
                        data.setdefault("seen_instagram", []).append(f"ig:{i['text'][:50]}")

                data["last_check"] = datetime.now().isoformat()
                _save_data(data)

        except Exception as e:
            print(f"[Notif] Background check error: {e}")

        time.sleep(300)


def start_monitoring():
    """Start background notification monitoring."""
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_background_check, daemon=True)
    _thread.start()
    print("[Notif] Notification monitoring started")


def stop_monitoring():
    """Stop background notification monitoring."""
    global _running
    _running = False
    print("[Notif] Notification monitoring stopped")
