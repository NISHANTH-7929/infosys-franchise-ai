"""Data Feeder: upload / folder inbox / URL feeds -> validated, auto-mapped, upserted into the live tables, then the agents re-run."""
import os, io, json, time, shutil, difflib, subprocess, datetime
import pandas as pd
from live_engine import conn, _DB_LOCK, now, emit, get_state, set_state
from config import DB_PATH
DATA_DIR = os.path.dirname(DB_PATH); INBOX = os.path.join(DATA_DIR, "inbox"); DONE = os.path.join(DATA_DIR, "inbox_done")
ALLOWED = {"Franchise": ["outlets", "staff", "inventory", "marketing", "audits", "feedback", "sales", "customers_fr", "hr_training"],
           "Freight": ["vessels", "ports", "carriers", "shipments", "customers", "freight_quotes", "freight_rates", "quote_requests", "customs_rules"]}
ALIAS = {"hr_training": {"attrition": ["attrition", "left", "churn"], "job_satisfaction": ["jobsatisfaction", "satisfaction"], "tenure_years": ["yearsatcompany", "tenure"], "work_life_balance": ["worklifebalance"], "monthly_income": ["monthlyincome", "income", "salary"], "age": ["age"], "overtime_hrs": ["overtime", "overtimehrs"]},
         "freight_rates": {"distance_nm": ["distance", "distancenm", "distance_nm"], "cargo_weight": ["weight", "weighttons", "cargoweight"], "cargo_type": ["cargotype", "cargo"], "congestion_level": ["congestion", "congestionlevel"], "freight_cost_usd": ["cost", "freightcost", "price", "freight_cost_usd"]}}
VIRTUAL = {"hr_training": ["attrition", "job_satisfaction", "tenure_years", "work_life_balance", "monthly_income", "age", "overtime_hrs"], "freight_rates": ["distance_nm", "cargo_weight", "cargo_type", "congestion_level", "freight_cost_usd"]}
def init():
    os.makedirs(INBOX, exist_ok=True); os.makedirs(DONE, exist_ok=True)
    with _DB_LOCK, conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS feed_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, target TEXT, rows_in INT, rows_ok INT, rows_bad INT, note TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS feed_urls(id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, target TEXT, every_s INT, last_run REAL DEFAULT 0)")
        for col, ty in (("auth_env", "TEXT"), ("json_path", "TEXT"), ("last_status", "TEXT")):
            try: c.execute(f"ALTER TABLE feed_urls ADD COLUMN {col} {ty}")
            except Exception: pass
        c.execute("CREATE TABLE IF NOT EXISTS feed_rejects(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, target TEXT, row_no INT, field TEXT, reason TEXT, value TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS feed_idem(k TEXT PRIMARY KEY, ts REAL)")
        c.execute("CREATE TABLE IF NOT EXISTS ais_map(mmsi TEXT PRIMARY KEY, shipment_id TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS hr_training(attrition INT, job_satisfaction REAL, tenure_years REAL, work_life_balance REAL, monthly_income REAL, age REAL, overtime_hrs REAL)")
        c.execute("CREATE TABLE IF NOT EXISTS freight_rates(distance_nm REAL, cargo_weight REAL, cargo_type INT, congestion_level INT, freight_cost_usd REAL)")
def seen_key(k):
    """Idempotency: True if this key was already accepted (replayed webhook), else records it."""
    init()
    with _DB_LOCK, conn() as c:
        c.execute("DELETE FROM feed_idem WHERE ts<?", (time.time() - 86400,))
        try: c.execute("INSERT INTO feed_idem VALUES(?,?)", (str(k)[:200], time.time())); return False
        except Exception: return True
def mark_real(ids):
    """Entities that receive a real feed (POS or AIS) are no longer driven by the simulator for 10 minutes after the last real record."""
    with _DB_LOCK, conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS real_feed(entity TEXT PRIMARY KEY, ts REAL)")
        c.executemany("INSERT OR REPLACE INTO real_feed VALUES(?,?)", [(str(i), time.time()) for i in ids])
def real_entities(ttl=600):
    try:
        with _DB_LOCK, conn() as c: return {r[0] for r in c.execute("SELECT entity FROM real_feed WHERE ts>?", (time.time() - ttl,)).fetchall()}
    except Exception: return set()
