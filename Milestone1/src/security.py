"""
Security and cryptography module for Milestone 1.

Implements:
1. Salted bcrypt hashing and verification for passwords and security answers.
2. PyJWT session token generation, decoding, and signature verification.
"""

import bcrypt
import datetime
import jwt
from typing import Tuple, Optional, Dict, Any
try:
    from .config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRATION_HOURS
except ImportError:
    try:
        from src.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRATION_HOURS
    except ImportError:
        from config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRATION_HOURS

def hash_secret(secret_text: str) -> str:
    """
    Hashes a plaintext string using bcrypt with an automatically generated salt.
    Returns the string representation of the hash.
    """
    if not isinstance(secret_text, str):
        secret_text = str(secret_text)
    salt = bcrypt.gensalt(rounds=12)
    hashed_bytes = bcrypt.hashpw(secret_text.encode("utf-8"), salt)
    return hashed_bytes.decode("utf-8")

def verify_secret(secret_text: str, stored_hash: str) -> bool:
    """
    Verifies a plaintext string against a stored bcrypt hash using constant-time check.
    """
    if not secret_text or not stored_hash:
        return False
    try:
        return bcrypt.checkpw(secret_text.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception:
        return False

def hash_security_answer(answer: str) -> str:
    """
    Normalizes security answer (trimmed and lowercase) before hashing with bcrypt
    so answering with differing capitalization succeeds securely.
    """
    normalized = answer.strip().lower()
    return hash_secret(normalized)

def verify_security_answer(candidate_answer: str, stored_hash: str) -> bool:
    """
    Verifies normalized candidate security answer against stored hash.
    """
    normalized = candidate_answer.strip().lower()
    return verify_secret(normalized, stored_hash)

def generate_jwt_token(user_id: int, username: str, email: str, expiry_hours: int = JWT_EXPIRATION_HOURS) -> str:
    """
    Generates a cryptographically signed JWT token upon successful user authentication.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    expiration = now + datetime.timedelta(hours=expiry_hours)

    payload = {
        "sub": str(user_id),
        "username": username,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(expiration.timestamp()),
        "iss": "infosys-springboard-auth"
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token

def verify_jwt_token(token: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Decodes and validates a JWT session token.
    Returns: (is_valid, payload, error_message)
    """
    if not token or not isinstance(token, str):
        return False, None, "Session token is missing."

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return True, payload, "Valid session."
    except jwt.ExpiredSignatureError:
        return False, None, "Session has expired. Please log in again."
    except jwt.InvalidTokenError as e:
        return False, None, f"Invalid session token: {str(e)}"
    except Exception as e:
        return False, None, f"Token verification error: {str(e)}"
