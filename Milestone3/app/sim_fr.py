"""Franchise simulators (Milestone 3). One model per agent; every model reads its starting values from the live tables, never writes to them,
lists its assumptions, shows a 10th to 90th percentile range instead of a single number, and takes a seed so a run can be repeated exactly.

    run_X(a) -> {"blocks": [...], "m": {metrics used by the Digital Twin and by mc_sims.py}}

Seed: every random draw comes from numpy's default_rng(seed + a fixed offset), so the same seed gives the same numbers, and the baseline and the
scenario of one run share their random numbers (the difference between them is the effect of the change, not noise). Default seed = 42.

What Milestone 3 added to each simulator (the modelling ideas of the team's stand-alone prototype were rebuilt on the database):
  Inventory  demand seasonality, random supplier delays, stock-out probability and service level, three reorder rules compared
  Workforce  attrition by tenure band, hiring lead time, overtime versus hiring cost
  P&L        price elasticity, wage and rent inflation, best and worst case band
  Marketing  diminishing returns plus campaign fatigue, ROI by channel with a range
  Sentiment  what fixing the most common complaint does to CSAT and repeat visits
  Audit      chance of failing the next audit from the open findings and the days needed to become compliant"""
import numpy as np, pandas as pd
import blocks as B
from blocks import Q, TEAL, BLUE, AMBER, RED, VIOLET
GREY = "#8b8d98"
DEFAULT_SEED = 42


def g(a, k, d):
    try: return float(a.get(k, d))
    except Exception: return float(d)
def inr(x):
    x = float(x); s = "-" if x < 0 else ""; x = abs(x)
    return s + ("₹%.2f Cr" % (x / 1e7) if x >= 1e7 else "₹%.2f L" % (x / 1e5) if x >= 1e5 else "₹{:,.0f}".format(x))
def seed_of(a): return int(g(a, "seed", DEFAULT_SEED))
def rng_of(a, salt=0): return np.random.default_rng(seed_of(a) * 1000 + salt)
def pr(v, lo=10, hi=90):
    """(P10, P50, P90) of a sample."""
    v = np.asarray(v, dtype=float); return float(np.percentile(v, lo)), float(np.percentile(v, 50)), float(np.percentile(v, hi))
def rng_txt(v, f=inr):
    p10, p50, p90 = pr(v); return f"P10–P90 {f(p10)} – {f(p90)}"


ASSUME = {
    "inventory": ["Daily demand per SKU is random (volatility is a setting) around its weekly demand from the database, with a shared ±10% demand swing across SKUs.",
                  "Seasonality: a weekly pattern (weekend peak) and a month-long festive swing, scaled by the strength you choose; the average demand stays the same.",
                  "A reorder is placed when stock reaches the reorder level and arrives after the lead time plus a random supplier delay (Poisson, mean = the delay setting).",
                  "Unit value = annualised outlet revenue ÷ units demanded; gross margin = 1 − operating costs ÷ revenue. Holding cost = 25% of stock value per year.",
                  "100 simulated 30-day futures per SKU; baseline and scenario use the same random numbers. Three reorder rules are compared on the same futures."],
    "workforce": ["Hourly wage = salary ÷ 160; overtime pays 1.5×, temp cover 1.3×. Each overtime hour per person per week adds 0.4 points of attrition.",
                  "Annual attrition by tenure band (under 1 year 30%, 1–3 years 20%, 3–5 years 12%, 5+ years 7%) is averaged with each person's predicted attrition probability from the database.",
                  "Replacing a leaver costs 50% of annual pay; a vacancy lasts the hiring lead time (weeks, a setting) and is covered with overtime.",
                  "Without hiring, the leaver's work is covered with overtime for the rest of the year; the extra overtime lifts attrition among the people who stay.",
                  "2,000 simulated years of who leaves; uncovered hours cost revenue in proportion to the lost labour share (80% productivity)."],
    "outlets": ["Revenue and costs in the outlets table are treated as monthly. 65% of operating costs vary with volume, the rest are fixed.",
                "Price elasticity (setting, default −1.2): a 1% price rise cuts volume by 1.2%.",
                "Wages are 40% and rent 15% of operating costs; wage inflation is drawn from the band you set and rent inflation around your value.",
                "Best case = low end of the wage band and elasticity 0.4 closer to zero; worst case = high end of the band and elasticity 0.4 further from zero.",
                "2,000 simulated months sample wage inflation, rent inflation and elasticity; the range shown is P10 to P90."],
    "marketing": ["Conversions = k · budget^α per channel (diminishing returns, α is a setting), with k fitted from your campaigns.",
                  "Campaign fatigue: a channel loses effectiveness the longer its campaigns run (campaign length comes from the start and end dates, counted up to 12 weeks), at the fatigue rate you set; more budget means more exposure and more fatigue.",
                  "ROI by channel moves with conversions per rupee: ROI = recorded ROI × (conversions per ₹ in the scenario ÷ today).",
                  "The optimiser equalises marginal conversions across channels at a fixed total budget.",
                  "1,500 simulated futures sample α, fatigue and channel noise (8%); the range shown is P10 to P90."],
    "sentiment": ["New reviews are a mix of 1.5★ (negative wave) and 4.3★; recovery reviews are 4.6★. Revenue moves 7% per star (your own elasticity may differ).",
                  "Top complaint = the most frequent issue in your reviews (food quality, staff behaviour, wait time, hygiene, value). Fixing it removes a share of those complaints (effectiveness is a setting); each fixed review then counts as the average positive review (4.3★).",
                  "CSAT moves one-for-one with the average review rating; repeat visits rise by the sensitivity you set per +0.1★ (default 3% of today's visits).",
                  "Repeat visits and the revenue per visit come from the customers table.",
                  "2,000 simulated outcomes sample fix effectiveness and repeat-visit sensitivity; the range shown is P10 to P90."],
    "audit": ["Probability an outlet fails = logistic(score vs the pass mark 65 (+ your stricter mark), scale 6). Fine per violation is a setting.",
              "Open findings = the violations of each outlet's latest audit. Each closed finding gives back (100 − score) ÷ findings points.",
              "Findings are closed at the rate you set (per week, random ± 50%); the next audit comes in the number of days you set. New findings can appear (the extra-violations setting).",
              "Days to become compliant = open findings ÷ closing rate; outlets still carrying findings at the audit date can fail.",
              "2,000 simulated audits; baseline = audit held today, scenario = audit held after the days you set. The range shown is P10 to P90."]}


def _cb(t, a=None):
    items = "\n".join("- " + x for x in ASSUME[t]); seed = f"\n- **Random seed {seed_of(a or {})}**: run again with the same seed and you get the same numbers; change it to see another set of futures."
    return B.callout(items + seed, "info", "Assumptions (change the sliders; edit the model in sim_fr.py)")


