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
from .models import (User, Project, Role, Application, Remark, RemarkEvent, DocVersion, Milestone, Opening, OpeningApp,
                     FEEDBACK_CATEGORIES, FEEDBACK_PRIORITIES)
from . import validate as V
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
    team = user.id in ppl["team"]; adv = user.id in ppl["advisors"] and user.is_faculty   # a suspended professor keeps the seat but loses advisor rights
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
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
def day_box(d):   # "2026-11-30" -> ("30", "NOV") for the date boxes on the dashboard
    try: y, m, dd = d.split("-"); return str(int(dd)), MONTHS[int(m) - 1]
    except (ValueError, IndexError, AttributeError): return "", ""
templates.env.globals["day_box"] = day_box

def hours_ok(v):
    return bool(re.fullmatch(r"\d{1,2}(\s*[-–]\s*\d{1,2})?", v))


# ---------- research supervision on the project page ----------
STATE_LABEL = {"open": "Open", "in_progress": "In progress", "submitted": "Submitted for review", "resolved": "Resolved", "reopened": "Reopened"}
templates.env.globals["STATE_LABEL"] = STATE_LABEL

def is_done(t): return t.state == "resolved"

def supervision(s, pr, user, ppl):
    """Threads, replies, history and milestones the viewer may see."""
    from .docs import doc_versions_for, visible_version
    r = roles_of(user, ppl)
    q = select(Remark).where(Remark.project_id == pr.id, Remark.parent_id == None)
    if not r["insider"]: q = q.where(Remark.public == True, Remark.kind == "feedback", Remark.deleted_at == None)
    threads = s.exec(q).all()
    if not r["insider"]:   # public feedback written on a version outsiders cannot open stays hidden
        threads = [t for t in threads if not t.version_id or visible_version(s, user, t.version_id)]
    replies = defaultdict(list)
    if r["insider"] and threads:
        for x in s.exec(select(Remark).where(Remark.parent_id.in_([t.id for t in threads])).order_by(Remark.created)).all():
            replies[x.parent_id].append(x)
    threads = [t for t in threads if not t.deleted_at or any(not x.deleted_at for x in replies[t.id])]   # a deleted thread stays only for others' replies
    rank = {p: i for i, p in enumerate(FEEDBACK_PRIORITIES)}
    threads.sort(key=lambda t: (is_done(t), rank.get(t.priority, 1), -(t.last_at or t.created).timestamp()))
    events = defaultdict(list)
    if r["insider"] and threads:
        for e in s.exec(select(RemarkEvent).where(RemarkEvent.remark_id.in_([t.id for t in threads])).order_by(RemarkEvent.created)).all():
            events[e.remark_id].append(e)
    ids = {t.author_id for t in threads} | {x.author_id for xs in replies.values() for x in xs} | {e.actor_id for es in events.values() for e in es}
    authors = {u.id: u for u in s.exec(select(User).where(User.id.in_(ids or {-1})))}
    ms = s.exec(select(Milestone).where(Milestone.project_id == pr.id)).all() if r["insider"] else []
    ms.sort(key=lambda m: (m.done, m.due or "9999", m.id))
    vinfo, choices = doc_versions_for(s, pr, user) if r["insider"] else ({}, [])
    return dict(threads=threads, replies=replies, events=events, rauthors=authors, milestones=ms, sv=r, ppl=ppl, vinfo=vinfo, version_choices=choices,
                open_threads=[t for t in threads if not is_done(t)], done_threads=[t for t in threads if is_done(t)],
                ms_done=len([m for m in ms if m.done]), can_ask=r["team"] and bool(ppl["advisors"]),
                categories=FEEDBACK_CATEGORIES, priorities=FEEDBACK_PRIORITIES)

def _thread_for(s, tid, user):
    t = s.get(Remark, tid)
    if not t: raise HTTPException(404)
    if t.parent_id: t = s.get(Remark, t.parent_id)
    if not t: raise HTTPException(404)
    pr = s.get(Project, t.project_id)
    if not pr: raise HTTPException(404)
    ppl = people(s, pr)
    return t, pr, roles_of(user, ppl), ppl

def thread_link(t): return f"/projects/{t.project_id}#t{t.id}"

def short(text, n=60):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"

def submitter_of(s, t):
    e = s.exec(select(RemarkEvent).where(RemarkEvent.remark_id == t.id, RemarkEvent.to_state == "submitted").order_by(RemarkEvent.created.desc())).first()
    return e.actor_id if e else 0

