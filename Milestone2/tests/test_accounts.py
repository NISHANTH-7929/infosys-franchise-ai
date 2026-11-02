"""Real accounts, no simulated users: signup, login, lockout, password recovery, profile and the admin dashboard,
checked against the rules in the Milestone 2 instructions (Steps 3, 4, 5 and 6)."""
import re, itertools
import pytest

OUT = re.compile(r"OUT-\d+")
PW = "Passw0rd!x"
_n = itertools.count(1)

@pytest.fixture
def call(server):
    def _call(method, path, token=None, **kw):
        server.client.cookies.clear()               # the test client keeps the login cookie; send only what the test means to send
        h = {"Authorization": f"Bearer {token}"} if token else {}
        return server.client.request(method, path, headers=h, **kw)
    return _call

@pytest.fixture
def make(call):
    """make(role, outlet=None) -> (token, user) of a brand-new account created through the public signup route."""
    def _make(role, outlet=None, password=PW):
        k = next(_n); name = f"user{k}_{role.split()[0].lower()}"
        body = {"email": f"{name}@test.org", "username": name, "password": password, "confirm_password": password, "role": role, "outlet": outlet}
        r = call("POST", "/api/auth/signup", json=body); assert r.status_code == 200, r.text
        r = call("POST", "/api/auth/login", json={"identity": body["email"], "password": password}); assert r.status_code == 200, r.text
        return r.json()["token"], {**r.json()["user"], "email": body["email"], "username": name, "password": password}
    return _make

@pytest.fixture
def admin(call):
    import config
    r = call("POST", "/api/auth/login", json={"identity": config.ADMIN_EMAIL_ID, "password": config.ADMIN_PASSWORD}); assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["user"]

# ------------------------------------------------------------------ signup (Step 3 validation rules + RBAC at signup)
def signup(call, **over):
    k = next(_n); body = {"email": f"s{k}@test.org", "username": f"su{k}", "password": PW, "confirm_password": PW, "role": "Staff", "outlet": "OUT-010", **over}
    return call("POST", "/api/auth/signup", json=body)

@pytest.mark.parametrize("over,needle", [
    ({"email": ""}, "empty"), ({"username": "  "}, "empty"), ({"password": "", "confirm_password": ""}, "empty"),
    ({"email": "a@bc.de"}, "2 characters before"), ({"email": "ab@c.de"}, "2 characters between"), ({"email": "ab@cd.e"}, "2 characters after"), ({"email": "no-at-sign.com"}, "@"),
    ({"password": "Sh0rt!a", "confirm_password": "Sh0rt!a"}, "8 characters"), ({"password": "alllower1!", "confirm_password": "alllower1!"}, "uppercase"),
    ({"password": "ALLUPPER1!", "confirm_password": "ALLUPPER1!"}, "lowercase"), ({"password": "NoDigits!!", "confirm_password": "NoDigits!!"}, "digit"),
    ({"password": "NoSpecial11", "confirm_password": "NoSpecial11"}, "special"), ({"confirm_password": "Different1!"}, "does not match"),
    ({"username": "a b"}, "letters, numbers"), ({"role": "Customer"}, "valid role"), ({"role": ""}, "empty"),
    ({"role": "Staff", "outlet": ""}, "outlet"), ({"role": "Store Manager", "outlet": "OUT-999"}, "does not exist"),
])
def test_signup_validation(call, over, needle):
    r = signup(call, **over); assert r.status_code == 400 and needle.lower() in r.json()["detail"].lower(), (over, r.text)

def test_nobody_can_sign_up_as_admin(call):
    for role in ("Admin", "admin", "ADMIN", "Administrator"):
        assert signup(call, role=role).status_code == 400, role

def test_signup_roles_and_outlet_rules(call):
    assert signup(call, role="Franchise Owner", outlet="").status_code == 200       # chain-wide roles need no outlet
    assert signup(call, role="Auditor", outlet="").status_code == 200
    assert signup(call, role="Store Manager", outlet="OUT-010").status_code == 200
    assert signup(call, role="Store Manager", outlet="").status_code == 400

def test_signup_rejects_duplicates(call, make):
    _, u = make("Staff", "OUT-010")
    assert "email" in signup(call, email=u["email"].upper()).json()["detail"].lower()
    assert "username" in signup(call, username=u["username"].upper()).json()["detail"].lower()

def test_signup_options_are_public_and_exclude_admin(call):
    o = call("GET", "/api/auth/options").json(); assert "Admin" not in o["roles"] and set(o["roles"]) == {"Franchise Owner", "Store Manager", "Staff", "Auditor"} and "OUT-010" in o["outlets"]