# ------------------------------------------------------------------------------------------------ inventory
def _inv_frame():
    d = Q("SELECT i.outlet_id, i.sku_name, i.current_stock, i.reorder_threshold, i.weekly_demand, i.lead_time_days, o.revenue, o.operating_costs FROM inventory i JOIN outlets o USING(outlet_id)")
    d = d[d.weekly_demand > 0].reset_index(drop=True)
    tot = d.groupby("outlet_id").weekly_demand.transform("sum") * 52; d["uv"] = (d.revenue * 12 / tot).clip(1, 5000); d["gm"] = (1 - d.operating_costs / d.revenue).clip(.1, .6); return d
def _season(T, strength):
    """Daily demand multipliers: a weekly pattern (weekend peak) times a festive swing over the month; mean 1, so total demand does not change."""
    t = np.arange(T); f = (1 + .5 * strength * np.cos(2 * np.pi * (t - 5) / 7)) * (1 + strength * np.sin(2 * np.pi * t / max(T, 1))); return f / f.mean()
RULES = [("Reorder at the reorder level (today's rule)", "rop", 0.0), ("Reorder level + 30% safety stock", "ss", 0.3), ("Weekly review, order up to 3 weeks of cover", "periodic", 0.0)]
def _inv_core(d, dp, dl, buf, cv, T=30, R=100, seed=7, season=0.0, dvar=0.0, rule="rop"):
    """Simulates T days for every SKU in R futures. dp = demand change, dl = extra lead-time days, buf = extra safety stock, cv = demand volatility,
    season = seasonality strength, dvar = mean of the random extra supplier delay (days), rule = rop | ss | periodic."""
    rng = np.random.default_rng(seed); N = len(d); wk = d.weekly_demand.values[:, None] * (1 + dp); dd = wk / 7; lead = np.maximum(1, d.lead_time_days.values + int(round(dl)))[:, None]
    if rule == "ss": buf = max(buf, .3)
    thr = (d.reorder_threshold.values * (1 + buf))[:, None]; Q_ = np.maximum(2 * wk, thr * 1.5); tgt = wk / 7 * (lead + 7) * 1.15 if rule == "periodic" else None
    stock = np.repeat(d.current_stock.values[:, None].astype(np.float32), R, 1); pend = np.zeros((N, R), bool); arr = np.zeros((N, R)); qty = np.zeros((N, R), np.float32); lost = np.zeros((N, R), np.float32); out = np.zeros((T, N, R), bool)
    z = rng.standard_normal((T, N, R)).astype(np.float32); shock = np.exp(0.10 * rng.standard_normal((1, R))).astype(np.float32); day_lost = np.zeros((T, R), np.float64); sf = _season(T, season)
    uvv = d.uv.values[:, None]; held = np.zeros((N, R), np.float64); demand_tot = np.zeros((N, R), np.float32)
    for t in range(T):
        dem = np.maximum(0, dd * sf[t] * shock * (1 + cv * z[t])); demand_tot += dem; stock -= dem; short = np.maximum(0, -stock); lost += short; stock = np.maximum(stock, 0); out[t] = short > 0
        day_lost[t] = (short * uvv).sum(0); held += stock
        land = pend & (t >= arr); stock = np.where(land, stock + qty, stock); pend &= ~land
        go = (~pend) & ((stock <= thr) if rule != "periodic" else ((t % 7 == 0) & (stock < tgt)))
        extra = rng.poisson(dvar, (N, R)) if dvar > 0 else 0
        qty = np.where(go, (np.maximum(0, tgt - stock) if rule == "periodic" else Q_), qty); pend |= go; arr = np.where(go, t + lead + extra, arr)
    return {"lost": lost, "out": out, "day_lost": day_lost, "stock0": d.current_stock.values, "dd": dd[:, 0], "Q": Q_[:, 0], "avg_stock": held / T, "demand": demand_tot}
