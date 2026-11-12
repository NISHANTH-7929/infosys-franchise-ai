"""Digital Twin v2: stack several shocks at once, run every quantitative model for this app, show the money impact with uncertainty bands, rank mitigations,
re-run the real agents on a private copy, save/compare scenarios, and send a chosen mitigation to the approval queue. Nothing here changes live data."""
import json, time
import numpy as np, pandas as pd
import blocks as B, live_engine as LE, twin as TW
from blocks import Q, TEAL, BLUE, AMBER, RED, VIOLET
GREY = "#8b8d98"
def _num(v, d=0.0):
    try: return float(v)
    except Exception: return float(d)
def fields(kind):
    if kind == "Franchise":
        outs = Q("SELECT outlet_id FROM outlets ORDER BY outlet_id").outlet_id.tolist()
        return [{"name": "pct", "label": "Demand change %", "type": "range", "min": -50, "max": 100, "value": 0}, {"name": "days", "label": "Supplier lead-time delay (days)", "type": "range", "min": 0, "max": 14, "value": 0}, {"name": "absent", "label": "Staff absent %", "type": "range", "min": 0, "max": 60, "value": 0},
                {"name": "price", "label": "Price change %", "type": "range", "min": -20, "max": 20, "value": 0}, {"name": "cost", "label": "Cost inflation %", "type": "range", "min": -20, "max": 40, "value": 0}, {"name": "neg", "label": "Share of new reviews that are negative %", "type": "range", "min": 0, "max": 100, "value": 0},
                {"name": "mk", "label": "Marketing budget change %", "type": "range", "min": -50, "max": 100, "value": 0}, {"name": "raise", "label": "Stricter audit pass mark (points)", "type": "range", "min": 0, "max": 15, "value": 0}, {"name": "cv", "label": "Demand volatility %", "type": "range", "min": 10, "max": 80, "value": 30},
                {"name": "outlets", "label": "Outlets affected (empty = all)", "type": "multi", "options": outs, "value": []}]
    ports = Q("SELECT carrier, COUNT(*) n FROM shipments WHERE carrier IS NOT NULL GROUP BY carrier ORDER BY n DESC LIMIT 25").carrier.tolist()
    return [{"name": "closures", "label": "Closed chokepoints", "type": "multi", "options": ["suez", "panama", "malacca", "hormuz", "bosphorus"], "value": []}, {"name": "area", "label": "Storm area", "type": "select", "options": ["None", "Red Sea", "Arabian Sea", "Strait of Malacca", "South China Sea", "Bay of Biscay", "Cape of Good Hope", "North Atlantic"], "value": "None"},
            {"name": "wind", "label": "Storm wind m/s", "type": "range", "min": 15, "max": 40, "value": 25}, {"name": "add", "label": "Port congestion increase", "type": "range", "min": 0, "max": 3, "step": .5, "value": 0}, {"name": "pct", "label": "Fuel price change %", "type": "range", "min": -30, "max": 80, "value": 0},
            {"name": "carrier_cost", "label": "Carrier rate change %", "type": "range", "min": -10, "max": 30, "value": 0}, {"name": "fx", "label": "Currency move %", "type": "range", "min": -10, "max": 15, "value": 0}, {"name": "carrier", "label": "Carrier with an outage", "type": "select", "options": ["None"] + ports, "value": "None"},
            {"name": "loss", "label": "Outage: share of its capacity lost %", "type": "range", "min": 10, "max": 100, "value": 100}, {"name": "hold", "label": "Extra customs holds % of inbound", "type": "range", "min": 0, "max": 60, "value": 0}, {"name": "dwell", "label": "Extra dwell days at customs", "type": "range", "min": 1, "max": 14, "value": 4},
            {"name": "elasticity", "label": "Customer price sensitivity", "type": "range", "min": 0.5, "max": 4, "step": .5, "value": 2}]
def _mut_fr(a):
    cat = TW.franchise_scenarios(); fs = []; outs = a.get("outlets") or []
    if _num(a.get("pct")): fs.append(cat["Demand change"][0](_num(a["pct"]), outs))
    if _num(a.get("days")): fs.append(cat["Supplier lead-time delay"][0](int(_num(a["days"])), outs))
    if _num(a.get("absent")): fs.append(cat["Staff absenteeism"][0](_num(a["absent"]), outs))
    if _num(a.get("neg")): fs.append(cat["Negative review wave"][0](_num(a["neg"]), outs))
    return (lambda c: [f(c) for f in fs]) if fs else None
