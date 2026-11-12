"""Shared pages: Notifications, Digital Twin, Data Feed Center, Admin, Copilot (chat, knowledge base, document translator)."""
import os, re, json, time
import numpy as np, pandas as pd
from fastapi import HTTPException
import live_engine as LE, data_feeder as FD, twin as TW, gpu, rag, rbac
import blocks as B
from blocks import Q, clean, TEAL, BLUE, AMBER, RED, VIOLET
from views_core import can, latest, ticket_block, tk_df, scoped
from config import DB_PATH

# ------------------------------------------------------------------ Notifications
def notifications(c, tab="alerts"):
    dom, kind = c["dom"], c["kind"]; tabs = [{"id": "alerts", "label": "Alert feed"}, {"id": "chan", "label": "Channels"}] + ([{"id": "digest", "label": "Weekly digest"}] if kind == "Franchise" else [])
    sub = "Alerts and delivery channels. Critical tickets go to Slack, Teams, Gmail and SMS when configured; overdue tickets escalate automatically (see Approvals)."
    if tab == "chan":
        ch = [("Slack", "SLACK_WEBHOOK_URL"), ("Microsoft Teams", "TEAMS_WEBHOOK_URL"), ("Gmail SMTP", "EMAIL_ID"), ("SMS (Twilio)", "TWILIO_SID")]
        bl = [B.table([{"channel": n, "status": "configured" if os.environ.get(k) else "not configured", "environment variable": k} for n, k in ch], ["channel", B.pill_col("status"), "environment variable"], h=220, key="chan")]
        if can(c, "admin"): bl.append(B.button("tn", "Send a test Critical alert", "/api/notify_test", "ghost"))
        return B.page("Notifications", sub, bl, tabs, live=0)
    if tab == "digest" and kind == "Franchise":
        r = latest("digest"); txt = (r or {}).get("out", {}).get("digest")
        bl = [B.hero("digest", "Digest agent", "Weekly executive digest built from every other agent's latest findings.", r, can_run=can(c, "run")), B.callout(txt, "info", "Latest digest") if txt else B.callout("No digest yet. Press Run on the card above.", "info")]
        bl.append(ticket_block(c, "digest", title="Digest tickets", key="tk_dg")); return B.page("Notifications", sub, bl, tabs, live=0)
    ec = dom.ENTITY_COL; a = Q(f"SELECT alert_id id, {ec} target, severity, category, message, date FROM alerts ORDER BY alert_id DESC LIMIT 300"); a = scoped(a, c)
    bl = [B.kpis(("Alerts logged", len(a)), ("Critical", int((a.severity == "Critical").sum()), None, "Critical"), ("Open tickets", int(Q("SELECT COUNT(*) n FROM agent_actions WHERE status IN ('open','proposed')").n[0]))),
          B.table(a, ["id", B.pill_col("severity"), "target", "category", "message", "date"], h=470, open={"col": "target"}, key="alerts", search=True)]
    return B.page("Notifications", sub, bl, tabs, live=10)

# ------------------------------------------------------------------ Digital twin
def _rng(n, l, lo, hi, v, st=None):
    d = {"name": n, "label": l, "type": "range", "min": lo, "max": hi, "value": v}
    if st: d["step"] = st
    return d
