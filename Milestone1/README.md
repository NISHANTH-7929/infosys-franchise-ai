# Infosys Springboard Internship 7.0 (Batch 4)
## Milestone 1: User Authentication Module

---

### 1. Project Overview

This repository contains the complete implementation of **Milestone 1 (User Authentication Module)** for the **Infosys Springboard Internship 7.0 (Batch 4)**. 

Designed for both Google Colab (with ngrok public tunneling) and local execution, this system provides a secure, modular authentication engine built with **Python, Streamlit, SQLite, bcrypt, PyJWT, and Gmail SMTP**.

The implementation features an educational-first architecture that strictly satisfies all evaluation rubrics, including an additional **Mandatory Email OTP Signup Verification** workflow where permanent user records are committed to the database **only after successful OTP verification**.

---

### 2. Key Features Implemented

1. **Mandatory Email OTP Signup Verification**:
   - Registration requires Username, Email, Password, Confirm Password, Security Question, and Security Answer.
   - Account data is staged temporarily in a pending state with expiration.
   - A cryptographically secure 6-digit OTP is dispatched via Gmail SMTP.
   - The permanent user account is created in the SQLite database **only after the candidate successfully enters and verifies the OTP**.
2. **Dual-Identifier Login**:
   - Supports sign-in using either **Username or Email Address** alongside Password.
   - Rate limiting and brute-force mitigation lock accounts after 3 consecutive failed attempts for 5 minutes (300 seconds).
   - Returns generic error messages (*"Invalid username/email or password."*) to prevent user enumeration attacks.
3. **JWT Session Management**:
   - Generates cryptographically signed **HS256 JSON Web Tokens (JWT)** upon successful authentication.
   - Stores session state in Streamlit and enforces token validity before rendering protected pages.
   - Secure logout mechanism clears session state and redirects to the Login view.
4. **Dual-Route Forgot Password Recovery**:
   - **Route A (Security Question)**: Recovers account access by answering the preset security question chosen during signup.
   - **Route B (Email OTP)**: Recovers account access by verifying a 6-digit one-time code sent to the registered email.
   - Both recovery flows enforce the exact same password complexity and confirmation rules.
5. **Role-Based Protected Dashboards**:
   - **User Dashboard**: Displays personalized welcome banner, profile details, registration date, and active JWT session status.
   - **Admin Management Console**: Dedicated admin login displaying registered user catalog (User ID, Username, Email, Registration Timestamp). In accordance with strict security standards, **password hashes and security answer hashes are never exposed**.
6. **Strict Field & Credential Validation**:
   - Mandatory check: No form submits with empty or whitespace-only inputs.
   - Email format: Enforces the Infosys rule requiring at least 2 characters before `@`, at least 2 characters between `@` and the dot, and at least 2 characters after the final dot (`ab@cd.ef`).
   - Password complexity: Minimum 8 characters, at least 1 uppercase letter, 1 lowercase letter, 1 numeric digit, and 1 special symbol.
7. **Single SQLite Database (`milestone1.db`)**:
   - Unified persistence managing `users`, `pending_signups`, `otp_codes`, and `login_attempts`.
   - Distinct OTP separation between `'SIGNUP'` verification and `'FORGOT_PASSWORD'` recovery.
   - Plaintext passwords, security answers, and OTP codes are never stored in plaintext (salted `bcrypt` hashes throughout).
8. **Automated Test Suite**:
   - 24 unit and integration tests covering validators, bcrypt, PyJWT, OTP limits/expiry, and complete authentication flows.

---

### 3. Technology Stack

| Technology | Purpose |
| :--- | :--- |
| **Python 3.10+** | Core programming language |
| **Streamlit** | Interactive web application framework with modern card styling |
| **SQLite3** | Single unified relational database engine |
| **bcrypt** | Salted cryptographic password and security answer hashing |
| **PyJWT** | HS256 signed JSON Web Tokens for session handling |
| **Gmail SMTP** | Automated OTP email delivery with anti-spam RFC headers |
| **pyngrok** | Secure tunnel exposing local Streamlit server via public URL |
| **pytest** | Automated test runner for unit and integration testing |
| **Google Colab** | Cloud notebook execution environment |

---

### 4. Standardized Project Structure