def run_inventory(a):
    d = _inv_frame(); dp, dl, buf, cv = g(a, "pct", 0) / 100, g(a, "days", 0), g(a, "buffer", 0) / 100, g(a, "cv", 30) / 100; outs = a.get("outlets") or []
    season, dvar = g(a, "season", 15) / 100, g(a, "dvar", 2); sd = seed_of(a)
    if outs: d = d[d.outlet_id.isin(outs)].reset_index(drop=True)
    if not len(d): return {"blocks": [B.callout("No inventory rows for this selection.", "warn")], "m": {}}
    base = _inv_core(d, 0, 0, 0, cv, seed=sd, season=season, dvar=dvar); sc = _inv_core(d, dp, dl, 0, cv, seed=sd, season=season, dvar=dvar); uv = d.uv.values; gm = d.gm.values
    lv = lambda r: (r["lost"] * uv[:, None]); tot = lambda r: lv(r).sum(0)
    b_t, s_t = tot(base), tot(sc); p = lambda r: r["out"].sum(0).mean(1)
    bp, sp = p(base), p(sc); dem = d.weekly_demand.values / 7 * 30; fr = lambda r, dm: float(1 - r["lost"].mean(1).sum() / dm.sum()); gmm = float(np.average(gm, weights=uv * d.weekly_demand.values))
    daily = lambda r: np.cumsum(r["day_lost"], 0)
    cb, cs = daily(base), daily(sc); dif = (cs - cb) * gmm; x = [f"D{t + 1}" for t in range(cb.shape[0])]
    # buffer sweep under the scenario
    rows = []
    for b in (0, .1, .2, .3, .4, .5):
        r = _inv_core(d, dp, dl, b, cv, seed=sd, season=season, dvar=dvar); lost_m = float(tot(r).mean() * gmm); hold = float((d.reorder_threshold.values * b * uv * 0.25 * (30 / 365)).sum()); rows.append((b, lost_m, hold, lost_m + hold))
    best = min(rows, key=lambda r: r[3]); cur_total = rows[0][3]
    # stock-out probability and service level, and three reorder rules on the same random numbers
    any_out = sc["out"].any(0)                                                  # (SKU, future): did this SKU run dry at least once in the 30 days
    p_stockout = float(any_out.mean()); service = fr(sc, dem * (1 + dp))
    cmp_rows = []
    for name, rl, bf in RULES:
        r = _inv_core(d, dp, dl, bf, cv, seed=sd, season=season, dvar=dvar, rule=rl); lm = tot(r) * gmm; hold = (r["avg_stock"] * uv[:, None]).sum(0) * 0.25 * (30 / 365); n_dem = r["demand"].sum()
        cmp_rows.append({"rule": name, "stock-out probability": float(r["out"].any(0).mean()), "service level": float(1 - r["lost"].sum() / max(n_dem, 1)), "lost margin (expected)": float(lm.mean()), "lost margin P10": float(np.percentile(lm, 10)), "lost margin P90": float(np.percentile(lm, 90)), "holding cost": float(hold.mean()), "total cost": float((lm + hold).mean())})
    cmp_df = pd.DataFrame(cmp_rows); best_rule = cmp_df.sort_values("total cost").iloc[0]
    d["p_base"], d["p_scn"] = bp, sp; d["loss"] = lv(sc).mean(1); d["cover_days"] = d.current_stock / (d.weekly_demand / 7 * (1 + dp)).replace(0, np.nan); d["p_out"] = any_out.mean(1)
    d["need_order"] = np.ceil(np.maximum(0, d.weekly_demand * (1 + dp) / 7 * (d.lead_time_days + dl + 3) - d.current_stock))
    top = d.sort_values("loss", ascending=False).head(15)
    byo = d.groupby("outlet_id").agg(loss=("loss", "sum"), skus_at_risk=("p_scn", lambda s: int((s > .5).sum()))).sort_values("loss", ascending=False).head(10).reset_index()
    bl = [_cb("inventory", a), B.kpis(("Service level (units served)", f"{service:.1%}", f"now {fr(base, dem):.1%}", "Critical" if service < fr(base, dem) - .02 else None), ("Stock-out probability", f"{p_stockout:.1%}", f"a SKU runs dry at least once in 30 days · now {float(base['out'].any(0).mean()):.1%}", "Critical" if p_stockout > .5 else None),
                              ("Expected lost sales, 30 days", inr(s_t.mean()), rng_txt(s_t), None), ("Lost gross margin", inr(s_t.mean() * gmm), f"+{inr((s_t.mean() - b_t.mean()) * gmm)} vs baseline"),
                              ("Best reorder rule", str(best_rule["rule"]).split(" (")[0].split(",")[0], f"lowest total cost: {inr(best_rule['total cost'])}"), ("SKUs out of stock 5+ days", int((sp >= 5).sum()), f"now {int((bp >= 5).sum())}"))]
    bl.append(B.row(B.card("Cumulative lost sales over 30 days (expected)", B.chart(B.line(x, {"baseline": [round(float(v.mean()), 0) for v in cb], "scenario": [round(float(v.mean()), 0) for v in cs]}, area=False, colors=[GREY, RED]), h=260, key="inv_c"),
                           sub="Average of 100 simulated futures; P10 to P90 band is in the Monte Carlo panel below"),
                    B.card("Safety-buffer trade-off", B.chart(B.bar([f"+{r[0]:.0%}" for r in rows], {"lost margin": [round(r[1]) for r in rows], "holding cost": [round(r[2]) for r in rows]}, stack=True, colors=[RED, AMBER]), h=260, key="inv_b"), sub="Higher buffer: fewer stock-outs, more stock held")))
    bl.append(B.table(cmp_df, ["rule", B.num_col("stock-out probability", "stock-out probability", "pct"), B.num_col("service level", "service level", "pct"), B.num_col("lost margin (expected)", "lost margin (expected)", "money"), B.num_col("lost margin P10", "P10", "money"), B.num_col("lost margin P90", "P90", "money"), B.num_col("holding cost", "holding cost", "money"), B.num_col("total cost", "total cost", "money")],
                      title="Three reorder rules on the same 100 futures (30 days, whole selection)", h=190, key="inv_rules"))
    bl.append(B.table(top[["outlet_id", "sku_name", "current_stock", "cover_days", "p_out", "p_base", "p_scn", "loss", "need_order"]].rename(columns={"p_out": "stockout_prob", "p_base": "days_out_now", "p_scn": "days_out_scn", "loss": "expected_lost_sales"}), ["outlet_id", "sku_name", B.num_col("current_stock", "stock", "int"), B.num_col("cover_days", "days of cover", "num"), B.num_col("stockout_prob", "stock-out probability", "pct"), B.num_col("days_out_now", "stock-out days now", "num"), B.num_col("days_out_scn", "under scenario", "num"), B.num_col("expected_lost_sales", "expected lost sales", "money"), B.num_col("need_order", "order now (units)", "int")], title="SKUs to act on first", h=420, open={"kind": "outlet", "col": "outlet_id"}, key="inv_t"))
    bl.append(B.table(byo, ["outlet_id", B.num_col("loss", "expected lost sales", "money"), B.num_col("skus_at_risk", "SKUs at risk", "int")], title="Most exposed outlets", h=300, open={"kind": "outlet", "col": "outlet_id"}, key="inv_o"))
    return {"blocks": bl, "m": {"d_samples": ((s_t - b_t) * gmm), "loss": float(s_t.mean() * gmm), "loss_base": float(b_t.mean() * gmm), "loss_p10": float(np.percentile(s_t, 10) * gmm), "loss_p90": float(np.percentile(s_t, 90) * gmm), "best_buffer": best[0], "buf_rows": rows, "buffer_saving": float(cur_total - best[3]), "at_risk": int((sp >= 5).sum()), "fill": service, "fill_base": fr(base, dem), "stockout_prob": p_stockout, "rules": cmp_rows, "curve": [float(v.mean()) for v in dif], "curve_lo": [float(np.percentile(v, 10)) for v in dif], "curve_hi": [float(np.percentile(v, 90)) for v in dif], "need": top[["outlet_id", "sku_name", "need_order"]].head(5).to_dict("records")}}


# ------------------------------------------------------------------------------------------------ workforce
BANDS = [("under 1 year", 0, 1, .30), ("1 to 3 years", 1, 3, .20), ("3 to 5 years", 3, 5, .12), ("5+ years", 5, 99, .07)]
def _band_of(t):
    for i, (_, lo, hi, _) in enumerate(BANDS):
        if lo <= t < hi: return i
    return len(BANDS) - 1
