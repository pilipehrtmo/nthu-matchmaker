import asyncio, re, secrets, time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlmodel import Session, select, delete
from starlette.middleware.sessions import SessionMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from .config import *
from .db import init_db, get_session, engine
from .models import *
from .mail import send_magic
from .scraper import run_scrapers
from .seed import seed, seed_starter, seed_examples
from .matching import match_pct, why, warm
from .cv import parse_cv, CVError, MAX_BYTES
from .links import CONTACTS, PRO_LINKS, LinkError, clean_contact, clean_handle, clean_link, short

signer = URLSafeTimedSerializer(SECRET, salt="magic")
def ago(d):
    s = int((datetime.utcnow() - d).total_seconds())
    for n, u in ((86400, "d"), (3600, "h"), (60, "m")):
        if s >= n: return f"{s // n}{u} ago"
    return "just now"
templates = Jinja2Templates(directory="app/templates"); templates.env.filters["ago"] = ago

def purge_logs():
    with Session(engine) as s:
        s.exec(delete(SignupLog).where(SignupLog.at < datetime.utcnow() - timedelta(days=LOG_RETENTION_DAYS))); s.commit()

@asynccontextmanager
async def lifespan(app):
    from urllib.parse import urlparse
    print(">>> startup: connecting to database at", urlparse(DB_URL.replace("+psycopg2", "")).hostname or "sqlite", flush=True)
    try:
        init_db()
    except Exception as e:
        print(">>> DATABASE CONNECTION FAILED:", type(e).__name__, str(e).splitlines()[0][:300], flush=True); raise
    print(">>> startup: database ready, seeding", flush=True)
    seed(); seed_starter()
    if not DEMO_DATA: seed_examples()
    if DEMO_DATA:
        from .demo_data import seed_demo; seed_demo(); print(">>> DEMO MODE: sample teams loaded into a separate database. Do not share this server with real users.")
    warm(); sch = BackgroundScheduler()
    sch.add_job(run_scrapers); sch.add_job(run_scrapers, "cron", hour=3); sch.add_job(purge_logs, "cron", hour=4); sch.start()
    yield
    sch.shutdown()

# ---------- CSRF + rate limiting ----------
async def csrf_check(request: Request):
    if request.method == "POST":
        form = await request.form()
        if not secrets.compare_digest(str(form.get("csrf", "")), request.session.get("csrf", "x")):
            raise HTTPException(403, "Security check failed. Reload the page and try again.")

HITS = defaultdict(deque)
def hit(key: str, n: int, secs: int):
    q = HITS[key]; now = time.time()
    while q and q[0] < now - secs: q.popleft()
    if len(q) >= n: raise HTTPException(429, "Too many requests. Please wait a few minutes.")
    q.append(now)
def limited(name: str, n: int, secs: int):
    # Logged-in actions are limited per account, not per IP: a whole class on campus Wi-Fi shares one public IP.
    def dep(request: Request):
        uid = request.session.get("uid")
        hit(f"{name}:u{uid}" if uid else f"{name}:{request.client.host if request.client else '-'}", n, secs)
    return Depends(dep)

if SECRET == "dev-secret-change-me": print("WARNING: set SECRET_KEY before real use.")
app = FastAPI(lifespan=lifespan, dependencies=[Depends(csrf_check)])
# At most 10 pages are built at once; the rest wait in line without holding a thread.
# The database pool has 12 connections, so a page never waits for one (no pile-up when a whole class logs in).
SLOTS = asyncio.Semaphore(10)
@app.middleware("http")
async def one_queue(request: Request, call_next):
    if request.url.path.startswith("/static"): return await call_next(request)
    async with SLOTS: return await call_next(request)
app.add_middleware(SessionMiddleware, secret_key=SECRET, max_age=60 * 60 * 24 * 30, https_only=PUBLIC, same_site="lax")
if PUBLIC and SECRET == "dev-secret-change-me": raise SystemExit("Set SECRET_KEY before putting the site online.")
if PUBLIC and not SMTP_HOST: print("WARNING: no SMTP settings, so login emails cannot be sent. Set SMTP_HOST/SMTP_USER/SMTP_PASS/SMTP_FROM.")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def me(req: Request, s: Session = Depends(get_session)):
    uid = req.session.get("uid"); u = s.get(User, uid) if uid else None
    return u if u and not u.banned else None