def _outs(kind): return Q("SELECT outlet_id FROM outlets ORDER BY outlet_id").outlet_id.tolist()
def _seed(): return {"name": "seed", "label": "Random seed (the same seed gives the same result)", "type": "number", "value": 42, "min": 0, "max": 99999, "step": 1}
def _multi(kind): return {"name": "outlets", "label": "Outlets (empty = all)", "type": "multi", "options": _outs(kind), "value": []}
def _carriers(): return Q("SELECT carrier, COUNT(*) n FROM shipments WHERE carrier IS NOT NULL GROUP BY carrier ORDER BY n DESC LIMIT 30").carrier.tolist()
AREAS = ["Red Sea", "Arabian Sea", "Strait of Malacca", "South China Sea", "Bay of Biscay", "Cape of Good Hope", "North Atlantic"]
SIMDEF = {   # page -> (title, description, fields(kind), agents re-run, agent scenario builder)
    "Franchise": {
        "inventory": ("Inventory simulator", "100 simulated 30-day futures per SKU: fill rate, lost sales, the best safety buffer, and what to order now.", lambda: [_rng("pct", "Demand change %", -50, 100, 30), _rng("days", "Supplier delay (extra lead-time days)", 0, 14, 4), _rng("cv", "Demand volatility %", 10, 80, 30), _rng("season", "Demand seasonality strength %", 0, 50, 15), _rng("dvar", "Supplier delay randomness (mean extra days)", 0, 10, 2), _seed(), _multi("Franchise")], ["inventory"]),
        "workforce": ("Workforce simulator", "Overtime, temp cover, extra leavers and revenue at risk when staff are absent.", lambda: [_rng("pct", "Staff absent %", 0, 60, 25), _rng("ot_cap", "Overtime cap (hours per person per week)", 0, 20, 10), _rng("temp", "Share of the gap filled by temps %", 0, 100, 0), _rng("lead", "Hiring lead time (weeks)", 1, 16, 4), _rng("horizon", "Attrition horizon (months)", 3, 24, 12), _seed(), _multi("Franchise")], ["staff"]),
        "outlets": ("Outlet P&L simulator", "Profit, margin, loss-making outlets and what moved profit, under demand, price and cost changes.", lambda: [_rng("pct", "Demand change %", -50, 50, -10), _rng("price", "Price change %", -20, 20, 0), _rng("cost", "General cost inflation %", -20, 40, 5), _rng("elast", "Price elasticity (demand drop per 1% price rise)", 0.2, 3, 1.2, .1), _rng("wage_lo", "Wage inflation: low end of the band %", 0, 15, 3), _rng("wage_hi", "Wage inflation: high end of the band %", 0, 25, 10), _rng("rent", "Rent inflation %", 0, 20, 4), _seed(), _multi("Franchise")], ["outlet", "anomaly"]),
        "marketing": ("Marketing budget simulator", "Conversions with diminishing returns per channel, and the best way to split the same budget.", lambda: [_rng("pct", "Total budget change %", -50, 100, 20), _rng("alpha", "Diminishing returns (higher = closer to linear)", 40, 90, 70), _rng("fatigue", "Campaign fatigue (effectiveness lost per extra 4 weeks) %", 0, 40, 10), _seed()], ["marketing"]),
        "sentiment": ("Reviews & rating simulator", "How a wave of negative reviews moves each outlet's rating, the revenue at risk, and the good reviews needed to recover.", lambda: [_rng("pct", "Share of new reviews that are negative %", 5, 100, 40), _rng("n_new", "New reviews per outlet", 5, 200, 30), _rng("fix", "Fix of the top complaint: effectiveness %", 10, 100, 70), _rng("repeat", "Repeat-visit sensitivity (% of visits per +0.1 star)", 0, 10, 3, .5), _seed(), _multi("Franchise")], ["feedback"]),
        "audit": ("Audit readiness simulator", "Probability each outlet fails the next inspection from its open findings and the days needed to become compliant, expected fines and remediation load.", lambda: [_rng("raise", "Stricter pass mark (points)", 0, 15, 5), _rng("pct", "More violations found %", 0, 100, 10), {"name": "fine", "label": "Fine per violation", "type": "number", "value": 5000}, _rng("days", "Remediation days", 1, 60, 14), _rng("wait", "Days until the next audit", 1, 120, 30), _rng("close", "Findings closed per outlet per week", 0.5, 8, 2, .5), _seed(), _multi("Franchise")], ["audit"])},
    "Freight": {
        "route": ("Route simulator", "Re-plans real sea routes for your busiest lanes when chokepoints close, storms hit or ports congest: extra nm, days and cost.", lambda: [{"name": "closures", "label": "Closed chokepoints", "type": "multi", "options": ["suez", "panama", "malacca", "hormuz", "bosphorus"], "value": ["suez"]}, {"name": "area", "label": "Storm area", "type": "select", "options": ["None"] + AREAS, "value": "None"}, _rng("wind", "Storm wind m/s", 15, 40, 25), _rng("add", "Port congestion increase", 0, 3, 0, .5), {"name": "delay_cost", "label": "Cost of a shipment-day waiting ($)", "type": "number", "value": 120}], ["route_watch", "weather_watch"]),
        "quotes": ("Quote cost simulator", "How fuel, carrier-rate and currency moves hit quote margins, and the price that maximises expected profit.", lambda: [_rng("pct", "Fuel price change %", -30, 80, 20), _rng("carrier", "Carrier rate change %", -10, 30, 0), _rng("fx", "Currency move %", -10, 15, 0), _rng("elasticity", "Customer price sensitivity", 0.5, 4, 2, .5)], ["quote_watch"]),
        "margin": ("Pricing & margin simulator", "Test a discount or a price rise: expected profit and win probability across all open quotes.", lambda: [_rng("pct", "Fuel price change %", -30, 80, 0), _rng("carrier", "Carrier rate change %", -10, 30, 0), _rng("discount", "Discount %", 0, 20, 5), _rng("elasticity", "Customer price sensitivity", 0.5, 4, 2, .5)], ["quote_watch", "anomaly_watch"]),
        "carriers": ("Carrier outage simulator", "A carrier fails: where its shipments go, what it costs and who has no capacity.", lambda: [{"name": "carrier", "label": "Carrier", "type": "select", "options": _carriers(), "value": _carriers()[0]}, _rng("loss", "Capacity lost %", 10, 100, 100), {"name": "delay_cost", "label": "Cost of a shipment-day waiting ($)", "type": "number", "value": 120}], ["route_watch", "anomaly_watch"]),
        "weather": ("Storm simulator", "Vessels inside the storm, delay days and demurrage cost, and how cost climbs with wind.", lambda: [{"name": "area", "label": "Storm area", "type": "select", "options": AREAS, "value": "Red Sea"}, _rng("wind", "Wind m/s", 12, 40, 28), _rng("radius", "Storm radius (nm)", 300, 2000, 900), {"name": "demurrage", "label": "Delay cost per shipment-day ($)", "type": "number", "value": 900}], ["weather_watch"]),
        "customs": ("Customs simulator", "Extra holds, dwell days and duty changes: held shipments, storage cost and the hit to open quotes.", lambda: [_rng("hold", "Inbound shipments put on hold %", 0, 60, 20), _rng("dwell", "Extra dwell days", 1, 14, 4), {"name": "storage", "label": "Storage cost per shipment-day ($)", "type": "number", "value": 180}, _rng("duty", "Duty change (points)", -5, 10, 0)], ["customs_watch"])}}
SIM = {k: {p: (v[3], []) for p, v in d.items()} for k, d in SIMDEF.items()}
def _agent_mut(kind, pid, a):
    if kind == "Franchise":
        cat = TW.franchise_scenarios(); o = a.get("outlets") or []
        return {"inventory": lambda: [cat["Demand change"][0](_nf(a, "pct"), o), cat["Supplier lead-time delay"][0](int(_nf(a, "days")), o)], "workforce": lambda: [cat["Staff absenteeism"][0](_nf(a, "pct"), o)], "outlets": lambda: [cat["Demand change"][0](_nf(a, "pct"), o)],
                "sentiment": lambda: [cat["Negative review wave"][0](_nf(a, "pct"), o)], "audit": lambda: [cat["Failed inspection"][0](o or _outs(kind)[:2])], "marketing": lambda: []}.get(pid, lambda: [])()
    cat = TW.freight_scenarios()
    return {"route": lambda: ([cat["Storm on a sea area"][0](a.get("area"), _nf(a, "wind", 25))] if a.get("area") not in (None, "None") else []) + ([cat["Port congestion surge"][0](_nf(a, "add"), "All")] if _nf(a, "add") else []), "quotes": lambda: [cat["Fuel price move"][0](_nf(a, "pct"))], "margin": lambda: [cat["Fuel price move"][0](_nf(a, "pct"))],
            "weather": lambda: [cat["Storm on a sea area"][0](a.get("area") or "Red Sea", _nf(a, "wind", 25))], "customs": lambda: [cat["Customs crackdown"][0](int(_nf(a, "hold") / 100 * 200))], "carriers": lambda: []}.get(pid, lambda: [])()
def _nf(a, k, d=0.0):
    try: return float(a.get(k, d))
    except Exception: return float(d)
def simulator(c, pid):
    kind = c["kind"]; title, desc, flds, agents = SIMDEF[kind][pid]
    fields = flds() + [{"name": "page", "type": "hidden", "value": pid}, {"name": "scenario", "type": "hidden", "value": "sim"}, {"name": "agents", "label": "Also re-run the real agents on the copy (slower)", "type": "select", "options": ["no", "yes"], "value": "no"}]
    bl = [B.callout(desc + " Every run copies the live data; nothing live changes. Assumptions are listed in the results.", "info"), B.form("sim_" + pid, fields, "Run simulation", "/api/sim/run", title=title)]
    return B.page("Simulator", "Per-agent what-if on a private copy of the data", bl, [], live=0)
