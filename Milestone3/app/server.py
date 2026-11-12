"""Web server: FastAPI JSON API + server-sent events + the single-page front end. Models live on the GPU in this process; the simulator and agent cycles run in worker.py."""
import os as _os, time as _time
_os.environ["TZ"] = "Asia/Kolkata"
try: _time.tzset()
except Exception: pass          # all times in this app are India Standard Time (IST)
import sqlite3, os, sys, io, re, csv, json, time, asyncio, subprocess, threading, importlib, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from config import KIND, DB_PATH
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File, Form, Header
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
import numpy as np
import mailer, reports as RP
import privacy as PV, qa as QA, analyst as AN, live_engine as LE, data_feeder as FD, gpu, rag, entities as EN, blocks as B
import rbac, accounts, intents
import views_core as VC, views_misc as VM, persist as PS
dom = importlib.import_module("domain_franchise" if KIND == "Franchise" else "domain_freight")
V = importlib.import_module("views_franchise" if KIND == "Franchise" else "views_freight")
HERE = os.path.dirname(os.path.abspath(__file__)); STATIC = os.path.join(HERE, "static")
app = FastAPI(title=f"{V.NAME} Platform", docs_url=None, redoc_url=None, openapi_url=None) if os.environ.get("PUBLIC_DOCS") != "1" else FastAPI(title=f"{V.NAME} Platform"); _worker = None; _ready = {"db": False}
import hardening; hardening.install(app, KIND); PV.start()

@app.middleware("http")
async def sec(request, call_next):
    r = await call_next(request); r.headers["X-Content-Type-Options"] = "nosniff"; r.headers["Referrer-Policy"] = "same-origin"; r.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else r.headers.get("Cache-Control", "public, max-age=300"); return r

def _boot():
    from db import init_db; from seed_data import seed_all
    PS.restore()                                                  # bring the database back from Google Drive after a runtime reset
    init_db(); seed_all(); LE.init_live_tables(); accounts.init(); FD.init(); _ready["db"] = True; PS.start()
    try:
        _c = LE.conn(); LE._steps_ddl(_c); _c.commit()          # the approval table exists from the first start, not only after the first ticket
    except Exception as e: print("approval table:", repr(e), file=sys.stderr)
    threading.Thread(target=_warm_up, daemon=True).start()
    threading.Thread(target=lambda: (rag._seed(), _seed_taught()), daemon=True).start()   # builds the knowledge base (built-in pack + your Drive chunks) right at start, then loads the taught questions
def _seed_taught():
    """Loads taught_questions.csv (question, answer, keywords) into Admin > Teach Copilot on start. A question that is already taught is left alone, so this is safe to run on every start."""
    import csv as _csv, copilot_pro as _CP
    for p in (os.environ.get("TAUGHT_CSV", ""), os.path.join(HERE, "taught_questions.csv"), os.path.join(HERE, "..", "taught_questions.csv")):
        if p and os.path.isfile(p): break
    else: return
    try:
        have = {r["question"].strip().lower() for r in _CP.taught_rows()}; n = 0
        for r in _csv.DictReader(open(p, encoding="utf-8-sig")):
            r = {str(k or "").strip().lower(): (v or "") for k, v in r.items()}; q = (r.get("question") or r.get("q") or "").strip()
            if q and q.lower() not in have and _CP.teach(q, r.get("answer") or r.get("a", ""), r.get("keywords", ""), r.get("added_by") or r.get("by") or "taught_questions.csv"): n += 1
        if n: print(f"taught questions: {n} loaded from {os.path.basename(p)}", file=sys.stderr)
    except Exception as e: print("taught questions:", repr(e), file=sys.stderr)
def _warm_up():
    """Runs once the models are up: one dummy search, rerank, translation and generation, so the first real question is not the one that pays for CUDA kernels and caches."""
    try:
        for _ in range(150):
            m = gpu.S["models"]
            if all(m[k]["state"] in ("ready", "failed") for k in ("embed", "rerank", "nllb")) and m["llm"]["state"] in ("ready", "failed"): break
            time.sleep(4)
        try: rag.search("refund policy and approval limits", "warm", 3, "hybrid", True)
        except Exception: pass
        try: gpu.translate("How many outlets are open today?", "hin_Deva", "eng_Latn")
        except Exception: pass
        try:
            if gpu.llm_ready(): gpu.llm_text([{"role": "user", "content": "Say OK."}], max_new_tokens=4, temperature=0.0)
        except Exception: pass
        try: VC.decision()
        except Exception: pass
    except Exception as e: print("warm-up:", repr(e), file=sys.stderr)
@app.on_event("startup")
def startup():
    global _worker
    _boot(); gpu.start()
    if os.environ.get("NO_WORKER") != "1":
        env = {**os.environ, "APP_KIND": KIND}; _worker = subprocess.Popen([sys.executable, os.path.join(HERE, "worker.py")], env=env, cwd=HERE)
@app.on_event("shutdown")
def shutdown():
    try: PS.stop()
    except Exception: pass
    if _worker:
        try: _worker.terminate()
        except Exception: pass

# ------------------------------------------------------------------ auth + context (Milestone 2: JWT login, RBAC, 403)
def user_of(request: Request): return accounts.current_user(request)     # Bearer JWT (or the cookie for GET downloads and the live stream) -> the real user from the database; 401 when missing, expired, deleted or locked
app.include_router(accounts.router)                                     # sign-up, sign-in, recovery by e-mail code or security question, profile, admin users
app.state.user_of = lambda request: user_of(request)                    # late-bound so hardening.py (metrics) always asks the current user_of
def ctx(u, params=None):
    """Identity and permission for one request. Raises 403 for an unknown role or a scoped role with no outlet. scope = the outlet id, or None for all outlets."""
    return {"dom": dom, "kind": KIND, "role": rbac.role_of(u), "email": u["email"], "user": u, "scope": rbac.scope_for(u), "params": params or {}}
def need(c, cap): rbac.need(c, cap)                                     # 403 when the role lacks the capability (see rbac.ROLE_CAPS)
def _cop(request):
    """A signed-in user whose role may use the Copilot and the knowledge base (403 otherwise)."""
    u = user_of(request); need(ctx(u), "copilot"); return u
def menu_for(user): return rbac.menu_for(user if isinstance(user, str) else rbac.role_of(user), list(V.MENU))
def ok(msg="Done", **kw): return {"ok": True, "msg": msg, **kw}
def bad(msg): return JSONResponse({"ok": False, "msg": msg}, status_code=400)

@app.get("/api/public")
def public():
    s = LE.get_state("boot", {}) if _ready["db"] else {}
    return {"kind": KIND, "name": V.NAME, "stage": (s or {}).get("stage", "starting"), "gpu": {"cuda": gpu.S["cuda"], "name": gpu.S["gpu"]}, "questions": [], "email_enabled": mailer.configured(), "demo": []}
@app.get("/api/me")
def me(request: Request):
    u = user_of(request); c = ctx(u); pub = {k: u.get(k) for k in ("id", "email", "username", "role", "outlet", "created_at", "last_login") if k in u}; pub["picture"] = accounts.picture_of(u["id"]) if u.get("id") else None   # never the password hash
    return {"user": pub, "kind": KIND, "name": V.NAME, "menu": [{"id": i, "label": l, "icon": ic} for i, l, ic in menu_for(u)], "caps": sorted(rbac.caps_of(c["role"])), "scope": c["scope"], "langs": list(gpu.NLLB_LANGS), "questions": []}