def _mut_fq(a):
    cat = TW.freight_scenarios(); fs = []
    if a.get("area") not in (None, "None"): fs.append(cat["Storm on a sea area"][0](a["area"], _num(a.get("wind"), 25)))
    if _num(a.get("add")): fs.append(cat["Port congestion surge"][0](_num(a["add"]), "All"))
    if _num(a.get("pct")): fs.append(cat["Fuel price move"][0](_num(a["pct"])))
    if _num(a.get("hold")): fs.append(cat["Customs crackdown"][0](int(_num(a["hold"]) / 100 * 200)))
    return (lambda c: [f(c) for f in fs]) if fs else None
def _p(v): return f"{v:,.0f}"
def _cur(kind): return (lambda x: __import__("sim_fr").inr(x)) if kind == "Franchise" else (lambda x: __import__("sim_fq").usd(x))
def _fr(a):
    import sim_fr as S; inr = S.inr; args = dict(a); outs = a.get("outlets") or []
    inv = S.run_inventory({"pct": a.get("pct", 0), "days": a.get("days", 0), "buffer": 0, "cv": a.get("cv", 30), "outlets": outs}); wf = S.run_workforce({"pct": a.get("absent", 0), "ot_cap": 10, "temp": 0, "outlets": outs})
    pn = S.run_pnl({"pct": a.get("pct", 0), "price": a.get("price", 0), "cost": a.get("cost", 0), "outlets": outs}); se = S.run_sentiment({"pct": a.get("neg", 0) or 25, "n_new": 30 if _num(a.get("neg")) else 0, "outlets": outs}) if _num(a.get("neg")) else {"m": {"rev_risk": 0, "below35": 0}, "blocks": []}
    au = S.run_audit({"raise": a.get("raise", 0), "pct": min(1, max(0, _num(a.get("pct")) / 100 * -1)), "fine": 5000, "days": 14, "outlets": outs}); au0 = S.run_audit({"outlets": outs}); mk = S.run_marketing({"pct": a.get("mk", 0), "alpha": 70})
    mi, mw, mp, ms, ma, mm = inv["m"], wf["m"], pn["m"], se["m"], au["m"], mk["m"]
    comp = [("Lost sales margin (stock-outs)", -(mi.get("loss", 0) - mi.get("loss_base", 0))), ("Overtime, temp cover, attrition, lost output", -mw.get("cost", 0)), ("Profit change from demand, price, costs", mp.get("profit_delta", 0)), ("Revenue lost to rating drop", -ms.get("rev_risk", 0)), ("Audit fines", -(ma.get("fines", 0) - au0["m"].get("fines", 0)))]
    total = sum(v for _, v in comp); days = len(mi.get("curve", []))
    other = (comp[1][1] + comp[2][1] + comp[3][1] + comp[4][1])
    cur = np.array(mi.get("curve", [0])); lo = np.array(mi.get("curve_lo", [0])); hi = np.array(mi.get("curve_hi", [0]))
    acc = other * np.linspace(1 / max(days, 1), 1, max(days, 1)); p50, p10, p90 = -(cur) + acc, -(hi) + acc, -(lo) + acc
    # mitigations
    cand = []; rows = mi.get("buf_rows", [])
    for b, lm, hold, tot in rows:
        if b in (.2, .4) and rows: cand.append(("Raise safety stock +%d%% on all SKUs" % (b * 100), rows[0][3] - tot, "holding cost included", "inventory"))
    for t in (.5, 1.0):
        if mw.get("model") and _num(a.get("absent")): cand.append((f"Cover {int(t * 100)}% of the staffing gap with temps", mw["model"](_num(a["absent"]) / 100, 10, 0) - mw["model"](_num(a["absent"]) / 100, 10, t), "temp wages included", "workforce"))
    if mp.get("model"): cand.append(("Raise prices 3%", mp["model"](_num(a.get("pct")) / 100, _num(a.get("price")) / 100 + .03, _num(a.get("cost")) / 100) - mp["model"](_num(a.get("pct")) / 100, _num(a.get("price")) / 100, _num(a.get("cost")) / 100), "volume loss from elasticity included", "outlets"))
    if _num(a.get("days")) >= 2:
        i2 = S.run_inventory({"pct": a.get("pct", 0), "days": max(0, _num(a["days"]) - 2), "buffer": 0, "cv": a.get("cv", 30), "outlets": outs}); cand.append(("Expedite suppliers: recover 2 days of lead time", mi["loss"] - i2["m"]["loss"], "expedite fees NOT modelled", "inventory"))
    if mm.get("uplift", 0) > 0: cand.append((f"Re-allocate marketing to the best channels (+{mm['uplift']:,.0f} conversions at the same spend)", 0.0, "conversions, not money", "marketing"))
    cand = sorted([c for c in cand if c[1] > 0 or c[3] == "marketing"], key=lambda r: -r[1])[:6]
    parts = [inv, wf, pn, mk, se, au]
    return {"inv_samples": mi.get("d_samples"), "comp": comp, "total": total, "p10": p10, "p50": p50, "p90": p90, "mit": cand, "blocks": {"inventory": inv["blocks"], "workforce": wf["blocks"], "outlets": pn["blocks"], "marketing": mk["blocks"], "sentiment": se["blocks"], "audit": au["blocks"]},
            "kpi": {"Fill rate": f"{mi.get('fill', 0):.1%}", "Lost sales margin": inr(comp[0][1]), "Profit change": inr(comp[2][1]), "Overtime/temp/attrition": inr(comp[1][1]), "Rating revenue at risk": inr(comp[3][1]), "Audit fines": inr(comp[4][1]), "TOTAL": inr(total)}, "fmt": inr, "unit": "₹"}
