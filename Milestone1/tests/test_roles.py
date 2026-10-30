"""
Unit tests for the role and outlet columns, the seeded Admin account and role-carrying JWTs.
"""

import os
import tempfile
import pytest
from Milestone1.src.database import init_db, get_connection
from Milestone1.src.config import SECURITY_QUESTIONS, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_ROLE, DEFAULT_ROLE
from Milestone1.src.security import verify_jwt_token
from Milestone1.src.auth_service import register_user, login_user, get_all_registered_users

@pytest.fixture
def role_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.remove(path)

def test_admin_is_seeded_with_admin_role(role_db):
    conn = get_connection(role_db)
    row = conn.execute("SELECT role, password_hash FROM users WHERE username = ?", (ADMIN_USERNAME,)).fetchone()
    conn.close()
    assert row["role"] == ADMIN_ROLE
    assert row["password_hash"] != ADMIN_PASSWORD  # stored hashed, never plain

def test_init_db_does_not_duplicate_admin(role_db):
    init_db(role_db)
    conn = get_connection(role_db)
    count = conn.execute("SELECT COUNT(*) AS c FROM users WHERE username = ?", (ADMIN_USERNAME,)).fetchone()["c"]
    conn.close()
    assert count == 1

def test_new_user_gets_default_role_and_token_carries_it(role_db):
    ok, _ = register_user("role_user", "role@user.org", "RolePass@2026", "RolePass@2026",
                          SECURITY_QUESTIONS[0], "Ans", db_path=role_db)
    assert ok
    ok, token, _, info = login_user("role_user", "RolePass@2026", db_path=role_db)
    assert ok
    assert info["role"] == DEFAULT_ROLE
    valid, payload, _ = verify_jwt_token(token)
    assert valid and payload["role"] == DEFAULT_ROLE

def test_user_directory_lists_role_without_hashes(role_db):
    users = get_all_registered_users(db_path=role_db)
    assert all("Role" in u and "Outlet" in u for u in users)
    assert all("password_hash" not in u for u in users)

def test_old_database_is_upgraded(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, security_question TEXT NOT NULL,
        security_answer_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    conn.execute("INSERT INTO users (username,email,password_hash,security_question,security_answer_hash,created_at,updated_at)"
                 " VALUES ('old','old@user.org','x','q','y','t','t')")
    conn.commit()
    conn.close()
    init_db(path)
    conn = get_connection(path)
    assert conn.execute("SELECT role FROM users WHERE username='old'").fetchone()["role"] == DEFAULT_ROLE
    conn.close()
