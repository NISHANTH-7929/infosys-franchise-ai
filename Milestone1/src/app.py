"""
Infosys Springboard Internship 7.0 - Batch 4
Milestone 1: User Authentication Module (Streamlit Application)

Professional light-mode design with Josefin Sans typography.
Clean, precise, and built for a corporate authentication platform.

Features:
- Pure light-mode aesthetic, no dark mode
- Josefin Sans headings and UI labels
- Mandatory Email OTP registration
- Multi-identifier login (Username or Email)
- HS256 JWT session tokens
- Dual-route password recovery
- Protected User and Administrator dashboards
"""

import sys
import os
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

init_db()

st.set_page_config(
    page_title="Infosys Springboard — Authentication Portal",
    layout="wide",
    initial_sidebar_state="expanded"
)

GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Josefin+Sans:wght@300;400;600;700&family=Inter:wght@400;500;600&display=swap');

/* ─── Reset & Base ─────────────────────────────────── */
html, body, .stApp {
    background-color: #f6f8fb !important;
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
    color: #0d1117 !important;
}

header[data-testid="stHeader"] {
    background: transparent !important;
}

.stDeployButton,
header[data-testid="stHeader"] [data-testid="stDecoration"] {
    display: none !important;
}

.block-container {
    padding-top: 2rem !important;
    padding-bottom: 4rem !important;
    max-width: 1080px !important;
}

/* ─── Typography ────────────────────────────────────── */
h1, h2, h3, h4, h5, h6 {
    font-family: 'Josefin Sans', sans-serif !important;
    color: #0d1117 !important;
    letter-spacing: -0.01em !important;
}

/* ─── Sidebar ───────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background-color: #ffffff !important;
    border-right: 1px solid #e2e6ea !important;
    padding-top: 0 !important;
}

section[data-testid="stSidebar"] .block-container {
    padding-top: 1.5rem !important;
    padding-left: 1.25rem !important;
    padding-right: 1.25rem !important;
}

/* Sidebar radio items */
div[data-testid="stRadio"] > div {
    gap: 6px !important;
    flex-direction: column !important;
}

div[data-testid="stRadio"] label {
    background: #f6f8fb !important;
    border: 1px solid #e2e6ea !important;
    border-radius: 8px !important;
    padding: 10px 14px !important;
    margin: 0 !important;
    transition: background 0.15s, border-color 0.15s !important;
    cursor: pointer !important;
}

div[data-testid="stRadio"] label:hover {
    background: #eef2f8 !important;
    border-color: #c5cfe0 !important;
}

div[data-testid="stRadio"] label p {
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 13.5px !important;
    font-weight: 600 !important;
    color: #1e2a3a !important;
    letter-spacing: 0.02em !important;
    margin: 0 !important;
}

/* ─── Form Inputs ───────────────────────────────────── */
div[data-baseweb="input"] {
    background-color: #ffffff !important;
    border: 1.5px solid #d0d7df !important;
    border-radius: 8px !important;
    transition: border-color 0.15s, box-shadow 0.15s !important;
}

div[data-baseweb="input"]:focus-within {
    border-color: #1a6ef5 !important;
    box-shadow: 0 0 0 3px rgba(26, 110, 245, 0.10) !important;
}

input, textarea {
    color: #0d1117 !important;
    -webkit-text-fill-color: #0d1117 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 14.5px !important;
}

input::placeholder {
    color: #9da8b5 !important;
    -webkit-text-fill-color: #9da8b5 !important;
}

div[data-baseweb="select"] > div {
    background-color: #ffffff !important;
    border: 1.5px solid #d0d7df !important;
    border-radius: 8px !important;
    color: #0d1117 !important;
}

