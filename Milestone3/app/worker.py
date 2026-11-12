"""Background worker process: the simulator, the agent cycles, escalation and the feed threads run here so the web server (and the GPU models) never share a GIL with them."""
import os as _os, time as _time
_os.environ["TZ"] = "Asia/Kolkata"
try: _time.tzset()
except Exception: pass          # all times in this app are India Standard Time (IST)
import os, sys, time, importlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, live_engine as LE
dom = importlib.import_module("domain_franchise" if config.KIND == "Franchise" else "domain_freight")
if __name__ == "__main__":
    rt = LE.Runtime(dom, int(os.environ.get("LIVE_TICK_SEC", 5)), int(os.environ.get("LIVE_CYCLE_SEC", 60)))
    import mailer, accounts, rbac, reports as RP, datetime, threading
    def digest_loop():
        every = float(os.environ.get("DIGEST_EVERY_H", 24)) * 3600
        while True:
            time.sleep(60)
            try:
                if not mailer.configured(): continue
                for u in accounts.digest_targets():
                    last = u.get("last_digest"); due = (not last) or (datetime.datetime.now() - datetime.datetime.fromisoformat(last)).total_seconds() >= every
                    if not due: continue
                    try: scope = rbac.scope_for(u)
                    except Exception: continue                   # a scoped role without an outlet gets nothing
                    name, data = RP.build_pdf(config.KIND, "fr_exec" if config.KIND == "Franchise" else "fq_exec", {"scope": scope})
                    ok, m = mailer.send(u["email"], f"{dom.NAME} daily digest", "Your daily digest: the executive report is attached.", [(name, data, "application/pdf")])
                    if ok: accounts.set_prefs(u["id"], last_digest=datetime.datetime.now().isoformat(timespec="seconds")); LE.audit(u["email"], "digest_sent", u["email"])
            except Exception: pass
    threading.Thread(target=digest_loop, daemon=True).start()
    if config.KIND == "Freight":
        import weather as WX; WX.start()
    while True: time.sleep(3600)
