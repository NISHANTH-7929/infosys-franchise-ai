"""Shared page builders: helpers, Command Center (tickets, agents, anomalies), Knowledge Graph."""
import json, datetime
import numpy as np, pandas as pd
import live_engine as LE, entities as EN
import rbac
import blocks as B
from blocks import Q, clean, L, TEAL, BLUE, AMBER, RED, VIOLET, TONE

def can(c, cap): return cap in rbac.caps_of(c["role"])      # same table as need(): a button or form is only drawn for a role that may use it
def latest(agent):
    r = LE.conn().execute("SELECT ts,score,risk,latency_ms,summary,output,cycle_id FROM agent_runs WHERE agent=? ORDER BY run_id DESC LIMIT 1", (agent,)).fetchone()
    if not r: return None
    try: out = json.loads(r[5])
    except Exception: out = {}
    return {"ts": r[0], "score": r[1], "risk": r[2], "ms": r[3], "summary": r[4], "out": out, "cycle": r[6]}
def decision():
    d = Q("SELECT decision_id, ts, score, risk, narrative, evidence FROM decisions ORDER BY decision_id DESC LIMIT 1")
    if not len(d): return None
    try: ev = json.loads(d.evidence[0])
    except Exception: ev = {}
    return {"id": int(d.decision_id[0]), "ts": d.ts[0], "score": float(d.score[0]), "risk": d.risk[0], "narrative": d.narrative[0], "ev": ev}
def scoped(df, c, col="target"):
    return df[df[col].astype(str) == c["scope"]] if c.get("scope") and len(df) else df

# ------------------------------------------------------------------ tickets
def tk_df(c, agent=None, types=None, target=None, statuses=("open", "proposed"), limit=300):
    dom = c["dom"]; sql = "SELECT action_id id, severity, status, type, target, detail, owner, assignee, due, note, ts FROM agent_actions WHERE status IN (%s)" % ",".join("?" * len(statuses)); p = list(statuses)
    ts = types or ([t for t, a in dom.ACTION_AGENT.items() if a == agent] if agent else None)
    if ts: sql += f" AND type IN ({','.join('?' * len(ts))})"; p += list(ts)
    if target: sql += " AND target=?"; p.append(target)
    df = Q(sql + " ORDER BY CASE severity WHEN 'Critical' THEN 0 WHEN 'Warning' THEN 1 ELSE 2 END, action_id DESC LIMIT " + str(limit), p)
    return scoped(df, c)
def ticket_items(c, df, comments=True):
    dom = c["dom"]; now = LE.now(); ids = df.id.tolist(); cm = {}
    if comments and ids:
        for r in Q("SELECT action_id a, ts, author, body FROM ticket_comments WHERE action_id IN (%s) ORDER BY comment_id" % ",".join("?" * len(ids)), ids).itertuples(): cm.setdefault(int(r.a), []).append({"ts": r.ts[5:16], "by": r.author, "body": r.body})
    out = []; ch = LE.chains(ids) if ids else {}
    for r in df.itertuples():
        _c = ch.get(int(r.id), []); _nx = LE.next_role(_c)
        out.append({"chain": _c, "turn": _nx, "id": int(r.id), "sev": r.severity, "status": r.status, "type": r.type, "target": r.target, "detail": r.detail, "owner": r.owner if isinstance(r.owner, str) else "", "assignee": r.assignee if isinstance(r.assignee, str) else "", "due": (r.due if isinstance(r.due, str) else "")[:16], "note": r.note if isinstance(r.note, str) else "", "agent": dom.ACTION_AGENT.get(r.type, "engine"), "ts": (r.ts or "")[5:16],
                    "overdue": bool(isinstance(r.due, str) and r.due and r.due < now), "comments": cm.get(int(r.id), []), "can_approve": bool(can(c, "approve") and (not _nx or LE._role_ok(c["role"], _nx))), "can_resolve": bool(can(c, "resolve")), "quote": r.type == "quote_approval", "entity": EN.kind_of(r.target)})
    return out