def sim_run(c, pid, sc, args):
    kind, dom = c["kind"], c["dom"]; title, desc, flds, agents = SIMDEF[kind][pid]
    import sim_fr, sim_fq; mod = sim_fr if kind == "Franchise" else sim_fq; r = mod.RUN[pid](args); bl = r["blocks"]
    if args.get("agents") == "yes":
        muts = _agent_mut(kind, pid, args)
        if muts:
            base = TW.run_agents(dom, agents); sc_res = TW.run_agents(dom, agents, (lambda cn: [f(cn) for f in muts])); rows = [{"agent": n, "before": base[n].score, "after": sc_res[n].score, "delta": round(sc_res[n].score - base[n].score, 1), "finding": sc_res[n].summary} for n in agents]
            bk = {(a["type"], str(a["target"])) for n in agents for a in base[n].actions}; new = [a for n in agents for a in sc_res[n].actions if (a["type"], str(a["target"])) not in bk]
            bl.append(B.card("What the real agent says on the copy", B.callout(" | ".join(x["finding"] for x in rows), "info"), B.table(rows, ["agent", B.num_col("before", "before", "num"), B.num_col("after", "after", "num"), B.num_col("delta", "Δ", "num")], h=160, key="sim_ag"),
                             *([B.table(pd.DataFrame(new)[["type", "target", "severity", "detail"]].head(20), ["type", "target", B.pill_col("severity"), "detail"], title=f"{len(new)} tickets it would raise", h=260, key="sim_na")] if new else [])))
        else: bl.append(B.callout("No data-changing scenario maps to this agent, so only the model above applies.", "info"))
    import mc_sims; bl = bl + mc_sims.blocks(kind, pid, args)
    return bl
def twin(c, tab=None):
    import twin2 as T2; kind = c["kind"]; tabs = [{"id": "lab", "label": "Scenario lab"}, {"id": "saved", "label": "Saved scenarios"}, {"id": "assume", "label": "Assumptions"}]; tab = tab if tab in ("lab", "saved", "assume") else "lab"
    if tab == "assume":
        import sim_fr, sim_fq; A = sim_fr.ASSUME if kind == "Franchise" else sim_fq.ASSUME
        return B.page("Digital Twin", "What the twin assumes", [B.callout("Every number the twin shows comes from these models and settings. They are explicit so you can challenge them; edit sim_fr.py / sim_fq.py to match your business.", "info")] + [B.card(k.title(), B.md(v)) for k, v in A.items()], tabs, live=0)
    if tab == "saved":
        s = T2.saved(); rows = [{"name": r.name, "saved": r.ts[:16], "by": r.by, "total_impact": (json.loads(r.result).get("kpi", {}).get("TOTAL", "")) if r.result else ""} for r in s.itertuples()]; names = [r["name"] for r in rows]
        bl = [B.table(rows, ["name", "saved", "by", "total_impact"], title="Saved scenarios", h=260, key="t2_s")] if rows else [B.callout("Nothing saved yet. In the Scenario lab, type a name before running to save the scenario.", "info")]
        if len(names) >= 1: bl += [B.form("t2_run", [{"name": "a", "label": "Run saved scenario", "type": "select", "options": names, "value": names[0]}], "Run again on today's data", "/api/twin/saved", title=None, tone="ghost")]
        if len(names) >= 2: bl += [B.form("t2_cmp", [{"name": "a", "label": "Scenario A", "type": "select", "options": names, "value": names[0]}, {"name": "b", "label": "Scenario B", "type": "select", "options": names, "value": names[1]}], "Compare side by side", "/api/twin/compare", title="Compare two scenarios", tone="ghost")]
        return B.page("Digital Twin", "Saved what-ifs", bl, tabs, live=0)
    fields = T2.fields(kind) + [{"name": "agents", "label": "Also re-run the real agents on the copy (slower)", "type": "select", "options": ["no", "yes"], "value": "no"}, {"name": "name", "label": "Save this scenario as (optional)", "type": "text"}]
    bl = [B.callout("Stack as many shocks as you like. The twin runs every simulator together, shows the money impact with uncertainty bands, ranks the best responses, and can send one to the approval queue. The live database is never touched.", "info"), B.form("twin_lab", fields, "Run the twin", "/api/twin/run", title="Scenario lab")]
    return B.page("Digital Twin", "Stacked what-if on a private copy of the live data", bl, tabs, live=0)
def twin_run(c, args):
    import twin2 as T2; args = dict(args); name = (args.pop("name", "") or "").strip(); bl, summ = T2.run(c, args)
    if name: T2.save(name, args, c.get("email", "user"), summ); bl.insert(0, B.callout(f"Saved as '{name}'.", "info"))
    return bl
def twin_compare(c, an, bn):
    import twin2 as T2; s = T2.saved().set_index("name"); out = []
    for n in (an, bn):
        a = json.loads(s.loc[n].args); _, sm = T2.run(c, a); out.append((n, sm))
    keys = list(dict.fromkeys(list(out[0][1]["kpi"]) + list(out[1][1]["kpi"]))); rows = [{"measure": k, an: out[0][1]["kpi"].get(k, ""), bn: out[1][1]["kpi"].get(k, "")} for k in keys]
    return [B.table(rows, ["measure", an, bn], title="Side by side (re-run on today's data)", h=min(80 + 38 * len(rows), 360), key="t2_cmpt")]