def _ingest_positions(d, n0, mapping, source):
    """AIS-style vessel positions: needs shipment_id, lat, lon. Updates the tracked vessel in place and stops simulating it."""
    if "shipment_id" not in d.columns and "mmsi" in mapping:
        with _DB_LOCK, conn() as c: mp = dict(c.execute("SELECT mmsi, shipment_id FROM ais_map").fetchall())
        d["shipment_id"] = d["mmsi"].astype(str).map(mp)
    miss = [k for k in ("shipment_id", "lat", "lon") if k not in d.columns]
    if miss: raise ValueError(f"Required column(s) not mapped: {miss}")
    d = d.dropna(subset=["shipment_id", "lat", "lon"]).copy(); d["lat"] = pd.to_numeric(d.lat, errors="coerce"); d["lon"] = pd.to_numeric(d.lon, errors="coerce")
    d = d[d.lat.between(-90, 90) & d.lon.between(-180, 180)]; ok = 0
    with _DB_LOCK, conn() as c:
        known = {r[0] for r in c.execute("SELECT shipment_id FROM vessels").fetchall()}
        for r in d.itertuples(index=False):
            sid = str(r.shipment_id)
            if sid in known:
                sp = getattr(r, "speed_kn", None) if "speed_kn" in d.columns else None
                c.execute("UPDATE vessels SET lat=?, lon=?, updated=?" + (", speed_kn=?" if sp is not None and sp == sp else "") + " WHERE shipment_id=?", (float(r.lat), float(r.lon), now()) + ((float(sp),) if sp is not None and sp == sp else ()) + (sid,)); ok += 1
        c.execute("INSERT INTO feed_log(ts,source,target,rows_in,rows_ok,rows_bad,note) VALUES(?,?,?,?,?,?,?)", (now(), source, "vessels", n0, ok, n0 - ok, "AIS positions; unknown shipment ids rejected"))
    mark_real(d.shipment_id.astype(str).tolist())
    try: from live_engine import audit; audit(source[:40], "ingest", "vessels", f"{ok} positions")
    except Exception: pass
    return ok, n0 - ok
def schema(table):
    c = conn(); return [(r[1], r[2], r[5]) for r in c.execute(f"PRAGMA table_info({table})")]
def _norm(s): return "".join(ch for ch in str(s).lower() if ch.isalnum())
def auto_map(df, table):
    cols = [c for c, _, _ in schema(table)]; out = {}; used = set()
    for tc in cols:
        cands = [_norm(tc)] + [_norm(a) for a in ALIAS.get(table, {}).get(tc, [])]; best = None
        for sc in df.columns:
            if sc in used: continue
            if _norm(sc) in cands: best = sc; break
        if not best:
            m = difflib.get_close_matches(_norm(tc), [_norm(c) for c in df.columns if c not in used], n=1, cutoff=.82)
            best = next((c for c in df.columns if _norm(c) == m[0]), None) if m else None
        if best: out[tc] = best; used.add(best)
    return out
def read_any(name, data):
    n = name.lower()
    if n.endswith(".csv"): return pd.read_csv(io.BytesIO(data))
    if n.endswith((".xlsx", ".xls")): return pd.read_excel(io.BytesIO(data))
    if n.endswith(".json"): return pd.read_json(io.BytesIO(data))
    raise ValueError("Use CSV, XLSX or JSON")