def ticket_block(c, agent=None, types=None, title="Open tickets", target=None, key=None, limit=60):
    df = tk_df(c, agent, types, target, limit=limit); return B.tickets(ticket_items(c, df), key=key or f"tk_{agent or target or 'all'}", title=title)
def ist_time(ts):
    """A server timestamp (naive = the server's local time) as a clock time in Indian Standard Time, e.g. 10:42:15 PM IST."""
    try: d = datetime.datetime.fromisoformat(str(ts))
    except Exception: return ts
    d = d.astimezone() if d.tzinfo is None else d
    return d.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).strftime("%I:%M:%S %p IST").lstrip("0")
def hero(c, agent, title, blurb):
    r = latest(agent)
    if r: r = {**r, "ts": ist_time(r["ts"])}
    if c.get("scope") and r: r = {**r, "score": None, "risk": "", "summary": "Showing your outlet only."}      # the agent's score and summary are chain-wide and name other outlets
    return B.hero(agent, title, blurb, r, can_run=can(c, "run"))
def cross(c, targets, own, title="Flagged by other agents for these entities"):
    t = [str(x) for x in list(dict.fromkeys(targets))][:60]
    if not t: return None
    df = Q("SELECT type, target, severity, detail FROM agent_actions WHERE status IN ('open','proposed') AND target IN (%s)" % ",".join("?" * len(t)), t)
    df["agent"] = df.type.map(lambda x: c["dom"].ACTION_AGENT.get(x, "engine")); df = df[df.agent != own].head(30)
    if not len(df): return None
    return B.table(df, ["target", "agent", "type", B.pill_col("severity"), "detail"], title=title, h=240, open={"col": "target"}, key="cross_" + own)

# ------------------------------------------------------------------ Command Center
def command(c, tab="ops"):
    dom, kind = c["dom"], c["kind"]; tabs = [{"id": "ops", "label": "Operations"}, {"id": "agents", "label": "Agents"}, {"id": "anomaly", "label": "Anomalies"}, {"id": "net", "label": "Knowledge graph"}, {"id": "explore", "label": "Entity explorer"}]
    if c.get("scope"): sub = f"{dom.NAME} · scoped to {c['scope']}"
    else: sub = f"{dom.NAME} · live agent network"
    acts = [{"id": "run", "label": "Run agent cycle", "url": "/api/run_cycle", "tone": "primary"}] if can(c, "run") else []
    if tab == "agents": return B.page("Command Center", sub, _agents_tab(c), tabs, live=8, actions=acts)
    if tab == "anomaly": return B.page("Command Center", sub, _anomaly_tab(c), tabs, live=12, actions=acts)
    if tab == "net": return B.page("Command Center", sub, kg_blocks(c), tabs, live=12, actions=acts)
    if tab == "explore": return B.page("Command Center", sub, entity_explorer(c), tabs, live=0, actions=acts)
    return B.page("Command Center", sub, kind_ops(c), tabs, live=4, actions=acts)