# ------------------------------------------------------------------ Data Feed Center
def feeds(c, tab="upload"):
    kind = c["kind"]; tabs = [{"id": "upload", "label": "Upload"}, {"id": "api", "label": "Live API push"}, {"id": "url", "label": "URL feeds"}, {"id": "inbox", "label": "Folder inbox"}, {"id": "quality", "label": "Quality & rejects"}]
    sub = "Real data in, agents re-run, entities with real data stop being simulated."
    if not can(c, "feeder"): return B.page("Data Feed Center", sub, [B.callout("Your role cannot feed data. Ask an Admin or a manager.", "warn")], [], live=0)
    FD.init(); hist = Q("SELECT ts, source, target, rows_in, rows_ok, rows_bad FROM feed_log ORDER BY id DESC LIMIT 15"); real = FD.real_entities()
    foot = [B.row(B.card("Ingestion history", B.table(hist, ["ts", "source", "target", "rows_in", "rows_ok", "rows_bad"], h=300, key="fh")), B.card("Entities on a real feed right now", B.kpis(("Real-fed entities", len(real), "no longer simulated")), B.table([{"entity": e} for e in sorted(real)[:60]], ["entity"], h=200, key="rf")))]
    if tab == "api":
        k = os.environ.get("INGEST_KEY", "(set INGEST_KEY in the launcher first)"); ex = '[{"outlet_id":"OUT-001","ts":"2026-01-01T10:00:00","amount":1520.5,"tx_count":6}]' if kind == "Franchise" else '[{"shipment_id":"SHP-L00000001","lat":18.9,"lon":72.8}]'; tb = "sales" if kind == "Franchise" else "vessels"
        return B.page("Data Feed Center", sub, [B.md(f"**POST rows as JSON** from a POS terminal, an AIS gateway or any system:\n\n```\ncurl -X POST $BASE_URL/ingest/{tb} -H 'X-API-Key: {k}' -H 'Content-Type: application/json' -d '{ex}'\n```\nAdd `-H 'Idempotency-Key: <unique id>'` so a retried request is never applied twice; send up to 50,000 rows as a JSON array or NDJSON. Rows are validated, auto-mapped and upserted. The matching entities leave the simulator for 10 minutes after their last real record."), *([B.form("ais_map", [{"name": "pairs", "label": "One 'MMSI,shipment_id' per line, so AIS pushes (POST /ingest/ais with mmsi, lat, lon, speed_kn) update the right vessel", "type": "textarea"}], "Save links", "/api/feed/ais_map", title="AIS vessel identifiers")] if kind == "Freight" else []), *foot], tabs, live=15)
    if tab == "url":
        u = Q("SELECT id, url, target, every_s FROM feed_urls")
        return B.page("Data Feed Center", sub, [B.form("fd_url", [{"name": "url", "label": "CSV or JSON URL", "type": "text"}, {"name": "target", "label": "Into table", "type": "select", "options": FD.ALLOWED[kind], "value": FD.ALLOWED[kind][0]}, {"name": "every", "label": "Refresh every (seconds, min 30)", "type": "number", "value": 300}, {"name": "auth_env", "label": "Auth: NAME of the environment variable holding the Bearer token (never the token itself)", "type": "text"}, {"name": "json_path", "label": "JSON path to the rows, e.g. data.items (optional)", "type": "text"}], "Register feed", "/api/feed/url", title="Register a REST / CSV / JSON feed"), B.table(Q("SELECT id, url, target, every_s, auth_env, last_status FROM feed_urls"), ["id", "url", "target", "every_s", "auth_env", "last_status"], title="Registered feeds", h=200, key="fu"), *foot], tabs, live=0)
    if tab == "quality":
        rj = Q("SELECT ts, source, target, row_no, field, reason, value FROM feed_rejects ORDER BY id DESC LIMIT 200"); sm = Q("SELECT target, reason, COUNT(*) n FROM feed_rejects GROUP BY target, reason ORDER BY n DESC LIMIT 12")
        bl = [B.kpis(("Rejected rows stored", int(Q("SELECT COUNT(*) n FROM feed_rejects").n[0]), "kept 90 days", None), ("Feeds registered", int(Q("SELECT COUNT(*) n FROM feed_urls").n[0]))),
              B.md("Every feed is validated row by row: numeric ranges, valid dates, allowed values and foreign keys (an outlet or port must exist). Bad rows are quarantined here with the reason; good rows still load. [Download all rejected rows (CSV)](/api/feed/rejects.csv)"),
              B.table(sm, ["target", "reason", B.num_col("n", "rows", "int")], title="Most common problems", h=220, key="fq_s"), B.table(rj, ["ts", "source", "target", B.num_col("row_no", "row", "int"), "field", "reason", "value"], title="Latest rejected rows", h=320, key="fq_r"), *foot[:0]]
        return B.page("Data Feed Center", sub, bl, tabs, live=10)
    if tab == "inbox":
        files = sorted(os.listdir(FD.INBOX)); return B.page("Data Feed Center", sub, [B.md(f"Drop files named `<table>.csv` or `<table>__anything.csv` into `{FD.INBOX}` (for example `staff.csv`, `ports__2026.xlsx`). They are ingested automatically within seconds."), B.table([{"file": f} for f in files], ["file"], title="Waiting in the inbox", h=160, key="fi"), *foot], tabs, live=10)
    return B.page("Data Feed Center", sub, [B.form("fd_up", [{"name": "table", "label": "Target table", "type": "select", "options": FD.ALLOWED[kind], "value": "sales" if kind == "Franchise" else "vessels"}, {"name": "file", "label": "CSV, XLSX or JSON", "type": "file"}], "Validate and ingest", "/api/feed/upload", title="Upload a file", sub="Columns are auto-matched to the table (exact, alias and fuzzy). Rows that fail validation are rejected and counted."), *foot], tabs, live=0)

