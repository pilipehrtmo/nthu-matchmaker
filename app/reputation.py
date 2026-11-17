"""Track record: completed projects, confirmed contributions and teammate endorsements. No star ratings.

How a contribution becomes part of someone's record:
  1. The project lead marks the project completed. Everyone who was accepted on it gets a row (Contribution);
     the lead writes their role and a short note, and may say a member did not take part. Members the lead
     removed earlier are listed too, as "not included", so they can say they did contribute.
  2. Each person confirms their row or disputes it (with a reason). Only rows confirmed by both sides count.
     The lead's own row counts once at least one teammate has confirmed theirs.
  3. Disputes go to the admins, who decide; admins can also mark a completion "Admin-verified" after checking
     its evidence, or reopen a project that was not really finished (this removes its rows and endorsements).
Endorsements: after a completed project, confirmed teammates may vouch for up to 3 strengths of each other,
from a fixed positive list or the skills of the other person's seat. No text, nothing negative, never yourself.
"""
from collections import Counter
from datetime import datetime
from fastapi import Request, Depends, Form, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select, delete
from .db import get_session
from .models import User, Project, Role, Application, Contribution, Endorsement
from .main import app, render, me, go, limited, tags, kind_of, templates

NOTE_MAX, REASON_MIN, REASON_MAX, MAX_ENDORSE = 200, 10, 300, 3
QUALITIES = [   # (id, English, Chinese): positive only
    ("reliable", "Reliable communication", "溝通可靠"), ("consistent", "Consistent contribution", "穩定投入"),
    ("technical", "Strong technical work", "技術實力強"), ("research", "Good research and analysis", "研究分析能力佳"),
    ("coord", "Effective coordination", "協調能力佳"), ("design", "Thoughtful design", "設計用心"),
    ("present", "Clear presentation", "表達清楚"), ("helpful", "Helpful teammate", "樂於協助隊友")]
QMAP = {q: (en, zh) for q, en, zh in QUALITIES}


def tag_label(tag, lang="en"):
    kind, _, v = tag.partition(":")
    if kind == "q" and v in QMAP: return QMAP[v][1 if lang == "zh" else 0]
    return v   # a skill: shown as written
templates.env.globals["endorse_label"] = tag_label


def counts(c, others_ok=True):
    """Does this row count on the person's record?"""
    if c.lead_status != "confirmed" or c.member_status != "confirmed": return False
    return others_ok if c.is_lead else True


def _rows(s, pid): return s.exec(select(Contribution).where(Contribution.project_id == pid).order_by(Contribution.is_lead.desc(), Contribution.id)).all()


def _lead_ok(rows): return any(not c.is_lead and counts(c) for c in rows)


def team_for_completion(s, pr):
    """People the completion form lists: accepted members and advisors, then members the lead removed earlier."""
    out = []
    for a, r in s.exec(select(Application, Role).join(Role, Role.id == Application.role_id)
                       .where(Role.project_id == pr.id, Application.status.in_(["accepted", "removed"])).order_by(Application.at)).all():
        if a.user_id == pr.owner_id or any(x["user"].id == a.user_id for x in out): continue
        u = s.get(User, a.user_id)
        if u: out.append(dict(app=a, role=r, user=u, removed=a.status == "removed"))
    return out


def panel(s, pr, user):
    """Everything the project page needs for the completion and endorsement box."""
    rows = _rows(s, pr.id) if pr.status == "completed" else []
    people = {u.id: u for u in s.exec(select(User).where(User.id.in_([c.user_id for c in rows] or [-1])))}
    lead_ok = _lead_ok(rows)
    mine = next((c for c in rows if user and c.user_id == user.id), None)
    team = team_for_completion(s, pr) if pr.status != "completed" else []
    is_owner = bool(user and user.id == pr.owner_id)
    out = dict(rows=[dict(c=c, user=people.get(c.user_id), counted=counts(c, lead_ok)) for c in rows], mine=mine, lead_ok=lead_ok,
               can_complete=is_owner and pr.status in ("open", "closed") and any(not x["removed"] for x in team), team=team,
               can_cancel=is_owner and pr.status == "completed" and not any(c.member_status == "confirmed" and not c.is_lead for c in rows)
                          and not any(c.admin_status for c in rows),
               endorse=[], given=set(), qualities=QUALITIES)
    if mine and counts(mine, True) and not (mine.is_lead and not lead_ok):
        given = set(s.exec(select(Endorsement.to_id, Endorsement.tag).where(Endorsement.project_id == pr.id, Endorsement.from_id == user.id)).all())
        out["given"] = given
        for c in rows:
            if c.user_id != user.id and counts(c, lead_ok) and c.user_id in people:
                done = [t for to, t in given if to == c.user_id]
                out["endorse"].append(dict(user=people[c.user_id], c=c, skills=sorted(tags(c.skills))[:6], done=done, left=MAX_ENDORSE - len(done)))
    return out
