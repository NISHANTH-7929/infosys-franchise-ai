"""
Authentication and user management service for Milestone 1.

Responsibilities:
1. Mandatory Email OTP gated signup:
   - Stages unverified user in `pending_signups`
   - Dispatches 'SIGNUP' OTP
   - Commits permanent account to `users` only upon valid OTP entry
2. Login with dual identifier (Username or Email):
   - Rate limiting and brute-force lockout
   - Constant-time bcrypt password matching
   - Generic error messages (no enumeration)
   - Cryptographic JWT session token generation
3. Forgot Password recovery:
   - Route A: Security Question verification
   - Route B: Email OTP verification ('FORGOT_PASSWORD' context)
4. Admin authentication & masked registered user directory:
   - Strictly hides password and security answer hashes
"""

import time
from typing import Tuple, Optional, Dict, Any, List

try:
    from .config import (
        ADMIN_USERNAME,
        ADMIN_PASSWORD,
        MAX_LOGIN_ATTEMPTS,
        LOCKOUT_SECONDS,
        SECURITY_QUESTIONS,
        DB_PATH
    )
    from .database import get_connection, clean_expired_pending_signups
    from .security import (
        hash_secret,
        verify_secret,
        hash_security_answer,
        verify_security_answer,
        generate_jwt_token
    )
    from .validators import (
        validate_mandatory_fields,
        validate_username,
        validate_email_format,
        validate_password_complexity,
        validate_password_confirmation
    )
    from .otp_service import (
        create_and_store_otp,
        verify_stored_otp,
        send_otp_email
    )
except ImportError:
    try:
        from src.config import (
            ADMIN_USERNAME,
            ADMIN_PASSWORD,
            MAX_LOGIN_ATTEMPTS,
            LOCKOUT_SECONDS,
            SECURITY_QUESTIONS,
            DB_PATH
        )
        from src.database import get_connection, clean_expired_pending_signups
        from src.security import (
            hash_secret,
            verify_secret,
            hash_security_answer,
            verify_security_answer,
            generate_jwt_token
        )
        from src.validators import (
            validate_mandatory_fields,
            validate_username,
            validate_email_format,
            validate_password_complexity,
            validate_password_confirmation
        )
        from src.otp_service import (
            create_and_store_otp,
            verify_stored_otp,
            send_otp_email
        )
    except ImportError:
        from config import (
            ADMIN_USERNAME,
            ADMIN_PASSWORD,
            MAX_LOGIN_ATTEMPTS,
            LOCKOUT_SECONDS,
            SECURITY_QUESTIONS,
            DB_PATH
        )
        from database import get_connection, clean_expired_pending_signups
        from security import (
            hash_secret,
            verify_secret,
            hash_security_answer,
            verify_security_answer,
            generate_jwt_token
        )
        from validators import (
            validate_mandatory_fields,
            validate_username,
            validate_email_format,
            validate_password_complexity,
            validate_password_confirmation
        )
        from otp_service import (
            create_and_store_otp,
            verify_stored_otp,
            send_otp_email
        )

