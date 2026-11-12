"""Digital Twin: a what-if engine that runs the *same agents and the same Intelligence Engine* on a private copy of the live database.
No separate model, no hand-written formula: the scenario edits the copy's data, the real agents re-evaluate it, and the page shows
the difference in health, per-agent scores and the tickets that WOULD be raised. The live database is never touched."""
import os, sqlite3, tempfile, json, copy, re
import numpy as np, pandas as pd
import live_engine as LE

def _nk(s): return re.sub(r"\d+(?:\.\d+)?", "#", str(s))

def run_on_copy(dom, mutate=None):
    """Snapshot the live DB (SQLite online backup), apply `mutate(conn)`, run every agent + the engine on the copy, restore."""
    fd, tmp = tempfile.mkstemp(suffix=".twin.db"); os.close(fd); dst = sqlite3.connect(tmp); src = LE.conn()
    with LE._DB_LOCK: src.backup(dst)
    old = getattr(LE._TL, "c", None); LE._TL.c = dst
    try:
        if mutate: mutate(dst); dst.commit()
        s = {"cycle_id": "twin", "trigger": "twin", "request": "", "queue": [], "results": {}, "decision": {}}
        for name in [n for n in dom.AGENTS if n != "digest"]:
            try: s["results"][name] = dom.AGENTS[name](s)
            except Exception as e: s["results"][name] = LE.AgentResult(name, 50.0, "Medium", f"agent error on twin: {e}")
        d = dom.engine(s)
        return {"decision": d, "results": s["results"]}
    finally:
        LE._TL.c = old
        try: dst.close(); os.remove(tmp)
        except Exception: pass

def run_agents(dom, names, mutate=None):
    """Fast path for the per-agent simulators: private DB copy, run ONLY the named agents (no engine), return their results."""
    fd, tmp = tempfile.mkstemp(suffix=".twin.db"); os.close(fd); dst = sqlite3.connect(tmp); src = LE.conn()
    with LE._DB_LOCK: src.backup(dst)
    old = getattr(LE._TL, "c", None); LE._TL.c = dst
    try:
        if mutate: mutate(dst); dst.commit()
        s = {"cycle_id": "twin", "trigger": "twin", "request": "", "queue": [], "results": {}, "decision": {}}; out = {}
        for n in names:
            try: out[n] = dom.AGENTS[n](s); s["results"][n] = out[n]
            except Exception as e: out[n] = LE.AgentResult(n, 50.0, "Medium", f"agent error on twin: {e}")
        return out
    finally:
        LE._TL.c = old
        try: dst.close(); os.remove(tmp)
        except Exception: pass

def compare(dom, mutate, label=""):
    base = run_on_copy(dom, None); scen = run_on_copy(dom, mutate)
    bk = {(a["type"], str(a["target"])) for a in base["decision"]["actions"]}
    new = [a for a in scen["decision"]["actions"] if (a["type"], str(a["target"])) not in bk]
    gone = [a for a in base["decision"]["actions"] if (a["type"], str(a["target"])) not in {(x["type"], str(x["target"])) for x in scen["decision"]["actions"]}]
    rows = [{"agent": k, "before": base["results"][k].score, "after": scen["results"][k].score, "delta": round(scen["results"][k].score - base["results"][k].score, 1),
             "risk_before": base["results"][k].risk, "risk_after": scen["results"][k].risk, "summary_after": scen["results"][k].summary} for k in base["results"] if k in scen["results"]]
    per = None
    bh, sh = base["decision"].get("health"), scen["decision"].get("health")
    if bh and sh:
        per = pd.DataFrame({"before": pd.Series(bh), "after": pd.Series(sh)}).dropna(); per["delta"] = (per.after - per.before).round(1); per = per.sort_values("delta")
    return {"label": label, "base": base["decision"], "scen": scen["decision"], "agents": pd.DataFrame(rows), "new_actions": new, "cleared_actions": gone, "per_entity": per}