def _attrition(a, outs):
    """Attrition by tenure band, hiring lead time and overtime versus hiring, for the selected outlets (Monte Carlo over who leaves)."""
    st = Q("SELECT outlet_id, salary, overtime_hrs, tenure_years, predicted_attrition_prob FROM staff")
    if outs: st = st[st.outlet_id.isin(outs)]
    st = st.dropna(subset=["salary"])
    if not len(st): return [], {}
    lead_w, horizon = g(a, "lead", 4), g(a, "horizon", 12); R = 2000; r = rng_of(a, 3); n = len(st)
    band = st.tenure_years.fillna(2).map(_band_of).values; base = np.array([b[3] for b in BANDS])[band]; pred = st.predicted_attrition_prob.fillna(pd.Series(base, index=st.index)).clip(0, .9).values
    p_year = np.clip(.5 * base + .5 * pred, .01, .9); p_h = 1 - (1 - p_year) ** (horizon / 12)                       # chance each person leaves inside the horizon
    leave = r.random((R, n)) < p_h[None, :]; L = leave.sum(1); sal = st.salary.values; hr = sal / 160
    avg_hr = float(hr.mean()); week_cost = 40 * avg_hr * 1.5; hire = .5 * 12 * sal.mean()                                                     # one overtime week for one post; replacing one leaver
    hire_cost = L * hire + L * lead_w * week_cost                                                                                       # hire a replacement, cover the vacancy with overtime while hiring
    weeks_left = horizon * 4.33 / 2                                                                                                     # a leaver leaves on average half way through
    stay = np.maximum(1, n - L); extra_ot_pp = (L * 40) / stay                                                                           # extra overtime hours per person who stays, per week, if nobody is hired
    burn = np.clip(extra_ot_pp * .004, 0, .5); extra_leavers = stay * burn * (horizon / 12)
    ot_cost = L * weeks_left * week_cost + extra_leavers * hire                                                                          # nobody is hired: overtime for the rest of the year, and the burnout leavers are replaced
    tbl = []
    for i, (nm, lo, hi, _) in enumerate(BANDS):
        m = band == i
        if not m.any(): continue
        lv = leave[:, m].sum(1); tbl.append({"band": nm, "people": int(m.sum()), "annual attrition": float(p_year[m].mean()), "expected leavers": float(lv.mean()), "leavers P10": float(np.percentile(lv, 10)), "leavers P90": float(np.percentile(lv, 90))})
    cmp_ = [{"strategy": "Hire replacements (cover the vacancy with overtime for the lead time)", "cost P10": float(np.percentile(hire_cost, 10)), "cost P50": float(np.percentile(hire_cost, 50)), "cost P90": float(np.percentile(hire_cost, 90))},
            {"strategy": "Do not hire: cover with overtime (and replace the extra burnout leavers)", "cost P10": float(np.percentile(ot_cost, 10)), "cost P50": float(np.percentile(ot_cost, 50)), "cost P90": float(np.percentile(ot_cost, 90))}]
    win = "Hiring" if np.median(hire_cost) < np.median(ot_cost) else "Overtime"; be = hire / week_cost + lead_w
    bl = [B.kpis(("Expected leavers", f"{L.mean():.1f}", f"in {horizon:.0f} months · P10–P90 {np.percentile(L, 10):.0f} – {np.percentile(L, 90):.0f}"), ("Hire replacements: cost", inr(np.median(hire_cost)), rng_txt(hire_cost)), ("Overtime only: cost", inr(np.median(ot_cost)), rng_txt(ot_cost)),
                    ("Cheaper strategy", win, f"hiring pays off when the post stays open longer than {be:.0f} weeks", None))]
    bl.append(B.row(B.card("Attrition by tenure band", B.chart(B.bar([t["band"] for t in tbl], {"expected leavers": [round(t["expected leavers"], 1) for t in tbl]}, colors=[VIOLET]), h=230, key="wf_band"), sub=f"{horizon:.0f}-month horizon, whole selection · seed {seed_of(a)}"),
                    B.card("Hiring versus overtime (median cost)", B.chart(B.bar(["Hire replacements", "Overtime only"], {"cost": [round(float(np.median(hire_cost))), round(float(np.median(ot_cost)))]}, colors=[TEAL]), h=230, key="wf_hvo"), sub="Median of 2,000 simulated years; the table gives P10 and P90")))
    bl.append(B.table(pd.DataFrame(tbl), ["band", B.num_col("people", "people", "int"), B.num_col("annual attrition", "annual attrition", "pct"), B.num_col("expected leavers", "expected leavers", "num"), B.num_col("leavers P10", "P10", "num"), B.num_col("leavers P90", "P90", "num")], title="Attrition by tenure band (P10–P90 of leavers)", h=200, key="wf_bt"))
    bl.append(B.table(pd.DataFrame(cmp_), ["strategy", B.num_col("cost P10", "P10", "money"), B.num_col("cost P50", "median", "money"), B.num_col("cost P90", "P90", "money")], title=f"Overtime versus hiring over {horizon:.0f} months (hiring lead time {lead_w:.0f} weeks)", h=150, key="wf_cmp"))
    return bl, {"leavers": float(L.mean()), "hire_cost": float(np.median(hire_cost)), "ot_cost": float(np.median(ot_cost)), "cheaper": win, "bands": tbl}
def run_workforce(a):
    ab, cap, temp = g(a, "pct", 0) / 100, g(a, "ot_cap", 10), g(a, "temp", 0) / 100; outs = a.get("outlets") or []
    s = Q("SELECT outlet_id, COUNT(*) n, AVG(salary) sal, AVG(overtime_hrs) ot, AVG(predicted_attrition_prob) att FROM staff GROUP BY outlet_id"); o = Q("SELECT outlet_id, revenue FROM outlets")
    d = s.merge(o, on="outlet_id")
    if outs: d = d[d.outlet_id.isin(outs)]
    if not len(d): return {"blocks": [B.callout("No staff data.", "warn")], "m": {}}
    def model(ab_, cap_, temp_):
        n = d.n.values.astype(float); avail = n * (1 - ab_); need = (n - avail) * 40; hr = d.sal.values / 160; capw = cap_ * avail; ot_h = np.minimum(need, capw); rest = need - ot_h
        tmp_h = rest * temp_; gap = rest - tmp_h; ot_cost = ot_h * hr * 1.5 * 4.3; tmp_cost = tmp_h * hr * 1.3 * 4.3
        ot_pp = (ot_h / np.maximum(avail, 1)); att_up = np.minimum(.5, ot_pp * 0.004 * 1.0 * (1 if True else 0)); leav = n * att_up; repl = leav * d.sal.values * 12 * .5
        rev = gap / np.maximum(n * 40 * 4.3, 1) * 0.8 * d.revenue.values; return {"ot_cost": ot_cost, "tmp_cost": tmp_cost, "gap_h": gap * 4.3, "leav": leav, "repl": repl, "rev": rev, "cover": 1 - gap / np.maximum(need, 1) if need.sum() else np.ones(len(n))}
    b = model(0, cap, 0); s_ = model(ab, cap, temp); tot = lambda m: m["ot_cost"] + m["tmp_cost"] + m["repl"] + m["rev"]
    d = d.assign(ot_cost=s_["ot_cost"], tmp_cost=s_["tmp_cost"], gap_h=s_["gap_h"], leavers=s_["leav"], revenue_at_risk=s_["rev"], total=tot(s_), coverage=np.where((d.n * ab) > 0, 1 - s_["gap_h"] / np.maximum(d.n * ab * 40 * 4.3, 1), 1))
    sweep = [round(float(tot(model(v / 100, cap, temp)).sum())) for v in (0, 10, 20, 30, 40)]
    top = d.sort_values("total", ascending=False).head(15)
    # the monthly cost of absence has no randomness of its own: its range comes from absenteeism ± 30% (a stated assumption) with the same seed
    r = rng_of(a, 1); ab_s = np.clip(r.normal(ab, max(.03, ab * .3), 1000), 0, .8); cost_s = np.array([float(tot(model(x, cap, temp)).sum()) for x in ab_s[:200]])
    at_bl, at_m = _attrition(a, outs)
    bl = [_cb("workforce", a), B.kpis(("Overtime + temp cost / month", inr(d.ot_cost.sum() + d.tmp_cost.sum()), f"overtime {inr(d.ot_cost.sum())}"), ("Total monthly people cost", inr(d.total.sum()), rng_txt(cost_s)), ("Uncovered labour hours", f"{d.gap_h.sum():,.0f}", "service gap" if d.gap_h.sum() else "fully covered", "Critical" if d.gap_h.sum() > 500 else None), ("Revenue at risk / month", inr(d.revenue_at_risk.sum())), ("Extra expected leavers", f"{d.leavers.sum():.1f}", f"replacement {inr(s_['repl'].sum())}")),
          B.row(B.card("Total monthly cost by absenteeism", B.chart(B.bar(["0%", "10%", "20%", "30%", "40%"], {"cost": sweep}, colors=[VIOLET]), h=250, key="wf_sw"), sub="Overtime, temp cover, replacements, lost revenue"),
                B.card("Outlets with the largest cost", B.chart(B.bar(top.outlet_id, {"overtime": [round(x) for x in top.ot_cost], "temp": [round(x) for x in top.tmp_cost], "revenue at risk": [round(x) for x in top.revenue_at_risk]}, stack=True, colors=[AMBER, BLUE, RED]), h=250, key="wf_o"))),
          B.table(top[["outlet_id", "n", "ot_cost", "tmp_cost", "gap_h", "leavers", "revenue_at_risk", "coverage"]], ["outlet_id", B.num_col("n", "staff", "int"), B.num_col("ot_cost", "overtime cost", "money"), B.num_col("tmp_cost", "temp cost", "money"), B.num_col("gap_h", "uncovered hrs", "int"), B.num_col("leavers", "extra leavers", "num"), B.num_col("revenue_at_risk", "revenue at risk", "money"), B.num_col("coverage", "coverage", "pct")], title="Outlets to staff first", h=420, open={"kind": "outlet", "col": "outlet_id"}, key="wf_t")] + at_bl
    return {"blocks": bl, "m": {"cost": float(d.total.sum()), "ot": float(d.ot_cost.sum() + d.tmp_cost.sum()), "rev_risk": float(d.revenue_at_risk.sum()), "leavers": float(d.leavers.sum()), "gap_h": float(d.gap_h.sum()), "sweep": sweep, "attrition": at_m, "model": lambda ab_, cap_, temp_: float(tot(model(ab_, cap_, temp_)).sum())}}