def tags(text: str): return {t.strip().lower() for t in text.split(",") if t.strip()}
def days_left(d):
    try: return (datetime.strptime(d, "%Y-%m-%d").date() - datetime.utcnow().date()).days
    except (ValueError, TypeError): return None
def render(req, name, user=None, **ctx):
    if "csrf" not in req.session: req.session["csrf"] = secrets.token_hex(16)
    theme = req.cookies.get("theme", "light")
    if theme not in ("light", "dark", "system"): theme = "light"
    return templates.TemplateResponse(req, name, {"user": user, "csrf": req.session["csrf"], "theme": theme, **ctx})
def go(url): return RedirectResponse(url, status_code=303)
def kind_of(pr):   # older projects have no kind saved: infer it from the competition link
    return pr.kind or ("Competition" if pr.competition_id else "Side project")
templates.env.globals["kind_of"] = kind_of
templates.env.globals.update(CONTACTS=CONTACTS, PRO_LINKS=PRO_LINKS)
templates.env.filters["shortlink"] = short

# ---------- auth ----------
SID = re.compile(r"^[A-Za-z0-9]{6,12}$")

@app.get("/login")
def login_page(req: Request, user=Depends(me)): return render(req, "login.html", user)

@app.post("/login", dependencies=[limited("login", 300, 600)])   # per IP; each email is also limited below
def login(req: Request, email: str = Form(...), name: str = Form(""), student_id: str = Form(""), agree: str = Form(""), s: Session = Depends(get_session)):
    email = email.strip().lower(); name = name.strip()[:60]; sid = student_id.strip().upper()
    exists = s.exec(select(User).where(User.email == email)).first()
    if exists and exists.banned and email not in ADMIN_EMAILS: return render(req, "login.html", error="This account is banned.")
    hit(f"mail:{email}", 3, 600)   # max 3 login emails per address per 10 minutes
    if not exists:
        if not agree: return render(req, "login.html", error="Please agree to the privacy notice to create an account.")
        if not name or not SID.match(sid):
            return render(req, "login.html", error="First time here? Enter your full name and student ID (6-12 letters or digits).")
        if s.exec(select(User).where(User.student_id == sid)).first():
            return render(req, "login.html", error="That student ID already has an account.")
    s.add(SignupLog(email=email, ip="-", allowed=True)); s.commit()
    link = f"{BASE_URL}/auth/{signer.dumps({'e': email, 'n': name, 's': sid})}"
    try: send_magic(email, link)
    except Exception as e:   # mail server busy or down: tell the student instead of showing a server error
        print(">>> LOGIN EMAIL FAILED for", email, type(e).__name__, e)
        return render(req, "login.html", error="We could not send the login email just now. Please wait a minute and try again.")
    return render(req, "login.html", sent=True, demo_link=link if SHOW_LINK and not SMTP_HOST else "")

@app.get("/auth/{token}")
def auth(req: Request, token: str, s: Session = Depends(get_session)):
    try: d = signer.loads(token, max_age=900)
    except BadSignature: return render(req, "login.html", error="That link is invalid or expired. Request a new one.")
    email = d["e"]; u = s.exec(select(User).where(User.email == email)).first(); new = u is None
    if new:
        if not d["s"] or s.exec(select(User).where(User.student_id == d["s"])).first():
            return render(req, "login.html", error="That student ID already has an account.")
        u = User(email=email, name=d["n"], student_id=d["s"], handle="student-" + secrets.token_hex(3), is_admin=email in ADMIN_EMAILS)
        s.add(u); s.commit(); s.refresh(u)
    if email in ADMIN_EMAILS and (not u.is_admin or u.banned): u.is_admin = True; u.banned = False; s.commit()   # listed admins are never locked out
    req.session["uid"] = u.id
    return go("/profile" if new else "/")

