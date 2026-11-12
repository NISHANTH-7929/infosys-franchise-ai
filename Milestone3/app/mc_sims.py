"""Monte Carlo layer for every simulator. Each function returns blocks (distribution, risk numbers, exceedance, tornado, heat map, fan chart where there is a time axis).
Uncertain inputs are sampled around the values you set; the spreads are stated in each panel's note and are the first thing to calibrate with your own history."""
import numpy as np, pandas as pd
import blocks as B, mc
from blocks import Q
N = 1500
def _rng(): return np.random.default_rng(11)
def _norm(r, mu, sd, lo=None, hi=None): return np.clip(r.normal(mu, sd, N), lo, hi)
def _fan(x, M): return (x, M)
# ============================================================================== FRANCHISE
def fr_inventory(a):
    import sim_fr as S
    d = S._inv_frame(); outs = a.get("outlets") or []
    if outs: d = d[d.outlet_id.isin(outs)].reset_index(drop=True)
    if not len(d): return []
    dp, dl, buf, cv = S.g(a, "pct", 0) / 100, S.g(a, "days", 0), S.g(a, "buffer", 0) / 100, S.g(a, "cv", 30) / 100; uv = d.uv.values; se, dv, sd = S.g(a, "season", 15) / 100, S.g(a, "dvar", 2), S.seed_of(a); gmm = float(np.average(d.gm.values, weights=uv * d.weekly_demand.values))
    tot = lambda r: (r["lost"] * uv[:, None]).sum(0) * gmm
    base = S._inv_core(d, 0, 0, 0, cv, R=300, seed=sd + 21, season=se, dvar=dv); sc = S._inv_core(d, dp, dl, buf, cv, R=300, seed=sd + 21, season=se, dvar=dv); smp = tot(sc); today = float(tot(base).mean())
    fn = lambda p: float(tot(S._inv_core(d, p["dp"], p["dl"], p["buf"], p["cv"], R=50, seed=sd + 5, season=se, dvar=dv)).mean()); p0 = {"dp": dp, "dl": dl, "buf": buf, "cv": cv}
    torn = mc.sweep_tornado(fn, p0, {"Demand ±15%": ("dp", dp - .15, dp + .15), "Supplier delay ±3 days": ("dl", max(0, dl - 3), dl + 3), "Demand volatility ±15 pts": ("cv", max(.05, cv - .15), cv + .15), "Safety buffer 0% / +40%": ("buf", 0, .4)})
    xs, ys = [-10, 0, 10, 25, 40], [0, 2, 4, 7]; Z = mc.grid(fn, p0, "dp", [x / 100 for x in xs], "dl", ys)
    T = sc["day_lost"].shape[0]; paths = (np.cumsum(sc["day_lost"], 0) * gmm).T
    bl, _ = mc.panel("lost margin, next 30 days", smp, "money", "high", today=today, fan=_fan([f"D{i + 1}" for i in range(T)], paths), tornado=torn, key="mci",
                     heat={"title": "Expected lost margin: demand change × supplier delay", "x": [f"{x:+d}%" for x in xs], "y": [f"+{y}d" for y in ys], "Z": Z, "xname": "demand change", "yname": "supplier lead-time delay", "sub": "Darker red = more money lost; find the combination where the business breaks"},
                     note="300 futures: daily demand is random per SKU with a shared demand shock; reorders arrive after the lead time.")
    return bl
def _model_panel(metric, fn, p0, sd, spec, grid_spec, bad, today=None, unit="money", note=""):
    r = _rng(); keys = list(p0)
    S = {k: sd[k](r) for k in keys}; out = np.array([fn({k: S[k][i] for k in keys}) for i in range(N)])
    torn = mc.sweep_tornado(fn, p0, spec); kx, xs, xl, ky, ys, yl, tx, ty, title = grid_spec; Z = mc.grid(fn, p0, kx, xs, ky, ys)
    bl, _ = mc.panel(metric, out, unit, bad, today=today, tornado=torn, heat={"title": title, "x": xl, "y": yl, "Z": Z, "xname": tx, "yname": ty}, note=note, key="mc" + metric[:3].replace(" ", ""))
    return bl
