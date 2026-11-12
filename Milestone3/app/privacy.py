"""Retention, PII inventory, masking and data-subject requests (export / erase)."""
import re, json, time, threading, datetime, hashlib
import pandas as pd
import live_engine as LE
from config import KIND
# table -> (timestamp column, default days kept). Only operational history is purged; master data (outlets, ports, ...) is never deleted by policy.
RETENTION = {"sales": ("ts", 730), "attendance": ("ts", 365), "feedback": ("date", 730), "feed_log": ("ts", 180), "feed_rejects": ("ts", 90), "live_events": ("ts", 30), "agent_runs": ("ts", 90),
             "decisions": ("ts", 180), "audit_log": ("ts", 1095), "alerts": ("date", 365), "weather_risks": (None, 0), "purchase_orders": ("ts", 730), "quote_requests": ("ts", 730)}
PII = {"Franchise": [("staff", "name", "Employee name", "Role-masked"), ("staff", "salary", "Salary", "Role-masked"), ("staff", "age", "Age", "Admin/Owner only"), ("feedback", "comment", "Customer free text (emails and phones auto-redacted)", "Redacted at ingest"),
                     ("app_users", "email", "Login email", "Erasable"), ("customers_fr", "customer_id", "Customer spend profile (pseudonymous id)", "Pseudonymous"), ("audit_log", "actor", "Who did what", "Anonymised on erase")],
       "Freight": [("customers", "name", "Customer company", "Business data"), ("app_users", "email", "Login email", "Erasable"), ("users", "email", "Login email", "Erasable"), ("quote_requests", "customer_id", "Requester id", "Pseudonymous"), ("audit_log", "actor", "Who did what", "Anonymised on erase")]}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"); PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)")
def redact(t):
    return PHONE.sub("[phone]", EMAIL.sub("[email]", t)) if isinstance(t, str) else t
def policy():
    o = LE.get_state("retention", {}) or {}; return {t: int(o.get(t, d)) for t, (c, d) in RETENTION.items() if c}
def _exists(c, t): return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None
def purge(dry=True, actor="system"):
    out = []; pol = policy()
    with LE._DB_LOCK:
        c = LE.conn()
        for t, days in pol.items():
            col = RETENTION[t][0]
            if not _exists(c, t): continue
            cut = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec="seconds"); cutd = cut[:10]
            q = f"FROM {t} WHERE {col} IS NOT NULL AND {col} < ?"
            n = c.execute(f"SELECT COUNT(*) {q}", (cut if col != 'date' else cutd,)).fetchone()[0]
            if n and not dry and t != "audit_log": c.execute(f"DELETE {q}", (cut if col != 'date' else cutd,))
            elif n and not dry: c.execute(f"DELETE {q}", (cut,))
            out.append({"table": t, "keep_days": days, "older_rows": int(n), "deleted": 0 if dry else int(n)})
        if not dry:
            c.commit()
    if not dry: LE.audit(actor, "retention_purge", "all", json.dumps({r["table"]: r["deleted"] for r in out if r["deleted"]}))
    return out
def _hash(s): return "erased-" + hashlib.sha256(str(s).encode()).hexdigest()[:10]
def export_subject(key):
    """Everything held about one person: staff id (STF-/EMP-), or a login email."""
    key = str(key).strip(); data = {}
    with LE._DB_LOCK:
        c = LE.conn()
        def grab(t, col, cols="*"):
            if not _exists(c, t): return
            df = pd.read_sql_query(f"SELECT {cols} FROM {t} WHERE {col}=?", c, params=(key,))
            if len(df): data[t] = json.loads(df.to_json(orient="records"))
        if "@" in key:
            grab("app_users", "email", "email, username, role, status, created, last_login"); grab("user_prefs", "email"); grab("user_scope", "email"); grab("audit_log", "actor")
        else:
            grab("staff", "staff_id"); grab("attendance", "staff_id"); grab("customers_fr", "customer_id"); grab("audit_log", "target")
    return data
def erase_subject(key, actor):
    key = str(key).strip(); n = {}
    with LE._DB_LOCK:
        c = LE.conn()
        if "@" in key:
            for t in ("user_prefs", "user_scope"):
                if _exists(c, t): n[t] = c.execute(f"DELETE FROM {t} WHERE email=?", (key,)).rowcount
            if _exists(c, "app_users"): n["app_users"] = c.execute("DELETE FROM app_users WHERE email=?", (key,)).rowcount
            if _exists(c, "users"): n["users"] = c.execute("DELETE FROM users WHERE email=?", (key,)).rowcount
            n["audit_log"] = c.execute("UPDATE audit_log SET actor=? WHERE actor=?", (_hash(key), key)).rowcount
        else:
            if _exists(c, "staff"): n["staff"] = c.execute("UPDATE staff SET name='Erased', salary=NULL, age=NULL WHERE staff_id=?", (key,)).rowcount
        c.commit()
    LE.audit(actor, "dsar_erase", _hash(key), json.dumps(n)); return n
def mask_role(role):
    import rbac; return rbac.masked(role)           # Staff and Auditor never see salary or personal details
_T = {"t": None}
def start():
    if _T["t"]: return
    def loop():
        while True:
            time.sleep(3600)
            try:
                last = (LE.get_state("purge_last", {}) or {}).get("day")
                if last != datetime.date.today().isoformat(): purge(False, "retention-job"); LE.set_state("purge_last", {"day": datetime.date.today().isoformat()})
            except Exception: pass
    _T["t"] = threading.Thread(target=loop, daemon=True); _T["t"].start()
