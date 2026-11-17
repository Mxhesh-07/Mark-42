"""Tactical sitrep for ULTRON-LITE / FRIDAY style."""

from __future__ import annotations

import os
import platform
import time
from datetime import datetime


def sitrep() -> str:
    lines = []
    lines.append(f"[SITREP] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")
    problems: list[str] = []
    warnings: list[str] = []
    measured = False
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        measured = True
        lines.append(f"CPU: {cpu}% | RAM: {mem.percent}% ({mem.used // (1024**3)}GB/{mem.total // (1024**3)}GB)")
        lines.append(f"Disk: {disk.percent}% ({disk.used // (1024**3)}GB used, {disk.free // (1024**3)}GB free)")
        lines.append(f"Boot: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(psutil.boot_time()))}")
        for name, value in (("CPU", cpu), ("RAM", mem.percent), ("disk", disk.percent)):
            if value >= 90:
                problems.append(f"{name} at {value}%")
            elif value >= 75:
                warnings.append(f"{name} at {value}%")
    except Exception as e:
        lines.append(f"Sys stats unavailable: {e}")
    try:
        proc_count = len(os.listdir('/proc')) if os.path.exists('/proc') else None
        if proc_count is None:
            import psutil as p
            proc_count = len(p.pids())
        lines.append(f"Processes: {proc_count}")
    except Exception:
        pass
    # Never claim health that was not measured, and do not call a loaded machine
    # nominal: a sitrep that only knows "fine" is trusted when it should not be.
    if not measured:
        lines.append("Status: UNKNOWN (metrics unavailable)")
    elif problems:
        lines.append("Status: ATTENTION - " + "; ".join(problems))
    elif warnings:
        lines.append("Status: ELEVATED - " + "; ".join(warnings))
    else:
        lines.append("Status: ALL SYSTEMS NOMINAL")
    return "\n".join(lines)
