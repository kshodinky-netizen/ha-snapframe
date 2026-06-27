#!/usr/bin/env python3
"""
Zdieľaný stav medzi watcher.py a webserver.py.
Oba moduly bežia v rovnakom procese (webserver ako daemon vlákno).
"""

import threading
import time as _time

_lock = threading.Lock()

last_scan_time = None    # float – unix timestamp posledného skenu
next_scan_time = None    # float – unix timestamp nasledujúceho skenu
converted_total = 0      # int   – celkový počet skonvertovaných od štartu
_scan_requested = False  # bool  – flag pre manuálny trigger


def request_scan():
    """Vyžiada okamžitý scan (nastavený cez /scan endpoint)."""
    global _scan_requested
    with _lock:
        _scan_requested = True


def consume_scan_request():
    """Ak bol vyžiadaný scan, resetuj flag a vráť True."""
    global _scan_requested
    with _lock:
        if _scan_requested:
            _scan_requested = False
            return True
        return False


def update_after_scan(converted: int, next_scan: float):
    """Watcher zavolá po každom skene."""
    global last_scan_time, next_scan_time, converted_total
    with _lock:
        last_scan_time = _time.time()
        next_scan_time = next_scan
        converted_total += converted


def get_status() -> dict:
    with _lock:
        return {
            "last_scan_time": last_scan_time,
            "next_scan_time": next_scan_time,
            "converted_total": converted_total,
            "scan_pending": _scan_requested,
        }

# ── Progres pregenerácie thumbnailov ─────────────────────────────────────────
thumb_total   = 0    # celkový počet fotiek na spracovanie
thumb_done    = 0    # hotové thumbnaile
thumb_running = False  # práve beží pregenerácia


def thumb_start(total: int):
    global thumb_total, thumb_done, thumb_running
    with _lock:
        thumb_total   = total
        thumb_done    = 0
        thumb_running = True


def thumb_progress(done: int):
    global thumb_done
    with _lock:
        thumb_done = done


def thumb_finish():
    global thumb_running
    with _lock:
        thumb_running = False


def get_thumb_status() -> dict:
    with _lock:
        return {
            "running": thumb_running,
            "total":   thumb_total,
            "done":    thumb_done,
        }
