"""Copilot Pro - the SQL-only assistant, upgraded. No LLM, no RAG: every number comes from a read-only query.
Layers (each is plain Python you can read and extend):
  1. small talk      greetings, thanks, goodbye, "who are you", "what can you do"
  2. typo repair     fuzzy-corrects words against the vocabulary of this app's tables, columns, places and names
  3. conversation    follow-ups ("and OUT-010?", "what about Mumbai", "top 10 instead", "its staff") use the previous turn
  4. smart intents   daily briefing, compare two entities, entity profile, export, show SQL
  5. exact engine    analyst.py (explanations) then qa.py (whitelisted NL->SQL)
  6. presentation    auto chart, follow-up suggestions, "interpreted as" note, CSV export, type-ahead, thumbs feedback
Every question that could not be answered is logged (table copilot_unanswered) so you can see what to teach it next."""
import re, io, time, json, difflib, sqlite3, threading, collections, datetime
import pandas as pd
import qa as QA, analyst as AN, blocks as B
from blocks import Q
from config import DB_PATH

ID_RE = re.compile(r"\b((?:OUT|STF|EMP|SHP|QTE|PORT|CAR|CUST|CMP|CAMP|AUD|FB)-[A-Z0-9]*\d[A-Z0-9-]*)\b", re.I)
GREET = re.compile(r"^\W*(hi+|hello+|hey+|hola|namaste|yo|good (morning|afternoon|evening|day)|greetings|howdy|sup)\b[\w\s!.,?]*$", re.I)
THANKS = re.compile(r"^\W*(thanks|thank you|thx|ty|ok thanks|great|cool|nice|awesome|perfect|got it|ok|okay)\b[\w\s!.,]*$", re.I)
BYE = re.compile(r"^\W*(bye|goodbye|see you|good night|cya|later)\b[\w\s!.,]*$", re.I)
HOWARE = re.compile(r"\b(how are you|how r u|how's it going|whats up|what's up)\b", re.I)
WHO = re.compile(r"\b(who are you|what are you|your name|who made you|who built you)\b", re.I)
TIME = re.compile(r"\b(what('?s| is) the (time|date|day)|current time|today'?s date|what day is it|time now|date today|what time is it)\b", re.I)
HELP = re.compile(r"^\W*(help|what can you do|what do you do|how (do|can) i use|commands|capabilities|what can i ask|examples?)\b", re.I)
BRIEF = re.compile(r"\b(briefing|brief me|overview|summary|summari[sz]e|status report|dashboard|health check|what needs (my )?attention|what'?s happening|big picture|key numbers|kpis?|situation)\b", re.I)
COMPARE = re.compile(r"\b(compare|versus|vs\.?|difference between)\b", re.I)
SHOWSQL = re.compile(r"\b(show|give|what'?s?) (me )?(the )?(sql|query)\b|how did you (get|calculate|work out)", re.I)
FOLLOW = re.compile(r"^\W*(and|what about|how about|same for|now|also|then|what of)\b\s*", re.I)
MORE = re.compile(r"^\W*(more|show more|next|go on|continue|another|show all|expand)\W*$", re.I)
TOPN = re.compile(r"\b(?:top|bottom|first|last)\s+(\d+)\b", re.I)
PRON = re.compile(r"\b(its|their|it|them|this (?:outlet|store|branch|shipment|quote|carrier|port|customer|campaign|employee|member)|that (?:outlet|store|branch|shipment|quote|carrier|port|customer|campaign|employee|member)|the same (?:outlet|store|shipment|quote|carrier|port))\b", re.I)

STOP = set("""about above after again against also always among another answer any are around ask asked asking available because been before being below between both brief but can cannot could current currently data database did does doing done down during each either else enough ever every explain find first following for from further get give given going good great had has have having here highest how however into its itself just keep know last least less let like list little look made make many may maybe might more most much must need never next none nor not now number off often once only other ought our out over own per please put rather really same say see seems shall she should show since some still such take tell than that the their them then there these they thing think this those though three through thus tight time today together too top toward under until upon use used using very want was way well were what when where whether which while who whom whose why will with within without would write year years yes you your yours""".split())
EXTRA_WORDS = """highest lowest average total number count revenue satisfaction customer inventory staff employees outlets stores campaigns marketing sentiment feedback reviews audit audits compliance violations stockout reorder threshold attrition overtime salary headcount tickets shipments quotes carriers ports customers weather congestion congested delay delayed margin price customs duty vessels route routes delivery rating ratings largest smallest biggest cheapest riskiest weakest strongest compare location locations region regions country tier category channel status severity critical briefing overview summary""".split()

# ------------------------------------------------------------------ vocabulary / typo repair
_V = {"t": 0, "words": set(), "list": [], "corpus": [], "places": []}
def _vocab():
    if time.time() - _V["t"] < 600 and _V["words"]: return _V
    kind = _kind(); w = set(EXTRA_WORDS)
    for t, (syn, idc, cols, _m) in QA.TABLES[kind].items():
        w.add(t); w.update(re.findall(r"[a-z]{3,}", " ".join(syn + cols).lower()))
    for c, syns in QA.CSYN.items(): w.update(re.findall(r"[a-z]{3,}", " ".join(syns + [c.replace("_", " ")]).lower()))
    vals = []; places = set()
    for t, (syn, idc, cols, _m) in QA.TABLES[kind].items():
        for c in cols:
            if c in ("location", "tier", "role", "category", "channel", "region", "country", "origin_port", "dest_port", "carrier", "port_name", "industry", "name", "outlet_name", "sku_name", "campaign_name", "risk_level", "priority_tier", "status"):
                try:
                    got = Q(f"SELECT DISTINCT {c} v FROM {t} WHERE {c} IS NOT NULL LIMIT 400").v.astype(str).tolist(); vals += got
                    if c in ("location", "port_name", "country", "region", "origin_port", "dest_port"): places.update(got)
                except Exception: pass
    for v in vals: w.update(re.findall(r"[a-z]{3,}", v.lower()))
    pv = set(places)
    for p0 in places:
        pv.add(re.sub(r"\s*\(.*?\)", "", p0).strip()); pv.update(re.findall(r"\(([^)]+)\)", p0)); pv.add(re.sub(r"\s+(Port|Terminal|Harbou?r)$", "", p0).strip())
    _V.update(t=time.time(), words=w, list=sorted(w), corpus=sorted(set(vals)), places=sorted({x for x in pv if len(x) >= 4}, key=len, reverse=True))
    return _V
def _kind():
    import config; return config.KIND
def correct(q):
    V = _vocab(); out, changed = [], []
    def fix(m):
        tok = m.group(0); low = tok.lower()
        if len(low) < 5 or low in V["words"] or low in STOP or any(len(low) - k >= 4 and low[:-k] in V["words"] for k in (1, 2, 3)): return tok
        cand = [c for c in difflib.get_close_matches(low, V["list"], n=3, cutoff=0.84) if c[0] == low[0] and abs(len(c) - len(low)) <= 2]
        if not cand: return tok
        changed.append((tok, cand[0])); return cand[0].capitalize() if tok[0].isupper() else cand[0]
    new = re.sub(r"(?<![A-Za-z0-9-])[A-Za-z]{5,}(?![A-Za-z0-9-])", fix, q)
    return new, changed

# ------------------------------------------------------------------ conversation memory
_S = collections.OrderedDict(); _L = threading.Lock()
def session(sid):
    with _L:
        s = _S.get(sid)
        if s is None:
            s = _S[sid] = {"q": "", "ids": [], "df": None, "sql": "", "turns": 0}
            while len(_S) > 300: _S.popitem(last=False)
        _S.move_to_end(sid); return s
