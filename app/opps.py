"""Opportunities: competition status (read from the dates we actually have), a detail page per competition,
and Saved items (competitions and projects a person bookmarked).

A competition's status is worked out only from its stored date text. If the text has no real date
("Annual · check site"), the status is "Date not confirmed": we never guess a deadline.
"""
import re
from datetime import date, datetime, timedelta, timezone
from fastapi import Request, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlmodel import Session, select
from .db import get_session
from .models import User, Project, Role, Competition, SavedItem
from .main import app, render, me, go, limited, templates, kind_of

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
CLOSING_DAYS = 14

def today_tw():
    return datetime.now(timezone(timedelta(hours=8))).date()

def last_date(text):
    """The last calendar date written in a date text, or None. Handles 2026-11-30, 'Dec 18 - 21, 2026',
    'Oct 31 - Nov 15, 2026', '30 Nov 2026' and '2026/11/30'."""
    t = (text or "").lower()
    iso = re.findall(r"(20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})", t)
    if iso:
        y, m, d = iso[-1]
        try: return date(int(y), int(m), int(d))
        except ValueError: return None
    years = re.findall(r"\b(20\d\d)\b", t)
    if not years: return None
    year = int(years[-1]); month = None; found = None
    for tok in re.findall(r"[a-z]{3,9}|\d{1,2}(?!\d)", t.split(years[-1])[0]):
        if tok[:3] in MONTHS and not tok.isdigit(): month = MONTHS[tok[:3]]
        elif tok.isdigit() and month:
            try: found = date(year, month, int(tok))
            except ValueError: pass
    return found

def comp_status(c):
    """(key, label, days left or None). Keys: open / closing / past / unknown."""
    end = last_date(c.deadline)
    if not end: return ("unknown", "Date not confirmed", None)
    n = (end - today_tw()).days
    if n < 0: return ("past", "Past", n)
    if n <= CLOSING_DAYS: return ("closing", "Closing soon", n)
    return ("open", "Upcoming", n)
templates.env.globals["comp_status"] = comp_status


def saved_ids(s, user, kind):
    if not user: return set()
    return set(s.exec(select(SavedItem.item_id).where(SavedItem.user_id == user.id, SavedItem.kind == kind)).all())

