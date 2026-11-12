"""Notifications: the bell in the top bar, the /notifications page, and email (off / daily digest / instant).

A notification links to a page on this site, never to a file, so it cannot leak a document.
People are never notified about their own action. The same event for the same person within
10 minutes is merged into one (the text is replaced and it moves back to the top).
"""
import threading
from datetime import datetime, timedelta
from fastapi import Request, Depends, Form, HTTPException
from sqlmodel import Session, select
from .db import get_session, engine
from .models import User, Notification, ReviewRequest, Remark, ResearchDoc, DocVersion, Project
from .main import app, render, me, go, limited, templates
from .mail import send_mail, email_enabled
from .config import BASE_URL

EMAIL_PREFS = ["off", "daily", "important", "instant"]
IMPORTANT = {"review_request", "remark_submitted", "remark_reopened", "removed", "app_decision", "deadline", "faculty_status"}   # "important": these right away, the rest in the daily summary
MERGE = timedelta(minutes=10)


def notify(s, user_ids, kind, text, link, project_id=None, actor=None, instant_ok=True):
    """Write one notification per person (not the actor). Instant emails go out in the background."""
    now = datetime.utcnow(); sent = []
    for uid in {u for u in user_ids if u and u != actor}:
        n = s.exec(select(Notification).where(Notification.user_id == uid, Notification.kind == kind, Notification.link == link,
                                              Notification.read_at == None, Notification.created > now - MERGE)).first()
        if n: n.text, n.created, n.emailed_at = text[:300], now, None
        else: n = Notification(user_id=uid, kind=kind, text=text[:300], link=link[:300], project_id=project_id)
        s.add(n); sent.append(uid)
    s.commit()
    if instant_ok and sent:
        prefs = ["instant", "important"] if kind in IMPORTANT else ["instant"]
        for u in s.exec(select(User).where(User.id.in_(sent), User.email_pref.in_(prefs), User.banned == False)).all():
            _mail_later(u.email, "NTHU Matchmaker: " + text[:80], f"{text}\n\nOpen it: {BASE_URL}{link}\n\nYou get these emails because of your notification email setting on your profile.")
            for n in s.exec(select(Notification).where(Notification.user_id == u.id, Notification.link == link, Notification.emailed_at == None)).all():
                n.emailed_at = now; s.add(n)
        s.commit()

def _mail_later(to, subject, body):
    def run():
        try: send_mail(to, subject, body)
        except Exception as e: print(">>> notification email failed:", type(e).__name__, flush=True)
    threading.Thread(target=run, daemon=True).start()

def unread(s, uid):
    return len(s.exec(select(Notification.id).where(Notification.user_id == uid, Notification.read_at == None)).all())


@app.get("/notifications")
def notifications_page(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    rows = s.exec(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created.desc()).limit(100)).all()
    return render(req, "notifications.html", user, rows=rows, prefs=EMAIL_PREFS, emails_on=email_enabled())

@app.get("/notifications/{nid}/go")
def notification_go(nid: int, user=Depends(me), s: Session = Depends(get_session)):
    n = s.get(Notification, nid)
    if not user or not n or n.user_id != user.id: raise HTTPException(404)
    if not n.read_at: n.read_at = datetime.utcnow(); s.add(n); s.commit()
    link = n.link if n.link.startswith("/") and not n.link.startswith("//") and "\\" not in n.link else "/"
    return go(link)

@app.post("/notifications/read")
def notifications_read(user=Depends(me), s: Session = Depends(get_session)):
    if user:
        for n in s.exec(select(Notification).where(Notification.user_id == user.id, Notification.read_at == None)).all():
            n.read_at = datetime.utcnow(); s.add(n)
        s.commit()
    return go("/notifications")

@app.post("/profile/notifications", dependencies=[limited("emailpref", 30, 3600)])
def email_pref(pref: str = Form("off"), next: str = Form("/notifications"), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    user.email_pref = pref if pref in EMAIL_PREFS else "off"; s.add(user); s.commit()
    return go((next if next in ("/notifications", "/profile") else "/notifications") + "?n=saved")


# ---------- scheduled jobs (registered in main's scheduler) ----------
def send_digests():
    """Once a day: one email per person with 'daily' set, listing unread notifications not emailed yet."""
    if not email_enabled(): return
    with Session(engine) as s:
        for u in s.exec(select(User).where(User.email_pref.in_(["daily", "important"]), User.banned == False)).all():
            ns = s.exec(select(Notification).where(Notification.user_id == u.id, Notification.read_at == None, Notification.emailed_at == None)
                        .order_by(Notification.created.desc()).limit(30)).all()
            if not ns: continue
            lines = "\n".join(f"- {n.text}\n  {BASE_URL}{n.link}" for n in ns)
            _mail_later(u.email, f"NTHU Matchmaker: {len(ns)} update{'s' if len(ns) != 1 else ''} for you",
                        f"Hi {u.name},\n\nHere is what happened since your last digest:\n\n{lines}\n\nChange how often you get these on {BASE_URL}/notifications")
            for n in ns: n.emailed_at = datetime.utcnow(); s.add(n)
            s.commit()

def send_reminders():
    """Once a day: anything waiting on someone for more than 7 days gets one reminder (not more than once a week)."""
    from .advisor import people
    week = datetime.utcnow() - timedelta(days=7)
    with Session(engine) as s:
        def remind(uids, text, link, pid):
            for uid in uids:
                if s.exec(select(Notification).where(Notification.user_id == uid, Notification.kind == "reminder", Notification.link == link,
                                                     Notification.created > week)).first(): continue
                notify(s, [uid], "reminder", text, link, pid)
        for rq in s.exec(select(ReviewRequest).where(ReviewRequest.status == "waiting", ReviewRequest.created < week)).all():
            d = s.get(ResearchDoc, rq.doc_id); v = s.get(DocVersion, rq.version_id); pr = s.get(Project, d.project_id) if d else None
            if pr and v: remind(people(s, pr)["advisors"], f"Still waiting: review of {d.title} v{v.number}", f"/docs/{d.id}?v={v.id}", pr.id)
        for t in s.exec(select(Remark).where(Remark.parent_id == None, Remark.deleted_at == None, Remark.kind == "feedback",
                                             Remark.state.in_(["submitted", "reopened"]), Remark.last_at < week)).all():
            pr = s.get(Project, t.project_id)
            if not pr: continue
            ppl = people(s, pr)
            if t.state == "submitted": remind(ppl["advisors"], "Still waiting: a remark marked as fixed needs your check", f"/projects/{pr.id}#t{t.id}", pr.id)
            else: remind(ppl["team"], "Still open: reopened feedback is waiting for your team", f"/projects/{pr.id}#t{t.id}", pr.id)