# ------------------------------------------------------------------------------------------------ outlet P&L
WAGE_SHARE, RENT_SHARE, VAR_SHARE = .40, .15, .65
def run_pnl(a):
    dp, pp, cp = g(a, "pct", 0) / 100, g(a, "price", 0) / 100, g(a, "cost", 0) / 100; outs = a.get("outlets") or []
    e = -abs(g(a, "elast", 1.2)); wlo, whi = g(a, "wage_lo", 3) / 100, max(g(a, "wage_hi", 10) / 100, g(a, "wage_lo", 3) / 100); rent = g(a, "rent", 4) / 100; wmid = (wlo + whi) / 2
    o = Q("SELECT outlet_id, location, revenue, operating_costs FROM outlets")
    if outs: o = o[o.outlet_id.isin(outs)]
    if not len(o): return {"blocks": [B.callout("No outlets for this selection.", "warn")], "m": {}}
    v = VAR_SHARE
    def pl(dp_, pp_, cp_, wi=0.0, ri=0.0, e_=e):
        vol = (1 + dp_) * (1 + e_ * pp_); rev = o.revenue * vol * (1 + pp_); cost = o.operating_costs * (v * vol * (1 + cp_) + (1 - v) * (1 + cp_)) * (1 + WAGE_SHARE * wi + RENT_SHARE * ri); return rev, cost, rev - cost, vol
    r0, c0, p0, _ = pl(0, 0, 0); r1, c1, p1, vol = pl(dp, pp, cp, wmid, rent)
    # effect decomposition (sequential): demand, price, general costs, wages and rent
    ps = [p0.sum(), pl(dp, 0, 0)[2].sum(), pl(dp, pp, 0)[2].sum(), pl(dp, pp, cp)[2].sum(), p1.sum()]; deltas = [ps[i + 1] - ps[i] for i in range(4)]
    o = o.assign(profit_now=p0, profit_scn=p1, delta=p1 - p0, margin_scn=np.where(r1 > 0, p1 / r1, 0))
    sweep = [round(float(pl(x / 100, pp, cp, wmid, rent)[2].sum())) for x in (-30, -15, 0, 15, 30)]
    worst = o.sort_values("delta").head(15)
    # best and worst case band + Monte Carlo over elasticity, wage and rent inflation (the whole selection)
    best_c = float(pl(dp, pp, cp, wlo, rent, e + .4)[2].sum()); worst_c = float(pl(dp, pp, cp, whi, rent, e - .4)[2].sum()); mid_c = float(p1.sum())
    r = rng_of(a, 2); Rn = 2000; el = -np.clip(r.normal(abs(e), .25, Rn), .1, 4); wi_s = r.uniform(wlo, whi, Rn); ri_s = np.clip(r.normal(rent, .02, Rn), -.05, .3)
    prof = np.array([float(pl(dp, pp, cp, wi_s[i], ri_s[i], el[i])[2].sum()) for i in range(0, Rn, 4)]); delta_s = prof - float(p0.sum())
    band = [{"case": "Best case", "profit": best_c, "vs now": best_c - float(p0.sum()), "assumes": f"wage inflation {wlo:.0%}, elasticity {abs(e) - .4:.1f}"},
            {"case": "Expected", "profit": mid_c, "vs now": mid_c - float(p0.sum()), "assumes": f"wage inflation {wmid:.1%}, elasticity {abs(e):.1f}"},
            {"case": "Worst case", "profit": worst_c, "vs now": worst_c - float(p0.sum()), "assumes": f"wage inflation {whi:.0%}, elasticity {abs(e) + .4:.1f}"}]
    p10, p50, p90 = pr(prof)
    bl = [_cb("outlets", a), B.kpis(("Total profit (expected)", inr(p1.sum()), f"{inr(p1.sum() - p0.sum())} vs now", "Critical" if p1.sum() < p0.sum() * .9 else "Low" if p1.sum() > p0.sum() * 1.02 else None), ("Profit range P10–P90", f"{inr(p10)} – {inr(p90)}", f"median {inr(p50)}"), ("Best / worst case", f"{inr(best_c)} / {inr(worst_c)}", "low and high end of the wage band"),
                              ("Margin", f"{p1.sum() / max(r1.sum(), 1):.1%}", f"now {p0.sum() / max(r0.sum(), 1):.1%}"), ("Loss-making outlets", int((p1 < 0).sum()), f"now {int((p0 < 0).sum())}", "Critical" if (p1 < 0).sum() > (p0 < 0).sum() else None)),
          B.row(B.card("What moved profit", B.chart(B.waterfall(["Demand", "Price", "General costs", "Wages and rent"], [round(x) for x in deltas], "Net change"), h=260, key="pl_w")),
                B.card("Profit vs demand change", B.chart(B.bar(["-30%", "-15%", "0", "+15%", "+30%"], {"profit": sweep}, colors=[TEAL]), h=260, key="pl_s"), sub="With your price, cost and inflation settings")),
          B.table(pd.DataFrame(band), ["case", B.num_col("profit", "total profit", "money"), B.num_col("vs now", "change vs now", "money"), "assumes"], title="Best and worst case band", h=170, key="pl_band"),
          B.table(worst[["outlet_id", "location", "profit_now", "profit_scn", "delta", "margin_scn"]], ["outlet_id", "location", B.num_col("profit_now", "profit now", "money"), B.num_col("profit_scn", "profit scenario", "money"), B.num_col("delta", "change", "money"), B.num_col("margin_scn", "margin", "pct")], title="Outlets hit hardest", h=420, open={"kind": "outlet", "col": "outlet_id"}, key="pl_t")]
    return {"blocks": bl, "m": {"profit_delta": float(p1.sum() - p0.sum()), "loss_makers": int((p1 < 0).sum()), "profit": float(p1.sum()), "best": best_c, "worst": worst_c, "p10": p10, "p90": p90, "model": lambda dp_, pp_, cp_: float(pl(dp_, pp_, cp_, wmid, rent)[2].sum() - p0.sum())}}


