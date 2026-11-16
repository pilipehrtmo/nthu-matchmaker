"""Professor verification.

A professor signs up like anyone else and starts as "pending". Three kinds of evidence, all shown to an admin:
  A. email ownership: a 6-digit code sent to the institutional address (or the normal confirmation link);
  B. the official NTHU page they give us: we open it ourselves and look for their email, name, title and department;
  C. an admin's decision (approve, reject, ask for more information, suspend), always with the admin's name and time.

Owning an NTHU address alone never verifies anyone. The account is verified automatically only when all of these hold:
the email is confirmed, it is a staff address (not @gapp/@oz/@m…, which students also have), and our own fetch of
an nthu.edu.tw page (not a personal ~user page) shows both that email and their name. Everything else waits for an admin.
Only admins and that automatic check change the status; every change is written to FacultyAudit.
"""
import hmac, re, secrets
from collections import Counter
from datetime import datetime, timedelta
from fastapi import Request, Depends, Form, HTTPException
from sqlmodel import Session, select
from .db import get_session
from .models import User, FacultyAudit, AuthToken
from .faculty import fetch_page, email_on_page, name_on_page, title_on_page, dept_on_page, nthu_url, nthu_email, staff_email, shared_domain, academic_email
from .security import token_hash
from .main import app, render, me, go, limited, templates, TITLES, wait_left, note, wait_text, send_mail, email_enabled, PUBLIC, BREVO_API_KEY

STATUS = {"pending": "Pending verification", "verified": "Verified", "rejected": "Rejected", "more_info": "More information required", "suspended": "Suspended"}

OTHER = "Other academic appointment"
NEEDS_REASON = {"reject", "more_info", "suspend"}
ACTIONS = {"approve": ("verified", "approved"), "reject": ("rejected", "rejected"), "more_info": ("more_info", "more_info"),
           "suspend": ("suspended", "suspended"), "reinstate": ("verified", "reinstated")}
HIST = {"applied": "Signed up", "resubmitted": "Information sent", "email_verified": "Email confirmed", "auto_check": "Automatic page check", "approved": "Approved",
        "rejected": "Rejected", "more_info": "More information requested", "suspended": "Suspended", "reinstated": "Reinstated"}
MATCH = [("email", "Email on page"), ("name", "Name on page"), ("title", "Title on page"), ("dept", "Department on page")]
templates.env.globals.update(PROF_STATUS=STATUS, PROF_TITLES=TITLES, PROF_OTHER=OTHER, PROF_HIST=HIST, PROF_MATCH=MATCH)

def status_of(u):
    return u.faculty_status if u.faculty_status in STATUS else "pending"

def audit(s, u, action, actor=None, frm="", to="", reason=""):
    s.add(FacultyAudit(user_id=u.id, actor_id=actor, action=action, status_from=frm, status_to=to or frm, reason=reason[:500]))

def set_status(s, u, to, action, actor=None, reason=""):
    """The one place a professor's status changes. actor None = the automatic check."""
    frm = u.faculty_status
    u.faculty_status, u.is_faculty = to, to == "verified"
    if to == "verified": u.role = "faculty"
    if to in ("rejected", "more_info", "suspended"): u.faculty_reason = reason[:500]
    elif to == "verified": u.faculty_reason = ""
    if actor is not None and action not in ("applied", "resubmitted"): u.faculty_reviewed_by, u.faculty_reviewed_at = actor, datetime.utcnow()
    elif actor is None and to == "verified": u.faculty_reviewed_by, u.faculty_reviewed_at = None, datetime.utcnow()
    audit(s, u, action, actor, frm, to, reason); s.add(u)

def clean_title(title, other=""):
    if title in TITLES: return title
    if title == OTHER: return re.sub(r"\s+", " ", other).strip()[:60]
    return ""

def auto_ok(u, found):
    """Strong enough to verify without a person: see the module docstring."""
    return (u.email_verified and staff_email(u.email) and not shared_domain(u.email) and "email" in found and "name" in found
            and "~" not in (u.faculty_url or ""))

