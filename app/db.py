from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine
from .config import DB_URL
DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)   # some hosts hand out the old scheme
if DB_URL.startswith("postgresql://"):
    DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg2://", 1)   # the driver in requirements.txt
if DB_URL.startswith("sqlite"):
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
else:   # Postgres (e.g. Supabase): small pool, drop dead connections after the free tier pauses
    engine = create_engine(DB_URL, pool_pre_ping=True, pool_size=8, max_overflow=4, pool_timeout=15, pool_recycle=300,   # 12 max: stays under Supabase's free connection limit
                           connect_args={"connect_timeout": 10})   # fail fast with a clear error instead of hanging
NEW_COLS = {"project": [("kind", "VARCHAR DEFAULT ''"), ("category", "VARCHAR DEFAULT ''"), ("stage", "VARCHAR DEFAULT ''"), ("tagline", "VARCHAR DEFAULT ''"), ("problem", "VARCHAR DEFAULT ''"), ("audience", "VARCHAR DEFAULT ''"), ("solution", "VARCHAR DEFAULT ''"), ("progress", "VARCHAR DEFAULT ''"), ("needs", "VARCHAR DEFAULT ''"), ("metrics", "VARCHAR DEFAULT ''"), ("tags", "VARCHAR DEFAULT ''"), ("links", "VARCHAR DEFAULT ''"), ("event_name", "VARCHAR DEFAULT ''"), ("objectives", "VARCHAR DEFAULT ''"), ("methodology", "VARCHAR DEFAULT ''"), ("outcomes", "VARCHAR DEFAULT ''"), ("completed_at", "TIMESTAMP")], "post": [("hidden", "BOOLEAN DEFAULT 0"), ("project_id", "INTEGER")], "comment": [("hidden", "BOOLEAN DEFAULT 0")],
            "report": [("kind", "VARCHAR DEFAULT 'user'"), ("target_id", "INTEGER DEFAULT 0")],
            "competition": [("category", "VARCHAR DEFAULT 'Other'"), ("description", "VARCHAR DEFAULT ''"), ("verified_at", "TIMESTAMP"), ("online", "BOOLEAN DEFAULT 0"), ("online_checked", "BOOLEAN DEFAULT 0")],
            "program": [("verified_at", "TIMESTAMP"), ("checked_at", "TIMESTAMP"), ("check_status", "VARCHAR DEFAULT ''"), ("check_note", "VARCHAR DEFAULT ''"), ("page_hash", "VARCHAR DEFAULT ''"), ("deadline_source", "VARCHAR DEFAULT ''")], "saved_item": [("status", "VARCHAR DEFAULT ''")],
            "remark": [("kind", "VARCHAR DEFAULT 'feedback'"), ("parent_id", "INTEGER"), ("category", "VARCHAR DEFAULT 'General'"), ("priority", "VARCHAR DEFAULT 'Normal'"), ("status", "VARCHAR DEFAULT 'open'"), ("resources", "VARCHAR DEFAULT ''"), ("last_at", "TIMESTAMP"), ("last_by", "INTEGER DEFAULT 0"), ("state", "VARCHAR DEFAULT 'open'"), ("doc_id", "INTEGER"), ("version_id", "INTEGER"), ("anchor", "VARCHAR DEFAULT ''"), ("fixed_in_version_id", "INTEGER"), ("resolved_by", "INTEGER DEFAULT 0"), ("resolved_at", "TIMESTAMP"), ("deleted_at", "TIMESTAMP")],
            "role": [("advisor", "BOOLEAN DEFAULT 0"), ("about", "VARCHAR DEFAULT ''"), ("must", "VARCHAR DEFAULT ''"), ("nice", "VARCHAR DEFAULT ''"), ("years", "INTEGER DEFAULT 0"), ("years_in", "VARCHAR DEFAULT ''"), ("beginner", "BOOLEAN DEFAULT 0")],
            "user": [("competitions", "VARCHAR DEFAULT ''"), ("past_projects", "VARCHAR DEFAULT ''"), ("awards", "VARCHAR DEFAULT ''"), ("password_hash", "VARCHAR DEFAULT ''"), ("email_verified", "BOOLEAN DEFAULT 1"), ("role", "VARCHAR DEFAULT 'student'"), ("faculty_status", "VARCHAR DEFAULT ''"), ("faculty_url", "VARCHAR DEFAULT ''"), ("faculty_note", "VARCHAR DEFAULT ''"), ("faculty_match", "VARCHAR DEFAULT ''"), ("faculty_reason", "VARCHAR DEFAULT ''"), ("faculty_evidence", "VARCHAR DEFAULT ''"), ("faculty_applied_at", "TIMESTAMP"), ("faculty_reviewed_at", "TIMESTAMP"), ("faculty_reviewed_by", "INTEGER"), ("title", "VARCHAR DEFAULT ''"), ("research", "VARCHAR DEFAULT ''"), ("lab_name", "VARCHAR DEFAULT ''"), ("lab_url", "VARCHAR DEFAULT ''"), ("orcid", "VARCHAR DEFAULT ''"), ("email_pref", "VARCHAR DEFAULT 'off'"), ("lang", "VARCHAR DEFAULT ''"), ("avatar_v", "INTEGER DEFAULT 0"), ("is_faculty", "BOOLEAN DEFAULT 0"), ("verified", "BOOLEAN DEFAULT 0"), ("name", "VARCHAR DEFAULT ''"), ("student_id", "VARCHAR DEFAULT ''"), ("faculty", "VARCHAR DEFAULT ''"), ("hours", "INTEGER DEFAULT 4"), ("line", "VARCHAR DEFAULT ''"), ("instagram", "VARCHAR DEFAULT ''"), ("discord", "VARCHAR DEFAULT ''"), ("linkedin", "VARCHAR DEFAULT ''"), ("github", "VARCHAR DEFAULT ''"), ("website", "VARCHAR DEFAULT ''"), ("behance", "VARCHAR DEFAULT ''"), ("scholar", "VARCHAR DEFAULT ''"), ("faculty_orig", "VARCHAR DEFAULT ''"), ("dept_id", "VARCHAR DEFAULT ''"), ("dept_track", "VARCHAR DEFAULT ''"), ("dept_status", "VARCHAR DEFAULT ''"), ("dept_src", "VARCHAR DEFAULT ''"), ("interests", "VARCHAR DEFAULT ''"), ("roles_wanted", "VARCHAR DEFAULT ''"), ("degree", "VARCHAR DEFAULT ''")]}
