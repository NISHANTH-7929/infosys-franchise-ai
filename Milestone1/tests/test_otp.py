"""
Unit tests for OTP generation, database hashing, attempt limits, expiry, and separation of purposes.
"""

import time
import os
import tempfile
import pytest
from Milestone1.src.database import init_db, get_connection
from Milestone1.src.otp_service import (
    generate_numeric_otp,
    create_and_store_otp,
    verify_stored_otp
)

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)

def test_numeric_otp_format():
    otp = generate_numeric_otp(6)
    assert len(otp) == 6
    assert otp.isdigit()

def test_otp_creation_and_hashing(temp_db):
    email = "test@example.com"
    success, otp_code, msg = create_and_store_otp(email, "SIGNUP", temp_db)
    assert success
    assert len(otp_code) == 6

    # Verify that plaintext OTP is NOT in database
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT otp_hash FROM otp_codes WHERE identifier = ?", (email,))
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["otp_hash"].startswith("$2b$")
    assert otp_code not in row["otp_hash"]

def test_otp_successful_verification(temp_db):
    email = "student@infosys.com"
    _, otp_code, _ = create_and_store_otp(email, "SIGNUP", temp_db)

    is_valid, msg = verify_stored_otp(email, "SIGNUP", otp_code, temp_db)
    assert is_valid
    assert "verified successfully" in msg.lower()

    # Once verified, it cannot be reused (one-time verification)
    is_valid_again, msg_again = verify_stored_otp(email, "SIGNUP", otp_code, temp_db)
    assert not is_valid_again
    assert "No active OTP request" in msg_again

def test_otp_separate_purposes(temp_db):
    # Ensure signup OTP and password-recovery OTP are separate
    email = "dual@example.com"
    _, signup_otp, _ = create_and_store_otp(email, "SIGNUP", temp_db)
    _, recovery_otp, _ = create_and_store_otp(email, "FORGOT_PASSWORD", temp_db)

    # Trying to verify signup OTP with FORGOT_PASSWORD purpose must fail
    is_valid, _ = verify_stored_otp(email, "FORGOT_PASSWORD", signup_otp, temp_db)
    assert not is_valid

    # Recovery OTP must verify with FORGOT_PASSWORD purpose
    is_valid, _ = verify_stored_otp(email, "FORGOT_PASSWORD", recovery_otp, temp_db)
    assert is_valid

def test_otp_attempt_limits(temp_db):
    email = "limit@example.com"
    _, real_otp, _ = create_and_store_otp(email, "SIGNUP", temp_db)

    # 1st wrong attempt
    valid, msg = verify_stored_otp(email, "SIGNUP", "000000", temp_db)
    assert not valid
    assert "2 attempt(s) remaining" in msg

    # 2nd wrong attempt
    valid, msg = verify_stored_otp(email, "SIGNUP", "111111", temp_db)
    assert not valid
    assert "1 attempt(s) remaining" in msg

    # 3rd wrong attempt: should invalidate
    valid, msg = verify_stored_otp(email, "SIGNUP", "222222", temp_db)
    assert not valid
    assert "Maximum attempts" in msg

    # Now even the correct OTP should be rejected because code was invalidated
    valid, msg = verify_stored_otp(email, "SIGNUP", real_otp, temp_db)
    assert not valid
    assert "No active OTP request" in msg

def test_otp_expired(temp_db):
    email = "expired@example.com"
    _, otp_code, _ = create_and_store_otp(email, "SIGNUP", temp_db)

    # Artificially expire the OTP in database
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("UPDATE otp_codes SET expires_at = ? WHERE identifier = ?", (time.time() - 100, email))
    conn.commit()
    conn.close()

    valid, msg = verify_stored_otp(email, "SIGNUP", otp_code, temp_db)
    assert not valid
    assert "expired" in msg.lower()