# ---------------------------------------------------------------- scenario catalogues (each one edits the data the real agents read)
def franchise_scenarios():
    def demand(pct, outlets):
        f = 1 + pct / 100
        def m(c):
            w = "" if not outlets else f" WHERE outlet_id IN ({','.join('?' * len(outlets))})"
            c.execute(f"UPDATE inventory SET weekly_demand=weekly_demand*?{w}", [f] + list(outlets)); c.execute(f"UPDATE sales SET amount=amount*?, tx_count=MAX(1,CAST(tx_count*? AS INT)){w}", [f, f] + list(outlets))
        return m
    def supplier(days, outlets):
        def m(c):
            w = "" if not outlets else f" WHERE outlet_id IN ({','.join('?' * len(outlets))})"; c.execute(f"UPDATE inventory SET lead_time_days=lead_time_days+?{w}", [int(days)] + list(outlets))
        return m
    def absent(pct, outlets):
        def m(c):
            w = "" if not outlets else f" AND outlet_id IN ({','.join('?' * len(outlets))})"
            ids = c.execute(f"SELECT staff_id, outlet_id FROM staff WHERE 1=1{w}", list(outlets)).fetchall(); rng = np.random.default_rng(11)
            for sid, oid in ids:
                if rng.random() < pct / 100:
                    for _ in range(12): c.execute("INSERT INTO attendance(staff_id,outlet_id,ts,status) VALUES(?,?,datetime('now','localtime'),'Absent')", (sid, oid))
                    c.execute("UPDATE staff SET overtime_hrs=MIN(45,overtime_hrs+8) WHERE staff_id=?", (sid,))
        return m
    def audit(outlets):
        def m(c):
            for o in outlets: c.execute("INSERT INTO audits(audit_id,outlet_id,audit_date,score,violations,category,status,notes) VALUES(?,?,date('now','localtime'),45,9,'Food Safety','Fail','twin')", ("AUD-TW" + o, o))
        return m
    def reviews(pct, outlets):
        def m(c):
            w = "" if not outlets else f" WHERE outlet_id IN ({','.join('?' * len(outlets))})"
            c.execute(f"UPDATE feedback SET rating=MAX(1, rating-2), comment='slow service dirty rude cold food wrong order' WHERE rowid IN (SELECT rowid FROM feedback{w} ORDER BY RANDOM() LIMIT (SELECT COUNT(*)*?/100 FROM feedback{w}))", list(outlets) + [int(pct)] + list(outlets))
        return m
    return {"Negative review wave": (reviews, ["pct", "outlets"]), "Demand change": (demand, ["pct", "outlets"]), "Supplier lead-time delay": (supplier, ["days", "outlets"]), "Staff absenteeism": (absent, ["pct", "outlets"]), "Failed inspection": (audit, ["outlets"])}

PRESET_STORMS = {"Red Sea": (18.0, 40.0), "Arabian Sea": (15.0, 65.0), "Strait of Malacca": (3.5, 100.5), "South China Sea": (14.0, 114.0), "Bay of Biscay": (45.0, -8.0), "Cape of Good Hope": (-35.0, 20.0), "North Atlantic": (48.0, -35.0)}
def freight_scenarios():
    def storm(area, wind):
        def m(c):
            la, lo = PRESET_STORMS[area]; LE.set_state("storms", (LE.get_state("storms", []) or []) + [{"lat": la, "lon": lo, "r": 900, "wind": float(wind), "ts": LE.now()}])
        return m
    def congestion(add, region):
        def m(c):
            w = "" if region == "All" else " WHERE region=?"; c.execute(f"UPDATE ports SET congestion_index=MIN(5,congestion_index+?){w}", [float(add)] + ([] if region == "All" else [region]))
        return m
    def fuel(pct):
        def m(c):
            LE.set_state("fuel_pct", .12 * (1 + pct / 100)); k = pct / 100
            c.execute("UPDATE freight_quotes SET margin_pct=ROUND(margin_pct-(fuel_surcharge*?)/MAX(final_price,1)*100,2), fuel_surcharge=fuel_surcharge*(1+?)", (k, k))
            c.execute("UPDATE freight_quotes SET status='Pending Approval' WHERE margin_pct<10 AND status NOT IN ('On Hold','Rejected')")
        return m
    def customs(extra):
        def m(c): c.execute("UPDATE shipments SET status='Customs Hold' WHERE shipment_id IN (SELECT shipment_id FROM shipments WHERE status='In Transit' ORDER BY RANDOM() LIMIT ?)", (int(extra),))
        return m
    return {"Storm on a sea area": (storm, ["area", "wind"]), "Port congestion surge": (congestion, ["add", "region"]), "Fuel price move": (fuel, ["pct"]), "Customs crackdown": (customs, ["extra"])}