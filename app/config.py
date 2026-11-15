import os
SECRET = os.getenv("SECRET_KEY", "dev-secret-change-me")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
DB_URL = os.getenv("DB_URL", "sqlite:///matchmaker.db")
ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "nthumatchmaker@gmail.com").split(",") if e.strip()]
SMTP_HOST = os.getenv("SMTP_HOST", ""); SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", ""); SMTP_FROM = os.getenv("SMTP_FROM", "noreply@example.com")
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "180"))
NTHU_PAGES = [u for u in os.getenv("NTHU_PAGES", "").split(",") if u]  # announcement pages to scan
KEYWORDS = ["競賽", "比賽", "徵件", "黑客松", "hackathon", "創業", "補助", "計畫"]
MATCH_MODE = os.getenv("MATCH_MODE", "hybrid")   # hybrid | embeddings | tags
PUBLIC = BASE_URL.startswith("https://")             # deployed on the internet (e.g. Hugging Face Spaces)
SHOW_LINK = os.getenv("SHOW_LINK", "0") == "1" and not PUBLIC   # DEMO ONLY, never on a public site: anyone could log in as anyone
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
DEMO_DATA = os.getenv("DEMO_DATA", "0") == "1"   # run-demo.bat: realistic sample teams, separate demo.db
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")   # https://www.brevo.com: free email API over HTTPS (Render blocks SMTP)
MAIL_FROM = os.getenv("MAIL_FROM", os.getenv("SMTP_FROM", "nthumatchmaker@gmail.com"))   # must be a sender verified in Brevo
# Email verification is switched on only when email can really be sent from the server
REQUIRE_VERIFY = os.getenv("REQUIRE_EMAIL_VERIFY", "auto")