templates.env.globals["completion_panel"] = panel


def record(s, p):
    """A person's public track record: only what platform records show."""
    mine = s.exec(select(Contribution).where(Contribution.user_id == p.id)).all()
    pids = {c.project_id for c in mine}
    projects = {x.id: x for x in s.exec(select(Project).where(Project.id.in_(pids or {-1})))}
    rows_by = {pid: _rows(s, pid) for pid in pids}
    done = []
    for c in mine:
        pr = projects.get(c.project_id)
        if not pr or pr.status != "completed": continue
        rows = rows_by[c.project_id]; lead_ok = _lead_ok(rows)
        if not counts(c, lead_ok): continue
        mates = [x.user_id for x in rows if x.user_id != p.id and counts(x, lead_ok)]
        done.append(dict(c=c, pr=pr, verified=c.admin_status == "verified", mates=s.exec(select(User).where(User.id.in_(mates or [-1]))).all()))
    done.sort(key=lambda x: x["pr"].completed_at or x["pr"].created, reverse=True)
    joined = set(s.exec(select(Role.project_id).join(Application, Application.role_id == Role.id)
                        .where(Application.user_id == p.id, Application.status == "accepted")).all())
    joined |= {x["pr"].id for x in done if not x["c"].is_lead}
    led = set(s.exec(select(Project.id).join(Role, Role.project_id == Project.id).join(Application, Application.role_id == Role.id)
                     .where(Project.owner_id == p.id, Application.status == "accepted")).all())
    led |= {x["pr"].id for x in done if x["c"].is_lead}
    en = Counter(s.exec(select(Endorsement.tag).where(Endorsement.to_id == p.id)).all()) if done else Counter()
    roles = sorted({x["c"].role_name for x in done if not x["c"].is_lead})
    return dict(done=done, joined=len(joined), led=len(led), completed=len(done), endorsements=en.most_common(8), roles=roles)


def _member_counts(s, pr): return {a.user_id for a in s.exec(select(Application).join(Role, Role.id == Application.role_id)
                                                              .where(Role.project_id == pr.id, Application.status == "accepted")).all()}