# ------------------------------------------------------------------------------------------------ marketing
def _mk_frame():
    m = Q("SELECT channel, SUM(budget) B, SUM(conversions) C, COUNT(*) n, AVG(actual_roi) roi, AVG(MAX(1, julianday(end_date) - julianday(start_date)) / 7.0) weeks FROM marketing WHERE budget>0 GROUP BY channel")
    m["channel"] = m.channel.replace({"Influencer Campaign": "Influencer", "Social Media": "Social"}); m["roi"] = m.roi.fillna(0); m["weeks"] = m.weeks.fillna(4)
    return m.groupby("channel", as_index=False).agg(B=("B", "sum"), C=("C", "sum"), n=("n", "sum"), roi=("roi", "mean"), weeks=("weeks", "mean"))
def _fatigue(weeks, expo, rate):
    """Share of effectiveness kept: a campaign is fresh for 4 weeks, then loses `rate` of its effect per extra 4 weeks of exposure. Run length counts up to 12 weeks (longer campaigns are repeated bursts), and more budget means proportionally more exposure."""
    return 1 / (1 + rate * np.maximum(0, np.minimum(np.asarray(weeks), 12) * expo - 4) / 4)
def run_marketing(a):
    bp, al, fat = g(a, "pct", 0) / 100, g(a, "alpha", 70) / 100, g(a, "fatigue", 10) / 100; m = _mk_frame()
    if not len(m): return {"blocks": [B.callout("No campaigns.", "warn")], "m": {}}
    k = m.C / m.B ** al; B0 = m.B.values; wk = m.weeks.values; tot = B0.sum() * (1 + bp)
    f0 = _fatigue(wk, 1.0, fat); f1 = _fatigue(wk, 1 + bp, fat); conv = lambda Bv, ff=None: float((k.values * Bv ** al * (1 if ff is None else ff / f0)).sum())
    keep = B0 * (1 + bp); opt = keep.copy()
    for _ in range(8):                                                       # the best split depends on fatigue and fatigue on the split: iterate until it settles
        w = (k.values * al * _fatigue(wk, opt / B0, fat) / f0) ** (1 / (1 - al)); opt = .5 * opt + .5 * tot * w / w.sum()
    f_opt = _fatigue(wk, opt / B0, fat)
    if conv(opt, f_opt) < conv(keep, f1): opt, f_opt = keep.copy(), f1                  # reallocating must beat the scenario budget as it is; otherwise the current split stays
    m = m.assign(budget_now=B0, budget_keep=keep, budget_opt=opt, conv_now=m.C, conv_keep=k.values * keep ** al * f1 / f0, conv_opt=k.values * opt ** al * f_opt / f0, cpc_now=B0 / m.C, cpc_opt=opt / (k.values * opt ** al * f_opt / f0), fatigue_now=1 - f0, fatigue_scn=1 - f1)
    sweep = [round(conv(B0 * (1 + x / 100), _fatigue(wk, 1 + x / 100, fat))) for x in (-30, -15, 0, 25, 50)]; keepc = conv(keep, f1); optc = conv(opt, f_opt); up = optc - keepc
    # ROI by channel with a range: sample alpha, fatigue and noise around your settings
    r = rng_of(a, 4); Rn = 1500; al_s = np.clip(r.normal(al, .08, Rn), .3, .95); fa_s = np.clip(r.normal(fat, .04, Rn), 0, .6); nz = r.lognormal(0, .08, (Rn, len(m)))
    kk = m.C.values[None, :] / B0[None, :] ** al_s[:, None]; fs0 = _fatigue(wk[None, :], 1.0, fa_s[:, None]); fs1 = _fatigue(wk[None, :], 1 + bp, fa_s[:, None])
    conv_s = kk * (keep[None, :] ** al_s[:, None]) * fs1 / fs0 * nz; roi_s = m.roi.values[None, :] * (conv_s / keep[None, :]) / (m.C.values / B0)[None, :]
    roi_tbl = pd.DataFrame({"channel": m.channel, "roi_now": m.roi.values, "roi_p10": np.percentile(roi_s, 10, axis=0), "roi_p50": np.percentile(roi_s, 50, axis=0), "roi_p90": np.percentile(roi_s, 90, axis=0), "fatigue": m.fatigue_scn})
    tot_s = conv_s.sum(1)
    bl = [_cb("marketing", a), B.kpis(("Conversions now", f"{m.C.sum():,.0f}"), ("Conversions with this budget", f"{keepc:,.0f}", f"{keepc - m.C.sum():+,.0f} · {rng_txt(tot_s, lambda x: f'{x:,.0f}')}"), ("With optimal allocation", f"{optc:,.0f}", f"+{up:,.0f} for the same spend", "Low" if up > 0 else None), ("Cost per conversion", inr(tot / max(optc, 1)), f"now {inr(B0.sum() / m.C.sum())}"), ("Average campaign fatigue", f"{float((1 - f1).mean()):.0%}", f"now {float((1 - f0).mean()):.0%} of effectiveness lost")),
          B.row(B.card("Budget by channel", B.chart(B.bar(m.channel, {"now": [round(x) for x in B0], "this scenario": [round(x) for x in keep], "optimal": [round(x) for x in opt]}, colors=[GREY, BLUE, TEAL]), h=270, key="mk_b")),
                B.card("Diminishing returns and fatigue", B.chart(B.bar(["-30%", "-15%", "0", "+25%", "+50%"], {"conversions": sweep}, colors=[VIOLET]), h=270, key="mk_s"), sub="Total conversions as the whole budget changes (fatigue included)")),
          B.table(roi_tbl, ["channel", B.num_col("roi_now", "ROI now", "num"), B.num_col("roi_p10", "ROI P10", "num"), B.num_col("roi_p50", "ROI median", "num"), B.num_col("roi_p90", "ROI P90", "num"), B.num_col("fatigue", "fatigue", "pct")], title="ROI by channel in this scenario (P10–P90)", h=260, key="mk_roi"),
          B.table(m[["channel", "n", "budget_now", "budget_opt", "conv_now", "conv_opt", "cpc_now", "cpc_opt"]], ["channel", B.num_col("n", "campaigns", "int"), B.num_col("budget_now", "budget now", "money"), B.num_col("budget_opt", "optimal budget", "money"), B.num_col("conv_now", "conversions now", "int"), B.num_col("conv_opt", "conversions optimal", "int"), B.num_col("cpc_now", "cost/conv now", "money"), B.num_col("cpc_opt", "cost/conv optimal", "money")], title="Where to move money", h=330, key="mk_t")]
    return {"blocks": bl, "m": {"uplift": float(up), "conv": keepc, "conv_opt": optc, "conv_now": float(m.C.sum()), "roi": roi_tbl.to_dict("records"), "conv_p10": pr(tot_s)[0], "conv_p90": pr(tot_s)[2]}}