def last_csv(sid):
    s = _S.get(sid); df = s and s.get("df")
    return df.to_csv(index=False) if df is not None and len(df) else None

def _places_in(t):
    hits = []
    for p in _vocab()["places"]:
        for m in re.finditer(r"(?<![A-Za-z])" + re.escape(p) + r"(?![A-Za-z])", t, re.I):
            if not any(m.start() < e and m.end() > b for b, e, _ in hits): hits.append((m.start(), m.end(), p))
    return sorted(hits)
def _place_in(t):
    h = _places_in(t); return h[-1][2] if h else None
def _swap_place(old_q, new_place):
    h = _places_in(old_q)
    if not h: return None
    b, e, _ = h[-1]; return old_q[:b] + new_place + old_q[e:]
def contextualize(q, s):
    """Rewrite a follow-up into a self-contained question, using the previous turn."""
    ql = q.strip(); note = None; ids = [i.upper() for i in ID_RE.findall(q)]
    if MORE.match(ql) and s["q"]:
        m = TOPN.search(s["q"]); n = min(50, (int(m.group(1)) * 2) if m else 20)
        base = TOPN.sub(f"top {n}", s["q"]) if m else s["q"] + f" top {n}"; return base, f"showing more: {base}"
    m = TOPN.search(ql)
    if m and s["q"] and len(ql.split()) <= 4 and not re.search(r"\b(outlet|store|staff|shipment|quote|carrier|port|campaign|customer|audit|item|sku)", ql):
        base = TOPN.sub(m.group(0), s["q"]) if TOPN.search(s["q"]) else s["q"] + " " + m.group(0); return base, f"{base}"
    if FOLLOW.match(ql) and s["q"]:
        rest = FOLLOW.sub("", ql).strip(" ?.!")
        if ids and s["ids"] and ID_RE.search(s["q"]): new = ID_RE.sub(ids[0], s["q"], count=1)
        elif ids and re.search(r"\b(staff|inventory|revenue|risk|why|quote|customs|weather|margin|campaign|audit|sentiment|feedback)\b", rest, re.I) is None: new = s["q"] + " " + rest
        elif ids: new = (rest if len(rest.split()) > 2 else rest + " " + s["q"])
        elif _place_in(rest) and _place_in(s["q"]): new = _swap_place(s["q"], _place_in(rest))
        elif re.match(r"^(in|at|for|from|to)\b", rest, re.I): new = s["q"] + " " + rest
        elif len(rest.split()) <= 3: new = s["q"] + " in " + rest
        else: new = rest
        return new, new
    if not ids and s["ids"] and PRON.search(ql):
        new = PRON.sub(s["ids"][0], ql, count=1); return new, new
    return q, None

# ------------------------------------------------------------------ smart intents
def _num(sql, p=()):
    try:
        r = Q(sql, p); return None if not len(r) else r.iloc[0, 0]
    except Exception: return None
def _f(v, d=1): return "n/a" if v is None or v != v else (f"{v:,.{d}f}" if isinstance(v, float) else f"{int(v):,}")

def briefing(kind, dec, dom):
    rows, sqls = [], []
    def add(label, sql, d=1, suffix=""):
        v = _num(sql); rows.append((label, _f(v, d) + suffix)); sqls.append(sql)
    if kind == "Franchise":
        add("Outlets", "SELECT COUNT(*) FROM outlets", 0); add("Total revenue", "SELECT SUM(revenue) FROM outlets", 0)
        add("Avg customer satisfaction", "SELECT AVG(customer_satisfaction) FROM outlets", 2); add("Staff", "SELECT COUNT(*) FROM staff", 0)
        add("Staff with attrition risk > 60%", "SELECT COUNT(*) FROM staff WHERE predicted_attrition_prob>0.6", 0)
        add("Items below reorder level", "SELECT COUNT(*) FROM inventory WHERE current_stock<reorder_threshold", 0)
        add("Avg audit score", "SELECT AVG(score) FROM audits", 1); add("Avg review rating", "SELECT AVG(rating) FROM feedback", 2)
        add("Open agent tickets", "SELECT COUNT(*) FROM agent_actions WHERE status IN ('open','proposed')", 0)
        focus_q = "Which outlets are at highest risk?"
    else:
        add("Shipments", "SELECT COUNT(*) FROM shipments", 0); add("Avg delay risk", "SELECT AVG(predicted_delay_risk) FROM shipments", 2)
        add("Quotes", "SELECT COUNT(*) FROM freight_quotes", 0); add("Avg margin %", "SELECT AVG(margin_pct) FROM freight_quotes", 1)
        add("Avg port congestion", "SELECT AVG(congestion_index) FROM ports", 2); add("Avg carrier on-time %", "SELECT AVG(on_time_pct) FROM carriers", 1)
        add("Weather points above 0.5 severity", "SELECT COUNT(*) FROM weather_risks WHERE current_severity>0.5", 0)
        add("Open agent tickets", "SELECT COUNT(*) FROM agent_actions WHERE status IN ('open','proposed')", 0)
        focus_q = "Which ports are most congested?"
    text = "**Briefing: the numbers right now**\n\n" + "\n".join(f"- {a}: **{b}**" for a, b in rows)
    ex = None
    try: ex = AN.answer(kind, focus_q, None, dec, dom) or QA.answer(kind, focus_q, None, None)
    except Exception: pass
    out = {"answer": text, "df": None, "sql": ";\n".join(sqls), "sugg": [focus_q]}
    if ex and ex.get("answer"): out["answer"] += "\n\n**Needs attention:** " + ex["answer"]; out["df"] = ex.get("df"); out["extra"] = ex.get("extra")
    return out

def _entity_row(e):
    for t, (_, idc, cols, _m) in QA.TABLES[_kind()].items():
        if t == "agent_actions": continue
        try: df = Q(f"SELECT * FROM {t} WHERE {idc}=?", (e,))
        except Exception: continue
        if len(df): return t, df.iloc[0]
    return None, None

def compare(ids):
    cols, t0 = {}, None; sqls = []
    for e in ids[:3]:
        t, r = _entity_row(e)
        if r is None: return {"answer": f"I could not find {e} in the data.", "df": None, "sql": ""}
        if t0 and t != t0: return {"answer": f"{ids[0]} and {e} are different kinds of records ({t0} vs {t}), so I cannot compare them side by side.", "df": None, "sql": ""}
        t0 = t; cols[e] = r; sqls.append(f"SELECT * FROM {t} WHERE id='{e}'")
    df = pd.DataFrame({e: {k: QA._fmt(v) for k, v in r.items() if str(v) not in ("None", "nan")} for e, r in cols.items()}).reset_index().rename(columns={"index": "field"})
    return {"answer": f"Side-by-side: **{' vs '.join(ids[:3])}** ({t0}).", "df": df, "sql": "; ".join(sqls), "nochart": True}

