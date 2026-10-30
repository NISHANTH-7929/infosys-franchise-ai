"""
Infosys Springboard Internship 7.0 - Batch 4
Milestone 1: User Authentication Module (Streamlit Application)

Professional light-mode design with Josefin Sans typography.
Clean, modern, single-card corporate authentication portal.

Features:
- Pure light-mode aesthetic, no dark mode
- Josefin Sans typography and crisp card UI
- Unified sign-in for both standard users and administrators
- Single centered login card with form and header merged
- Standard login page pattern: bottom links for "Sign Up" and "Forgot Password"
- Direct account registration without email OTP
- Account locked for 15 minutes upon 3 OTP mismatches
- Password recovery via Security Question (lookup by username or email) or Email OTP
- Protected User and Administrator dashboards with JWT verification
- No sidebar panel: clean centered authentication layout
"""

import sys
import os
import time
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
if str(CURRENT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR.parent))

import streamlit as st
import pandas as pd

try:
    from .config import SECURITY_QUESTIONS, EMAIL_ADDRESS, ADMIN_USERNAME
    from .database import init_db
    from .security import verify_jwt_token
    from .auth_service import (
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
except ImportError:
    try:
        from src.config import SECURITY_QUESTIONS, EMAIL_ADDRESS, ADMIN_USERNAME
        from src.database import init_db
        from src.security import verify_jwt_token
        from src.auth_service import (
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
    except ImportError:
        from config import SECURITY_QUESTIONS, EMAIL_ADDRESS, ADMIN_USERNAME
        from database import init_db
        from security import verify_jwt_token
        from auth_service import (
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

# Ensure database is initialized
init_db()

st.set_page_config(
    page_title="Infosys Springboard — Identity Platform",
    layout="wide",
    initial_sidebar_state="collapsed"
)

GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Josefin+Sans:wght@300;400;600;700&family=Inter:wght@400;500;600&display=swap');

/* ─── Reset & Base ─────────────────────────────────── */
html, body, .stApp {
    background-color: #f8fafc !important;
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
    color: #0f172a !important;
}

header[data-testid="stHeader"] {
    background: transparent !important;
}

.stDeployButton,
header[data-testid="stHeader"] [data-testid="stDecoration"] {
    display: none !important;
}

/* Hide sidebar panel completely */
section[data-testid="stSidebar"],
[data-testid="collapsedControl"] {
    display: none !important;
}

.block-container {
    padding-top: 3.2rem !important;
    padding-bottom: 4rem !important;
    max-width: 1040px !important;
    margin: 0 auto !important;
}

/* ─── Typography ────────────────────────────────────── */
h1, h2, h3, h4, h5, h6 {
    font-family: 'Josefin Sans', sans-serif !important;
    color: #0f172a !important;
    letter-spacing: -0.01em !important;
}

/* ─── Form Inputs ───────────────────────────────────── */
div[data-baseweb="input"] {
    background-color: #ffffff !important;
    border: 1.5px solid #cbd5e1 !important;
    border-radius: 8px !important;
    transition: border-color 0.15s, box-shadow 0.15s !important;
    height: 44px !important;
}

div[data-baseweb="input"]:focus-within {
    border-color: #1a6ef5 !important;
    box-shadow: 0 0 0 3px rgba(26, 110, 245, 0.12) !important;
}

input, textarea {
    color: #0f172a !important;
    -webkit-text-fill-color: #0f172a !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 14px !important;
}

input::placeholder {
    color: #94a3b8 !important;
    -webkit-text-fill-color: #94a3b8 !important;
}

div[data-baseweb="select"] > div {
    background-color: #ffffff !important;
    border: 1.5px solid #cbd5e1 !important;
    border-radius: 8px !important;
    color: #0f172a !important;
    min-height: 44px !important;
}

label[data-testid="stWidgetLabel"] p,
label[data-testid="stWidgetLabel"] span {
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    color: #475569 !important;
    letter-spacing: 0.05em !important;
    text-transform: uppercase !important;
    margin-bottom: 4px !important;
}

/* ─── Forms Styled as Single Bordered Container ──────── */
div[data-testid="stForm"] {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 14px !important;
    padding: 40px 36px 32px 36px !important;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05) !important;
}

div[data-testid="stForm"] div[data-testid="stVerticalBlock"] { gap: 1rem !important; }
div[data-testid="stFormSubmitButton"],
div[data-testid="stElementContainer"]:has(div[data-testid="stFormSubmitButton"]),
div[data-testid="stFormSubmitButton"] > div { width: 100% !important; margin-top: 6px; }
div[data-testid="stColumn"] div[data-testid="stElementContainer"] { width: 100% !important; }
div[data-testid="stColumn"]:last-child .stButton { display: flex; justify-content: flex-end; }
div[data-testid="stFormSubmitButton"] > button { width: 100% !important; }

/* ─── Buttons ────────────────────────────────────────── */
button[kind="primary"],
div[data-testid="stFormSubmitButton"] button {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    background-color: #0f172a !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 13.5px !important;
    font-weight: 700 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    height: 44px !important;
    min-height: 44px !important;
    padding: 0 24px !important;
    width: 100% !important;
    cursor: pointer !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08) !important;
    transition: all 0.15s ease !important;
    margin-top: 8px !important;
}

button[kind="secondary"],
.stButton > button {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    background-color: #ffffff !important;
    color: #475569 !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 8px !important;
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 12.5px !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em !important;
    height: 38px !important;
    min-height: 38px !important;
    padding: 0 16px !important;
    width: 100% !important;
    cursor: pointer !important;
    transition: all 0.15s ease !important;
}

div.stButton > button[kind="tertiary"] {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: #1a6ef5 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
    letter-spacing: 0 !important;
    width: auto !important;
    padding: 0 !important;
}
div.stButton > button[kind="tertiary"]:hover {
    background: transparent !important;
    text-decoration: underline !important;
    color: #0f4fc4 !important;
}

button[kind="primary"]:hover,
div[data-testid="stFormSubmitButton"] button:hover {
    background-color: #1a6ef5 !important;
    box-shadow: 0 4px 12px rgba(26, 110, 245, 0.25) !important;
    transform: translateY(-1px) !important;
    color: #ffffff !important;
}

button[kind="secondary"]:hover,
.stButton > button:hover {
    background-color: #f8fafc !important;
    border-color: #1a6ef5 !important;
    color: #1a6ef5 !important;
}

/* ─── Tabs ──────────────────────────────────────────── */
div[data-baseweb="tab-list"] {
    background: #f1f5f9 !important;
    border-radius: 10px !important;
    padding: 4px !important;
    border: 1px solid #e2e8f0 !important;
    gap: 4px !important;
    margin-bottom: 16px !important;
}

button[data-baseweb="tab"] {
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 12.5px !important;
    font-weight: 600 !important;
    color: #64748b !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
    border-radius: 7px !important;
    border: none !important;
    background: transparent !important;
    padding: 8px 16px !important;
    transition: all 0.15s ease !important;
}

button[data-baseweb="tab"][aria-selected="true"] {
    background: #ffffff !important;
    color: #1a6ef5 !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08) !important;
}

/* ─── Metrics ───────────────────────────────────────── */
div[data-testid="stMetric"] {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
    padding: 18px 22px !important;
}

div[data-testid="stMetricLabel"] p {
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    color: #64748b !important;
    letter-spacing: 0.10em !important;
    text-transform: uppercase !important;
}

div[data-testid="stMetricValue"] {
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 26px !important;
    font-weight: 700 !important;
    color: #0f172a !important;
}

/* ─── DataTable ─────────────────────────────────────── */
div[data-testid="stDataFrame"] {
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}

/* ─── Card component (for Dashboards) ────────────────── */
.ui-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 28px 28px;
    margin-bottom: 20px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

/* ─── Label/Badge ───────────────────────────────────── */
.ui-label {
    display: inline-block;
    font-family: 'Josefin Sans', sans-serif;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    padding: 4px 10px;
    border-radius: 5px;
    margin-bottom: 12px;
}

.ui-label-green {
    background: #ecfdf5;
    color: #059669;
    border: 1px solid #a7f3d0;
}

.ui-label-orange {
    background: #fff7ed;
    color: #c2410c;
    border: 1px solid #fed7aa;
}

/* ─── Info box ──────────────────────────────────────── */
.ui-infobox {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-left: 4px solid #1a6ef5;
    border-radius: 6px;
    padding: 10px 14px;
    font-size: 12.5px;
    color: #1e40af;
    line-height: 1.5;
    margin: 4px 0 14px 0;
}
</style>
"""

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ─── Session State Initialization ─────────────────────────────────────────────
if "auth_view" not in st.session_state:
    st.session_state["auth_view"] = "sign_in"
if "jwt_token" not in st.session_state:
    st.session_state["jwt_token"] = None
if "user_info" not in st.session_state:
    st.session_state["user_info"] = None
if "admin_logged_in" not in st.session_state:
    st.session_state["admin_logged_in"] = False
if "signup_success_msg" not in st.session_state:
    st.session_state["signup_success_msg"] = None

def set_auth_width(px):
    """Narrow, centered column so the auth card reads like a real login card."""
    st.markdown(
        f"<style>.block-container{{max-width:{px}px !important;padding-left:1rem !important;padding-right:1rem !important;}}</style>",
        unsafe_allow_html=True,
    )

def logout_user():
    st.session_state["jwt_token"] = None
    st.session_state["user_info"] = None
    st.session_state["auth_view"] = "sign_in"
    st.rerun()

def logout_admin():
    st.session_state["admin_logged_in"] = False
    st.session_state["user_info"] = None
    st.session_state["auth_view"] = "sign_in"
    st.rerun()

# Active session checks
is_user_authenticated = False
if st.session_state["jwt_token"]:
    is_valid, payload, _ = verify_jwt_token(st.session_state["jwt_token"])
    if is_valid and payload:
        is_user_authenticated = True
    else:
        st.session_state["jwt_token"] = None
        st.session_state["user_info"] = None

is_admin_authenticated = st.session_state["admin_logged_in"]

# ═════════════════════════════════════════════════════════════════════════════
# VIEW: PROTECTED USER DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
if is_user_authenticated:
    user = st.session_state["user_info"] or {}

    st.markdown("""
    <div class="ui-card">
        <span class="ui-label ui-label-green">Authenticated Session &bull; JWT Verified</span>
        <h1 style="font-size: 26px; margin: 8px 0 6px 0;">Welcome, {username}</h1>
        <p style="color: #64748b; font-size: 14px; margin: 0;">
            Your session is secured with a cryptographically signed JSON Web Token (HS256).
        </p>
    </div>
    """.format(username=user.get("username", "User")), unsafe_allow_html=True)

    col_profile, col_session = st.columns([3, 2])

    with col_profile:
        st.markdown("""
        <div class="ui-card">
            <div style="font-family: 'Josefin Sans', sans-serif; font-size: 10.5px; font-weight: 700;
                        letter-spacing: 0.12em; color: #64748b; text-transform: uppercase; margin-bottom: 14px;">
                User Profile
            </div>
            <table style="width: 100%; border-collapse: collapse; font-size: 13.5px;">
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 12px 0; color: #64748b; width: 38%; font-weight: 500;">Username</td>
                    <td style="padding: 12px 0; font-weight: 600; color: #0f172a;">{username}</td>
                </tr>
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 12px 0; color: #64748b; font-weight: 500;">Email</td>
                    <td style="padding: 12px 0; font-weight: 600; color: #0f172a;">{email}</td>
                </tr>
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 12px 0; color: #64748b; font-weight: 500;">System ID</td>
                    <td style="padding: 12px 0; font-family: monospace; font-size: 13px; color: #1a6ef5;">#{uid}</td>
                </tr>
                <tr>
                    <td style="padding: 12px 0; color: #64748b; font-weight: 500;">Registered</td>
                    <td style="padding: 12px 0; color: #334155;">{created}</td>
                </tr>
            </table>
            <div style="margin-top: 18px;" class="ui-infobox">
                <strong>Security Status:</strong> Passwords and security answers are stored as
                salted bcrypt hashes — never in plaintext.
            </div>
        </div>
        """.format(
            username=user.get("username", "N/A"),
            email=user.get("email", "N/A"),
            uid=user.get("id", "N/A"),
            created=user.get("created_at", "N/A")
        ), unsafe_allow_html=True)

    with col_session:
        st.markdown("""
        <div class="ui-card">
            <div style="font-family: 'Josefin Sans', sans-serif; font-size: 10.5px; font-weight: 700;
                        letter-spacing: 0.12em; color: #64748b; text-transform: uppercase; margin-bottom: 14px;">
                Session Control
            </div>
            <p style="font-size: 13px; color: #64748b; line-height: 1.6; margin-bottom: 20px;">
                JWT token claims and signature are verified on every page load.
                You can terminate your session securely at any time.
            </p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Sign Out", key="user_logout_btn"):
            logout_user()

# ═════════════════════════════════════════════════════════════════════════════
# VIEW: PROTECTED ADMINISTRATOR CONSOLE
# ═════════════════════════════════════════════════════════════════════════════
elif is_admin_authenticated:
    st.markdown("""
    <div class="ui-card">
        <span class="ui-label ui-label-orange">Administrative Access &bull; Privileged Console</span>
        <h1 style="font-size: 26px; margin: 8px 0 6px 0;">Administrator Directory</h1>
        <p style="color: #64748b; font-size: 14px; margin: 0;">
            Complete catalog of registered candidate accounts. Password hashes and security answers are strictly masked.
        </p>
    </div>
    """, unsafe_allow_html=True)

    users_data = get_all_registered_users()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Registered Users", len(users_data))
    with c2:
        st.metric("Database Engine", "SQLite")
    with c3:
        st.metric("Active Admin", ADMIN_USERNAME)

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div style="font-family: 'Josefin Sans', sans-serif; font-size: 10.5px; font-weight: 700;
                letter-spacing: 0.12em; color: #64748b; text-transform: uppercase; margin-bottom: 10px;">
        Registered User Accounts
    </div>
    """, unsafe_allow_html=True)

    if users_data:
        df = pd.DataFrame(users_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No accounts registered yet in milestone1.db.")

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
    col_btn, _, _ = st.columns([1, 2, 2])
    with col_btn:
        if st.button("Exit Console", key="admin_exit_btn"):
            logout_admin()

# ═════════════════════════════════════════════════════════════════════════════
# VIEW: PUBLIC AUTHENTICATION PORTAL (CLEAN SINGLE-CARD PATTERN)
# ═════════════════════════════════════════════════════════════════════════════
else:
    cur_view = st.session_state["auth_view"]

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-VIEW: SIGN IN (NARROW CENTERED CARD, HEADING & FORM MERGED)
    # ─────────────────────────────────────────────────────────────────────────
    if cur_view == "sign_in":
        set_auth_width(460)
        with st.container():
            with st.form("unified_login_form"):
                st.markdown("""
                <div style="text-align: center; margin-bottom: 22px;">
                    <div style="font-family: 'Josefin Sans', sans-serif; font-size: 11px; font-weight: 700;
                                letter-spacing: 0.18em; color: #1a6ef5; text-transform: uppercase; margin-bottom: 4px;">
                        Infosys Springboard
                    </div>
                    <h2 style="font-size: 24px; font-weight: 700; margin: 0 0 4px 0; color: #0f172a;">Sign In</h2>
                    <p style="color: #64748b; font-size: 13.5px; margin: 0;">Enter your credentials to continue</p>
                </div>
                """, unsafe_allow_html=True)

                identifier = st.text_input("Username or Email Address", placeholder="Enter username or email", key="uni_id")
                password = st.text_input("Password", type="password", placeholder="Enter your password", key="uni_pw")
                login_submit = st.form_submit_button("Sign In")

                if login_submit:
                    # Check for Administrator credentials first
                    if identifier.strip() == ADMIN_USERNAME and authenticate_admin(identifier, password):
                        st.session_state["admin_logged_in"] = True
                        st.session_state["user_info"] = {"username": ADMIN_USERNAME, "role": "Administrator"}
                        st.success("Administrator authenticated.")
                        st.rerun()
                    else:
                        # Standard User login with rate limiting & lockout
                        success, token, msg, user_info = login_user(identifier, password)
                        if success and token:
                            st.session_state["jwt_token"] = token
                            st.session_state["user_info"] = user_info
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

            # Standard bottom links
            st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button("Create an account", key="goto_signup_btn", type="tertiary"):
                    st.session_state["auth_view"] = "create_account"
                    st.rerun()
            with col_b2:
                if st.button("Forgot password?", key="goto_reset_btn", type="tertiary"):
                    st.session_state["auth_view"] = "reset_password"
                    st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-VIEW: CREATE ACCOUNT (SPACIOUS SINGLE CARD — NO EMAIL OTP)
    # ─────────────────────────────────────────────────────────────────────────
    elif cur_view == "create_account":
        set_auth_width(640)
        with st.container():
            with st.form("direct_signup_form"):
                st.markdown("""
                <div style="text-align: center; margin-bottom: 22px;">
                    <div style="font-family: 'Josefin Sans', sans-serif; font-size: 11px; font-weight: 700;
                                letter-spacing: 0.18em; color: #1a6ef5; text-transform: uppercase; margin-bottom: 4px;">
                        Infosys Springboard
                    </div>
                    <h2 style="font-size: 24px; font-weight: 700; margin: 0 0 4px 0; color: #0f172a;">Create Account</h2>
                    <p style="color: #64748b; font-size: 13.5px; margin: 0;">Instant registration with salted bcrypt encryption</p>
                </div>
                """, unsafe_allow_html=True)

                if st.session_state.get("signup_success_msg"):
                    st.success(st.session_state["signup_success_msg"])

                col1, col2 = st.columns(2)
                with col1:
                    username  = st.text_input("Username", placeholder="e.g. alex_dev", key="reg_u")
                    email     = st.text_input("Email Address", placeholder="e.g. alex@company.com", key="reg_e")
                with col2:
                    password  = st.text_input("Password", type="password", placeholder="8+ characters", key="reg_p")
                    confirm_p = st.text_input("Confirm Password", type="password", placeholder="Re-enter password", key="reg_cp")

                security_question = st.selectbox("Security Question", SECURITY_QUESTIONS, key="reg_sq")
                security_answer   = st.text_input("Security Answer", placeholder="Answer used for account recovery", key="reg_sa")

                st.markdown("""
                <div class="ui-infobox" style="margin-top: 8px; margin-bottom: 8px;">
                    <strong>Security Guarantee:</strong> Passwords and security answers are stored exclusively as salted bcrypt hashes.
                </div>
                """, unsafe_allow_html=True)

                signup_submit = st.form_submit_button("Create Account")

                if signup_submit:
                    ok, msg = register_user(
                        username=username,
                        email=email,
                        password=password,
                        confirm_password=confirm_p,
                        security_question=security_question,
                        security_answer=security_answer
                    )
                    if ok:
                        st.session_state["signup_success_msg"] = msg
                        st.rerun()
                    else:
                        st.error(msg)

            st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
            if st.button("Already have an account? Sign in", key="reg_back_btn", type="tertiary"):
                st.session_state["signup_success_msg"] = None
                st.session_state["auth_view"] = "sign_in"
                st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-VIEW: RESET PASSWORD (SPACIOUS SINGLE CARD WITH TABS)
    # ─────────────────────────────────────────────────────────────────────────
    elif cur_view == "reset_password":
        set_auth_width(560)
        with st.container():
            st.markdown("""
            <div style="text-align: center; margin-bottom: 20px;">
                <div style="font-family: 'Josefin Sans', sans-serif; font-size: 11px; font-weight: 700;
                            letter-spacing: 0.18em; color: #1a6ef5; text-transform: uppercase; margin-bottom: 4px;">
                    Infosys Springboard
                </div>
                <h2 style="font-size: 24px; font-weight: 700; margin: 0 0 4px 0; color: #0f172a;">Password Recovery</h2>
                <p style="color: #64748b; font-size: 13.5px; margin: 0;">Recover access using your security question or email verification code</p>
            </div>
            """, unsafe_allow_html=True)

            if st.session_state.get("recovery_done_msg"):
                st.success(st.session_state.pop("recovery_done_msg"))

            tab_sq, tab_otp = st.tabs(["Security Question", "Email Code"])

            with tab_sq:
                if not st.session_state.get("active_sec_q_user"):
                    with st.form("sec_q_fetch_form"):
                        sq_identifier = st.text_input("Username or Email Address", placeholder="Enter registered username or email", key="sq_uid")
                        fetch_btn = st.form_submit_button("Continue")
                        if fetch_btn:
                            ok, question, msg = get_security_question_for_user(sq_identifier)
                            if ok:
                                st.session_state["active_sec_q_user"] = sq_identifier
                                st.session_state["active_sec_question"] = question
                                st.rerun()
                            else:
                                st.error(msg)
                else:
                    with st.form("sec_q_reset_form"):
                        st.markdown(f"""
                        <div class="ui-infobox">
                            <strong>Security Question:</strong> {st.session_state['active_sec_question']}
                        </div>
                        """, unsafe_allow_html=True)
                        sq_answer    = st.text_input("Security Answer", type="password", placeholder="Enter your answer", key="sq_ans")
                        sq_new_pass  = st.text_input("New Password", type="password", placeholder="Minimum 8 characters", key="sq_np")
                        sq_conf_pass = st.text_input("Confirm New Password", type="password", placeholder="Re-enter new password", key="sq_cp")
                        sq_reset_btn = st.form_submit_button("Update Password")

                        if sq_reset_btn:
                            ok, msg = reset_password_with_security_question(
                                st.session_state["active_sec_q_user"],
                                sq_answer, sq_new_pass, sq_conf_pass
                            )
                            if ok:
                                st.session_state["recovery_done_msg"] = msg
                                del st.session_state["active_sec_question"]
                                del st.session_state["active_sec_q_user"]
                                st.rerun()
                            else:
                                st.error(msg)
                    if st.button("Use a different account", key="sq_change_btn", type="tertiary"):
                        del st.session_state["active_sec_question"]
                        del st.session_state["active_sec_q_user"]
                        st.rerun()

            with tab_otp:
                if not st.session_state.get("active_rec_email"):
                    with st.form("otp_recovery_send_form"):
                        rec_email = st.text_input("Registered Email Address", placeholder="Enter your registered email address", key="rec_em")
                        send_otp_btn = st.form_submit_button("Send Code")

                        if send_otp_btn:
                            ok, msg, dev_otp = initiate_forgot_password_otp(rec_email)
                            if ok:
                                st.session_state["active_rec_email"] = rec_email.strip().lower()
                                st.session_state["rec_send_msg"] = msg
                                st.rerun()
                            else:
                                st.error(msg)
                else:
                    with st.form("otp_recovery_finalize_form"):
                        if st.session_state.get("rec_send_msg"):
                            st.success(st.session_state["rec_send_msg"])
                        st.markdown("""
                        <div class="ui-infobox">
                            3 incorrect codes will block this account for 15 minutes.
                        </div>
                        """, unsafe_allow_html=True)
                        rec_otp      = st.text_input("6-Digit Verification Code", max_chars=6, placeholder="Enter 6-digit code", key="rec_code")
                        rec_new_pass = st.text_input("New Password", type="password", placeholder="Minimum 8 characters", key="rec_np")
                        rec_conf     = st.text_input("Confirm New Password", type="password", placeholder="Re-enter new password", key="rec_cp")
                        rec_reset_btn = st.form_submit_button("Update Password")

                        if rec_reset_btn:
                            ok, msg = reset_password_with_otp(
                                st.session_state["active_rec_email"],
                                rec_otp, rec_new_pass, rec_conf
                            )
                            if ok:
                                st.session_state["recovery_done_msg"] = msg
                                del st.session_state["active_rec_email"]
                                st.rerun()
                            else:
                                st.error(msg)
                    if st.button("Use a different email", key="rec_change_btn", type="tertiary"):
                        del st.session_state["active_rec_email"]
                        st.rerun()

            st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
            if st.button("Back to sign in", key="reset_back_btn", type="tertiary"):
                st.session_state["auth_view"] = "sign_in"
                st.rerun()