# ------------------------------------------------------------------------------------------------ sentiment
def _top_complaint(outs):
    """The most frequent issue in the reviews (same keyword groups as the Sentiment agent) and who wrote about it."""
    import domain_franchise as D
    f = Q("SELECT outlet_id, rating, comment FROM feedback");
    if outs: f = f[f.outlet_id.isin(outs)]
    f = f.dropna(subset=["comment"]).copy(); lc = f.comment.str.lower()
    cnt = {k: int(lc.str.contains("|".join(v)).sum()) for k, v in D.ISSUES.items()}; top = max(cnt, key=cnt.get) if cnt else None
    return f, lc, cnt, top, ("|".join(D.ISSUES[top]) if top else "")
def run_sentiment(a):
    neg, n_new, star = g(a, "pct", 25) / 100, g(a, "n_new", 30), 0.07; outs = a.get("outlets") or []
    f = Q("SELECT outlet_id, COUNT(*) n, AVG(rating) r FROM feedback GROUP BY outlet_id"); o = Q("SELECT outlet_id, revenue, customer_satisfaction csat FROM outlets"); d = f.merge(o, on="outlet_id")
    if outs: d = d[d.outlet_id.isin(outs)]
    if not len(d): return {"blocks": [B.callout("No review data.", "warn")], "m": {}}
    mix = neg * 1.5 + (1 - neg) * 4.3; d = d.assign(r_new=(d.n * d.r + n_new * mix) / (d.n + n_new)); d["rec_n"] = np.ceil(np.maximum(0, n_new * (d.r - mix) / (4.6 - d.r).clip(lower=.1)))
    d["rev_risk"] = np.maximum(0, d.r - d.r_new) * star * d.revenue; sw = [round(float((d.n * d.r + n_new * ((x / 100) * 1.5 + (1 - x / 100) * 4.3)).sum() / (d.n + n_new).sum()), 2) for x in (0, 10, 25, 50, 75)]
    wt = d.sort_values("rev_risk", ascending=False).head(15)
    # ---- fix the most common complaint: CSAT and repeat visits
    eff, sens = g(a, "fix", 70) / 100, g(a, "repeat", 3) / 100; fr_, lc, cnt, top, rx = _top_complaint(outs); fix_bl = []; fix_m = {}
    if top and len(fr_):
        has = lc.str.contains(rx); n_top = int(has.sum()); avg0 = float(fr_.rating.mean()); bad = has & (fr_.rating <= 3); n_bad = int(bad.sum()); r_bad = float(fr_.rating[bad].mean()) if n_bad else 0.0; r_top = float(fr_.rating[has].mean()) if n_top else 0.0
        GOOD = 4.3                                                                                       # a review without the complaint is as good as the average positive review (the same 4.3★ as the review-wave model)
        cu = Q("SELECT outlet_id, SUM(visit_freq) vf, AVG(avg_order_value) aov FROM customers_fr GROUP BY outlet_id")
        if outs: cu = cu[cu.outlet_id.isin(outs)]
        visits0 = float(cu.vf.sum()) if len(cu) else 0.0; aov = float(cu.aov.mean()) if len(cu) and cu.aov.notna().any() else 0.0; scale5 = float(d.csat.max()) <= 5.5 if len(d) else True
        r = rng_of(a, 5); Rn = 2000; ef = np.clip(r.normal(eff, .12, Rn), .2, 1); se = np.clip(r.normal(sens, .01, Rn), 0, .15); lift = ef * (n_bad / len(fr_)) * max(0.0, GOOD - r_bad)       # rating points gained across all reviews: the unhappy reviews that mention the complaint become good ones
        new_avg = avg0 + lift; csat_gain = lift * (1 if scale5 else 20); visits_gain = visits0 * se * (lift / .1); rev_gain = visits_gain * aov * 3         # three months of visits (customers table = 90-day spend)
        csat0 = float(d.csat.mean()); per_issue = pd.DataFrame({"complaint": list(cnt), "reviews": [cnt[k] for k in cnt]}).sort_values("reviews", ascending=False)
        fix_bl = [B.callout(f"**Most common complaint: {top}** ({n_top:,} of {len(fr_):,} reviews mention it, {n_bad:,} of them are 1–3★ and average {r_bad:.2f}★). Fixing it with {eff:.0%} effectiveness turns those unhappy reviews into 4.3★ ones; the result is simulated below.", "info", "Fix the top complaint"),
                  B.kpis(("Chain CSAT", f"{csat0 + float(np.median(csat_gain)):.2f}", f"now {csat0:.2f} · gain P10–P90 {np.percentile(csat_gain, 10):+.2f} – {np.percentile(csat_gain, 90):+.2f}"), ("Average review rating", f"{avg0 + float(np.median(lift)):.2f}★", f"now {avg0:.2f}★"),
                         ("Repeat visits gained / quarter", f"{np.median(visits_gain):,.0f}", rng_txt(visits_gain, lambda x: f"{x:,.0f}")), ("Revenue from repeat visits", inr(np.median(rev_gain)), rng_txt(rev_gain), "Low")),
                  B.row(B.card("Complaints by type", B.chart(B.bar(per_issue.complaint, {"reviews": [int(x) for x in per_issue.reviews]}, colors=[AMBER], horizontal=True), h=240, key="se_iss"), sub="Keyword groups of the Sentiment agent"),
                        B.card("CSAT before and after the fix", B.chart(B.bar(["now", "P10", "median", "P90"], {"CSAT": [round(csat0, 2), round(csat0 + float(np.percentile(csat_gain, 10)), 2), round(csat0 + float(np.median(csat_gain)), 2), round(csat0 + float(np.percentile(csat_gain, 90)), 2)]}, colors=[TEAL], max_=5 if scale5 else 100), h=240, key="se_csat"), sub=f"2,000 simulated outcomes · seed {seed_of(a)}"))]
        fix_m = {"top": top, "csat_gain": float(np.median(csat_gain)), "repeat_gain": float(np.median(visits_gain)), "rev_gain": float(np.median(rev_gain))}
    bl = [_cb("sentiment", a), B.kpis(("Average rating", f"{(d.r_new * d.n).sum() / d.n.sum():.2f}★", f"now {(d.r * d.n).sum() / d.n.sum():.2f}★"), ("Outlets below 3.5★", int((d.r_new < 3.5).sum()), f"now {int((d.r < 3.5).sum())}", "Critical" if (d.r_new < 3.5).sum() > (d.r < 3.5).sum() else None), ("Revenue at risk", inr(d.rev_risk.sum())), ("Good reviews needed to recover", f"{d.rec_n.sum():,.0f}", "4.6★ replies across the chain")),
          B.card("Chain rating vs share of negative reviews", B.chart(B.bar(["0%", "10%", "25%", "50%", "75%"], {"rating": sw}, colors=[AMBER], max_=5), h=240, key="se_s")),
          B.table(wt[["outlet_id", "n", "r", "r_new", "rev_risk", "rec_n"]], ["outlet_id", B.num_col("n", "reviews", "int"), B.num_col("r", "rating now", "num"), B.num_col("r_new", "rating after", "num"), B.num_col("rev_risk", "revenue at risk", "money"), B.num_col("rec_n", "good reviews to recover", "int")], title="Outlets most exposed", h=400, open={"kind": "outlet", "col": "outlet_id"}, key="se_t")] + fix_bl
    return {"blocks": bl, "m": {"rev_risk": float(d.rev_risk.sum()), "below35": int((d.r_new < 3.5).sum()), "fix": fix_m}}


