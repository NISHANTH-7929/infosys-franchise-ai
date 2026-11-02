import random
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models import User
from schemas import (
    SignupRequest, LoginRequest, ForgotRequest, ResetRequest,
    SecurityResetRequest, TokenResponse,
)
from security import hash_password, verify_password, create_access_token, decode_token
from mailer import send_otp_email, send_reset_link_email

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILED_ATTEMPTS = 5
GENERIC_LOGIN_ERROR = "Invalid email or password"
OTP_VALIDITY_MINUTES = 10


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "outlet": user.outlet,
        "locked": user.locked,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


def user_of(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """Real token-based user resolver (replaces localuser.py)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.locked:
        raise HTTPException(status_code=403, detail="Account is locked")
    return user


@router.post("/signup", response_model=TokenResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        email=payload.email.lower(),
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role or "user",
        outlet=payload.outlet or "Main",
        locked=False,
        failed_attempts=0,
        security_question=payload.security_question,
        security_answer_hash=hash_password(payload.security_answer.strip().lower()),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenResponse(access_token=token, user=_user_dict(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()

    if not user:
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

    if user.locked:
        raise HTTPException(status_code=403, detail="Account is locked. Contact an administrator.")

    if not verify_password(payload.password, user.password_hash):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked = True
        db.commit()
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

    user.failed_attempts = 0
    user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenResponse(access_token=token, user=_user_dict(user))


@router.post("/forgot-password")
def forgot_password(payload: ForgotRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if user and not user.locked:
        otp = f"{random.randint(100000, 999999)}"
        user.otp_code = otp
        user.otp_expires = datetime.utcnow() + timedelta(minutes=OTP_VALIDITY_MINUTES)
        db.commit()
        print(f"[OTP] {user.email} -> {otp}")   # visible in Colab output if mail fails
        send_otp_email(user.email, otp)
    return {"message": "If the email exists, an OTP has been sent."}


@router.post("/reset-password")
def reset_password(payload: ResetRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid reset request")
    if not user.otp_code or not user.otp_expires or user.otp_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="OTP expired or invalid")
    if user.otp_code != payload.otp.strip():
        raise HTTPException(status_code=400, detail="Invalid OTP")

    user.password_hash = hash_password(payload.new_password)
    user.otp_code = None
    user.otp_expires = None
    user.failed_attempts = 0
    user.locked = False
    db.commit()
    return {"message": "Password reset successful"}


@router.post("/reset-with-security")
def reset_with_security(payload: SecurityResetRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not user.security_answer_hash:
        raise HTTPException(status_code=400, detail="Invalid reset request")
    if not verify_password(payload.security_answer.strip().lower(), user.security_answer_hash):
        raise HTTPException(status_code=400, detail="Incorrect security answer")

    user.password_hash = hash_password(payload.new_password)
    user.failed_attempts = 0
    user.locked = False
    db.commit()
    return {"message": "Password reset successful"}


@router.get("/me")
def me(current_user: User = Depends(user_of)):
    return _user_dict(current_user)


@router.post("/send-reset-link")
def send_reset_link(payload: ForgotRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if user and not user.locked:
        token = create_access_token({"sub": str(user.id), "purpose": "reset"})
        send_reset_link_email(user.email, token)
    return {"message": "If the email exists, a reset link has been sent."}