def test_passwords_are_hashed(server, make):
    _, u = make("Staff", "OUT-010")
    import accounts
    with accounts.db() as c: h = c.execute("SELECT password_hash FROM users WHERE email=?", (u["email"],)).fetchone()[0]
    assert h.startswith("$2") and u["password"] not in h

# ------------------------------------------------------------------ login, JWT, lockout (Step 3)
def test_login_by_email_or_username_and_token_is_required(call, make):
    tok, u = make("Staff", "OUT-010")
    assert call("GET", "/api/me").status_code == 401                                   # no token
    assert call("GET", "/api/me", token="garbage").status_code == 401
    assert call("GET", "/api/me", token=tok).json()["user"]["role"] == "Staff"
    r = call("POST", "/api/auth/login", json={"identity": u["username"].upper(), "password": u["password"]}); assert r.status_code == 200
    assert "password" not in r.text and "hash" not in r.text

def test_unknown_user_and_wrong_password_give_the_same_error(call, make):
    _, u = make("Staff", "OUT-010")
    a = call("POST", "/api/auth/login", json={"identity": "nobody@nowhere.org", "password": "Whatever1!"})
    b = call("POST", "/api/auth/login", json={"identity": u["email"], "password": "Whatever1!"})
    assert a.status_code == b.status_code == 401 and a.json()["detail"] == b.json()["detail"]

def test_five_wrong_passwords_lock_the_account(call, make, admin):
    tok, u = make("Staff", "OUT-010")
    for i in range(4): assert call("POST", "/api/auth/login", json={"identity": u["email"], "password": f"Wrong{i}pass!"}).status_code == 401
    assert call("POST", "/api/auth/login", json={"identity": u["email"], "password": u["password"]}).status_code == 200     # still open after 4; success resets the counter
    for i in range(5): call("POST", "/api/auth/login", json={"identity": u["email"], "password": f"Wrong{i}pass!"})
    r = call("POST", "/api/auth/login", json={"identity": u["email"], "password": u["password"]}); assert r.status_code == 403 and "locked" in r.json()["detail"].lower()
    assert call("GET", "/api/me", token=tok).status_code == 401                         # the token from before the lock stops working at once
    users = call("GET", "/api/admin/overview", token=admin[0]).json()["users"]; assert next(x for x in users if x["email"] == u["email"])["locked"]

def test_locked_user_is_blocked_immediately_and_unlock_restores(call, make, admin):
    tok, u = make("Franchise Owner")
    assert call("GET", "/api/page/outlets", token=tok).status_code == 200
    assert call("POST", f"/api/admin/users/{u['id']}/lock", token=admin[0]).status_code == 200
    assert call("GET", "/api/page/outlets", token=tok).status_code == 401
    assert call("POST", "/api/auth/login", json={"identity": u["email"], "password": u["password"]}).status_code == 403
    assert call("POST", f"/api/admin/users/{u['id']}/unlock", token=admin[0]).status_code == 200
    assert call("POST", "/api/auth/login", json={"identity": u["email"], "password": u["password"]}).status_code == 200

# ------------------------------------------------------------------ RBAC with real accounts (Step 5: log in as each role, one allowed and one 403)
def test_each_real_role_gets_the_right_pages(call, make, admin):
    accounts = {"Admin": admin[0], "Franchise Owner": make("Franchise Owner")[0], "Store Manager": make("Store Manager", "OUT-010")[0], "Staff": make("Staff", "OUT-010")[0], "Auditor": make("Auditor")[0]}
    allowed = {"Admin": {"marketing", "audit"}, "Franchise Owner": {"marketing", "audit"}, "Store Manager": {"audit"}, "Staff": set(), "Auditor": {"marketing", "audit"}}
    for role, tok in accounts.items():
        for page in ("marketing", "audit"): assert call("GET", f"/api/page/{page}", token=tok).status_code == (200 if page in allowed[role] else 403), (role, page)
        assert call("GET", "/api/page/copilot", token=tok).status_code == 200
        assert call("POST", "/api/run_cycle", token=tok).status_code == (200 if role in ("Admin", "Franchise Owner") else 403), role
        assert call("GET", "/api/admin/overview", token=tok).status_code == (200 if role == "Admin" else 403), role
    sm = accounts["Store Manager"]; assert set(OUT.findall(call("GET", "/api/page/audit", token=sm).text)) <= {"OUT-010"}

# ------------------------------------------------------------------ forgot / reset by e-mail code
@pytest.fixture
def mails(monkeypatch):
    sent = []
    import mailer; monkeypatch.setattr(mailer, "send", lambda to, subject, body, *a, **k: (sent.append((to, body)) or (True, "ok")))
    return sent
