"""Link existing profiles to departments, without touching what people typed.

    python -m app.dept_migrate plan       # what would happen, per distinct text (reads DB_URL)
    python -m app.dept_migrate apply      # do it (safe to run again: only rows without a link are touched)
    python -m app.dept_migrate verify     # check: every original text still there, counts
    python -m app.dept_migrate rollback   # undo the links this script made (dept_src = 'migration')
    python -m app.dept_migrate sql "text1" "text2" ...   # print the same migration as one SQL transaction

What it does, in one transaction:
 1. copies id + every department column of every user into dept_migration_backup (once per user);
 2. faculty_orig = faculty where faculty_orig is empty (a frozen copy of the original text);
 3. links rows whose text is an exact reviewed alias or an exact official name (departments.map_legacy);
 4. marks every other non-empty text 'review' for the admin queue. Empty text stays empty.
It never changes `faculty`, and never touches a row that already has a link or a status.
"""
import sys
from sqlalchemy import text
from . import departments as D

BACKUP = """CREATE TABLE IF NOT EXISTS dept_migration_backup (user_id INTEGER PRIMARY KEY, faculty VARCHAR, faculty_orig VARCHAR,
  dept_id VARCHAR, dept_track VARCHAR, dept_status VARCHAR, dept_src VARCHAR, saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
COPY = """INSERT INTO dept_migration_backup (user_id, faculty, faculty_orig, dept_id, dept_track, dept_status, dept_src)
  SELECT id, faculty, faculty_orig, dept_id, dept_track, dept_status, dept_src FROM "user"
  WHERE id NOT IN (SELECT user_id FROM dept_migration_backup)"""
FREEZE = """UPDATE "user" SET faculty_orig = faculty WHERE COALESCE(faculty_orig, '') = '' AND COALESCE(faculty, '') <> ''"""
REVIEW = """UPDATE "user" SET dept_status = 'review', dept_src = 'migration'
  WHERE TRIM(COALESCE(faculty, '')) <> '' AND COALESCE(dept_id, '') = '' AND COALESCE(dept_status, '') = ''"""
ROLLBACK = """UPDATE "user" SET dept_id = '', dept_track = '', dept_status = '', dept_src = '' WHERE dept_src = 'migration'"""


def _q(s): return "'" + s.replace("'", "''") + "'"


def plan(values):
    """distinct texts -> [(text, mapping or None)]"""
    return [(v, D.map_legacy(v)) for v in sorted({(v or "").strip() for v in values})]


def link_statements(values):
    out = []
    for v, m in plan(values):
        if m and m["dept_status"] == "ok":
            out.append(f"""UPDATE "user" SET dept_id = {_q(m['dept_id'])}, dept_track = {_q(m['dept_track'])}, dept_status = 'ok', dept_src = 'migration'
  WHERE TRIM(faculty) = {_q(v)} AND COALESCE(dept_id, '') = '' AND COALESCE(dept_status, '') = ''""")
    return out


def statements(values): return [BACKUP, COPY, FREEZE, *link_statements(values), REVIEW]


LOCK = ["ALTER TABLE dept_migration_backup ENABLE ROW LEVEL SECURITY",   # Postgres/Supabase: keep the copy off the public API
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN REVOKE ALL ON dept_migration_backup FROM anon, authenticated; END IF; END $$"]


def sql(values): return "BEGIN;\n" + ";\n".join([BACKUP, *LOCK, *statements(values)[1:]]) + ";\nCOMMIT;"


def _values(c): return [r[0] for r in c.execute(text('SELECT DISTINCT faculty FROM "user"'))]


def apply(engine):
    with engine.begin() as c:
        for st in statements(_values(c)): c.execute(text(st))


def rollback(engine):
    with engine.begin() as c: c.execute(text(ROLLBACK))


def verify(engine):
    """Problems found (empty list = fine)."""
    probs = []
    with engine.begin() as c:
        has_backup = c.execute(text("SELECT COUNT(*) FROM dept_migration_backup")).scalar() if _has(c, "dept_migration_backup") else 0
        if has_backup:
            changed = c.execute(text('SELECT COUNT(*) FROM "user" u JOIN dept_migration_backup b ON b.user_id = u.id WHERE COALESCE(u.faculty_orig, \'\') <> \'\' AND u.faculty_orig <> b.faculty AND COALESCE(b.faculty_orig, \'\') = \'\'')).scalar()
            if changed: probs.append(f"{changed} frozen originals differ from the backup")
        for uid, d, t, st in c.execute(text('SELECT id, dept_id, dept_track, dept_status FROM "user" WHERE COALESCE(dept_id, \'\') <> \'\'')):
            if not D.valid(d, t or "", for_new=False): probs.append(f"user {uid}: unknown department {d}|{t}")
            if st != "ok": probs.append(f"user {uid}: linked but status {st!r}")
        n = c.execute(text("SELECT COUNT(*) FROM \"user\" WHERE TRIM(COALESCE(faculty, '')) <> '' AND COALESCE(dept_id, '') = '' AND COALESCE(dept_status, '') = ''")).scalar()
        if n: probs.append(f"{n} profiles with text but no link and no review status")
    return probs


def _has(c, table):
    try: c.execute(text(f"SELECT 1 FROM {table} LIMIT 1")); return True
    except Exception: return False


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if cmd == "sql": print(sql(sys.argv[2:])); sys.exit()
    from .db import engine, init_db
    init_db()   # adds the new columns if they are missing (additive only)
    if cmd == "plan":
        with engine.begin() as c:
            for v, m in plan(_values(c)): print(repr(v), "->", m)
    elif cmd == "apply": apply(engine); print("applied"); print(verify(engine) or "verify: ok")
    elif cmd == "verify": print(verify(engine) or "ok")
    elif cmd == "rollback": rollback(engine); print("rolled back the links made by the migration")