# ------------------------------------------------------------------ Approvals inbox (human in the loop)
SOURCE = {"manual_request": "Approval request", "quote_approval": "Quote approval", "ml_review": "ML second opinion", "twin_mitigation": "Digital Twin"}
def approvals(c, tab="awaiting"):
    dom = c["dom"]; tabs = [{"id": "awaiting", "label": "Awaiting approval"}, {"id": "tickets", "label": "All open tickets"}, {"id": "request", "label": "Request approval"}, {"id": "matrix", "label": "Who approves what"}, {"id": "history", "label": "Decisions & audit trail"}] + ([{"id": "policy", "label": "Autonomy policy"}] if can(c, "admin") else [])
    sub = "Everything that needs a human: agent proposals, quote approvals, ML second opinions and Digital Twin recommendations. Approve to execute, reject to dismiss; every decision is audited."
    if tab == "policy" and can(c, "admin"):
        return B.page("Approvals", sub, [B.callout("Choose which agent actions run on their own (auto) and which wait here for a human (approval), and who signs off each kind. Changes apply to the next agent cycle and are written to the audit log.", "info"), policy_form(c), chain_form(c)], tabs, live=0)
    if tab == "request":
        who = c["email"]; mine = Q("SELECT action_id id, ts, detail, severity, status, approval decision FROM agent_actions WHERE type='manual_request' AND note LIKE ? ORDER BY action_id DESC LIMIT 50", (f"%requested by {who};%",)) if not can(c, "admin") else Q("SELECT action_id id, ts, detail, severity, status, approval decision FROM agent_actions WHERE type='manual_request' ORDER BY action_id DESC LIMIT 100")
        ch = LE.chains(mine.id.tolist()) if len(mine) else {}
        if len(mine): mine["progress"] = mine.id.map(lambda i: " → ".join(f"{s['role']} {'✓' if s['status']=='approved' else '✗' if s['status']=='rejected' else '…'}" for s in ch.get(int(i), [])))
        kinds = list(dom.REQUEST_KINDS)
        bl = [B.callout("Ask for a decision on anything the agents did not raise themselves. Every kind of request has its own sign-off chain (see the tab Who approves what). Pick 2 levels to add an Admin sign-off on top. Nobody can approve their own request or two steps of the same one.", "info"),
              B.form("req", [{"name": "kind", "label": "What do you need approved?", "type": "select", "options": kinds}, {"name": "target", "label": "Outlet / shipment / quote ID (optional)", "type": "text", "value": c.get("scope") or ""},
                             {"name": "detail", "label": "Details and why", "type": "textarea"}, {"name": "severity", "label": "Urgency", "type": "select", "options": ["Info", "Warning", "Critical"], "value": "Warning"},
                             {"name": "levels", "label": "Approval levels (1 = the standard chain for this request, 2 = also an Admin)", "type": "select", "options": ["1", "2"], "value": "1"}], "Send for approval", "/api/approval/request", title="New approval request")]
        bl.append(B.table(mine[["id", "ts", "detail", "severity", "progress", "status"]], ["id", "ts", "detail", B.pill_col("severity"), "progress", B.pill_col("status")], title="Requests (yours; Admin sees all)", h=300, key="ap_req") if len(mine) else B.callout("No requests yet.", "info"))
        return B.page("Approvals", sub, bl, tabs, live=0)
    if tab == "matrix":
        return B.page("Approvals", sub, approval_matrix(c), tabs, live=0)
    if tab == "history":
        h = Q("SELECT action_id id, ts, type, target, severity, approval decision, status, note FROM agent_actions WHERE approval IN ('approved','rejected') OR status IN ('resolved','rejected') ORDER BY action_id DESC LIMIT 300"); h = scoped(h, c) if len(h) else h
        bl = []
        if len(h):
            h["decision"] = h.decision.fillna(h.status); h["by"] = h.note.fillna("").str.extract(r"(?:approved|rejected) by (\S+)")[0].fillna("").str.rstrip(";,")
            n_ap = int((h.decision == "approved").sum()); n_rj = int((h.decision == "rejected").sum())
            bl.append(B.kpis(("Approved", n_ap), ("Rejected", n_rj, None, "Warning" if n_rj else None), ("Resolved", int((h.status == "resolved").sum())), ("Approval rate", f"{n_ap / max(1, n_ap + n_rj):.0%}")))
            bl.append(B.table(h.assign(type=h.type.map(lambda t: SOURCE.get(t, t)))[["id", "ts", "type", "target", "severity", "decision", "by"]], ["id", "ts", "type", "target", B.pill_col("severity"), B.pill_col("decision"), "by"], title="Recent decisions", h=360, open={"col": "target"}, key="ap_h", search=True))
        else: bl.append(B.callout("No decisions recorded yet. Approve or reject something on the first tab.", "info"))
        if can(c, "admin"):
            a = Q("SELECT ts, actor, event, target, detail FROM audit_log WHERE event IN ('approve','reject','policy','twin_propose','reroute','resolve','assign') ORDER BY audit_id DESC LIMIT 200")
            bl.append(B.table(a, ["ts", "actor", B.pill_col("event"), "target", "detail"], title="Who decided what (audit trail)", h=320, key="ap_a", search=True))
        return B.page("Approvals", sub, bl, tabs, live=0)
    df = tk_df(c, limit=300)
    if tab == "tickets":
        n_over = int(df.detail.str.startswith("OVERDUE").sum()) if len(df) else 0
        bl = [B.kpis(("Open + proposed", len(df)), ("Critical", int((df.severity == "Critical").sum()) if len(df) else 0, None, "Critical"), ("Overdue / escalated", n_over, f"escalated to {dom.ESCALATE_TO}", "Critical" if n_over else None)),
              B.tickets(ticket_items(c, df), key="tk_all", title="Tickets", sub="Assign, comment and resolve. Overdue tickets escalate automatically.")]
        if can(c, "run"): bl.append(B.button("sla", "Check SLAs now", "/api/sla", "ghost"))
        return B.page("Approvals", sub, bl, tabs, live=6)
    aw = df[(df.status == "proposed") | (df.type == "quote_approval")] if len(df) else df
    src = aw.type.map(lambda t: SOURCE.get(t, "Agent proposal")).value_counts() if len(aw) else pd.Series(dtype=int)
    try: oldest = f"{max(0, (pd.Timestamp(LE.now()) - pd.to_datetime(aw.ts, errors='coerce').min()).total_seconds() / 3600):.0f} h" if len(aw) else "–"
    except Exception: oldest = "–"
    bl = [B.kpis(("Awaiting your decision", len(aw), None, "Warning" if len(aw) else None), ("Critical", int((aw.severity == "Critical").sum()) if len(aw) else 0, None, "Critical"), ("Oldest waiting", oldest), ("From agents", int(src.get("Agent proposal", 0))), ("Quotes / ML / Twin", int(len(aw) - src.get("Agent proposal", 0))))]
    if len(aw): bl.append(B.tickets(ticket_items(c, aw), key="tk_aw", title="Needs a decision", sub="Approve executes the action (re-route, quote, stock transfer…); reject dismisses it. Add a note and it is kept in the audit trail."))
    else: bl.append(B.callout("Nothing is waiting for you. Agents act on their own where the autonomy policy says auto; anything set to approval, every ML second opinion and every Digital Twin recommendation shows up here.", "success", "All clear"))
    return B.page("Approvals", sub, bl, tabs, live=6)