@app.post("/projects/{pid}/complete", dependencies=[limited("complete", 20, 3600)])
async def complete_project(req: Request, pid: int, user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if not pr: raise HTTPException(404)
    if not user or user.id != pr.owner_id: raise HTTPException(403)
    if pr.status not in ("open", "closed"): return go(f"/projects/{pid}?n=already#complete")
    team = team_for_completion(s, pr)
    if not any(not x["removed"] for x in team): return go(f"/projects/{pid}?n=noteam#complete")
    form = await req.form(); now = datetime.utcnow()
    rows = [Contribution(project_id=pid, user_id=user.id, role_name="Project lead", is_lead=True, member_status="confirmed",
                         note=" ".join(str(form.get("lead_note", "")).split())[:NOTE_MAX], joined_at=pr.created)]
    for x in team:
        aid = x["app"].id
        took_part = not x["removed"] and form.get(f"in_{aid}") == "1"
        rows.append(Contribution(project_id=pid, user_id=x["user"].id, role_name=x["role"].name[:80], skills=x["role"].skills[:300],
                                 note=" ".join(str(form.get(f"note_{aid}", "")).split())[:NOTE_MAX],
                                 lead_status="confirmed" if took_part else "not_included", member_status="pending", joined_at=x["app"].at))
    pr.status, pr.completed_at = "completed", now
    for c in rows: s.add(c)
    s.add(pr)
    try: s.commit()
    except IntegrityError:   # pressed twice: the first one won
        s.rollback(); return go(f"/projects/{pid}?n=already#complete")
    from .notify import notify
    notify(s, [c.user_id for c in rows if not c.is_lead], "completion", f"{pr.title} was marked completed. Please confirm your part.", f"/projects/{pid}#complete", pid, user.id)
    return go(f"/projects/{pid}?n=completed#complete")


@app.post("/projects/{pid}/complete/cancel")
def cancel_completion(pid: int, user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if not pr: raise HTTPException(404)
    if not user or user.id != pr.owner_id: raise HTTPException(403)
    if not panel(s, pr, user)["can_cancel"]: return go(f"/projects/{pid}?n=locked#complete")
    s.exec(delete(Endorsement).where(Endorsement.project_id == pid)); s.exec(delete(Contribution).where(Contribution.project_id == pid))
    pr.status, pr.completed_at = "closed", None; s.add(pr); s.commit()
    return go(f"/projects/{pid}?n=reopened#complete")


@app.post("/contributions/{cid}/{answer}", dependencies=[limited("contrib", 30, 3600)])
def answer_contribution(cid: int, answer: str, reason: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    c = s.get(Contribution, cid)
    if not c: raise HTTPException(404)
    if not user or user.id != c.user_id or c.is_lead: raise HTTPException(403)   # only the person themself answers
    pid = c.project_id
    if answer not in ("confirm", "dispute") or c.member_status != "pending" or c.admin_status: return go(f"/projects/{pid}#complete")
    if answer == "confirm":
        if c.lead_status != "confirmed": return go(f"/projects/{pid}#complete")   # "not included": only a dispute makes sense
        c.member_status = "confirmed"
    else:
        reason = " ".join(reason.split())
        if not REASON_MIN <= len(reason) <= REASON_MAX: return go(f"/projects/{pid}?n=reason#complete")
        c.member_status, c.member_note = "disputed", reason
    s.add(c); s.commit()
    if answer == "dispute":
        pr = s.get(Project, pid)
        from .notify import notify
        notify(s, [pr.owner_id], "completion", f"{user.name or user.handle} disagrees with the completion record of {pr.title}. An admin will review it.", f"/projects/{pid}#complete", pid, user.id)
    return go(f"/projects/{pid}?n={'confirmed' if answer == 'confirm' else 'disputed'}#complete")


@app.post("/projects/{pid}/endorse", dependencies=[limited("endorse", 60, 3600)])
async def endorse(req: Request, pid: int, user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if not pr: raise HTTPException(404)
    if not user: return go("/login")
    form = await req.form()
    try: to = int(form.get("to", 0))
    except ValueError: to = 0
    p = panel(s, pr, user)
    target = next((e for e in p["endorse"] if e["user"].id == to), None)
    if not target or to == user.id: raise HTTPException(403)   # only confirmed teammates on this completed project
    allowed = {f"q:{q}" for q, *_ in QUALITIES} | {f"s:{k}" for k in target["skills"]}
    picked = [t for t in dict.fromkeys(form.getlist("tag")) if t in allowed and t not in target["done"]]
    picked = picked[:target["left"]]
    for t in picked:
        s.add(Endorsement(project_id=pid, from_id=user.id, to_id=to, tag=t))
        try: s.commit()
        except IntegrityError: s.rollback()   # the same endorsement twice: kept once
    return go(f"/projects/{pid}?n={'endorsed' if picked else 'noendorse'}#complete")


def admin_queue(s):
    """Disputes waiting for a decision, and completed projects not yet verified."""
    disputes = []
    for c in s.exec(select(Contribution).where(Contribution.member_status == "disputed", Contribution.admin_status == "").order_by(Contribution.id)).all():
        disputes.append(dict(c=c, user=s.get(User, c.user_id), pr=s.get(Project, c.project_id)))
    done = []
    for pr in s.exec(select(Project).where(Project.status == "completed").order_by(Project.completed_at.desc())).all():
        rows = _rows(s, pr.id)
        if any(c.admin_status == "verified" for c in rows) or not _lead_ok(rows): continue
        done.append(dict(pr=pr, rows=[(c, s.get(User, c.user_id)) for c in rows if counts(c, True)], owner=s.get(User, pr.owner_id)))
    return dict(disputes=disputes, completed=done)
templates.env.globals["contribution_queue"] = admin_queue


@app.post("/admin/contribution/{cid}/{decision}")
def admin_decide(cid: int, decision: str, user=Depends(me), s: Session = Depends(get_session)):
    if not (user and user.is_admin): raise HTTPException(403)
    c = s.get(Contribution, cid)
    if not c: raise HTTPException(404)
    if decision == "count":        # the person did take part as recorded (or as they say)
        c.lead_status, c.member_status = "confirmed", "confirmed"
    elif decision == "dont_count":  # leave it off their record
        c.lead_status = "not_included"
    else: raise HTTPException(400)
    c.admin_status, c.decided_by, c.decided_at = "resolved", user.id, datetime.utcnow()
    s.add(c); s.commit(); print(f">>> CONTRIBUTION by admin {user.id}: row {cid} {decision}")
    return go("/admin#track")


@app.post("/admin/completion/{pid}/{decision}")
def admin_completion(pid: int, decision: str, user=Depends(me), s: Session = Depends(get_session)):
    if not (user and user.is_admin): raise HTTPException(403)
    pr = s.get(Project, pid)
    if not pr or pr.status != "completed": raise HTTPException(404)
    if decision == "verify":       # an admin checked the evidence (links, demo, results)
        for c in _rows(s, pid):
            if counts(c, True): c.admin_status, c.decided_by, c.decided_at = "verified", user.id, datetime.utcnow(); s.add(c)
    elif decision == "reopen":     # it was not really finished: nothing from it stays on anyone's record
        s.exec(delete(Endorsement).where(Endorsement.project_id == pid)); s.exec(delete(Contribution).where(Contribution.project_id == pid))
        pr.status, pr.completed_at = "closed", None; s.add(pr)
    else: raise HTTPException(400)
    s.commit(); print(f">>> COMPLETION by admin {user.id}: project {pid} {decision}")
    return go("/admin#track")