# ------------------------------------------------------------------ Admin
def admin(c, tab="users"):
    dom, kind = c["dom"], c["kind"]; tabs = [{"id": "users", "label": "Users & access"}, {"id": "runtime", "label": "Runtime"}, {"id": "gpu", "label": "GPU & models"}, {"id": "decisions", "label": "Decisions"}, {"id": "audit", "label": "Audit log"}, {"id": "insights", "label": "Copilot insights"}, {"id": "teach", "label": "Teach Copilot"}, {"id": "check", "label": "System check"}, {"id": "gov", "label": "Data governance"}, {"id": "data", "label": "Data"}]
    if not can(c, "admin"): raise HTTPException(403, "Forbidden: only the Admin role can open the Admin page.")
    sub = "Platform health, access control and the audit trail"
    if tab == "gpu":
        g = gpu.status(); m = g["models"]; bl = []
        bl.append(B.kpis(("Device", g["gpu"] or "CPU only", f"CUDA {'available' if g['cuda'] else 'NOT available'} · torch {g['torch']}", None if g["cuda"] else "Critical"), ("VRAM used", f"{g['vram_used_gb']} GB", f"reserved {g['vram_reserved_gb']} of {g['vram_gb']} GB"), ("LLM speed", f"{g['stats']['tok_s'] or '–'} tok/s", f"{g['stats']['llm_calls']} generations"), ("Translations", g["stats"]["translations"], f"last batch {g['stats']['translate_ms'] or '–'} ms")))
        if not g["cuda"]: bl.append(B.callout("This runtime has no GPU. In Colab choose Runtime > Change runtime type > T4 GPU, then run the notebook again. Models fall back to CPU or stay unloaded.", "danger"))
        bl.append(B.table([{"model": k, "name": v["name"], "state": v["state"], "device": v["device"], "load_s": v["sec"], "download_gb": (f"{v.get('done_gb')}/{v.get('total_gb')}" if v.get("total_gb") else None), "precision": v.get("quant"), "error": v["err"]} for k, v in m.items()], ["model", "name", B.pill_col("state"), "download_gb", "device", "load_s", "precision", "error"], title="Models on the GPU", h=190, key="gm"))
        return B.page("Admin", sub, bl, tabs, live=3)
    if tab == "insights":
        import copilot_pro as CPX; I = CPX.insights(); tot = I["total"] or 0; rt = {r[0]: r[1] for r in I["routes"]}; ex = rt.get("exact", 0) + rt.get("exact+llm", 0); un = rt.get("unanswered", 0); fbn = I["up"] + I["down"]
        bl = [B.kpis(("Questions", tot, "all time, this database"), ("Answered exactly (SQL)", f"{round(100 * ex / tot) if tot else 0}%", f"{ex} question(s)", None), ("Unanswered", f"{round(100 * un / tot) if tot else 0}%", f"{un} question(s)", "Critical" if tot and un / tot > .25 else ("Warning" if un else None)), ("Thumbs up / down", f"{I['up']} / {I['down']}", f"{fbn} ratings"), ("Avg exact answer", f"{round(I['avg_ms'])} ms" if I["avg_ms"] else "–"))]
        try: bl += _tuning_blocks()                                                            # [tuning] answer rate before / after the fine-tune
        except Exception as _e: bl.append(B.callout("Fine-tune results could not be shown: " + repr(_e)[:120], "warn"))
        bl.append(B.table([{"route": r[0], "questions": r[1]} for r in I["routes"]], ["route", B.num_col("questions", "questions", "int")], title="How questions were answered", h=190, key="ci_r"))
        bl.append(B.table([{"question": r[0], "times": r[1], "last_asked": str(r[2]).replace("T", " ")} for r in I["unanswered"]], ["question", B.num_col("times", "times", "int"), "last_asked"], title="Top unanswered questions: add an intent or synonym for these", h=300, key="ci_u"))
        bl.append(B.row(B.card("Thumbs-down answers", B.table([{"when": str(r[0]).replace("T", " "), "question": r[1]} for r in I["down_q"]], ["when", "question"], h=260, key="ci_d")), B.card("Recent questions", B.table([{"when": str(r[0]).replace("T", " "), "question": r[1], "route": r[2], "ms": r[3]} for r in I["recent"]], ["when", "question", B.pill_col("route"), B.num_col("ms", "ms", "int")], h=260, key="ci_c"))))
        return B.page("Admin", sub, bl, tabs, live=0)
    if tab == "teach":
        import copilot_pro as CPX; S = CPX.teach_stats(); GOAL = 50; bk = CPX.backlog(300); tr = CPX.taught_rows()
        ex_q = [r["question"] for r in bk[:40]]
        bl = [B.kpis(("Taught so far", f"{S['taught']} / {GOAL}", "goal: 50+ questions", None if S["taught"] >= GOAL else "Warning"), ("Unanswered found", S["found"], "distinct questions"), ("Still open", S["open"], "not taught yet", "Critical" if S["open"] > 20 else ("Warning" if S["open"] else None)))]
        bl.append(B.callout("How this works: 1) Find questions the Copilot cannot answer: ask it in AI Copilot, or paste a list below and test them. 2) Teach it: pick the question, write the correct answer (and keywords). 3) Ask again: it now answers, also for rephrased versions. Aim for 50+ taught questions from real, useful domain questions.", "info"))
        bl.append(B.row(
            B.form("probe", [{"name": "questions", "label": "Questions to test (one per line, up to 25)", "type": "textarea", "placeholder": "What is the refund policy?\nWhich outlets need a service recovery visit?\n..."}], "Test them now", "/api/copilot/probe", title="1. Find unanswered questions", sub="Runs each question through the real Copilot (SQL, agents, RAG, LLM). Unanswered ones go to the backlog."),
            B.form("teach", [{"name": "question", "label": "Question", "type": ("select" if ex_q else "text"), **({"options": ex_q} if ex_q else {})}, {"name": "answer", "label": "Correct answer (a few lines; include the numbers or the policy)", "type": "textarea"}, {"name": "keywords", "label": "Keywords / other ways to ask it (comma separated)", "type": "text"}], "Teach the Copilot", "/api/copilot/teach", title="2. Teach it", sub="Pick a question from the backlog list (filled after you test questions or ask the Copilot).")))
        bl.append(B.row(
            B.form("teach_q2", [{"name": "question", "label": "Or type any question", "type": "text"}, {"name": "answer", "label": "Correct answer", "type": "textarea"}, {"name": "keywords", "label": "Keywords (optional)", "type": "text"}], "Save", "/api/copilot/teach", title="Add a question directly"),
            B.form("teach_imp", [{"name": "file", "label": "CSV with the columns: question, answer, keywords", "type": "file"}], "Import CSV", "/api/copilot/teach/import", title="Bulk add from a CSV", sub="Best for adding many at once. Download the current list first to see the format."),))
        bl.append(B.table(bk, ["question", B.num_col("times", "times asked", "int"), "last_asked"], title="Backlog: questions the Copilot could not answer", h=300, key="tc_bk"))
        bl.append(B.table([{"id": r["id"], "question": r["question"], "answer": r["answer"][:160], "keywords": r["keywords"], "by": r["by"], "when": r["when"].replace("T", " ")} for r in tr], ["id", "question", "answer", "keywords", "by", "when"], title="Taught questions", h=320, key="tc_tr"))
        bl.append(B.row(B.button("tc_exp", "Download taught questions (CSV)", "/api/copilot/teach/export", "ghost", payload={"download": True}), B.form("teach_del", [{"name": "id", "label": "Remove a taught question (enter its id)", "type": "number"}], "Remove", "/api/copilot/teach/delete", tone="ghost")))
        return B.page("Admin", sub, bl, tabs, live=0)
    if tab == "check":
        import datetime as _dt, copilot_pro as CPX, qa as QAX
        from config import DATA_DIR
        chk = []
        def add(name, ok, detail, warn=False): chk.append({"check": name, "status": "OK" if ok else ("Warning" if warn else "Critical"), "detail": detail})
        n = _dt.datetime.now(); add("Server clock (IST)", True, n.strftime("%A %d %B %Y, %I:%M:%S %p") + " · TZ=" + (os.environ.get("TZ") or "system"))
        db = LE.conn()
        try: LE._steps_ddl(db); db.commit()
        except Exception: pass
        try:
            import rag as _rg0; _rg0._seed()
        except Exception: pass
        for t in ["outlets", "staff", "inventory", "sales"] if kind == "Franchise" else ["shipments", "ports", "carriers", "freight_quotes", "customs_rules"]:
            try: k = int(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]); add("Table " + t, k > 0, f"{k} rows")
            except Exception as e: add("Table " + t, False, str(e)[:80])
        def age(sql):
            try:
                r = db.execute(sql).fetchone(); return None if not r or not r[0] else (n - _dt.datetime.fromisoformat(str(r[0])[:19].replace(" ", "T"))).total_seconds()
            except Exception: return None
        for ag in dom.AGENTS:
            if ag == "digest":
                a = age("SELECT MAX(ts) FROM agent_runs WHERE agent='digest'"); add("Agent digest (daily)", True, "runs once a day on its schedule; " + ("not run yet today" if a is None else f"last run {int(a // 3600)} h ago")); continue
            a = age("SELECT MAX(ts) FROM agent_runs WHERE agent=?".replace("?", "'" + ag + "'")); add("Agent " + ag, a is not None and a < 900, "not run yet: the worker starts about a minute after the app" if a is None else f"last run {int(a // 60)} min ago", warn=True)
        a = age("SELECT MAX(ts) FROM decisions"); add("Intelligence Engine decision", a is not None and a < 900, "none yet: first cycle runs about a minute after start" if a is None else f"{int(a // 60)} min ago", warn=True)
        try:
            k = int(db.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]); add("Knowledge base (RAG)", k > 0, f"{k} chunks indexed", warn=True)
        except Exception: add("Knowledge base (RAG)", False, "not built yet: it builds in the background after start", warn=True)
        import rag as _rg
        try:
            _d = _rg.drive_dir(); _mt = os.path.isdir(_d); add("Google Drive (RAG builder output)", _mt, _d if _mt else "Drive not mounted or folder missing. In the launcher cell keep USE_DRIVE = True, allow Drive access, run the RAG notebook first, then use AI Copilot > Knowledge base > Import from Drive.", warn=True)
            _n = int(db.execute("SELECT COUNT(*) FROM kb_chunks WHERE builtin=2").fetchone()[0]); add("Chunks imported from Drive", _n > 0, f"{_n} chunks (your RAG notebook output)" if _n else "none imported yet", warn=True)
        except Exception as e: add("Google Drive (RAG builder output)", False, str(e)[:80], warn=True)
        try:
            import persist as _ps; _ok, _dt = _ps.status(); add("Database backup on Google Drive (chats, users, tickets)", bool(_ok), _dt, warn=True)
        except Exception as e: add("Database backup on Google Drive", False, str(e)[:80], warn=True)
        L = gpu.S["models"]["llm"]; add("LLM", L["state"] == "ready", f"{L['state']} on {L['device'] or '-'} {L['err'] or ''}".strip(), warn=True)
        N = gpu.S["models"]["nllb"]; add("Translation (NLLB)", N["state"] == "ready", f"{N['state']} on {N['device'] or '-'}", warn=True)
        ok = 0; probes = ["Top 5 outlets by revenue", "How many staff are there?"] if kind == "Franchise" else ["How many shipments are on customs hold?", "Which port has the highest congestion?"]
        for p in probes:
            try: r = QAX.answer(kind, p, None, True); good = bool(r and r.get("answer")); ok += good; add("Copilot: " + p, good, (r or {}).get("answer", "no exact answer")[:90] if good else "no exact answer")
            except Exception as e: add("Copilot: " + p, False, repr(e)[:90])
        try:
            r = db.execute("SELECT COUNT(*) FROM agent_actions WHERE status IN ('proposed','open')").fetchone()[0]; s2 = db.execute("SELECT COUNT(*) FROM approval_steps WHERE status='pending'").fetchone()[0]; add("Approvals pipeline", True, f"{r} open tickets · {s2} pending steps")
        except Exception as e: add("Approvals pipeline", False, str(e)[:80])
        try: t = os.path.join(DATA_DIR, ".w"); open(t, "w").write("x"); os.remove(t); add("Data folder writable", True, DATA_DIR)
        except Exception as e: add("Data folder writable", False, str(e)[:80])
        bad = sum(1 for x in chk if x["status"] == "Critical"); wr = sum(1 for x in chk if x["status"] == "Warning")
        return B.page("Admin", sub, [B.kpis(("Checks", len(chk)), ("Critical", bad, None, "Critical" if bad else None), ("Warnings", wr, None, "Warning" if wr else None), ("IST now", n.strftime("%I:%M %p"), n.strftime("%d %b %Y"))), B.table(chk, ["check", B.pill_col("status"), "detail"], title="System check (run again by reopening this tab)", h=560, key="sc")], tabs, live=0)
    if tab == "gov":
        import privacy as PV; pol = PV.policy(); rows = PV.purge(True, "view"); last = LE.get_state("purge_last", {}) or {}
        bl = [B.kpis(("Rows past retention", sum(r["older_rows"] for r in rows), "removed by the nightly job", None), ("Last purge", last.get("day", "never"))),
              B.table(rows, ["table", B.num_col("keep_days", "keep (days)", "int"), B.num_col("older_rows", "past retention", "int")], title="Retention policy (operational history only; master data is never purged)", h=300, key="gv_r"),
              B.form("gv_set", [{"name": "table", "label": "Table", "type": "select", "options": list(pol), "value": list(pol)[0]}, {"name": "days", "label": "Keep for (days, min 7)", "type": "number", "value": 365}], "Set retention", "/api/gov/retention", title="Change a retention period", tone="ghost"),
              B.form("gv_purge", [{"name": "mode", "label": "Mode", "type": "select", "options": ["dry", "run"], "value": "dry"}], "Run purge", "/api/gov/purge", title="Purge now", sub="Start with a dry run: it only counts."),
              B.table([{"table": t, "field": f, "what": w, "handling": h} for t, f, w, h in PV.PII[kind]], ["table", "field", "what", "handling"], title="Personal data inventory", h=260, key="gv_p"),
              B.form("gv_dsar", [{"name": "subject", "label": "Staff id or login email", "type": "text"}, {"name": "action", "label": "Action", "type": "select", "options": ["export", "erase"], "value": "export"}], "Run request", "/api/gov/dsar", title="Data-subject request (access / erasure)", sub="Export returns everything held about the person. Erase anonymises or deletes it and is recorded in the audit log."),
              B.callout("Free-text feedback has emails and phone numbers replaced before storage. Names and salaries are hidden from roles that are not Admin, Franchise Owner or Store Manager in the Copilot. This is a technical baseline, not legal advice: set the retention periods your counsel requires.", "info")]
        return B.page("Admin", sub, bl, tabs, live=0)
    if tab == "decisions": return B.page("Admin", sub, [B.table(Q("SELECT ts, trigger_src, score, risk, narrative FROM decisions ORDER BY decision_id DESC LIMIT 60"), ["ts", "trigger_src", B.num_col("score", "score", "num"), B.pill_col("risk"), "narrative"], h=520, key="dc")], tabs, live=10)
    if tab == "users":              # the Milestone 2 Admin dashboard (users table, add / delete, promote / demote, lock / unlock, activity log, role privilege table) is drawn by the front end
        return B.page("Admin", "Users, roles and recent activity", [{"t": "admin_users"}], tabs, live=0)
    if tab == "audit":
        a = Q("SELECT ts, actor, event, target, detail FROM audit_log ORDER BY audit_id DESC LIMIT 400"); return B.page("Admin", sub, [B.table(a, ["ts", "actor", B.pill_col("event"), "target", "detail"], title="Audit log", h=520, key="au", search=True), B.button("csv", "Export CSV", "/api/audit.csv", "ghost", payload={"download": True})], tabs, live=10)
    if tab == "data":
        tbls = [r[0] for r in LE.conn().execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]; rows = []
        for t in tbls:
            try: rows.append({"table": t, "rows": int(LE.conn().execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])})
            except Exception: pass
        return B.page("Admin", sub, [B.kpis(("Database size", f"{os.path.getsize(DB_PATH) / 2**20:.1f} MB"), ("Tables", len(rows))), B.button("bk", "Download database backup", "/api/backup", "ghost", payload={"download": True}), B.callout("The database lives in " + os.path.dirname(DB_PATH) + (". Colab erases it when the runtime resets: set PERSIST = True in the notebook's start cell to keep it on Google Drive, or download a backup here." if "/content/" in DB_PATH else "."), "info"), B.table(sorted(rows, key=lambda r: -r["rows"]), ["table", B.num_col("rows", "rows", "int")], h=480, key="dt")], tabs, live=15)
    s = LE.get_state("runtime", {}) or {}; perf = Q("SELECT agent, COUNT(*) runs, ROUND(AVG(latency_ms)) avg_ms, ROUND(AVG(score),1) avg_score, MAX(ts) last_run FROM agent_runs GROUP BY agent ORDER BY runs DESC"); lat = Q("SELECT substr(ts,12,8) t, agent, latency_ms ms FROM agent_runs ORDER BY run_id DESC LIMIT 200")
    g = {a: [{"x": i, "y": r.ms, "label": r.t} for i, r in enumerate(lat[lat.agent == a].itertuples())] for a in lat.agent.unique()}
    bl = [B.kpis(("Ticks", s.get("ticks", 0)), ("Cycles", s.get("cycles", 0)), ("Last cycle", (s.get("last_cycle") or "starting")[11:]), ("Open tickets", int(Q("SELECT COUNT(*) n FROM agent_actions WHERE status='open'").n[0]))),
          B.row(B.card("Agent performance", B.table(perf, ["agent", B.num_col("runs", "runs", "int"), B.num_col("avg_ms", "avg ms", "int"), B.num_col("avg_score", "avg score", "num"), "last_run"], h=300, key="perf")), B.card("Recent agent latency (ms)", B.chart(B.scatter(g, "run", "ms"), h=300, key="latc"))),
          B.table(Q("SELECT ts, etype, entity FROM live_events ORDER BY event_id DESC LIMIT 15"), ["ts", "etype", "entity"], title="Live events", h=260, key="ev")]
    return B.page("Admin", sub, bl, tabs, live=6)