def kind_ops(c):
    import importlib; return importlib.import_module("views_franchise" if c["kind"] == "Franchise" else "views_freight").ops(c)

def _tickets_tab(c):
    dom = c["dom"]; blocks = []
    df = tk_df(c, limit=250); n_prop = int((df.status == "proposed").sum()); n_over = int(df.detail.str.startswith("OVERDUE").sum()) if len(df) else 0
    blocks.append(B.kpis(("Open + proposed", len(df)), ("Awaiting your approval", n_prop, "agent proposals not yet executed", "Warning" if n_prop else None), ("Overdue / escalated", n_over, None, "Critical" if n_over else None), ("Critical", int((df.severity == "Critical").sum()), None, "Critical")))
    blocks.append(B.tickets(ticket_items(c, df), key="tk_all", title="Tickets", sub="Approve or reject what the agents propose, assign, comment and resolve. Everything is recorded in the audit log."))
    if can(c, "admin"): blocks.append(policy_form(c))
    return blocks
def _chain_txt(ch): return " → ".join(ch)
def approval_matrix(c):
    """Every approval in the product on one page: agent actions (auto or approval) and every kind of manual request, with its sign-off chain and deadline."""
    dom = c["dom"]; pol = LE.policy(dom); cfg = LE.get_state("approval_chain", {}) or {}; rows = []
    for t in sorted(dom.ACTION_AGENT):
        ch = cfg.get(t) or dom.DEFAULT_CHAINS.get(t) or []
        rows.append({"what": t.replace("_", " "), "raised by": "Agent: " + dom.ACTION_AGENT[t], "mode": pol.get(t, "auto"), "sign-off chain": _chain_txt(ch) if pol.get(t, "auto") == "approval" else "none: the agent acts and logs it", "owner": dom.OWNER.get(t, "")})
    for k in dom.REQUEST_KINDS:
        rows.append({"what": k, "raised by": "A person (Request approval tab)", "mode": "approval", "sign-off chain": _chain_txt(cfg.get("req:" + k) or dom.REQUEST_KINDS[k]), "owner": "the approvers"})
    df = pd.DataFrame(rows); n_ap = int((df["mode"] == "approval").sum())
    bl = [B.kpis(("Things that need approval", n_ap), ("Run automatically", len(df) - n_ap), ("Agent action types", len(dom.ACTION_AGENT)), ("Kinds of request", len(dom.REQUEST_KINDS))),
          B.callout("Each row is one kind of decision. approval = a human signs off, in the order shown, before anything runs. Critical items get an extra Admin sign-off. Nobody can approve their own request or two steps of the same one. An Admin can change a chain or a mode on the Autonomy policy tab.", "info"),
          B.table(df, ["what", "raised by", B.pill_col("mode"), "sign-off chain", "owner"], title="Who approves what", h=520, key="ap_matrix", search=True)]
    return bl