# ------------------------------------------------------------------ live pulse
def pulse(scope=None):
    """Live header numbers. A scoped role only gets its own outlet's tickets and health, never the chain-wide totals."""
    rt = LE.get_state("runtime", {}) or {}; boot = LE.get_state("boot", {}) or {}
    d = VC.decision(); oa = B.Q("SELECT status, severity, COUNT(*) n FROM agent_actions WHERE status IN ('open','proposed')" + (" AND target=?" if scope else "") + " GROUP BY status, severity", (scope,) if scope else ())
    n = lambda st, sv=None: int(oa[(oa.status == st) & ((oa.severity == sv) if sv else True)].n.sum()) if len(oa) else 0
    if scope and d: sh = (d.get("ev") or {}).get("health", {}).get(scope); d = {"score": sh, "risk": "High" if sh is not None and sh < 60 else "Medium" if sh is not None and sh < 80 else "Low", "id": d["id"]} if sh is not None else None
    g = gpu.status()
    return {"stage": boot.get("stage", "starting"), "ticks": rt.get("ticks", 0), "cycles": rt.get("cycles", 0), "last_cycle": rt.get("last_cycle"), "health": d["score"] if d else None, "risk": d["risk"] if d else None, "dec": d["id"] if d else 0,
            "open": n("open"), "critical": n("open", "Critical"), "proposed": n("proposed"), "gpu": {"cuda": g["cuda"], "name": g["gpu"], "used": g["vram_used_gb"], "total": g["vram_gb"], "llm": g["models"]["llm"]["state"], "llm_name": g["models"]["llm"]["name"], "llm_done": g["models"]["llm"].get("done_gb"), "llm_total": g["models"]["llm"].get("total_gb"), "llm_err": g["models"]["llm"]["err"], "nllb": g["models"]["nllb"]["state"], "embed": g["models"]["embed"]["state"], "tok_s": g["stats"]["tok_s"]}, "worker_alive": (_worker is None or _worker.poll() is None)}
@app.get("/api/pulse")
def pulse_http(request: Request): c = ctx(user_of(request)); return pulse(c["scope"])
@app.get("/api/stream")
async def stream(request: Request):
    sc = ctx(user_of(request))["scope"]
    async def gen():
        last = None; t0 = time.time()
        while True:
            if await request.is_disconnected(): break
            try: p = await asyncio.to_thread(pulse, sc)
            except Exception as e: p = {"error": str(e)}
            k = json.dumps(p, sort_keys=True, default=str)
            if k != last or time.time() - t0 > 10: last = k; t0 = time.time(); yield f"data: {k}\n\n"
            await asyncio.sleep(1.5)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ------------------------------------------------------------------ pages
_TABS = {}
def _tabs_of(c, f):
    if f not in _TABS: _TABS[f] = f(c, None).get("tabs")
    return _TABS[f]
def _simtabs(t): return (t or [{"id": "main", "label": "Overview"}]) + [{"id": "sim", "label": "Simulator"}]
def _page(c, pid, tab):
    if pid == "command": return VC.command(c, tab or "ops")
    if pid == "approvals": return VC.approvals(c, tab or "awaiting")
    if pid == "kg": return VC.kg_page(c, tab or "net")
    if pid == "copilot": return VM.copilot(c, tab or "chat")
    if pid == "notifications": return VM.notifications(c, tab or "alerts")
    if pid == "twin": return VM.twin(c, tab)
    if pid == "feeds": return VM.feeds(c, tab or "upload")
    if pid == "admin": return VM.admin(c, tab or "users")
    if pid == "reports": return VM.reports(c, tab or "pdf")
    f = V.PAGES.get(pid)
    if f:
        if tab == "sim":
            sm = VM.simulator(c, pid); return {**sm, "title": sm["title"], "tabs": _simtabs(_tabs_of(c, f)), "live": 0}
        o = f(c, None if tab == "main" else tab); _TABS[f] = o.get("tabs"); o["tabs"] = _simtabs(o.get("tabs")); return o
    raise HTTPException(404, "unknown page")
@app.get("/api/page/{pid}")
def page(pid: str, request: Request, tab: str = "", p: str = ""):
    u = user_of(request); c = ctx(u, json.loads(p) if p else {})
    rbac.need_page(c, pid); rbac.guard_outlets(c, p, tab)                 # 403 for a page outside the role, or for a parameter naming another outlet
    t = time.time(); out = _page(c, pid, tab or None); out["id"] = pid; out["ms"] = round((time.time() - t) * 1000); return JSONResponse(B.clean(out))
@app.get("/api/detail/{eid:path}")
def detail(eid: str, request: Request):
    u = user_of(request); c = ctx(u); need(c, "view"); rbac.guard_outlets(c, eid)
    return JSONResponse(B.clean(V.detail(c, eid)))

# ------------------------------------------------------------------ tickets, cycles, policy
def _tk(aid):
    r = LE.conn().execute("SELECT target, type, status FROM agent_actions WHERE action_id=?", (aid,)).fetchone()
    if not r: raise HTTPException(404, "ticket not found")
    return r
@app.post("/api/approval/request")
async def approval_request(request: Request):
    u = user_of(request); c = ctx(u); need(c, "view"); d = await request.json(); det = str(d.get("detail", "")).strip()[:600]
    if len(det) < 5: return bad("Describe what you need approved (a sentence or two).")
    tg = str(d.get("target", "")).strip()[:60] or "general"
    if c["scope"] and tg != "general" and not tg.startswith(c["scope"]): return bad(f"You can only raise requests for your outlet ({c['scope']}).")
    sev = d.get("severity") if d.get("severity") in ("Info", "Warning", "Critical") else "Warning"
    aid = LE.request_approval(dom, str(d.get("kind", "Other"))[:60], tg, det, sev, u["email"], d.get("levels") or 1)
    return ok(f"Request #{aid} sent. Track it under Approvals > Request approval.", refresh=True)
@app.post("/api/ticket/{aid}/{action}")
async def ticket(aid: int, action: str, request: Request):
    u = user_of(request); c = ctx(u); d = await request.json() if request.headers.get("content-length", "0") != "0" else {}; tg, typ, st = _tk(aid)
    if c["scope"] and not str(tg).startswith(c["scope"]): raise HTTPException(403, "outside your outlet")
    em = u["email"]
    if action in ("approve", "reject"):
        need(c, "approve"); yes = action == "approve"
        if st == "proposed":
            s2, msg = LE.approve_action(dom, aid, em, yes, d.get("note", ""), c["role"])
            if s2 in ("denied", "missing"): return bad(msg)
            return ok(("Approved and executed" if s2 == "final" else (msg[:1].upper() + msg[1:])) if yes else "Rejected")
        elif typ == "quote_approval" and hasattr(dom, "decide"):
            s2, msg = LE.advance(aid, em, c["role"], yes, d.get("note", ""))
            if s2 in ("denied", "missing"): return bad(msg)
            if s2 == "partial": return ok((msg[:1].upper() + msg[1:]))
            dom.decide(aid, yes, em); return ok("Approved and executed" if yes else "Rejected")
        else: raise HTTPException(400, "nothing to approve on this ticket")
    if action == "resolve": need(c, "resolve"); LE.resolve_action(aid, "resolved", f"by {em}", actor=em); return ok("Resolved")
    if action == "assign": need(c, "resolve"); LE.assign_action(aid, d.get("assignee"), em); return ok("Assigned")
    if action == "comment": need(c, "view"); LE.comment_action(aid, em, str(d.get("body", ""))[:500]); return ok("Posted")
    raise HTTPException(400, "unknown action")
@app.post("/api/run_cycle")
def run_cycle(request: Request):
    u = user_of(request); c = ctx(u); need(c, "run"); t = time.time(); LE.run_cycle(dom, "manual", ""); LE.audit(u["email"], "manual_cycle", "all"); return ok(f"Agents finished in {time.time() - t:.1f}s")
@app.post("/api/run_agent")
async def run_agent(request: Request):
    u = user_of(request); c = ctx(u); need(c, "run"); a = (await request.json()).get("agent")
    if a not in dom.AGENTS: raise HTTPException(404, "unknown agent")
    await asyncio.to_thread(_run_one, a); LE.audit(u["email"], "manual_agent", a); return ok(f"{a} re-ran")
def _run_one(agent):
    cid = time.strftime("%m%d-%H%M%S") + "-page"; t = time.time(); s = {"cycle_id": cid, "trigger": "page", "request": "", "queue": [], "results": {}}
    if agent == "digest":
        for a in ("outlet", "inventory", "staff", "marketing", "audit"): s["results"][a] = dom.AGENTS[a](s)
    res = dom.AGENTS[agent](s); LE._log_run(cid, "page", res, int((time.time() - t) * 1000)); s["results"][agent] = res; LE.act(dom, {"actions": res.actions}, cid, {agent: res})
