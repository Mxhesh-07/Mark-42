"""
J.A.R.V.I.S. — Enterprise Tools Module
Task Automation, Email Drafting, News Monitoring, Stock/Crypto Tracking, Client CRM
"""

import copy
import json
import time
import threading
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from pathlib import Path
from datetime import datetime, timedelta
from threading import RLock

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "enterprise_data.json"
_lock = RLock()

_DEFAULT = {
    "automations": [],
    "email_drafts": [],
    "email_sent": [],
    "news_topics": [],
    "news_alerts": [],
    "watchlist": [],
    "price_alerts": [],
    "clients": [],
    "deals": [],
}


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively overlay non-default keys/values onto a default structure."""
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _locked(fn):
    """Hold the module lock across a full load→modify→save mutation."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return wrapper


def _load_data() -> dict:
    data = copy.deepcopy(_DEFAULT)
    with _lock:
        if not DATA_PATH.exists():
            return data
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                _deep_merge(data, loaded)
            return data
        except Exception:
            return copy.deepcopy(_DEFAULT)


def _save_data(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# === Task Automation ===

@_locked
def create_automation(name: str, trigger: str, actions: list) -> dict:
    data = _load_data()
    automation = {
        "id": f"auto_{len(data['automations']) + 1}",
        "name": name,
        "trigger": trigger,
        "actions": actions,
        "active": True,
        "created": datetime.now().isoformat(),
        "last_run": None,
    }
    data["automations"].append(automation)
    _save_data(data)
    return automation


def get_automations(active_only: bool = False) -> list:
    data = _load_data()
    if active_only:
        return [a for a in data["automations"] if a["active"]]
    return data["automations"]


@_locked
def toggle_automation(auto_id: str) -> bool:
    data = _load_data()
    for a in data["automations"]:
        if a["id"] == auto_id:
            a["active"] = not a["active"]
            _save_data(data)
            return True
    return False


@_locked
def run_automation(auto_id: str) -> dict:
    data = _load_data()
    for a in data["automations"]:
        if a["id"] == auto_id:
            a["last_run"] = datetime.now().isoformat()
            _save_data(data)
            return {"status": "completed", "automation": a["name"], "actions": len(a["actions"])}
    return {"status": "not_found"}


# === Email Drafting ===

@_locked
def draft_email(to: str, subject: str, body: str) -> dict:
    data = _load_data()
    draft = {
        "id": f"draft_{len(data['email_drafts']) + 1}",
        "to": to,
        "subject": subject,
        "body": body,
        "status": "draft",
        "created": datetime.now().isoformat(),
    }
    data["email_drafts"].append(draft)
    _save_data(data)
    return draft


def get_email_drafts() -> list:
    data = _load_data()
    return data["email_drafts"]


def _email_config_path() -> Path:
    return BASE_DIR / "config" / "email_config.json"


def _load_email_config() -> dict:
    path = _email_config_path()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_password(password: str) -> str:
    """Gmail shows app passwords as 'abcd efgh ijkl mnop' — strip spaces."""
    return "".join(str(password).split())


def configure_email(email: str, app_password: str, imap_server: str = None, smtp_server: str = None) -> dict:
    """Save email credentials. Use a Gmail App Password (16 chars), not your normal password."""
    email = (email or "").strip()
    app_password = _normalize_password(app_password)
    if not email or "@" not in email:
        return {"ok": False, "error": "Invalid email address."}
    if not app_password:
        return {"ok": False, "error": "Password / app password is required."}

    config = {
        "email": email,
        "password": app_password,
        "provider": "gmail" if email.lower().endswith("gmail.com") else "generic",
        "server": imap_server or "imap.gmail.com",
        "imap_server": imap_server or "imap.gmail.com",
        "imap_port": 993,
        "smtp_server": smtp_server or "smtp.gmail.com",
        "smtp_port": 465,
    }
    _email_config_path().parent.mkdir(parents=True, exist_ok=True)
    with open(_email_config_path(), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    ok, message = test_email_connection()
    note = "Email configured and verified." if ok else f"Saved, but login test failed: {message}"
    if config["provider"] == "gmail" and len(app_password) != 16:
        note += " (Gmail app passwords are 16 characters — double-check yours.)"
    return {"ok": ok, "note": note, "email": email}


def test_email_connection() -> tuple:
    """Test IMAP + SMTP login. Returns (ok, message)."""
    try:
        import imaplib
        try:
            config = _load_email_config()
        except Exception as e:
            return False, f"No email config: {e}"

        email_addr = config.get("email", "")
        password = _normalize_password(config.get("password", ""))
        imap_host = config.get("imap_server") or config.get("server") or "imap.gmail.com"
        smtp_host = config.get("smtp_server") or "smtp.gmail.com"

        if not email_addr or not password:
            return False, "Email or password missing in config/email_config.json."

        try:
            m = imaplib.IMAP4_SSL(imap_host, config.get("imap_port", 993), timeout=20)
            m.login(email_addr, password)
            m.logout()
        except Exception as e:
            return False, f"IMAP login failed: {e}"

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, config.get("smtp_port", 465), context=context, timeout=20) as server:
                server.login(email_addr, password)
        except Exception as e:
            return False, f"SMTP login failed: {e}"

        return True, "Email connection OK (IMAP + SMTP)."
    except Exception as e:
        return False, f"Email test error: {e}"


def send_email(to: str, subject: str, body: str) -> tuple:
    """Send an email. Returns (ok, message)."""
    try:
        config = _load_email_config()
        email_addr = config.get("email", "")
        password = _normalize_password(config.get("password", ""))
        smtp_host = config.get("smtp_server") or "smtp.gmail.com"
        smtp_port = config.get("smtp_port", 465)

        if not email_addr or not password:
            return False, "Email not configured — set it in config/email_config.json."
        if not to:
            return False, "No recipient given."

        msg = MIMEMultipart()
        msg["From"] = email_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=30) as server:
            server.login(email_addr, password)
            server.sendmail(email_addr, to, msg.as_string())

        with _lock:
            data = _load_data()
            data["email_sent"].append({
                "to": to,
                "subject": subject,
                "sent_at": datetime.now().isoformat(),
            })
            _save_data(data)
        return True, f"Email sent to {to}."
    except Exception as e:
        print(f"[Email] Send failed: {e}")
        return False, f"Email send failed: {e}"