def fr_workforce(a):
    import sim_fr as S; r = S.run_workforce(a); m = r["m"]
    if not m.get("model"): return []
    ab, cap, temp = S.g(a, "pct", 0) / 100, S.g(a, "ot_cap", 10), S.g(a, "temp", 0) / 100; f = lambda p: m["model"](float(np.clip(p["ab"], 0, .8)), float(max(0, p["cap"])), float(np.clip(p["temp"], 0, 1)))
    return _model_panel("monthly people cost", f, {"ab": ab, "cap": cap, "temp": temp}, {"ab": lambda r: _norm(r, ab, max(.03, ab * .3), 0, .8), "cap": lambda r: _norm(r, cap, 2, 0, 20), "temp": lambda r: _norm(r, temp, .1, 0, 1)},
                        {"Absenteeism ±10 pts": ("ab", max(0, ab - .1), ab + .1), "Overtime cap ±5 h": ("cap", max(0, cap - 5), cap + 5), "Temp cover 0% / 100%": ("temp", 0, 1)},
                        ("ab", [0, .1, .2, .3, .4], ["0%", "10%", "20%", "30%", "40%"], "temp", [0, .25, .5, .75, 1], ["0%", "25%", "50%", "75%", "100%"], "absenteeism", "temp cover", "Monthly cost: absenteeism × temp cover"), "high", today=f({"ab": 0, "cap": cap, "temp": 0}),
                        note="Absenteeism, overtime cap and temp cover are sampled around your settings (absenteeism spread = 30% of the value, at least 3 points).")
def fr_pnl(a):
    import sim_fr as S; r = S.run_pnl(a); m = r["m"]
    if not m.get("model"): return []
    dp, pp, cp = S.g(a, "pct", 0) / 100, S.g(a, "price", 0) / 100, S.g(a, "cost", 0) / 100; f = lambda p: m["model"](p["dp"], p["pp"], p["cp"])
    return _model_panel("profit change per month", f, {"dp": dp, "pp": pp, "cp": cp}, {"dp": lambda r: _norm(r, dp, .06), "pp": lambda r: _norm(r, pp, .02), "cp": lambda r: _norm(r, cp, .03)},
                        {"Demand ±10 pts": ("dp", dp - .1, dp + .1), "Price ±5 pts": ("pp", pp - .05, pp + .05), "Costs ±5 pts": ("cp", cp - .05, cp + .05)},
                        ("dp", [-.2, -.1, 0, .1, .2], ["-20%", "-10%", "0", "+10%", "+20%"], "cp", [-.05, 0, .05, .1, .2], ["-5%", "0", "+5%", "+10%", "+20%"], "demand change", "cost inflation", "Profit change: demand × cost inflation"), "low", today=0.0,
                        note="Demand, price and cost moves are sampled around your settings (spreads 6, 2 and 3 points).")
