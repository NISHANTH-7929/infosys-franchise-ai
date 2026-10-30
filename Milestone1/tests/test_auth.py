"""
Integration tests for complete authentication flows:
1. Signup staging & OTP-gated permanent account creation.
2. Login with username or email, brute-force lockout, and JWT token generation.
3. Forgot password Route A (Security question) & Route B (Email OTP).
4. Admin authentication and credential masking in user catalog.
"""

import os
import tempfile
import pytest
from Milestone1.src.database import init_db, get_connection
from Milestone1.src.config import SECURITY_QUESTIONS, ADMIN_USERNAME, ADMIN_PASSWORD
from Milestone1.src.security import verify_jwt_token
from Milestone1.src.auth_service import (
    register_user,
    stage_signup,
    complete_signup,
    login_user,
    get_security_question_for_user,
    reset_password_with_security_question,
    initiate_forgot_password_otp,
    reset_password_with_otp,
    authenticate_admin,
    get_all_registered_users
)

@pytest.fixture
def auth_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)

def test_signup_otp_gated_flow(auth_db):
    username = "alice_wonder"
    email = "alice@wonderland.org"
    password = "SecurePassword@123"
    question = SECURITY_QUESTIONS[0]
    answer = "Greenwood High"

    # 1. Stage signup
    ok, msg, dev_otp = stage_signup(
        username=username,
        email=email,
        password=password,
        confirm_password=password,
        security_question=question,
        security_answer=answer,
        db_path=auth_db
    )
    assert ok, f"Staging signup failed: {msg}"
    assert dev_otp is not None

    conn = get_connection(auth_db)
    cursor = conn.cursor()

    # 2. Verify account is NOT in permanent users table yet
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    assert cursor.fetchone() is None, "Permanent user account should NOT exist before OTP verification!"

    # 3. Verify record IS staged in pending_signups
    cursor.execute("SELECT * FROM pending_signups WHERE email = ?", (email,))
    staged = cursor.fetchone()
    assert staged is not None
    assert staged["username"] == username
    conn.close()

    # 4. Attempt login before OTP verification -> Must fail
    login_ok, _, _, _ = login_user(username, password, db_path=auth_db)
    assert not login_ok

    # 5. Complete signup with wrong OTP -> Fails
    comp_ok, comp_msg = complete_signup(email, "999999", db_path=auth_db)
    assert not comp_ok
    assert "Incorrect OTP" in comp_msg

    # 6. Complete signup with valid OTP -> Succeeds
    comp_ok, comp_msg = complete_signup(email, dev_otp, db_path=auth_db)
    assert comp_ok
    assert "successfully verified" in comp_msg.lower()

    # 7. Check permanent users table now contains user
    conn = get_connection(auth_db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    assert user is not None
    assert user["username"] == username
    # Password hash must be bcrypt
    assert user["password_hash"].startswith("$2b$")
    assert user["security_answer_hash"].startswith("$2b$")

    # Pending signups record must be cleaned
    cursor.execute("SELECT * FROM pending_signups WHERE email = ?", (email,))
    assert cursor.fetchone() is None
    conn.close()

def test_login_with_username_and_email(auth_db):
    username = "bob_builder"
    email = "bob@builder.com"
    password = "BuilderPass@2026"
    question = SECURITY_QUESTIONS[1]
    answer = "Smith"

    # Stage and verify
    _, _, dev_otp = stage_signup(username, email, password, password, question, answer, db_path=auth_db)
    complete_signup(email, dev_otp, db_path=auth_db)

    # 1. Login with username
    ok, token, msg, user_info = login_user(username, password, db_path=auth_db)
    assert ok
    assert token is not None
    assert user_info["username"] == username
    valid_jwt, payload, _ = verify_jwt_token(token)
    assert valid_jwt
    assert payload["username"] == username

    # 2. Login with email
    ok, token2, msg, user_info2 = login_user(email, password, db_path=auth_db)
    assert ok
    assert token2 is not None
    assert user_info2["email"] == email

    # 3. Wrong password -> generic error
    ok, token3, err_msg, _ = login_user(username, "WrongPassword@123", db_path=auth_db)
    assert not ok
    assert token3 is None
    assert err_msg == "Invalid username/email or password."

def test_login_brute_force_lockout(auth_db):
    username = "target_user"
    email = "target@example.com"
    password = "TargetPassword@123"

    _, _, dev_otp = stage_signup(username, email, password, password, SECURITY_QUESTIONS[0], "Answer", db_path=auth_db)
    complete_signup(email, dev_otp, db_path=auth_db)

    # 3 consecutive failed logins
    for i in range(3):
        ok, _, msg, _ = login_user(username, f"WrongPassword@{i}", db_path=auth_db)
        assert not ok

    # 4th login attempt should report account locked
    ok, _, msg, _ = login_user(username, password, db_path=auth_db)
    assert not ok
    assert "locked" in msg.lower()

def test_forgot_password_route_a_security_question(auth_db):
    username = "charlie"
    email = "charlie@domain.com"
    password = "InitialPassword@123"
    question = SECURITY_QUESTIONS[2]
    answer = "Goldie"

    _, _, dev_otp = stage_signup(username, email, password, password, question, answer, db_path=auth_db)
    complete_signup(email, dev_otp, db_path=auth_db)

    # Retrieve question
    ok, retrieved_q, _ = get_security_question_for_user(username, db_path=auth_db)
    assert ok
    assert retrieved_q == question

    # Wrong answer -> fails
    new_password = "UpdatedPassword@2026"
    ok, msg = reset_password_with_security_question(username, "WrongAnswer", new_password, new_password, db_path=auth_db)
    assert not ok
    assert "incorrect" in msg.lower()

    # Correct answer -> succeeds
    ok, msg = reset_password_with_security_question(username, "goldie", new_password, new_password, db_path=auth_db)
    assert ok

    # Verify login with new password
    login_ok, _, _, _ = login_user(username, new_password, db_path=auth_db)
    assert login_ok

def test_forgot_password_route_b_email_otp(auth_db):
    username = "diana"
    email = "diana@domain.com"
    password = "DianaPassword@123"

    _, _, dev_otp = stage_signup(username, email, password, password, SECURITY_QUESTIONS[0], "Ans", db_path=auth_db)
    complete_signup(email, dev_otp, db_path=auth_db)

    # Request recovery OTP
    ok, msg, rec_otp = initiate_forgot_password_otp(email, db_path=auth_db)
    assert ok
    assert rec_otp is not None

    # Reset password with OTP
    new_pass = "DianaNewPassword@2026"
    ok, msg = reset_password_with_otp(email, rec_otp, new_pass, new_pass, db_path=auth_db)
    assert ok

    # Verify login with updated password
    login_ok, _, _, _ = login_user(email, new_pass, db_path=auth_db)
    assert login_ok

def test_admin_dashboard_security_and_masking(auth_db):
    # Verify admin credentials check
    assert authenticate_admin(ADMIN_USERNAME, ADMIN_PASSWORD)
    assert not authenticate_admin("admin", "WrongAdminPass")

    # Register sample user
    username = "eva_green"
    email = "eva@green.org"
    _, _, dev_otp = stage_signup(username, email, "EvaPass@2026", "EvaPass@2026", SECURITY_QUESTIONS[0], "Ans", db_path=auth_db)
    complete_signup(email, dev_otp, db_path=auth_db)

    users_list = get_all_registered_users(db_path=auth_db)
    assert len(users_list) >= 1

    for u in users_list:
        assert "Username" in u
        assert "Email Address" in u
        # SECURITY REQUIREMENT: Never expose password hashes or security answer hashes
        assert "password" not in u
        assert "password_hash" not in u
        assert "security_answer" not in u
        assert "security_answer_hash" not in u

def test_direct_user_registration(auth_db):
    username = "direct_user"
    email = "direct@example.com"
    password = "DirectPass@2026"
    question = SECURITY_QUESTIONS[0]
    answer = "Central School"

    # Direct registration without OTP
    ok, msg = register_user(
        username=username,
        email=email,
        password=password,
        confirm_password=password,
        security_question=question,
        security_answer=answer,
        db_path=auth_db
    )
    assert ok, f"Registration failed: {msg}"
    assert "successfully registered" in msg.lower()

    # User immediately exists in users table
    conn = get_connection(auth_db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    assert row["email"] == email

    # User can log in immediately
    login_ok, token, _, user_info = login_user(username, password, db_path=auth_db)
    assert login_ok
    assert token is not None

def test_security_question_recovery_with_username_and_email(auth_db):
    username = "dual_rec_user"
    email = "dual_rec@example.com"
    password = "OriginalPassword@123"
    question = SECURITY_QUESTIONS[1]
    answer = "Pet Rover"

    # Register
    ok, _ = register_user(username, email, password, password, question, answer, db_path=auth_db)
    assert ok

    # Retrieve security question using USERNAME
    ok_user, q_user, _ = get_security_question_for_user(username, db_path=auth_db)
    assert ok_user
    assert q_user == question

    # Retrieve security question using EMAIL
    ok_email, q_email, _ = get_security_question_for_user(email, db_path=auth_db)
    assert ok_email
    assert q_email == question

    # Reset password using EMAIL identifier
    new_pass = "ResetViaEmail@2026"
    reset_ok, reset_msg = reset_password_with_security_question(
        email, "pet rover", new_pass, new_pass, db_path=auth_db
    )
    assert reset_ok
    assert "successfully reset" in reset_msg.lower()

    # Can log in with new password
    login_ok, _, _, _ = login_user(username, new_pass, db_path=auth_db)
    assert login_ok

def test_otp_lockout_across_operations(auth_db):
    from Milestone1.src.otp_service import verify_stored_otp

    username = "locked_user"
    email = "locked@example.com"
    password = "LockedPass@123"

    ok, _ = register_user(username, email, password, password, SECURITY_QUESTIONS[0], "Ans", db_path=auth_db)
    assert ok

    # Initiate OTP
    ok_otp, _, _ = initiate_forgot_password_otp(email, db_path=auth_db)
    assert ok_otp

    # 3 consecutive incorrect OTP entries
    for _ in range(2):
        v_ok, v_msg = verify_stored_otp(email, "FORGOT_PASSWORD", "000000", db_path=auth_db)
        assert not v_ok
        assert "remaining" in v_msg

    # 3rd incorrect attempt triggers 15-minute lockout
    v_ok, v_msg = verify_stored_otp(email, "FORGOT_PASSWORD", "000000", db_path=auth_db)
    assert not v_ok
    assert "blocked for 15 minutes" in v_msg.lower() or "maximum attempts" in v_msg.lower()

    # 1. No new OTP can be requested
    can_request, req_msg, _ = initiate_forgot_password_otp(email, db_path=auth_db)
    assert not can_request
    assert "blocked" in req_msg.lower() or "locked" in req_msg.lower()

    # 2. Login is blocked for this account during lockout
    login_ok, _, log_msg, _ = login_user(username, password, db_path=auth_db)
    assert not login_ok
    assert "locked" in log_msg.lower() or "blocked" in log_msg.lower()

    # 3. Security question recovery is blocked during lockout
    sq_ok, _, sq_msg = get_security_question_for_user(email, db_path=auth_db)
    assert not sq_ok
    assert "locked" in sq_msg.lower() or "blocked" in sq_msg.lower()