def stage_signup(
    username: str,
    email: str,
    password: str,
    confirm_password: str,
    security_question: str,
    security_answer: str,
    db_path: Optional[str] = None
) -> Tuple[bool, str, Optional[str]]:
    """
    Validates signup details, ensures username/email are unique in permanent accounts,
    stages the unverified account in `pending_signups`, and dispatches an OTP.

    Permanent account is NOT created here.
    Returns: (success, message, dev_otp_for_offline_runs)
    """
    # 1. Validate mandatory fields
    fields = {
        "Username": username,
        "Email": email,
        "Password": password,
        "Confirm Password": confirm_password,
        "Security Question": security_question,
        "Security Answer": security_answer
    }
    is_valid, msg = validate_mandatory_fields(fields)
    if not is_valid:
        return False, msg, None

    # 2. Validate formats
    is_valid, msg = validate_username(username)
    if not is_valid:
        return False, msg, None

    is_valid, msg = validate_email_format(email)
    if not is_valid:
        return False, msg, None

    is_valid, msg = validate_password_complexity(password)
    if not is_valid:
        return False, msg, None

    is_valid, msg = validate_password_confirmation(password, confirm_password)
    if not is_valid:
        return False, msg, None

    if security_question not in SECURITY_QUESTIONS:
        return False, "Please select a valid security question from the provided list.", None

    norm_username = username.strip()
    norm_email = email.strip().lower()

    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 3. Check permanent users table for duplicate username or email
    cursor.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (norm_username,))
    if cursor.fetchone():
        conn.close()
        return False, "Username is already registered. Please choose a different username.", None

    cursor.execute("SELECT id FROM users WHERE email = ? COLLATE NOCASE", (norm_email,))
    if cursor.fetchone():
        conn.close()
        return False, "Email address is already registered. Please use another email or log in.", None

    # 4. Clean expired pending signups
    now_ts = time.time()
    clean_expired_pending_signups(now_ts, db_path)

    # Invalidate any previous pending signup for this email/username
    cursor.execute("DELETE FROM pending_signups WHERE email = ? OR username = ?", (norm_email, norm_username))

    # 5. Hash credentials
    password_hash = hash_secret(password)
    answer_hash = hash_security_answer(security_answer)

    # 6. Stage in pending_signups (valid for 15 minutes)
    expires_at = now_ts + (15 * 60)
    created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now_ts))

    cursor.execute("""
        INSERT INTO pending_signups (username, email, password_hash, security_question, security_answer_hash, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (norm_username, norm_email, password_hash, security_question, answer_hash, created_at, expires_at))
    conn.commit()
    conn.close()

    # 7. Generate and send SIGNUP OTP
    otp_ok, otp_code, otp_msg = create_and_store_otp(norm_email, "SIGNUP", db_path)
    if not otp_ok:
        return False, f"Failed to generate signup OTP: {otp_msg}", None

    email_ok, email_msg = send_otp_email(norm_email, otp_code, "SIGNUP")

    status_note = f"Verification OTP sent to {norm_email}."
    if not email_ok:
        status_note += f" [Notice: {email_msg}]"

    return True, status_note, otp_code

def complete_signup(
    email: str,
    otp_code: str,
    db_path: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Verifies the signup OTP code. Upon successful verification, moves the staged
    registration into the permanent `users` table and clears the pending record.
    """
    norm_email = email.strip().lower()
    otp_code = otp_code.strip()

    if not norm_email:
        return False, "Email address is required."
    if not otp_code:
        return False, "Please enter the OTP verification code."

    # 1. Verify OTP with 'SIGNUP' purpose
    is_valid, msg = verify_stored_otp(norm_email, "SIGNUP", otp_code, db_path)
    if not is_valid:
        return False, msg

    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 2. Retrieve staged registration
    now_ts = time.time()
    cursor.execute("""
        SELECT username, email, password_hash, security_question, security_answer_hash, expires_at
        FROM pending_signups
        WHERE email = ?
    """, (norm_email,))
    staged = cursor.fetchone()

    if not staged:
        conn.close()
        return False, "No pending registration found for this email, or it may have already been completed."

    if now_ts > staged["expires_at"]:
        cursor.execute("DELETE FROM pending_signups WHERE email = ?", (norm_email,))
        conn.commit()
        conn.close()
        return False, "Pending registration has expired. Please fill out the signup form again."

    # 3. Commit to permanent users table
    created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now_ts))
    try:
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, security_question, security_answer_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            staged["username"],
            staged["email"],
            staged["password_hash"],
            staged["security_question"],
            staged["security_answer_hash"],
            created_at,
            created_at
        ))
        # Remove staged entry
        cursor.execute("DELETE FROM pending_signups WHERE email = ?", (norm_email,))
        conn.commit()
        conn.close()
        return True, "Account successfully verified and created! You can now log in."
    except Exception as e:
        conn.close()
        return False, f"Failed to finalize account creation: {str(e)}"