def fr_marketing(a):
    import sim_fr as S; mm = S._mk_frame()
    if not len(mm): return []
    bp, al = S.g(a, "pct", 0) / 100, S.g(a, "alpha", 70) / 100; B0 = mm.B.values; C0 = mm.C.values
    def f(p):
        alp = float(np.clip(p["al"], .3, .95)); k = C0 / B0 ** alp; return float((k * (B0 * (1 + p["bp"])) ** alp).sum())
    rr = _rng()
    S_ = {"bp": _norm(rr, bp, .05), "al": _norm(rr, al, .08, .3, .95)}; out = np.array([f({"bp": S_["bp"][i], "al": S_["al"][i]}) * rr.lognormal(0, .08) for i in range(N)])
    p0 = {"bp": bp, "al": al}; torn = mc.sweep_tornado(f, p0, {"Budget ±20 pts": ("bp", bp - .2, bp + .2), "Diminishing returns α ±0.15": ("al", al - .15, al + .15)})
    Z = mc.grid(f, p0, "bp", [-.3, -.15, 0, .25, .5], "al", [.5, .6, .7, .8, .9]); bl, _ = mc.panel("conversions", out, "num", "low", today=float(C0.sum()), tornado=torn, key="mcmk",
        heat={"title": "Conversions: budget change × diminishing-returns strength", "x": ["-30%", "-15%", "0", "+25%", "+50%"], "y": ["α .5", "α .6", "α .7", "α .8", "α .9"], "Z": Z, "xname": "total budget change", "yname": "returns exponent α"}, note="Budget change, α and per-run channel noise (8%) are sampled around your settings.")
    return bl
def fr_sentiment(a):
    import sim_fr as S; f_ = Q("SELECT outlet_id, COUNT(*) n, AVG(rating) r FROM feedback GROUP BY outlet_id"); o = Q("SELECT outlet_id, revenue FROM outlets"); d = f_.merge(o, on="outlet_id"); outs = a.get("outlets") or []
    if outs: d = d[d.outlet_id.isin(outs)]
    if not len(d): return []
    neg, nn = S.g(a, "pct", 25) / 100, S.g(a, "n_new", 30); n, rr_, rev = d.n.values, d.r.values, d.revenue.values
    def f(p):
        nv = max(0, p["nn"]); ng = float(np.clip(p["neg"], 0, 1)); mix = ng * 1.5 + (1 - ng) * 4.3; rn = (n * rr_ + nv * mix) / (n + nv); return float((np.maximum(0, rr_ - rn) * p["st"] * rev).sum())
    r = _rng(); sm = {"neg": _norm(r, neg, .08, 0, 1), "nn": _norm(r, nn, max(3, nn * .25), 0), "st": _norm(r, .07, .02, .01)}; out = np.array([f({k: v[i] for k, v in sm.items()}) for i in range(N)])
    p0 = {"neg": neg, "nn": nn, "st": .07}; torn = mc.sweep_tornado(f, p0, {"Negative share ±15 pts": ("neg", max(0, neg - .15), neg + .15), "New reviews ±40%": ("nn", nn * .6, nn * 1.4), "Revenue per star 3% / 11%": ("st", .03, .11)})
    Z = mc.grid(f, p0, "neg", [0, .1, .25, .5, .75], "nn", [10, 30, 60, 100]); bl, _ = mc.panel("revenue at risk per month", out, "money", "high", tornado=torn, key="mcse", heat={"title": "Revenue at risk: negative share × number of new reviews", "x": ["0%", "10%", "25%", "50%", "75%"], "y": ["10", "30", "60", "100"], "Z": Z, "xname": "share of new reviews that are negative", "yname": "new reviews"},
                note="Revenue sensitivity per star (7%, spread 2 points) is the biggest unknown; replace it with your own estimate.")
    return bl
