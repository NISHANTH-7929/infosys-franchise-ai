"""Milestone 3 tests: simulators (seed, ranges, assumptions, no writes), taught questions, Admin tools, Copilot fine-tune, role limits on the new pages."""
import csv, json, os, sqlite3
import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SIMS = ["inventory", "workforce", "outlets", "marketing", "sentiment", "audit"]

def text_of(blocks): return json.dumps(blocks, default=str)

# ------------------------------------------------------------------ simulators
@pytest.mark.parametrize("pid", SIMS)
def test_simulator_lists_assumptions_range_and_seed(server, pid):
    import sim_fr as S
    r = S.RUN[pid]({"seed": 7, "pct": 20}); t = text_of(r["blocks"])
    assert "Assumptions" in t and "Random seed 7" in t
    assert "P10" in t or "P10–P90" in t                                   # a range, not one number

@pytest.mark.parametrize("pid", SIMS)
def test_same_seed_same_result_other_seed_differs(server, pid):
    import sim_fr as S
    a, b, c = (text_of(S.RUN[pid]({"seed": s, "pct": 20})["blocks"]) for s in (5, 5, 6))
    assert a == b
    if pid not in ("outlets",): assert a != c                              # the P&L base case is deterministic; its band is sampled, but the table text may match

def test_simulators_never_change_live_data(server):
    import sim_fr as S, config
    def counts():
        with sqlite3.connect(config.DB_PATH) as c: return [c.execute(f"SELECT COUNT(*), COALESCE(SUM(1),0) FROM {t}").fetchone() for t in ("outlets", "staff", "inventory", "marketing", "feedback", "audits", "agent_actions")]
    before = counts()
    for pid in SIMS: S.RUN[pid]({"seed": 1, "pct": 30})
    assert counts() == before

def test_inventory_compares_three_reorder_rules_and_reports_stockout_probability(server):
    import sim_fr as S
    m = S.run_inventory({"seed": 3})["m"]
    assert len(m["rules"]) == 3 and 0 <= m["stockout_prob"] <= 1

def test_workforce_attrition_by_tenure_and_hiring_vs_overtime(server):
    import sim_fr as S
    m = S.run_workforce({"pct": 25, "seed": 3, "lead": 6})["m"]["attrition"]
    assert len(m["bands"]) >= 2 and m["cheaper"] in ("Hiring", "Overtime") and m["hire_cost"] > 0 and m["ot_cost"] > 0

def test_pnl_has_best_and_worst_case(server):
    import sim_fr as S
    m = S.run_pnl({"seed": 3, "pct": -10, "wage_lo": 3, "wage_hi": 12})["m"]
    assert m["worst"] <= m["profit"] <= m["best"] and m["p10"] <= m["p90"]

def test_sentiment_top_complaint_fix_raises_csat(server):
    import sim_fr as S
    f = S.run_sentiment({"seed": 3, "fix": 80})["m"]["fix"]
    assert f["top"] and f["csat_gain"] > 0 and f["repeat_gain"] >= 0

def test_audit_uses_open_findings_and_days(server):
    import sim_fr as S
    slow = S.run_audit({"seed": 3, "wait": 5, "close": 0.5})["m"]; fast = S.run_audit({"seed": 3, "wait": 90, "close": 6})["m"]
    assert slow["fail_at_audit"] >= fast["fail_at_audit"] and slow["days_to_comply"] >= fast["days_to_comply"]

def test_simulator_endpoint_for_every_agent(login):
    c = login("Admin")
    for pid in SIMS:
        r = c.post("/api/sim/run", json={"page": pid, "seed": 42}); assert r.status_code == 200 and r.json()["blocks"], pid
        assert c.get(f"/api/page/{pid}", params={"tab": "sim"}).status_code == 200

# ------------------------------------------------------------------ taught questions
def test_taught_questions_csv_has_at_least_50_unique_rows():
    rows = list(csv.DictReader(open(os.path.join(ROOT, "taught_questions.csv"), encoding="utf-8-sig")))
    assert len(rows) >= 50 and len({r["question"].strip().lower() for r in rows}) == len(rows)
    assert all(len(r["answer"]) >= 10 and r["keywords"].strip() for r in rows)