def profile(kind, e):
    t, r = _entity_row(e)
    if r is None: return None
    base = QA.lookup(kind, e)
    extra, sqls = [], []
    def m(label, sql, p=(), d=1):
        v = _num(sql, p); sqls.append(sql)
        if v is not None and v == v: extra.append(f"- {label}: **{_f(v, d)}**")
    if kind == "Franchise" and e.startswith("OUT-"):
        m("Staff on record", "SELECT COUNT(*) FROM staff WHERE outlet_id=?", (e,), 0); m("Avg attrition risk", "SELECT AVG(predicted_attrition_prob) FROM staff WHERE outlet_id=?", (e,), 2)
        m("Items below reorder level", "SELECT COUNT(*) FROM inventory WHERE outlet_id=? AND current_stock<reorder_threshold", (e,), 0)
        m("Avg review rating", "SELECT AVG(rating) FROM feedback WHERE outlet_id=?", (e,), 2); m("Avg audit score", "SELECT AVG(score) FROM audits WHERE outlet_id=?", (e,), 1)
        m("Active campaigns", "SELECT COUNT(*) FROM marketing WHERE outlet_id=?", (e,), 0)
    if kind == "Freight" and e.startswith("SHP-"):
        m("Quotes on this shipment", "SELECT COUNT(*) FROM freight_quotes WHERE shipment_id=?", (e,), 0)
    if not base: return None
    out = dict(base); out["answer"] = base["answer"] + (("\n\n**Context**\n" + "\n".join(extra)) if extra else ""); out["sql"] = (base.get("sql") or "") + ("; " + "; ".join(sqls) if sqls else "")
    return out

FKEY = {"OUT": "outlet_id", "SHP": "shipment_id", "CUST": "customer_id", "STF": "staff_id", "QTE": "quote_id", "EMP": "staff_id"}
def scoped(kind, e, q):
    """'staff in OUT-010', 'its inventory', 'quotes for CUST-001': the rows of one table that belong to one entity."""
    col = FKEY.get(e.split("-")[0]); ql = q.lower()
    if not col: return None
    own = {"OUT": "outlets", "SHP": "shipments", "CUST": "customers", "STF": "staff", "QTE": "freight_quotes"}.get(e.split("-")[0])
    best = None
    for t, (syn, idc, show, met) in QA.TABLES[kind].items():
        if t == own or t == "agent_actions" and not re.search(r"\b(ticket|action|task|alert)", ql): continue
        if not any(QA._w(ql, x.strip()) for x in syn): continue
        try: cols = QA._cols(t)
        except Exception: continue
        if col not in cols: continue
        best = (t, show, met, cols); break
    if not best: return None
    t, show, met, cols = best; show = [c for c in show if c in cols] or cols[:8]
    n = _num(f"SELECT COUNT(*) FROM {t} WHERE {col}=?", (e,))
    order = f" ORDER BY {met} DESC" if met and met in cols else ""
    sql = f"SELECT {', '.join(show)} FROM {t} WHERE {col}='{e}'{order} LIMIT 15"
    df = Q(f"SELECT {', '.join(show)} FROM {t} WHERE {col}=?{order} LIMIT 15", (e,))
    label = t.replace("_", " ")
    return {"answer": f"**{e}** has **{_f(n, 0)}** {label} records" + (f" (showing the top 15 by {met.replace('_', ' ')})." if met and met in cols and (n or 0) > 15 else "."), "df": df, "sql": sql + f"; SELECT COUNT(*) FROM {t} WHERE {col}='{e}'", "sugg": [f"Tell me about {e}"]}