def fr_audit(a):
    import sim_fr as S; raise_, extra, fine = S.g(a, "raise", 0), S.g(a, "pct", 0) / 100, S.g(a, "fine", 5000); outs = a.get("outlets") or []
    d = Q("SELECT outlet_id, score, violations FROM audits WHERE audit_id IN (SELECT audit_id FROM audits a2 WHERE a2.outlet_id=audits.outlet_id ORDER BY audit_date DESC LIMIT 1)")
    if outs: d = d[d.outlet_id.isin(outs)]
    if not len(d): return []
    sc, v = d.score.values, d.violations.values; pf = lambda s, mark: 1 / (1 + np.exp((s - mark) / 6)); r = _rng()
    p1 = pf(sc - extra * 20, 65 + raise_); fails = r.random((N, len(d))) < p1; out = (fails * (v * (1 + extra))[None, :] * fine * r.lognormal(0, .15, (N, 1))).sum(1)
    f = lambda p: float((pf(sc - p["ex"] * 20, 65 + p["rs"]) * v * (1 + p["ex"]) * p["fi"]).sum()); p0 = {"ex": extra, "rs": raise_, "fi": fine}
    torn = mc.sweep_tornado(f, p0, {"Stricter pass mark 0 / +10": ("rs", 0, 10), "Extra violations ±10 pts": ("ex", max(0, extra - .1), extra + .1), "Fine per violation ±40%": ("fi", fine * .6, fine * 1.4)})
    Z = mc.grid(f, p0, "rs", [0, 5, 10, 15], "ex", [0, .1, .2, .3]); nf = fails.sum(1)
    bl, _ = mc.panel("audit fines", out, "money", "high", tornado=torn, key="mcau", heat={"title": "Expected fines: pass mark × extra violations", "x": ["+0", "+5", "+10", "+15"], "y": ["0%", "+10%", "+20%", "+30%"], "Z": Z, "xname": "pass mark raised by", "yname": "extra violations"},
                note=f"Each outlet fails or passes by chance (logistic on its last score). Failing outlets: median {int(np.median(nf))}, 95% of runs ≤ {int(np.percentile(nf, 95))}.")
    return bl
# ============================================================================== FREIGHT
def fq_route(a):
    import sim_fq as S
    L = getattr(S, "LAST", {}).get("route")
    if L is None or not len(L): return []
    dist, dly = float(L.dist_cost.sum()), float(L.delay_cost.sum()); f = lambda p: p["m1"] * dist + p["m2"] * dly; r = _rng()
    out = np.array([f({"m1": m1, "m2": m2}) for m1, m2 in zip(r.lognormal(0, .18, N), r.lognormal(0, .35, N))]) * r.lognormal(0, .1, N)
    p0 = {"m1": 1.0, "m2": 1.0}; torn = mc.sweep_tornado(f, p0, {"Freight rate ±30%": ("m1", .7, 1.3), "Delay cost / waiting ±50%": ("m2", .5, 1.5)}); Z = mc.grid(f, p0, "m1", [.7, .85, 1, 1.15, 1.3], "m2", [.5, .75, 1, 1.5, 2])
    bl, _ = mc.panel("extra cost of the re-route", out, "money", "high", tornado=torn, key="mcrt", heat={"title": "Extra cost: freight rate × delay cost", "x": ["-30%", "-15%", "base", "+15%", "+30%"], "y": ["×0.5", "×0.75", "×1", "×1.5", "×2"], "Z": Z, "xname": "freight rate vs assumption", "yname": "delay cost vs assumption"},
                note="Distances come from the sea-route model; the rate per tonne-mile (spread 18%) and the cost of waiting (spread 35%) are uncertain and sampled.")
    return bl
