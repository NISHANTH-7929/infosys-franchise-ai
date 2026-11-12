"""Freight simulators (USD). Real sea routes (seanav), live shipments, quotes, carriers and ports; assumptions are shown on every page and are editable in the form."""
import numpy as np, pandas as pd
import blocks as B
from blocks import Q, TEAL, BLUE, AMBER, RED, VIOLET
GREY = "#8b8d98"; STORM_AREAS = {"Red Sea": (18.0, 40.0), "Arabian Sea": (15.0, 65.0), "Strait of Malacca": (3.5, 100.5), "South China Sea": (14.0, 114.0), "Bay of Biscay": (45.0, -8.0), "Cape of Good Hope": (-35.0, 20.0), "North Atlantic": (48.0, -35.0)}
def g(a, k, d):
    try: return float(a.get(k, d))
    except Exception: return float(d)
def usd(x):
    x = float(x); s = "-" if x < 0 else ""; x = abs(x); return s + ("$%.2fM" % (x / 1e6) if x >= 1e6 else "$%.1fk" % (x / 1e3) if x >= 1e4 else "${:,.0f}".format(x))
def _D():
    import domain_freight as D; return D
def hav(la1, lo1, la2, lo2):
    p = np.pi / 180; a = np.sin((la2 - la1) * p / 2) ** 2 + np.cos(la1 * p) * np.cos(la2 * p) * np.sin((lo2 - lo1) * p / 2) ** 2; return 2 * 3440.065 * np.arcsin(np.sqrt(a))
def _wrap(lon): return (np.asarray(lon, float) + 180) % 360 - 180
ASSUME = {"route": "Real sea routes on a land-masked graph. Speed 14 kn. Freight cost $0.012 per tonne-nautical-mile; cargo waiting costs $120 per shipment-day. Each +1 congestion adds 0.8 days at each end port. Closed chokepoints are removed from the graph; storms are avoided by a 700 nm radius.",
          "quote": "Win probability = 45% × exp(−elasticity × price change). Elasticity is a setting. Costs rise with the carrier-rate and fuel moves you set (fuel applies to the fuel surcharge). Expected profit = win probability × (price − cost).",
          "carrier": "Alternatives are ranked by rating, on-time % and cost index. Each alternative can absorb up to 30% more load. Delay cost $120 per shipment-day, and 1 point of on-time ≈ 0.08 days.",
          "weather": "Delay days = 0.25 × (wind − 12 m/s), capped at 7. A vessel is affected inside the storm radius. Demurrage and re-planning cost is a setting per shipment-day.",
          "customs": "Held shipments are those arriving soonest at the affected ports; each is delayed by the extra dwell days at the storage cost you set. Duty changes scale customs fees (average duty 7.5%)."}
def _cb(k): return B.callout(ASSUME[k], "info", "Assumptions")
def _lanes(limit=40):
    s = Q("SELECT s.shipment_id, s.origin_port o, s.dest_port d, s.carrier, s.weight_kg/1000.0 t, s.status FROM shipments s WHERE s.status IN ('In Transit','Port Congestion Delay','Anchorage Pending','Customs Hold') ORDER BY s.shipment_id")
    p = Q("SELECT port_name, lat, lon, congestion_index ci, avg_dwell_days dw FROM ports"); pm = {r.port_name: r for r in p.itertuples()}
    s = s[s.o.isin(pm) & s.d.isin(pm) & (s.o != s.d)]; lanes = s.groupby(["o", "d"], as_index=False).agg(n=("shipment_id", "count"), t=("t", "sum")).sort_values("n", ascending=False).head(limit); return lanes, pm
