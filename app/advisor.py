"""Advisor ecosystem: research supervision on project pages, the professor dashboard,
and the professor directory with research positions.

Every rule about who may see or change something is checked here on the server.
Who counts as what on a project:
  team      = the project lead and every accepted member (not advisor seats)
  advisors  = professors accepted on an advisor seat
  insiders  = team + advisors + admins; only they see supervision threads and milestones
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import Request, Depends, Form, HTTPException
from sqlmodel import Session, select, delete
from .db import get_session, engine
from .models import (User, Project, Role, Application, Remark, Milestone, Opening, OpeningApp,
                     FEEDBACK_CATEGORIES, FEEDBACK_PRIORITIES)
from .main import app, render, me, go, limited, days_left, tags, kind_of, templates
from .links import LinkError

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


# ---------- who is who on a project ----------
def people(s, pr):
    acc = s.exec(select(Application.user_id, Role.advisor).join(Role, Role.id == Application.role_id)
                 .where(Role.project_id == pr.id, Application.status == "accepted")).all()
    members = {uid for uid, adv in acc if not adv}
    advisors = {uid for uid, adv in acc if adv}
    return dict(owner=pr.owner_id, members=members, team=members | {pr.owner_id}, advisors=advisors)

def roles_of(user, ppl):
    if not user: return dict(team=False, adv=False, insider=False)
    team = user.id in ppl["team"]; adv = user.id in ppl["advisors"]
    return dict(team=team, adv=adv, insider=team or adv or user.is_admin)

def supervised(pr, roles):   # research projects and any project with an advisor seat get the supervision section
    return kind_of(pr) == "Research" or any(r.advisor for r in roles)


# ---------- small text helpers ----------
def clean_lines(v, n=10, w=300):
    return "\n".join([re.sub(r"\s+", " ", l).strip(" -•*")[:w] for l in str(v or "").splitlines() if l.strip()][:n])

def res_lines(text):
    """Suggested papers and links, one per line: [(label, url or None)]. Only http(s) links become links."""
    out = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line: continue
        m = URL_RE.search(line)
        if m:
            url = m.group(0).rstrip(".,;)")
            label = (line[:m.start()] + line[m.start() + len(url):]).strip(" -–:|()") or re.sub(r"^https?://(www\.)?", "", url)[:60]
            out.append((label, url))
        else: out.append((line, None))
    return out
templates.env.globals["res_lines"] = res_lines

def due_text(d):
    n = days_left(d)
    if n is None: return ""
    return "overdue" if n < 0 else ("due today" if n == 0 else f"due in {n} day{'s' if n != 1 else ''}")
templates.env.globals["due_text"] = due_text
templates.env.globals["days_left"] = days_left

def hours_ok(v):
    return bool(re.fullmatch(r"\d{1,2}(\s*[-–]\s*\d{1,2})?", v))


# ---------- research supervision on the project page ----------
def supervision(s, pr, user, ppl):
    """Threads, replies and milestones the viewer may see."""
    r = roles_of(user, ppl)
    q = select(Remark).where(Remark.project_id == pr.id, Remark.parent_id == None)
    if not r["insider"]: q = q.where(Remark.public == True, Remark.kind == "feedback")
    threads = s.exec(q).all()
    rank = {p: i for i, p in enumerate(FEEDBACK_PRIORITIES)}
    threads.sort(key=lambda t: (t.status == "resolved", rank.get(t.priority, 1), -(t.last_at or t.created).timestamp()))
    replies = defaultdict(list)
    if r["insider"] and threads:
        for x in s.exec(select(Remark).where(Remark.parent_id.in_([t.id for t in threads])).order_by(Remark.created)).all():
            replies[x.parent_id].append(x)
    ids = {t.author_id for t in threads} | {x.author_id for xs in replies.values() for x in xs}
    authors = {u.id: u for u in s.exec(select(User).where(User.id.in_(ids or {-1})))}
    ms = s.exec(select(Milestone).where(Milestone.project_id == pr.id)).all() if r["insider"] else []
    ms.sort(key=lambda m: (m.done, m.due or "9999", m.id))
    return dict(threads=threads, replies=replies, rauthors=authors, milestones=ms, sv=r, ppl=ppl,
                open_threads=[t for t in threads if t.status != "resolved"], done_threads=[t for t in threads if t.status == "resolved"],
                ms_done=len([m for m in ms if m.done]), can_ask=r["team"] and bool(ppl["advisors"]),
                categories=FEEDBACK_CATEGORIES, priorities=FEEDBACK_PRIORITIES)

def _thread_for(s, tid, user):
    t = s.get(Remark, tid)
    if not t: raise HTTPException(404)
    if t.parent_id: t = s.get(Remark, t.parent_id)
    if not t: raise HTTPException(404)
    pr = s.get(Project, t.project_id)
    if not pr: raise HTTPException(404)
    return t, pr, roles_of(user, people(s, pr))

@app.post("/projects/{pid}/threads", dependencies=[limited("thread", 40, 3600)])
def new_thread(pid: int, body: str = Form(""), category: str = Form("General"), priority: str = Form("Normal"),
               resources: str = Form(""), public: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    pr = s.get(Project, pid)
    if not pr: raise HTTPException(404)
    ppl = people(s, pr); r = roles_of(user, ppl)
    body = body.strip()[:3000]
    if not body or not (r["adv"] or (r["team"] and ppl["advisors"])): return go(f"/projects/{pid}#supervision")
    t = Remark(project_id=pid, author_id=user.id, body=body, kind="feedback" if r["adv"] else "request",
               category=category if category in FEEDBACK_CATEGORIES else "General",
               priority=priority if priority in FEEDBACK_PRIORITIES else "Normal",
               resources=clean_lines(resources) if r["adv"] else "", public=bool(public) and r["adv"],
               last_by=user.id)
    s.add(t); s.commit()
    return go(f"/projects/{pid}#t{t.id}")

@app.post("/threads/{tid}/reply", dependencies=[limited("reply", 80, 3600)])
def reply_thread(tid: int, body: str = Form(""), resources: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    t, pr, r = _thread_for(s, tid, user)
    body = body.strip()[:3000]
    if body and (r["team"] or r["adv"]):
        s.add(Remark(project_id=pr.id, author_id=user.id, body=body, kind="reply", parent_id=t.id,
                     resources=clean_lines(resources) if r["adv"] else ""))
        t.last_at, t.last_by, t.status = datetime.utcnow(), user.id, "open"   # a new message reopens the conversation
        s.add(t); s.commit()
    return go(f"/projects/{pr.id}#t{t.id}")

@app.post("/threads/{tid}/status")
def thread_status(tid: int, status: str = Form(...), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    t, pr, r = _thread_for(s, tid, user)
    if status in ("open", "resolved") and (r["team"] or r["adv"]): t.status = status; s.add(t); s.commit()
    return go(f"/projects/{pr.id}#t{t.id}")

@app.post("/remarks/{rid}/delete")
def delete_remark(rid: int, user=Depends(me), s: Session = Depends(get_session)):
    x = s.get(Remark, rid)
    if not x: raise HTTPException(404)
    if user and (user.id == x.author_id or user.is_admin):
        if x.parent_id is None: s.exec(delete(Remark).where(Remark.parent_id == x.id))
        parent = s.get(Remark, x.parent_id) if x.parent_id else None
        s.delete(x); s.commit()
        if parent:   # the thread's newest message may have changed
            last = s.exec(select(Remark).where(Remark.parent_id == parent.id).order_by(Remark.created.desc())).first()
            parent.last_at, parent.last_by = (last.created, last.author_id) if last else (parent.created, parent.author_id)
            s.add(parent); s.commit()
    return go(f"/projects/{x.project_id}#supervision")

@app.post("/projects/{pid}/milestones", dependencies=[limited("milestone", 60, 3600)])
def add_milestone(pid: int, title: str = Form(""), due: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    pr = s.get(Project, pid)
    if not pr: raise HTTPException(404)
    r = roles_of(user, people(s, pr))
    title = re.sub(r"\s+", " ", title).strip()[:120]; due = due.strip()[:10]
    if days_left(due) is None: due = ""
    count = len(s.exec(select(Milestone.id).where(Milestone.project_id == pid)).all())
    if title and (r["team"] or r["adv"]) and count < 40:
        s.add(Milestone(project_id=pid, title=title, due=due, created_by=user.id)); s.commit()
    return go(f"/projects/{pid}#milestones")

@app.post("/milestones/{mid}/{action}")
def change_milestone(mid: int, action: str, user=Depends(me), s: Session = Depends(get_session)):
    m = s.get(Milestone, mid)
    if not m: raise HTTPException(404)
    pr = s.get(Project, m.project_id)
    if not user or not pr: return go("/login")
    r = roles_of(user, people(s, pr))
    if action == "toggle" and (r["team"] or r["adv"]):
        m.done = not m.done; m.done_at = datetime.utcnow() if m.done else None; s.add(m); s.commit()
    elif action == "delete" and (user.id in (m.created_by, pr.owner_id) or user.is_admin):
        s.delete(m); s.commit()
    return go(f"/projects/{pr.id}#milestones")


# ---------- professor dashboard ----------
def advised(s, uid):
    """Projects this professor supervises: [(project, seat name)]."""
    return s.exec(select(Project, Role.name).join(Role, Role.project_id == Project.id).join(Application, Application.role_id == Role.id)
                  .where(Application.user_id == uid, Application.status == "accepted", Role.advisor == True)).all()

def waiting_reviews(s, uid, pids=None):
    """Open threads where the team wrote last: they are waiting for this professor."""
    pids = pids if pids is not None else [p.id for p, _ in advised(s, uid)]
    if not pids: return []
    advs = defaultdict(set)
    for pid, a in s.exec(select(Role.project_id, Application.user_id).join(Application, Application.role_id == Role.id)
                         .where(Role.project_id.in_(pids), Role.advisor == True, Application.status == "accepted")).all():
        advs[pid].add(a)
    ts = s.exec(select(Remark).where(Remark.project_id.in_(pids), Remark.parent_id == None, Remark.status == "open")).all()
    return [t for t in ts if t.last_by not in advs[t.project_id]]

def waiting_team(s, uid):
    """Open threads on this user's team projects where an advisor wrote last."""
    owned = [p for p in s.exec(select(Project.id).where(Project.owner_id == uid)).all()]
    joined = [p for p in s.exec(select(Role.project_id).join(Application, Application.role_id == Role.id)
                                .where(Application.user_id == uid, Application.status == "accepted", Role.advisor == False)).all()]
    pids = list(set(owned) | set(joined))
    if not pids: return []
    advs = defaultdict(set)
    for pid, a in s.exec(select(Role.project_id, Application.user_id).join(Application, Application.role_id == Role.id)
                         .where(Role.project_id.in_(pids), Role.advisor == True, Application.status == "accepted")).all():
        advs[pid].add(a)
    ts = s.exec(select(Remark).where(Remark.project_id.in_(pids), Remark.parent_id == None, Remark.status == "open")).all()
    return [t for t in ts if t.last_by in advs[t.project_id]]