def chain_form(c):
    dom = c["dom"]; cfg = LE.get_state("approval_chain", {}) or {}; fields = []
    def f(key, label, default):
        cur = _chain_txt(cfg.get(key) or default); opts = list(dom.CHAIN_PRESETS) + ([cur] if cur not in dom.CHAIN_PRESETS else []); fields.append({"name": key, "label": label, "type": "select", "options": opts, "value": cur})
    for t in sorted(dom.ACTION_AGENT):
        if t in dom.DEFAULT_CHAINS or t in cfg: f(t, "Agent action: " + t.replace("_", " "), dom.DEFAULT_CHAINS.get(t, ["Franchise Owner"]))
    for k, v in dom.REQUEST_KINDS.items(): f("req:" + k, "Request: " + k, v)
    return B.form("chain", fields, "Save approval chains", "/api/approval/chain", title="Approval chains", sub="Who signs off, and in which order, for each kind of approval. Critical items still get an extra Admin sign-off unless you set the chain here.")
def policy_form(c):
    pol = LE.policy(c["dom"]); fields = [{"name": t, "label": t.replace("_", " "), "type": "select", "options": ["auto", "approval"], "value": pol.get(t, "auto")} for t in sorted(c["dom"].ACTION_AGENT)]
    return B.form("policy", fields, "Save autonomy policy", "/api/policy", title="Autonomy policy", sub="auto = the agent executes and logs it. approval = the action is only proposed until a human approves it (human in the loop).")

def _agents_tab(c):
    dom = c["dom"]; blocks = []
    t = Q("SELECT substr(ts,12,8) time, cycle_id cycle, agent, risk, latency_ms ms, summary FROM agent_runs ORDER BY run_id DESC LIMIT 40")
    h = Q("SELECT substr(ts,12,8) t, score FROM decisions ORDER BY decision_id DESC LIMIT 90").iloc[::-1]
    blocks.append(B.row(B.card("Agent timeline (live): planner, agents, re-plan loop, engine", B.table(t, ["time", "cycle", "agent", B.pill_col("risk"), B.num_col("ms", "ms", "int"), "summary"], h=380, key="timeline")),
                        B.card("Health trend", B.chart(B.line(h.t, h.score, ymin=0, ymax=100, colors=[TEAL]), h=170, key="trend"), B.table(pd.DataFrame(dom.feed_status(), columns=["feed", "status"]), title="Data feeds", h=170, key="feeds")), ratio=[3, 2]))
    e = Q("SELECT type, COUNT(*) raised, SUM(status IN ('resolved','approved')) resolved, SUM(status='auto-closed') auto_closed, SUM(status IN ('open','proposed')) open_, SUM(status='rejected') rejected FROM agent_actions GROUP BY type ORDER BY raised DESC")
    if len(e):
        e["agent"] = e.type.map(lambda x: dom.ACTION_AGENT.get(x, "engine")); e["fix_rate"] = ((e.resolved + e.auto_closed) / e.raised * 100).round(0)
        pf = Q("SELECT agent, COUNT(*) runs, ROUND(AVG(latency_ms)) avg_ms, ROUND(AVG(score),1) avg_score FROM agent_runs GROUP BY agent ORDER BY runs DESC")
        blocks.append(B.row(B.card("Agent effectiveness: raised, fixed by people, auto-closed once the problem went away", B.table(e, ["agent", "type", B.num_col("raised", "raised", "int"), B.num_col("resolved", "resolved", "int"), B.num_col("auto_closed", "auto-closed", "int"), B.num_col("open_", "open", "int"), B.num_col("fix_rate", "fixed %", "bar", 100)], h=300, key="eff")),
                            B.card("Latency per agent (ms)", B.chart(B.bar(pf.agent, pf.avg_ms, horizontal=True, colors=[BLUE]), h=300, key="lat")), ratio=[3, 2]))
    return blocks