def login_user(
    identifier: str,
    password: str,
    db_path: Optional[str] = None
) -> Tuple[bool, Optional[str], str, Optional[Dict[str, Any]]]:
    """
    Authenticates user using Username OR Email and password.
    Enforces rate-limiting and brute-force lockout.
    Returns generic error messages on authentication failure to prevent enumeration.

    Returns: (success, jwt_token_or_none, message, user_info_dict)
    """
    norm_id = identifier.strip()
    if not norm_id or not password:
        return False, None, "Username/Email and password are both mandatory.", None

    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_ts = time.time()

    # 1. Check rate-limit & lockout status
    cursor.execute("SELECT failed_attempts, locked_until FROM login_attempts WHERE identifier = ?", (norm_id.lower(),))
    attempt_row = cursor.fetchone()

    if attempt_row and attempt_row["locked_until"] and attempt_row["locked_until"] > now_ts:
        remaining_secs = int(attempt_row["locked_until"] - now_ts)
        conn.close()
        return False, None, f"Too many failed login attempts. Account temporarily locked for {remaining_secs} seconds.", None

    # 2. Look up user by username OR email
    cursor.execute("""
        SELECT id, username, email, password_hash, created_at
        FROM users
        WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE
    """, (norm_id, norm_id))
    user_row = cursor.fetchone()

    if not user_row:
        # Increment failed attempts for this identifier
        _record_failed_login(cursor, norm_id.lower(), attempt_row, now_ts)
        conn.commit()
        conn.close()
        return False, None, "Invalid username/email or password.", None

    # 3. Verify password hash
    stored_hash = user_row["password_hash"]
    if not verify_secret(password, stored_hash):
        _record_failed_login(cursor, norm_id.lower(), attempt_row, now_ts)
        conn.commit()
        conn.close()
        return False, None, "Invalid username/email or password.", None

    # 4. Successful Login: clear login attempts
    cursor.execute("DELETE FROM login_attempts WHERE identifier = ?", (norm_id.lower(),))
    cursor.execute("DELETE FROM login_attempts WHERE identifier = ?", (user_row["username"].lower(),))
    cursor.execute("DELETE FROM login_attempts WHERE identifier = ?", (user_row["email"].lower(),))
    conn.commit()
    conn.close()

    # 5. Issue JWT session token
    user_id = user_row["id"]
    username = user_row["username"]
    email = user_row["email"]
    token = generate_jwt_token(user_id=user_id, username=username, email=email)

    user_info = {
        "id": user_id,
        "username": username,
        "email": email,
        "created_at": user_row["created_at"]
    }

    return True, token, "Login successful.", user_info

def _record_failed_login(cursor, identifier: str, attempt_row, now_ts: float):
    current_attempts = (attempt_row["failed_attempts"] if attempt_row else 0) + 1
    locked_until = 0.0

    if current_attempts >= MAX_LOGIN_ATTEMPTS:
        locked_until = now_ts + LOCKOUT_SECONDS

    cursor.execute("""
        INSERT INTO login_attempts (identifier, failed_attempts, last_failed_at, locked_until)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(identifier) DO UPDATE SET
            failed_attempts = excluded.failed_attempts,
            last_failed_at = excluded.last_failed_at,
            locked_until = excluded.locked_until
    """, (identifier, current_attempts, now_ts, locked_until))

# --- Forgot Password: Route A (Security Question) ---

