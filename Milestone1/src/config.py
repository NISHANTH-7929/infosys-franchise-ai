"""
Configuration and secrets management module for Milestone 1.

Designed for educational evaluation in dual environments:
- Google Colab (retrieves secrets via google.colab.userdata)
- Local Development (retrieves from environment variables or .env file)
"""

import os
from pathlib import Path

# Load local .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def get_secret(key: str, default: str = "") -> str:
    """
    Retrieve secret prioritizing Google Colab userdata, then environment variables.
    Never exposes plaintext secrets in logs or exceptions.
    """
    # 1. Try Google Colab userdata
    try:
        from google.colab import userdata  # type: ignore
        val = userdata.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    except Exception:
        pass

    # 2. Try OS environment variables
    env_val = os.getenv(key)
    if env_val is not None and env_val.strip():
        return env_val.strip()

    return default

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "src"

# Database Configuration
DEFAULT_DB_PATH = str(BASE_DIR / "milestone1.db")
DB_PATH = get_secret("DB_PATH", DEFAULT_DB_PATH)

# Authentication & JWT Configuration
JWT_SECRET = get_secret("JWT_SECRET", "infosys-springboard-m1-educational-jwt-secret-key-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 2

# Gmail SMTP Configuration
EMAIL_ADDRESS = get_secret("EMAIL_ADDRESS", "").strip()
EMAIL_PASSWORD = get_secret("EMAIL_PASSWORD", "").replace(" ", "").strip()
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT_SSL = 465
SMTP_PORT_TLS = 587

# OTP Configuration
OTP_EXPIRY_MINUTES = 5
MAX_OTP_ATTEMPTS = 3
OTP_RESEND_COOLDOWN_SECONDS = 60

# Rate Limiting & Lockout
MAX_LOGIN_ATTEMPTS = 3
LOCKOUT_SECONDS = 300  # 5 minutes lockout

# Admin Credentials (For Educational & Demo Evaluation)
ADMIN_USERNAME = get_secret("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD", "Admin@Infosys123")

# ngrok Authtoken
NGROK_AUTHTOKEN = get_secret("NGROK_AUTHTOKEN", "")

# Fixed list of Security Questions for Signup
SECURITY_QUESTIONS = [
    "What was the name of your first school?",
    "What is your mother's maiden name?",
    "What was your favorite childhood pet's name?",
    "What is the name of the city where you were born?",
    "What was the make of your family's first car?"
]
