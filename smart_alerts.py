"""
J.A.R.V.I.S. — Smart Alert System
Monitors emails and sends WhatsApp voice alerts when important ones arrive.
100% free — no Twilio needed.
"""

import json
import time
import threading
import subprocess
import tempfile
import os
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
ALERT_CONFIG_PATH = BASE_DIR / "config" / "alert_config.json"
ALERT_LOG_PATH = BASE_DIR / "alert_log.json"

IMPORTANT_KEYWORDS = [
    "client", "project", "proposal", "contract", "meeting",
    "urgent", "asap", "deadline", "payment", "invoice",
    "website", "build", "develop", "startup", "invest",
    "funding", "partnership", "collaboration", "offer",
    "interview", "hire", "consult", "deal", "agreement",
]

# High-signal phrases: enough on their own (in the SUBJECT) to alert, even
# from a no-reply sender. Kept precise — vague words like "hired"/"interview"
# appear in job-spam and newsletters, so those live in IMPORTANT_KEYWORDS.
STRONG_KEYWORDS = [
    "urgent", "asap", "action required", "immediate action",
    "deadline", "overdue", "past due",
    "invoice", "payment due", "payment failed", "refund",
    "contract", "proposal", "agreement", "termination",
    "offer letter", "job offer",
    "verification code", "security alert", "password reset",
    "suspicious login", "unauthorized", "otp",
]

# Bulk / marketing mail should never raise an "important email" alert.
BULK_SUBJECT_MARKERS = [
    "newsletter", "weekly", "digest", "unsubscribe", "% off", "off sitewide",
    "sitewide", "sale", "promo", "limited time", "exclusive offer for you",
    "deal of the day", "flash sale", "don't miss", "last chance",
    "webinar", "we miss you", "come back", "preorder", "giveaway",
]
BULK_SENDER_MARKERS = [
    "no-reply", "noreply", "donotreply", "do-not-reply", "newsletter",
    "mailer", "marketing@", "promo@", "news@", "updates@",
    "notifications@", "info@", "hello@", "support@", "team@",
]

RUNNING = False
_thread = None
_lock = threading.RLock()

# WhatsApp alert circuit-breaker — stop hammering when WhatsApp Web isn't
# logged in (every attempt launches a headless browser and times out).
_wa_fail_streak = 0
_wa_disabled = False
_WA_MAX_FAILS = 3