def inbox_extra(s, user):
    """Things waiting for this user besides project applications (added to the Activity badge)."""
    n = len(waiting_team(s, user.id))
    if user.role == "faculty":
        n += len(waiting_reviews(s, user.id))
        mine = [o.id for o in s.exec(select(Opening).where(Opening.owner_id == user.id)).all()]
        if mine: n += len(s.exec(select(OpeningApp.id).where(OpeningApp.opening_id.in_(mine), OpeningApp.status == "pending")).all())
    return n

@app.get("/advisor")
def dashboard(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if user.role != "faculty": return go("/research")
    rows = advised(s, user.id); pids = [p.id for p, _ in rows]
    reviews = waiting_reviews(s, user.id, pids)
    projects = {p.id: p for p, _ in rows}
    # team of each project
    team = defaultdict(set)
    for p in projects.values(): team[p.id].add(p.owner_id)
    if pids:
        for pid, uid in s.exec(select(Role.project_id, Application.user_id).join(Application, Application.role_id == Role.id)
                               .where(Role.project_id.in_(pids), Role.advisor == False, Application.status == "accepted")).all():
            team[pid].add(uid)
    students = set().union(*team.values()) if team else set()
    ms = s.exec(select(Milestone).where(Milestone.project_id.in_(pids or [-1]))).all()
    threads = s.exec(select(Remark).where(Remark.project_id.in_(pids or [-1]))).all()
    names = {u.id: u for u in s.exec(select(User).where(User.id.in_((students | {t.author_id for t in threads}) or {-1})))}
    # progress per project
    prog = []
    for p, seat in rows:
        pm = [m for m in ms if m.project_id == p.id]
        nxt = sorted([m for m in pm if not m.done], key=lambda m: m.due or "9999")
        stamps = [t.created for t in threads if t.project_id == p.id] + [m.done_at or m.created for m in pm]
        prog.append(dict(p=p, seat=seat, students=len(team[p.id]), done=len([m for m in pm if m.done]), total=len(pm),
                         next=nxt[0] if nxt else None, overdue=len([m for m in nxt if m.due and (days_left(m.due) or 0) < 0]),
                         open=len([t for t in threads if t.project_id == p.id and t.parent_id is None and t.status == "open"]),
                         waiting=len([t for t in reviews if t.project_id == p.id]),
                         last=max(stamps) if stamps else None))
    prog.sort(key=lambda x: (-x["waiting"], -x["overdue"], -(x["last"].timestamp() if x["last"] else 0)))
    upcoming = sorted([m for m in ms if not m.done and m.due and (days_left(m.due) is not None) and days_left(m.due) <= 30],
                      key=lambda m: m.due)[:8]
    # recent activity: messages from the teams and milestones they finished
    events = [("msg", t.created, t) for t in threads if t.author_id != user.id]
    events += [("done", m.done_at, m) for m in ms if m.done and m.done_at]
    events = sorted(events, key=lambda e: e[1], reverse=True)[:10]
    openings = s.exec(select(Opening).where(Opening.owner_id == user.id).order_by(Opening.created.desc())).all()
    oapps = defaultdict(lambda: [0, 0])   # [pending, accepted]
    for a in s.exec(select(OpeningApp).where(OpeningApp.opening_id.in_([o.id for o in openings] or [-1]))).all():
        if a.status == "pending": oapps[a.opening_id][0] += 1
        elif a.status == "accepted": oapps[a.opening_id][1] += 1
    seat_apps = s.exec(select(Application, Role, Project).join(Role, Role.id == Application.role_id).join(Project, Project.id == Role.project_id)
                       .where(Application.user_id == user.id, Application.status == "pending")).all()
    return render(req, "advisor.html", user, projects=projects, prog=prog, reviews=sorted(reviews, key=lambda t: t.last_at or t.created),
                  students=len(students), upcoming=upcoming, events=events, names=names, openings=openings, oapps=oapps,
                  pending_lab=sum(v[0] for v in oapps.values()), seat_apps=seat_apps)


# ---------- professor directory and research positions ----------
def opening_state(s, o):
    acc = len(s.exec(select(OpeningApp.id).where(OpeningApp.opening_id == o.id, OpeningApp.status == "accepted")).all())
    d = days_left(o.deadline)
    full = acc >= o.positions
    return dict(accepted=acc, full=full, days=d, taking=o.status == "open" and not full and not (d is not None and d < 0))

@app.get("/research")
def research(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    profs = s.exec(select(User).where(User.is_faculty == True, User.banned == False).order_by(User.name)).all()
    pmap = {p.id: p for p in profs}
    openings, counts = [], defaultdict(int)
    for o in s.exec(select(Opening).where(Opening.status == "open").order_by(Opening.created.desc())).all():
        st = opening_state(s, o)
        if o.owner_id in pmap and st["taking"]:
            openings.append(dict(o=o, prof=pmap[o.owner_id], **st)); counts[o.owner_id] += 1
    mine = tags(user.skills) if user else set()
    for x in openings: x["fit"] = sorted(mine & tags(x["o"].skills))
    return render(req, "research.html", user, openings=openings, profs=profs, counts=counts, mytags=mine)

def read_opening(form):
    f = {k: str(form.get(k, "")).replace("\r", "").strip() for k in ("title", "description", "skills", "requirements", "hours", "positions", "deadline", "process")}
    out = dict(title=re.sub(r"\s+", " ", f["title"])[:120], description=f["description"][:2000],
               skills=",".join(t.strip() for t in f["skills"].split(",") if t.strip())[:200],
               requirements=clean_lines(f["requirements"], 8, 160), hours=re.sub(r"\s+", "", f["hours"])[:7].replace("–", "-"),
               deadline=f["deadline"][:10], process=f["process"][:800])
    try: out["positions"] = int(f["positions"] or 1)
    except ValueError: out["positions"] = 0
    err = ""
    if len(out["title"]) < 5: err = "Give the position a title (at least 5 characters)."
    elif len(out["description"]) < 20: err = "Describe the research and what the student will do (at least 20 characters)."
    elif not hours_ok(out["hours"]): err = "Hours per week must be a number or a range, for example 6 or 8-10."
    elif not 1 <= out["positions"] <= 20: err = "Positions must be a number from 1 to 20."
    elif out["deadline"] and days_left(out["deadline"]) is None: err = "The application deadline is not a valid date."
    return out, err

def _prof_only(user):
    return user and user.is_faculty

@app.get("/openings/new")
def opening_new(req: Request, user=Depends(me)):
    if not user: return go("/login")
    if not _prof_only(user): return go("/research")
    return render(req, "opening_form.html", user, o=None, error="")

@app.post("/openings/new", dependencies=[limited("opening", 20, 3600)])
async def opening_create(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if not _prof_only(user): return go("/research")
    f, err = read_opening(await req.form())
    if not err and f["deadline"] and days_left(f["deadline"]) < 0: err = "The application deadline is in the past."
    if not err and len(s.exec(select(Opening.id).where(Opening.owner_id == user.id, Opening.status == "open")).all()) >= 10:
        err = "You can have at most 10 open positions. Close one first."
    if err: return render(req, "opening_form.html", user, o=Opening(owner_id=user.id, **f), error=err)
    o = Opening(owner_id=user.id, **f); s.add(o); s.commit(); s.refresh(o)
    return go(f"/openings/{o.id}")

@app.get("/openings/{oid}")
def opening_page(req: Request, oid: int, user=Depends(me), s: Session = Depends(get_session)):
    o = s.get(Opening, oid); prof = s.get(User, o.owner_id) if o else None
    if not o or not prof or prof.banned: raise HTTPException(404)
    is_owner = bool(user and user.id == o.owner_id)
    st = opening_state(s, o)
    apps = []
    if is_owner or (user and user.is_admin):
        for a in s.exec(select(OpeningApp).where(OpeningApp.opening_id == oid).order_by(OpeningApp.at)).all():
            apps.append((a, s.get(User, a.user_id)))
    mine = s.exec(select(OpeningApp).where(OpeningApp.opening_id == oid, OpeningApp.user_id == user.id)).first() if user else None
    return render(req, "opening.html", user, o=o, prof=prof, is_owner=is_owner, apps=[x for x in apps if x[1]], mine=mine,
                  mytags=tags(user.skills) if user else set(), notice=req.query_params.get("n", ""), **st)

@app.get("/openings/{oid}/edit")
def opening_edit(req: Request, oid: int, user=Depends(me), s: Session = Depends(get_session)):
    o = s.get(Opening, oid)
    if not o: raise HTTPException(404)
    if not user or user.id != o.owner_id: return go(f"/openings/{oid}")
    return render(req, "opening_form.html", user, o=o, error="")

@app.post("/openings/{oid}/edit", dependencies=[limited("openingedit", 40, 3600)])
async def opening_save(req: Request, oid: int, user=Depends(me), s: Session = Depends(get_session)):
    o = s.get(Opening, oid)
    if not o: raise HTTPException(404)
    if not user or user.id != o.owner_id: return go(f"/openings/{oid}")
    f, err = read_opening(await req.form())
    if not err and f["deadline"] and days_left(f["deadline"]) < 0 and f["deadline"] != o.deadline: err = "The application deadline is in the past."
    if err:
        for k, v in f.items(): setattr(o, k, v)
        s.expunge(o); return render(req, "opening_form.html", user, o=o, error=err)
    for k, v in f.items(): setattr(o, k, v)
    s.add(o); s.commit(); return go(f"/openings/{oid}")

@app.post("/openings/{oid}/status")
def opening_status(oid: int, status: str = Form(...), user=Depends(me), s: Session = Depends(get_session)):
    o = s.get(Opening, oid)
    if o and user and user.id == o.owner_id and status in ("open", "closed"): o.status = status; s.add(o); s.commit()
    return go(f"/openings/{oid}")

@app.post("/openings/{oid}/delete")
def opening_delete(oid: int, user=Depends(me), s: Session = Depends(get_session)):
    o = s.get(Opening, oid)
    if o and user and (user.id == o.owner_id or user.is_admin):
        s.exec(delete(OpeningApp).where(OpeningApp.opening_id == oid)); s.delete(o); s.commit()
        return go("/advisor" if user.id == o.owner_id else "/research")
    return go(f"/openings/{oid}")

@app.post("/openings/{oid}/apply", dependencies=[limited("openingapply", 30, 3600)])
def opening_apply(oid: int, message: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    o = s.get(Opening, oid)
    if not o: raise HTTPException(404)
    if user.id == o.owner_id or user.role == "faculty": return go(f"/openings/{oid}")
    if not opening_state(s, o)["taking"]: return go(f"/openings/{oid}?n=closed")
    message = message.strip()[:1000]
    if len(message) < 10: return go(f"/openings/{oid}?n=short")
    dup = s.exec(select(OpeningApp).where(OpeningApp.opening_id == oid, OpeningApp.user_id == user.id)).first()
    if dup and dup.status == "withdrawn": dup.status, dup.message, dup.at = "pending", message, datetime.utcnow(); s.add(dup); s.commit()
    elif not dup: s.add(OpeningApp(opening_id=oid, user_id=user.id, message=message)); s.commit()
    return go(f"/openings/{oid}?n=sent")

@app.post("/opening-apps/{aid}/edit", dependencies=[limited("oappedit", 40, 3600)])
def opening_app_edit(aid: int, message: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    a = s.get(OpeningApp, aid)
    if not a: raise HTTPException(404)
    message = message.strip()[:1000]
    if user and a.user_id == user.id and a.status == "pending" and len(message) >= 10: a.message = message; s.add(a); s.commit()
    return go(f"/openings/{a.opening_id}?n=edited")

@app.post("/opening-apps/{aid}/{decision}")
def opening_decide(aid: int, decision: str, next: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    a = s.get(OpeningApp, aid); o = s.get(Opening, a.opening_id) if a else None
    if not o: raise HTTPException(404)
    if not user: return go("/login")
    if decision == "withdrawn" and a.user_id == user.id and a.status == "pending":
        a.status = "withdrawn"; s.add(a); s.commit()
        return go("/activity?n=withdrawn" if next == "/activity" else f"/openings/{o.id}?n=withdrawn")
    if user.id == o.owner_id and a.status == "pending" and decision in ("accepted", "rejected"):
        if decision == "accepted" and opening_state(s, o)["full"]: return go(f"/openings/{o.id}?n=full")
        a.status = decision; s.add(a); s.commit()
        if decision == "accepted" and opening_state(s, o)["full"]:   # every position is taken: close the other applications
            for x in s.exec(select(OpeningApp).where(OpeningApp.opening_id == o.id, OpeningApp.status == "pending")).all():
                x.status = "closed"; s.add(x)
            s.commit()
    return go(f"/openings/{o.id}#applicants")

def clean_url(v, hosts=()):
    from urllib.parse import urlparse
    v = (v or "").strip()
    if not v: return ""
    if not re.match(r"^[a-z]+://", v, re.I): v = "https://" + v
    u = urlparse(v)
    if u.scheme.lower() not in ("http", "https") or not u.hostname or "." not in u.hostname: raise LinkError("that doesn't look like a link.")
    if hosts and not any(u.hostname.lower() == h or u.hostname.lower().endswith("." + h) for h in hosts): raise LinkError("wrong site.")
    return ("https://" + v.split("://", 1)[1])[:200]

@app.post("/profile/research", dependencies=[limited("research", 30, 3600)])
def profile_research(req: Request, research: str = Form(""), lab_name: str = Form(""), lab_url: str = Form(""), orcid: str = Form(""),
                     user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if user.role != "faculty": return go("/profile")
    from .links import ORCID
    try:
        lab = clean_url(lab_url)
        oc = orcid.strip()
        oc = "https://orcid.org/" + oc.upper() if ORCID.match(oc) else clean_url(oc, ("orcid.org",))
    except LinkError:
        return render(req, "profile.html", user, error="Lab website and ORCID must be links (ORCID on orcid.org, or just your ORCID iD).")
    user.research = ", ".join(sorted({t.strip()[:40] for t in research.split(",") if t.strip()}, key=str.lower)[:12])
    user.lab_name = re.sub(r"\s+", " ", lab_name).strip()[:100]; user.lab_url = lab; user.orcid = oc
    s.add(user); s.commit()
    return go("/profile?n=research#research")