# ------------------------------------------------------------------------------------------------ routes
_BASE = {}; LAST = {}
def run_route(a):
    import seanav; D = _D(); S = seanav.sea(); closed = [c for c in (a.get("closures") or []) if c in seanav.BLOCK_GROUPS]; area = a.get("area") or "None"; wind = g(a, "wind", 25); cong = g(a, "add", 0); dc = g(a, "delay_cost", 120); rate = g(a, "rate", 12) / 1000
    st = ((STORM_AREAS[area][0], STORM_AREAS[area][1], 700.0),) if area in STORM_AREAS and area != "None" else ()
    lanes, pm = _lanes(int(g(a, "lanes", 25))); rows = []
    for r in lanes.itertuples():
        o, d = pm[r.o], pm[r.d]; oo, dd = (o.lat, o.lon), (d.lat, d.lon)
        try:
            b = _BASE.get((r.o, r.d)) or _BASE.setdefault((r.o, r.d), S.options(oo, dd, (), (), D._access(oo), D._access(dd))); sc = S.options(oo, dd, tuple(closed), st, D._access(oo), D._access(dd)) or (S.options(oo, dd, tuple(closed), (), D._access(oo), D._access(dd)) if st else [])
        except Exception: continue
        if not b: continue
        bn = b[0]["nm"]; days0 = bn / (14 * 24) + (o.dw + d.dw) * .5
        if not sc: rows.append({"lane": f"{r.o} → {r.d}", "shipments": int(r.n), "tonnes": r.t, "nm_now": round(bn), "nm_scn": None, "days_now": round(days0, 1), "days_scn": None, "extra_cost": np.nan, "route_scn": "NO ROUTE", "route_now": b[0]["name"]}); continue
        sn = sc[0]["nm"]; days1 = sn / (14 * 24) + (o.dw + d.dw) * .5 + 0.8 * cong * 2; ex = (sn - bn) * rate * r.t + (days1 - days0) * dc * r.n
        rows.append({"dist_cost": (sn - bn) * rate * r.t, "delay_cost": (days1 - days0) * dc * r.n, "lane": f"{r.o} → {r.d}", "shipments": int(r.n), "tonnes": r.t, "nm_now": round(bn), "nm_scn": round(sn), "days_now": round(days0, 1), "days_scn": round(days1, 1), "extra_cost": ex, "route_scn": sc[0]["name"], "route_now": b[0]["name"]})
    if not rows: return {"blocks": [B.callout("No active lanes found.", "warn")], "m": {}}
    d = pd.DataFrame(rows); LAST["route"] = d[d.nm_scn.notna()]; ok = d[d.nm_scn.notna()]; nor = d[d.nm_scn.isna()]; top = ok.sort_values("extra_cost", ascending=False).head(15)
    bl = [_cb("route"), B.kpis(("Lanes re-routed", int((ok.route_scn != ok.route_now).sum()), f"of {len(d)} active lanes"), ("Lanes with no route", len(nor), "blocked completely" if len(nor) else "none", "Critical" if len(nor) else None), ("Extra cost / voyage set", usd(ok.extra_cost.sum()), f"{int(ok.shipments.sum())} shipments"), ("Average extra days", f"{(ok.days_scn - ok.days_now).mean():+.1f}", None, "Critical" if (ok.days_scn - ok.days_now).mean() > 3 else None)),
          B.card("Extra days on the worst lanes", B.chart(B.bar(top.lane, {"days now": list(top.days_now), "days under scenario": list(top.days_scn)}, horizontal=True, colors=[GREY, RED]), h=360, key="rt_c")),
          B.table(d.sort_values("extra_cost", ascending=False).head(25), ["lane", B.num_col("shipments", "shipments", "int"), B.num_col("nm_now", "nm now", "int"), B.num_col("nm_scn", "nm scenario", "int"), B.num_col("days_now", "days now", "num"), B.num_col("days_scn", "days scenario", "num"), B.num_col("extra_cost", "extra cost", "money"), "route_scn"], title="Lane by lane", h=420, key="rt_t")]
    return {"blocks": bl, "m": {"extra": float(ok.extra_cost.sum()), "no_route": len(nor), "rerouted": int((ok.route_scn != ok.route_now).sum()), "extra_days": float((ok.days_scn - ok.days_now).mean()), "lanes": len(d)}}