def ingest(df, table, mapping=None, source="upload"):
    init(); mapping = mapping or auto_map(df, table); sch = schema(table)
    d = pd.DataFrame({tc: df[sc] for tc, sc in mapping.items() if sc in df.columns})
    if table == "hr_training" and "attrition" in d: d["attrition"] = d.attrition.astype(str).str.lower().isin(["1", "yes", "true", "y"]).astype(int)
    if table == "hr_training" and "overtime_hrs" in d and d.overtime_hrs.dtype == object: d["overtime_hrs"] = d.overtime_hrs.astype(str).str.lower().isin(["yes", "true", "1"]).astype(int) * 15
    if table == "freight_rates" and "cargo_type" in d and d.cargo_type.dtype == object: d["cargo_type"] = d.cargo_type.astype("category").cat.codes
    if table == "sales" and "source" not in d: d["source"] = "pos"; sch = schema(table)
    if table == "vessels": return _ingest_positions(d, n0 := len(d), mapping, source)
    for tc, ty, _ in sch:
        if tc in d and ty.upper() in ("REAL", "INTEGER", "INT", "FLOAT"): d[tc] = pd.to_numeric(d[tc], errors="coerce")
    rej = []
    if table not in VIRTUAL:
        import validate; d, rej = validate.validate(table, d, conn())
        if rej:
            with _DB_LOCK, conn() as c: c.executemany("INSERT INTO feed_rejects(ts,source,target,row_no,field,reason,value) VALUES(?,?,?,?,?,?,?)", [(now(), source[:60], table, r["row"], r["field"], r["reason"], r["value"]) for r in rej[:300]])
    if table == "feedback" and "comment" in d:
        import privacy; d["comment"] = d["comment"].map(privacy.redact)
    pk = [tc for tc, _, p in sch if p]; need = pk or [sch[0][0]] if table not in VIRTUAL else list(VIRTUAL[table])
    need = [n for n in need if not (n.endswith("_id") and n not in d and any(t.upper() == "INTEGER" and p for _, t, p in sch))]
    if table in VIRTUAL: need = [VIRTUAL[table][-1] if table == "freight_rates" else "attrition"]
    miss = [n for n in need if n not in d.columns]
    if miss: raise ValueError(f"Required column(s) not mapped: {miss}")
    if table in VIRTUAL: d = d.fillna(d.median(numeric_only=True))
    n0 = len(d) + len(rej); d = d.dropna(subset=need).drop_duplicates(subset=(need if pk else None) or None); bad = n0 - len(d)
    cols = list(d.columns); ph = ",".join("?" * len(cols))
    with _DB_LOCK, conn() as c:
        c.executemany(f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES({ph})", d.astype(object).where(d.notna(), None).values.tolist())
        c.execute("INSERT INTO feed_log(ts,source,target,rows_in,rows_ok,rows_bad,note) VALUES(?,?,?,?,?,?,?)", (now(), source, table, n0, len(d), bad, json.dumps(mapping)[:300]))
    if table == "sales" and "outlet_id" in d: mark_real(d.outlet_id.astype(str).unique().tolist())
    try: from live_engine import audit; audit(source[:40], "ingest", table, f"{len(d)} rows ok, {bad} rejected")
    except Exception: pass
    emit("feed", table, {"rows": len(d), "source": source}); return len(d), bad
def watch(dom_kind):
    """Called by the runtime: ingests files dropped into the inbox (name = <table>.csv or <table>__x.csv) and polls registered URLs."""
    init(); done = []
    for f in os.listdir(INBOX):
        tbl = f.split("__")[0].rsplit(".", 1)[0]
        if tbl in ALLOWED[dom_kind]:
            try:
                with open(os.path.join(INBOX, f), "rb") as fh: ingest(read_any(f, fh.read()), tbl, source="inbox:" + f)
                shutil.move(os.path.join(INBOX, f), os.path.join(DONE, f)); done.append(f)
            except Exception as e:
                with _DB_LOCK, conn() as c: c.execute("INSERT INTO feed_log(ts,source,target,rows_in,rows_ok,rows_bad,note) VALUES(?,?,?,0,0,0,?)", (now(), "inbox:" + f, tbl, "ERROR " + str(e)[:200]))
                shutil.move(os.path.join(INBOX, f), os.path.join(DONE, "failed_" + f))
    with _DB_LOCK, conn() as c: due = c.execute("SELECT id,url,target,every_s,auth_env,json_path FROM feed_urls WHERE ?-last_run>every_s", (time.time(),)).fetchall()
    for i, url, tbl, ev, auth_env, jp in due:
        try:
            import requests; hd = {"Authorization": "Bearer " + os.environ[auth_env]} if auth_env and os.environ.get(auth_env) else {}
            r = requests.get(url, timeout=15, headers=hd); r.raise_for_status()
            if jp or url.split("?")[0].lower().endswith(".json") or "json" in r.headers.get("content-type", ""):
                js = r.json()
                for k in [p for p in (jp or "").split(".") if p]: js = js[int(k)] if isinstance(js, list) else js[k]
                df = pd.DataFrame(js if isinstance(js, list) else [js])
            else: df = read_any(url.split("?")[0] if "." in url.split("/")[-1] else "x.csv", r.content)
            n_ok, n_bad = ingest(df, tbl, source="url:" + url[:60])
            with _DB_LOCK, conn() as c: c.execute("UPDATE feed_urls SET last_status=? WHERE id=?", (f"ok {n_ok} rows, {n_bad} rejected @ {now()}", i))
        except Exception as e:
            with _DB_LOCK, conn() as c: c.execute("INSERT INTO feed_log(ts,source,target,rows_in,rows_ok,rows_bad,note) VALUES(?,?,?,0,0,0,?)", (now(), "url:" + url[:60], tbl, "ERROR " + str(e)[:200])); c.execute("UPDATE feed_urls SET last_status=? WHERE id=?", ("ERROR " + str(e)[:120], i))
        with _DB_LOCK, conn() as c: c.execute("UPDATE feed_urls SET last_run=? WHERE id=?", (time.time(), i))
    return done
