"""
J.A.R.V.I.S. — Cloud Monitor
Runs on Oracle Cloud 24/7. Monitors email, sends WhatsApp alerts.
No UI, no voice — just pure monitoring.
"""

import sys
import os
import json
import time
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from smart_alerts import start_monitoring, get_status, check_emails_and_alert
from notifications import briefing, get_all_notifications
from work_assistant import daily_briefing


def run_cloud_jarvis():
    print("[Cloud JARVIS] Starting...")
    print(f"[Cloud JARVIS] Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    config_path = BASE_DIR / "config" / "alert_config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        phone = config.get("user_phone", "")
        enabled = config.get("enabled", False)
        print(f"[Cloud JARVIS] Phone: {phone}")
        print(f"[Cloud JARVIS] Alerts enabled: {enabled}")

        if enabled and phone:
            start_monitoring()
            print("[Cloud JARVIS] Email monitoring active")
        else:
            print("[Cloud JARVIS] Alerts disabled — configure alert_config.json")
    else:
        print("[Cloud JARVIS] No config found — running in manual mode")

    print("[Cloud JARVIS] Cloud JARVIS is online, sir.")
    print("[Cloud JARVIS] Press Ctrl+C to shutdown")

    try:
        while True:
            time.sleep(60)
            status = get_status()
            print(f"[Cloud JARVIS] Status: {status['total_alerts_sent']} alerts sent")
    except KeyboardInterrupt:
        print("\n[Cloud JARVIS] Shutting down, sir.")
        sys.exit(0)


if __name__ == "__main__":
    run_cloud_jarvis()