# ------------------------------------------------------------------ teach me: plain intents (pattern -> SQL). Add yours here.
# (regex on the lower-cased question, answer title, SQL with an optional {id} placeholder bound as a parameter, needs_id)
TICKETS = ("Open agent tickets, critical first.", "SELECT action_id, type, target, severity, status, detail FROM agent_actions WHERE status IN ('open','proposed') ORDER BY CASE severity WHEN 'Critical' THEN 0 WHEN 'Warning' THEN 1 ELSE 2 END, action_id DESC LIMIT 10")
UNSUPPORTED = {
 "Franchise": [(r"\b(expired|expiry|expiring|shelf[- ]?life|best before)\b", "The inventory data has no expiry dates, so I cannot answer that. I can show items at or below reorder level, or with less than 7 days of stock cover.")],
 "Freight": [],
}
INTENTS = {
 "Franchise": [
  (r"(which|what|top).*(outlets?|stores?|branch\w*).*(tickets?|issues?|alerts?|actions?)|(most|highest|largest|top).*(open )?(tickets?|issues?|alerts?)", "Outlets with the most open tickets.", "SELECT target AS outlet_id, COUNT(*) AS open_tickets, SUM(severity = 'Critical') AS critical FROM agent_actions WHERE status IN ('open', 'proposed') AND target LIKE 'OUT-%' GROUP BY target ORDER BY open_tickets DESC, critical DESC LIMIT 10", False),
  (r"(revenue|sales|csat|satisfaction|outlets?|performance).*\bby tier\b|\btier[- ]?wise\b|\bper tier\b|\beach tier\b", "Outlets by tier.", "SELECT tier, COUNT(*) AS outlets, ROUND(SUM(revenue), 0) AS revenue, ROUND(AVG(customer_satisfaction), 2) AS avg_csat, SUM(staff_headcount) AS staff FROM outlets GROUP BY tier ORDER BY revenue DESC", False),
  (r"(revenue|sales|csat|satisfaction).*\b(by|per|each) (city|location|town)\b|\bcity[- ]?wise\b", "Outlets by city.", "SELECT location AS city, COUNT(*) AS outlets, ROUND(SUM(revenue), 0) AS revenue, ROUND(AVG(customer_satisfaction), 2) AS avg_csat FROM outlets GROUP BY location ORDER BY revenue DESC LIMIT 12", False),
  (r"overtime.*(outlets?|stores?|branch\w*)|(outlets?|stores?|branch\w*).*overtime", "Overtime hours by outlet.", "SELECT outlet_id, ROUND(SUM(overtime_hrs), 0) AS overtime_hours, ROUND(AVG(overtime_hrs), 1) AS avg_per_staff, COUNT(*) AS staff FROM staff GROUP BY outlet_id ORDER BY overtime_hours DESC LIMIT 10", False),
  (r"(stock|inventory).*(value|worth|units|quantity|total)|total (stock|inventory)|stock by category", "Units in stock by category (the inventory table holds no prices, so a money value cannot be computed).", "SELECT category, COUNT(*) AS sku_records, SUM(current_stock) AS units_in_stock, SUM(CASE WHEN current_stock <= reorder_threshold THEN 1 ELSE 0 END) AS at_or_below_reorder FROM inventory GROUP BY category ORDER BY units_in_stock DESC", False),
  (r"\b(absent|absence|absentees?|on leave|leave|attendance|late arrivals?|punctuality)\b", "Absences and late arrivals by outlet (the data records Present, Late and Absent; there is no separate leave type).", "SELECT outlet_id, SUM(status = 'Absent') AS absent, SUM(status = 'Late') AS late, COUNT(*) AS records, ROUND(100.0 * SUM(status = 'Absent') / COUNT(*), 1) AS absent_pct FROM attendance GROUP BY outlet_id ORDER BY absent DESC LIMIT 10", False),
  (r"(sales|revenue|takings|turnover).*\btoday\b|\btoday'?s (sales|revenue|takings)", "Sales so far today (IST), by outlet.", "SELECT outlet_id, ROUND(SUM(amount), 0) AS sales_today, SUM(tx_count) AS transactions FROM sales WHERE substr(ts, 1, 10) = date('now', 'localtime') GROUP BY outlet_id ORDER BY sales_today DESC LIMIT 10", False),
  (r"(sales|revenue|takings|turnover).*\byesterday\b|\byesterday'?s (sales|revenue|takings)", "Sales yesterday (IST), by outlet.", "SELECT outlet_id, ROUND(SUM(amount), 0) AS sales_yesterday, SUM(tx_count) AS transactions FROM sales WHERE substr(ts, 1, 10) = date('now', 'localtime', '-1 day') GROUP BY outlet_id ORDER BY sales_yesterday DESC LIMIT 10", False),
  (r"(sales|revenue|takings|turnover).*(this week|past week|last week|last 7 days|past 7 days)", "Sales in the last 7 days (IST), by outlet.", "SELECT outlet_id, ROUND(SUM(amount), 0) AS sales_7d, SUM(tx_count) AS transactions FROM sales WHERE substr(ts, 1, 10) >= date('now', 'localtime', '-6 day') GROUP BY outlet_id ORDER BY sales_7d DESC LIMIT 10", False),
  (r"(likely|expected|predicted|going|about) to (leave|quit|resign)|attrition|churn|resign", "Staff most likely to leave (highest predicted attrition risk).", "SELECT staff_id, name, role, outlet_id, predicted_attrition_prob, overtime_hrs, salary FROM staff ORDER BY predicted_attrition_prob DESC LIMIT 10", False),
  (r"(negative|bad|poor|worst|unhappy|angry|low).*(review|feedback|comment|complaint)", "The most negative customer feedback.", "SELECT feedback_id, outlet_id, rating, sentiment_score, date, comment FROM feedback ORDER BY sentiment_score ASC, rating ASC LIMIT 10", False),
  (r"(positive|best|good|happy|great).*(review|feedback|comment)", "The most positive customer feedback.", "SELECT feedback_id, outlet_id, rating, sentiment_score, date, comment FROM feedback ORDER BY sentiment_score DESC, rating DESC LIMIT 10", False),
  (r"(average|avg|mean) (review |customer )?rating.*", "Average review rating for {id}.", "SELECT ROUND(AVG(rating), 2) FROM feedback WHERE outlet_id=?", True),
  (r"overtime.*(most|highest|top|worst)|(most|highest|top|worst).*overtime", "Staff with the most overtime hours.", "SELECT staff_id, name, role, outlet_id, overtime_hrs, salary FROM staff ORDER BY overtime_hrs DESC LIMIT 10", False),
  (r"(losing money|negative roi|worst campaign|lowest roi|poor(ly)? performing campaign)", "Campaigns with the lowest return on investment.", "SELECT campaign_id, campaign_name, outlet_id, channel, budget, actual_roi, conversions FROM marketing ORDER BY actual_roi ASC LIMIT 10", False),
  (r"^(show |list |what are |which are )?(the )?(open |pending |critical |latest )+(tickets?|actions?|alerts?)\W*$", *TICKETS, False),
 ],
 "Freight": [
  (r"(quotes?|pricing).*(need|needs|needing|awaiting|pending|waiting|require|requiring).*(approval|review|sign[- ]?off|attention)|(approval|review).*quotes?|quotes? (to|for) (approve|review)", "Quotes that need a decision: drafts, submitted quotes and quotes with an open anomaly, hold or approval ticket.", "SELECT q.quote_id, q.shipment_id, q.customer_id, q.carrier, q.final_price, q.margin_pct, q.status FROM freight_quotes q WHERE q.status IN ('Draft', 'Submitted', 'On Hold') OR q.quote_id IN (SELECT target FROM agent_actions WHERE status IN ('open', 'proposed') AND type IN ('quote_approval', 'quote_anomaly', 'quote_hold')) ORDER BY q.margin_pct LIMIT 15", False),
  (r"(arriv|eta|due|deliver|reach|land).*\btoday\b", "Shipments due today (IST).", "SELECT shipment_id, origin_port, dest_port, carrier, status, eta, predicted_delay_risk FROM shipments WHERE substr(eta, 1, 10) = date('now', 'localtime') ORDER BY predicted_delay_risk DESC LIMIT 15", False),
  (r"(arriv|eta|due|deliver|reach|land).*\btomorrow\b", "Shipments due tomorrow (IST).", "SELECT shipment_id, origin_port, dest_port, carrier, status, eta, predicted_delay_risk FROM shipments WHERE substr(eta, 1, 10) = date('now', 'localtime', '+1 day') ORDER BY predicted_delay_risk DESC LIMIT 15", False),
  (r"(arriv|eta|due|deliver|reach|land).*(this week|next 7 days|coming week|next week)", "Shipments due in the next 7 days (IST).", "SELECT shipment_id, origin_port, dest_port, carrier, status, eta, predicted_delay_risk FROM shipments WHERE substr(eta, 1, 10) BETWEEN date('now', 'localtime') AND date('now', 'localtime', '+6 day') ORDER BY eta, predicted_delay_risk DESC LIMIT 15", False),
  (r"^(show |list |what are |give me )?(the |all )?customs (rules|duties|duty|tariffs?)\W*$", "Customs rules, highest duty first.", "SELECT chapter, goods, duty_pct, docs, restricted FROM customs_rules ORDER BY duty_pct DESC LIMIT 10", False),
  (r"^(which|list|show|what).*(delayed|late|behind schedule)", "Shipments with the highest delay risk.", "SELECT shipment_id, origin_port, dest_port, carrier, status, eta, predicted_delay_risk FROM shipments WHERE status LIKE '%elay%' OR predicted_delay_risk>=0.5 ORDER BY predicted_delay_risk DESC LIMIT 10", False),
  (r"(unreliable|least reliable|worst carrier|late carrier|poor carrier)", "Carriers with the lowest on-time performance.", "SELECT name, rating, on_time_pct, avg_cost_index, risk_level FROM carriers ORDER BY on_time_pct ASC LIMIT 10", False),
  (r"(risky|risk|bad credit|poor credit).*(customer|client)|(customer|client).*(risk|credit)", "Customers with the highest credit risk.", "SELECT customer_id, name, industry, priority_tier, credit_risk FROM customers ORDER BY credit_risk DESC LIMIT 10", False),
  (r"(storm|rough|dangerous|bad weather|severe)", "Ports with the roughest conditions.", "SELECT port_name, current_severity, forecast, wind_speed, wave_height FROM weather_risks ORDER BY wave_height DESC LIMIT 10", False),
  (r"^(show |list |what are |which are )?(the )?(open |pending |critical |latest )+(tickets?|actions?|alerts?)\W*$", *TICKETS, False),
 ]}
def intent(kind, q, ids, scope=None):
    ql = q.lower().strip()
    for pat, msg in UNSUPPORTED.get(kind, []):
        if re.search(pat, ql): return {"answer": msg, "df": None, "sql": "", "complete": True}
    for pat, title, sql, needs_id in INTENTS.get(kind, []):
        if not re.search(pat, ql): continue
        if needs_id and not ids: continue
        params = (ids[0],) if needs_id else ()
        if scope:                                   # a scoped user (one outlet) only sees their own rows
            if needs_id:
                if ids[0] != scope: continue
            elif "outlet_id" in sql and " WHERE " not in sql and " ORDER BY" in sql: sql = sql.replace(" ORDER BY", " WHERE outlet_id=? ORDER BY", 1); params = (scope,)
            else: continue
        try: df = Q(sql, params)
        except Exception: continue
        if df is None or not len(df):
            if "(IST)" in title: return {"answer": "No records: " + title.rstrip(".").replace(" (IST)", "").lower() + ": none found for today's IST date.", "df": None, "sql": sql, "complete": True}
            continue
        if needs_id: return {"answer": title.format(id=ids[0]) + f" **{df.iloc[0, 0]}**", "df": None, "sql": sql.replace("?", f"'{ids[0]}'")}
        return {"answer": title, "df": df, "sql": sql.replace("?", f"'{params[0]}'") if params else sql}
    return None

