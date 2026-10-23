import smtplib, logging
from email.message import EmailMessage
from .config import *
def send_magic(to: str, link: str):
    if not SMTP_HOST:
        logging.warning("MAGIC LINK for %s: %s", to, link); print(f"\n>>> MAGIC LINK for {to}: {link}\n"); return
    m = EmailMessage(); m["To"] = to; m["From"] = SMTP_FROM; m["Subject"] = "Your NTHU Matchmaker login link"
    m.set_content(f"Click to log in (valid 15 minutes):\n{link}")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(m)
