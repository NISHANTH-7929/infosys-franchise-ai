from pydantic import BaseModel, Field, validator
import re


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email_2_2_2(email: str) -> str:
    if not EMAIL_RE.match(email):
        raise ValueError("Invalid email format")
    local, domain = email.split("@")
    if len(local) < 2:
        raise ValueError("Email local part must be at least 2 characters")
    if "." not in domain:
        raise ValueError("Email domain must contain a dot")
    name, tld = domain.rsplit(".", 1)
    if len(name) < 2:
        raise ValueError("Email domain name must be at least 2 characters")
    if len(tld) < 2:
        raise ValueError("Email TLD must be at least 2 characters")
    return email


def validate_password_strength(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain an uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain a lowercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain a digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValueError("Password must contain a special character")
    return password


class SignupRequest(BaseModel):
    email: str
    username: str = Field(min_length=2, max_length=64)
    password: str
    confirm_password: str
    role: str = "user"
    outlet: str = "Main"
    security_question: str
    security_answer: str = Field(min_length=2)

    @validator("email")
    def _email(cls, v):
        return validate_email_2_2_2(v)

    @validator("password")
    def _pw(cls, v):
        return validate_password_strength(v)

    @validator("confirm_password")
    def _confirm(cls, v, values):
        if "password" in values and v != values["password"]:
            raise ValueError("Passwords do not match")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class ForgotRequest(BaseModel):
    email: str

    @validator("email")
    def _email(cls, v):
        return validate_email_2_2_2(v)


class ResetRequest(BaseModel):
    email: str
    otp: str
    new_password: str
    confirm_password: str

    @validator("new_password")
    def _pw(cls, v):
        return validate_password_strength(v)

    @validator("confirm_password")
    def _confirm(cls, v, values):
        if "new_password" in values and v != values["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class SecurityResetRequest(BaseModel):
    email: str
    security_answer: str
    new_password: str
    confirm_password: str

    @validator("new_password")
    def _pw(cls, v):
        return validate_password_strength(v)

    @validator("confirm_password")
    def _confirm(cls, v, values):
        if "new_password" in values and v != values["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict
