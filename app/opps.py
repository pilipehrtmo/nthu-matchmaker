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
    if kind not in ("competition", "project"): raise HTTPException(404)
    if not user: return JSONResponse({"error": "login"}, status_code=401) if req.headers.get("x-fetch") else go("/login")
    target = s.get(Competition if kind == "competition" else Project, iid)
    if not target: raise HTTPException(404)
    row = s.exec(select(SavedItem).where(SavedItem.user_id == user.id, SavedItem.kind == kind, SavedItem.item_id == iid)).first()
    if row: s.delete(row); on = False
    else: s.add(SavedItem(user_id=user.id, kind=kind, item_id=iid)); on = True
    s.commit()
    if req.headers.get("x-fetch"): return JSONResponse({"saved": on})
    back = next if re.fullmatch(r"/(projects|competitions)/\d+|/activity|/", next) else "/"
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
    return render(req, "competition.html", user, c=c, st=comp_status(c), teams=teams, owners=owners, open_seats=open_seats, mine=mine,
                  saved=cid in saved_ids(s, user, "competition"))

def saved_for(s, user):
    """Saved competitions and projects for the Activity page (missing ones are skipped)."""
    rows = s.exec(select(SavedItem).where(SavedItem.user_id == user.id).order_by(SavedItem.created.desc())).all()
    cids = [r.item_id for r in rows if r.kind == "competition"]; pids = [r.item_id for r in rows if r.kind == "project"]
    comps = {c.id: c for c in s.exec(select(Competition).where(Competition.id.in_(cids or [-1]))).all()}
    projs = {p.id: p for p in s.exec(select(Project).where(Project.id.in_(pids or [-1]))).all()}
    return [("competition", comps[r.item_id]) for r in rows if r.kind == "competition" and r.item_id in comps] + \
           [("project", projs[r.item_id]) for r in rows if r.kind == "project" and r.item_id in projs]
