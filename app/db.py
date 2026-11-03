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
NEW_COLS = {"project": [("kind", "VARCHAR DEFAULT ''"), ("category", "VARCHAR DEFAULT ''"), ("stage", "VARCHAR DEFAULT ''")], "post": [("hidden", "BOOLEAN DEFAULT 0")], "comment": [("hidden", "BOOLEAN DEFAULT 0")],
            "report": [("kind", "VARCHAR DEFAULT 'user'"), ("target_id", "INTEGER DEFAULT 0")],
            "competition": [("category", "VARCHAR DEFAULT 'Other'"), ("description", "VARCHAR DEFAULT ''")],
            "role": [("advisor", "BOOLEAN DEFAULT 0")],
            "user": [("role", "VARCHAR DEFAULT 'student'"), ("faculty_status", "VARCHAR DEFAULT ''"), ("faculty_url", "VARCHAR DEFAULT ''"), ("faculty_note", "VARCHAR DEFAULT ''"), ("title", "VARCHAR DEFAULT ''"), ("avatar_v", "INTEGER DEFAULT 0"), ("is_faculty", "BOOLEAN DEFAULT 0"), ("verified", "BOOLEAN DEFAULT 0"), ("name", "VARCHAR DEFAULT ''"), ("student_id", "VARCHAR DEFAULT ''"), ("faculty", "VARCHAR DEFAULT ''"), ("hours", "INTEGER DEFAULT 4"), ("line", "VARCHAR DEFAULT ''"), ("instagram", "VARCHAR DEFAULT ''"), ("discord", "VARCHAR DEFAULT ''"), ("linkedin", "VARCHAR DEFAULT ''"), ("github", "VARCHAR DEFAULT ''"), ("website", "VARCHAR DEFAULT ''"), ("behance", "VARCHAR DEFAULT ''"), ("scholar", "VARCHAR DEFAULT ''")]}
def init_db():
    SQLModel.metadata.create_all(engine)
    if DB_URL.startswith("sqlite"):   # tiny migration so old matchmaker.db files keep working
        with engine.begin() as c:
            for table, cols in NEW_COLS.items():
                have = {r[1] for r in c.execute(text(f'PRAGMA table_info("{table}")'))}
                for col, ddl in cols:
                    if col not in have: c.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {col} {ddl}'))
    else:   # Postgres: same tiny migration, and keep every table closed to Supabase's public API
        with engine.begin() as c:
            for table, cols in NEW_COLS.items():
                for col, ddl in cols:
                    ddl = ddl.replace("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT false")
                    c.execute(text(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS {col} {ddl}'))
            for t in SQLModel.metadata.sorted_tables:
                c.execute(text(f'ALTER TABLE public."{t.name}" ENABLE ROW LEVEL SECURITY'))
def get_session():
    with Session(engine) as s: yield s