def code_in(mails, to): return re.search(r"\b(\d{6})\b", [b for t, b in mails if t == to][-1]).group(1)

def expire_cooldown(email):
    import accounts
    with accounts.db() as c: c.execute("UPDATE users SET otp_sent=0 WHERE lower(email)=?", (email.lower(),))

def test_forgot_is_silent_about_unknown_emails(call, mails):
    r = call("POST", "/api/auth/forgot", json={"email": "ghost@nowhere.org"}); assert r.status_code == 200 and not mails
    assert call("POST", "/api/auth/forgot", json={"email": "bad"}).status_code == 400

def test_reset_flow_changes_the_password_and_ends_old_sessions(call, make, mails):
    tok, u = make("Staff", "OUT-010"); call("POST", "/api/auth/forgot", json={"email": u["email"]}); code = code_in(mails, u["email"])
    assert call("POST", "/api/auth/verify", json={"email": u["email"], "otp": "000000"}).status_code == 400
    assert call("POST", "/api/auth/verify", json={"email": u["email"], "otp": code}).status_code == 200
    assert call("POST", "/api/auth/reset", json={"email": u["email"], "otp": code, "password": "weak", "confirm_password": "weak"}).status_code == 400
    assert call("POST", "/api/auth/reset", json={"email": u["email"], "otp": code, "password": "NewPassw0rd!", "confirm_password": "Other0Passw!"}).status_code == 400
    assert call("POST", "/api/auth/reset", json={"email": u["email"], "otp": code, "password": "NewPassw0rd!", "confirm_password": "NewPassw0rd!"}).status_code == 200
    assert call("POST", "/api/auth/reset", json={"email": u["email"], "otp": code, "password": "NewPassw0rd!", "confirm_password": "NewPassw0rd!"}).status_code == 400   # the code works once
    assert call("POST", "/api/auth/login", json={"identity": u["email"], "password": u["password"]}).status_code == 401
    assert call("POST", "/api/auth/login", json={"identity": u["email"], "password": "NewPassw0rd!"}).status_code == 200
    assert call("GET", "/api/me", token=tok).status_code == 401

def test_five_wrong_codes_burn_the_code(call, make, mails):
    _, u = make("Staff", "OUT-010"); call("POST", "/api/auth/forgot", json={"email": u["email"]}); code = code_in(mails, u["email"])
    for _ in range(5): assert call("POST", "/api/auth/verify", json={"email": u["email"], "otp": "111111" if code != "111111" else "222222"}).status_code == 400
    assert call("POST", "/api/auth/verify", json={"email": u["email"], "otp": code}).status_code == 400

def test_reset_does_not_unlock_a_locked_account(call, make, admin, mails):
    _, u = make("Staff", "OUT-010"); call("POST", f"/api/admin/users/{u['id']}/lock", token=admin[0])
    call("POST", "/api/auth/forgot", json={"email": u["email"]}); assert not [m for m in mails if m[0] == u["email"]]       # no code for a locked account
    assert call("POST", "/api/auth/login", json={"identity": u["email"], "password": u["password"]}).status_code == 403

# ------------------------------------------------------------------ profile (Step 4)
def test_profile_shows_account_and_never_the_hash(call, make):
    tok, u = make("Store Manager", "OUT-010"); p = call("GET", "/api/profile", token=tok).json()["profile"]
    assert p["email"] == u["email"] and p["role"] == "Store Manager" and p["outlet"] == "OUT-010" and p["created_at"] and p["last_login"] and "hash" not in str(p).lower()

def test_profile_username_change(call, make):
    tok, u = make("Staff", "OUT-010"); _, other = make("Staff", "OUT-011")
    assert call("POST", "/api/profile/username", token=tok, json={"username": other["username"]}).status_code == 400
    assert call("POST", "/api/profile/username", token=tok, json={"username": "x"}).status_code == 400
    assert call("POST", "/api/profile/username", token=tok, json={"username": "renamed_user"}).status_code == 200
    assert call("GET", "/api/profile", token=tok).json()["profile"]["username"] == "renamed_user"