# ------------------------------------------------------------------------------------------------ audit
def run_audit(a):
    raise_ = g(a, "raise", 0); extra = g(a, "pct", 0) / 100; fine = g(a, "fine", 5000); days = g(a, "days", 14); wait = g(a, "wait", 30); close_w = g(a, "close", 2.0); outs = a.get("outlets") or []
    d = Q("SELECT outlet_id, score, violations FROM audits WHERE audit_id IN (SELECT audit_id FROM audits a2 WHERE a2.outlet_id=audits.outlet_id ORDER BY audit_date DESC LIMIT 1)")
    if outs: d = d[d.outlet_id.isin(outs)]
    if not len(d): return {"blocks": [B.callout("No audit data.", "warn")], "m": {}}
    pf = lambda sc, mark: 1 / (1 + np.exp((sc - mark) / 6)); sc0 = d.score.values.astype(float); V = d.violations.fillna(0).values.astype(float); pts = np.where(V > 0, (100 - sc0) / np.maximum(V, 1), 0)         # points one closed finding gives back
    p0 = pf(sc0, 65); v1 = V * (1 + extra); sc1 = sc0 - extra * 20; p1 = pf(sc1, 65 + raise_)                                                                                                  # (existing) risk if the audit were held today with more findings and a stricter mark
    r = rng_of(a, 6); Rn = 2000; n = len(d); rate = np.clip(r.normal(close_w, close_w * .5, (Rn, n)), 0, None) / 7                                                                          # findings closed per day, random per outlet and future
    closed = np.minimum(v1[None, :], r.poisson(rate * wait)); rest = v1[None, :] - closed; sc_at = np.minimum(100, sc1[None, :] + closed * pts[None, :]); p_at = pf(sc_at, 65 + raise_)
    fail_now = r.random((Rn, n)) < p1[None, :]; fail_at = r.random((Rn, n)) < p_at; nf_now, nf_at = fail_now.sum(1), fail_at.sum(1); fines_at = (fail_at * rest * fine).sum(1)
    days_c = np.where(v1 > 0, v1 / max(close_w / 7, 1e-6), 0)
    d = d.assign(p_now=p1, p_audit=p_at.mean(0), open_findings=v1, rest=rest.mean(0), days_to_comply=days_c, fines=(fail_at * rest * fine).mean(0), rem_days=np.where(p_at.mean(0) > .5, days, 0))
    sw = [round(float(pf(sc1, 65 + x).sum()), 1) for x in (0, 5, 10, 15)]; wt = d.sort_values("p_audit", ascending=False).head(15)
    f10, f50, f90 = pr(nf_at)
    bl = [_cb("audit", a), B.kpis(("Expected failing outlets at the audit", f"{nf_at.mean():.1f}", f"P10–P90 {f10:.0f} – {f90:.0f} · audit held today {nf_now.mean():.1f}", "Critical" if nf_at.mean() > nf_now.mean() + 2 else None), ("Expected fines", inr(fines_at.mean()), rng_txt(fines_at)), ("Open findings now", f"{v1.sum():,.0f}", f"{rest.sum(1).mean():,.0f} still open in {wait:.0f} days"),
                              ("Days to become compliant", f"{float(np.median(days_c[V > 0])) if (V > 0).any() else 0:.0f}", f"median outlet · slowest {float(days_c.max()):.0f} days at {close_w:.1f} findings/week"), ("Outlets likely to fail (>50%)", int((p_at.mean(0) > .5).sum()), f"audit today {int((p1 > .5).sum())}"), ("Outlet-days under remediation", f"{d.rem_days.sum():,.0f}")),
          B.row(B.card("Expected failures vs stricter pass mark", B.chart(B.bar(["65", "70", "75", "80"], {"expected failures": sw}, colors=[RED]), h=240, key="au_s"), sub="Audit held today"),
                B.card("Chance of failing: today vs at the audit date", B.chart(B.bar(["audit today", f"audit in {wait:.0f} days"], {"expected failing outlets": [round(float(nf_now.mean()), 1), round(float(nf_at.mean()), 1)]}, colors=[AMBER]), h=240, key="au_d"), sub=f"Findings closed at {close_w:.1f} per week · seed {seed_of(a)}")),
          B.table(wt[["outlet_id", "score", "open_findings", "days_to_comply", "p_now", "p_audit", "fines"]], ["outlet_id", B.num_col("score", "last score", "num"), B.num_col("open_findings", "open findings", "int"), B.num_col("days_to_comply", "days to comply", "int"), B.num_col("p_now", "fail risk today", "pct"), B.num_col("p_audit", "fail risk at audit", "pct"), B.num_col("fines", "expected fines", "money")], title="Outlets to prepare first", h=400, open={"kind": "outlet", "col": "outlet_id"}, key="au_t")]
    return {"blocks": bl, "m": {"fines": float(d.fines.sum()), "fail": float(p1.sum()), "fail_at_audit": float(nf_at.mean()), "fail_p10": f10, "fail_p90": f90, "days_to_comply": float(np.median(days_c[V > 0])) if (V > 0).any() else 0.0}}
RUN = {"inventory": run_inventory, "workforce": run_workforce, "outlets": run_pnl, "marketing": run_marketing, "sentiment": run_sentiment, "audit": run_audit}
