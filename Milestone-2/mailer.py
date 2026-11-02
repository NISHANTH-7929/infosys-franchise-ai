import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from database import settings


def send_email(to_email: str, subject: str, body_html: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.MAIL_EMAIL
        msg["To"] = to_email
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(settings.MAIL_HOST, settings.MAIL_PORT, timeout=20) as server:
            server.starttls()
            server.login(settings.MAIL_EMAIL, settings.MAIL_PASSWORD)
            server.sendmail(settings.MAIL_EMAIL, [to_email], msg.as_string())
        print(f"[mailer] ✅ sent to {to_email}")
        return True
    except Exception as e:
        print(f"[mailer] ❌ failed: {e}")
        return False


def send_otp_email(to_email: str, otp: str) -> bool:
    body = f"""
    <h2>Password Reset OTP</h2>
    <p>Your OTP is: <b style="font-size:24px;letter-spacing:4px">{otp}</b></p>
    <p>This code expires in 10 minutes.</p>
    """
    return send_email(to_email, "Your OTP Code", body)


def send_reset_link_email(to_email: str, token: str) -> bool:
    link = f"{settings.NGROK_URL}/reset-link?token={token}"
    body = f"""
    <h2>Password Reset</h2>
    <p>Click the link below to reset your password:</p>
    <p><a href="{link}">{link}</a></p>
    """
    return send_email(to_email, "Password Reset Link", body)