label[data-testid="stWidgetLabel"] p,
label[data-testid="stWidgetLabel"] span {
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    color: #3d4f63 !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}

/* ─── Buttons — ALL selectors to cover every Streamlit version ─── */
button[kind="primary"],
button[kind="secondary"],
button[kind="tertiary"],
button[kind="formSubmit"],
div[data-testid="stButton"] button,
div[data-testid="stFormSubmitButton"] button,
.stButton > button,
.stFormSubmitButton > button,
[data-testid="stButton"] > button,
[data-testid="stFormSubmitButton"] > button {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    background-color: #1a1f2e !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 13.5px !important;
    font-weight: 700 !important;
    letter-spacing: 0.09em !important;
    text-transform: uppercase !important;
    height: 44px !important;
    min-height: 44px !important;
    padding: 0 24px !important;
    width: 100% !important;
    cursor: pointer !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.10), 0 2px 8px rgba(0,0,0,0.06) !important;
    transition: background-color 0.18s ease, box-shadow 0.18s ease, transform 0.12s ease !important;
    -webkit-appearance: none !important;
    -moz-appearance: none !important;
    appearance: none !important;
    text-decoration: none !important;
    outline: none !important;
}

div[data-testid="stButton"] button:hover,
div[data-testid="stFormSubmitButton"] button:hover,
.stButton > button:hover,
.stFormSubmitButton > button:hover,
[data-testid="stButton"] > button:hover,
[data-testid="stFormSubmitButton"] > button:hover {
    background-color: #1a6ef5 !important;
    box-shadow: 0 4px 14px rgba(26, 110, 245, 0.28) !important;
    transform: translateY(-1px) !important;
    color: #ffffff !important;
}

div[data-testid="stButton"] button:active,
div[data-testid="stFormSubmitButton"] button:active,
.stButton > button:active,
.stFormSubmitButton > button:active {
    transform: translateY(0px) !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.12) !important;
    background-color: #1559c9 !important;
}

/* ─── Tabs ──────────────────────────────────────────── */
div[data-baseweb="tab-list"] {
    background: #edf0f4 !important;
    border-radius: 10px !important;
    padding: 4px !important;
    border: 1px solid #e0e4ea !important;
    gap: 4px !important;
    margin-bottom: 20px !important;
}

button[data-baseweb="tab"] {
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 13.5px !important;
    font-weight: 600 !important;
    color: #6b7b8e !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
    border-radius: 7px !important;
    border: none !important;
    background: transparent !important;
    padding: 8px 18px !important;
    transition: all 0.15s ease !important;
}

button[data-baseweb="tab"][aria-selected="true"] {
    background: #ffffff !important;
    color: #1a6ef5 !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.10) !important;
}

button[data-baseweb="tab"]:hover {
    color: #1a1f2e !important;
}

/* ─── Metrics ───────────────────────────────────────── */
div[data-testid="stMetric"] {
    background: #ffffff !important;
    border: 1px solid #e2e6ea !important;
    border-radius: 10px !important;
    padding: 18px 22px !important;
}

div[data-testid="stMetricLabel"] p {
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    color: #7b8fa3 !important;
    letter-spacing: 0.10em !important;
    text-transform: uppercase !important;
}

div[data-testid="stMetricValue"] {
    font-family: 'Josefin Sans', sans-serif !important;
    font-size: 26px !important;
    font-weight: 700 !important;
    color: #0d1117 !important;
}

/* ─── Alerts ────────────────────────────────────────── */
div[data-testid="stAlert"] {
    border-radius: 8px !important;
    font-size: 13.5px !important;
}