def _fq(a):
    import sim_fq as S; usd = S.usd; closures = a.get("closures") or []; area = a.get("area") or "None"
    rt = S.run_route({"closures": closures, "area": area, "wind": a.get("wind", 25), "add": a.get("add", 0)}); qt = S.run_quote({"pct": a.get("pct", 0), "carrier": a.get("carrier_cost", 0), "fx": a.get("fx", 0), "discount": 0, "elasticity": a.get("elasticity", 2)})
    cr = S.run_carrier({"carrier": a.get("carrier") if a.get("carrier") != "None" else "", "loss": a.get("loss", 100)}) if a.get("carrier") not in (None, "None") else {"m": {"extra": 0, "unplaced": 0, "displaced": 0}, "blocks": []}
    wx = S.run_weather({"area": area if area != "None" else "Red Sea", "wind": a.get("wind", 25)}) if area != "None" else {"m": {"cost": 0, "hit": 0}, "blocks": []}
    cu = S.run_customs({"hold": a.get("hold", 0), "dwell": a.get("dwell", 4), "storage": 180, "duty": 0}) if _num(a.get("hold")) else {"m": {"cost": 0, "held": 0}, "blocks": []}
    mr, mq, mc, mw, mu = rt["m"], qt["m"], cr["m"], wx["m"], cu["m"]
    comp = [("Longer / re-routed voyages", -mr.get("extra", 0)), ("Margin lost on quotes if prices are held", -mq.get("margin_loss", 0)), ("Carrier outage re-placement", -mc.get("extra", 0)), ("Storm delay + demurrage", -mw.get("cost", 0)), ("Customs hold storage", -mu.get("cost", 0))]
    total = sum(v for _, v in comp); cand = []
    if mq.get("best_gain", 0) > 0: cand.append((f"Reprice quotes by {mq['best_move']:+.0%} (expected-profit optimum)", mq["best_gain"], "uses the price-sensitivity setting", "quotes"))
    if _num(a.get("hold")): cu2 = S.run_customs({"hold": _num(a["hold"]) / 2, "dwell": a.get("dwell", 4), "storage": 180, "duty": 0}); cand.append(("Pre-clear customs documents (halves holds)", mu["cost"] - cu2["m"]["cost"], "document-prep effort not modelled", "customs"))
    if area != "None" and mw.get("cost", 0) > mr.get("extra", 0): cand.append(("Reroute vessels around the storm instead of waiting", mw["cost"] - mr.get("extra", 0), "assumes the route detour is cheaper than the delay", "route"))
    if mc.get("displaced", 0): cand.append(("Pre-book capacity with the top alternative carriers", mc["extra"] * 0.25, "assumes 25% saving from pre-booking", "carriers"))
    if mr.get("no_route", 0): cand.append((f"Open an alternative gateway: {mr['no_route']} lanes have no route", 0.0, "see Route AI for the lanes", "route"))
    cand = sorted(cand, key=lambda r: -r[1])[:6]
    return {"comp": comp, "total": total, "p10": None, "p50": None, "p90": None, "mit": cand, "blocks": {"route": rt["blocks"], "quotes": qt["blocks"], "carriers": cr["blocks"], "weather": wx["blocks"], "customs": cu["blocks"]},
            "kpi": {"Lanes re-routed": mr.get("rerouted", 0), "Lanes with no route": mr.get("no_route", 0), "Margin if prices held": f"{mq.get('margin_hold', 0):.1%}", "Quotes under 5% margin": mq.get("under5", 0), "Shipments held": mu.get("held", 0), "TOTAL": usd(total)}, "fmt": usd, "unit": "$"}