@app.post("/save/{kind}/{iid}", dependencies=[limited("save", 120, 3600)])
def toggle_save(req: Request, kind: str, iid: int, next: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if kind not in ("competition", "project", "program"): raise HTTPException(404)
    from .models import Program
    if not user: return JSONResponse({"error": "login"}, status_code=401) if req.headers.get("x-fetch") else go("/login")
    target = s.get({"competition": Competition, "project": Project, "program": Program}[kind], iid)
    if not target: raise HTTPException(404)
    row = s.exec(select(SavedItem).where(SavedItem.user_id == user.id, SavedItem.kind == kind, SavedItem.item_id == iid)).first()
    if row: s.delete(row); on = False
    else: s.add(SavedItem(user_id=user.id, kind=kind, item_id=iid)); on = True
    s.commit()
    if req.headers.get("x-fetch"): return JSONResponse({"saved": on})
    back = next if re.fullmatch(r"/(projects|competitions)/\d+|/activity|/|/funding(#p\d+)?", next) else "/"
    return go(back)

@app.get("/competitions/{cid}")
def competition_page(req: Request, cid: int, user=Depends(me), s: Session = Depends(get_session)):
    c = s.get(Competition, cid)
    if not c: raise HTTPException(404)
    teams = s.exec(select(Project).where(Project.competition_id == cid, Project.status == "open").order_by(Project.created.desc()).limit(20)).all()
    owners = {u.id: u for u in s.exec(select(User).where(User.id.in_({p.owner_id for p in teams} or {-1})))}
    open_seats = {}
    for p in teams: open_seats[p.id] = len(s.exec(select(Role.id).where(Role.project_id == p.id, Role.filled == False)).all())
    mine = [p for p in s.exec(select(Project).where(Project.competition_id == cid, Project.owner_id == user.id)).all()] if user else []
    row = s.exec(select(SavedItem).where(SavedItem.user_id == user.id, SavedItem.kind == "competition", SavedItem.item_id == cid)).first() if user else None
    return render(req, "competition.html", user, c=c, st=comp_status(c), teams=teams, owners=owners, open_seats=open_seats, mine=mine,
                  saved=bool(row), track=row.status if row else "")

def saved_for(s, user):
    """Saved competitions and projects for the Activity page (missing ones are skipped)."""
    from .models import Program
    rows = s.exec(select(SavedItem).where(SavedItem.user_id == user.id).order_by(SavedItem.created.desc())).all()
    gids = [r.item_id for r in rows if r.kind == "program"]
    progs = {p.id: p for p in s.exec(select(Program).where(Program.id.in_(gids or [-1]))).all()}
    st = {(r.kind, r.item_id): r.status for r in rows}
    cids = [r.item_id for r in rows if r.kind == "competition"]; pids = [r.item_id for r in rows if r.kind == "project"]
    comps = {c.id: c for c in s.exec(select(Competition).where(Competition.id.in_(cids or [-1]))).all()}
    projs = {p.id: p for p in s.exec(select(Project).where(Project.id.in_(pids or [-1]))).all()}
    return [("program", progs[r.item_id], st[("program", r.item_id)]) for r in rows if r.kind == "program" and r.item_id in progs] + \
           [("competition", comps[r.item_id], st[("competition", r.item_id)]) for r in rows if r.kind == "competition" and r.item_id in comps] + \
           [("project", projs[r.item_id], "") for r in rows if r.kind == "project" and r.item_id in projs]


# ---------- funding programs ----------
TRACK = [("", "Not tracking"), ("planning", "Planning to apply"), ("applied", "Applied"), ("accepted", "Accepted"), ("not_selected", "Not selected")]
templates.env.globals["TRACK"] = TRACK

def prog_status(p):
    """From the stored YYYY-MM-DD deadline only. Without one: 'Date not announced' (the program's own note is shown)."""
    end = last_date(p.next_deadline)
    if not end: return ("unknown", "Date not announced", None)
    n = (end - today_tw()).days
    if n < 0: return ("past", "Deadline passed", n)
    if n <= CLOSING_DAYS: return ("closing", "Closing soon", n)
    return ("open", "Open", n)
templates.env.globals["prog_status"] = prog_status

@app.get("/funding")
def funding(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    from .models import Program
    from .main import PROJECT_KINDS
    progs = s.exec(select(Program).where(Program.active == True).order_by(Program.sort)).all()
    mine = s.exec(select(Project).where(Project.owner_id == user.id, Project.kind.in_(["Startup", "Research"]))).all() if user else []
    track = {r.item_id: r.status for r in s.exec(select(SavedItem).where(SavedItem.user_id == user.id, SavedItem.kind == "program")).all()} if user else {}
    fields = sorted({c.strip() for p in progs for c in (p.categories or "").split(",") if c.strip()})
    allc = s.exec(select(Competition).order_by(Competition.needs_review, Competition.id.desc())).all()
    rank = {"closing": 0, "open": 1, "unknown": 2, "past": 3}
    comps = sorted(allc[:300], key=lambda c: (rank[comp_status(c)[0]], comp_status(c)[2] if comp_status(c)[2] is not None else 9999, -c.id))
    return render(req, "funding.html", user, progs=progs, mine=mine, track=track, fields=fields, comps=comps, cats=sorted({c.category for c in allc}),
                  saved_c=saved_ids(s, user, "competition"), cat="")

@app.post("/save/program/{iid}/track", dependencies=[limited("track", 120, 3600)])
def track_program(req: Request, iid: int, status: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    """Application tracking for a program: saving it is implied; 'Not tracking' removes it."""
    from .models import Program
    if not user: return go("/login")
    if not s.get(Program, iid): raise HTTPException(404)
    status = status if status in dict(TRACK) else ""
    row = s.exec(select(SavedItem).where(SavedItem.user_id == user.id, SavedItem.kind == "program", SavedItem.item_id == iid)).first()
    if status == "" and row: s.delete(row)
    elif status:
        if not row: row = SavedItem(user_id=user.id, kind="program", item_id=iid)
        row.status = status; s.add(row)
    s.commit()
    return JSONResponse({"status": status}) if req.headers.get("x-fetch") else go(f"/funding#p{iid}")

@app.post("/save/competition/{iid}/track", dependencies=[limited("track", 120, 3600)])
def track_competition(req: Request, iid: int, status: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if not s.get(Competition, iid): raise HTTPException(404)
    status = status if status in dict(TRACK) else ""
    row = s.exec(select(SavedItem).where(SavedItem.user_id == user.id, SavedItem.kind == "competition", SavedItem.item_id == iid)).first()
    if not row: row = SavedItem(user_id=user.id, kind="competition", item_id=iid)
    row.status = status; s.add(row); s.commit()
    return go(f"/competitions/{iid}")

@app.post("/admin/verify/{kind}/{iid}")
def admin_verify(kind: str, iid: int, user=Depends(me), s: Session = Depends(get_session)):
    """An admin confirms an opportunity against its official page today; the date is shown to everyone."""
    from .models import Program
    if not (user and user.is_admin): raise HTTPException(404)
    x = s.get(Program if kind == "program" else Competition, iid) if kind in ("program", "competition") else None
    if not x: raise HTTPException(404)
    x.verified_at = datetime.utcnow()
    if kind == "competition": x.needs_review = False
    s.add(x); s.commit()
    return go("/funding#p%d" % iid if kind == "program" else f"/competitions/{iid}")


# ---------- deadline reminders (daily job) ----------
def send_deadline_reminders():
    """People who saved a program or competition get a notification 7 days and 1 day before its deadline (once each)."""
    from .db import engine
    from .models import Program, Notification
    from .notify import notify
    with Session(engine) as s:
        for r in s.exec(select(SavedItem).where(SavedItem.kind.in_(["program", "competition"]))).all():
            if r.status in ("applied", "accepted", "not_selected"): continue   # already done: no nagging
            x = s.get(Program if r.kind == "program" else Competition, r.item_id)
            if not x: continue
            st = prog_status(x) if r.kind == "program" else comp_status(x)
            if st[2] not in (7, 1): continue
            name = x.name if r.kind == "program" else x.title
            link = f"/funding#p{x.id}" if r.kind == "program" else f"/competitions/{x.id}"
            text = f"{name}: {st[2]} day{'s' if st[2] != 1 else ''} left"
            if s.exec(select(Notification).where(Notification.user_id == r.user_id, Notification.kind == "deadline", Notification.text == text)).first(): continue
            notify(s, [r.user_id], "deadline", text, link)