def goods_duty(kind, q):
    """Freight: 'customs duty on pharmaceuticals' -> the matching customs rule rows."""
    if kind != "Freight": return None
    m = re.search(r"\b(?:duty|duties|tariff|customs|restricted|documents?|docs)\b.*?\b(?:on|for|of|about)\s+([a-z][a-z ]{3,40})", q.lower())
    if not m: return None
    term = re.sub(r"\b(the|a|an|my|our|goods|cargo|shipments?|items?)\b", "", m.group(1)).strip(" ?.!")
    if len(term) < 4: return None
    like = "%" + term[:7] + "%"
    try: df = Q("SELECT chapter, goods, duty_pct, docs, restricted FROM customs_rules WHERE LOWER(goods) LIKE ? LIMIT 10", (like,))
    except Exception: return None
    if df is None or not len(df): return None
    return {"answer": f"Customs rules matching **{term}**: {len(df)} found.", "df": df, "sql": f"SELECT chapter, goods, duty_pct, docs, restricted FROM customs_rules WHERE LOWER(goods) LIKE '{like}'"}

SMALL = {
 "greet": "Hello! I'm your data copilot. I answer from live database queries, never from guesses. Ask a question, or say **briefing** for the key numbers.",
 "thanks": "You're welcome. Ask me anything else about your data.",
 "bye": "Goodbye! Come back any time.",
 "how": "I'm running well and ready for questions. What would you like to know about your data?",
 "who": "I'm the data copilot of this platform. I turn your question into a read-only SQL query on the live tables and show you the exact rows and the query. I do not use a language model, so I never invent numbers.",
}
def samples(kind):
    try:
        if kind == "Franchise": o = Q("SELECT outlet_id v FROM outlets ORDER BY outlet_id LIMIT 3").v.tolist(); return {"a": o[0], "b": o[1], "c": o[2]}
        sh = Q("SELECT shipment_id v FROM shipments ORDER BY shipment_id LIMIT 1").v.tolist(); q = Q("SELECT quote_id v FROM freight_quotes ORDER BY quote_id LIMIT 2").v.tolist()
        return {"a": sh[0], "b": q[0], "c": q[1]}
    except Exception: return {"a": "OUT-007", "b": "OUT-010", "c": "OUT-020"}
def help_text(kind):
    sm = samples(kind)
    if kind == "Franchise":
        g = {"Rank": ["Top 5 outlets by revenue", "Which stores have the lowest customer satisfaction?", "Worst audit scores"], "Count and average": ["How many staff work in Hyderabad?", "Average salary by role", "Total budget of social media campaigns"],
             "Explain": [f"Why is {sm['a']} flagged?", f"Tell me about {sm['b']}", f"Compare {sm['a']} and {sm['b']}"], "Operations": ["Which items are below reorder level?", "Which staff are most likely to leave?", "Open tickets by severity"], "Overview": ["Briefing", "How is inventory holding up?"]}
    else:
        g = {"Rank": ["Top 5 carriers by on-time", "Which ports are most congested?", "Cheapest carriers"], "Count and average": ["How many shipments are delayed?", "Average margin by carrier", "Total quote value"],
             "Explain": [f"Tell me about {sm['a']}", f"Compare {sm['b']} and {sm['c']}", "Mumbai to Singapore 50 t electronics: days, cost and best route"], "Operations": ["Quotes with margin below 10%", "Where is the weather worst?", "Customs duty for electronics"], "Overview": ["Briefing", "Which shipments are at highest delay risk?"]}
    return "**What I can do**\n\n" + "\n".join(f"- **{k}:** " + " · ".join(f"*{x}*" for x in v) for k, v in g.items()) + "\n\nI understand typos, follow-ups (*and OUT-010?*, *top 10 instead*, *what about Mumbai*), and I can show the SQL behind any answer."

# ------------------------------------------------------------------ presentation
def chart_block(df):
    if df is None or len(df) < 2 or len(df) > 40: return None
    lab = next((c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])), None)
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not re.search(r"(^id$|_id$|lat|lon|^rank$)", c)]
    if not lab or not num: return None
    c = num[0]; d = df[[lab, c]].dropna().head(15)
    if len(d) < 2: return None
    d = d.iloc[::-1]
    opt = B.bar(d[lab].astype(str).tolist(), {c.replace("_", " "): d[c].astype(float).round(3).tolist()}, horizontal=True)
    return B.chart(opt, title=c.replace("_", " ").title() + " by " + lab.replace("_", " "), h=max(180, 34 * len(d) + 60), open={"bar": True} if "id" in lab else None, key="cp_" + c)

def suggestions(kind, q, res, ids):
    df = res.get("df"); out = list(res.get("sugg") or [])
    first = None
    if df is not None and len(df):
        fcol = None
        for c in df.columns:
            if re.search(r"(^|_)id$", c) and str(df[c].iloc[0]).upper().startswith(("OUT-", "SHP-", "QTE-", "CAR-", "PORT-", "CUST-")): first = str(df[c].iloc[0]); fcol = c; break
        if first and kind == "Franchise" and first.startswith("OUT-"): out += [f"Why is {first} flagged?", f"Tell me about {first}"]
        elif first: out += [f"Tell me about {first}"]
        if len(df) >= 2 and first and len(df) > 1:
            second = str(df[fcol].iloc[1]); out.append(f"Compare {first} and {second}")
        if not TOPN.search(q) and len(df) >= 5: out.append("Top 10 instead")
    elif ids and kind == "Franchise" and ids[0].startswith("OUT-"): out += [f"Why is {ids[0]} flagged?", f"Which items are below reorder level in {ids[0]}?"]
    if not out: out = ["Briefing"]
    seen, r = set(), []
    for x in out:
        if x not in seen and x.lower() != q.lower(): seen.add(x); r.append(x)
    return r[:4]

# ------------------------------------------------------------------ logging / feedback
def _db():
    c = sqlite3.connect(DB_PATH, timeout=30); c.execute("PRAGMA journal_mode=WAL;")
    c.execute("CREATE TABLE IF NOT EXISTS copilot_unanswered(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, q TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS copilot_feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, q TEXT, helpful INT)")
    c.execute("CREATE TABLE IF NOT EXISTS copilot_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, q TEXT, route TEXT, ms INT)"); return c
def _log_unanswered(q):
    try:
        with _db() as c: c.execute("INSERT INTO copilot_unanswered(ts,q) VALUES(datetime('now'),?)", (q[:300],))
    except Exception: pass
def log_turn(q, route, ms=0):
    """Every question is logged with the route that answered it: chat, exact (SQL), agents+llm, unanswered. Feeds the Copilot insights page."""
    try:
        with _db() as c: c.execute("INSERT INTO copilot_log(ts,q,route,ms) VALUES(?,?,?,?)", (datetime.datetime.now().isoformat(timespec="seconds"), (q or "")[:300], route, int(ms)))
    except Exception: pass