def fq_quote(a):
    import sim_fq as S; fuel, car, fx, disc = S.g(a, "pct", 0) / 100, S.g(a, "carrier", 0) / 100, S.g(a, "fx", 0) / 100, S.g(a, "discount", 0) / 100
    q = Q("SELECT base_cost, customs_fee, fuel_surcharge, final_price, margin_pct FROM freight_quotes WHERE final_price>0 ORDER BY created_at DESC LIMIT 400")
    if not len(q): return []
    p0v = q.final_price.values; c0 = p0v * (1 - q.margin_pct.values / 100); bc, cf, fs = q.base_cost.values, q.customs_fee.values, q.fuel_surcharge.values
    f = lambda p: float((p0v - (c0 + bc * ((1 + p["car"]) * (1 + p["fx"]) - 1) + cf * p["fx"] + fs * p["fu"])).sum()); r = _rng()
    sm = {"car": _norm(r, car, .03), "fx": _norm(r, fx, .03), "fu": _norm(r, fuel, .08)}; out = np.array([f({k: v[i] for k, v in sm.items()}) for i in range(N)]); p0 = {"car": car, "fx": fx, "fu": fuel}
    torn = mc.sweep_tornado(f, p0, {"Fuel ±15 pts": ("fu", fuel - .15, fuel + .15), "Carrier rates ±8 pts": ("car", car - .08, car + .08), "Currency ±8 pts": ("fx", fx - .08, fx + .08)}); Z = mc.grid(f, p0, "fu", [-.1, 0, .1, .2, .3], "car", [-.05, 0, .05, .1, .2])
    bl, _ = mc.panel("total margin if prices are held", out, "money", "low", today=float((p0v - c0).sum()), tornado=torn, key="mcqt", heat={"title": "Margin: fuel move × carrier rate move", "x": ["-10%", "0", "+10%", "+20%", "+30%"], "y": ["-5%", "0", "+5%", "+10%", "+20%"], "Z": Z, "xname": "fuel move", "yname": "carrier rate move"},
                note="Fuel (spread 8 points), carrier rate and currency (3 points each) are sampled around your settings; prices on open quotes stay as quoted.")
    return bl
def fq_weather(a):
    import sim_fq as S; area = a.get("area") or "Red Sea"; la, lo = S.STORM_AREAS.get(area, S.STORM_AREAS["Red Sea"]); wind, rad, dem = S.g(a, "wind", 25), S.g(a, "radius", 900), S.g(a, "demurrage", 900)
    v = Q("SELECT lat, lon FROM vessels");
    if not len(v): return []
    dist = S.hav(v.lat.values, S._wrap(v.lon.values), la, lo)
    def f(p):
        rd = max(50, p["rad"]); h = dist[dist <= rd]; dl = min(7.0, max(0.0, .25 * (p["w"] - 12))); return float((dl * (1 - h / rd * .5) * p["dem"]).sum())
    r = _rng(); sm = {"w": _norm(r, wind, 4, 8), "rad": _norm(r, rad, rad * .15, 100), "dem": r.lognormal(np.log(max(dem, 1)), .25, N)}; out = np.array([f({k: v_[i] for k, v_ in sm.items()}) for i in range(N)])
    p0 = {"w": wind, "rad": rad, "dem": dem}; torn = mc.sweep_tornado(f, p0, {"Wind ±8 m/s": ("w", wind - 8, wind + 8), "Storm radius ±300 nm": ("rad", max(100, rad - 300), rad + 300), "Demurrage ±40%": ("dem", dem * .6, dem * 1.4)}); Z = mc.grid(f, p0, "w", [14, 20, 26, 32, 38], "rad", [400, 700, 900, 1200, 1600])
    bl, _ = mc.panel("storm delay + demurrage cost", out, "money", "high", tornado=torn, key="mcwx", heat={"title": "Cost: wind speed × storm radius", "x": [f"{x} m/s" for x in (14, 20, 26, 32, 38)], "y": [f"{y} nm" for y in (400, 700, 900, 1200, 1600)], "Z": Z, "xname": "wind speed", "yname": "storm radius"},
                note="Wind (±4 m/s), radius (±15%) and demurrage rate (±25%) are uncertain because storm forecasts are; they are sampled around your settings.")
    return bl