# === News Monitoring ===

@_locked
def add_news_topic(topic: str, keywords: list) -> dict:
    data = _load_data()
    entry = {
        "id": f"news_{len(data['news_topics']) + 1}",
        "topic": topic,
        "keywords": keywords,
        "active": True,
        "added": datetime.now().isoformat(),
    }
    data["news_topics"].append(entry)
    _save_data(data)
    return entry


def get_news_topics() -> list:
    data = _load_data()
    return data["news_topics"]


@_locked
def check_news() -> list:
    try:
        from duckduckgo_search import DDGS

        data = _load_data()
        new_alerts = []

        for topic in data["news_topics"]:
            if not topic["active"]:
                continue

            with DDGS() as ddgs:
                results = ddgs.text(topic["topic"], max_results=5)
                for r in results:
                    alert = {
                        "topic": topic["topic"],
                        "title": r["title"],
                        "url": r["href"],
                        "date": datetime.now().isoformat(),
                    }
                    data["news_alerts"].append(alert)
                    new_alerts.append(alert)

        _save_data(data)
        return new_alerts
    except Exception as e:
        print(f"[News] Check failed: {e}")
        return []


def get_news_alerts(limit: int = 10) -> list:
    data = _load_data()
    return data["news_alerts"][-limit:]


# === Stock/Crypto Tracking ===

@_locked
def add_to_watchlist(symbol: str, name: str, alert_price: float = None) -> dict:
    data = _load_data()
    entry = {
        "id": f"watch_{len(data['watchlist']) + 1}",
        "symbol": symbol,
        "name": name,
        "alert_price": alert_price,
        "added": datetime.now().isoformat(),
    }
    data["watchlist"].append(entry)
    _save_data(data)
    return entry


def get_watchlist() -> list:
    data = _load_data()
    return data["watchlist"]


def get_stock_price(symbol: str) -> dict:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return {
            "symbol": symbol,
            "price": info.get("currentPrice", 0),
            "change": info.get("regularMarketChangePercent", 0),
            "currency": info.get("currency", "USD"),
        }
    except Exception:
        try:
            import requests
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
            r = requests.get(url, timeout=10)
            data = r.json()
            price = data.get(symbol, {}).get("usd", 0)
            return {"symbol": symbol, "price": price, "change": 0, "currency": "USD"}
        except Exception:
            return {"symbol": symbol, "price": 0, "change": 0, "currency": "USD"}


def check_price_alerts() -> list:
    data = _load_data()
    triggered = []
    for item in data["watchlist"]:
        if not item["alert_price"]:
            continue
        price_info = get_stock_price(item["symbol"])
        current = price_info["price"]
        if current >= item["alert_price"]:
            triggered.append({
                "symbol": item["symbol"],
                "name": item["name"],
                "current_price": current,
                "alert_price": item["alert_price"],
                "date": datetime.now().isoformat(),
            })
    return triggered


# === Client CRM ===

@_locked
def add_client(name: str, company: str, email: str, phone: str = "", value: float = 0) -> dict:
    data = _load_data()
    client = {
        "id": f"client_{len(data['clients']) + 1}",
        "name": name,
        "company": company,
        "email": email,
        "phone": phone,
        "value": value,
        "status": "lead",
        "added": datetime.now().isoformat(),
        "last_contact": None,
    }
    data["clients"].append(client)
    _save_data(data)
    return client


def get_clients(status: str = None) -> list:
    data = _load_data()
    if status:
        return [c for c in data["clients"] if c["status"] == status]
    return data["clients"]


@_locked
def update_client_status(client_id: str, status: str) -> bool:
    valid = ["lead", "contacted", "proposal", "negotiation", "won", "lost"]
    if status not in valid:
        return False
    data = _load_data()
    for c in data["clients"]:
        if c["id"] == client_id:
            c["status"] = status
            c["last_contact"] = datetime.now().isoformat()
            _save_data(data)
            return True
    return False


@_locked
def add_deal(client_name: str, title: str, value: float, stage: str = "lead") -> dict:
    data = _load_data()
    deal = {
        "id": f"deal_{len(data['deals']) + 1}",
        "client": client_name,
        "title": title,
        "value": value,
        "stage": stage,
        "created": datetime.now().isoformat(),
    }
    data["deals"].append(deal)
    _save_data(data)
    return deal


def get_deals(stage: str = None) -> list:
    data = _load_data()
    if stage:
        return [d for d in data["deals"] if d["stage"] == stage]
    return data["deals"]


def get_crm_summary() -> dict:
    data = _load_data()
    clients = data["clients"]
    deals = data["deals"]

    pipeline = {}
    for stage in ["lead", "contacted", "proposal", "negotiation", "won"]:
        pipeline[stage] = len([d for d in deals if d["stage"] == stage])

    total_value = sum(d["value"] for d in deals)
    won_value = sum(d["value"] for d in deals if d["stage"] == "won")

    return {
        "total_clients": len(clients),
        "active_deals": len(deals),
        "pipeline": pipeline,
        "total_pipeline_value": total_value,
        "won_value": won_value,
        "win_rate": len([d for d in deals if d["stage"] == "won"]) / max(len(deals), 1) * 100,
    }
