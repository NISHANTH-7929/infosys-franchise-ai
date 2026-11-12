"""Reports: print-ready PDFs (reportlab + matplotlib) and CSV exports built from the live database and the agents' latest output.
Every report has a cover band, KPI tiles, charts, tables, the Intelligence Engine narrative and a prioritised action list."""
import io, os, json, datetime
import pandas as pd, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether
from blocks import Q
import entities as EN
TEAL, BLUE, AMBER, RED, INK, MUT = "#0f9f8f", "#2f6fdb", "#d99a00", "#d64545", "#0f172a", "#64748b"
ss = getSampleStyleSheet()
ST = {"h1": ParagraphStyle("h1", parent=ss["Heading1"], fontSize=15, textColor=colors.HexColor(INK), spaceBefore=10, spaceAfter=6), "p": ParagraphStyle("p", parent=ss["Normal"], fontSize=9.5, leading=13.5, textColor=colors.HexColor("#1e293b")),
      "s": ParagraphStyle("s", parent=ss["Normal"], fontSize=8, textColor=colors.HexColor(MUT)), "c": ParagraphStyle("c", parent=ss["Normal"], fontSize=7.8, leading=9.5)}

def esc(t): return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def decision():
    d = Q("SELECT decision_id, ts, score, risk, narrative, evidence FROM decisions ORDER BY decision_id DESC LIMIT 1")
    if not len(d): return {"score": None, "risk": "-", "narrative": "", "ev": {}, "ts": ""}
    try: ev = json.loads(d.evidence[0])
    except Exception: ev = {}
    return {"score": float(d.score[0]), "risk": d.risk[0], "narrative": d.narrative[0], "ev": ev, "ts": d.ts[0]}
def money(v): return f"{v:,.0f}"

# ---------------------------------------------------------------- block helpers (each returns reportlab flowables)
def H(t): return [Paragraph(esc(t), ST["h1"])]
def P(t, style="p"): return [Paragraph(esc(t).replace("\n", "<br/>"), ST[style])]
def KPI(items):
    cells = [[Paragraph(f'<font size="7.5" color="{MUT}">{esc(l).upper()}</font><br/><font size="15" color="{INK}"><b>{esc(v)}</b></font>' + (f'<br/><font size="7.5" color="{MUT}">{esc(s)}</font>' if s else ""), ST["p"]) for l, v, s in items]]
    t = Table(cells, colWidths=[(A4[0] - 36 * mm) / len(items)] * len(items)); t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, colors.HexColor("#cbd5e1")), ("INNERGRID", (0, 0), (-1, -1), .6, colors.HexColor("#e2e8f0")), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LEFTPADDING", (0, 0), (-1, -1), 9)])); return [t, Spacer(1, 8)]
def TBL(df, cols=None, widths=None, maxrows=25, tone_col=None):
    if df is None or not len(df): return P("No records.", "s")
    cols = cols or list(df.columns); df = df.head(maxrows)
    data = [[Paragraph(f"<b>{esc(c).replace('_', ' ')}</b>", ST["c"]) for c in cols]] + [[Paragraph(esc(f"{v:,.2f}" if isinstance(v, float) else v), ST["c"]) for v in r] for r in df[cols].itertuples(index=False)]
    w = widths or [(A4[0] - 36 * mm) / len(cols)] * len(cols); t = Table(data, colWidths=w, repeatRows=1)
    sty = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#cbd5e1")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for i in range(1, len(data)):
        if i % 2 == 0: sty.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8fafc")))
    if tone_col in cols:
        j = cols.index(tone_col)
        for i, v in enumerate(df[tone_col].tolist(), 1):
            col = {"Critical": RED, "High": RED, "Fail": RED, "Warning": AMBER, "Medium": AMBER, "Info": BLUE}.get(str(v))
            if col: sty.append(("TEXTCOLOR", (j, i), (j, i), colors.HexColor(col)))
    t.setStyle(TableStyle(sty)); return [t, Spacer(1, 8)]
def FIG(fn, w=170, h=62):
    fig, ax = plt.subplots(figsize=(w / 25.4, h / 25.4), dpi=170); fn(ax); ax.spines[["top", "right"]].set_visible(False); ax.tick_params(labelsize=7); ax.title.set_fontsize(8.5)
    for s in ax.spines.values(): s.set_color("#94a3b8")
    fig.tight_layout(); b = io.BytesIO(); fig.savefig(b, format="png"); plt.close(fig); b.seek(0); return [Image(b, width=w * mm, height=h * mm), Spacer(1, 6)]
