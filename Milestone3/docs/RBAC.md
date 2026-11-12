# Role-Based Access Control (Step 5): developer notes

All access rules live in [`app/rbac.py`](../app/rbac.py) and are enforced on the server. Hiding a menu item is only a convenience: a user who types `/api/page/<id>` directly gets **403**. The user-facing description (matrix, capabilities, scope) is in the [Milestone 2 README](../README.md#3-roles-and-privileges-rbac).

## Where identity and permission enter the system

| Piece | Where | What it does |
|---|---|---|
| `user_of(request)` | `server.py` -> `accounts.current_user` | Bearer JWT -> the real user. 401 when the token is missing, expired or invalid, or the user was deleted or is locked. Role, outlet and lock flag are read from the database on every request. |
| `ctx(user)` | `server.py` | Builds the request context: role, outlet `scope` (`None` = all outlets). Raises 403 for an unknown role or a one-outlet role with no outlet. |
| `need(ctx, capability)` | `server.py` -> `rbac.need` | 403 when the role lacks the capability. Called by every action route. |
| `menu_for(user)` | `server.py` -> `rbac.menu_for` | Only the pages the role may open (also returned by `/api/me`, with `caps` and `scope`). |
| `rbac.need_page` / `guard_outlets` / `own_outlet` | `server.py` routes | Page access, "no other outlet in a parameter, tab, id or question", "write only for your own outlet". |
| `can(ctx, cap)` | `views_core.py` | Same table as `need()`: a button or form is only drawn for a role that may use it. |

## Adding a new page or action

1. Add the page id to `ALL_PAGES` and to the roles that may open it in `ROLE_MENU`.
2. Add a capability to `ALL_CAPS` / `ROLE_CAPS` if it is a new action, and call `need(c, "<capability>")` first in the route.
3. For anything that returns data, filter by `c["scope"]` when it is set (see `views_franchise._sc` and `views_core.scoped`).
4. Add the role/page to the matrix in `tests/test_rbac.py` (it is written independently of `rbac.py` on purpose).

## Decisions you can change in `rbac.py`

- The Franchise Owner sees **all** outlets (the matrix says "all agent pages").
- A Store Manager may log inspections and reviews for their **own** outlet (the instructions only say they cannot run agents).
- Salary and personal data are hidden from **Staff and Auditor** in the Copilot (`MASKED_ROLES`).

## Tests

```bash
pip install fastapi pandas numpy scikit-learn scipy vaderSentiment httpx python-multipart bcrypt pyjwt pytest
python -m pytest Milestone2/tests -v
```

## Milestone 3: the finished application

The same table (`rbac.ROLE_MENU`, `rbac.ROLE_CAPS`) now covers the pages that came with the finished application: Approvals, Command Center, Digital Twin, Reports, Notifications and Data Feed Center, plus the Admin page (whose first tab, Users & access, is the Milestone 2 dashboard). New capabilities: `approve` (approve or reject what the agents propose) and `feeder` (upload data). `views_franchise.ROLE_MENU` is the same object as `rbac.ROLE_MENU`, so the menu, the routes and the Admin privilege table cannot disagree. Admin-only tools (Teach Copilot, Copilot insights, policies, data governance, backup) check the `admin` capability on the server.

For a Store Manager or Staff the Copilot also skips the chain-wide agent findings and the live document hits, and any answer that would name another outlet is replaced by a refusal.