# ------------------------------------------------------------------ Copilot
def copilot(c, tab="chat"):
    kind = c["kind"]; tabs = [{"id": "chat", "label": "Ask the agents"}, {"id": "kb", "label": "Knowledge base"}, {"id": "tr", "label": "Document translator"}]; sub = "Agents run first, then the GPU LLM answers from their fresh evidence, in any of 37 languages (NLLB-200)."
    ex = ["Which outlets are at highest risk and why?", "How is inventory holding up this week?", "Why is OUT-007 flagged?"] if kind == "Franchise" else ["Which vessels are in danger from weather right now?", "What quotes need approval?", "How congested are the ports on the Suez route?"]
    if c.get("scope"): ex = [f"How many staff does {c['scope']} have?", "Show inventory items below reorder level", "Show negative reviews this week", "Show failed audits"]       # a scoped role gets examples about its own outlet only
    if tab == "kb":
        d = rag.docs(c["email"]); seen = {}
        for x in d: seen.setdefault((x["title"].split(" (part")[0], x["source"]), 0); seen[(x["title"].split(" (part")[0], x["source"])] += 1
        mine = sum(1 for x in d if x["owner"] == c["email"]); ms = gpu.S["models"]
        st = f"Retrieval: BM25 always on · dense embeddings {ms['embed']['state']} · cross-encoder reranker {ms['rerank']['state']}"
        return B.page("AI Copilot", sub, [B.callout(st + f" · {len(d)} passages ({mine} yours). The sample policies are illustrative; upload your own PDFs or import a corpus built in the RAG notebook.", "info"),
            B.row(B.form("kb_up", [{"name": "file", "label": "PDF or text file", "type": "file"}], "Add to knowledge base", "/api/kb/upload", title="Add a document", sub="Chunked, indexed for BM25, embedded on the GPU. Your uploads are private to you."),
                  B.form("kb_q", [{"name": "q", "label": "Search the knowledge base", "type": "text"}, {"name": "mode", "label": "Method", "type": "select", "options": ["Hybrid + rerank", "BM25 only", "Dense only"], "value": "Hybrid + rerank"}, {"name": "live", "label": "Also search live tickets / reviews", "type": "select", "options": ["no", "yes"], "value": "no"}], "Search", "/api/kb/search", title="Search", tone="ghost")),
            B.row(B.form("kb_imp", [{"name": "file", "label": "kb_export.json (from the RAG builder notebook or an earlier export)", "type": "file"}], "Import corpus", "/api/kb/import", title="Import a corpus", tone="ghost"),
                  B.card("Export, evaluate, sync", B.button("kb_exp", "Download my corpus (JSON)", "/api/kb/export", "ghost", payload={"download": True}), B.button("kb_eval", "Evaluate retrieval (recall@k)", "/api/kb/eval", "primary", payload={}), B.button("kb_drv", "Reload my Drive RAG index", "/api/kb/drive", "ghost", payload={}))),
            B.table([{"document": k[0], "source": k[1], "chunks": v} for k, v in seen.items()], ["document", "source", B.num_col("chunks", "chunks", "int")], title=f"Documents available to you · {len(seen)}", h=300, key="kbd")], tabs, live=0)
    if tab == "tr":
        langs = [k for k in gpu.NLLB_LANGS]; return B.page("AI Copilot", sub, [B.form("trf", [{"name": "text", "label": "Text (any language, auto-detected)", "type": "textarea"}, {"name": "file", "label": "or a PDF / text file", "type": "file"}, {"name": "lang", "label": "Translate into", "type": "select", "options": langs, "value": langs[1]}], "Translate with NLLB-200", "/api/translate_doc", title="Document translator", sub="Facebook NLLB-200 on the GPU, sentence-chunked so long documents are translated completely.")], tabs, live=0)
    return B.page("AI Copilot", sub, [{"t": "chat", "examples": ex, "langs": list(gpu.NLLB_LANGS)}], tabs, live=0)


