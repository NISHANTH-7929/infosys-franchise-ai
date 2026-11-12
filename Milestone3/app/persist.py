"""Keeps the app database (users, tickets, approvals and every saved Copilot chat) safe on Google Drive.
The live SQLite file stays on the fast local disk; a consistent copy is written to Drive (SQLite online-backup, temp file then atomic rename)
every few minutes, a few seconds after each chat is saved, and at shutdown. On the next start, if the local database is gone (Colab runtime reset),
the Drive copy is restored before the app opens it. Set DRIVE_DB_DIR to the Drive folder; unset = disabled."""
import os, shutil, sqlite3, threading, time, json
import config

DIR = os.environ.get("DRIVE_DB_DIR", "").strip()
EVERY = int(os.environ.get("DB_BACKUP_EVERY", "180"))
_state = {"last": None, "ok": None, "err": "", "size": 0, "restored": False, "n": 0}
_lock = threading.Lock(); _timer = [None]; _stop = threading.Event()
_EXTRA = (".jwt_secret", ".admin_initial")

def enabled(): return bool(DIR)
def _target(): return os.path.join(DIR, os.path.basename(config.DB_PATH))
def _sig():
    try: return tuple(os.stat(config.DB_PATH + s).st_mtime_ns if os.path.exists(config.DB_PATH + s) else 0 for s in ("", "-wal"))
    except Exception: return None

def restore():
    """Call before the database is opened. Copies the Drive backup back when the local file is missing."""
    if not enabled(): return False
    try:
        t = _target()
        if os.path.exists(t) and not os.path.exists(config.DB_PATH):
            os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
            shutil.copy2(t, config.DB_PATH)
            for x in _EXTRA:
                s = os.path.join(DIR, x)
                if os.path.exists(s) and not os.path.exists(os.path.join(config.DATA_DIR, x)): shutil.copy2(s, os.path.join(config.DATA_DIR, x))
            _state["restored"] = True; print("persist: restored database from", t)
            return True
    except Exception as e: _state["err"] = repr(e)[:160]; print("persist restore failed:", repr(e))
    return False

def backup(force=False):
    if not enabled() or not os.path.exists(config.DB_PATH): return False
    with _lock:
        sig = _sig()
        if not force and sig is not None and sig == _state.get("sig"): return True
        try:
            os.makedirs(DIR, exist_ok=True); t = _target(); tmp = t + ".tmp"
            if os.path.exists(t) and (not os.path.exists(t + ".prev") or time.time() - os.path.getmtime(t + ".prev") > 1800):
                try: shutil.copy2(t, t + ".prev"); os.utime(t + ".prev", None)        # an older generation (refreshed at most every 30 min), in case the latest copy is ever bad
                except Exception: pass
            src = sqlite3.connect(config.DB_PATH, timeout=30); dst = sqlite3.connect(tmp)
            try: src.backup(dst)
            finally: dst.close(); src.close()
            os.replace(tmp, t)
            for x in _EXTRA:
                s = os.path.join(config.DATA_DIR, x)
                if os.path.exists(s): shutil.copy2(s, os.path.join(DIR, x))
            _state.update(last=time.strftime("%Y-%m-%d %H:%M:%S"), ok=True, err="", size=os.path.getsize(t), sig=sig, n=_state["n"] + 1)
            return True
        except Exception as e:
            _state.update(ok=False, err=repr(e)[:160]); print("persist backup failed:", repr(e)); return False

def soon(delay=5):
    """Debounced backup (used after a chat is saved)."""
    if not enabled(): return
    if _timer[0] and _timer[0].is_alive(): return
    _timer[0] = threading.Timer(delay, lambda: backup()); _timer[0].daemon = True; _timer[0].start()

def _loop():
    while not _stop.wait(EVERY): backup()

def start():
    if not enabled(): return
    threading.Thread(target=_loop, daemon=True).start(); threading.Timer(15, lambda: backup(True)).start()

def stop(): _stop.set(); backup()

def status():
    """(ok, detail) for the System check page."""
    if not enabled(): return None, "Not enabled. In the launcher cell keep PERSIST = True so the database (chats, users, tickets) is copied to Google Drive."
    if _state["ok"] is False: return False, "Last backup failed: " + _state["err"]
    if not _state["last"]: return None, f"Waiting for the first backup to {DIR} (runs ~15 s after start)."
    return True, f"{_state['n']} backup(s), last at {_state['last']} IST, {_state['size'] / 2**20:.1f} MB in {DIR}" + (" (restored from Drive at start)" if _state["restored"] else "")