def get_security_question_for_user(
    username: str,
    db_path: Optional[str] = None
) -> Tuple[bool, Optional[str], str]:
    """
    Retrieves the security question stored during signup for the given username.
    """
    norm_user = username.strip()
    if not norm_user:
        return False, None, "Username is required."

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT security_question
        FROM users
        WHERE username = ? COLLATE NOCASE
    """, (norm_user,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return False, None, "User not found."

    return True, row["security_question"], "Security question retrieved."

def reset_password_with_security_question(
    username: str,
    security_answer: str,
    new_password: str,
    confirm_password: str,
    db_path: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Verifies user's security answer and updates password if complex and confirmed.
    """
    norm_user = username.strip()
    norm_answer = security_answer.strip()

    fields = {
        "Username": norm_user,
        "Security Answer": norm_answer,
        "New Password": new_password,
        "Confirm Password": confirm_password
    }
    is_valid, msg = validate_mandatory_fields(fields)
    if not is_valid:
        return False, msg

    is_valid, msg = validate_password_complexity(new_password)
    if not is_valid:
        return False, msg

    is_valid, msg = validate_password_confirmation(new_password, confirm_password)
    if not is_valid:
        return False, msg

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, security_answer_hash
        FROM users
        WHERE username = ? COLLATE NOCASE
    """, (norm_user,))
    user_row = cursor.fetchone()

    if not user_row:
        conn.close()
        return False, "User not found."

    stored_answer_hash = user_row["security_answer_hash"]
    if not verify_security_answer(norm_answer, stored_answer_hash):
        conn.close()
        return False, "Incorrect security answer."

    new_hash = hash_secret(new_password)
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))

    cursor.execute("""
        UPDATE users
        SET password_hash = ?, updated_at = ?
        WHERE id = ?
    """, (new_hash, now_str, user_row["id"]))
    conn.commit()
    conn.close()

    return True, "Password has been successfully reset! You can now log in with your new password."

# --- Forgot Password: Route B (Email OTP) ---

def initiate_forgot_password_otp(
    email: str,
    db_path: Optional[str] = None
) -> Tuple[bool, str, Optional[str]]:
    """
    Initiates password recovery via Email OTP for a registered email.
    """
    norm_email = email.strip().lower()
    is_valid, msg = validate_email_format(norm_email)
    if not is_valid:
        return False, msg, None

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ? COLLATE NOCASE", (norm_email,))
    user_row = cursor.fetchone()
    conn.close()

    if not user_row:
        return False, "No registered account found with this email address.", None

    otp_ok, otp_code, otp_msg = create_and_store_otp(norm_email, "FORGOT_PASSWORD", db_path)
    if not otp_ok:
        return False, f"Failed to generate recovery OTP: {otp_msg}", None

    email_ok, email_msg = send_otp_email(norm_email, otp_code, "FORGOT_PASSWORD")

    status_note = f"Password recovery OTP sent to {norm_email}."
    if not email_ok:
        status_note += f" [Notice: {email_msg}]"

    return True, status_note, otp_code

def reset_password_with_otp(
    email: str,
    otp_code: str,
    new_password: str,
    confirm_password: str,
    db_path: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Verifies the recovery OTP and updates the user's password.
    """
    norm_email = email.strip().lower()

    fields = {
        "Email": norm_email,
        "OTP Code": otp_code,
        "New Password": new_password,
        "Confirm Password": confirm_password
    }
    is_valid, msg = validate_mandatory_fields(fields)
    if not is_valid:
        return False, msg

    is_valid, msg = validate_password_complexity(new_password)
    if not is_valid:
        return False, msg

    is_valid, msg = validate_password_confirmation(new_password, confirm_password)
    if not is_valid:
        return False, msg

    # Verify 'FORGOT_PASSWORD' OTP
    is_valid, msg = verify_stored_otp(norm_email, "FORGOT_PASSWORD", otp_code, db_path)
    if not is_valid:
        return False, msg

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ? COLLATE NOCASE", (norm_email,))
    user_row = cursor.fetchone()

    if not user_row:
        conn.close()
        return False, "User account not found."

    new_hash = hash_secret(new_password)
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))

    cursor.execute("""
        UPDATE users
        SET password_hash = ?, updated_at = ?
        WHERE id = ?
    """, (new_hash, now_str, user_row["id"]))
    conn.commit()
    conn.close()

    return True, "Password has been successfully reset! You can now log in with your new password."

# --- Admin Operations ---

def authenticate_admin(username: str, password: str) -> bool:
    """
    Authenticates administrative user against secure configuration.
    """
    if not username or not password:
        return False
    return (username.strip() == ADMIN_USERNAME) and (password.strip() == ADMIN_PASSWORD)

def get_all_registered_users(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns registered users catalog for Admin Dashboard.
    Strictly excludes password hashes and security answer hashes.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, created_at, updated_at
        FROM users
        ORDER BY id ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    users_list = []
    for r in rows:
        users_list.append({
            "User ID": r["id"],
            "Username": r["username"],
            "Email Address": r["email"],
            "Registration Date": r["created_at"],
            "Status": "Active"
        })
    return users_list