def _anomaly_tab(c):
    dom, kind = c["dom"], c["kind"]; agent = "anomaly" if kind == "Franchise" else "anomaly_watch"; r = latest(agent); blocks = []
    blocks.append(B.hero(agent, "Anomaly detection (IsolationForest)", "Each outlet's sales vs baseline, volatility and sentiment." if kind == "Franchise" else "Quote economics: price/base ratio, margin, fuel share.", r, can_run=can(c, "run")))
    o = (r or {}).get("out", {}); fl = set(o.get("flagged", []))
    if kind == "Franchise" and o.get("all"):
        d = pd.DataFrame(o["all"]); d["flag"] = d.outlet_id.isin(fl) | (d.ratio < .6); d = d if not c.get("scope") else d[d.outlet_id == c["scope"]]
        g = {"Normal": [{"x": a.ratio, "y": a.vol, "label": a.outlet_id} for a in d[~d.flag].itertuples()], "Flagged": [{"x": a.ratio, "y": a.vol, "label": a.outlet_id} for a in d[d.flag].itertuples()]}
        blocks.append(B.card("Sales vs baseline and volatility (click a dot)", B.chart(B.scatter(g, "sales ÷ baseline", "volatility", colors={"Normal": TEAL, "Flagged": RED}), h=340, open={"scatter": True}, key="an_sc")))
    elif kind == "Freight":
        q = Q("SELECT quote_id, base_cost, final_price price, margin_pct margin FROM freight_quotes WHERE base_cost>0 ORDER BY rowid DESC LIMIT 600"); q["ratio"] = q.price / q.base_cost; q["flag"] = q.quote_id.isin(fl)
        g = {"Normal": [{"x": a.ratio, "y": a.margin, "label": a.quote_id} for a in q[~q.flag].itertuples()], "Flagged": [{"x": a.ratio, "y": a.margin, "label": a.quote_id} for a in q[q.flag].itertuples()]}
        blocks.append(B.card("Price ÷ base cost vs margin (click a dot)", B.chart(B.scatter(g, "price ÷ base", "margin %", colors={"Normal": TEAL, "Flagged": RED}), h=340, open={"scatter": True}, key="an_sc")))
    blocks += kg_blocks(c, compact=True)
    x = cross(c, fl, agent)
    if x: blocks.append(x)
    blocks.append(ticket_block(c, agent, title="Anomaly tickets", key="tk_anom")); return blocks

# ------------------------------------------------------------------ Knowledge graph
def kg_network(c, sev=("Critical", "Warning"), limit=110):
    dom = c["dom"]; a = Q("SELECT type, target, severity, detail FROM agent_actions WHERE status IN ('open','proposed') ORDER BY CASE severity WHEN 'Critical' THEN 0 WHEN 'Warning' THEN 1 ELSE 2 END, action_id DESC LIMIT 260"); a = scoped(a, c); a = a[a.severity.isin(sev)].head(limit)
    nodes, links, seen = [], [], set()
    def add(i, kind, size, color=None, tip="", label=False, open=None):
        if i not in seen: seen.add(i); nodes.append({"id": i, "kind": kind, "size": size, "color": color, "tip": tip, "label": label, "open": open})
    for t, tg, sv, d in a.itertuples(index=False):
        ag = dom.ACTION_AGENT.get(t, "engine"); add(ag, "agent", 34, TEAL, "agent", True); add(t, "ticket type", 22, VIOLET, "action type", True); add(tg, "entity", 11, TONE.get(sv, "#8b8d98"), d[:120], False, tg); links += [(ag, t), (t, tg)]
    multi = a.groupby("target").agg(issues=("type", "nunique"), agents=("type", lambda s: len({dom.ACTION_AGENT.get(x, "engine") for x in s}))).sort_values(["agents", "issues"], ascending=False); multi = multi[multi.issues > 1].reset_index().rename(columns={"target": "entity"})
    return nodes, links, multi