# ------------------------------------------------------------------------------------------------ quotes and margin
def run_quote(a):
    fuel, car, disc, fx, el = g(a, "pct", 0) / 100, g(a, "carrier", 0) / 100, g(a, "discount", 0) / 100, g(a, "fx", 0) / 100, g(a, "elasticity", 2.0)
    q = Q("SELECT quote_id, carrier, base_cost, insurance, customs_fee, fuel_surcharge, final_price, margin_pct FROM freight_quotes WHERE final_price>0 ORDER BY created_at DESC LIMIT 400")
    if not len(q): return {"blocks": [B.callout("No quotes yet.", "warn")], "m": {}}
    p0 = q.final_price; c0 = p0 * (1 - q.margin_pct / 100); c1 = c0 + q.base_cost * ((1 + car) * (1 + fx) - 1) + q.customs_fee * fx + q.fuel_surcharge * fuel; m0 = (p0 - c0) / p0
    hold = p0; pass_ = c1 / (1 - m0.clip(.02, .6)) * (1 - disc)
    ev = lambda price, cost: (.45 * np.exp(-el * (price / p0 - 1)).clip(0, 2) * (price - cost)).sum()
    grid = np.arange(-.10, .21, .02); curve = [ev(p0 * (1 + x), c1) for x in grid]; bi = int(np.argmax(curve)); bx = float(grid[bi])
    q = q.assign(margin_now=m0, margin_hold=(hold - c1) / hold, margin_pass=(pass_ - c1) / pass_, cost_up=c1 - c0)
    kp = lambda v: float(v.mean())
    bl = [_cb("quote"), B.kpis(("Margin if prices are held", f"{kp(q.margin_hold):.1%}", f"now {kp(q.margin_now):.1%}", "Critical" if kp(q.margin_hold) < kp(q.margin_now) - .03 else None), ("Margin if costs are passed through", f"{kp(q.margin_pass):.1%}", f"price {((pass_ / p0).mean() - 1):+.1%}"), ("Quotes under 5% margin (held)", int((q.margin_hold < .05).sum()), f"now {int((q.margin_now < .05).sum())}", "Critical" if (q.margin_hold < .05).sum() > (q.margin_now < .05).sum() else None), ("Best price move", f"{bx:+.0%}", f"expected profit {usd(max(curve))} vs {usd(ev(p0, c1))} if held")),
          B.row(B.card("Expected profit vs price change", B.chart(B.line([f"{x:+.0%}" for x in grid], {"expected profit": [round(v) for v in curve]}, area=False, colors=[TEAL], markers=True), h=260, key="qt_c"), sub="Win probability falls as price rises (elasticity setting)"),
                B.card("Extra cost per quote", B.chart(B.hist(list(q.cost_up), bins=18, color=AMBER), h=260, key="qt_h"))),
          B.table(q.sort_values("margin_hold").head(15)[["quote_id", "carrier", "final_price", "cost_up", "margin_now", "margin_hold", "margin_pass"]], ["quote_id", "carrier", B.num_col("final_price", "price", "money"), B.num_col("cost_up", "extra cost", "money"), B.num_col("margin_now", "margin now", "pct"), B.num_col("margin_hold", "margin if held", "pct"), B.num_col("margin_pass", "margin if passed on", "pct")], title="Quotes to reprice first", h=400, open={"kind": "quote", "col": "quote_id"}, key="qt_t")]
    return {"blocks": bl, "m": {"margin_hold": kp(q.margin_hold), "margin_now": kp(q.margin_now), "margin_loss": float(((q.margin_now - q.margin_hold) * p0).sum()), "best_move": bx, "best_gain": float(max(curve) - ev(p0, c1)), "under5": int((q.margin_hold < .05).sum())}}