_SIG = {"Lost sales margin (stock-outs)": .0, "Overtime, temp cover, attrition, lost output": .25, "Profit change from demand, price, costs": .30, "Revenue lost to rating drop": .35, "Audit fines": .40,
        "Longer / re-routed voyages": .30, "Margin lost on quotes if prices are held": .25, "Carrier outage re-placement": .35, "Storm delay + demurrage": .40, "Customs hold storage": .30}
def _mc(kind, r, f, n=3000, rho=.4):
    """Joint Monte Carlo of the total impact. Inventory uses its own simulated futures; every other driver is its modelled value times a lognormal factor (spread in _SIG) that shares a common shock (rho)."""
    import mc; rng = np.random.default_rng(5); comp = r["comp"]; z0 = rng.standard_normal(n); cols = {}; d_inv = r.get("inv_samples")
    for i, (nm, v) in enumerate(comp):
        sg = _SIG.get(nm, .3)
        if d_inv is not None and i == 0 and len(d_inv): cols[nm] = -np.asarray(rng.choice(d_inv, n), float)
        elif sg > 0 and v != 0: cols[nm] = v * np.exp(sg * (np.sqrt(rho) * z0 + np.sqrt(1 - rho) * rng.standard_normal(n)) - sg * sg / 2)
        else: cols[nm] = np.full(n, float(v))
    tot = sum(cols.values()); unit = "money"; fan = None
    if r.get("p50") is not None and len(r["p50"]): x = [f"D{i + 1}" for i in range(len(r["p50"]))]; sc = tot[:, None] / max(abs(float(r["total"])), 1.0) * np.asarray(r["p50"], float)[None, :] if r["total"] else None; fan = (x, sc) if sc is not None else None
    tor = []
    for nm, v in cols.items():
        m_ = float(v.mean()); tor.append((nm[:34], float(np.percentile(v, 10)) - m_, float(np.percentile(v, 90)) - m_))
    bl, s = mc.panel("total impact (30 days)", tot, unit, "low", today=0.0, fan=fan, tornado=tor, key="mct", note="Inventory comes from its own simulated futures; every other driver is its modelled value with a stated uncertainty (±25–40%) and a shared shock (correlation 0.4), because bad things tend to arrive together.")
    return [B.md("### Monte Carlo risk analysis (all shocks together)")] + bl