def can_move(s, t, user, r, to, pr):
    """The one rule book for status changes. Feedback: only advisors resolve or reopen. Questions: the team closes them."""
    frm = t.state
    if t.deleted_at or to == frm: return False
    if t.kind == "request":
        return to in ("resolved", "open") and (r["team"] or r["adv"])
    if to == "in_progress":
        if frm in ("open", "reopened"): return r["team"]
        if frm == "submitted": return r["team"] and user.id in (submitter_of(s, t), pr.owner_id)   # withdraw before the professor looks
        return False
    if to == "submitted": return r["team"] and frm in ("open", "in_progress", "reopened")
    if to == "resolved": return r["adv"]
    if to == "reopened": return r["adv"] and frm in ("submitted", "resolved")
    return False

def move_state(s, t, user, to, note="", version_id=None, pr=None, ppl=None, notify_people=True):
    """Change a thread's state and record it. The caller has already checked can_move."""
    from .notify import notify
    frm = t.state; now = datetime.utcnow()
    t.state = to; t.status = "resolved" if to == "resolved" else "open"; t.last_at = now
    if to == "resolved": t.resolved_by, t.resolved_at = user.id, now
    if to == "submitted" and version_id: t.fixed_in_version_id = version_id
    s.add(t); s.add(RemarkEvent(remark_id=t.id, actor_id=user.id, from_state=frm, to_state=to, version_id=version_id, note=note[:1000])); s.commit()
    if not notify_people: return
    pr = pr or s.get(Project, t.project_id); ppl = ppl or people(s, pr); name = user.name or user.handle; what = short(t.body, 50)
    if t.kind == "request": return
    if to == "submitted": notify(s, ppl["advisors"], "remark_submitted", f"{name} marked “{what}” as fixed and asks you to check it", thread_link(t), pr.id, user.id)
    elif to == "resolved": notify(s, ppl["team"], "remark_resolved", f"Feedback confirmed resolved: “{what}”", thread_link(t), pr.id, user.id)
    elif to == "reopened": notify(s, ppl["team"] | {submitter_of(s, t)}, "remark_reopened", f"Feedback reopened: “{what}” · {short(note, 80)}", thread_link(t), pr.id, user.id)

