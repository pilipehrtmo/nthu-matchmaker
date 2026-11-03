"""Sending email. Render's free plan blocks normal email ports (SMTP), so on the server we use Brevo's
web API over HTTPS. Without BREVO_API_KEY we fall back to SMTP (works on your own computer), and without
either we just print the email to the console (local testing)."""
import logging, smtplib
from email.message import EmailMessage
import httpx
from .config import *

def email_enabled() -> bool: return bool(BREVO_API_KEY or SMTP_HOST)

def send_mail(to: str, subject: str, text: str):
    if BREVO_API_KEY:
        r = httpx.post("https://api.brevo.com/v3/smtp/email", timeout=15, headers={"api-key": BREVO_API_KEY, "accept": "application/json"},
                       json={"sender": {"name": "NTHU Matchmaker", "email": MAIL_FROM}, "to": [{"email": to}], "subject": subject, "textContent": text})
        if r.status_code >= 300: raise RuntimeError(f"Brevo answered {r.status_code}: {r.text[:200]}")
        return
    if SMTP_HOST:
        m = EmailMessage(); m["To"] = to; m["From"] = SMTP_FROM; m["Subject"] = subject; m.set_content(text)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=12) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(m)
        return
    logging.warning("EMAIL to %s: %s\n%s", to, subject, text); print(f"\n>>> EMAIL to {to}: {subject}\n{text}\n")