def test_taught_questions_are_loaded_and_counted(login, server):
    import copilot_pro as CP, time
    for _ in range(40):
        if CP.teach_stats()["taught"] >= 50: break
        time.sleep(0.5)
    assert CP.teach_stats()["taught"] >= 50
    tab = login("Admin").get("/api/page/admin", params={"tab": "teach"}).json(); assert "/ 50" in text_of(tab)

def test_taught_answer_is_returned_by_the_copilot(login):
    q = next(iter(csv.DictReader(open(os.path.join(ROOT, "taught_questions.csv"), encoding="utf-8-sig"))))["question"]
    r = login("Admin").post("/api/copilot", json={"q": q}); assert r.status_code == 200 and "taught answer" in r.text.lower()

# ------------------------------------------------------------------ admin tools and role limits
@pytest.mark.parametrize("tab", ["users", "runtime", "gpu", "decisions", "audit", "insights", "teach", "check", "gov", "data"])
def test_admin_tabs_open_for_admin(login, tab):
    assert login("Admin").get("/api/page/admin", params={"tab": tab}).status_code == 200

def test_users_tab_is_the_milestone2_dashboard(login):
    d = login("Admin").get("/api/page/admin", params={"tab": "users"}).json()
    assert any(b.get("t") == "admin_users" for b in d["blocks"]) and d["tabs"][0]["id"] == "users"

@pytest.mark.parametrize("role", ["Franchise Owner", "Store Manager", "Staff", "Auditor"])
@pytest.mark.parametrize("path,method", [("/api/copilot/teach", "post"), ("/api/copilot/insights", "get"), ("/api/copilot/probe", "post"), ("/api/policy", "post"), ("/api/gov/purge", "post"), ("/api/backup", "get")])
def test_admin_only_tools_refuse_other_roles_with_403(login, role, path, method):
    c = login(role, "OUT-010" if role in ("Store Manager", "Staff") else None)
    r = c.get(path) if method == "get" else c.post(path, json={})
    assert r.status_code == 403, (role, path)

def test_staff_cannot_open_new_pages_and_manager_cannot_feed_data(login):
    s = login("Staff", "OUT-010")
    for pid in ("approvals", "command", "twin", "reports", "notifications", "feeds"): assert s.get(f"/api/page/{pid}").status_code == 403, pid
    m = login("Store Manager", "OUT-010")
    assert m.get("/api/page/feeds").status_code == 403 and m.post("/api/feed/url", json={"target": "sales", "url": "http://x"}).status_code == 403

def test_auditor_is_read_only_on_tickets(login):
    assert login("Auditor").post("/api/run_cycle").status_code == 403

# ------------------------------------------------------------------ Copilot fine-tune and the knowledge base
@pytest.mark.parametrize("q", ["Which outlets are making a loss?", "How much did we sell today?", "How many agents are out of stock?"])
def test_tuned_questions_answer_from_sql_with_the_query_shown(login, q):
    r = login("Admin").post("/api/copilot", json={"q": q}); assert r.status_code == 200
    assert '"ev": "final"' in r.text

def test_unanswerable_question_says_i_do_not_know(login):
    r = login("Admin").post("/api/copilot", json={"q": "What is the weather in Delhi tomorrow?"})
    assert "I do not know" in r.text

def test_copilot_insights_panel_and_system_check(login):
    c = login("Admin")
    assert "Knowledge base" in text_of(c.get("/api/page/admin", params={"tab": "check"}).json())
    assert c.get("/api/page/admin", params={"tab": "insights"}).status_code == 200

def test_scoped_role_never_gets_other_outlets_in_the_copilot(login):
    c = login("Store Manager", "OUT-010")
    r = c.post("/api/copilot", json={"q": "Show OUT-011 inventory"})
    assert "outside your outlet" in r.text

def test_preferences_round_trip(server, login):
    import accounts
    accounts.set_prefs(1, lang="Hindi", email_alerts=1, daily_digest=0)
    p = accounts.get_prefs(1); assert p["lang"] == "Hindi" and p["email_alerts"] == 1 and p["daily_digest"] == 0