@app.post("/projects/{pid}/threads", dependencies=[limited("thread", 40, 3600)])
def new_thread(pid: int, body: str = Form(""), category: str = Form("General"), priority: str = Form("Normal"), resources: str = Form(""),
               public: str = Form(""), version_id: str = Form(""), anchor: str = Form(""), next: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    from .notify import notify
    from .docs import version_of_project, visible_version
    if not user: return go("/login")
    pr = s.get(Project, pid)
    if not pr: raise HTTPException(404)
    ppl = people(s, pr); r = roles_of(user, ppl)
    body = body.strip()[:3000]
    back = next if re.fullmatch(r"/docs/\d+(\?v=\d+)?", next) else f"/projects/{pid}#supervision"
    if not body or not (r["adv"] or (r["team"] and ppl["advisors"])): return go(back)
    v = version_of_project(s, pr, version_id, user) if version_id else None   # feedback written on a document version
    pub = bool(public) and r["adv"]
    if pub and v and not visible_version(s, None, v.id, any_logged_in=True): pub = False   # never public feedback on a non-public version
    t = Remark(project_id=pid, author_id=user.id, body=body, kind="feedback" if r["adv"] else "request",
               category=category if category in FEEDBACK_CATEGORIES else "General",
               priority=priority if priority in FEEDBACK_PRIORITIES else "Normal",
               resources=clean_lines(resources) if r["adv"] else "", public=pub, last_by=user.id,
               doc_id=v.doc_id if v else None, version_id=v.id if v else None, anchor=re.sub(r"\s+", " ", anchor).strip()[:120] if v else "")
    s.add(t); s.commit(); s.refresh(t)
    name = user.name or user.handle
    if r["adv"]: notify(s, ppl["team"], "feedback", f"New feedback from {name} ({t.category}{', high priority' if t.priority == 'High' else ''}): “{short(body, 50)}”", thread_link(t), pid, user.id)
    else: notify(s, ppl["advisors"], "request", f"{name} asked for your feedback: “{short(body, 60)}”", thread_link(t), pid, user.id)
    return go(back if back.startswith("/docs/") else thread_link(t))

@app.post("/threads/{tid}/reply", dependencies=[limited("reply", 80, 3600)])
def reply_thread(tid: int, body: str = Form(""), resources: str = Form(""), next: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    from .notify import notify
    if not user: return go("/login")
    t, pr, r, ppl = _thread_for(s, tid, user)
    body = body.strip()[:3000]
    if body and (r["team"] or r["adv"]) and not (t.deleted_at and t.kind == "request"):
        s.add(Remark(project_id=pr.id, author_id=user.id, body=body, kind="reply", parent_id=t.id,
                     resources=clean_lines(resources) if r["adv"] else ""))
        t.last_at, t.last_by = datetime.utcnow(), user.id   # a reply no longer changes the status
        s.add(t); s.commit()
        others = {x.author_id for x in s.exec(select(Remark).where(Remark.parent_id == t.id)).all()} | {t.author_id}
        others |= ppl["team"] if r["adv"] else ppl["advisors"]
        notify(s, others & (ppl["team"] | ppl["advisors"]), "reply", f"{user.name or user.handle} replied on “{short(t.body, 50)}”", thread_link(t), pr.id, user.id)
    return go(next + f"#t{t.id}" if re.fullmatch(r"/docs/\d+(\?v=\d+)?", next) else thread_link(t))

@app.post("/threads/{tid}/state", dependencies=[limited("tstate", 120, 3600)])
def thread_state(tid: int, to: str = Form(...), note: str = Form(""), version_id: str = Form(""), next: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    from .docs import version_of_project
    if not user: return go("/login")
    t, pr, r, ppl = _thread_for(s, tid, user)
    note = note.strip()[:1000]
    back = next + f"#t{t.id}" if re.fullmatch(r"/docs/\d+(\?v=\d+)?", next) else thread_link(t)
    if to == "reopened" and not note: return go(back)                       # a reopen needs a reason
    if to == "submitted" and t.kind == "feedback" and not note: return go(back)   # say what changed
    v = version_of_project(s, pr, version_id, user) if version_id else None
    if can_move(s, t, user, r, to, pr):
        move_state(s, t, user, to, note, v.id if v else None, pr, ppl)
        if v and to == "submitted":
            from .models import VersionAddresses
            if not s.exec(select(VersionAddresses).where(VersionAddresses.version_id == v.id, VersionAddresses.remark_id == t.id)).first():
                s.add(VersionAddresses(version_id=v.id, remark_id=t.id, note=note)); s.commit()
    return go(back)

@app.post("/threads/{tid}/status")   # old two-button form (kept so open pages from before the upgrade still work)
def thread_status(tid: int, status: str = Form(...), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    t, pr, r, ppl = _thread_for(s, tid, user)
    to = "resolved" if status == "resolved" else ("open" if t.kind == "request" else "reopened")
    if can_move(s, t, user, r, to, pr) and (to != "reopened"): move_state(s, t, user, to, "", None, pr, ppl)
    return go(thread_link(t))

@app.post("/remarks/{rid}/delete")
def delete_remark(rid: int, next: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    """Soft delete: the words become [deleted]; the thread, its history and other people's replies stay."""
    x = s.get(Remark, rid)
    if not x: raise HTTPException(404)
    if user and (user.id == x.author_id or user.is_admin) and not x.deleted_at:
        x.deleted_at = datetime.utcnow(); s.add(x); s.commit()
        parent = s.get(Remark, x.parent_id) if x.parent_id else None
        if parent:   # the thread's newest message may have changed
            last = s.exec(select(Remark).where(Remark.parent_id == parent.id, Remark.deleted_at == None).order_by(Remark.created.desc())).first()
            parent.last_at, parent.last_by = (last.created, last.author_id) if last else (parent.created, parent.author_id)
            s.add(parent); s.commit()
    return go(next if re.fullmatch(r"/docs/\d+(\?v=\d+)?", next) else f"/projects/{x.project_id}#supervision")

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

def _advisors_by_project(s, pids):
    advs = defaultdict(set)
    for pid, a in s.exec(select(Role.project_id, Application.user_id).join(Application, Application.role_id == Role.id)
                         .where(Role.project_id.in_(pids), Role.advisor == True, Application.status == "accepted")).all():
        advs[pid].add(a)
    return advs

def waiting_reviews(s, uid, pids=None):
    """Threads waiting for the professor: feedback marked as fixed, and conversations where the team wrote last."""
    pids = pids if pids is not None else [p.id for p, _ in advised(s, uid)]
    if not pids: return []
    advs = _advisors_by_project(s, pids)
    ts = s.exec(select(Remark).where(Remark.project_id.in_(pids), Remark.parent_id == None, Remark.deleted_at == None, Remark.state != "resolved")).all()
    return [t for t in ts if (t.kind == "feedback" and t.state == "submitted") or t.last_by not in advs[t.project_id]]

def waiting_team(s, uid):
    """Threads on this user's team projects that the team should act on: new or reopened feedback, and answered questions."""
    owned = [p for p in s.exec(select(Project.id).where(Project.owner_id == uid)).all()]
    joined = [p for p in s.exec(select(Role.project_id).join(Application, Application.role_id == Role.id)
                                .where(Application.user_id == uid, Application.status == "accepted", Role.advisor == False)).all()]
    pids = list(set(owned) | set(joined))
    if not pids: return []
    advs = _advisors_by_project(s, pids)
    ts = s.exec(select(Remark).where(Remark.project_id.in_(pids), Remark.parent_id == None, Remark.deleted_at == None, Remark.state != "resolved")).all()
    out = []
    for t in ts:
        if t.kind == "feedback" and (t.state in ("open", "reopened") or (t.state == "in_progress" and t.last_by in advs[t.project_id])): out.append(t)
        elif t.kind == "request" and t.last_by in advs[t.project_id]: out.append(t)
    return out

def waiting_doc_reviews(s, pids):
    """Documents a team asked its advisors to review, still waiting."""
    from .models import ResearchDoc, ReviewRequest
    if not pids: return []
    return s.exec(select(ReviewRequest, ResearchDoc).join(ResearchDoc, ResearchDoc.id == ReviewRequest.doc_id)
                  .where(ResearchDoc.project_id.in_(pids), ResearchDoc.visibility != "private", ReviewRequest.status == "waiting")
                  .order_by(ReviewRequest.created)).all()

def attention(s, user):
    """Everything waiting for this person. The badge in the top bar and the dashboard both use THIS count, so they always agree."""
    a = dict(team=waiting_team(s, user.id), reviews=[], docs=[], lab=[], overdue=[])
    a["apps"] = len(s.exec(select(Application.id).join(Role, Role.id == Application.role_id).join(Project, Project.id == Role.project_id)
                           .where(Project.owner_id == user.id, Application.status == "pending")).all())
    if user.is_faculty:
        pids = [p.id for p, _ in advised(s, user.id)]
        a["reviews"] = waiting_reviews(s, user.id, pids)
        a["docs"] = waiting_doc_reviews(s, pids)
        mine = s.exec(select(Opening).where(Opening.owner_id == user.id)).all()
        pend = defaultdict(int)
        for x in s.exec(select(OpeningApp).where(OpeningApp.opening_id.in_([o.id for o in mine] or [-1]), OpeningApp.status == "pending")).all(): pend[x.opening_id] += 1
        a["lab"] = [(o, pend[o.id]) for o in mine if pend[o.id]]
        for pid in pids:
            late = [m for m in s.exec(select(Milestone).where(Milestone.project_id == pid, Milestone.done == False)).all() if m.due and (days_left(m.due) or 0) < 0]
            if late: a["overdue"].append(pid)
    a["total"] = len(a["team"]) + a["apps"] + len(a["reviews"]) + len(a["docs"]) + len(a["lab"]) + len(a["overdue"])
    return a

def inbox_extra(s, user):   # kept for older callers
    a = attention(s, user); return a["total"] - a["apps"]

@app.get("/advisor")
def dashboard(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if user.role != "faculty": return go("/research")
    if not user.is_faculty: return go("/verification")   # the dashboard is for verified professors only
    rows = advised(s, user.id); pids = [p.id for p, _ in rows]
    att = attention(s, user)
    reviews = att["reviews"]; doc_reviews = att["docs"]
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
                         open=len([t for t in threads if t.project_id == p.id and t.parent_id is None and t.state != "resolved" and not t.deleted_at]),
                         waiting=len([t for t in reviews if t.project_id == p.id]) + len([1 for rq, d in doc_reviews if d.project_id == p.id]),
                         people=[names[u] for u in sorted(team[p.id], key=lambda u: u != p.owner_id) if u in names],
                         last=max(stamps) if stamps else None))
    prog.sort(key=lambda x: (-x["waiting"], -x["overdue"], -(x["last"].timestamp() if x["last"] else 0)))
    upcoming = sorted([m for m in ms if not m.done and m.due and (days_left(m.due) is not None) and days_left(m.due) <= 30],
                      key=lambda m: m.due)[:8]
    # recent activity: messages from the teams and milestones they finished
    events = [("msg", t.created, t) for t in threads if t.author_id != user.id and not t.deleted_at]
    events += [("done", m.done_at, m) for m in ms if m.done and m.done_at]
    events = sorted(events, key=lambda e: e[1], reverse=True)[:10]
    openings = s.exec(select(Opening).where(Opening.owner_id == user.id).order_by(Opening.created.desc())).all()
    oapps = defaultdict(lambda: [0, 0])   # [pending, accepted]
    for a in s.exec(select(OpeningApp).where(OpeningApp.opening_id.in_([o.id for o in openings] or [-1]))).all():
        if a.status == "pending": oapps[a.opening_id][0] += 1
        elif a.status == "accepted": oapps[a.opening_id][1] += 1
    seat_apps = s.exec(select(Application, Role, Project).join(Role, Role.id == Application.role_id).join(Project, Project.id == Role.project_id)
                       .where(Application.user_id == user.id, Application.status == "pending")).all()
    from datetime import timezone
    h = datetime.now(timezone(timedelta(hours=8))).hour   # Taiwan time (no daylight saving), whatever the server's clock is set to
    greet = "Good morning" if 5 <= h < 12 else ("Good afternoon" if 12 <= h < 18 else "Good evening")
    t = user.title or "Professor"
    honor = "Professor" if "Professor" in t else t   # an Associate or Assistant Professor is addressed as Professor; never abbreviated
    rank = {p: i for i, p in enumerate(FEEDBACK_PRIORITIES)}
    reviews = sorted(reviews, key=lambda t: (rank.get(t.priority, 1), t.last_at or t.created))   # high priority first, then the longest waiting
    open_pos = len([o for o in openings if opening_state(s, o)["taking"]])
    return render(req, "advisor.html", user, greet=greet, honor=honor, projects=projects, prog=prog, reviews=reviews, open_pos=open_pos,
                  high=len([t for t in reviews if t.priority == "High"]), overdue=sum(x["overdue"] for x in prog), teams=len([x for x in prog if x["people"]]),
                  students=len(students), upcoming=upcoming, events=events, names=names, openings=openings, oapps=oapps,
                  pending_lab=sum(v[0] for v in oapps.values()), seat_apps=seat_apps, att=att, doc_reviews=doc_reviews,
                  vnum={v.id: v.number for v in s.exec(select(DocVersion).where(DocVersion.id.in_([rq.version_id for rq, _ in doc_reviews] or [-1]))).all()},
                  fbp={p.id: p for p in s.exec(select(Project).where(Project.id.in_({t.project_id for t in att["team"]} or {-1})))},
                  doc_open=_doc_open(s, [d.id for _, d in doc_reviews]))

def _doc_open(s, dids):
    """Per document under review: (unresolved remarks, how many of them are high priority)."""
    out = {d: [0, 0] for d in dids}
    if dids:
        for t in s.exec(select(Remark).where(Remark.doc_id.in_(dids), Remark.parent_id == None, Remark.deleted_at == None, Remark.state != "resolved")).all():
            out[t.doc_id][0] += 1; out[t.doc_id][1] += t.priority == "High"
    return out


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
    message = V.normalize_text(message)
    if len(message) < V.NOTE_MIN: return go(f"/openings/{oid}?n=short")
    if len(message) > V.NOTE_MAX: return go(f"/openings/{oid}?n=long")
    dup = s.exec(select(OpeningApp).where(OpeningApp.opening_id == oid, OpeningApp.user_id == user.id)).first()
    if dup and dup.status == "withdrawn": dup.status, dup.message, dup.at = "pending", message, datetime.utcnow(); s.add(dup); s.commit()
    elif not dup: s.add(OpeningApp(opening_id=oid, user_id=user.id, message=message)); s.commit()
    else: return go(f"/openings/{oid}?n=sent")   # already applied: no second application, no second notification
    from .notify import notify
    notify(s, [o.owner_id], "lab_application", f"{user.name or user.handle} applied for {o.title}", f"/openings/{oid}#applicants", None, user.id)
    return go(f"/openings/{oid}?n=sent")

@app.post("/opening-apps/{aid}/edit", dependencies=[limited("oappedit", 40, 3600)])
def opening_app_edit(aid: int, message: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    a = s.get(OpeningApp, aid)
    if not a: raise HTTPException(404)
    message = V.normalize_text(message)
    if not V.NOTE_MIN <= len(message) <= V.NOTE_MAX: return go(f"/openings/{a.opening_id}?n=" + ("short" if len(message) < V.NOTE_MIN else "long"))
    if user and a.user_id == user.id and a.status == "pending": a.message = message; s.add(a); s.commit()
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
        from .notify import notify
        notify(s, [a.user_id], "lab_decision", f"{'You were accepted for' if decision == 'accepted' else 'Your application was not accepted for'} {o.title}", f"/openings/{o.id}", None, user.id)
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