def barh(labels, vals, colors_=None, title="", fmt="{:.0f}", xmax=None):
    def f(ax):
        y = np.arange(len(labels)); ax.barh(y, vals, color=colors_ or TEAL, height=.62); ax.set_yticks(y); ax.set_yticklabels(labels); ax.invert_yaxis(); ax.set_title(title, loc="left", fontweight="bold")
        for i, v in enumerate(vals): ax.text(v, i, " " + fmt.format(v), va="center", fontsize=6.5, color=INK)
        if xmax: ax.set_xlim(0, xmax)
    return f
def colbar(labels, vals, colors_=None, title=""):
    def f(ax): ax.bar(labels, vals, color=colors_ or BLUE, width=.6); ax.set_title(title, loc="left", fontweight="bold"); ax.grid(axis="y", alpha=.25)
    return f
def linef(x, ys, title="", names=None, cols=None):
    def f(ax):
        for i, y in enumerate(ys): ax.plot(x, y, color=(cols or [TEAL, BLUE, AMBER])[i], lw=1.8, label=(names or [None] * 9)[i])
        ax.set_title(title, loc="left", fontweight="bold"); ax.grid(alpha=.25)
        if names: ax.legend(fontsize=6.5, frameon=False)
        n = len(x); ax.set_xticks(list(range(0, n, max(1, n // 8))))
    return f
def hcol(h): return RED if h < 60 else AMBER if h < 80 else TEAL
def actions(target_like=None, types=None, limit=15, scope=None):
    sql = "SELECT action_id id, severity, type, target, detail, owner, assignee, due, status FROM agent_actions WHERE status IN ('open','proposed')"; p = []
    if scope: sql += " AND target LIKE ?"; p.append(scope + "%")
    if target_like: sql += " AND target LIKE ?"; p.append(target_like + "%")
    if types: sql += " AND type IN (%s)" % ",".join("?" * len(types)); p += list(types)
    sql += " ORDER BY CASE severity WHEN 'Critical' THEN 0 WHEN 'Warning' THEN 1 ELSE 2 END, action_id DESC LIMIT %d" % limit; df = Q(sql, tuple(p))
    if len(df): df["due"] = df.due.fillna("").str[:10]; df["owner"] = df.owner.fillna("-")
    return df
def ACTIONS(df, title="Prioritised action list (open tickets)"):
    out = H(title)
    if df is None or not len(df): return out + P("No open actions. Everything raised by the agents is resolved.", "s")
    return out + TBL(df, ["id", "severity", "type", "target", "detail", "owner", "due"], [14 * mm, 17 * mm, 28 * mm, 20 * mm, 60 * mm, 20 * mm, 15 * mm], 30, "severity")

# ---------------------------------------------------------------- Franchise reports
def fr_exec(c):
    d = decision(); ev = d["ev"]; hl = ev.get("health", {}); out = []
    o = Q("SELECT outlet_id, outlet_name, location, tier, revenue, operating_costs, customer_satisfaction csat, staff_headcount hc FROM outlets"); o["health"] = o.outlet_id.map(hl).astype(float).round(1)
    t = Q("SELECT severity, COUNT(*) n FROM agent_actions WHERE status IN ('open','proposed') GROUP BY severity").set_index("severity").n.to_dict(); sc = d["score"]
    out += KPI([("Network health", f"{sc:.1f}" if sc is not None else "-", d["risk"] + " risk"), ("Outlets", len(o), f"{int((o.health < 60).sum())} below 60"), ("Revenue", money(o.revenue.sum()), f"margin {100 * (1 - o.operating_costs.sum() / max(o.revenue.sum(), 1)):.0f}%"), ("Open actions", sum(t.values()), f"{t.get('Critical', 0)} critical")])
    out += H("Intelligence Engine summary") + P(d["narrative"] or "No decision yet.")
    ob = o.dropna(subset=["health"]); b = ob.sort_values("health").head(10)
    out += H("Outlet benchmark: ten weakest outlets") + FIG(barh(b.outlet_id + " " + b.location.str[:14], b.health.values, [hcol(x) for x in b.health], "Health score (0-100)", "{:.1f}", 100), h=66) + TBL(b, ["outlet_id", "outlet_name", "location", "health", "csat", "hc"], maxrows=10)
    top = ob.sort_values("health", ascending=False).head(5); out += H("Growth opportunities") + P("Outlets that are the network's best operators. Their routines are the playbook for the weakest outlets above.") + TBL(top, ["outlet_id", "outlet_name", "location", "health", "csat", "revenue"], maxrows=5)
    mk = Q("SELECT channel, ROUND(AVG(actual_roi),1) roi, COUNT(*) n FROM marketing GROUP BY channel ORDER BY roi DESC")
    if len(mk): out += FIG(colbar(mk.channel, mk.roi, TEAL, "Average campaign ROI by channel (%)"), h=50) + P(f"Best channel: {mk.channel[0]} ({mk.roi[0]}% ROI). Shift budget from {mk.channel.iloc[-1]} ({mk.roi.iloc[-1]}%).")
    ag = Q("SELECT agent, risk, summary FROM agent_runs WHERE run_id IN (SELECT MAX(run_id) FROM agent_runs GROUP BY agent)"); out += H("What each agent found") + TBL(ag, ["agent", "risk", "summary"], [24 * mm, 18 * mm, 124 * mm], 12, "risk")
    return out + ACTIONS(actions(limit=12, scope=c.get("scope")))
def fr_outlet(c, oid):
    o = Q("SELECT * FROM outlets WHERE outlet_id=?", (oid,))
    if not len(o): return P("Unknown outlet.")
    r = o.iloc[0]; d = decision(); h = d["ev"].get("health", {}).get(oid); out = KPI([("Health", f"{h:.1f}" if h is not None else "-", None), ("Revenue", money(r.revenue), None), ("Satisfaction", f"{r.customer_satisfaction:.2f}", "of 5"), ("Headcount", int(r.staff_headcount), None)])
    out += P(f"{r.outlet_name} · {r.location} · tier {r.tier}", "s"); bd = {}
    for a in ("outlet", "inventory", "staff", "marketing", "audit", "feedback"):
        v = EN.latest_out(a).get("per_outlet", {}).get(oid)
        if v is not None: bd[a] = round(v, 1)
    if bd: out += H("Why this score") + FIG(barh(list(bd), list(bd.values()), [hcol(v) for v in bd.values()], "Agent sub-scores", "{:.0f}", 100), h=52)
    s = Q("SELECT substr(ts,12,5) t, amount FROM sales WHERE outlet_id=? ORDER BY sale_id DESC LIMIT 60", (oid,)).iloc[::-1]
    if len(s): out += FIG(linef(s.t.tolist(), [s.amount.tolist()], "Latest sales (per tick)"), h=45)
    inv = Q("SELECT sku_name, current_stock stock, weekly_demand wk, lead_time_days lead, ROUND(current_stock*7.0/MAX(weekly_demand,1),1) cover_days FROM inventory WHERE outlet_id=? ORDER BY cover_days LIMIT 8", (oid,)); out += H("Lowest stock cover") + TBL(inv)
    au = Q("SELECT audit_date, score, violations, category, status FROM audits WHERE outlet_id=? ORDER BY audit_date DESC LIMIT 6", (oid,)); out += H("Recent audits") + TBL(au)
    fb = Q("SELECT date, rating, comment FROM feedback WHERE outlet_id=? ORDER BY date DESC LIMIT 6", (oid,)); out += H("Recent customer feedback") + TBL(fb, widths=[22 * mm, 14 * mm, 136 * mm])
    return out + ACTIONS(actions(oid), f"Action plan for {oid}")
def fr_inventory(c):
    i = Q("SELECT outlet_id, sku_name, category, current_stock stock, reorder_threshold thr, weekly_demand wk, lead_time_days lead, ROUND(stockout_risk_prob*100,0) risk_pct, ROUND(current_stock*7.0/MAX(weekly_demand,1),1) cover_days FROM inventory")
    if c.get("scope"): i = i[i.outlet_id == c["scope"]]
    short = i[i.stock <= i.thr]; out = KPI([("SKUs tracked", len(i), None), ("Below reorder point", len(short), f"{100 * len(short) / max(len(i), 1):.0f}%"), ("Avg cover", f"{i.cover_days.mean():.1f} d", None), ("Stock-out risk > 50%", int((i.risk_pct > 50).sum()), None)])
    cat = i.groupby("category").apply(lambda g: (g.stock <= g.thr).mean() * 100).sort_values(); out += FIG(barh(cat.index.tolist(), cat.values, AMBER, "Share of SKUs below reorder point, by category (%)", "{:.0f}", 100), h=55)
    out += H("Most urgent SKUs") + TBL(short.sort_values("cover_days").head(25), ["outlet_id", "sku_name", "stock", "thr", "cover_days", "lead", "risk_pct"])
    po = Q("SELECT po_id, outlet_id, sku_name, qty, status, eta_ts FROM purchase_orders ORDER BY ts DESC LIMIT 15"); out += H("Replenishment orders raised by the Inventory agent") + TBL(po)
    return out + ACTIONS(actions(types=("reorder", "pause_promo"), limit=15, scope=c.get("scope")), "Replenishment actions")
def fr_workforce(c):
    s = Q("SELECT staff_id, outlet_id, name, role, overtime_hrs, job_satisfaction, tenure_years, ROUND(predicted_attrition_prob*100,0) risk_pct FROM staff")
    if c.get("scope"): s = s[s.outlet_id == c["scope"]]
    hi = s[s.risk_pct >= 60]; out = KPI([("Employees", len(s), None), ("High attrition risk", len(hi), f"{100 * len(hi) / max(len(s), 1):.0f}%"), ("Avg overtime", f"{s.overtime_hrs.mean():.1f} h", None), ("Avg satisfaction", f"{s.job_satisfaction.mean():.1f}", "of 4")])
    out += FIG(lambda ax: (ax.hist(s.risk_pct, bins=20, color=BLUE), ax.set_title("Attrition risk distribution (%)", loc="left", fontweight="bold")), h=50)
    g = s.groupby("outlet_id").risk_pct.mean().sort_values(ascending=False).head(10); out += FIG(barh(g.index.tolist(), g.values, AMBER, "Outlets with the highest average attrition risk (%)", "{:.0f}", 100), h=58)
    out += H("Highest-risk employees") + TBL(hi.sort_values("risk_pct", ascending=False), ["staff_id", "outlet_id", "name", "role", "overtime_hrs", "job_satisfaction", "risk_pct"], maxrows=25)
    return out + ACTIONS(actions(types=("staffing_shortage", "retention_plan"), limit=15, scope=c.get("scope")), "Workforce recommendations")
def fr_marketing(c):
    m = Q("SELECT outlet_id, campaign_name, channel, budget, actual_roi, reach, conversions FROM marketing")
    if c.get("scope"): m = m[m.outlet_id == c["scope"]]
    m["cost_per_conv"] = (m.budget / m.conversions.clip(lower=1)).round(1); ch = m.groupby("channel").agg(budget=("budget", "sum"), roi=("actual_roi", "mean"), conv=("conversions", "sum")).sort_values("roi", ascending=False).reset_index()
    out = KPI([("Campaigns", len(m), None), ("Total budget", money(m.budget.sum()), None), ("Avg ROI", f"{m.actual_roi.mean():.1f}%", None), ("Conversions", money(m.conversions.sum()), None)])
    out += FIG(colbar(ch.channel, ch.roi, [TEAL if v >= 0 else RED for v in ch.roi], "ROI by channel (%)"), h=52) + TBL(ch.round(1)); w = m.sort_values("actual_roi").head(12)
    out += H("Weakest campaigns: recommend pausing or reworking") + TBL(w, ["outlet_id", "campaign_name", "channel", "budget", "actual_roi", "cost_per_conv"]); b = m.sort_values("actual_roi", ascending=False).head(8); out += H("Best campaigns: recommend scaling") + TBL(b, ["outlet_id", "campaign_name", "channel", "budget", "actual_roi", "cost_per_conv"])
    return out + ACTIONS(actions(types=("pause_promo", "reallocate_budget", "win_back_campaign"), limit=12, scope=c.get("scope")), "Marketing actions")
def fr_audit(c):
    a = Q("SELECT outlet_id, audit_date, score, violations, category, status, notes FROM audits")
    if c.get("scope"): a = a[a.outlet_id == c["scope"]]
    last = a.sort_values("audit_date").groupby("outlet_id").tail(1); out = KPI([("Audits on file", len(a), None), ("Latest avg score", f"{last.score.mean():.1f}", None), ("Failing outlets", int((last.score < 60).sum()), None), ("Open violations", int(last.violations.sum()), None)])
    cat = a.groupby("category").score.mean().sort_values(); out += FIG(barh(cat.index.tolist(), cat.values, [hcol(v) for v in cat.values], "Average score by audit category", "{:.0f}", 100), h=55)
    out += H("Lowest-scoring outlets (latest audit)") + TBL(last.sort_values("score").head(15), ["outlet_id", "audit_date", "score", "violations", "category", "status", "notes"], [18 * mm, 20 * mm, 12 * mm, 16 * mm, 24 * mm, 17 * mm, 59 * mm])
    ca = Q("SELECT action_id id, severity, target, detail, status, owner, due FROM agent_actions WHERE type='corrective_action' ORDER BY action_id DESC LIMIT 30"); out += H("Corrective actions tracker") + TBL(ca, ["id", "severity", "target", "detail", "status", "owner", "due"], [14 * mm, 17 * mm, 20 * mm, 68 * mm, 17 * mm, 20 * mm, 15 * mm], 30, "severity")
    return out
def fr_plan(c):
    df = actions(limit=400, scope=c.get("scope")); out = KPI([("Open actions", len(df), None), ("Critical", int((df.severity == "Critical").sum()) if len(df) else 0, None), ("Awaiting approval", int((df.status == "proposed").sum()) if len(df) else 0, None), ("Outlets affected", df.target.nunique() if len(df) else 0, None)])
    out += P("A franchise action plan: every open item the agents raised, grouped by outlet, most severe first, with the owner and due date. Items marked proposed need a human approval before the system executes them.")
    if not len(df): return out
    rank = df.groupby("target").apply(lambda g: (g.severity == "Critical").sum() * 10 + len(g)).sort_values(ascending=False).head(12)
    for t in rank.index:
        g = df[df.target == t]; out.append(KeepTogether([Paragraph(f"<b>{esc(t)}</b> · {len(g)} action(s)", ST["p"])] + TBL(g, ["id", "severity", "type", "detail", "owner", "due"], [12 * mm, 17 * mm, 28 * mm, 80 * mm, 20 * mm, 17 * mm], 10, "severity")))
    return out

# ---------------------------------------------------------------- Freight reports
def fq_exec(c):
    d = decision(); q = Q("SELECT quote_id, customer_id, carrier, base_cost, final_price, margin_pct, status, created_at FROM freight_quotes"); sh = Q("SELECT status, COUNT(*) n FROM shipments GROUP BY status")
    t = Q("SELECT severity, COUNT(*) n FROM agent_actions WHERE status IN ('open','proposed') GROUP BY severity").set_index("severity").n.to_dict(); appr = q[q.status == "Approved"]
    out = KPI([("Fleet health", f"{d['score']:.1f}" if d["score"] is not None else "-", d["risk"] + " risk"), ("Quotes", len(q), f"{len(appr)} approved"), ("Quoted value", money(q.final_price.sum()), "USD"), ("Avg margin", f"{q.margin_pct.mean():.1f}%" if len(q) else "-", None), ("Open actions", sum(t.values()), f"{t.get('Critical', 0)} critical")])
    out += H("Intelligence Engine summary") + P(d["narrative"] or "No decision yet.")
    if len(sh): out += FIG(colbar(sh.status, sh.n, BLUE, "Shipments by status"), h=48)
    if len(q): s = q.status.value_counts(); out += FIG(colbar(s.index, s.values, [TEAL if i == "Approved" else AMBER if "Pending" in i else RED if i == "On Hold" else "#94a3b8" for i in s.index], "Quotes by status"), h=48)
    cg = Q("SELECT name, ROUND(on_time_pct,1) on_time, ROUND(avg_cost_index,2) cost_index, risk_level FROM carriers ORDER BY on_time_pct DESC LIMIT 8"); out += H("Carrier scorecard (top 8 on-time)") + TBL(cg, tone_col="risk_level")
    ag = Q("SELECT agent, risk, summary FROM agent_runs WHERE run_id IN (SELECT MAX(run_id) FROM agent_runs GROUP BY agent)"); out += H("What each agent found") + TBL(ag, ["agent", "risk", "summary"], [28 * mm, 18 * mm, 120 * mm], 12, "risk")
    return out + ACTIONS(actions(limit=12))
def fq_quotation(c, qid):
    q = Q("SELECT * FROM freight_quotes WHERE quote_id=?", (qid,))
    if not len(q): return P("Quote not found.")
    r = q.iloc[0]; s = Q("SELECT origin_port, dest_port, eta, weight_kg, hs_code, carrier FROM shipments WHERE shipment_id=?", (r.shipment_id,)); cu = Q("SELECT name, industry FROM customers WHERE customer_id=?", (r.customer_id,)); nm = cu.name[0] if len(cu) else r.customer_id
    out = KPI([("Quote", r.quote_id, r.status), ("Total price", f"USD {r.final_price:,.0f}", "all-in"), ("Carrier", r.carrier or (s.carrier[0] if len(s) and "carrier" in s else "To be assigned"), None)]) + P(f"Prepared for {nm} on {str(r.created_at)[:10]}. Valid for 7 days.", "s")
    if len(s): x = s.iloc[0]; out += H("Shipment") + TBL(pd.DataFrame([{"origin": x.origin_port, "destination": x.dest_port, "ETA": str(x.eta)[:10], "weight_kg": x.weight_kg, "HS code": x.hs_code}]))
    rows = [("Base freight", r.base_cost), ("Insurance", r.insurance), ("Customs handling", r.customs_fee), ("Fuel surcharge", r.fuel_surcharge)]; sub = sum(v for _, v in rows); rows += [("Brokerage margin", r.final_price - sub), ("TOTAL", r.final_price)]
    out += H("Price breakdown (USD)") + TBL(pd.DataFrame([{"item": a, "amount": f"{b:,.2f}"} for a, b in rows]), widths=[110 * mm, 60 * mm]) + FIG(lambda ax: (ax.pie([max(v, 0) for _, v in rows[:-1]], labels=[a for a, _ in rows[:-1]], colors=[BLUE, TEAL, AMBER, "#8b5cf6", "#94a3b8"], autopct="%1.0f%%", textprops={"fontsize": 7}), ax.set_title("Where the price goes", loc="left", fontweight="bold")), h=62)
    return out + P("Terms: rates are valid for 7 days and subject to space and equipment availability. Weather or customs events can change transit time; the platform re-plans automatically and will notify you. Customs documents listed in the shipment record must be provided before sailing.", "s")
def fq_route(c):
    p = Q("SELECT port_name, country, ROUND(congestion_index,2) congestion, ROUND(avg_dwell_days,1) dwell_days, region FROM ports ORDER BY congestion_index DESC"); sh = Q("SELECT status, COUNT(*) n FROM shipments GROUP BY status"); v = Q("SELECT COUNT(*) n, ROUND(AVG(speed_kn),1) sp FROM vessels")
    out = KPI([("Ports tracked", len(p), None), ("Congested (>=4)", int((p.congestion >= 4).sum()), None), ("Vessels", int(v.n[0]), f"avg {v.sp[0]} kn"), ("Avg dwell", f"{p.dwell_days.mean():.1f} d", None)])
    t = p.head(12); out += FIG(barh(t.port_name.tolist(), t.congestion.values, [RED if x >= 4 else AMBER for x in t.congestion], "Most congested ports (index 0-5)", "{:.2f}", 5), h=62) + TBL(t, ["port_name", "country", "region", "congestion", "dwell_days"])
    cg = Q("SELECT name, ROUND(on_time_pct,1) on_time, ROUND(avg_cost_index,2) cost_index, rating, risk_level FROM carriers ORDER BY on_time_pct DESC LIMIT 12"); out += H("Carrier comparison") + TBL(cg, tone_col="risk_level")
    return out + ACTIONS(actions(types=("reroute", "congestion_notice"), limit=15), "Route actions")
def fq_risk(c):
    w = Q("SELECT port_name, current_severity sev, wind_speed, wave_height FROM weather_risks ORDER BY wind_speed DESC"); s = Q("SELECT s.shipment_id, s.origin_port, s.dest_port, s.carrier, ROUND(s.predicted_delay_risk*100,0) delay_risk_pct, s.status FROM shipments s ORDER BY s.predicted_delay_risk DESC LIMIT 20")
    lv = w.sev.value_counts(); out = KPI([("Ports monitored", len(w), None), ("High severity", int(lv.get("High", 0)), None), ("Max wind", f"{w.wind_speed.max():.0f} km/h" if len(w) else "-", None), ("High delay-risk shipments", int((s.delay_risk_pct >= 60).sum()), None)])
    t = w.head(12); out += FIG(barh(t.port_name.tolist(), t.wind_speed.values, [RED if x == "High" else AMBER if x == "Medium" else TEAL for x in t.sev], "Strongest port winds (km/h)", "{:.0f}"), h=62)
    out += H("Shipments with the highest predicted delay risk") + TBL(s) + ACTIONS(actions(types=("reroute",), limit=15), "Risk alerts and re-routes")
    return out
def fq_customs(c):
    sh = Q("SELECT shipment_id, origin_port, dest_port, hs_code, status FROM shipments"); hold = sh[sh.status.str.contains("Customs|Hold", case=False, na=False)]; cr = pd.DataFrame()
    try: cr = Q("SELECT * FROM customs_rules LIMIT 20")
    except Exception: pass
    out = KPI([("Shipments", len(sh), None), ("On customs hold", len(hold), f"{100 * len(hold) / max(len(sh), 1):.0f}%"), ("Delivered", int((sh.status == "Delivered").sum()) if len(sh) else 0, None)]) + H("Shipments on customs hold") + TBL(hold, maxrows=25)
    if len(cr): out += H("Customs rules in force") + TBL(cr, maxrows=20)
    return out + ACTIONS(actions(types=("customs_docs",), limit=20), "Customs readiness actions")
def fq_margin(c):
    q = Q("SELECT quote_id, customer_id, carrier, base_cost, final_price, margin_pct, status FROM freight_quotes"); out = KPI([("Quotes", len(q), None), ("Avg margin", f"{q.margin_pct.mean():.1f}%" if len(q) else "-", None), ("Gross profit", money((q.final_price - q.base_cost).sum()), "USD"), ("Low margin (<10%)", int((q.margin_pct < 10).sum()), None)])
    if len(q):
        out += FIG(lambda ax: (ax.scatter(q.base_cost, q.final_price, s=14, c=[RED if m < 10 else TEAL for m in q.margin_pct]), ax.set_xlabel("base cost", fontsize=7), ax.set_ylabel("price", fontsize=7), ax.set_title("Price vs base cost (red = margin under 10%)", loc="left", fontweight="bold")), h=62)
        g = q.assign(profit=q.final_price - q.base_cost).groupby("customer_id").agg(quotes=("quote_id", "count"), profit=("profit", "sum"), margin=("margin_pct", "mean")).sort_values("margin").head(10).round(1).reset_index(); out += H("Lowest-margin customers") + TBL(g)
        g = q.groupby("carrier").agg(quotes=("quote_id", "count"), margin=("margin_pct", "mean")).round(1).reset_index().sort_values("margin"); out += H("Brokerage performance by carrier") + TBL(g)
    return out + ACTIONS(actions(types=("margin_review", "quote_approval", "quote_hold", "quote_anomaly"), limit=15), "Pricing actions")

REPORTS = {
    "Franchise": [("fr_exec", "Executive franchise report", "Network health, outlet benchmark, growth opportunities, agent findings, action list.", fr_exec, None), ("fr_outlet", "Outlet performance report", "One outlet: score breakdown, sales, stock cover, audits, feedback, action plan.", fr_outlet, "outlet"),
                  ("fr_inventory", "Inventory report", "Stock shortages, cover days, replenishment orders.", fr_inventory, None), ("fr_workforce", "Workforce report", "Attrition risk, overtime, recommendations.", fr_workforce, None), ("fr_marketing", "Marketing ROI report", "ROI by channel, best and weakest campaigns.", fr_marketing, None),
                  ("fr_audit", "Audit & compliance report", "Scores, violations, corrective-action tracker.", fr_audit, None), ("fr_plan", "Franchise action plan", "Every open item grouped by outlet with owners and due dates.", fr_plan, None)],
    "Freight": [("fq_exec", "Executive brokerage report", "Fleet health, quotes, carriers, agent findings, action list.", fq_exec, None), ("fq_quotation", "Customer quotation (PDF)", "Customer-facing quote with price breakdown and terms.", fq_quotation, "quote"),
                ("fq_route", "Route intelligence report", "Port congestion, carrier comparison, route actions.", fq_route, None), ("fq_risk", "Shipment risk report", "Weather exposure and highest delay-risk shipments.", fq_risk, None),
                ("fq_customs", "Customs readiness report", "Shipments on hold, rules in force, document actions.", fq_customs, None), ("fq_margin", "Margin & brokerage performance", "Profit, low-margin quotes and customers, carrier margin.", fq_margin, None)]}

def build_pdf(kind, rid, c, arg=None):
    spec = next((r for r in REPORTS[kind] if r[0] == rid), None)
    if not spec: raise KeyError(rid)
    name, title = spec[1], spec[1]; ctx = c or {}
    try: body = spec[3](ctx, arg) if spec[4] else spec[3](ctx)
    except Exception as e: body = P(f"This section could not be built: {e}")
    buf = io.BytesIO(); W, Hh = A4; plat = "FranchiseOps AI" if kind == "Franchise" else "FreightQuote AI"; gen = datetime.datetime.now().strftime("%d %b %Y %H:%M")
    def deco(cv, doc):
        cv.saveState(); cv.setFillColor(colors.HexColor("#0b1220")); cv.rect(0, Hh - 24 * mm, W, 24 * mm, fill=1, stroke=0); cv.setFillColor(colors.HexColor("#2dd4bf")); cv.rect(0, Hh - 24 * mm, 6 * mm, 24 * mm, fill=1, stroke=0)
        cv.setFillColor(colors.white); cv.setFont("Helvetica-Bold", 15); cv.drawString(14 * mm, Hh - 12 * mm, title + (f" · {arg}" if arg else "")); cv.setFont("Helvetica", 8.5); cv.setFillColor(colors.HexColor("#9fb0c3")); cv.drawString(14 * mm, Hh - 18 * mm, f"{plat} · generated {gen} by the agent network" + (f" · scope {ctx['scope']}" if ctx.get("scope") else ""))
        cv.setFillColor(colors.HexColor(MUT)); cv.setFont("Helvetica", 7.5); cv.drawString(18 * mm, 10 * mm, f"{plat} · confidential"); cv.drawRightString(W - 18 * mm, 10 * mm, f"Page {doc.page}"); cv.restoreState()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=30 * mm, bottomMargin=16 * mm, title=title, author=plat); doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(18 * mm, 16 * mm, W - 36 * mm, Hh - 46 * mm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=deco)])
    doc.build([Spacer(1, 2)] + body); safe = (rid + ("_" + str(arg) if arg else "") + "_" + datetime.date.today().isoformat()).replace(" ", "_"); return safe + ".pdf", buf.getvalue()

EXPORTS = {"Franchise": {"outlets": "SELECT * FROM outlets", "staff": "SELECT * FROM staff", "inventory": "SELECT * FROM inventory", "marketing": "SELECT * FROM marketing", "audits": "SELECT * FROM audits", "feedback": "SELECT * FROM feedback", "sales_latest": "SELECT * FROM sales ORDER BY sale_id DESC LIMIT 20000", "tickets": "SELECT * FROM agent_actions ORDER BY action_id DESC"},
           "Freight": {"quotes": "SELECT * FROM freight_quotes", "shipments": "SELECT * FROM shipments", "ports": "SELECT * FROM ports", "carriers": "SELECT * FROM carriers", "customers": "SELECT * FROM customers", "vessels": "SELECT * FROM vessels", "weather": "SELECT * FROM weather_risks", "tickets": "SELECT * FROM agent_actions ORDER BY action_id DESC"}}
def export_csv(kind, table, scope=None):
    sql = EXPORTS[kind][table]; df = Q(sql)
    if scope and "outlet_id" in df.columns: df = df[df.outlet_id == scope]
    if scope and table == "tickets": df = df[df.target.astype(str).str.startswith(scope)]
    return df.to_csv(index=False).encode()
