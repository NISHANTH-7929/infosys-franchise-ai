"""
Database management module for Milestone 1.

Implements a single unified SQLite database for:
1. Permanent user accounts (`users`)
2. Staged unverified registrations (`pending_signups`)
3. One-Time Passwords (`otp_codes`)
4. Rate limiting and lockout counters (`login_attempts`)
"""

import secrets
import sqlite3
import datetime
from pathlib import Path
from typing import Optional
try:
    from .config import DB_PATH, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_EMAIL, ADMIN_ROLE, DEFAULT_ROLE
    from .security import hash_secret
except ImportError:
    try:
        from src.config import DB_PATH, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_EMAIL, ADMIN_ROLE, DEFAULT_ROLE
        from src.security import hash_secret
    except ImportError:
        from config import DB_PATH, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_EMAIL, ADMIN_ROLE, DEFAULT_ROLE
        from security import hash_secret

def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Returns an active SQLite connection configured with row factory.
    """
    path = db_path or DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: Optional[str] = None) -> None:
    """
    Initializes all required tables and indexes in the single SQLite database.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 1. Permanent Users Table (created only after successful signup OTP verification)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL COLLATE NOCASE,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            security_question TEXT NOT NULL,
            security_answer_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    # Role and outlet columns (added for role-based access control); also upgrades older databases
    existing_cols = {row["name"] for row in cursor.execute("PRAGMA table_info(users)").fetchall()}
    if "role" not in existing_cols:
        cursor.execute(f"ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT '{DEFAULT_ROLE}'")
    if "outlet" not in existing_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN outlet TEXT")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

    # 2. Staged Pending Signups Table (temporary storage awaiting signup OTP)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_signups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL COLLATE NOCASE,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            security_question TEXT NOT NULL,
            security_answer_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_email ON pending_signups(email)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_username ON pending_signups(username)")

    # 3. OTP Codes Table (strictly separates SIGNUP and FORGOT_PASSWORD purposes)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS otp_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identifier TEXT NOT NULL COLLATE NOCASE,
            otp_hash TEXT NOT NULL,
            purpose TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3,
            expires_at REAL NOT NULL,
            is_used INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_otp_lookup ON otp_codes(identifier, purpose, is_used)")

    # 4. Login Attempts Table (rate limiting & brute-force lockout)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            identifier TEXT PRIMARY KEY COLLATE NOCASE,
            failed_attempts INTEGER DEFAULT 0,
            last_failed_at REAL DEFAULT 0,
            locked_until REAL DEFAULT 0
        )
    """)

    # 5. Seed the Admin account (password comes from the ADMIN_PASSWORD secret, stored hashed)
    cursor.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (ADMIN_USERNAME,))
    if not cursor.fetchone():
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, security_question, security_answer_hash,
                               created_at, updated_at, role)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (ADMIN_USERNAME, ADMIN_EMAIL.lower(), hash_secret(ADMIN_PASSWORD), "N/A",
              hash_secret(secrets.token_urlsafe(24)), now_str, now_str, ADMIN_ROLE))

    conn.commit()
    conn.close()

def clean_expired_pending_signups(current_time: float, db_path: Optional[str] = None) -> None:
    """
    Prunes expired unverified pending signups so users can re-attempt signup
    if their previous session expired.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pending_signups WHERE expires_at < ?", (current_time,))
    conn.commit()
    conn.close()