# ------------------------------------------------------------------------------------------------ carriers
def run_carrier(a):
    name = a.get("carrier"); loss = g(a, "loss", 100) / 100; dc = g(a, "delay_cost", 120); c = Q("SELECT name, rating, on_time_pct ot, avg_cost_index ci, risk_level FROM carriers")
    if not name or name not in set(c.name): name = Q("SELECT carrier, COUNT(*) n FROM shipments WHERE carrier IS NOT NULL GROUP BY carrier ORDER BY n DESC LIMIT 1").carrier[0]
    act = Q("SELECT shipment_id, carrier, weight_kg/1000.0 t, status FROM shipments WHERE status IN ('In Transit','Quoted','Anchorage Pending','Port Congestion Delay')"); load = act.groupby("carrier").size(); mine = act[act.carrier == name].sample(frac=loss, random_state=3) if len(act[act.carrier == name]) else act.iloc[0:0]
    c = c.assign(score=c.rating / 5 * 40 + c.ot * .4 - c.ci * 12 - (c.risk_level.str.lower().map({"low": 0, "medium": 6, "high": 14}).fillna(6))); cur = c[c.name == name].iloc[0]
    alts = c[(c.name != name) & c.name.isin(load.index)].sort_values("score", ascending=False).head(6).copy(); alts["cap"] = (load.reindex(alts.name).values * .30).round().clip(min=1)
    rows = []; room = dict(zip(alts.name, alts.cap))
    for r in mine.itertuples():
        pick = next((n for n in alts.name if room[n] > 0), None)
        if pick: room[pick] -= 1; al = alts[alts.name == pick].iloc[0]; rows.append({"shipment": r.shipment_id, "tonnes": r.t, "from": name, "to": pick, "cost_index": al.ci - cur.ci, "on_time": al.ot - cur.ot, "delay_cost": max(0, cur.ot - al.ot) * .08 * dc})
        else: rows.append({"shipment": r.shipment_id, "tonnes": r.t, "from": name, "to": "NO CAPACITY", "cost_index": np.nan, "on_time": np.nan, "delay_cost": np.nan})
    d = pd.DataFrame(rows)
    if not len(d): return {"blocks": [B.callout(f"{name} has no active shipments.", "info")], "m": {"unplaced": 0}}
    LAST["carrier"] = d; ok = d[d.to != "NO CAPACITY"]; ex = float((ok.cost_index * ok.tonnes * 400).sum()) + float(ok.delay_cost.sum())
    bl = [_cb("carrier"), B.kpis(("Shipments displaced", len(d), f"{name}, {loss:.0%} capacity lost"), ("Re-placed", len(ok), f"{len(d) - len(ok)} with no capacity", "Critical" if len(d) > len(ok) else None), ("Average cost index change", f"{ok.cost_index.mean():+.2f}" if len(ok) else "–"), ("Extra cost", usd(ex), "cost index × tonnes × $400 + delay cost")),
          B.card("Where the load goes", B.chart(B.bar(list(ok.groupby("to").size().index), {"shipments": list(ok.groupby("to").size().values)}, colors=[BLUE]), h=240, key="cr_c")),
          B.table(d.head(40), ["shipment", B.num_col("tonnes", "tonnes", "num"), "from", "to", B.num_col("cost_index", "cost index Δ", "num"), B.num_col("on_time", "on-time Δ (pts)", "num"), B.num_col("delay_cost", "delay cost", "money")], title="Re-assignments", h=380, key="cr_t")]
    return {"blocks": bl, "m": {"displaced": len(d), "unplaced": len(d) - len(ok), "extra": ex}}