# ------------------------------------------------------------------ Reports
import reports as RP
def reports(c, tab="pdf"):
    kind = c["kind"]; tabs = [{"id": "pdf", "label": "PDF reports"}, {"id": "csv", "label": "Data exports (CSV)"}]; sub = "Print-ready reports built from live data and the agents' latest findings"
    if tab == "csv":
        bl = [B.callout("Each file is a live snapshot of the table, exactly as the agents see it." + (f" You only get rows for {c['scope']}." if c.get("scope") else ""), "info")]
        bl += [B.button("csv_" + t, f"Download {t}.csv", f"/api/export/{t}.csv", "ghost", payload={"download": True}) for t in RP.EXPORTS[kind]]
        return B.page("Reports", sub, bl, tabs, live=0)
    em = c["email"]; bl = [B.callout(f"PDFs are generated on demand from the current database. Use \"E-mail me\" to receive a copy at {em}" + ("" if __import__("mailer").configured() else " (e-mail is not configured on this server yet, so only Download works)") + ".", "info")]; cards = []
    for rid, title, desc, _, arg in RP.REPORTS[kind]:
        if c.get("scope") and rid in ("fq_exec",): continue
        fields = []
        if arg == "outlet": fields = [{"name": "arg", "label": "Outlet", "type": "select", "options": ([c["scope"]] if c.get("scope") else Q("SELECT outlet_id FROM outlets ORDER BY outlet_id").outlet_id.tolist()), "value": c.get("scope")}]
        if arg == "quote": fields = [{"name": "arg", "label": "Quote", "type": "select", "options": Q("SELECT quote_id FROM freight_quotes ORDER BY created_at DESC LIMIT 300").quote_id.tolist()}]
        cards.append(B.card(title, B.md(desc), B.form("dl_" + rid, fields, "Download PDF", "get:/api/report/" + rid, tone="primary", inline=True) if False else {"t": "form", "id": "dl_" + rid, "fields": fields, "submit": "Download PDF", "url": "get:/api/report/" + rid, "title": None, "tone": "primary", "inline": True},
                            {"t": "form", "id": "em_" + rid, "fields": fields + [{"name": "rid", "type": "hidden", "value": rid}], "submit": "E-mail me", "url": "/api/report/email", "title": None, "tone": "ghost", "inline": True}))
    for i in range(0, len(cards), 2): bl.append(B.row(*cards[i:i + 2]))
    return B.page("Reports", sub, bl, tabs, live=0)

