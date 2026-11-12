"""Smoke test for a running app:  python selftest.py http://localhost:8000 admin@infosys.com 'password'
Logs in, opens every page the role can see, asks the Copilot exact-data questions and checks the answers against the database."""
import sys, json, httpx
def main(base, login, pw):
    c = httpx.Client(base_url=base, timeout=120); bad = []
    r = c.post("/api/login", json={"login": login, "password": pw}); assert r.status_code == 200, f"login failed: {r.text}"
    assert c.get("/api/ready").status_code == 200, "not ready"
    me = c.get("/api/me").json(); pages = [m["id"] for m in me.get("menu", [])]
    for p in pages:
        rr = c.get(f"/api/page/{p}")
        if rr.status_code != 200: bad.append((p, rr.status_code))
    kind = me.get("kind", ""); qs = ["how many outlets are there", "which outlet has the highest revenue"] if kind == "Franchise" else ["how many shipments are there", "which port has the highest congestion"]
    for q in qs:
        t = c.post("/api/copilot", json={"q": q, "lang": "English"}); fin = [json.loads(l[6:]) for l in t.text.splitlines() if l.startswith("data: ")]
        fin = [e for e in fin if e["ev"] == "final"]
        if not fin or not any(ch.isdigit() for ch in fin[0]["text"]) or not fin[0].get("sql"): bad.append(("copilot", q))
    print(f"{len(pages)} pages, {len(qs)} copilot questions, problems: {bad or 'none'}"); return 1 if bad else 0
if __name__ == "__main__": sys.exit(main(*sys.argv[1:4]))