def _load_config() -> dict:
    if not ALERT_CONFIG_PATH.exists():
        return {
            "user_phone": "",
            "enabled": False,
            "whatsapp_on_important": True,
            "toast_on_important": True,
            "check_interval": 60,
        }
    try:
        with open(ALERT_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(config: dict) -> None:
    ALERT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def _load_alert_log() -> list:
    if not ALERT_LOG_PATH.exists():
        return []
    try:
        with open(ALERT_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_alert_log(log: list) -> None:
    with open(ALERT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


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


def is_important_email(subject: str, sender: str, body: str = "") -> tuple:
    """
    Decide whether an email deserves an alert.

    Only the SUBJECT is scored — scanning the body matched generic words like
    "build"/"develop"/"offer" in every newsletter. Bulk mail is filtered out
    first so promos never trigger alerts.
    """
    subject_l = (subject or "").lower()
    sender_l = (sender or "").lower()

    # Obvious promo/subject markers → never alert (even if it says "urgent").
    if any(m in subject_l for m in BULK_SUBJECT_MARKERS):
        return False, ""

    # Strong signal in the subject → alert, even from a no-reply sender
    # (banks and security systems use no-reply for "action required" mail).
    for keyword in STRONG_KEYWORDS:
        if keyword in subject_l:
            return True, keyword

    # Bulk sender with no strong signal → skip (job alerts, newsletters…).
    if any(m in sender_l for m in BULK_SENDER_MARKERS):
        return False, ""

    # Weaker keyword, still subject-only.
    for keyword in IMPORTANT_KEYWORDS:
        if keyword in subject_l:
            return True, keyword

    return False, ""


def send_toast_notification(title: str, message: str) -> None:
    """Send Windows toast notification."""
    try:
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(title, message, duration=10, threaded=True)
    except Exception as e:
        print(f"[Alert] Toast failed: {e}")


def send_whatsapp_voice_alert(phone_number: str, message: str) -> bool:
    """Send WhatsApp voice message via Playwright (free)."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://web.whatsapp.com", timeout=30000)

                page.wait_for_selector('[data-testid="chat-list"]', timeout=15000)

                search = page.query_selector('[data-testid="search-input"]')
                if search:
                    search.click()
                    search.fill(phone_number)
                    page.wait_for_timeout(2000)

                    chat = page.query_selector('[data-testid="chat-item"]')
                    if chat:
                        chat.click()
                        page.wait_for_timeout(1000)

                        attach = page.query_selector('[data-testid="attach-button"]')
                        if attach:
                            attach.click()
                            page.wait_for_timeout(500)

                            voice_option = page.query_selector('[data-testid="audio-option"]')
                            if voice_option:
                                voice_option.click()
                                page.wait_for_timeout(500)

                                record_btn = page.query_selector('[data-testid="record-button"]')
                                if record_btn:
                                    record_btn.click()
                                    page.wait_for_timeout(3000)
                                    stop_btn = page.query_selector('[data-testid="stop-button"]')
                                    if stop_btn:
                                        stop_btn.click()
                                        page.wait_for_timeout(500)
                                        send_btn = page.query_selector('[data-testid="send-button"]')
                                        if send_btn:
                                            send_btn.click()
                                            page.wait_for_timeout(2000)
                                            return True

                return False
            finally:
                browser.close()

    except Exception as e:
        print(f"[Alert] WhatsApp voice failed: {e}")
        return False


def send_whatsapp_text_alert(phone_number: str, message: str) -> bool:
    """Send WhatsApp text message via Playwright (free, backup)."""
    global _wa_fail_streak, _wa_disabled

    if _wa_disabled or not phone_number:
        return False

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://web.whatsapp.com", timeout=30000)

                page.wait_for_selector('[data-testid="chat-list"]', timeout=15000)

                search = page.query_selector('[data-testid="search-input"]')
                if search:
                    search.click()
                    search.fill(phone_number)
                    page.wait_for_timeout(2000)

                    chat = page.query_selector('[data-testid="chat-item"]')
                    if chat:
                        chat.click()
                        page.wait_for_timeout(1000)

                        input_box = page.query_selector('[data-testid="chat-input"]')
                        if input_box:
                            input_box.click()
                            input_box.type(message)
                            page.wait_for_timeout(500)
                            send_btn = page.query_selector('[data-testid="send-button"]')
                            if send_btn:
                                send_btn.click()
                                page.wait_for_timeout(2000)
                                _wa_fail_streak = 0
                                return True

                return False
            finally:
                browser.close()

    except Exception as e:
        _wa_fail_streak += 1
        if _wa_fail_streak >= _WA_MAX_FAILS:
            _wa_disabled = True
            print(
                f"[Alert] WhatsApp alerts disabled after {_wa_fail_streak} "
                "failed attempts (WhatsApp Web not logged in?). "
                "Re-enable via the alerts phone setup."
            )
        else:
            print(f"[Alert] WhatsApp text failed: {e}")
        return False


def alert_important_email(subject: str, sender: str, body: str = "") -> None:
    """Alert user about important email via WhatsApp + toast."""
    config = _load_config()

    is_important, keyword = is_important_email(subject, sender, body)
    if not is_important:
        return

    message = f"Important email from {sender}: {subject}"

    if config.get("toast_on_important", True):
        send_toast_notification("JARVIS — Important Email", message)

    if config.get("whatsapp_on_important", True) and config.get("user_phone"):
        wa_msg = f"JARVIS Alert: Important email from {sender}. Subject: {subject}. Keyword: {keyword}."
        send_whatsapp_text_alert(config["user_phone"], wa_msg)

    with _lock:
        log = _load_alert_log()
        log.append({
            "sender": sender,
            "subject": subject,
            "keyword": keyword,
            "alerted_at": datetime.now().isoformat(),
            "method": "whatsapp+toast",
        })
        _save_alert_log(log)

    print(f"[Alert] Important email: {subject}")


def check_emails_and_alert() -> list:
    """Check emails and alert on important ones."""
    try:
        import imaplib
        import email
        from email.header import decode_header

        with open(BASE_DIR / "config" / "email_config.json", "r", encoding="utf-8") as f:
            email_config = json.load(f)

        password = "".join(str(email_config.get("password", "")).split())
        host = email_config.get("imap_server") or email_config.get("server") or "imap.gmail.com"
        mail = imaplib.IMAP4_SSL(host, email_config.get("imap_port", 993))
        mail.login(email_config["email"], password)
        mail.select("inbox")

        _, messages = mail.search(None, "UNSEEN")
        email_ids = messages[0].split()

        alerted = set(_load_config().get("alerted_email_ids", []))
        important_emails = []
        newly_alerted = []

        for eid in email_ids[-20:]:
            _, msg_data = mail.fetch(eid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            subject = _decode_subject(msg.get("Subject"))

            sender = msg.get("From")

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode()
                        except Exception:
                            pass
                        break
            else:
                try:
                    body = msg.get_payload(decode=True).decode()
                except Exception:
                    pass

            key = (msg.get("Message-ID") or "").strip() or f"{sender}|{subject}|{msg.get('Date')}"
            if key in alerted:
                continue

            important, keyword = is_important_email(subject, sender, body)
            if important:
                important_emails.append({
                    "subject": subject,
                    "sender": sender,
                    "body": body[:500],
                    "date": msg["Date"],
                })
                alert_important_email(subject, sender, body)
                newly_alerted.append(key)

        mail.logout()

        if newly_alerted:
            with _lock:
                config = _load_config()
                config["alerted_email_ids"] = (config.get("alerted_email_ids", []) + newly_alerted)[-500:]
                _save_config(config)

        return important_emails

    except Exception as e:
        print(f"[Alert] Email check failed: {e}")
        return []


def _background_monitor():
    """Background thread that monitors emails."""
    global RUNNING
    config = _load_config()
    interval = config.get("check_interval", 60)

    while RUNNING:
        try:
            check_emails_and_alert()
        except Exception as e:
            print(f"[Alert] Monitor error: {e}")

        time.sleep(interval)


def start_monitoring():
    """Start background email monitoring."""
    global RUNNING, _thread
    if RUNNING:
        return
    RUNNING = True
    _thread = threading.Thread(target=_background_monitor, daemon=True)
    _thread.start()
    print("[Alert] Smart alert monitoring started")


def stop_monitoring():
    """Stop background email monitoring."""
    global RUNNING
    RUNNING = False
    print("[Alert] Smart alert monitoring stopped")


def configure(user_phone: str) -> dict:
    """Configure smart alerts (100% free)."""
    with _lock:
        existing = _load_config()
        config = {
            "user_phone": user_phone,
            "enabled": True,
            "whatsapp_on_important": True,
            "toast_on_important": True,
            "check_interval": 60,
        }
        if "alerted_email_ids" in existing:
            config["alerted_email_ids"] = existing["alerted_email_ids"]
        _save_config(config)
        return config


def get_status() -> dict:
    """Get smart alert status."""
    config = _load_config()
    log = _load_alert_log()
    return {
        "enabled": config.get("enabled", False),
        "whatsapp_on_important": config.get("whatsapp_on_important", True),
        "toast_on_important": config.get("toast_on_important", True),
        "check_interval": config.get("check_interval", 60),
        "total_alerts_sent": len(log),
        "last_alert": log[-1] if log else None,
    }