# ------------------------------------------------------------------ My profile


def _tuning_blocks():
    """[tuning] Answer rate before / after the Copilot fine-tune (copilot_eval.py fills the tables; run the 'Evaluate the Copilot' notebook cell)."""
    import copilot_eval as CE
    S = CE.summary(); b, a = S.get("before", {}), S.get("after", {})
    if not (a.get("ALL") and b.get("ALL")): return [B.callout("Answer rate before / after the fine-tune is not measured yet: run the 'Evaluate the Copilot' cell of the fine-tune notebook, then reload this tab.", "info")]
    pct = lambda d, k: (f"{round(100 * d[k] / d['n_answerable'])}%" if d and d["n_answerable"] else "–")
    idk = lambda d: (f"{d['idk_ok']} of {d['n_idk']}" if d and d["n_idk"] else "–")
    x, y = b["ALL"], a["ALL"]
    out = [B.kpis(("Answer rate: before", pct(x, "answered"), f"{x['answered']} of {x['n_answerable']} answerable questions"), ("Answer rate: after", pct(y, "answered"), f"{y['answered']} of {y['n_answerable']} · measured " + str(y["ts"]).replace("T", " ")),
                  ("Verified correct: before", pct(x, "correct"), "numbers match an independent SQL check"), ("Verified correct: after", pct(y, "correct"), f"{y['correct']} of {y['n_answerable']}"),
                  ("'I do not know' when it should", f"{idk(x)} → {idk(y)}", "questions the data cannot answer"))]
    names = {"TUNE": "Tuning questions (used to write the patterns)", "HOLD": "Paraphrases (written first; wording known while tuning)", "BLIND": "Blind questions (written after tuning, run once)", "ALL": "All questions"}
    rows = [{"question set": names[k], "answerable": b[k]["n_answerable"], "answer rate before": pct(b[k], "answered"), "answer rate after": pct(a[k], "answered"), "correct before": pct(b[k], "correct"), "correct after": pct(a[k], "correct"), "I do not know before": idk(b[k]), "I do not know after": idk(a[k])} for k in ("TUNE", "HOLD", "BLIND", "ALL") if b.get(k) and a.get(k)]
    out.append(B.table(rows, ["question set", "answerable", "answer rate before", "answer rate after", "correct before", "correct after", "I do not know before", "I do not know after"], title="Answer rate before and after the fine-tune", h=min(300, 60 + 34 * len(rows)), key="ci_ev"))
    bad = [{"category": i["category"], "question": i["question"], "before": i["before"], "after": i["after"], "why": i["why_after"]} for i in S["items"] if i["after"].endswith("✗")]
    out.append(B.table(bad, ["category", "question", "before", "after", "why"], title="Still not right after the fine-tune: add a pattern or a synonym for these", h=min(320, 60 + 34 * max(1, len(bad))), key="ci_bad"))
    return out