@app.post("/api/sla")
def sla(request: Request): u = user_of(request); c = ctx(u); need(c, "run"); return ok(f"{LE.escalate_overdue(dom)} ticket(s) escalated")
@app.post("/api/notify_test")
def notify_test(request: Request): u = user_of(request); c = ctx(u); need(c, "admin"); LE.notify(dom, "TEST", "Critical", "Test", "Test alert from the Notifications page"); return ok("Sent to every configured channel")
@app.post("/api/policy")
async def policy(request: Request):
    u = user_of(request); c = ctx(u); need(c, "admin"); d = await request.json(); cur = LE.policy(dom)
    for t, m in d.items():
        if t in dom.ACTION_AGENT and m in ("auto", "approval") and cur.get(t, "auto") != m: LE.set_policy(t, m, u["email"])
    return ok("Policy saved")
@app.get("/api/audit.csv")
def audit_csv(request: Request):
    u = user_of(request); c = ctx(u)
    if not ("admin" in rbac.caps_of(c["role"]) or c["role"] == "Auditor"): raise HTTPException(403, "Forbidden: the audit log export is for the Admin and Auditor roles.")
    return PlainTextResponse(B.Q("SELECT ts, actor, event, target, detail FROM audit_log ORDER BY audit_id DESC LIMIT 20000").to_csv(index=False), headers={"Content-Disposition": "attachment; filename=audit_log.csv"}, media_type="text/csv")

# ------------------------------------------------------------------ digital twin
@app.post("/api/twin/run")
async def twin_run(request: Request):
    u = user_of(request); c = ctx(u); need(c, "view"); d = await request.json(); d.pop("scenario", None); c["email"] = u["email"]; t = time.time()
    if d.get("agents") not in ("yes", True): d["agents"] = False
    else: d["agents"] = True
    try: bl = await asyncio.to_thread(VM.twin_run, c, d)
    except Exception as e: return bad(f"Could not simulate: {e}")
    return ok(f"Simulated in {time.time() - t:.1f}s", blocks=B.clean(bl))
@app.post("/api/twin/saved")
async def twin_saved(request: Request):
    u = user_of(request); c = ctx(u); need(c, "view"); d = await request.json(); import twin2 as T2
    s = T2.saved().set_index("name")
    if d.get("a") not in s.index: return bad("unknown scenario")
    a = json.loads(s.loc[d["a"]].args); bl, _ = await asyncio.to_thread(T2.run, c, a); return ok("Re-run on today's data", blocks=B.clean(bl))
@app.post("/api/twin/compare")
async def twin_cmp(request: Request):
    u = user_of(request); c = ctx(u); need(c, "view"); d = await request.json()
    try: return ok("Compared", blocks=B.clean(await asyncio.to_thread(VM.twin_compare, c, d["a"], d["b"])))
    except Exception as e: return bad(f"Could not compare: {e}")
@app.post("/api/twin/propose")
async def twin_propose(request: Request):
    u = user_of(request); c = ctx(u); need(c, "approve"); d = await request.json(); import twin2 as T2
    txt = await asyncio.to_thread(T2.propose, KIND, str(d.get("action", ""))[:200], str(d.get("detail", "")), u["email"]); return ok("Sent to the approval queue (Actions > awaiting approval)", refresh=False)
@app.post("/api/sim/run")
async def sim_run(request: Request):
    u = user_of(request); c = ctx(u); need(c, "view"); d = await request.json(); d.pop("scenario", None); pg = d.pop("page"); t = time.time()
    try: bl = await asyncio.to_thread(VM.sim_run, c, pg, "sim", d)
    except Exception as e: return bad(f"Could not simulate: {e}")
    return ok(f"Simulated in {time.time() - t:.1f}s", blocks=B.clean(bl))

# ------------------------------------------------------------------ data feeds
@app.post("/api/feed/upload")
async def feed_upload(request: Request, file: UploadFile = File(...), table: str = Form(...)):
    u = user_of(request); c = ctx(u); need(c, "feeder")
    if table not in FD.ALLOWED[KIND]: return bad("table not allowed")
    try: df = FD.read_any(file.filename, await file.read()); mp = FD.auto_map(df, table); n, badn = await asyncio.to_thread(FD.ingest, df, table, mp, "upload:" + file.filename)
    except Exception as e: return bad(str(e))
    return ok(f"{n} rows ingested, {badn} rejected. Columns matched: {len(mp)}.", blocks=[B.table(df.head(8), list(df.columns), title="Preview of the file", h=240, key="fprev")])
@app.post("/api/feed/url")
async def feed_url(request: Request):
    u = user_of(request); c = ctx(u); need(c, "feeder"); d = await request.json()
    if d.get("target") not in FD.ALLOWED[KIND] or not str(d.get("url", "")).startswith("http"): return bad("need an http(s) URL and an allowed table")
    with LE._DB_LOCK, LE.conn() as cn: cn.execute("INSERT INTO feed_urls(url,target,every_s,auth_env,json_path) VALUES(?,?,?,?,?)", (d["url"], d["target"], max(30, int(d.get("every", 300))), (d.get("auth_env") or "").strip() or None, (d.get("json_path") or "").strip() or None))
    LE.audit(u["email"], "feed_url", d["target"], d["url"]); return ok("Feed registered", refresh=True)
@app.post("/ingest/{table}")
@app.post("/api/ingest/{table}")
async def ingest_api(table: str, request: Request, x_api_key: str = Header(default=""), idempotency_key: str = Header(default="")):
    import hmac; k = os.environ.get("INGEST_KEY", "")
    if not k or not hmac.compare_digest(x_api_key.encode(), k.encode()): raise HTTPException(401, "bad or missing X-API-Key (set INGEST_KEY)")
    if table == "ais" and KIND == "Freight": table = "vessels"
    if table not in FD.ALLOWED[KIND]: raise HTTPException(400, "table not allowed")
    if idempotency_key and await asyncio.to_thread(FD.seen_key, table + ":" + idempotency_key): return {"accepted": 0, "rejected": 0, "duplicate": True}
    body = await request.body()
    try:
        rows = [json.loads(l) for l in body.decode().splitlines() if l.strip()] if body[:1] not in (b"[", b"{") or b"\n{" in body.strip() else json.loads(body)
        if isinstance(rows, dict): rows = rows.get("rows", [rows])
        if len(rows) > 50000: raise ValueError("max 50,000 rows per request")
        n, badn = await asyncio.to_thread(FD.ingest, pd.DataFrame(rows), table, None, "api:" + table)
    except Exception as e: raise HTTPException(400, str(e))
    return {"accepted": n, "rejected": badn, "note": "rejected rows are listed in Data Feed Center > Quality"}
@app.post("/api/feed/ais_map")
async def feed_ais_map(request: Request):
    u = user_of(request); need(ctx(u), "feeder"); d = await request.json(); pairs = [l.split(",") for l in str(d.get("pairs", "")).splitlines() if "," in l]; FD.init()
    with LE._DB_LOCK, LE.conn() as cn: cn.executemany("INSERT OR REPLACE INTO ais_map VALUES(?,?)", [(a.strip(), b.strip()) for a, b in pairs])
    LE.audit(u["email"], "ais_map", "vessels", f"{len(pairs)} ids"); return ok(f"{len(pairs)} MMSI to shipment links saved", refresh=True)