/* ─── DataTable ─────────────────────────────────────── */
div[data-testid="stDataFrame"] {
    border: 1px solid #e2e6ea !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}

/* ─── Separator ─────────────────────────────────────── */
hr {
    border-color: #e2e6ea !important;
    margin: 18px 0 !important;
}

/* ─── Card component ────────────────────────────────── */
.ui-card {
    background: #ffffff;
    border: 1px solid #e2e6ea;
    border-radius: 14px;
    padding: 32px 30px;
    margin-bottom: 22px;
    box-shadow: 0 1px 4px rgba(13,17,23,0.03), 0 4px 16px rgba(13,17,23,0.03);
}

.ui-card-sm {
    background: #ffffff;
    border: 1px solid #e2e6ea;
    border-radius: 12px;
    padding: 22px 22px;
    margin-bottom: 16px;
    box-shadow: 0 1px 3px rgba(13,17,23,0.04);
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

.ui-label-blue {
    background: #eef3fd;
    color: #1a6ef5;
    border: 1px solid #c5d9fb;
}

.ui-label-green {
    background: #eafaf3;
    color: #078a56;
    border: 1px solid #b3e8d0;
}

.ui-label-orange {
    background: #fff7ed;
    color: #c05600;
    border: 1px solid #fcd5a0;
}

/* ─── Divider line ──────────────────────────────────── */
.ui-divider {
    height: 1px;
    background: #e8ecf0;
    margin: 20px 0;
}

/* ─── Info box ──────────────────────────────────────── */
.ui-infobox {
    background: #f4f7fe;
    border: 1px solid #d0ddf8;
    border-left: 4px solid #1a6ef5;
    border-radius: 6px;
    padding: 12px 16px;
    font-size: 13px;
    color: #2c4174;
    line-height: 1.6;
}
</style>
"""

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ─── Session State ───────────────────────────────────────────────────────────
if "jwt_token" not in st.session_state:
    st.session_state["jwt_token"] = None
if "user_info" not in st.session_state:
    st.session_state["user_info"] = None
if "admin_logged_in" not in st.session_state:
    st.session_state["admin_logged_in"] = False
if "signup_stage" not in st.session_state:
    st.session_state["signup_stage"] = "FORM"
if "signup_email" not in st.session_state:
    st.session_state["signup_email"] = ""

def logout_user():
    st.session_state["jwt_token"] = None
    st.session_state["user_info"] = None
    if "main_navigation_menu" in st.session_state:
        st.session_state["main_navigation_menu"] = "Sign In"
    st.rerun()

def logout_admin():
    st.session_state["admin_logged_in"] = False
    if "main_navigation_menu" in st.session_state:
        st.session_state["main_navigation_menu"] = "Sign In"
    st.rerun()

# ─── Sidebar ─────────────────────────────────────────────────────────────────
st.sidebar.markdown("""
<div style="padding: 16px 4px 24px 4px; border-bottom: 1px solid #e8ecf0; margin-bottom: 22px;">
    <div style="font-family: 'Josefin Sans', sans-serif; font-size: 10px; font-weight: 700;
                letter-spacing: 0.18em; color: #1a6ef5; text-transform: uppercase; margin-bottom: 6px;">
        Infosys Springboard
    </div>
    <div style="font-family: 'Josefin Sans', sans-serif; font-size: 21px; font-weight: 700;
                color: #0d1117; letter-spacing: -0.01em; line-height: 1.2;">
        Identity Platform
    </div>
    <div style="font-family: 'Inter', sans-serif; font-size: 12px; color: #7b8fa3; margin-top: 4px;">
        Milestone 1 &bull; Batch 4
    </div>
</div>
""", unsafe_allow_html=True)

# Active session check
is_user_authenticated = False
if st.session_state["jwt_token"]:
    is_valid, payload, _ = verify_jwt_token(st.session_state["jwt_token"])
    if is_valid and payload:
        is_user_authenticated = True
    else:
        st.session_state["jwt_token"] = None
        st.session_state["user_info"] = None

if is_user_authenticated:
    menu_options = ["User Dashboard", "Administrator Portal"]
elif st.session_state["admin_logged_in"]:
    menu_options = ["Admin Console", "Sign In"]
else:
    menu_options = ["Sign In", "Create Account", "Reset Password", "Administrator Portal"]

# Ensure session state for radio stays valid across auth state transitions
if "main_navigation_menu" in st.session_state and st.session_state["main_navigation_menu"] not in menu_options:
    st.session_state["main_navigation_menu"] = menu_options[0]

selected_page = st.sidebar.radio("Navigation", menu_options, key="main_navigation_menu", label_visibility="collapsed")

st.sidebar.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
st.sidebar.markdown("""
<div style="background: #f6f8fb; border: 1px solid #e2e6ea; border-radius: 10px;
            padding: 16px 14px; font-size: 11.5px; line-height: 1.85; color: #4d6070;">
    <div style="font-family: 'Josefin Sans', sans-serif; font-size: 10.5px; font-weight: 700;
                letter-spacing: 0.12em; color: #3d4f63; text-transform: uppercase; margin-bottom: 8px;">
        Security Architecture
    </div>
    Single SQLite store<br>
    Salted bcrypt hashes<br>
    HS256 JWT sessions<br>
    Email OTP on signup<br>
    Dual-route recovery<br>
    Rate-limit lockout
</div>
""", unsafe_allow_html=True)

# ─── VIEW: USER DASHBOARD ────────────────────────────────────────────────────
if is_user_authenticated and selected_page in ["User Dashboard", "Sign In", "User Sign In"]:
    user = st.session_state["user_info"] or {}

    st.markdown("""
    <div class="ui-card">
        <span class="ui-label ui-label-green">Authenticated Session &bull; JWT Verified</span>
        <h1 style="font-size: 28px; margin: 8px 0 6px 0;">Welcome, {username}</h1>
        <p style="color: #6b7b8e; font-size: 14px; margin: 0;">
            Your session is secured with a cryptographically signed JSON Web Token (HS256).
        </p>
    </div>
    """.format(username=user.get("username", "User")), unsafe_allow_html=True)

    col_profile, col_session = st.columns([3, 2])

    with col_profile:
        st.markdown("""
        <div class="ui-card">
            <div style="font-family: 'Josefin Sans', sans-serif; font-size: 10.5px; font-weight: 700;
                        letter-spacing: 0.12em; color: #7b8fa3; text-transform: uppercase; margin-bottom: 14px;">
                User Profile
            </div>
            <table style="width: 100%; border-collapse: collapse; font-size: 13.5px;">
                <tr style="border-bottom: 1px solid #f0f2f5;">
                    <td style="padding: 13px 0; color: #7b8fa3; width: 38%; font-weight: 500;">Username</td>
                    <td style="padding: 13px 0; font-weight: 600; color: #0d1117;">{username}</td>
                </tr>
                <tr style="border-bottom: 1px solid #f0f2f5;">
                    <td style="padding: 13px 0; color: #7b8fa3; font-weight: 500;">Email</td>
                    <td style="padding: 13px 0; font-weight: 600; color: #0d1117;">{email}</td>
                </tr>
                <tr style="border-bottom: 1px solid #f0f2f5;">
                    <td style="padding: 13px 0; color: #7b8fa3; font-weight: 500;">System ID</td>
                    <td style="padding: 13px 0; font-family: monospace; font-size: 13px; color: #1a6ef5;">#{uid}</td>
                </tr>
                <tr>
                    <td style="padding: 13px 0; color: #7b8fa3; font-weight: 500;">Registered</td>
                    <td style="padding: 13px 0; color: #3d4f63;">{created}</td>
                </tr>
            </table>
            <div style="margin-top: 20px;" class="ui-infobox">
                <strong>Security Status:</strong> Passwords and security answers are stored as
                salted bcrypt hashes — never as plaintext.
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
                        letter-spacing: 0.12em; color: #7b8fa3; text-transform: uppercase; margin-bottom: 14px;">
                Session Control
            </div>
            <p style="font-size: 13px; color: #6b7b8e; line-height: 1.7; margin-bottom: 22px;">
                JWT token claims and signature are verified on every page load.
                You can terminate your session at any time.
            </p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Sign Out", key="user_logout_btn"):
            logout_user()

# ─── VIEW: ADMIN DASHBOARD ───────────────────────────────────────────────────
elif st.session_state["admin_logged_in"] and selected_page in ["Admin Console", "Administrator Portal", "Admin Management Console"]:
    st.markdown("""
    <div class="ui-card">
        <span class="ui-label ui-label-orange">Administrative Access &bull; Privileged Console</span>
        <h1 style="font-size: 28px; margin: 8px 0 6px 0;">Administrator Directory</h1>
        <p style="color: #6b7b8e; font-size: 14px; margin: 0;">
            Complete catalog of verified user accounts. Password hashes are strictly masked.
        </p>
    </div>
    """, unsafe_allow_html=True)

    users_data = get_all_registered_users()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Registered Users", len(users_data))
    with c2:
        st.metric("Database", "milestone1.db")
    with c3:
        st.metric("Admin User", ADMIN_USERNAME)

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div style="font-family: 'Josefin Sans', sans-serif; font-size: 10.5px; font-weight: 700;
                letter-spacing: 0.12em; color: #7b8fa3; text-transform: uppercase; margin-bottom: 10px;">
        User Accounts
    </div>
    """, unsafe_allow_html=True)

    if users_data:
        df = pd.DataFrame(users_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No accounts registered yet. Complete user sign-up with OTP verification to populate this directory.")

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
    col_btn, _, _ = st.columns([1, 2, 2])
    with col_btn:
        if st.button("Exit Console", key="admin_exit_btn"):
            logout_admin()

# ─── VIEW: ADMINISTRATOR SIGN IN ─────────────────────────────────────────────
elif selected_page == "Administrator Portal":
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown("""
        <div class="ui-card">
            <span class="ui-label ui-label-orange">System Administration</span>
            <h2 style="font-size: 24px; margin: 8px 0 6px 0;">Administrator Sign In</h2>
            <p style="color: #6b7b8e; font-size: 13.5px; margin: 0 0 24px 0;">
                Authenticate with dedicated administrative credentials.
            </p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("admin_login_form"):
            admin_user = st.text_input("Username", placeholder="Administrator username", key="adm_usr")
            admin_pass = st.text_input("Password", type="password", placeholder="Administrator password", key="adm_pw")
            admin_submit = st.form_submit_button("Authenticate")

            if admin_submit:
                if authenticate_admin(admin_user, admin_pass):
                    st.session_state["admin_logged_in"] = True
                    st.session_state["main_navigation_menu"] = "Admin Console"
                    st.success("Administrative credentials verified.")
                    st.rerun()
                else:
                    st.error("Invalid administrator credentials.")

# ─── VIEW: USER SIGN IN ───────────────────────────────────────────────────────
elif selected_page in ["Sign In", "User Sign In"]:
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown("""
        <div class="ui-card">
            <span class="ui-label ui-label-blue">Authentication</span>
            <h2 style="font-size: 24px; margin: 8px 0 6px 0;">Sign In to Your Account</h2>
            <p style="color: #6b7b8e; font-size: 13.5px; margin: 0 0 24px 0;">
                Enter your username or email address and password to continue.
            </p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            identifier = st.text_input("Username or Email Address", placeholder="Enter username or email", key="li_id")
            password = st.text_input("Password", type="password", placeholder="Enter your password", key="li_pw")
            login_submit = st.form_submit_button("Sign In")

            if login_submit:
                success, token, msg, user_info = login_user(identifier, password)
                if success and token:
                    st.session_state["jwt_token"] = token
                    st.session_state["user_info"] = user_info
                    st.session_state["main_navigation_menu"] = "User Dashboard"
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

# ─── VIEW: CREATE ACCOUNT ─────────────────────────────────────────────────────
elif selected_page == "Create Account":
    st.markdown("""
    <div class="ui-card">
        <span class="ui-label ui-label-blue">Registration</span>
        <h2 style="font-size: 24px; margin: 8px 0 6px 0;">Create New Account</h2>
        <p style="color: #6b7b8e; font-size: 13.5px; margin: 0;">
            Your account is activated only after mandatory email OTP verification.
        </p>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state["signup_stage"] == "FORM":
        with st.form("signup_form"):
            col1, col2 = st.columns(2)
            with col1:
                username  = st.text_input("Username", placeholder="Minimum 3 characters, alphanumeric")
                email     = st.text_input("Email Address", placeholder="e.g. name@company.com")
                password  = st.text_input("Password", type="password", placeholder="8+ chars, upper, lower, digit, symbol")
                confirm_p = st.text_input("Confirm Password", type="password", placeholder="Re-enter password")
            with col2:
                security_question = st.selectbox("Security Question", SECURITY_QUESTIONS)
                security_answer   = st.text_input("Security Answer", placeholder="Used for account recovery")
                st.markdown("""
                <div class="ui-infobox" style="margin-top: 8px;">
                    Your security answer is stored as a salted bcrypt hash, never in plain text.
                </div>
                """, unsafe_allow_html=True)

            signup_submit = st.form_submit_button("Proceed to Email Verification")

            if signup_submit:
                ok, msg, dev_otp = stage_signup(
                    username=username,
                    email=email,
                    password=password,
                    confirm_password=confirm_p,
                    security_question=security_question,
                    security_answer=security_answer
                )
                if ok:
                    st.session_state["signup_stage"] = "OTP_VERIFY"
                    st.session_state["signup_email"] = email.strip().lower()
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    elif st.session_state["signup_stage"] == "OTP_VERIFY":
        col_l, col_c, col_r = st.columns([1, 2, 1])
        with col_c:
            target_email = st.session_state["signup_email"]
            st.markdown(f"""
            <div class="ui-card">
                <span class="ui-label ui-label-green">Step 2 of 2 &bull; Email Verification</span>
                <h3 style="font-size: 20px; margin: 8px 0 10px 0;">Verify Your Email</h3>
                <p style="font-size: 13.5px; color: #4d6070; margin: 0;">
                    A 6-digit code was sent to <strong style="color: #1a6ef5;">{target_email}</strong>.<br>
                    Your account is created only after successful verification.
                </p>
            </div>
            """, unsafe_allow_html=True)

            with st.form("otp_verification_form"):
                otp_code = st.text_input("6-Digit Verification Code", max_chars=6, placeholder="Enter the code from your inbox")
                verify_submit = st.form_submit_button("Verify and Activate Account")

                if verify_submit:
                    ok, msg = complete_signup(st.session_state["signup_email"], otp_code)
                    if ok:
                        st.session_state["signup_stage"] = "FORM"
                        st.session_state["signup_email"] = ""
                        st.success(msg)
                    else:
                        st.error(msg)

            st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
            if st.button("Back to Registration Form", key="reset_signup_btn"):
                st.session_state["signup_stage"] = "FORM"
                st.session_state["signup_email"] = ""
                st.rerun()

# ─── VIEW: RESET PASSWORD ────────────────────────────────────────────────────
elif selected_page == "Reset Password":
    st.markdown("""
    <div class="ui-card">
        <span class="ui-label ui-label-blue">Account Recovery</span>
        <h2 style="font-size: 24px; margin: 8px 0 6px 0;">Password Recovery</h2>
        <p style="color: #6b7b8e; font-size: 13.5px; margin: 0;">
            Recover access using your Security Question or a one-time code sent to your email.
        </p>
    </div>
    """, unsafe_allow_html=True)

    tab_sq, tab_otp = st.tabs(["Security Question", "Email Verification Code"])

    with tab_sq:
        st.markdown("""
        <div style="font-family: 'Josefin Sans', sans-serif; font-size: 10.5px; font-weight: 700;
                    letter-spacing: 0.12em; color: #7b8fa3; text-transform: uppercase; margin-bottom: 14px;">
            Route A — Security Question
        </div>
        """, unsafe_allow_html=True)

        with st.form("sec_q_fetch_form"):
            sq_user = st.text_input("Registered Username", placeholder="Enter your username", key="sq_uid")
            fetch_btn = st.form_submit_button("Look Up Security Question")
            if fetch_btn and sq_user:
                ok, question, msg = get_security_question_for_user(sq_user)
                if ok:
                    st.session_state["active_sec_q_user"] = sq_user
                    st.session_state["active_sec_question"] = question
                    st.success(f"Security Question: {question}")
                else:
                    st.error(msg)

        if "active_sec_question" in st.session_state and st.session_state.get("active_sec_q_user"):
            st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
            with st.form("sec_q_reset_form"):
                st.markdown(f"""
                <div class="ui-infobox" style="margin-bottom: 16px;">
                    <strong>Question for {st.session_state['active_sec_q_user']}:</strong><br>
                    {st.session_state['active_sec_question']}
                </div>
                """, unsafe_allow_html=True)
                sq_answer    = st.text_input("Security Answer", type="password", placeholder="Enter your answer")
                sq_new_pass  = st.text_input("New Password", type="password", placeholder="Minimum 8 characters")
                sq_conf_pass = st.text_input("Confirm New Password", type="password", placeholder="Re-enter new password")
                sq_reset_btn = st.form_submit_button("Update Password")

                if sq_reset_btn:
                    ok, msg = reset_password_with_security_question(
                        st.session_state["active_sec_q_user"],
                        sq_answer, sq_new_pass, sq_conf_pass
                    )
                    if ok:
                        st.success(msg)
                        del st.session_state["active_sec_question"]
                        del st.session_state["active_sec_q_user"]
                    else:
                        st.error(msg)

    with tab_otp:
        st.markdown("""
        <div style="font-family: 'Josefin Sans', sans-serif; font-size: 10.5px; font-weight: 700;
                    letter-spacing: 0.12em; color: #7b8fa3; text-transform: uppercase; margin-bottom: 14px;">
            Route B — Email Verification Code
        </div>
        """, unsafe_allow_html=True)

        with st.form("otp_recovery_send_form"):
            rec_email = st.text_input("Registered Email Address", placeholder="Enter your email address", key="rec_em")
            send_otp_btn = st.form_submit_button("Send Recovery Code")

            if send_otp_btn:
                ok, msg, dev_otp = initiate_forgot_password_otp(rec_email)
                if ok:
                    st.session_state["active_rec_email"] = rec_email.strip().lower()
                    st.success(msg)
                else:
                    st.error(msg)

        if "active_rec_email" in st.session_state:
            st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
            with st.form("otp_recovery_finalize_form"):
                st.markdown(f"""
                <div class="ui-infobox" style="margin-bottom: 16px;">
                    A recovery code was dispatched to
                    <strong style="color: #1a6ef5;">{st.session_state['active_rec_email']}</strong>.
                </div>
                """, unsafe_allow_html=True)
                rec_otp      = st.text_input("6-Digit Verification Code", max_chars=6, placeholder="Enter the code from your inbox")
                rec_new_pass = st.text_input("New Password", type="password", placeholder="Minimum 8 characters")
                rec_conf     = st.text_input("Confirm New Password", type="password", placeholder="Re-enter new password")
                rec_reset_btn = st.form_submit_button("Verify Code and Update Password")

                if rec_reset_btn:
                    ok, msg = reset_password_with_otp(
                        st.session_state["active_rec_email"],
                        rec_otp, rec_new_pass, rec_conf
                    )
                    if ok:
                        st.success(msg)
                        del st.session_state["active_rec_email"]
                    else:
                        st.error(msg)
else:
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.info("Please select an option from the sidebar to continue.")