def fq_customs(a):
    import sim_fq as S; hp, dw, sc = S.g(a, "hold", 20) / 100, S.g(a, "dwell", 4), S.g(a, "storage", 180)
    s = Q("SELECT shipment_id FROM shipments WHERE status IN ('In Transit','Port Congestion Delay','Anchorage Pending','Customs Hold')"); n0 = len(s)
    if not n0: return []
    f = lambda p: float(round(n0 * float(np.clip(p["hp"], 0, 1))) * max(0, p["dw"]) * p["sc"]); r = _rng()
    out = np.array([r.binomial(n0, float(np.clip(h, 0, 1))) * max(0, d) * c for h, d, c in zip(_norm(r, hp, .05, 0, 1), r.gamma(4, max(dw, .1) / 4, N), r.lognormal(np.log(max(sc, 1)), .15, N))])
    p0 = {"hp": hp, "dw": dw, "sc": sc}; torn = mc.sweep_tornado(f, p0, {"Hold rate ±10 pts": ("hp", max(0, hp - .1), hp + .1), "Extra dwell ±2 days": ("dw", max(0, dw - 2), dw + 2), "Storage cost ±$60": ("sc", max(10, sc - 60), sc + 60)}); Z = mc.grid(f, p0, "hp", [.05, .1, .2, .3, .5], "dw", [1, 2, 4, 6, 8])
    bl, _ = mc.panel("customs hold cost", out, "money", "high", tornado=torn, key="mccu", heat={"title": "Cost: hold rate × dwell days", "x": ["5%", "10%", "20%", "30%", "50%"], "y": ["1d", "2d", "4d", "6d", "8d"], "Z": Z, "xname": "share of inbound held", "yname": "extra dwell days"}, note="Which shipments get held is random (binomial); dwell days follow a gamma distribution around your setting.")
    return bl
def fq_carrier(a):
    import sim_fq as S; m = S.LAST.get("carrier") if hasattr(S, "LAST") else None
    if m is None or not len(m): return []
    ok = m[m.to != "NO CAPACITY"]; n = len(m); base_ex = float((ok.cost_index * ok.tonnes * 400).sum()) + float(ok.delay_cost.sum()); r = _rng()
    # capacity of alternatives is uncertain: each re-placement succeeds with p, failures pay a spot-market premium of 35% of $400/tonne equivalent
    pl = len(ok) / max(n, 1); out = []
    for _ in range(N):
        cap = np.clip(r.normal(1, .25), .2, 1.8); k = r.binomial(n, float(np.clip(pl * cap, 0, 1))); spot = (n - k) * float(m.tonnes.mean() or 1) * 400 * .35; out.append(base_ex * r.lognormal(0, .2) + spot)
    out = np.array(out); f = lambda p: base_ex * p["m"] + (n - round(n * min(1, pl * p["cap"]))) * float(m.tonnes.mean() or 1) * 400 * .35; p0 = {"m": 1.0, "cap": 1.0}
    torn = mc.sweep_tornado(f, p0, {"Alternative capacity ±40%": ("cap", .6, 1.4), "Cost index change ±50%": ("m", .5, 1.5)}); Z = mc.grid(f, p0, "cap", [.4, .7, 1, 1.3], "m", [.5, 1, 1.5, 2])
    bl, _ = mc.panel("cost of the carrier outage", out, "money", "high", tornado=torn, key="mccr", heat={"title": "Cost: spare capacity × cost increase", "x": ["×0.4", "×0.7", "×1", "×1.3"], "y": ["×0.5", "×1", "×1.5", "×2"], "Z": Z, "xname": "spare capacity at alternatives", "yname": "cost-index penalty"},
                note="Spare capacity at the alternative carriers is the big unknown (±25%); shipments that cannot be placed pay a 35% spot-market premium.")
    return bl
MC = {"Franchise": {"inventory": fr_inventory, "workforce": fr_workforce, "outlets": fr_pnl, "marketing": fr_marketing, "sentiment": fr_sentiment, "audit": fr_audit},
      "Freight": {"route": fq_route, "quotes": fq_quote, "margin": fq_quote, "weather": fq_weather, "customs": fq_customs, "carriers": fq_carrier}}
def blocks(kind, pid, a):
    f = MC.get(kind, {}).get(pid)
    if not f: return []
    try:
        bl = f(a)
    except Exception as e:
        import traceback, sys; traceback.print_exc(file=sys.stderr); return [B.callout(f"Monte Carlo panel skipped: {e}", "warn")]
    return [B.md("### Monte Carlo risk analysis")] + bl if bl else []