def insights():
    with _db() as c:
        one = lambda sql: (c.execute(sql).fetchone() or [0])[0] or 0
        out = {"total": one("SELECT COUNT(*) FROM copilot_log"), "avg_ms": one("SELECT AVG(ms) FROM copilot_log WHERE route='exact'"), "up": one("SELECT COUNT(*) FROM copilot_feedback WHERE helpful=1"), "down": one("SELECT COUNT(*) FROM copilot_feedback WHERE helpful=0")}
        out["routes"] = c.execute("SELECT route, COUNT(*) n FROM copilot_log GROUP BY route ORDER BY n DESC").fetchall()
        out["unanswered"] = c.execute("SELECT q, COUNT(*) n, MAX(ts) last FROM copilot_log WHERE route='unanswered' GROUP BY q ORDER BY n DESC, last DESC LIMIT 25").fetchall()
        out["recent"] = c.execute("SELECT ts, q, route, ms FROM copilot_log ORDER BY id DESC LIMIT 40").fetchall()
        out["down_q"] = c.execute("SELECT ts, q FROM copilot_feedback WHERE helpful=0 ORDER BY id DESC LIMIT 20").fetchall()
    return out
def feedback(q, helpful):
    with _db() as c: c.execute("INSERT INTO copilot_feedback(ts,q,helpful) VALUES(datetime('now'),?,?)", (q[:300], 1 if helpful else 0))
def unanswered(n=50):
    with _db() as c: return [{"ts": a, "q": b, "times": k} for a, b, k in c.execute("SELECT max(ts), q, COUNT(*) FROM copilot_unanswered GROUP BY q ORDER BY COUNT(*) DESC, max(ts) DESC LIMIT ?", (n,))]

def suggest(prefix, examples, n=7):
    p = prefix.strip().lower()
    if len(p) < 2: return []
    V = _vocab(); kind = _kind(); pool = list(examples)
    for t, (syn, idc, cols, met) in QA.TABLES[kind].items():
        if t == "agent_actions": continue
        nm = syn[0]; pool += [f"How many {nm}s are there?", f"Top 10 {nm}s"]
        if met: pool += [f"Which {nm} has the highest {met.replace('_', ' ')}?", f"Which {nm} has the lowest {met.replace('_', ' ')}?", f"Average {met.replace('_', ' ')}"]
    pool += ["Briefing", "What can you do?", f"Compare {samples(kind)['b' if kind != 'Franchise' else 'a']} and {samples(kind)['c' if kind != 'Franchise' else 'b']}"]
    words = p.split(); sc = []
    for x in pool:
        xl = x.lower(); s = (3 if xl.startswith(p) else 0) + sum(1 for w in words if w in xl)
        if s >= max(1, len(words) - 1) and (p in xl or s == len(words)): sc.append((-s, len(x), x))
    r = [x for _, _, x in sorted(set(sc))][:n]
    if len(words) == 1 and len(p) >= 3:
        for v in V["corpus"]:
            if v.lower().startswith(p) and len(r) < n: r.append("Tell me about " + v)
    return r

# ------------------------------------------------------------------ main entry (used by the full app)
SENS = ("salary", "age")
def _mask(df, mask):
    if df is None or not mask: return df
    drop = [c for c in df.columns if c in ("salary", "age")] + (["name"] if "staff_id" in df.columns else [])
    return df.drop(columns=drop, errors="ignore")
def prepare(kind, raw, sid, dom, dec_fn, examples, scope=None, mask=False):
    """Everything that happens BEFORE the heavy pipeline.
    Returns (direct, q2, res, notes, ids): direct = an instant reply (small talk, help, show-SQL) or None;
    q2 = the question after spelling repair and follow-up resolution; res = an exact SQL answer from a smart intent or None."""
    s = session(sid or "default"); raw = (raw or "").strip()[:800]
    def D(text, **k): return {"text": text, "sql": k.pop("sql", ""), **k}
    if not raw: return D("Type a question about your data, or say **briefing**.", sugg=["Briefing", "What can you do?"]), raw, None, [], []
    if GREET.match(raw): return D(SMALL["greet"], sugg=["Briefing", "What can you do?"] + examples[:1]), raw, None, [], []
    if BYE.match(raw): return D(SMALL["bye"]), raw, None, [], []
    if THANKS.match(raw): return D(SMALL["thanks"], sugg=["Briefing"]), raw, None, [], []
    if HOWARE.search(raw) and len(raw.split()) < 7: return D(SMALL["how"], sugg=["Briefing"]), raw, None, [], []
    if WHO.search(raw): return D(SMALL["who"], sugg=["What can you do?", "Briefing"]), raw, None, [], []
    if TIME.search(raw) and len(raw.split()) < 8:
        n = datetime.datetime.now(); return D(f"It is **{n:%A, %d %B %Y}**, **{n:%I:%M %p} IST** (India Standard Time).", sugg=["Briefing"]), raw, None, [], []
    if HELP.match(raw): return D(help_text(kind), sugg=["Briefing"] + examples[:2]), raw, None, [], []
    if SHOWSQL.search(raw) and s["sql"]: return D("This is the exact query behind my last answer:\n\n```sql\n" + s["sql"] + "\n```", sql=s["sql"]), raw, None, [], []
    try: _t = taught_match(raw)
    except Exception: _t = None
    if _t: return D(_t["answer"] + "\n\n**Source:** taught answer, added by " + str(_t["by"]) + " on " + str(_t["when"])[:10], sugg=["Briefing"] + examples[:1], route="taught"), raw, None, [], []
    fixed, changes = correct(raw); q2, fnote = contextualize(fixed, s); notes = []
    if changes: notes.append("Spelling: " + ", ".join(f"{a} -> {b}" for a, b in changes))
    if fnote and fnote != fixed: notes.append("Follow-up understood as: " + fnote)
    ids = [i.upper() for i in ID_RE.findall(q2)]; res = None
    if mask and kind == "Franchise" and re.search(r"\b(salary|salaries|wage|wages|payroll|pay|age)\b", q2, re.I) and re.search(r"\b(staff|employees?|workers?|people|team|role)\b", q2, re.I):
        return D("Salary and personal details are visible to the Admin, Franchise Owner and Operations roles only.", sugg=["Briefing"]), raw, None, notes, ids
    if scope:                                              # a scoped user (one outlet): only simple intents, filtered to their outlet; everything else uses the scope-aware engine
        try: r0 = intent(kind, q2, ids, scope)
        except Exception: r0 = None
        if r0 is not None: r0["df"] = _mask(r0.get("df"), mask); r0["complete"] = True
        return None, q2, r0, notes, ids
    if mask and any(i.startswith(("STF", "EMP")) for i in ids): return None, q2, None, notes, ids
    try:
        if ids: res = intent(kind, q2, ids)
        if res is not None: pass
        elif BRIEF.search(q2) and not ids and len(q2.split()) < 9: res = briefing(kind, dec_fn(), dom)
        elif len(ids) >= 2 and COMPARE.search(q2): res = compare(ids)
        elif len(ids) == 1 and scoped(kind, ids[0], q2) is not None and not re.search(r"\b(why|flag|risk|reason|explain)\b", q2, re.I): res = scoped(kind, ids[0], q2)
        elif len(ids) == 1 and len(q2.split()) <= 6 and not re.search(r"\b(why|flag|risk|reason|explain)\b", q2, re.I): res = profile(kind, ids[0])
        if res is None and not ids: res = intent(kind, q2, ids) or goods_duty(kind, q2)
    except Exception as e:
        import sys; print("copilot_pro failed:", repr(e), file=sys.stderr); res = None
    if res is not None:
        res["df"] = _mask(res.get("df"), mask); res["complete"] = True
        if mask and res.get("answer") and "salary=" in res["answer"]: res["answer"] = re.sub(r"salary=[^;\n]*;?\s*", "", res["answer"])
    return None, q2, res, notes, ids