def run_check(s, u):
    """Open their official page and record what is on it. May verify a pending account (never touches other statuses)."""
    found = []
    if not u.faculty_url: note_ = "No official NTHU page given yet."
    else:
        text, final, err = fetch_page(u.faculty_url)
        if err: note_ = err
        else:
            found = [k for k, ok in (("email", email_on_page(u.email, text)), ("name", name_on_page(u.name, text)),
                                     ("title", bool(u.title) and title_on_page(u.title, text)), ("dept", bool(u.faculty) and dept_on_page(u.faculty, text))) if ok]
            note_ = ("Found on the page: " + ", ".join({"email": "your email", "name": "your name", "title": "your title", "dept": "your department"}[k] for k in found) + "."
                     if found else "Your email and name were not found on that page.")
    u.faculty_note, u.faculty_match = note_[:300], ",".join(found)
    st = status_of(u)
    if st == "pending" and auto_ok(u, found):
        set_status(s, u, "verified", "auto_check", None, "Email confirmed, and our check of the official NTHU page found this email and name.")
    else:
        audit(s, u, "auto_check", None, u.faculty_status, u.faculty_status, note_)
    s.add(u); s.commit()

def on_email_verified(s, u, how):
    if u.role == "faculty" and status_of(u) in ("pending", "more_info"):
        audit(s, u, "email_verified", u.id, u.faculty_status, u.faculty_status, how); s.commit()
        run_check(s, u)

def new_application(s, u):
    u.faculty_status, u.faculty_applied_at = "pending", datetime.utcnow()
    audit(s, u, "applied", u.id, "", "pending"); s.add(u); s.commit()
    run_check(s, u)


# ---------- the professor's own page ----------
def history(s, uid):
    return s.exec(select(FacultyAudit).where(FacultyAudit.user_id == uid).order_by(FacultyAudit.created.desc(), FacultyAudit.id.desc())).all()

def can_mail():
    return bool(BREVO_API_KEY) or email_enabled() or not PUBLIC