def test_profile_password_change_needs_current_password_and_rules(call, make):
    tok, u = make("Staff", "OUT-010"); body = lambda **o: {"current_password": u["password"], "new_password": "Brand0New!pw", "confirm_password": "Brand0New!pw", **o}
    assert call("POST", "/api/profile/password", token=tok, json=body(current_password="Wrong0pass!")).status_code == 400
    assert call("POST", "/api/profile/password", token=tok, json=body(new_password="weak", confirm_password="weak")).status_code == 400
    assert call("POST", "/api/profile/password", token=tok, json=body(confirm_password="Mismatch0!pw")).status_code == 400
    r = call("POST", "/api/profile/password", token=tok, json=body()); assert r.status_code == 200
    assert call("GET", "/api/me", token=tok).status_code == 401 and call("GET", "/api/me", token=r.json()["token"]).status_code == 200
    assert call("POST", "/api/auth/login", json={"identity": u["email"], "password": "Brand0New!pw"}).status_code == 200

# ------------------------------------------------------------------ admin dashboard (Step 6)
def test_admin_overview_has_users_kpis_activity_and_no_hashes(call, admin, make):
    make("Staff", "OUT-010"); d = call("GET", "/api/admin/overview", token=admin[0]).json()
    assert d["kpis"]["total"] == len(d["users"]) and d["kpis"]["per_role"]["Admin"] >= 1 and "locked" in d["kpis"]
    assert {"email", "username", "role", "locked", "created_at", "last_login"} <= set(d["users"][0]) and "hash" not in str(d).lower() and "otp" not in str(d["users"]).lower()
    assert len(d["activity"]) <= 50 and d["activity"] and {"ts", "actor", "event"} <= set(d["activity"][0]) and d["matrix"][0]["Role"] == "Admin"

def test_admin_add_user_applies_the_validation_rules(call, admin):
    ok = {"email": "new.hire@test.org", "username": "new_hire", "password": "Temp0rary!pw", "role": "Auditor"}
    assert call("POST", "/api/admin/users", token=admin[0], json={**ok, "password": "weak"}).status_code == 400
    assert call("POST", "/api/admin/users", token=admin[0], json={**ok, "email": "a@b.c"}).status_code == 400
    assert call("POST", "/api/admin/users", token=admin[0], json={**ok, "role": "Store Manager"}).status_code == 400            # needs an outlet
    assert call("POST", "/api/admin/users", token=admin[0], json=ok).status_code == 200
    assert call("POST", "/api/admin/users", token=admin[0], json=ok).status_code == 400                                         # duplicate
    assert call("POST", "/api/auth/login", json={"identity": ok["email"], "password": ok["password"]}).status_code == 200
    assert call("POST", "/api/admin/users", token=admin[0], json={**ok, "email": "boss@test.org", "username": "boss_two", "role": "Admin"}).status_code == 200   # an Admin may create an Admin

def test_promote_and_demote_take_effect_immediately(call, admin, make):
    tok, u = make("Staff", "OUT-010")
    assert call("GET", "/api/page/workforce", token=tok).status_code == 403
    assert call("POST", f"/api/admin/users/{u['id']}/role", token=admin[0], json={"role": "Franchise Owner"}).status_code == 200
    assert call("GET", "/api/page/workforce", token=tok).status_code == 200 and call("POST", "/api/run_cycle", token=tok).status_code == 200      # same token, new privileges
    assert call("POST", f"/api/admin/users/{u['id']}/role", token=admin[0], json={"role": "Auditor"}).status_code == 200
    assert call("POST", "/api/run_cycle", token=tok).status_code == 403 and call("GET", "/api/page/workforce", token=tok).status_code == 200
    assert call("POST", f"/api/admin/users/{u['id']}/role", token=admin[0], json={"role": "Store Manager"}).status_code == 200            # the outlet from signup was kept while they held an all-outlets role
    assert call("GET", "/api/me", token=tok).json()["scope"] == "OUT-010"
    assert call("POST", f"/api/admin/users/{u['id']}/role", token=admin[0], json={"role": "Store Manager", "outlet": "OUT-020"}).status_code == 200
    assert call("GET", "/api/me", token=tok).json()["scope"] == "OUT-020"
    _, nobody = make("Franchise Owner")                                                                                                   # never had an outlet: a scoped role needs one
    assert call("POST", f"/api/admin/users/{nobody['id']}/role", token=admin[0], json={"role": "Store Manager"}).status_code == 400
    assert call("POST", f"/api/admin/users/{nobody['id']}/role", token=admin[0], json={"role": "Staff", "outlet": "OUT-999"}).status_code == 400
    assert call("POST", f"/api/admin/users/{u['id']}/role", token=admin[0], json={"role": "Wizard"}).status_code == 400

