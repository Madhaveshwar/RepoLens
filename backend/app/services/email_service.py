"""Email sending service.

Currently used for password-reset emails. Email sending is entirely optional:
when SMTP settings are absent the application falls back to a development
reset flow (the reset link is returned in the API response only outside
production) instead of failing.
"""
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("email_service")


def is_email_configured() -> bool:
    """True when enough SMTP settings are present to attempt sending email."""
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def send_password_reset_email_sync(to_email: str, reset_url: str) -> bool:
    """Send the password-reset email via SMTP. Returns True when sent.

    This is a blocking (smtplib) call — run it via ``asyncio.to_thread``
    from async endpoints.
    """
    if not is_email_configured():
        logger.warning("Password-reset email requested but SMTP is not configured; skipping send.")
        return False

    subject = f"{settings.PROJECT_NAME} — Password Reset Request"
    plain_body = (
        "Hello,\n\n"
        "We received a request to reset the password for your account.\n\n"
        f"Reset link (valid for {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes):\n"
        f"{reset_url}\n\n"
        "If you did not request a password reset, you can safely ignore this email — "
        "your password will remain unchanged.\n\n"
        f"— {settings.PROJECT_NAME}\n"
    )
    html_body = f"""\
<html>
  <body style="font-family: Arial, sans-serif; color: #27272a;">
    <p>Hello,</p>
    <p>We received a request to reset the password for your account.</p>
    <p>
      <a href="{reset_url}"
         style="display:inline-block;padding:10px 18px;border-radius:12px;background:#2563eb;color:#ffffff;text-decoration:none;">
        Reset your password
      </a>
    </p>
    <p>Or paste this link into your browser (valid for
       {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes):<br/>
       <span style="color:#3b82f6;">{reset_url}</span>
    </p>
    <p>If you did not request a password reset, you can safely ignore this email —
       your password will remain unchanged.</p>
    <p>— {settings.PROJECT_NAME}</p>
  </body>
</html>
"""

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to_email
        msg.set_content(plain_body)
        msg.add_alternative(html_body, subtype="html")

        if settings.SMTP_USE_TLS and settings.SMTP_PORT != 465:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                server.ehlo()
                try:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                except smtplib.SMTPException:
                    logger.warning("SMTP STARTTLS not available; continuing without TLS.")
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        else:
            # Port 465 or TLS disabled → implicit SSL
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15,
                                  context=ssl.create_default_context()) as server:
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

        logger.info(f"Password-reset email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send password-reset email to {to_email}: {e}", exc_info=True)
        return False