@app.post("/logout")
def logout(req: Request): req.session.clear(); return go("/")

@app.get("/privacy")
def privacy(req: Request, user=Depends(me)): return render(req, "privacy.html", user)

# ---------- profile ----------
@app.get("/profile")
def profile(req: Request, user=Depends(me)):
    return render(req, "profile.html", user) if user else go("/login")

@app.post("/profile")
async def profile_save(req: Request, handle: str = Form(...), bio: str = Form(""), skills: str = Form(""),
                 contact: str = Form(""), faculty: str = Form(""), hours: int = Form(4), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    form = await req.form()
    taken = s.exec(select(User).where(User.handle == handle, User.id != user.id)).first()
    if taken: return render(req, "profile.html", user, error="That handle is taken.")
    try: links = {f: clean_link(f, str(form.get(f, ""))) for f, *_ in PRO_LINKS}
    except LinkError as e: return render(req, "profile.html", user, error=str(e))
    for f in ("line", "instagram", "discord"): setattr(user, f, clean_handle(str(form.get(f, ""))))
    for f, v in links.items(): setattr(user, f, v)
    user.handle, user.bio, user.contact = handle.strip()[:30], bio[:500], clean_contact(contact, 100)
    user.faculty, user.hours = faculty.strip()[:40], max(1, min(hours, 60))
    user.skills = ",".join(sorted(tags(skills))); s.add(user); s.commit()
    return go("/")

@app.post("/profile/cv", dependencies=[limited("cv", 20, 3600)])
def profile_cv(file: UploadFile = File(...), user=Depends(me), s: Session = Depends(get_session)):
    """Read an uploaded CV and return suggested profile fields. The file is not saved."""
    if not user: return JSONResponse({"error": "Please log in again."}, status_code=401)
    data = file.file.read(MAX_BYTES + 1)
    known = set()
    for sk in s.exec(select(Role.skills)).all(): known |= tags(sk or "")
    try: return parse_cv(file.filename or "", data, known)
    except CVError as e: return JSONResponse({"error": str(e)}, status_code=400)
    finally: del data

@app.post("/profile/delete")
def delete_account(req: Request, confirm: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if user and confirm.strip() == "DELETE":
        email = user.email
        for p in s.exec(select(Post).where(Post.author_id == user.id)).all(): purge_post(s, p.id)
        for c in s.exec(select(Comment).where(Comment.author_id == user.id)).all(): c.body = "[deleted]"
        s.exec(delete(Vote).where(Vote.user_id == user.id))
        for pid in [p.id for p in s.exec(select(Project).where(Project.owner_id == user.id))]:
            for r in s.exec(select(Role).where(Role.project_id == pid)):
                for a in s.exec(select(Application).where(Application.role_id == r.id)): s.delete(a)
                s.delete(r)
            s.delete(s.get(Project, pid))
        for a in s.exec(select(Application).where(Application.user_id == user.id)): s.delete(a)
        s.exec(delete(SignupLog).where(SignupLog.email == email)); s.delete(user); s.commit(); req.session.clear()
    return go("/")

@app.get("/u/{handle}")
def public_profile(req: Request, handle: str, user=Depends(me), s: Session = Depends(get_session)):
    p = s.exec(select(User).where(User.handle == handle)).first()
    return render(req, "public.html", user, p=p, skills=sorted(tags(p.skills)) if p else [])

# ---------- board ----------
@app.get("/")
def board(req: Request, q: str = "", cat: str = "", kind: str = "", user=Depends(me), s: Session = Depends(get_session)):
    rows = []
    projs = s.exec(select(Project).where(Project.status == "open").order_by(Project.created.desc())).all()
    ids = [p.id for p in projs] or [-1]
    roles_of = defaultdict(list)   # 3 queries for the whole page instead of 2 per project
    for r in s.exec(select(Role).where(Role.project_id.in_(ids))): roles_of[r.project_id].append(r)
    owners = {u.id: u for u in s.exec(select(User).where(User.id.in_({p.owner_id for p in projs} or {-1})))}
    for pr in projs:
        allr = roles_of[pr.id]
        roles = [r for r in allr if not r.filled]
        if not roles: continue
        text = (pr.title + pr.description + " ".join(r.name + r.skills for r in roles)).lower()
        if q and q.lower() not in text: continue
        if kind and kind_of(pr) != kind: continue
        owner = owners.get(pr.owner_id)
        # no match score on your own project
        best = max((match_pct(user, r, pr, owner) for r in roles), default=0) if user and user.id != pr.owner_id else None
        rows.append(dict(p=pr, roles=roles, owner=owner, score=best, total=len(allr), days=days_left(pr.deadline)))
    rows.sort(key=lambda r: -(r["score"] or 0))
    allc = s.exec(select(Competition).order_by(Competition.needs_review, Competition.id.desc())).all()
    cats = sorted({c.category for c in allc})
    comps = [c for c in allc if (not cat or c.category == cat) and (not q or q.lower() in (c.title + c.description).lower())][:60]
    return render(req, "board.html", user, rows=rows, comps=comps, q=q, cat=cat, cats=cats, kind=kind, kinds=PROJECT_KINDS)

@app.get("/projects/new")
def new_project(req: Request, comp: str = "", kind: str = "", user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    kind = kind if kind in PROJECT_KINDS else ("Competition" if comp else "")
    return render(req, "new.html", user, sel=comp, kind=kind, kinds=PROJECT_KINDS, comps=s.exec(select(Competition).order_by(Competition.title)).all())

@app.post("/projects/new", dependencies=[limited("newproj", 10, 3600)])
def create_project(title: str = Form(...), description: str = Form(""), competition_id: str = Form(""),
                   hours: int = Form(4), deadline: str = Form(""), roles: str = Form(""), kind: str = Form("Other"),
                   user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    kind = kind if kind in PROJECT_KINDS else "Other"
    comp_id = int(competition_id) if competition_id and kind == "Competition" else None   # only competition projects link a contest
    pr = Project(owner_id=user.id, title=title[:120], description=description[:2000], hours_per_week=hours,
                 deadline=deadline, competition_id=comp_id, kind=kind)
    s.add(pr); s.commit(); s.refresh(pr)
    for line in roles.splitlines():          # one role per line: "UI designer: figma, ux"
        if line.strip():
            name, _, sk = line.partition(":"); s.add(Role(project_id=pr.id, name=name.strip(), skills=sk.strip()))
    s.commit(); return go(f"/projects/{pr.id}")

@app.get("/projects/{pid}")
def project(req: Request, pid: int, user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if not pr: return go("/")
    owner = s.get(User, pr.owner_id); is_owner = bool(user and user.id == owner.id); out = []
    for r in s.exec(select(Role).where(Role.project_id == pid)):
        apps = []
        for a in s.exec(select(Application).where(Application.role_id == r.id)):
            # application notes are private: only the project lead, the applicant and admins see them
            if is_owner or (user and (a.user_id == user.id or user.is_admin)): apps.append((a, s.get(User, a.user_id)))
        pct = match_pct(user, r, pr, owner) if user and not r.filled and not is_owner else None
        out.append(dict(r=r, apps=apps, mine=any(u.id == (user.id if user else 0) for _, u in apps),
                        pct=pct, why=why(user, r, pct) if pct is not None else ""))
    reveal = bool(user and any(a.status == "accepted" and u.id == user.id for r in out for a, u in r["apps"]))
    return render(req, "project.html", user, pr=pr, owner=owner, is_owner=is_owner, roles=out, reveal=reveal, mytags=tags(user.skills) if user else set(), days=days_left(pr.deadline),
                  comp=s.get(Competition, pr.competition_id) if pr.competition_id else None)

@app.post("/projects/{pid}/delete")
def delete_project(pid: int, user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if user and pr and (pr.owner_id == user.id or user.is_admin):
        for r in s.exec(select(Role).where(Role.project_id == pid)).all():
            for a in s.exec(select(Application).where(Application.role_id == r.id)).all(): s.delete(a)
            s.delete(r)
        s.delete(pr); s.commit()
    return go("/")

@app.post("/roles/{rid}/apply", dependencies=[limited("apply", 30, 3600)])
def apply(rid: int, message: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    r = s.get(Role, rid); pr = s.get(Project, r.project_id)
    if r.filled: return go(f"/projects/{pr.id}")
    dup = s.exec(select(Application).where(Application.role_id == rid, Application.user_id == user.id)).first()
    if not dup and pr.owner_id != user.id: s.add(Application(role_id=rid, user_id=user.id, message=message[:500])); s.commit()
    return go(f"/projects/{pr.id}")

@app.post("/applications/{aid}/{decision}")
def decide(aid: int, decision: str, user=Depends(me), s: Session = Depends(get_session)):
    a = s.get(Application, aid); r = s.get(Role, a.role_id); pr = s.get(Project, r.project_id)
    if user and user.id == pr.owner_id and decision in ("accepted", "rejected"):
        a.status = decision
        if decision == "accepted": r.filled = True
        s.commit()
    return go(f"/projects/{pr.id}")

@app.post("/report/{uid}", dependencies=[limited("report", 10, 3600)])
def report(uid: int, reason: str = Form(...), user=Depends(me), s: Session = Depends(get_session)):
    if user: s.add(Report(reporter_id=user.id, target_user_id=uid, reason=reason[:500])); s.commit()
    return go("/")

# ---------- discuss (Reddit-style forum) ----------
TOPICS = ["General", "Find a team", "Business", "Design & Arts", "Law & Policy", "Science & Health", "Social Impact", "Tech & Data"]

def votes_for(s, kind, ids, user):
    tot, mine = defaultdict(int), {}
    if ids:
        for v in s.exec(select(Vote).where(Vote.kind == kind, Vote.target_id.in_(ids))).all():
            tot[v.target_id] += v.value
            if user and v.user_id == user.id: mine[v.target_id] = v.value
    return tot, mine

def purge_post(s, pid):
    for c in s.exec(select(Comment).where(Comment.post_id == pid)).all():
        s.exec(delete(Vote).where(Vote.kind == "comment", Vote.target_id == c.id)); s.delete(c)
    s.exec(delete(Vote).where(Vote.kind == "post", Vote.target_id == pid))
    p = s.get(Post, pid)
    if p: s.delete(p)

@app.get("/discuss")
def discuss(req: Request, topic: str = "", sort: str = "hot", user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    q = select(Post)
    if topic: q = q.where(Post.topic == topic)
    if not user.is_admin: q = q.where(Post.hidden == False)
    posts = s.exec(q).all(); ids = [p.id for p in posts]
    tot, mine = votes_for(s, "post", ids, user); cc = defaultdict(int)
    if ids:
        for c in s.exec(select(Comment).where(Comment.post_id.in_(ids))).all(): cc[c.post_id] += 1
    now = datetime.utcnow()
    hot = lambda p: (tot[p.id] + 1) / (((now - p.created).total_seconds() / 3600 + 2) ** 1.5)
    key = {"new": lambda p: p.created, "top": lambda p: tot[p.id]}.get(sort, hot)
    posts.sort(key=key, reverse=True)
    authors = {u.id: u for u in s.exec(select(User).where(User.id.in_([p.author_id for p in posts] or [0]))).all()}
    return render(req, "discuss.html", user, posts=posts[:100], tot=tot, mine=mine, cc=cc, authors=authors, topic=topic, sort=sort, topics=TOPICS)

@app.get("/discuss/new")
def new_post(req: Request, topic: str = "", user=Depends(me)):
    return render(req, "newpost.html", user, topics=TOPICS, sel=topic) if user else go("/login")

@app.post("/discuss/new", dependencies=[limited("post", 10, 3600)])
def create_post(req: Request, title: str = Form(...), body: str = Form(""), topic: str = Form("General"), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if not title.strip(): return go("/discuss/new")
    if len(re.findall(r"https?://", title + body)) > 2:
        return render(req, "newpost.html", user, topics=TOPICS, sel=topic, error="Posts can contain at most 2 links.")
    p = Post(author_id=user.id, title=title.strip()[:150], body=body.strip()[:3000], topic=topic if topic in TOPICS else "General")
    s.add(p); s.commit(); s.refresh(p); return go(f"/discuss/{p.id}")

@app.get("/discuss/{pid}")
def thread(req: Request, pid: int, user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    p = s.get(Post, pid)
    if not p or (p.hidden and not user.is_admin): return go("/discuss")
    cs = s.exec(select(Comment).where(Comment.post_id == pid)).all()
    ptot, pmine = votes_for(s, "post", [pid], user); ctot, cmine = votes_for(s, "comment", [c.id for c in cs], user)
    kids = defaultdict(list)
    for c in sorted(cs, key=lambda c: (-ctot[c.id], c.created)): kids[c.parent_id].append(c)
    flat = []
    def walk(parent, d):
        for c in kids.get(parent, []): flat.append((c, d)); walk(c.id, d + 1)
    walk(None, 0)
    ids = {p.author_id} | {c.author_id for c in cs}
    authors = {u.id: u for u in s.exec(select(User).where(User.id.in_(list(ids)))).all()}
    return render(req, "thread.html", user, p=p, flat=flat, ptot=ptot, pmine=pmine, ctot=ctot, cmine=cmine, authors=authors, ncom=len(cs))

@app.post("/discuss/{pid}/comment", dependencies=[limited("comment", 30, 3600)])
def add_comment(pid: int, body: str = Form(...), parent_id: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if len(re.findall(r"https?://", body)) > 2: raise HTTPException(400, "Comments can contain at most 2 links.")
    par = s.get(Comment, int(parent_id)) if parent_id.isdigit() else None
    if body.strip() and s.get(Post, pid):
        s.add(Comment(post_id=pid, author_id=user.id, parent_id=par.id if par and par.post_id == pid else None, body=body.strip()[:2000])); s.commit()
    return go(f"/discuss/{pid}")

@app.post("/vote/{kind}/{oid}", dependencies=[limited("vote", 120, 3600)])
def vote(kind: str, oid: int, v: int = Form(...), next: str = Form("/discuss"), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if kind in ("post", "comment") and v in (1, -1):
        ex = s.exec(select(Vote).where(Vote.user_id == user.id, Vote.kind == kind, Vote.target_id == oid)).first()
        if ex and ex.value == v: s.delete(ex)
        elif ex: ex.value = v
        else: s.add(Vote(user_id=user.id, kind=kind, target_id=oid, value=v))
        s.commit()
    return go(next if next.startswith("/discuss") else "/discuss")

@app.post("/flag/{kind}/{oid}", dependencies=[limited("flag", 20, 3600)])
def flag(kind: str, oid: int, reason: str = Form(...), next: str = Form("/discuss"), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    obj = s.get(Post, oid) if kind == "post" else s.get(Comment, oid) if kind == "comment" else None
    if obj and obj.author_id != user.id and reason.strip() and not s.exec(select(Report).where(Report.reporter_id == user.id, Report.kind == kind, Report.target_id == oid)).first():
        s.add(Report(reporter_id=user.id, target_user_id=obj.author_id, kind=kind, target_id=oid, reason=reason.strip()[:300])); s.commit()
        if len(s.exec(select(Report).where(Report.kind == kind, Report.target_id == oid, Report.resolved == False)).all()) >= 3:
            obj.hidden = True; s.commit()    # auto-hide after 3 reports, until an admin reviews it
    return go(next if next.startswith("/discuss") else "/discuss")

@app.post("/delete/{kind}/{oid}")
def delete_item(kind: str, oid: int, user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if kind == "post":
        p = s.get(Post, oid)
        if p and (p.author_id == user.id or user.is_admin): purge_post(s, oid); s.commit()
        return go("/discuss")
    c = s.get(Comment, oid)
    if not c: return go("/discuss")
    if c.author_id == user.id or user.is_admin: c.body = "[deleted]"; s.commit()
    return go(f"/discuss/{c.post_id}")

# ---------- admin ----------
def extra_admin(s):
    reps = s.exec(select(Report).where(Report.resolved == False)).all(); info = {}
    for r in reps:
        if r.kind == "post": p = s.get(Post, r.target_id); info[r.id] = f"{p.title}: {p.body}"[:200] if p else "[gone]"
        elif r.kind == "comment": c = s.get(Comment, r.target_id); info[r.id] = c.body[:200] if c else "[gone]"
        else: info[r.id] = ""
    allu = s.exec(select(User)).all()
    stats = dict(users=len(allu), unverified=sum(1 for u in allu if not u.verified and not u.banned and not u.is_admin), reports=len(reps),
                 review=len(s.exec(select(Competition).where(Competition.needs_review == True)).all()))
    return dict(stats=stats, admin_ids={u.id for u in allu if u.is_admin}, reports=reps, info=info, pages=s.exec(select(SourcePage)).all(),
                slogs=s.exec(select(ScrapeLog).order_by(ScrapeLog.at.desc()).limit(10)).all())

@app.get("/admin")
def admin(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    if not (user and user.is_admin): return go("/")
    return render(req, "admin.html", user, users=s.exec(select(User)).all(),
        logs=s.exec(select(SignupLog).order_by(SignupLog.at.desc()).limit(100)).all(),
        review=s.exec(select(Competition).where(Competition.needs_review == True)).all(), **extra_admin(s))

@app.post("/admin/source")
def add_source(url: str = Form(...), user=Depends(me), s: Session = Depends(get_session)):
    if user and user.is_admin and url.strip().startswith("http") and not s.exec(select(SourcePage).where(SourcePage.url == url.strip())).first():
        s.add(SourcePage(url=url.strip()[:500])); s.commit()
    return go("/admin")

@app.post("/admin/competition")
def add_competition(title: str = Form(...), url: str = Form(...), category: str = Form("Other"), deadline: str = Form(""),
                    description: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not (user and user.is_admin): return go("/")
    if url.startswith("http") and not s.exec(select(Competition).where(Competition.url == url)).first():
        s.add(Competition(title=title[:150], url=url, category=category, deadline=deadline[:60], description=description[:300],
                          source="admin", needs_review=False)); s.commit()
    return go("/admin")

@app.post("/admin/{action}/{oid}")
def admin_act(action: str, oid: int, user=Depends(me), s: Session = Depends(get_session)):
    if not (user and user.is_admin): return go("/")
    if action == "ban":
        u = s.get(User, oid)
        if u and not u.is_admin: u.banned = True      # admins cannot be banned
    elif action == "unban":
        u = s.get(User, oid)
        if u: u.banned = False
    elif action == "verify_all":
        for u in s.exec(select(User).where(User.verified == False, User.banned == False)).all(): u.verified = True
    elif action == "approve_all":
        for c in s.exec(select(Competition).where(Competition.needs_review == True)).all(): c.needs_review = False
    elif action == "approve": s.get(Competition, oid).needs_review = False
    elif action == "reject": s.delete(s.get(Competition, oid))
    elif action == "resolve": s.get(Report, oid).resolved = True
    elif action == "verify": s.get(User, oid).verified = True
    elif action == "rmsource":
        sp = s.get(SourcePage, oid)
        if sp: s.delete(sp)
    elif action in ("restore", "remove"):
        r = s.get(Report, oid)
        if r and r.kind in ("post", "comment"):
            if action == "remove":
                if r.kind == "post": purge_post(s, r.target_id)
                else:
                    c = s.get(Comment, r.target_id)
                    if c: c.body = "[deleted]"; c.hidden = False
            else:
                obj = s.get(Post if r.kind == "post" else Comment, r.target_id)
                if obj: obj.hidden = False
            for x in s.exec(select(Report).where(Report.kind == r.kind, Report.target_id == r.target_id)).all(): x.resolved = True
    elif action == "scrape": run_scrapers()
    s.commit(); return go("/admin")