# ------------------------------------------------------------------------------------------------ weather
def run_weather(a):
    area = a.get("area") or "Red Sea"; wind = g(a, "wind", 25); rad = g(a, "radius", 900); dem = g(a, "demurrage", 900); la, lo = STORM_AREAS.get(area, STORM_AREAS["Red Sea"])
    v = Q("SELECT v.shipment_id, v.lat, v.lon, v.progress, s.origin_port o, s.dest_port d, s.weight_kg/1000.0 t FROM vessels v JOIN shipments s USING(shipment_id)"); p = Q("SELECT port_name, lat, lon, avg_dwell_days dw, congestion_index ci FROM ports")
    v["dist"] = hav(v.lat.values, _wrap(v.lon.values), la, lo); hit = v[v.dist <= rad].copy(); p["dist"] = hav(p.lat.values, p.lon.values, la, lo); ph = p[p.dist <= rad]
    delay = lambda w: min(7.0, max(0.0, .25 * (w - 12))); dd = delay(wind); hit["delay_days"] = dd * (1 - hit.dist / rad * .5); hit["cost"] = hit.delay_days * dem
    sw = [(w, round(delay(w), 1), round(delay(w) * dem * max(len(hit), 0))) for w in (12, 18, 24, 30, 36)]
    bl = [_cb("weather"), B.kpis(("Vessels inside the storm", len(hit), f"of {len(v)} tracked", "Critical" if len(hit) > 5 else None), ("Delay per vessel", f"{dd:.1f} days", f"wind {wind:g} m/s"), ("Delay + demurrage cost", usd(hit.cost.sum())), ("Ports in the storm", len(ph), ", ".join(ph.port_name.head(3)) or "none")),
          B.card("Cost vs wind speed", B.chart(B.bar([f"{w} m/s" for w, _, _ in sw], {"cost": [c for _, _, c in sw]}, colors=[AMBER]), h=240, key="wx_s"), sub="For the vessels currently inside the radius"),
          B.table(hit.sort_values("cost", ascending=False).head(25)[["shipment_id", "o", "d", "t", "dist", "delay_days", "cost"]].rename(columns={"o": "origin", "d": "destination"}), [{"k": "shipment_id", "label": "shipment", "type": "id"}, "origin", "destination", B.num_col("t", "tonnes", "num"), B.num_col("dist", "nm from centre", "int"), B.num_col("delay_days", "delay days", "num"), B.num_col("cost", "cost", "money")], title="Vessels affected", h=380, open={"kind": "shipment", "col": "shipment_id"}, key="wx_t")]
    return {"blocks": bl, "m": {"hit": len(hit), "cost": float(hit.cost.sum()), "delay": dd}}
# ------------------------------------------------------------------------------------------------ customs
def run_customs(a):
    hp, dw, sc, duty = g(a, "hold", 20) / 100, g(a, "dwell", 4), g(a, "storage", 180), g(a, "duty", 0)
    s = Q("SELECT shipment_id, dest_port d, eta, weight_kg/1000.0 t, status FROM shipments WHERE status IN ('In Transit','Port Congestion Delay','Anchorage Pending','Customs Hold')").sort_values("eta")
    n = int(round(len(s) * hp)); held = s.head(n); cost = len(held) * dw * sc; by = held.groupby("d").size().sort_values(ascending=False).head(10)
    q = Q("SELECT SUM(customs_fee) cf, SUM(final_price) fp, COUNT(*) n FROM freight_quotes"); cf, fp = float(q.cf[0] or 0), float(q.fp[0] or 1); dcost = cf * duty / 7.5
    bl = [_cb("customs"), B.kpis(("Shipments held", len(held), f"{hp:.0%} of {len(s)} inbound", "Critical" if len(held) > 20 else None), ("Storage + delay cost", usd(cost), f"{dw:g} days × ${sc:g}"), ("Duty impact on open quotes", usd(dcost), f"{dcost / fp:.1%} of quote value", "Critical" if dcost / fp > .02 else None), ("Port most affected", by.index[0] if len(by) else "–", f"{int(by.iloc[0])} held" if len(by) else "")),
          B.card("Held shipments by destination", B.chart(B.bar(list(by.index), {"held": [int(x) for x in by.values]}, horizontal=True, colors=[VIOLET]), h=300, key="cu_c")),
          B.table(held.head(25), [{"k": "shipment_id", "label": "shipment", "type": "id"}, "d", "eta", B.num_col("t", "tonnes", "num"), "status"], title="First to be held", h=360, open={"kind": "shipment", "col": "shipment_id"}, key="cu_t")]
    return {"blocks": bl, "m": {"held": len(held), "cost": float(cost), "duty": float(dcost)}}
RUN = {"route": run_route, "carriers": run_carrier, "weather": run_weather, "quotes": run_quote, "margin": run_quote, "customs": run_customs}