def run(c, a):
    kind = c["kind"]; dom = c["dom"]; t = time.time(); r = _fr(a) if kind == "Franchise" else _fq(a); f = r["fmt"]; comp = pd.DataFrame(r["comp"], columns=["driver", "impact"]).sort_values("impact")
    bl = [B.callout("A private what-if: every model reads a copy of your live data. All the shocks you set apply together. Negative numbers are money lost versus today.", "info")]
    tot = r["total"]; bl.append(B.kpis(("Total impact", f(tot), "vs today, next 30 days" if kind == "Franchise" else "vs today", "Critical" if tot < 0 else "Low" if tot > 0 else None), *[(k, v) for k, v in list(r["kpi"].items())[:-1][:4]]))
    bl.append(B.row(B.card("What costs the most", B.chart(B.bar(comp.driver, {"impact": [round(x) for x in comp.impact]}, horizontal=True, itemcolors=[RED if x < 0 else TEAL for x in comp.impact]), h=280, key="t2_t")),
                    B.card("Cumulative impact over 30 days" if r["p50"] is not None else "Impact by driver", B.chart(B.line([f"D{i + 1}" for i in range(len(r["p50"]))], {"expected": [round(float(x)) for x in r["p50"]]}, band=([round(float(x)) for x in r["p10"]], [round(float(x)) for x in r["p90"]]), area=False, colors=[RED]), h=280, key="t2_c"), sub="Line = expected; shaded = 10th to 90th percentile across 100 simulated futures (uncertainty from stock-outs; other costs are spread evenly)") if r["p50"] is not None else B.card("Breakdown", B.table(comp, ["driver", B.num_col("impact", "impact", "money")], h=280, key="t2_b"))))
    try: bl += _mc(kind, r, f)
    except Exception as e:
        import traceback, sys; traceback.print_exc(file=sys.stderr); bl.append(B.callout(f"Monte Carlo panel skipped: {e}", "warn"))
    if r["mit"]:
        mrows = [{"action": m[0], "benefit": m[1], "note": m[2], "area": m[3]} for m in r["mit"]]
        bl.append(B.card("Best responses (ranked by money saved)", B.table(mrows, ["action", B.num_col("benefit", "benefit", "money"), "note", "area"], h=min(80 + 42 * len(mrows), 330), key="t2_m"),
                         B.form("t2_prop", [{"name": "action", "label": "Action to send for approval", "type": "select", "options": [m[0] for m in r["mit"]], "value": r["mit"][0][0]}, {"name": "detail", "type": "hidden", "value": json.dumps({"scenario": {k: v for k, v in a.items() if v not in (None, "", [], 0, 0.0, "None")}, "kind": kind})}], "Propose to the approval queue", "/api/twin/propose", tone="ghost", title=None),
                         sub="Benefits come from the same models, assumptions listed on each simulator. Proposing creates a ticket that a human approves or rejects."))
    if a.get("agents"):
        mut = _mut_fr(a) if kind == "Franchise" else _mut_fq(a)
        if mut:
            res = TW.compare(dom, mut, "stacked"); ag = res["agents"]; b, s = res["base"], res["scen"]
            bl.append(B.card("What the real agents say on the copy", B.kpis(("Health before", b["score"]), ("Health after", s["score"], f"{s['score'] - b['score']:+.1f}", "Critical" if s["score"] < b["score"] - 1 else None), ("New tickets", len(res["new_actions"])), ("Cleared", len(res["cleared_actions"]))), B.callout(s["narrative"], "info"),
                             B.table(ag, ["agent", B.num_col("before", "before", "num"), B.num_col("after", "after", "num"), B.num_col("delta", "Δ", "num"), B.pill_col("risk_before", "risk before"), B.pill_col("risk_after", "risk after")], h=260, key="t2_ag")))
            if res["new_actions"]: bl.append(B.table(pd.DataFrame(res["new_actions"])[["type", "target", "severity", "detail"]].head(30), ["type", "target", B.pill_col("severity"), "detail"], title="Tickets this scenario would raise", h=300, key="t2_na"))
        else: bl.append(B.callout("The real agents can only be re-run for shocks that change data (demand, lead time, absence, reviews, storm, congestion, fuel, customs). Closed chokepoints are handled by the route model above.", "info"))
    bl += [B.card(k.title() + " model", *v) for k, v in r["blocks"].items() if v]
    return bl, {"total": tot, "kpi": r["kpi"], "comp": r["comp"], "unit": r["unit"]}
def _db():
    with LE._DB_LOCK, LE.conn() as c: c.execute("CREATE TABLE IF NOT EXISTS twin_scenarios(name TEXT PRIMARY KEY, args TEXT, ts TEXT, by TEXT, result TEXT)")
def save(name, args, by, result):
    _db()
    with LE._DB_LOCK, LE.conn() as c: c.execute("INSERT OR REPLACE INTO twin_scenarios VALUES(?,?,?,?,?)", (name[:60], json.dumps(args), LE.now(), by, json.dumps(result, default=str)))
def saved(): _db(); return Q("SELECT name, ts, by, args, result FROM twin_scenarios ORDER BY ts DESC")
def propose(kind, action, detail, actor):
    try: sc = json.loads(detail)
    except Exception: sc = {}
    txt = f"Digital Twin recommends: {action}. Based on scenario {json.dumps(sc.get('scenario', {}))}. Approve to put it into action; nothing has been changed yet."
    a = {"type": "twin_mitigation", "target": "NETWORK", "detail": txt, "severity": "Info"}
    with LE._DB_LOCK, LE.conn() as c: c.execute("INSERT INTO agent_actions(ts,type,target,detail,severity,owner,due,source_cycle,note,status,approval) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (LE.now(), a["type"], a["target"], txt, "Info", "Operations", (__import__("datetime").datetime.now() + __import__("datetime").timedelta(hours=72)).isoformat(timespec="seconds"), "twin", "proposed by " + actor, "proposed", json.dumps(a)))
    LE.audit(actor, "twin_propose", action[:60], ""); return txt