@app.get("/verification")
def verification_page(req: Request, n: str = "", user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if user.role != "faculty": return go("/profile")
    return render(req, "verification.html", user, st=status_of(user), hist=history(s, user.id), n=n, err=req.session.pop("verr", ""),
                  can_mail=can_mail(), titles=TITLES, staff=staff_email(user.email), nthu=nthu_email(user.email), shared=shared_domain(user.email))

def _back(req, err="", n=""):
    if err: req.session["verr"] = err
    return go("/verification" + (f"?n={n}" if n else "") + "#steps")

@app.post("/verification", dependencies=[limited("facsubmit", 8, 3600)])
def verification_submit(req: Request, page: str = Form(""), title: str = Form(""), title_other: str = Form(""), dept: str = Form(""),
                        evidence: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    """Send or update their information. Only while pending or when an admin asked for more; never changes the status upward."""
    if not user: return go("/login")
    if user.role != "faculty": return go("/profile")
    st = status_of(user)
    if st not in ("pending", "more_info"): return _back(req, "Your information can't be changed at this stage. Contact the admins if something is wrong.")
    page = page.strip()[:300]; dept = re.sub(r"\s+", " ", dept).strip()[:60]; t = clean_title(title, title_other)
    if page and not nthu_url(page): return _back(req, "The link must be an official page on nthu.edu.tw, such as your department's faculty list.")
    if not t: return _back(req, "Choose your academic title, or write it in the box under Other.")
    if len(dept) < 2: return _back(req, "Enter your department.")
    user.faculty_url, user.title = page, t
    from .departments import relink_text
    relink_text(user, dept)   # the typed text is stored as it is; an exact official name is linked, anything else goes to the admin's department queue
    user.faculty_evidence = evidence.replace("\r", "").strip()[:1000]
    if st == "more_info": set_status(s, user, "pending", "resubmitted", user.id, "Sent the information again.")
    else: audit(s, user, "resubmitted", user.id, "pending", "pending", "Updated the information.")
    s.add(user); s.commit()
    run_check(s, user)
    return _back(req, n="sent")

@app.post("/verification/code/send", dependencies=[limited("faccodesend", 5, 3600)])
def code_send(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if user.role != "faculty" or user.email_verified: return _back(req)
    w = wait_left(f"faccode:{user.id}", 3, 3600)
    if w: return _back(req, f"We already sent 3 codes this hour. Please wait {wait_text(w)}, and check your spam folder.")
    note(f"faccode:{user.id}")
    for x in s.exec(select(AuthToken).where(AuthToken.user_id == user.id, AuthToken.kind == "faccode", AuthToken.used == False)).all(): x.used = True
    code = f"{secrets.randbelow(10**6):06d}"
    tok = AuthToken(user_id=user.id, kind="faccode", token_hash=secrets.token_hex(24), expires=datetime.utcnow() + timedelta(minutes=15))
    s.add(tok); s.flush()
    tok.token_hash = token_hash(f"faccode:{tok.id}:{code}"); s.commit()   # the id keeps the hash unique; the code itself is never stored
    try: send_mail(user.email, "Your NTHU Matchmaker verification code",
                   f"Hi {user.name or ''},\n\nYour verification code is {code}\n\nIt works for 15 minutes. If you did not ask for it, ignore this email.")
    except Exception as e:
        print(">>> CODE EMAIL FAILED", user.email, type(e).__name__, e)
        return _back(req, "We could not send the email just now. Try again in a minute; an admin can also verify you without it.")
    return _back(req, n="code")

@app.post("/verification/code/check", dependencies=[limited("faccodecheck", 20, 3600)])
def code_check(req: Request, code: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if user.role != "faculty" or user.email_verified: return _back(req)
    w = wait_left(f"faccodebad:{user.id}", 5, 900)
    if w: return _back(req, f"Too many wrong codes. Please wait {wait_text(w)} and ask for a new one.")
    code = re.sub(r"\D", "", code)[:6]
    tok = s.exec(select(AuthToken).where(AuthToken.user_id == user.id, AuthToken.kind == "faccode", AuthToken.used == False)).first()
    if not tok or tok.expires < datetime.utcnow() or not hmac.compare_digest(tok.token_hash, token_hash(f"faccode:{tok.id}:{code}")):
        note(f"faccodebad:{user.id}")
        return _back(req, "That code is wrong or has expired. Check the latest email, or ask for a new code.")
    tok.used = True; user.email_verified = True; s.add(user); s.commit()
    on_email_verified(s, user, "Code sent to the email was entered.")
    return _back(req, n="email")


# ---------- admin queue ----------
def queue(s, show="open"):
    want = ["pending", "more_info"] if show == "open" else list(STATUS)
    us = s.exec(select(User).where(User.role == "faculty")).all()
    us = [u for u in us if status_of(u) in want]
    allp = s.exec(select(User).where(User.role == "faculty")).all()
    names = Counter(" ".join(sorted(u.name.lower().split())) for u in allp)
    pages = Counter(u.faculty_url.rstrip("/") for u in allp if u.faculty_url)
    rows = []
    for u in sorted(us, key=lambda u: (status_of(u) != "pending", u.faculty_applied_at or u.created)):
        flags = []
        if not u.email_verified: flags.append("Email not confirmed")
        if shared_domain(u.email): flags.append("Shared NTHU address (students have these too)")
        elif not nthu_email(u.email): flags.append("Not an NTHU email" + (" (another university or institute)" if academic_email(u.email) else ""))
        if names[" ".join(sorted(u.name.lower().split()))] > 1: flags.append("Another professor account has the same name")
        if u.faculty_url and pages[u.faculty_url.rstrip("/")] > 1 and "~" not in u.faculty_url: flags.append("Same page as another account (normal for a department list)")
        if "~" in (u.faculty_url or ""): flags.append("Personal ~user page, not an official listing")
        rows.append(dict(u=u, st=status_of(u), flags=flags, found=set(filter(None, (u.faculty_match or "").split(","))), hist=history(s, u.id)[:8]))
    return rows

@app.post("/admin/prof/{uid}/{action}")
def admin_prof(req: Request, uid: int, action: str, reason: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not (user and user.is_admin): raise HTTPException(404)
    u = s.get(User, uid)
    if not u or (u.role != "faculty" and action != "approve") or action not in (*ACTIONS, "recheck"): raise HTTPException(404)
    if u.id == user.id: return go("/admin?perr=self#faculty")   # nobody decides on their own application
    reason = reason.replace("\r", "").strip()[:500]
    back = f"/admin#prof{uid}"
    if action == "recheck": run_check(s, u); return go(back)
    if action in NEEDS_REASON and len(reason) < 5: return go(f"/admin?perr=reason&pu={uid}#prof{uid}")
    st = status_of(u)
    allowed = {"approve": {"pending", "more_info", "rejected"}, "reject": {"pending", "more_info"}, "more_info": {"pending"},
               "suspend": {"verified"}, "reinstate": {"suspended"}}[action]
    if u.role == "faculty" and st not in allowed: return go(back)
    to, act = ACTIONS[action]
    if u.role != "faculty": u.role, u.faculty_applied_at = "faculty", datetime.utcnow()   # an admin can mark a student account as a professor
    set_status(s, u, to, act, user.id, reason); s.commit()
    from .notify import notify
    msg = {"verified": "Your professor account is verified. Supervision and research positions are now open to you.",
           "rejected": "Your professor verification was not approved. See the reason on your verification page.",
           "more_info": "An admin needs more information to verify your professor account.",
           "suspended": "Your professor verification was suspended. See the reason on your verification page."}[to]
    notify(s, [u.id], "faculty_status", msg, "/verification", None, user.id)
    return go(back)
