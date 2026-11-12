"""Role-based access control (Step 5). One place that says who may open which page, which capability each role has and
which outlet a role is limited to. Everything here is enforced on the server; hiding a menu item in the front end is only a convenience.

The user object that user_of(request) returns must contain: email, username, role and (for Store Manager / Staff) outlet.
An unknown role gets nothing, and a scoped role without an outlet is refused: every check fails closed."""
import re
from fastapi import HTTPException

ROLES = ["Admin", "Franchise Owner", "Store Manager", "Staff", "Auditor"]

# page ids (the menu entries of views_franchise.MENU; "profile" and the Users tab of "admin" are drawn by the front end from /api/profile and /api/admin/*)
AGENT_PAGES = {"workforce", "outlets", "inventory", "marketing", "sentiment", "audit"}
ALL_PAGES = {"copilot", "approvals", "command", "twin", "reports", "notifications", "feeds", "profile", "admin"} | AGENT_PAGES
EXTRA_MENU = []                                   # kept for compatibility: the menu is views_franchise.MENU, filtered by ROLE_MENU

# page access matrix
_OPS = {"copilot", "approvals", "command", "twin", "reports", "notifications", "profile"} | AGENT_PAGES
ROLE_MENU = {
    "Admin":           ALL_PAGES - set(),
    "Franchise Owner": _OPS | {"feeds"},
    "Store Manager":   {"copilot", "approvals", "command", "twin", "reports", "notifications", "profile", "workforce", "outlets", "inventory", "sentiment", "audit"},
    "Staff":           {"copilot", "profile"},
    "Auditor":         (_OPS - {"twin"}),
}

# capabilities: what a role may DO (need(ctx, capability) is called by every action route)
#   copilot  use the AI Copilot, its saved chats and the knowledge base       view     read the agent pages, the detail drawer, run simulators and the Digital Twin
#   run      run the agents                                                    resolve  resolve and assign tickets, log an inspection (Audit page)
#   review   add a customer review (Sentiment page)                            approve  approve or reject what agents propose
#   feeder   upload data (Data Feed Center)                                    users    open the user management of the Admin page
#   admin    Admin-only tools: Teach Copilot, insights, policies, governance   profile  see and edit your own profile      quote: Freight edition, Admin only
ALL_CAPS = {"copilot", "view", "run", "resolve", "review", "users", "profile", "quote", "approve", "feeder", "admin"}
ROLE_CAPS = {
    "Admin":           set(ALL_CAPS),
    "Franchise Owner": {"copilot", "view", "run", "resolve", "review", "approve", "feeder", "profile"},
    "Store Manager":   {"copilot", "view", "resolve", "review", "profile"},
    "Staff":           {"copilot", "profile"},
    "Auditor":         {"copilot", "view", "profile"},
}

SCOPED_ROLES = {"Store Manager", "Staff"}       # limited to ONE outlet (user["outlet"]); the other roles see every outlet
MASKED_ROLES = {"Staff", "Auditor"}             # the Copilot hides salary and personal details from these roles
OUTLET_RE = re.compile(r"OUT-\d+", re.I)

def role_of(user):
    role = (user or {}).get("role")
    if role not in ROLE_MENU: raise HTTPException(403, "Your account has no valid role. Ask an Admin to assign one.")
    return role

def scope_for(user):
    """None = every outlet. A scoped role returns its outlet id, or is refused when no outlet is assigned."""
    role = role_of(user)
    if role not in SCOPED_ROLES: return None
    outlet = str((user or {}).get("outlet") or "").strip().upper()
    if not OUTLET_RE.fullmatch(outlet): raise HTTPException(403, f"No outlet is assigned to this {role} account. Ask an Admin to assign one.")
    return outlet

def permission_table():
    """The page access matrix as rows ({"Role": ..., "Copilot": "✓", ...}) for the Admin dashboard and the README, so both always match ROLE_MENU / ROLE_CAPS."""
    cols = [("copilot", "Copilot"), ("approvals", "Approvals"), ("command", "Command Center"), ("workforce", "Workforce"), ("outlets", "Outlets"), ("inventory", "Inventory"), ("marketing", "Marketing"), ("sentiment", "Sentiment"), ("audit", "Audit"),
            ("twin", "Digital Twin"), ("reports", "Reports"), ("notifications", "Notifications"), ("feeds", "Data feeds")]
    yes = lambda b: "✓" if b else "✗"
    return [{"Role": r, **{label: yes(pid in ROLE_MENU[r]) for pid, label in cols}, "Run agents": yes("run" in ROLE_CAPS[r]), "Approve": yes("approve" in ROLE_CAPS[r]), "Users": yes("users" in ROLE_CAPS[r])} for r in ROLES]

def caps_of(role): return set(ROLE_CAPS.get(role, ()))
def pages_of(role): return set(ROLE_MENU.get(role, ()))
def masked(role): return role in MASKED_ROLES

def menu_for(role, catalog):
    """The menu entries (id, label, icon) this role may open, in the catalog's order."""
    allowed = pages_of(role)
    return [m for m in catalog if m[0] in allowed]

def need(c, cap):
    """Raise 403 when the role lacks the capability."""
    if cap not in ROLE_CAPS.get(c["role"], ()): raise HTTPException(403, f"Forbidden: the {c['role']} role is not allowed to do this ({cap}).")

def need_page(c, pid):
    if pid not in ALL_PAGES: raise HTTPException(404, "unknown page")
    if pid not in ROLE_MENU.get(c["role"], ()): raise HTTPException(403, f"Forbidden: the {c['role']} role cannot open the {pid} page.")

def guard_outlets(c, *texts):
    """A scoped user may not mention another outlet in a request (page parameters, tab, detail id, question)."""
    s = c.get("scope")
    if not s: return
    for t in texts:
        for m in OUTLET_RE.findall(str(t)):
            if m.upper() != s: raise HTTPException(403, f"Forbidden: {m.upper()} is outside your outlet ({s}).")

def own_outlet(c, outlet):
    """Writes (reviews, inspections): a scoped user may only write for their own outlet."""
    s = c.get("scope")
    if s and str(outlet or "").strip().upper() != s: raise HTTPException(403, f"Forbidden: you can only act on your own outlet ({s}).")