def decorate(kind, sid, q2, res, ids):
    """After an exact answer exists: remember it (for follow-ups, CSV and show-SQL) and build the chart and the suggestion chips."""
    s = session(sid or "default"); df = res.get("df")
    s["q"] = q2; s["ids"] = ids or s["ids"]; s["df"] = df; s["sql"] = res.get("sql", ""); s["turns"] += 1
    cb = None if res.get("nochart") else chart_block(df)
    return (B.clean(cb) if cb else None), suggestions(kind, q2, res, ids), bool(df is not None and len(df))

_KQ = re.compile(r"\b(what is|what are|what's|how do|how to|how should|how can|policy|procedure|rules?|explain|define|meaning|difference|steps|guidelines?|requirements?|process|checklist|standards?|why do|who is responsible)\b", re.I)
_SW = set("what is are the a an of to in on for and or how do does should can i we you my our your with about this that these those why who when which be it its into per".split())
def _sentences(text):
    t = re.sub(r"\s+", " ", text or "").strip()
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", t) if len(x.strip()) > 25]
def _short(x, n=28):
    w = x.split(); return x if len(w) <= n else " ".join(w[:n]).rstrip(",;:") + "..."
def src_label(h):
    s = str(h.get("source") or "").replace("\\", "/"); s = s.rsplit("/", 1)[-1] if "/" in s and not s.startswith("http") else s
    return f"{h.get('title', 'Document')}" + (f" · {s[:60]}" if s and s != h.get("title") else "")
def sources_block(hits, cited=None):
    """Numbered source list that matches the [n] markers in the answer."""
    ids = sorted(cited) if cited else list(range(1, min(len(hits), 3) + 1))
    rows = [f"[{n}] {src_label(hits[n - 1])}" + (f" (match {hits[n - 1]['score']:.2f})" if isinstance(hits[n - 1].get("score"), (int, float)) else "") for n in ids if 1 <= n <= len(hits)]
    return ("**Sources**\n" + "\n".join(rows)) if rows else ""
def finish(ans, hits, max_points=3):
    """Tidy an LLM answer: Answer line, up to 3 numbered points, optional Next step; every cited [n] is listed in a Sources block."""
    ans = (ans or "").strip()
    if not ans: return ans
    lines = [l.rstrip() for l in ans.split("\n") if l.strip()]
    head = [l for l in lines if not re.match(r"\s*(\d{1,2}[.)]|[-*•])\s", l) and not l.lower().lstrip("* ").startswith("next step")][:2]
    pts = [l for l in lines if re.match(r"\s*(\d{1,2}[.)]|[-*•])\s", l)][:max_points]
    nxt = [l for l in lines if l.lower().lstrip("* ").startswith("next step")][:1]
    pts = [re.sub(r"^\s*(\d{1,2}[.)]|[-*•])\s*", f"{i}. ", l) for i, l in enumerate(pts, 1)]
    body = "\n".join(head + pts + nxt)
    cited = {int(x) for x in re.findall(r"\[(\d{1,2})\]", body) if 1 <= int(x) <= len(hits or [])}
    sb = sources_block(hits, cited) if hits and cited else ""
    return body + (("\n\n" + sb) if sb else "")

def kb_answer(q, hits, max_points=3):
    """No GPU model needed: a short, ordered answer built from the best sentences of the best passages, every line cited, then the Sources block. None when the passages do not match."""
    if not hits or not (_KQ.search(q) or is_term_q(q)): return None
    terms = {w for w in re.findall(r"[a-z]{3,}", q.lower()) if w not in _SW and w not in _S3}
    if not terms: return None
    key0 = {w for w in terms if w not in _GEN and w.rstrip("s") not in _GEN}
    _gen = {"policy", "policies", "customer", "customers", "rule", "rules", "process", "standard", "guide", "tell", "about", "explain", "describe", "limit", "limits"}
    key = {w.rstrip("s") for w in terms - _gen} or terms
    _how = bool(re.match(r"\s*(how|what (should|do|to)|steps)", q.lower()))
    cand = []
    for n, h in enumerate(hits[:3], 1):
        body = (h.get("title", "") + " " + h.get("text", "")).lower()
        if sum(1 for w in (key0 or terms) if w in body) < min(2, len(key0 or terms)): continue
        for k, sen in enumerate(_sentences(h.get("text", ""))):
            sc = sum(2 for w in key if w in sen.lower()) + sum(0.5 for w in terms - set(key) if w in sen.lower()) + (0.4 if re.search(r"\d", sen) else 0) + (1.5 if _how and re.search(r"\b(must|should|escalat|recover|call-?back|review|within|trigger|approv|follow)", sen.lower()) else 0) - k * 0.15 - (n - 1) * 0.4
            if sc > 0: cand.append((sc, n, k, sen))
    if not cand: return None
    cand.sort(key=lambda x: -x[0]); picked = sorted(cand[: max_points + 1], key=lambda x: (x[1], x[2]))
    lead = cand[0]; rest = [c for c in picked if c is not lead and c[0] >= 2][:max_points]
    out = [f"**Answer:** {_short(lead[3], 34)} [{lead[1]}]"] + [f"{i}. {_short(c[3], 26)} [{c[1]}]" for i, c in enumerate(rest, 1)]
    cited = {lead[1]} | {c[1] for c in rest}
    return "\n".join(out) + "\n\n" + sources_block(hits, cited)

def relevant(q, hits, need=2):
    """Keep only retrieved passages that really share content words with the question (so a plain SQL question does not show unrelated sources)."""
    terms = {w for w in re.findall(r"[a-z]{3,}", q.lower()) if w not in _SW and w not in _S3}
    if not terms: return []
    key = {w for w in terms if w not in _GEN and w.rstrip("s") not in _GEN}
    if _KQ.search(q) and key: terms, need = key, min(2, len(key))      # generic words (policy, process, outlet...) do not count as evidence
    else: need = 2 if _KQ.search(q) else 3
    out = []
    for h in hits:
        txt = (h.get("title", "") + " " + h.get("text", "")).lower()
        if sum(1 for w in terms if w in txt) >= min(need, len(terms)): out.append(h)
    return out

# ------------------------------------------------------------------ teaching: answers added by the admin / interns for questions the Copilot could not answer
def _tdb():
    c = _db(); c.execute("CREATE TABLE IF NOT EXISTS copilot_taught(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, q TEXT, answer TEXT, keywords TEXT, by TEXT)"); return c
def _tk(x):
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]{3,}", (x or "").lower()) if w not in _SW and w not in {"the", "and", "for", "are", "you", "can", "how", "what", "who", "why", "this", "that", "with", "does", "from", "our", "any"}}
_S3 = {"the", "for", "and", "are", "you", "can", "its", "get", "any", "has", "was", "not", "our", "all", "out", "off", "use", "new", "low", "high", "per", "why", "who", "how"}
_GEN = set("outlet outlets franchise franchises staff store stores employee employees shipment shipments freight carrier carriers port ports quote quotes customs route routes company new need needed policy policies process procedure rules steps guidelines guideline requirements requirement checklist standard standards explain define meaning difference tell about give show list which have there their each every between using used make made take work works working please currently current right data highest lowest best worst most least average total count many much more less than want know like also only just over under after before".split())
def weak_match(q, res):
    """True when none of the question's key words appear anywhere in the answer, the SQL or the table headings: a confident but unrelated answer."""
    kt = [w for w in re.findall(r"[a-z]{3,}", (q or "").lower()) if w not in _SW and w not in _GEN and w not in {"the", "for", "and", "are", "you", "can", "its", "get", "any", "has", "was", "not", "our", "all", "out", "off", "use"}]
    if not kt: return False
    df = res.get("df"); hay = str(res.get("answer", "")) + " " + str(res.get("sql", ""))
    try: hay += " " + " ".join(map(str, df.columns)) + " " + df.head(5).to_string()
    except Exception: pass
    toks = set(re.findall(r"[a-z]+", hay.lower()))
    def seen(w): return w in toks or w.rstrip("s") in toks or (w == "csat" and "satisfaction" in toks) or (len(w) >= 6 and any(t.startswith(w[:5]) for t in toks))
    return not any(seen(w) for w in kt)

