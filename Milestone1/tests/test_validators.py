"""
Unit tests for input validation rules according to Infosys Milestone 1 requirements.
"""

import pytest
from Milestone1.src.validators import (
    validate_mandatory_fields,
    validate_email_format,
    validate_password_complexity,
    validate_password_confirmation,
    validate_username
)

def test_mandatory_fields_empty():
    fields = {"Username": "john", "Email": "", "Password": "SecretPassword1@"}
    valid, msg = validate_mandatory_fields(fields)
    assert not valid
    assert "Email" in msg

def test_mandatory_fields_whitespace():
    fields = {"Username": "  ", "Email": "john@example.com"}
    valid, msg = validate_mandatory_fields(fields)
    assert not valid
    assert "Username" in msg

def test_mandatory_fields_success():
    fields = {"Username": "john_doe", "Email": "john@example.com", "Password": "SecretPassword1@"}
    valid, msg = validate_mandatory_fields(fields)
    assert valid
    assert msg == ""

def test_email_format_infosys_rule():
    # Valid shape (at least 2 chars before @, between @ and dot, and after dot)
    valid_emails = [
        "ab@cd.ef",
        "john.doe@company.org",
        "intern2026@infosys.co.in",
        "user_123@domain.ac.uk"
    ]
    for email in valid_emails:
        valid, msg = validate_email_format(email)
        assert valid, f"Expected {email} to be valid, got: {msg}"

    # Invalid: less than 2 chars before @
    valid, msg = validate_email_format("a@cd.ef")
    assert not valid
    assert "at least 2 characters before" in msg

    # Invalid: less than 2 chars between @ and dot
    valid, msg = validate_email_format("ab@c.ef")
    assert not valid
    assert "at least 2 characters between" in msg

    # Invalid: less than 2 chars after final dot
    valid, msg = validate_email_format("ab@cd.e")
    assert not valid
    assert "at least 2 characters after" in msg

    # Invalid: missing @ or dot
    valid, _ = validate_email_format("plainaddress")
    assert not valid

    valid, _ = validate_email_format("user@nodot")
    assert not valid

def test_password_complexity():
    # Valid passwords: >=8 chars, uppercase, lowercase, digit, special symbol
    assert validate_password_complexity("Strong@123")[0]
    assert validate_password_complexity("Infosys#2026")[0]
    assert validate_password_complexity("P@ssw0rd!xyz")[0]

    # Too short (< 8 chars)
    valid, msg = validate_password_complexity("Ab1@")
    assert not valid
    assert "at least 8 characters" in msg

    # Missing uppercase
    valid, msg = validate_password_complexity("strong@123")
    assert not valid
    assert "uppercase" in msg

    # Missing lowercase
    valid, msg = validate_password_complexity("STRONG@123")
    assert not valid
    assert "lowercase" in msg

    # Missing digit
    valid, msg = validate_password_complexity("Strong@Password")
    assert not valid
    assert "numeric digit" in msg

    # Missing special character
    valid, msg = validate_password_complexity("StrongPass123")
    assert not valid
    assert "special symbol" in msg

def test_password_confirmation():
    valid, _ = validate_password_confirmation("Secret123!", "Secret123!")
    assert valid

    valid, msg = validate_password_confirmation("Secret123!", "Different123!")
    assert not valid
    assert "does not match" in msg

def test_username_format():
    assert validate_username("john_doe")[0]
    assert validate_username("user123")[0]
    assert validate_username("abc")[0]

    # Too short (<3 chars)
    valid, _ = validate_username("ab")
    assert not valid

    # Invalid characters (spaces, special symbols)
    valid, _ = validate_username("john doe")
    assert not valid

    valid, _ = validate_username("john@doe")
    assert not valid
