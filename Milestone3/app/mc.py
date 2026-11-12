"""Monte Carlo panel shared by every simulator and the Digital Twin: distribution, risk numbers, exceedance curve, fan chart, tornado and a two-factor heat map.
Everything is plain ECharts options so it needs no extra front-end code."""
import numpy as np
import blocks as B
from blocks import TEAL, BLUE, AMBER, RED, VIOLET, GREY, L, clean
GRID = {"left": 8, "right": 18, "top": 30, "bottom": 6, "containLabel": True}
SPLIT = {"lineStyle": {"color": "#eceef6"}}
def fmt(x, unit="money"):
    x = float(x)
    if unit == "money":
        s = "-" if x < 0 else ""; x = abs(x); return s + ("₹%.2f Cr" % (x / 1e7) if x >= 1e7 else "₹%.2f L" % (x / 1e5) if x >= 1e5 else "₹{:,.0f}".format(x))
    if unit == "pct": return f"{x:.1%}"
    return f"{x:,.1f}" if abs(x) < 1000 else f"{x:,.0f}"
def stats(v, bad="high"):
    v = np.asarray(v, float); v = v[np.isfinite(v)]; p = lambda q: float(np.percentile(v, q))
    tail = v[v >= p(95)] if bad == "high" else v[v <= p(5)]
    return {"mean": float(v.mean()), "sd": float(v.std()), "p5": p(5), "p10": p(10), "p50": p(50), "p90": p(90), "p95": p(95), "p5lo": p(5), "var95": p(95) if bad == "high" else p(5), "cvar95": float(tail.mean()) if len(tail) else p(95)}
def density(v, bins=36):
    v = np.asarray(v, float); h, e = np.histogram(v, bins=bins); c = (e[:-1] + e[1:]) / 2; return c, h / max(h.sum(), 1)
def hist_opt(v, st, unit, color=BLUE, base=None):
    c, p = density(v); idx = lambda x: int(np.argmin(np.abs(c - x)))
    marks = [{"xAxis": idx(st["p10"]), "name": "P10"}, {"xAxis": idx(st["p50"]), "name": "P50"}, {"xAxis": idx(st["p90"]), "name": "P90"}]
    if base is not None: marks.append({"xAxis": idx(base), "name": "today"})
    ml = {"symbol": "none", "label": {"formatter": "{b}", "fontSize": 10}, "lineStyle": {"type": "dashed", "color": GREY}, "data": marks}
    o = B._base(grid=GRID); o.update({"tooltip": {"trigger": "axis", "confine": True}, "xAxis": {"type": "category", "data": [fmt(x, unit) for x in c], "axisLabel": {"hideOverlap": True, "fontSize": 10}}, "yAxis": {"type": "value", "name": "probability", "axisLabel": {"formatter": "{value}"}, "splitLine": SPLIT},
        "series": [{"type": "bar", "data": [round(float(x), 4) for x in p], "itemStyle": {"color": color, "borderRadius": [3, 3, 0, 0]}, "barCategoryGap": "6%", "markLine": ml},
                   {"type": "line", "data": [round(float(x), 4) for x in np.convolve(np.pad(p, 2, mode="edge"), np.ones(5) / 5, "valid")[:len(p)]], "smooth": True, "showSymbol": False, "lineStyle": {"color": RED, "width": 2}}]}); return o