def kg_blocks(c, compact=False):
    nodes, links, multi = kg_network(c)
    if not nodes: return [B.callout("No open tickets to graph.", "info")]
    out = [B.card("Live knowledge graph: agent → ticket type → entity (click an entity to open it)", B.chart(B.graph(nodes, links), h=480, open={"graph": True}, key="kg_net"), sub="Built from the agents' tickets in real time. Drag nodes, scroll to zoom.")]
    if len(multi): out.append(B.table(multi, ["entity", B.num_col("issues", "issue types", "int"), B.num_col("agents", "agents", "int")], title="Entities with several different problems at once (compounding risk)", h=220, open={"col": "entity"}, key="kg_multi"))
    return out
def kg_page(c, tab="net"):
    tabs = [{"id": "net", "label": "Network"}, {"id": "explore", "label": "Entity explorer"}]
    if tab == "explore": return B.page("Knowledge Graph", "Everything the platform knows about one entity", entity_explorer(c), tabs, live=0)
    return B.page("Knowledge Graph", "Built live from the agents' tickets and the operational tables", kg_blocks(c), tabs, live=12)
def entity_explorer(c):
    kind, dom = c["kind"], c["dom"]; e = (c.get("params") or {}).get("e")
    ents = Q("SELECT DISTINCT target FROM agent_actions WHERE status IN ('open','proposed') LIMIT 300").target.tolist()
    base = Q("SELECT outlet_id e FROM outlets ORDER BY outlet_id").e.tolist() if kind == "Franchise" else Q("SELECT port_name e FROM ports ORDER BY congestion_index DESC LIMIT 60").e.tolist()
    opts = list(dict.fromkeys(([c["scope"]] if c.get("scope") else ents + base))); e = e or opts[0]
    d = EN.describe(kind, dom, e); nodes = [{"id": e, "kind": "focus", "size": 34, "color": "#ffffff", "tip": "selected", "label": True}]; links = []
    for n, k, tip in d["rel"]: nodes.append({"id": n, "kind": k, "size": 16, "tip": tip, "label": True, "open": n if EN.kind_of(n) != "port" or kind == "Freight" else None}); links.append((e, n))
    for r in d["tickets"][d["tickets"].status.isin(["open", "proposed"])].itertuples():
        n = f"#{r.id} {r.type}"; ag = dom.ACTION_AGENT.get(r.type, "engine"); nodes += [{"id": n, "kind": "ticket", "size": 14, "color": TONE.get(r.severity), "tip": r.detail[:120], "label": True}, {"id": ag, "kind": "agent", "size": 26, "color": TEAL, "tip": "agent", "label": True}]; links += [(e, n), (n, ag)]
    seen = set(); nodes = [n for n in nodes if not (n["id"] in seen or seen.add(n["id"]))]
    sel = {"t": "form", "id": "kg_pick", "fields": [{"name": "e", "label": "Entity", "type": "select", "options": opts, "value": e}], "submit": "Explore", "url": "page:kg:explore", "title": None, "tone": "primary", "inline": True}
    info = B.table([{"field": k, "value": v} for k, v in d["info"].items()], ["field", "value"], title="What the platform knows", h=230, key="kg_info") if d["info"] else B.callout("No master record for this entity.", "info")
    tk = d["tickets"]
    return [sel, B.row(B.card("Facts", info, B.table(tk, ["id", B.pill_col("severity"), B.pill_col("status"), "type", "owner", "detail"], title="Why is it flagged", h=260, key="kg_tk")), B.card("Relations", B.chart(B.graph(nodes, links), h=470, open={"graph": True}, key="kg_ent")), ratio=[2, 3])]
