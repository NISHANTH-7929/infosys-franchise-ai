"""The one local operator. There is no login and no role system yet: everybody who opens the app is this admin.
Your Milestone 1 login and the RBAC you build replace this: server.py asks user_of(request) for the current user on every request."""
USER = {"email": "admin@local", "username": "Admin", "role": "Admin", "outlet": None}
