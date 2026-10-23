# NTHU Matchmaker (Team 22)

Students find teammates across faculties for competitions, startups, research and side projects.
Python (FastAPI, Jinja2, SQLModel) with Postgres on Supabase, hosted on Render.

## Run locally
    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt sentence-transformers
    set ADMIN_EMAILS=you@example.com
    uvicorn app.main:app --reload

Without `DB_URL` it uses a local SQLite file. Secrets (DB_URL, SECRET_KEY, SMTP_PASS) are set in Render, never in this repo.