def init_db():
    SQLModel.metadata.create_all(engine)
    if DB_URL.startswith("sqlite"):   # tiny migration so old matchmaker.db files keep working
        with engine.begin() as c:
            for table, cols in NEW_COLS.items():
                have = {r[1] for r in c.execute(text(f'PRAGMA table_info("{table}")'))}
                for col, ddl in cols:
                    if col not in have: c.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {col} {ddl}'))
            c.execute(text('UPDATE remark SET last_at = created, last_by = author_id WHERE last_at IS NULL'))
            c.execute(text("UPDATE remark SET state = 'resolved' WHERE status = 'resolved' AND state <> 'resolved'"))
    else:   # Postgres: same tiny migration, and keep every table closed to Supabase's public API
        with engine.begin() as c:
            for table, cols in NEW_COLS.items():
                for col, ddl in cols:
                    ddl = ddl.replace("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false").replace("BOOLEAN DEFAULT 1", "BOOLEAN DEFAULT true")
                    c.execute(text(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS {col} {ddl}'))
            c.execute(text('UPDATE remark SET last_at = created, last_by = author_id WHERE last_at IS NULL'))   # threads made before replies existed
            c.execute(text("UPDATE remark SET state = 'resolved' WHERE status = 'resolved' AND state <> 'resolved'"))   # the five-value state starts from the old open/resolved status
            for t in SQLModel.metadata.sorted_tables:
                c.execute(text(f'ALTER TABLE public."{t.name}" ENABLE ROW LEVEL SECURITY'))
            # Least privilege on Supabase: the browser-facing roles (anon, authenticated) get no table rights at all.
            # The app connects as the database owner, so this changes nothing for it; RLS (no policies) stays as a second wall.
            c.execute(text("""DO $$ BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
                REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
              END IF; END $$"""))
    # one account per student ID and per email, enforced by the database too (blank IDs, e.g. professors, are ignored)
    for ddl in ("""CREATE UNIQUE INDEX IF NOT EXISTS user_sid_uniq ON "user" (upper(trim(student_id))) WHERE trim(student_id) <> ''""",
                """CREATE UNIQUE INDEX IF NOT EXISTS user_email_lower_uniq ON "user" (lower(email))"""):
        try:
            with engine.begin() as c: c.execute(text(ddl))
        except Exception as e: print(">>> could not add unique index (duplicates?):", type(e).__name__, flush=True)
def get_session():
    with Session(engine) as s: yield s
