"""
Unit tests for security, bcrypt hashing, and JWT tokens.
"""

import time
import jwt
from Milestone1.src.security import (
    hash_secret,
    verify_secret,
    hash_security_answer,
    verify_security_answer,
    generate_jwt_token,
    verify_jwt_token
)
from Milestone1.src.config import JWT_SECRET, JWT_ALGORITHM

def test_bcrypt_hashing_and_verification():
    raw_password = "SecretPassword@123"
    hashed = hash_secret(raw_password)

    # Hash should be non-empty and start with $2b$
    assert hashed.startswith("$2b$")
    assert hashed != raw_password

    # Correct password verifies
    assert verify_secret(raw_password, hashed)

    # Wrong password fails
    assert not verify_secret("WrongPassword@123", hashed)

def test_security_answer_normalization():
    answer = "  Oxford University  "
    hashed = hash_security_answer(answer)

    # Check varying case and surrounding whitespace
    assert verify_security_answer("oxford university", hashed)
    assert verify_security_answer("OXFORD UNIVERSITY", hashed)
    assert verify_security_answer("   Oxford University   ", hashed)
    assert not verify_security_answer("Cambridge University", hashed)

def test_jwt_generation_and_verification():
    token = generate_jwt_token(user_id=42, username="test_user", email="test@example.com", expiry_hours=1)
    assert isinstance(token, str)

    is_valid, payload, msg = verify_jwt_token(token)
    assert is_valid
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["username"] == "test_user"
    assert payload["email"] == "test@example.com"
    assert msg == "Valid session."

def test_jwt_tampered_token():
    token = generate_jwt_token(user_id=1, username="alice", email="alice@example.com")
    tampered_token = token[:-5] + "abcde"

    is_valid, payload, msg = verify_jwt_token(tampered_token)
    assert not is_valid
    assert payload is None
    assert "Invalid session token" in msg

def test_jwt_expired_token():
    # Construct an expired token manually
    expired_payload = {
        "sub": "1",
        "username": "expired_user",
        "email": "exp@example.com",
        "iat": int(time.time()) - 7200,
        "exp": int(time.time()) - 3600
    }
    expired_token = jwt.encode(expired_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    is_valid, payload, msg = verify_jwt_token(expired_token)
    assert not is_valid
    assert payload is None
    assert "Session has expired" in msg