def teach(q, answer, keywords="", by="admin"):
    """Save a question + the answer you want. It is matched (also for rephrased versions) before the other layers, and indexed into the knowledge base."""
    q = (q or "").strip()[:300]; answer = (answer or "").strip()[:3000]
    if len(q) < 4 or len(answer) < 10: return None
    with _tdb() as c:
        old = c.execute("SELECT id FROM copilot_taught WHERE lower(q)=lower(?)", (q,)).fetchone()
        if old: c.execute("UPDATE copilot_taught SET answer=?, keywords=?, by=?, ts=? WHERE id=?", (answer, (keywords or "")[:300], by, datetime.datetime.now().isoformat(timespec="seconds"), old[0])); tid = old[0]
        else: tid = c.execute("INSERT INTO copilot_taught(ts,q,answer,keywords,by) VALUES(?,?,?,?,?)", (datetime.datetime.now().isoformat(timespec="seconds"), q, answer, (keywords or "")[:300], by)).lastrowid
    try:
        import rag as _rg; _rg.delete_doc("Taught: " + q[:80], None); _rg.add("Taught: " + q[:80], "Taught answer (added by " + by + ")", q + "\n" + answer + ("\nKeywords: " + keywords if keywords else ""), None)
    except Exception: pass
    return tid
def taught_rows():
    with _tdb() as c: return [{"id": a, "when": b, "question": q, "answer": an, "keywords": k, "by": by} for a, b, q, an, k, by in c.execute("SELECT id, ts, q, answer, keywords, by FROM copilot_taught ORDER BY id DESC")]
def taught_del(i):
    with _tdb() as c:
        r = c.execute("SELECT q FROM copilot_taught WHERE id=?", (i,)).fetchone(); c.execute("DELETE FROM copilot_taught WHERE id=?", (i,))
    if r:
        try: import rag as _rg; _rg.delete_doc("Taught: " + r[0][:80], None)
        except Exception: pass
    return bool(r)
def taught_match(q):
    qt = _tk(q)
    if not qt: return None
    best, bs = None, 0.0
    try: rows = taught_rows()
    except Exception: return None
    for r in rows:
        if r["question"].strip().lower() == (q or "").strip().lower(): return r
        tt = _tk(r["question"]) | _tk(r["keywords"]); inter = len(qt & tt)
        if inter < min(2, len(qt)): continue
        sc = inter / len(qt | _tk(r["question"]))
        if sc > bs: best, bs = r, sc
    return best if best and bs >= 0.6 else None
def backlog(n=300):
    """Distinct questions that went unanswered (not yet taught), most asked first."""
    with _db() as c: rows = c.execute("SELECT q, COUNT(*) n, MAX(ts) last FROM (SELECT q, ts FROM copilot_log WHERE route IN ('unanswered','weak') UNION ALL SELECT q, ts FROM copilot_feedback WHERE helpful=0) GROUP BY lower(q) ORDER BY n DESC, last DESC LIMIT ?", (n,)).fetchall()
    return [{"question": q, "times": k, "last_asked": str(l).replace("T", " ")} for q, k, l in rows if not taught_match(q)]
def teach_stats():
    with _db() as c:
        tot = c.execute("SELECT COUNT(DISTINCT lower(q)) FROM (SELECT q FROM copilot_log WHERE route IN ('unanswered','weak') UNION ALL SELECT q FROM copilot_feedback WHERE helpful=0)").fetchone()[0]
    return {"found": tot, "open": len(backlog(500)), "taught": len(taught_rows())}

def sane(t):
    """False for degenerate model output (only quotes/newlines, repeated tokens, foreign-script noise)."""
    t = (t or "").strip()
    if len(t) < 8: return False
    core = re.sub(r"\s", "", t)
    if sum(c.isascii() and c.isalnum() for c in core) < 0.55 * len(core): return False
    ws = re.findall(r"[A-Za-z]{2,}", t)
    if len(ws) < 3 or len(set(w.lower() for w in ws)) < 3: return False
    if re.search(r"(.{1,6})\1{5,}", t): return False
    return True
_DATA_WORDS = re.compile(r"\b(outlets?|stores?|sales|revenue|stock|inventory|staff|attrition|shipments?|ports?|vessels?|quotes?|carriers?|customers?|campaigns?|audits?|tickets?|approvals?|agents?|risk|health|top|bottom|how many|count|average|total|list|show)\b", re.I)
def is_term_q(q):
    """A bare term or very short phrase with no data words (FSSAI, HACCP, demurrage): look it up in the documents, skip the agents."""
    w = re.findall(r"[A-Za-z][A-Za-z0-9\-]*", q or "")
    return 1 <= len(w) <= 4 and not re.search(r"\d", q or "") and not _DATA_WORDS.search(q or "")
def is_knowledge_q(q): return bool(_KQ.search(q))

def unanswered_note(raw): _log_unanswered(raw)

def respond(kind, q, sid, dom, dec_fn, examples):
    """Standalone version (used by the lite app): prepare, then the exact engine only."""
    t0 = time.time(); ms = lambda: round((time.time() - t0) * 1000)
    direct, q2, res, notes, ids = prepare(kind, q, sid, dom, dec_fn, examples)
    if direct: log_turn(q, "chat", ms()); yield {"ev": "final", "ms": ms(), **direct}; return
    if notes: yield {"ev": "note", "text": " · ".join(notes)}
    try:
        if res is None: res = goods_duty(kind, q2) or AN.answer(kind, q2, None, dec_fn(), dom) or QA.answer(kind, q2, None, None)
    except Exception as e:
        import sys; print("copilot_pro failed:", repr(e), file=sys.stderr); res = None
    if not res or not res.get("answer"):
        _log_unanswered(q); log_turn(q, "unanswered", ms())
        yield {"ev": "final", "text": "I could not compute an exact answer to that from the tables. I would rather say so than guess.\n\nYou could try:\n" + "\n".join("- " + e for e in examples[:4]) + "\n\nOr say **what can you do**.", "sql": "", "ms": ms(), "sugg": ["What can you do?", "Briefing"]}; return
    cb, sg, has = decorate(kind, sid, q2, res, ids); df = res.get("df"); log_turn(q, "exact", ms())
    yield {"ev": "exact", "sql": res.get("sql", ""), "rows": 0 if df is None else len(df)}
    if cb: yield {"ev": "chart", "block": cb}
    tbl = (QA.md(df) if df is not None else "") + (("\n\n" + res["extra"]) if res.get("extra") else "")
    yield {"ev": "final", "text": res["answer"] + (("\n\n" + tbl) if tbl else ""), "sql": res.get("sql", ""), "ms": ms(), "rows": 0 if df is None else len(df), "csv": has, "sugg": sg}