def exceed_opt(v, unit, bad="high"):
    v = np.sort(np.asarray(v, float)); n = len(v); pr = 1 - np.arange(1, n + 1) / n if bad == "high" else np.arange(1, n + 1) / n; step = max(1, n // 120)
    o = B._base(grid=GRID); o.update({"xAxis": {"type": "category", "data": [fmt(x, unit) for x in v[::step]], "axisLabel": {"hideOverlap": True, "fontSize": 10}}, "yAxis": {"type": "value", "min": 0, "max": 1, "name": "chance outcome is worse" if bad == "high" else "chance outcome is lower", "axisLabel": {"formatter": "{value}"}, "splitLine": SPLIT},
        "series": [{"type": "line", "data": [round(float(x), 3) for x in pr[::step]], "showSymbol": False, "lineStyle": {"color": RED, "width": 2}, "areaStyle": {"color": "rgba(229,72,77,.12)"}, "markLine": {"symbol": "none", "silent": True, "lineStyle": {"type": "dashed", "color": GREY}, "label": {"formatter": "{b}", "fontSize": 10}, "data": [{"yAxis": .5, "name": "50%"}, {"yAxis": .1, "name": "10%"}, {"yAxis": .05, "name": "5%"}]}}]}); return o
def fan_opt(x, M, color=BLUE, unit="money"):
    """M: (paths, steps) matrix; bands P5-95, P25-75 and the median."""
    M = np.asarray(M, float); q = lambda p: np.percentile(M, p, axis=0); p5, p25, p50, p75, p95 = q(5), q(25), q(50), q(75), q(95)
    band = lambda lo, hi, a: [{"type": "line", "data": L(lo), "stack": f"s{a}", "lineStyle": {"opacity": 0}, "showSymbol": False, "silent": True, "tooltip": {"show": False}}, {"type": "line", "data": L(hi - lo), "stack": f"s{a}", "lineStyle": {"opacity": 0}, "areaStyle": {"color": color, "opacity": a}, "showSymbol": False, "silent": True, "tooltip": {"show": False}}]
    o = B._base(grid=GRID); o.update({"xAxis": {"type": "category", "data": L(x), "boundaryGap": False, "axisLabel": {"hideOverlap": True}}, "yAxis": {"type": "value", "scale": True, "splitLine": SPLIT},
        "series": band(p5, p95, .12) + band(p25, p75, .25) + [{"type": "line", "name": "median", "data": L(p50), "showSymbol": False, "smooth": True, "lineStyle": {"color": color, "width": 2.5}}]}); return o
def tornado_opt(rows, unit="money"):
    """rows: [(label, low_delta, high_delta)] change of the outcome when the input moves down/up."""
    rows = sorted(rows, key=lambda r: max(abs(r[1]), abs(r[2])))
    o = B._base(legend=True, grid={"left": 8, "right": 18, "top": 30, "bottom": 6, "containLabel": True}); o.update({"tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, "confine": True},
        "yAxis": {"type": "category", "data": [r[0] for r in rows], "axisLabel": {"fontSize": 11}}, "xAxis": {"type": "value", "splitLine": SPLIT, "name": "change in outcome"},
        "series": [{"type": "bar", "name": "input lower", "stack": "t", "data": [round(float(r[1]), 2) for r in rows], "itemStyle": {"color": BLUE}, "barMaxWidth": 20}, {"type": "bar", "name": "input higher", "stack": "t", "data": [round(float(r[2]), 2) for r in rows], "itemStyle": {"color": AMBER}, "barMaxWidth": 20}]}); return o
def heat_opt(xl, yl, Z, xname, yname, unit="money", good_low=True):
    Z = np.asarray(Z, float); data = [[i, j, round(float(Z[j, i]), 2)] for j in range(len(yl)) for i in range(len(xl))]; lo, hi = float(Z.min()), float(Z.max())
    cols = ["#12a594", "#f5a524", "#e5484d"] if good_low else ["#e5484d", "#f5a524", "#12a594"]
    o = B._base(); o.update({"tooltip": {"confine": True}, "grid": {"left": 8, "right": 14, "top": 8, "bottom": 52, "containLabel": True}, "xAxis": {"type": "category", "data": xl, "name": xname, "nameLocation": "middle", "nameGap": 26, "splitArea": {"show": True}}, "yAxis": {"type": "category", "data": yl, "name": yname, "splitArea": {"show": True}},
        "visualMap": {"min": lo, "max": hi if hi > lo else lo + 1, "calculable": False, "orient": "horizontal", "left": "center", "bottom": 0, "inRange": {"color": cols}, "itemWidth": 12, "itemHeight": 120, "text": ["high", "low"]},
        "series": [{"type": "heatmap", "data": data, "label": {"show": len(xl) * len(yl) <= 36, "fontSize": 10}, "emphasis": {"itemStyle": {"shadowBlur": 6}}}]}); return o
def panel(metric, samples, unit="money", bad="high", today=None, fan=None, tornado=None, heat=None, n_label=None, note=None, key="mc"):
    """Returns a list of blocks. samples: outcomes of many simulated futures. bad: which tail is the risk ('high' = costs/losses, 'low' = profit/conversions)."""
    s = stats(samples, bad); n = len(samples); w = "worst-case" if bad == "high" else "bad-case"
    prob = None
    if today is not None: prob = float(np.mean(np.asarray(samples) > today)) if bad == "high" else float(np.mean(np.asarray(samples) < today))
    k = [(f"Expected {metric}", fmt(s["mean"], unit), f"P10–P90 {fmt(s['p10'], unit)} – {fmt(s['p90'], unit)}"), ("Median (P50)", fmt(s["p50"], unit)), (f"{w} 1-in-20 (VaR 95)", fmt(s["var95"], unit), "95% of futures are better than this"), (f"Average of worst 5% (CVaR)", fmt(s["cvar95"], unit), "what a really bad run looks like")]
    if prob is not None: k.append(("Chance of being worse than today", f"{prob:.0%}", "across all simulated futures", "Critical" if prob > .6 else None))
    bl = [B.callout(f"Monte Carlo: {n:,} simulated futures with random demand, timing and model uncertainty. {note or ''}".strip(), "info", "How to read these charts"), B.kpis(*k)]
    r1 = [B.card(f"Distribution of {metric}", B.chart(hist_opt(samples, s, unit, base=today), h=250, key=key + "_h"), sub="Bars = how likely each outcome is; dashed lines mark P10 / P50 / P90"),
          B.card("Exceedance curve", B.chart(exceed_opt(samples, unit, bad), h=250, key=key + "_e"), sub="Read across: how likely is it to end up beyond a given value")]
    bl.append(B.row(*r1))
    r2 = []
    if fan is not None: r2.append(B.card("Fan chart over time", B.chart(fan_opt(fan[0], fan[1], unit=unit), h=260, key=key + "_f"), sub="Dark band = middle 50% of futures, light band = 90%; line = median"))
    if tornado: r2.append(B.card("What drives the result (tornado)", B.chart(tornado_opt(tornado, unit), h=260, key=key + "_t"), sub="Each input moved down/up on its own; the longest bar matters most"))
    if r2: bl.append(B.row(*r2))
    if heat: bl.append(B.card(heat["title"], B.chart(heat_opt(heat["x"], heat["y"], heat["Z"], heat["xname"], heat["yname"], unit, good_low=(bad == "high")), h=280, key=key + "_hm"), sub=heat.get("sub")))
    return bl, s
def sweep_tornado(fn, base, spec):
    """fn(params)->float. spec: {label: (key, low, high)}; returns rows (label, d_low, d_high) relative to fn(base)."""
    b0 = fn(base); out = []
    for lab, (k, lo, hi) in spec.items():
        a = dict(base); a[k] = lo; c = dict(base); c[k] = hi; out.append((lab, fn(a) - b0, fn(c) - b0))
    return out
def grid(fn, base, kx, xs, ky, ys):
    Z = np.zeros((len(ys), len(xs)))
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            p = dict(base); p[kx] = x; p[ky] = y; Z[j, i] = fn(p)
    return Z