```
Milestone1/
├── README.md                          # Comprehensive documentation & setup guide
├── Milestone1_Authentication.ipynb    # All-in-one Google Colab executable notebook
├── requirements.txt                  # Python package dependencies
├── screenshots/                      # UI demonstration captures
│   └── README.md
├── src/
│   ├── __init__.py
│   ├── config.py                     # Secrets loader (Colab userdata / .env)
│   ├── database.py                   # SQLite schema & connection management
│   ├── security.py                   # bcrypt hashing & PyJWT tokens
│   ├── validators.py                 # Email, password, and field validation
│   ├── otp_service.py                # 6-digit OTP engine & Gmail SMTP client
│   ├── auth_service.py               # Authentication & recovery business logic
│   └── app.py                        # Streamlit web application
└── tests/
    ├── __init__.py
    ├── test_validators.py            # Unit tests for input validation rules
    ├── test_security.py              # Unit tests for bcrypt & JWT
    ├── test_otp.py                   # Unit tests for OTP expiry, limits & hashing
    └── test_auth.py                  # Integration tests for auth, recovery & admin
```

---

### 5. Setup & Configuration Instructions

#### 5.1. Google Colab Secrets (Recommended)
When running inside Google Colab, open the **Secrets** panel (key icon in the left sidebar) and configure the following keys:

| Secret Name | Description | Example / Source |
| :--- | :--- | :--- |
| `NGROK_AUTHTOKEN` | Personal authtoken from ngrok | Copy from [ngrok dashboard](https://dashboard.ngrok.com/) |
| `EMAIL_ADDRESS` | Gmail address used as sender | `yourname@gmail.com` |
| `EMAIL_PASSWORD` | 16-character Gmail App Password | Generated from Google Account security |
| `JWT_SECRET` | Secret signing key for JWT tokens | Any long random string |
| `ADMIN_USERNAME` | (Optional) Admin portal login username | Defaults to `admin` |
| `ADMIN_PASSWORD` | (Optional) Admin portal login password | Defaults to `Admin@Infosys123` |

> **Important:** Ensure the toggle switch for **"Notebook access"** is turned **ON** for each secret.

#### 5.2. Gmail App Password Setup
1. Visit your Google Account: [myaccount.google.com](https://myaccount.google.com/).
2. Select **Security** and enable **2-Step Verification**.
3. In the search bar at the top, search for **App Passwords**.
4. Create a new app password labeled `"Infosys Portal"`.
5. Google will display a 16-character code. Copy this code into your `EMAIL_PASSWORD` secret (without spaces).

#### 5.3. ngrok Setup
1. Register for a free account at [ngrok.com](https://ngrok.com/).
2. Navigate to the **Your Authtoken** page in your dashboard.
3. Copy the token and paste it into `NGROK_AUTHTOKEN`.

---

### 6. How to Run

#### Option A: Running in Google Colab (Notebook)
1. Open [Google Colab](https://colab.research.google.com/).
2. Upload `Milestone1/Milestone1_Authentication.ipynb`.
3. Configure the secrets in the left sidebar as described in Section 5.1.
4. Run all cells sequentially (**Runtime -> Run all**):
   - Cell 1: Installs required packages (`streamlit`, `pyjwt`, `bcrypt`, `pyngrok`).
   - Cell 2: Validates configured Colab secrets.
   - Cell 3: Scaffolds source code files into `src/` and `tests/`.
   - Cell 4: Runs the complete automated test suite (`pytest tests -v`).
   - Cell 5: Starts the Streamlit application and outputs a live **ngrok Public URL**.
5. Click the generated public URL to access the live portal.

#### Option B: Running Locally

1. **Install Dependencies:**
   ```bash
   pip install -r Milestone1/requirements.txt
   ```

2. **Configure Environment Variables (Optional):**
   Create a `.env` file in the root or `Milestone1/` directory:
   ```env
   EMAIL_ADDRESS=your_email@gmail.com
   EMAIL_PASSWORD=your_16_char_app_password
   JWT_SECRET=your_jwt_secret_key
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=Admin@Infosys123
   ```

3. **Run Automated Test Suite:**
   ```bash
   python -m pytest Milestone1/tests -v
   ```

4. **Launch Streamlit Web Portal:**
   ```bash
   python -m streamlit run Milestone1/src/app.py
   ```
   Open your browser at `http://localhost:8501`.

---

### 7. Automated Test Suite Results

The automated test suite verifies all critical authentication, validation, and OTP behaviors:

```
platform win32 -- Python 3.14.7, pytest-9.1.0
collecting ... collected 24 items

Milestone1/tests/test_auth.py::test_signup_otp_gated_flow PASSED         [  4%]
Milestone1/tests/test_auth.py::test_login_with_username_and_email PASSED [  8%]
Milestone1/tests/test_auth.py::test_login_brute_force_lockout PASSED     [ 12%]
Milestone1/tests/test_auth.py::test_forgot_password_route_a_security_question PASSED [ 16%]
Milestone1/tests/test_auth.py::test_forgot_password_route_b_email_otp PASSED [ 20%]
Milestone1/tests/test_auth.py::test_admin_dashboard_security_and_masking PASSED [ 25%]
Milestone1/tests/test_otp.py::test_numeric_otp_format PASSED             [ 29%]
Milestone1/tests/test_otp.py::test_otp_creation_and_hashing PASSED       [ 33%]
Milestone1/tests/test_otp.py::test_otp_successful_verification PASSED    [ 37%]
Milestone1/tests/test_otp.py::test_otp_separate_purposes PASSED          [ 41%]
Milestone1/tests/test_otp.py::test_otp_attempt_limits PASSED             [ 45%]
Milestone1/tests/test_otp.py::test_otp_expired PASSED                    [ 50%]
Milestone1/tests/test_security.py::test_bcrypt_hashing_and_verification PASSED [ 54%]
Milestone1/tests/test_security.py::test_security_answer_normalization PASSED [ 58%]
Milestone1/tests/test_security.py::test_jwt_generation_and_verification PASSED [ 62%]
Milestone1/tests/test_security.py::test_jwt_tampered_token PASSED        [ 66%]
Milestone1/tests/test_security.py::test_jwt_expired_token PASSED         [ 70%]
Milestone1/tests/test_validators.py::test_mandatory_fields_empty PASSED  [ 75%]
Milestone1/tests/test_validators.py::test_mandatory_fields_whitespace PASSED [ 79%]
Milestone1/tests/test_validators.py::test_mandatory_fields_success PASSED [ 83%]
Milestone1/tests/test_validators.py::test_email_format_infosys_rule PASSED [ 87%]
Milestone1/tests/test_validators.py::test_password_complexity PASSED     [ 91%]
Milestone1/tests/test_validators.py::test_password_confirmation PASSED   [ 95%]
Milestone1/tests/test_validators.py::test_username_format PASSED         [100%]

============================= 24 passed in 11.54s =============================
```

---

### 8. User Interface Screenshots

*Screenshots demonstrating full functionality across all required views:*

#### 8.1. User Sign In View
![User Sign In](screenshots/01_login_page.png)

#### 8.2. User Registration View (Form Details)
![User Registration](screenshots/02_signup_page.png)

#### 8.3. Mandatory Signup Email OTP Verification Challenge
![Signup OTP Challenge](screenshots/03_signup_otp_verification.png)

#### 8.4. Forgot Password - Route A (Security Question)
![Forgot Password Route A](screenshots/04_forgot_password_security_question.png)

#### 8.5. Forgot Password - Route B (Email OTP)
![Forgot Password Route B](screenshots/05_forgot_password_email_otp.png)

#### 8.6. Professional OTP Verification Email
![OTP Email Sample](screenshots/06_otp_email_sample.png)

#### 8.7. Protected User Dashboard (JWT Session)
![Protected User Dashboard](screenshots/07_user_dashboard.png)

#### 8.8. Admin Dashboard (Registered Users with Masked Hashes)
![Admin Dashboard](screenshots/08_admin_dashboard.png)

---

### 9. Final Checklist Verification

- [x] Repository structured with milestone files strictly under `Milestone1/`.
- [x] Root `README.md` and `LICENSE` preserved intact.
- [x] Modular architecture (`config.py`, `database.py`, `security.py`, `validators.py`, `otp_service.py`, `auth_service.py`, `app.py`).
- [x] Mandatory signup Email OTP verification fully functioning.
- [x] Permanent user accounts created only after successful OTP verification.
- [x] Distinct OTP contexts separating signup from password recovery.
- [x] Single SQLite database (`milestone1.db`) handling all authentication tables.
- [x] Salted bcrypt hashing for passwords and security answers.
- [x] Cryptographic HS256 JWT tokens for session verification.
- [x] Protected User Dashboard with logout action.
- [x] Protected Admin Dashboard with user directory and masked credential hashes.
- [x] All 24 automated tests passing in `Milestone1/tests/`.
- [x] Google Colab notebook `Milestone1_Authentication.ipynb` prepared with outputs cleared and secrets abstracted.