def test_non_admins_cannot_touch_users(call, make, admin):
    tok, u = make("Franchise Owner"); _, victim = make("Staff", "OUT-010")
    for method, path, body in [("GET", "/api/admin/overview", None), ("POST", "/api/admin/users", {}), ("POST", f"/api/admin/users/{victim['id']}/role", {"role": "Admin"}),
                               ("POST", f"/api/admin/users/{victim['id']}/lock", {}), ("POST", f"/api/admin/users/{victim['id']}/delete", {"confirm": True})]:
        assert call(method, path, token=tok, json=body).status_code == 403, path
    assert call("GET", "/api/admin/overview").status_code == 401

def test_delete_needs_confirmation(call, admin, make):
    _, u = make("Staff", "OUT-010")
    assert call("POST", f"/api/admin/users/{u['id']}/delete", token=admin[0], json={}).status_code == 400
    assert call("POST", f"/api/admin/users/{u['id']}/delete", token=admin[0], json={"confirm": "yes"}).status_code == 400
    assert call("POST", f"/api/admin/users/{u['id']}/delete", token=admin[0], json={"confirm": True}).status_code == 200
    assert call("POST", "/api/auth/login", json={"identity": u["email"], "password": u["password"]}).status_code == 401
    assert call("POST", f"/api/admin/users/{u['id']}/delete", token=admin[0], json={"confirm": True}).status_code == 404

def test_an_admin_cannot_delete_lock_or_demote_themselves(call, admin):
    tok, me = admin
    assert call("POST", f"/api/admin/users/{me['id']}/delete", token=tok, json={"confirm": True}).status_code == 400
    assert call("POST", f"/api/admin/users/{me['id']}/lock", token=tok).status_code == 400
    assert call("POST", f"/api/admin/users/{me['id']}/role", token=tok, json={"role": "Staff", "outlet": "OUT-010"}).status_code == 400

def test_the_last_admin_is_protected(call, admin):
    """A locked Admin cannot act and an Admin cannot touch their own account, so the last active Admin can never be removed, locked or demoted."""
    tok, me = admin
    r = call("POST", "/api/admin/users", token=tok, json={"email": "extra.admin@test.org", "username": "extra_admin", "password": "Extra0Admin!", "role": "Admin"}); assert r.status_code == 200
    extra = r.json()["id"]; t2 = call("POST", "/api/auth/login", json={"identity": "extra.admin@test.org", "password": "Extra0Admin!"}).json()["token"]
    assert call("POST", f"/api/admin/users/{me['id']}/lock", token=t2).status_code == 200            # two Admins: one may lock the other
    assert call("GET", "/api/admin/overview", token=tok).status_code == 401                          # ...and the locked Admin is out at once, so it cannot hit back
    assert call("POST", f"/api/admin/users/{extra}/delete", token=t2, json={"confirm": True}).status_code == 400   # the remaining Admin cannot delete itself
    assert call("POST", f"/api/admin/users/{extra}/lock", token=t2).status_code == 400
    assert call("POST", f"/api/admin/users/{extra}/role", token=t2, json={"role": "Staff", "outlet": "OUT-010"}).status_code == 400
    assert call("POST", f"/api/admin/users/{me['id']}/unlock", token=t2).status_code == 200            # put things back
    assert call("POST", f"/api/admin/users/{extra}/delete", token=call("POST", "/api/auth/login", json={"identity": me["email"], "password": __import__("config").ADMIN_PASSWORD}).json()["token"], json={"confirm": True}).status_code == 200

def test_admin_actions_are_logged_with_who_what_when(call, admin, make):
    _, u = make("Staff", "OUT-010"); call("POST", f"/api/admin/users/{u['id']}/role", token=admin[0], json={"role": "Auditor"}); call("POST", f"/api/admin/users/{u['id']}/lock", token=admin[0])
    log = call("GET", "/api/admin/overview", token=admin[0]).json()["activity"]
    ev = {(x["event"], x["target"]) for x in log}; assert ("role_changed", u["email"]) in ev and ("user_locked", u["email"]) in ev
    assert all(x["actor"] and x["ts"] for x in log)

def test_five_wrong_passwords_never_lock_the_last_active_admin(call):
    import accounts, config
    with accounts.db() as c: c.execute("DELETE FROM users WHERE role='Admin' AND lower(email)<>lower(?)", (config.ADMIN_EMAIL_ID,)); c.execute("UPDATE users SET locked=0, failed_attempts=0 WHERE lower(email)=lower(?)", (config.ADMIN_EMAIL_ID,))
    for i in range(8): call("POST", "/api/auth/login", json={"identity": config.ADMIN_EMAIL_ID, "password": f"Wrong{i}pass!"})
    assert call("POST", "/api/auth/login", json={"identity": config.ADMIN_EMAIL_ID, "password": config.ADMIN_PASSWORD}).status_code == 200