@app.get("/api/feed/rejects.csv")
async def feed_rejects(request: Request):
    u = user_of(request); need(ctx(u), "feeder"); FD.init(); df = B.Q("SELECT * FROM feed_rejects ORDER BY id DESC LIMIT 5000")
    return Response(df.to_csv(index=False), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="rejected_rows.csv"'})
@app.post("/api/gov/purge")
async def gov_purge(request: Request):
    u = user_of(request); need(ctx(u), "admin"); d = await request.json(); dry = str(d.get("mode", "dry")) != "run"; rows = await asyncio.to_thread(PV.purge, dry, u["email"])
    return ok(("Dry run: nothing deleted. " if dry else "Purged. ") + f"{sum(r['older_rows'] for r in rows):,} rows past retention.", blocks=[B.table(rows, ["table", B.num_col("keep_days", "keep (days)", "int"), B.num_col("older_rows", "past retention", "int"), B.num_col("deleted", "deleted", "int")], h=300, key="gv_p")])
@app.post("/api/gov/retention")
async def gov_retention(request: Request):
    u = user_of(request); need(ctx(u), "admin"); d = await request.json(); cur = PV.policy()
    try: cur[str(d["table"])] = max(7, int(d["days"]))
    except Exception: return bad("table and days (min 7) required")
    if d["table"] not in PV.RETENTION: return bad("unknown table")
    LE.set_state("retention", cur); LE.audit(u["email"], "retention_set", d["table"], str(d["days"])); return ok("Retention updated", refresh=True)
@app.post("/api/gov/dsar")
async def gov_dsar(request: Request):
    u = user_of(request); need(ctx(u), "admin"); d = await request.json(); key = str(d.get("subject", "")).strip(); act = d.get("action", "export")
    if not key: return bad("enter a staff id or a login email")
    if act == "erase":
        n = await asyncio.to_thread(PV.erase_subject, key, u["email"]); return ok("Erased / anonymised: " + json.dumps(n))
    data = await asyncio.to_thread(PV.export_subject, key); LE.audit(u["email"], "dsar_export", PV._hash(key), ",".join(data))
    return ok(f"{sum(len(v) for v in data.values())} records found" if data else "Nothing held for this subject.", blocks=[B.md("```\n" + json.dumps(data, indent=1, default=str)[:6000] + "\n```")] if data else [])

# ------------------------------------------------------------------ Franchise actions
@app.post("/api/franchise/review")
async def fr_review(request: Request):
    import uuid; u = user_of(request); c = ctx(u); need(c, "review"); d = await request.json(); tx = str(d.get("comment", "")).strip(); rbac.own_outlet(c, d.get("outlet"))
    if not tx: return bad("Write a comment first")
    src = gpu.detect(tx); en = PV.redact(gpu.translate(tx, "eng_Latn", src)[0] if src != "eng_Latn" else tx)
    try: from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer; sc = SentimentIntensityAnalyzer().polarity_scores(en)["compound"]
    except Exception: sc = (int(d["rating"]) - 3) / 2
    rt = int(d["rating"])
    with LE._DB_LOCK, LE.conn() as cn: cn.execute("INSERT INTO feedback(feedback_id,outlet_id,rating,comment,date,sentiment_score) VALUES(?,?,?,?,?,?)", ("FB-U" + uuid.uuid4().hex[:10], d["outlet"], rt, en, datetime.date.today().isoformat(), .6 * (rt - 3) / 2 + .4 * sc))
    LE.emit("review", d["outlet"], {"rating": rt}); return ok(f"Stored for {d['outlet']} (sentiment {sc:+.2f}{', translated from ' + src if src != 'eng_Latn' else ''}). The Sentiment agent includes it in its next cycle.", refresh=True)
@app.post("/api/franchise/audit")
async def fr_audit(request: Request):
    import uuid; u = user_of(request); c = ctx(u); need(c, "resolve"); d = await request.json(); rbac.own_outlet(c, d.get("outlet")); sc = int(d["score"])
    with LE._DB_LOCK, LE.conn() as cn: cn.execute("INSERT INTO audits(audit_id,outlet_id,audit_date,score,violations,category,status,notes) VALUES(?,?,?,?,?,?,?,?)", ("AUD-U" + uuid.uuid4().hex[:10], d["outlet"], datetime.date.today().isoformat(), sc, int((100 - sc) / 6), d["category"], "Pass" if sc >= 80 else "Warning" if sc >= 60 else "Fail", d.get("notes", "")))
    LE.emit("audit", d["outlet"], {"score": sc}); LE.audit(u["email"], "audit_logged", d["outlet"], str(sc)); await asyncio.to_thread(_run_one, "audit"); return ok("Saved and evaluated by the Audit agent.", refresh=True)

# ------------------------------------------------------------------ language, knowledge base
@app.post("/api/translate_batch")
async def translate_batch(request: Request):
    _cop(request); d = await request.json(); texts = [str(t)[:700] for t in d.get("texts", [])[:400]]; out, err = await asyncio.to_thread(gpu.translate_many, texts, d.get("lang", "eng_Latn")); return {"out": out, "err": err}
@app.post("/api/translate_doc")
async def translate_doc(request: Request):
    _cop(request); data = ""; text = ""; lang = "Hindi (हिंदी)"
    if "json" in request.headers.get("content-type", ""):
        j = await request.json(); text = str(j.get("text", "")); lang = j.get("lang", lang)
    else:
        fm = await request.form(); text = str(fm.get("text", "") or ""); lang = fm.get("lang", lang); file = fm.get("file")
        if file is not None and getattr(file, "filename", ""):
            try: data = rag.read_pdf(file.filename, await file.read())
            except Exception as e: return bad(f"Could not read the file: {e}")
    t = (data or text).strip()
    if not t: return bad("Paste text or choose a file")
    src = gpu.detect(t); t0 = time.time(); out, err = await asyncio.to_thread(gpu.translate, t[:20000], gpu.code_of(lang), src)
    if err: return bad(err)
    return ok(f"Translated from {src} to {gpu.code_of(lang)} in {time.time() - t0:.1f}s on {gpu.S['models']['nllb']['device']}", blocks=[B.card("Translation", B.md(out))])
@app.post("/api/kb/upload")
async def kb_upload(request: Request, file: UploadFile = File(...)):
    u = _cop(request)
    try: txt = rag.read_pdf(file.filename, await file.read())
    except Exception as e: return bad(f"Could not read the file: {e}")
    n = await asyncio.to_thread(rag.add, file.filename, "uploaded by you", txt, u["email"]); LE.audit(u["email"], "kb_upload", file.filename, f"{n} chunks"); return ok(f"{n} passages indexed ({gpu.S['models']['embed']['device'] or 'tf-idf'}).", refresh=True)
@app.post("/api/kb/search")
async def kb_search(request: Request):
    u = _cop(request); d = await request.json(); q = d.get("q", ""); mode = {"BM25 only": "bm25", "Dense only": "dense"}.get(d.get("mode"), "hybrid"); t0 = time.time()
    hits = await asyncio.to_thread(rag.search, q, u["email"], 6, mode, True)
    if d.get("live", "no") in ("yes", True): hits += await asyncio.to_thread(rag.live_hits, q, 4)
    return ok(f"{len(hits)} passage(s) in {(time.time() - t0) * 1000:.0f} ms", blocks=[B.card(f"{h['title']} · {h['source']}", B.md(h["text"]), sub=f"score {h['score']} · {h.get('why', '')}") for h in hits] or [B.callout("Nothing relevant found.", "info")])
@app.post("/api/kb/drive")
async def kb_drive(request: Request):
    u = user_of(request); need(ctx(u), "admin"); n = await asyncio.to_thread(rag.import_drive); LE.audit(u["email"], "kb_drive_import", rag.drive_dir(), f"{n} chunks")
    return ok(f"{n} chunks loaded from your Drive RAG index ({rag.drive_dir()})" if n else f"Nothing found in {rag.drive_dir()}/synthetic_kb. Mount Drive and run your RAG builder first.", refresh=True)
@app.get("/api/kb/export")
async def kb_export(request: Request):
    u = _cop(request); data = await asyncio.to_thread(rag.export_json, u["email"]); return JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="kb_export.json"'})
@app.post("/api/kb/import")
async def kb_import(request: Request, file: UploadFile = File(...)):
    u = _cop(request)
    try: n, same = await asyncio.to_thread(rag.import_json, json.loads(await file.read()), u["email"])
    except Exception as e: return bad(f"Could not import: {e}")
    LE.audit(u["email"], "kb_import", file.filename, f"{n} chunks"); return ok(f"{n} passages imported" + (" with their embeddings." if same else "; embeddings will be recomputed on the GPU."), refresh=True)
@app.post("/api/kb/eval")
async def kb_eval(request: Request):
    u = user_of(request); need(c := ctx(u), "view"); rows = await asyncio.to_thread(rag.evaluate, KIND)
    return ok("Evaluated", blocks=[B.table(rows, ["method", B.num_col("recall@1", "recall@1", "num"), B.num_col("recall@3", "recall@3", "num"), B.num_col("MRR", "MRR", "num"), "note"], title="Retrieval quality on the built-in question set", h=240, key="kb_ev"), B.callout("This question set is small and written alongside the sample documents, so scores are optimistic. Use the builder notebook to evaluate on your own corpus and questions.", "info")])

# ------------------------------------------------------------------ Copilot (agents first, then the GPU LLM; NLLB for every language) + executive brief
def _sse(ev, **kw): return f"data: {json.dumps({'ev': ev, **kw}, default=str)}\n\n"
INSIGHT_SYS = "You are the operations copilot. An EXACT RESULT from the database is given in the EVIDENCE: do not repeat it or its table. In at most two short sentences add the most useful insight or next action, using the agent findings and the numbered sources when they help. Use only numbers that appear in the EVIDENCE. Cite a source as [1] when you use it. If you have nothing useful to add, answer exactly: NONE"
SYSTEM = "You are the operations copilot of an agentic platform. Answer ONLY from the EVIDENCE. FORMAT RULES: reply in exactly this layout and nothing else. Line 1: '**Answer:** ' plus one sentence of at most 25 words. Then up to 3 numbered points ('1. ...'), each at most 20 words, one fact each, with entity ids when the evidence has them. Last line, only if the evidence supports an action: '**Next step:** ' plus one short action. Quote numbers exactly as given and never invent any. Cite every fact that comes from a numbered source as [1], [2] matching the SOURCES list; facts from the database or the agents need no citation. If the evidence does not answer the question, reply exactly: I do not have that in the data or documents yet."
def _nums_ok(ans, ev):
    ans = re.sub(r"\[\d{1,2}\]|(?m:^\s*\d{1,2}[.)]\s)", " ", ans)        # citation markers and list numbering are not data
    have = set(re.findall(r"\d+(?:\.\d+)?", ev)); return all(n in have for n in re.findall(r"\d+(?:\.\d+)?", ans))
import copilot_pro as CP
CP_EXAMPLES = ["Which outlets are at highest risk?", "Why is OUT-007 flagged?", "How is inventory holding up?", "Top 5 outlets by revenue"] if KIND == "Franchise" else ["Mumbai to Singapore 50 t electronics: days, cost and best route", "Which port has the highest congestion?", "How many shipments are on customs hold?", "Quotes with margin below 10%"]
@app.post("/api/copilot")
async def copilot(request: Request):
    u = user_of(request); c = ctx(u); need(c, "copilot"); d = await request.json(); q = str(d.get("q", ""))[:800]; lang = d.get("lang", "English"); tgt = gpu.code_of(lang); SID = u["email"] + ":" + str(d.get("sid") or "default")[:40]
    sc_, mask_ = c.get("scope") or None, rbac.masked(c["role"])           # the Copilot only reads what this role may see: own outlet only for Store Manager and Staff, no salary or personal data for Staff and Auditor
    def _others(txt): return sorted({m.upper() for m in rbac.OUTLET_RE.findall(str(txt))} - {sc_}) if sc_ else []
    def gen():
        t0 = time.time(); src = gpu.detect(q); en = q
        if _others(q): yield _sse("final", text=f"{', '.join(_others(q))} is outside your outlet scope ({sc_}). Ask about {sc_} instead.", sql="", ms=0); yield _sse("done"); return
        if src != "eng_Latn":
            en, err = gpu.translate(q, "eng_Latn", src); yield _sse("stage", text=f"Detected {src}; translated to English with NLLB-200 on {gpu.S['models']['nllb']['device'] or 'cpu'}")
        dec = VC.decision(); exact = None
        if sc_ or mask_: dec = None                                            # the agents' narrative and findings are chain-wide: a scoped or masked role never gets them
        direct, en, pres, notes, pids = CP.prepare(KIND, en, SID, dom, VC.decision, CP_EXAMPLES, sc_, mask_)
        if notes: yield _sse("note", text=" · ".join(notes))
        if direct:
            txt = direct["text"]
            if tgt != "eng_Latn": txt = gpu.translate(txt, tgt, "eng_Latn")[0]
            CP.log_turn(q, direct.get("route", "chat"), round((time.time() - t0) * 1000))
            yield _sse("final", text=txt, sql=direct.get("sql", ""), sugg=direct.get("sugg"), en=(direct["text"] if tgt != "eng_Latn" else None), lang=lang, ms=round((time.time() - t0) * 1000), tok_s=gpu.S["stats"]["tok_s"]); yield _sse("done"); return
        analytic = bool(re.search(r"\b(why|explain|reason|recommend|should|suggest|advise|what to do|how can|how do|improve|summar)", en, re.I))
        try: exact = pres or AN.answer(KIND, en, sc_, dec, dom, mask_) or QA.answer(KIND, en, sc_, mask_)
        except Exception as e: print("qa failed:", repr(e), file=sys.stderr)
        if exact and exact.get("answer") and sc_ and _others(exact["answer"] + (QA.md(exact["df"]) if exact.get("df") is not None else "") + str(exact.get("extra") or "")):
            exact = {"answer": f"That answer would include other outlets, which your role cannot see. Ask about {sc_} instead.", "sql": "", "df": None}; pres = None       # safety net for any intent that forgets the scope
        try:
            if exact and exact.get("answer") and CP.is_knowledge_q(en) and CP.weak_match(en, exact): exact = None; pres = None; yield _sse("stage", text="That table does not match the question, so it is not shown. Looking in the knowledge base instead…")
        except Exception: pass
        fast = bool(exact and exact.get("answer") and (not analytic or exact.get("complete")))
        trace = []
        kno = bool(not (exact and exact.get("answer")) and not pids and (CP.is_knowledge_q(en) or CP.is_term_q(en)))
        if (sc_ or mask_) and not fast and not kno: planned = []; dd = {"narrative": "", "actions": [], "agents": {}}; yield _sse("stage", text="Your role sees its own outlet and the documents only, so the chain-wide agents are not used.")
        elif fast:
            planned = dom.plan(en); dd = {"narrative": dec["narrative"], "actions": [], "agents": dec["ev"].get("agents", {})} if dec else {"narrative": "", "actions": [], "agents": {}}
            trace = [{"agent": k, "risk": v["risk"], "score": v["score"], "finding": v["summary"][:160]} for k, v in dd.get("agents", {}).items() if k in planned]
            if trace: yield _sse("trace", rows=trace)
        elif kno:
            planned = []; dd = {"narrative": "", "actions": [], "agents": {}}; yield _sse("stage", text="Knowledge question: searching the documents (agents skipped).")
        else:
            planned = dom.plan(en); yield _sse("stage", text="Planner selected: " + ", ".join(planned))
            stale = (not dec) or (datetime.datetime.now() - datetime.datetime.fromisoformat(dec["ts"])).total_seconds() > 300      # the worker refreshes the agents every 60 s: reuse its latest results
            if stale:
                yield _sse("stage", text="Running the selected agents and the Intelligence Engine…"); dd = LE.run_cycle(dom, "copilot", en)
            else: dd = {"narrative": dec["narrative"], "actions": [], "agents": dec["ev"].get("agents", {})}
            yield _sse("stage", text=f"Agents ready in {time.time() - t0:.1f}s")
            trace = [{"agent": k, "risk": v["risk"], "score": v["score"], "finding": v["summary"][:160]} for k, v in dd.get("agents", {}).items() if k in planned]
            if trace: yield _sse("trace", rows=trace)
        if exact and exact.get("answer"):
            yield _sse("stage", text="Exact answer from your live data (read-only query)"); yield _sse("exact", sql=exact["sql"], rows=0 if exact["df"] is None else len(exact["df"]))
        planned = locals().get("planned") or []
        facts = [] if (fast or kno or sc_ or mask_) else EN.facts(KIND, dom, en); sql_fact = ""
        if not (fast or kno or sc_ or mask_):
            try: from intent_router import run_grounded_query; sql_fact, _ = run_grounded_query(en)
            except Exception: pass
        kb = (CP.relevant(en, rag.search(en, u["email"], 3, "hybrid", False)) if fast else (rag.search(en, u["email"], 4, "hybrid", gpu.llm_ready()) + ([] if (sc_ or mask_) else rag.live_hits(en, 2)))); acts = dd.get("actions", [])[:8]
        if kb: yield _sse("cites", rows=[{"n": n + 1, "title": h["title"], "source": h["source"], "why": h.get("why", ""), "score": h["score"], "text": h["text"][:240]} for n, h in enumerate(kb)])
        _k0 = None
        if kno and kb and tgt == "eng_Latn":
            _k0 = CP.kb_answer(en, [h for h in kb if h.get("via") != "live"])
            if _k0: yield _sse("partial", text=_k0)                      # instant extractive answer; a model answer replaces it only for how/why/explain questions
        ev = (f"EXACT RESULT (from the database, authoritative): {exact['answer']}\n{QA.md(exact['df'])}\n" if exact and exact.get("answer") else "") + f"{dd.get('narrative', '')} Top actions: " + " | ".join(f"{a['type']} {a['target']} ({a.get('severity')}): {a['detail']}" for a in acts) + (" Entities: " + " ".join(facts) if facts else "") + (f" Data lookup: {str(sql_fact)[:900]}" if sql_fact else "") + (" Sources: " + " ".join(f"[{n + 1}] ({h['title']}) {h['text'][:320]}" for n, h in enumerate(kb)) if kb else "")
        EXAMPLES = ["Which outlets are at highest risk?", "Why is OUT-007 flagged?", "How is inventory holding up?", "Top 5 outlets by revenue"] if KIND == "Franchise" else ["Mumbai to Singapore 50 t electronics: days, cost and best route", "Which port has the highest congestion?", "How many shipments are on customs hold?", "Quotes needing approval"]
        fallback = ("I do not know. I could not compute an exact answer to that from the tables, so I will not guess a number. What the agents responsible for this question found:\n" + "\n".join(f"- **{t['agent']}** ({t['risk']}): {t['finding']}" for t in trace if t["agent"] in planned) + (("\n\nRelated knowledge: " + "; ".join(h["title"] for h in kb[:3])) if kb else "") + "\n\nTry asking, for example: " + "; ".join(f'"{x}"' for x in EXAMPLES) + ".")
        ans = ""
        insight = False; _deco = None
        if exact and exact.get("answer"):
            _tb0 = (QA.md(exact["df"]) if exact.get("df") is not None else "") + (("\n\n" + exact["extra"]) if exact.get("extra") else "")
            if tgt == "eng_Latn": yield _sse("partial", text=exact["answer"] + (("\n\n" + _tb0) if _tb0 else ""))
            try:
                _deco = CP.decorate(KIND, SID, en, exact, pids)
                if _deco[0]: yield _sse("chart", block=_deco[0])
            except Exception as e: print("decorate failed:", repr(e), file=sys.stderr)
        _rows = 0 if not exact or exact.get("df") is None else len(exact["df"])
        if exact and exact.get("answer") and (not analytic or exact.get("complete")):
            if gpu.llm_ready() and analytic:
                yield _sse("stage", text=f"Writing the insight on {gpu.S['models']['llm']['device']} ({gpu.S['models']['llm']['name']})…")
                for piece in gpu.llm_stream([{"role": "system", "content": INSIGHT_SYS}, {"role": "user", "content": f"EVIDENCE:\n{ev[:2200]}\n\nQUESTION: {en}"}], max_new_tokens=70, temperature=0.0): ans += piece
                ans = ans.strip()
                if ans.upper().startswith("NONE") or len(ans) < 12 or not CP.sane(ans) or not _nums_ok(ans, ev): ans = ""
                else: ans = "**Insight:** " + ans; insight = True; yield _sse("tok", text=ans)
            elif not gpu.llm_ready(): yield _sse("stage", text="LLM not loaded (" + str(gpu.S["models"]["llm"]["state"]) + "): this answer uses SQL, the latest agent findings and the knowledge base only.")
        elif gpu.llm_ready() and not (kno and _k0 and not analytic):
            _tok_ok = False
            if fallback and tgt == "eng_Latn" and not exact: yield _sse("draft", text=fallback)      # shows the agents' findings at once; the model answer replaces it
            yield _sse("stage", text=f"Generating on {gpu.S['models']['llm']['device']} ({gpu.S['models']['llm']['name']})…")
            for piece in gpu.llm_stream([{"role": "system", "content": SYSTEM + (" An EXACT RESULT is given: start from it, do not contradict it, and add only the reasoning or advice asked for." if exact else "")}, {"role": "user", "content": f"EVIDENCE:\n{ev[:2200]}\n\nQUESTION: {en}"}], max_new_tokens=150, temperature=0.0):
                ans += piece
                if not _tok_ok:
                    if len(ans) >= 16:
                        if CP.sane(ans): _tok_ok = True; yield _sse("tok", text=ans)
                        else: break                                         # garbage from the model: stop and fall back to the evidence
                else: yield _sse("tok", text=piece)
            if not CP.sane(ans): ans = ""
            if not _nums_ok(ans, ev): yield _sse("stage", text="The model used a number that is not in the evidence: showing the evidence summary instead."); ans = ""
        else: yield _sse("stage", text="LLM not loaded (" + str(gpu.S["models"]["llm"]["state"]) + (": " + gpu.S["models"]["llm"]["err"] if gpu.S["models"]["llm"]["err"] else "") + "): answering from agent evidence.")
        if re.match(r"^\W*(no evidence|\[no evidence|i do not have that in the data)", ans.strip(), re.I) or len(ans.strip()) < 12: ans = ""
        llm_used = bool(ans.strip())
        if llm_used and not insight: ans = CP.finish(ans, kb)
        kba = None; kgap = False
        if not ans.strip() and not (exact and exact.get("answer")):
            kba = CP.kb_answer(en, [h for h in kb if h.get("via") != "live"])
            if kba: ans = kba
            elif (CP.is_knowledge_q(en) or CP.is_term_q(en)) and not pids:
                ans = "I do not know. There is no document on that topic in the knowledge base yet, and the database has no numbers for it. Add documents with the RAG notebook or in AI Copilot → Knowledge base, then ask again."; kgap = True; CP.unanswered_note(q)
        ans = ans.strip() or (fallback if not (exact and exact.get("answer")) else "")
        tbl = (QA.md(exact["df"]) if exact and exact.get("df") is not None else "") + (("\n\n" + exact["extra"]) if exact and exact.get("extra") else ""); lead = exact["answer"] if exact and exact.get("answer") else ""
        ans_en = (lead + ("\n\n" + ans if ans else "")).strip()
        if exact and exact.get("answer") and exact.get("sql"):              # Milestone 2: every exact answer says how many rows its read-only SQL query returned
            _n = 0 if exact.get("df") is None else len(exact["df"]); tbl += ("\n\n" if tbl else "") + "**%d row%s** returned by a read-only SQL query. Open \"Show the exact query\" to see it." % (_n, "" if _n == 1 else "s")
        if not (exact and exact.get("answer")) and (kgap or ans_en.startswith(("I do not know", "I could not compute"))):      # Milestone 2: the polite fallback names three questions the Copilot can answer
            ans_en += "\n\nTry one of these questions:\n" + "\n".join("- " + e_ for e_ in intents.suggestions(sc_, q))
        final = ans_en + (("\n\n" + tbl) if tbl else "")
        if tgt != "eng_Latn":
            tr, err = gpu.translate(ans_en, tgt, "eng_Latn"); final = tr + (("\n\n" + tbl) if tbl else ""); yield _sse("stage", text=f"Translated to {lang} with NLLB-200" + (f" (failed: {err})" if err else ""))
        _drv = False
        try: _drv = os.path.isdir(rag.drive_dir())
        except Exception: pass
        yield _sse("layers", sql=bool(exact and exact.get("answer")), agents=len(trace), rag=len([h for h in kb if h.get("via") != "live"]), llm=llm_used, llm_state=str(gpu.S["models"]["llm"]["state"]), drive=_drv, kb_hit=bool(kba))
        cb, sg, has = None, ["What can you do?", "Briefing"], False
        if exact and exact.get("answer"):
            cb, sg, has = _deco or CP.decorate(KIND, SID, en, exact, pids); CP.log_turn(q, "exact" if fast or not analytic else "exact+llm", round((time.time() - t0) * 1000))
            if cb and not _deco: yield _sse("chart", block=cb)
        elif ans_en.strip().startswith(("I do not know", "I could not compute")): CP.unanswered_note(q); CP.log_turn(q, "unanswered", round((time.time() - t0) * 1000))
        else: CP.log_turn(q, "knowledge" if kba else ("unanswered" if kgap else "agents+llm"), round((time.time() - t0) * 1000))
        if sc_ and _others(final): final = f"That answer would include other outlets, which your role cannot see. Ask about {sc_} instead."; ans_en = final
        yield _sse("final", text=final, sugg=sg, csv=has, rows=(0 if not exact or exact.get("df") is None else len(exact["df"])), sql=(exact or {}).get("sql", ""), en=((ans_en + (("\n\n" + tbl) if tbl else "")) if tgt != "eng_Latn" else None), lang=lang, ms=round((time.time() - t0) * 1000), tok_s=gpu.S["stats"]["tok_s"]); yield _sse("done")
    _ck = (u["role"], str(c.get("scope") or ""), str(u.get("email")) if mask_ else "", tgt, re.sub(r"\s+", " ", q.lower()).strip(" ?!."))
    _fu = bool(re.search(r"^(and|also|what about|how about|then|those|same)\b|\b(it|its|them|those|that one|this one)\b", q.lower()))
    def gen_cached():
        hit = _RC.get(_ck)
        if hit and not _fu and time.time() - hit[0] < hit[2]:
            t1 = time.time()
            try: CP.prepare(KIND, q, SID, dom, VC.decision, CP_EXAMPLES, sc_, mask_)      # keeps follow-up context
            except Exception: pass
            yield _sse("stage", text=f"Instant answer: the same question was answered {int(time.time() - hit[0])} s ago (refreshes automatically).")
            for e_ in hit[1]: yield _sse(e_["ev"], **{k_: v_ for k_, v_ in e_.items() if k_ != "ev"}) if e_["ev"] != "final" else _sse("final", **{**{k_: v_ for k_, v_ in e_.items() if k_ != "ev"}, "ms": round((time.time() - t1) * 1000), "cached": True})
            return
        rec = []
        for s_ in gen():
            yield s_
            try:
                e_ = json.loads(s_[6:])
                if e_.get("ev") not in ("stage", "tok"): rec.append(e_)
            except Exception: pass
        if any(e_.get("ev") == "layers" for e_ in rec) and any(e_.get("ev") == "final" for e_ in rec):
            if len(_RC) > 200: _RC.clear()
            _lay = next((e_ for e_ in rec if e_.get("ev") == "layers"), {}); _RC[_ck] = (time.time(), rec, 600 if (not _lay.get("sql") and not _lay.get("agents")) else 60)      # document answers do not depend on live data: keep 10 min
    return StreamingResponse(gen_cached(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
_BRIEF = {}
_RC = {}
def _chat_db():
    c = sqlite3.connect(DB_PATH, timeout=30); c.execute("PRAGMA journal_mode=WAL;"); c.execute("CREATE TABLE IF NOT EXISTS copilot_chats(id TEXT PRIMARY KEY, email TEXT, title TEXT, ts TEXT, data TEXT)"); c.execute("CREATE INDEX IF NOT EXISTS ix_chat_email ON copilot_chats(email, ts)"); return c
@app.get("/api/chats")
async def chats_list(request: Request):
    u = _cop(request)
    with _chat_db() as c: rows = c.execute("SELECT id, title, ts FROM copilot_chats WHERE email=? ORDER BY ts DESC LIMIT 60", (u["email"],)).fetchall()
    return {"ok": True, "chats": [{"id": r[0], "title": r[1], "ts": r[2]} for r in rows]}
@app.get("/api/chats/{cid}")
async def chats_get(cid: str, request: Request):
    u = _cop(request)
    with _chat_db() as c: r = c.execute("SELECT title, data FROM copilot_chats WHERE id=? AND email=?", (cid, u["email"])).fetchone()
    if not r: raise HTTPException(404, "chat not found")
    return {"ok": True, "title": r[0], "msgs": json.loads(r[1])}
@app.post("/api/chats/save")
async def chats_save(request: Request):
    u = _cop(request); d = await request.json(); cid = re.sub(r"[^a-zA-Z0-9_-]", "", str(d.get("id") or ""))[:40] or ("c" + str(int(time.time() * 1000))); msgs = d.get("msgs") or []
    if not isinstance(msgs, list) or not msgs: return bad("nothing to save")
    msgs = [{"role": m.get("role"), "text": str(m.get("text", ""))[:20000], "en": (str(m["en"])[:20000] if m.get("en") else None), "lang": m.get("lang"), "sql": str(m.get("sql") or "")[:1500]} for m in msgs[-80:]]
    title = next((m["text"] for m in msgs if m["role"] == "user"), "Chat")[:70]; now = datetime.datetime.now().isoformat(timespec="seconds")
    with _chat_db() as c:
        o = c.execute("SELECT email FROM copilot_chats WHERE id=?", (cid,)).fetchone()
        if o and o[0] != u["email"]: raise HTTPException(403, "not your chat")
        c.execute("INSERT OR REPLACE INTO copilot_chats VALUES(?,?,?,?,?)", (cid, u["email"], title, now, json.dumps(msgs)))
    PS.soon()
    return {"ok": True, "id": cid}
@app.delete("/api/chats/{cid}")
async def chats_del(cid: str, request: Request):
    u = _cop(request)
    with _chat_db() as c: c.execute("DELETE FROM copilot_chats WHERE id=? AND email=?", (cid, u["email"]))
    return {"ok": True}
@app.post("/api/weather/refresh")
async def wx_refresh(request: Request):
    u = user_of(request); c = ctx(u); need(c, "run")
    if KIND != "Freight": raise HTTPException(404)
    import weather as WX; n, msg = await asyncio.to_thread(WX.refresh); LE.audit(u["email"], "weather_refresh", "ports", msg)
    return ok(("Real weather updated: " if n else "Could not reach Open-Meteo, simulated values stay: ") + msg, refresh=True)
@app.post("/api/brief")
async def brief(request: Request):
    u = user_of(request); _c = ctx(u); need(_c, "view"); d = await request.json(); lang = d.get("lang", "English"); tgt = gpu.code_of(lang); dec = VC.decision()
    def gen():
        if _c.get("scope") or rbac.masked(_c["role"]): yield _sse("final", text="The executive brief covers the whole chain and is not available for your role."); return
        if not dec: yield _sse("final", text="No decision yet."); return
        key = (dec["id"], tgt)
        if key in _BRIEF: yield _sse("final", text=_BRIEF[key]); return
        ev = json.dumps({k: v for k, v in dec["ev"].items() if k != "agents"}, default=str)[:1500] + " Agents: " + json.dumps(dec["ev"].get("agents", {}), default=str)[:1800]; txt = ""
        if gpu.llm_ready():
            for piece in gpu.llm_stream([{"role": "system", "content": "Write a 4-line executive briefing for the owner: status, biggest risk, what to approve now, what to watch. Use only numbers present in the data."}, {"role": "user", "content": ev}], max_new_tokens=200): txt += piece; yield _sse("tok", text=piece)
            if not _nums_ok(txt, ev): txt = ""
        txt = txt.strip() or dec["narrative"]; out = gpu.translate(txt, tgt, "eng_Latn")[0] if tgt != "eng_Latn" else txt; _BRIEF[key] = out; yield _sse("final", text=out)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ------------------------------------------------------------------ reports, exports, profile, invitations
@app.get("/api/report/{rid}")
async def report(rid: str, request: Request, arg: str = ""):
    u = user_of(request); c = ctx(u)
    rbac.need_page(c, "reports")
    if c["scope"] and arg and not arg.startswith(c["scope"]) and rid == "fr_outlet": raise HTTPException(403, "outside your outlet")
    try: name, data = await asyncio.to_thread(RP.build_pdf, KIND, rid, c, arg or None)
    except KeyError: raise HTTPException(404, "unknown report")
    LE.audit(u["email"], "report", rid, arg); return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})
@app.post("/api/report/email")
async def report_email(request: Request):
    u = user_of(request); c = ctx(u); d = await request.json(); rid = d.get("rid")
    rbac.need_page(c, "reports")
    try: name, data = await asyncio.to_thread(RP.build_pdf, KIND, rid, c, d.get("arg") or None)
    except KeyError: return bad("unknown report")
    okk, msg = await asyncio.to_thread(mailer.send, u["email"], f"{V.NAME}: {name}", "Your report is attached. It was generated from the live data by the agent network.", [(name, data, "application/pdf")])
    LE.audit(u["email"], "report_email", rid, msg); return {"ok": okk, "msg": msg}
@app.get("/api/export/{table}.csv")
def export(table: str, request: Request):
    u = user_of(request); c = ctx(u)
    rbac.need_page(c, "reports")
    if table not in RP.EXPORTS[KIND]: raise HTTPException(404)
    LE.audit(u["email"], "export", table); return Response(RP.export_csv(KIND, table, c["scope"]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{table}.csv"'})
@app.get("/api/backup")
def backup(request: Request):
    import sqlite3, tempfile; u = user_of(request); c = ctx(u); need(c, "admin")
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); src = sqlite3.connect(DB_PATH); dst = sqlite3.connect(p); src.backup(dst); dst.close(); src.close()
    data = open(p, "rb").read(); os.remove(p); LE.audit(u["email"], "backup", DB_PATH); return Response(data, media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{os.path.basename(DB_PATH)}"'})

@app.get("/api/health")
def health(): return {"ok": True, "gpu": gpu.status()}
@app.get("/")
def index(): return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-store"})
app.mount("/static", StaticFiles(directory=STATIC), name="static")

@app.get("/api/copilot/suggest")
def copilot_suggest(request: Request, q: str = ""):
    _cop(request); return {"items": CP.suggest(q[:80], CP_EXAMPLES)}
@app.get("/api/copilot/csv")
def copilot_csv(request: Request, sid: str = "default"):
    from fastapi.responses import Response
    u = _cop(request); t = CP.last_csv(u["email"] + ":" + sid[:40])
    if t is None: raise HTTPException(404, "nothing to export yet")
    return Response(t, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=copilot_result.csv"})
@app.post("/api/copilot/feedback")
async def copilot_feedback(request: Request):
    _cop(request); d = await request.json(); CP.feedback(str(d.get("q", "")), bool(d.get("helpful"))); return {"ok": True}
# ------------------------------------------------------------------ teach the Copilot (admin): find unanswered questions, add the answers
@app.post("/api/copilot/teach")
async def teach_add(request: Request):
    u = user_of(request); need(ctx(u), "admin"); d = await request.json()
    i = await asyncio.to_thread(CP.teach, d.get("question", ""), d.get("answer", ""), d.get("keywords", ""), u["email"])
    if not i: return bad("Give a question (4+ characters) and an answer (10+ characters).")
    LE.audit(u["email"], "copilot_teach", str(d.get("question", ""))[:80], "taught"); st = CP.teach_stats(); return ok(f"Saved. The Copilot will now answer this, and rephrased versions of it. {st['taught']} taught so far.", refresh=True)
@app.post("/api/copilot/teach/delete")
async def teach_delete(request: Request):
    u = user_of(request); need(ctx(u), "admin"); d = await request.json(); CP.taught_del(int(d.get("id", 0))); return ok("Removed.", refresh=True)
@app.post("/api/copilot/teach/import")
async def teach_import(request: Request, file: UploadFile = File(...)):
    u = user_of(request); need(ctx(u), "admin"); import csv as _csv, io as _io
    try: rows = list(_csv.DictReader(_io.StringIO((await file.read()).decode("utf-8-sig", errors="ignore"))))
    except Exception as e: return bad(f"Could not read the CSV: {e}")
    n = 0; skipped = 0
    for r in rows[:500]:
        r = {str(a or "").strip().lower(): (b or "") for a, b in r.items()}
        if await asyncio.to_thread(CP.teach, r.get("question") or r.get("q", ""), r.get("answer") or r.get("a", ""), r.get("keywords", ""), u["email"]): n += 1
        else: skipped += 1
    LE.audit(u["email"], "copilot_teach_import", file.filename, f"{n} taught"); return ok(f"{n} question(s) taught" + (f", {skipped} row(s) skipped (need question + answer columns)" if skipped else "") + f". {CP.teach_stats()['taught']} taught in total.", refresh=True)
@app.get("/api/copilot/teach/export")
async def teach_export(request: Request):
    u = user_of(request); need(ctx(u), "admin"); import csv as _csv, io as _io
    o = _io.StringIO(); w = _csv.writer(o); w.writerow(["question", "answer", "keywords", "added_by", "when"])
    for r in CP.taught_rows(): w.writerow([r["question"], r["answer"], r["keywords"], r["by"], r["when"]])
    return Response(o.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="taught_questions.csv"'})
@app.post("/api/copilot/probe")
async def copilot_probe(request: Request):
    """Runs a list of questions (one per line) through the real Copilot and reports which ones it could not answer. Unanswered ones land in the backlog."""
    u = user_of(request); need(ctx(u), "admin"); d = await request.json()
    qs = [re.sub(r"^\s*(\d+[.)]|[-*])\s*", "", x).strip() for x in str(d.get("questions", "")).splitlines()]; qs = [x for x in dict.fromkeys(qs) if len(x) > 3][:25]
    if not qs: return bad("Paste at least one question, one per line.")
    import hardening as _hd
    _sp = (request.scope.get("server") or (None, None))[1]; ports = [x for x in dict.fromkeys([_sp, int(os.environ.get("PORT", 0) or 0) or None, 8000, request.url.port]) if x]
    cookie = request.headers.get("cookie", ""); auth = request.headers.get("authorization", "")
    def run():
        import requests as _rq; out = []; base = None
        for pt in ports:                                              # find the port this server really listens on
            try:
                if _rq.get(f"http://127.0.0.1:{pt}/api/time", timeout=4).status_code < 500: base = f"http://127.0.0.1:{pt}"; break
            except Exception: continue
        for q in qs:
            route = "error"; ftxt = ""; fsql = ""; why = ""
            if not base: out.append({"question": q, "result": "Error", "route": "error", "reply": "Could not reach the server on localhost. Reload the page and try again."}); continue
            try:
                r = _rq.post(base + "/api/copilot", json={"q": q, "sid": "probe-" + u["email"]}, headers={"Cookie": cookie, "Authorization": auth, "X-Internal": _hd.INTERNAL}, stream=True, timeout=120)
                if r.status_code != 200: raise RuntimeError(f"HTTP {r.status_code}")
                for ln in r.iter_lines():
                    if ln.startswith(b"data: "):
                        try: ev = json.loads(ln[6:])
                        except Exception: continue
                        if ev.get("ev") == "final": ftxt = ev.get("text", "")
                        elif ev.get("ev") == "exact": fsql = ev.get("sql", "")
                with sqlite3.connect(DB_PATH, timeout=30) as c: row = c.execute("SELECT route FROM copilot_log WHERE q=? ORDER BY id DESC LIMIT 1", (q[:300],)).fetchone()
                route = row[0] if row else "unknown"
                if route in ("exact", "agents+llm", "exact+llm") and CP.weak_match(q, {"answer": ftxt, "sql": fsql}): route = "weak"; CP.log_turn(q, "weak", 0)
            except Exception as e: route = "error"; why = repr(e)[:80]
            out.append({"question": q, "result": "Error" if route == "error" else ("UNANSWERED" if route == "unanswered" else ("Weak match: check" if route == "weak" else "Answered")), "route": route, "reply": why if route == "error" else ftxt[:110].replace("\n", " ")})
        return out
    res = await asyncio.to_thread(run); na = sum(1 for r in res if r["result"] not in ("Answered", "Error")); er = sum(1 for r in res if r["result"] == "Error")
    return ok(f"{len(res)} tested: {len(res) - na - er} answered, {na} unanswered or weak (added to the backlog below)" + (f", {er} could not be tested (see the reply column)" if er else "") + ".", blocks=[B.table(res, ["question", B.pill_col("result"), "route", "reply"], h=min(420, 60 + 34 * len(res)), key="probe_out")], refresh=True)
@app.get("/api/copilot/insights")
def copilot_insights(request: Request):
    u = user_of(request); need(ctx(u), "admin"); return CP.insights()
@app.get("/api/time")
def api_time():
    n = datetime.datetime.now(); return {"iso": n.isoformat(timespec="seconds"), "tz": "Asia/Kolkata", "label": n.strftime("%a %d %b %Y, %I:%M %p IST")}
@app.get("/api/copilot/unanswered")
def copilot_unanswered(request: Request):
    u = user_of(request); need(ctx(u), "admin"); return {"rows": CP.unanswered()}
LE.set_chain_defaults(dom)
@app.post("/api/approval/chain")
async def approval_chain(request: Request):
    u = user_of(request); c = ctx(u); need(c, "admin"); d = await request.json(); cur = LE.get_state("approval_chain", {}) or {}; n = 0
    valid = set(dom.ACTION_AGENT) | {"req:" + k for k in dom.REQUEST_KINDS}
    for k, v in d.items():
        if k not in valid or v not in dom.CHAIN_PRESETS: continue
        ch = [x.strip() for x in v.split("→")]
        if cur.get(k) != ch: cur[k] = ch; n += 1; LE.audit(u["email"], "approval_chain", k, " → ".join(ch))
    LE.set_state("approval_chain", cur); return ok(f"{n} approval chain(s) saved. New requests use them at once.", refresh=True)
