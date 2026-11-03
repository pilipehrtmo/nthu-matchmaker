import asyncio, re, secrets, time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse, Response
from markupsafe import Markup, escape
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
from . import guide
from .photo import make_avatar, PhotoError, MAX_UPLOAD
from .faculty import staff_email, nthu_url, check_page
TITLES = ["Professor", "Associate Professor", "Assistant Professor", "Lecturer", "Adjunct Professor", "Researcher", "Advisor"]
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    seed(); seed_starter(); seed_programs(); name_handles()
    if not DEMO_DATA: seed_examples()
    if DEMO_DATA:
        from .demo_data import seed_demo; seed_demo(); print(">>> DEMO MODE: sample teams loaded into a separate database. Do not share this server with real users.")
    warm(); sch = BackgroundScheduler()
    sch.add_job(run_scrapers); sch.add_job(run_scrapers, "cron", hour=3); sch.add_job(purge_logs, "cron", hour=4); sch.start()
    yield
    sch.shutdown()

def seed_programs():   # add any program from guide.PROGRAMS that is not in the database yet; admins edit them afterwards
    with Session(engine) as s:
        have = {p.key for p in s.exec(select(Program))}
        for d in guide.PROGRAMS:
            if d["key"] not in have: s.add(Program(**d))
        s.commit()

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

ERR_TITLES = {403: "Security check failed", 404: "Page not found", 429: "Slow down a little"}
@app.exception_handler(StarletteHTTPException)
async def http_error(req: Request, exc):
    if req.url.path.startswith(("/profile/cv", "/profile/photo", "/avatar/", "/static")) and not req.url.path.endswith("/delete"): return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    msg = exc.detail if exc.status_code != 404 else "That page does not exist, or it was deleted."
    return templates.TemplateResponse(req, "error.html", {"user": None, "csrf": req.session.get("csrf", "") if "session" in req.scope else "",
        "theme": req.cookies.get("theme", "light"), "inbox": 0, "title": ERR_TITLES.get(exc.status_code, "Something went wrong"), "msg": msg}, status_code=exc.status_code)
@app.exception_handler(RequestValidationError)
async def form_error(req: Request, exc):
    return templates.TemplateResponse(req, "error.html", {"user": None, "csrf": req.session.get("csrf", ""), "theme": req.cookies.get("theme", "light"), "inbox": 0,
        "title": "Please check the form", "msg": "A field was missing or had the wrong format (for example letters in a number box). Go back and try again."}, status_code=422)


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
    inbox = 0
    if user:   # applications waiting for this user's decision, shown as a badge on Activity
        with Session(engine) as s:
            inbox = len(s.exec(select(Application.id).join(Role, Role.id == Application.role_id).join(Project, Project.id == Role.project_id)
                               .where(Project.owner_id == user.id, Application.status == "pending")).all())
    return templates.TemplateResponse(req, name, {"user": user, "csrf": req.session["csrf"], "theme": theme, "inbox": inbox, **ctx})
def go(url): return RedirectResponse(url, status_code=303)
def kind_of(pr):   # older projects have no kind saved: infer it from the competition link
    return pr.kind or ("Competition" if pr.competition_id else "Side project")
templates.env.globals["kind_of"] = kind_of
templates.env.globals.update(CONTACTS=CONTACTS, PRO_LINKS=PRO_LINKS, G=guide)
templates.env.filters["shortlink"] = short

# ---------- names: everyone is shown by full name; the handle is only the web address /u/<handle> ----------
def dn(u): return (u.name or u.handle) if u else "[deleted]"
def initials(u):
    w = re.sub(r"[^\w\s]", " ", dn(u)).split()
    return ((w[0][0] + (w[-1][0] if len(w) > 1 else w[0][1:2])) if w else "?").upper()
def slugify(s, name, uid=None):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24].strip("-") or "student"
    h, n = base if len(base) >= 3 else base + "-nthu", 1
    while s.exec(select(User).where(User.handle == h, User.id != uid)).first(): n += 1; h = f"{base}-{n}"
    return h
def pic(u, cls="av"):   # profile photo if there is one, otherwise initials
    if u and u.avatar_v:
        return Markup(f'<img class="{cls} pic" src="/avatar/{u.id}?v={u.avatar_v}" alt="" loading="lazy" decoding="async">')
    return Markup(f'<span class="{cls}" aria-hidden="true">{escape(initials(u))}</span>')
templates.env.filters["dn"] = dn; templates.env.globals.update(initials=initials, pic=pic)

def name_handles():   # one-time: users who still have a random "student-xxxxxx" address get one made from their name
    with Session(engine) as s:
        for u in s.exec(select(User).where(User.handle.like("student-%"))).all():
            if u.name.strip(): u.handle = slugify(s, u.name, u.id); s.commit()

# ---------- auth ----------
SID = re.compile(r"^[A-Za-z0-9]{6,12}$")
HANDLE_RE = re.compile(r"^[a-z0-9._-]{3,30}$")

@app.get("/login")
def login_page(req: Request, user=Depends(me)): return render(req, "login.html", user, titles=TITLES)

@app.post("/login", dependencies=[limited("login", 300, 600)])   # per IP; each email is also limited below
def login(req: Request, email: str = Form(...), name: str = Form(""), student_id: str = Form(""), agree: str = Form(""),
          role: str = Form("student"), dept: str = Form(""), page: str = Form(""), title: str = Form(""), s: Session = Depends(get_session)):
    email = email.strip().lower(); name = " ".join(name.split())[:60]; sid = student_id.strip().upper()
    role = "faculty" if role == "faculty" else "student"; dept = dept.strip()[:60]; page = page.strip()[:300]
    back = lambda err: render(req, "login.html", error=err, titles=TITLES, form=dict(email=email, name=name, sid=sid, role=role, dept=dept, page=page, title=title))
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email): return back("Please enter a valid email address.")
    exists = s.exec(select(User).where(User.email == email)).first()
    if exists and exists.banned and email not in ADMIN_EMAILS: return back("This account is banned.")
    hit(f"mail:{email}", 3, 600)   # max 3 login emails per address per 10 minutes
    if not exists:
        if not agree: return back("Please agree to the privacy notice to create an account.")
        if role == "faculty":
            if not staff_email(email):
                return back("Professor and advisor accounts must use your NTHU staff email, for example name@cs.nthu.edu.tw or name@mx.nthu.edu.tw. Student addresses such as @gapp.nthu.edu.tw cannot be used.")
            if len(name) < 2 or not dept: return back("Enter your full name and your department.")
            if not nthu_url(page): return back("Paste a link to an NTHU page that lists you with this email, such as your department's faculty page. It must be on nthu.edu.tw.")
            sid = ""
        else:
            if not name or not SID.match(sid):
                return back("First time here? Enter your full name and student ID (6-12 letters or digits).")
            if s.exec(select(User).where(User.student_id == sid)).first():
                return back("That student ID already has an account.")
    s.add(SignupLog(email=email, ip="-", allowed=True)); s.commit()
    data = {'e': email, 'n': name, 's': sid}
    if role == "faculty" and not exists: data.update(r="faculty", d=dept, p=page, t=title if title in TITLES else "")
    link = f"{BASE_URL}/auth/{signer.dumps(data)}"
    try: send_magic(email, link)
    except Exception as e:   # mail server busy or down: tell the user instead of showing a server error
        print(">>> LOGIN EMAIL FAILED for", email, type(e).__name__, e)
        return back("We could not send the login email just now. Please wait a minute and try again.")
    return render(req, "login.html", sent=True, titles=TITLES, demo_link=link if SHOW_LINK and not SMTP_HOST else "")

def run_faculty_check(s, u):
    """Look for the user's email on their NTHU page. Found: verified automatically. Not found: an admin decides."""
    found, note = check_page(u.email, u.faculty_url)
    u.faculty_note = note[:300]
    if found: u.faculty_status, u.is_faculty = "verified", True
    elif u.faculty_status != "rejected": u.faculty_status, u.is_faculty = "pending", False
    s.add(u); s.commit()

@app.get("/auth/{token}")
def auth(req: Request, token: str, s: Session = Depends(get_session)):
    try: d = signer.loads(token, max_age=900)
    except BadSignature: return render(req, "login.html", error="That link is invalid or expired. Request a new one.", titles=TITLES)
    email = d["e"]; u = s.exec(select(User).where(User.email == email)).first(); new = u is None
    if new:
        fac = d.get("r") == "faculty"
        if fac and not staff_email(email): return render(req, "login.html", error="Professor accounts must use an NTHU staff email.", titles=TITLES)
        if not fac and (not d["s"] or s.exec(select(User).where(User.student_id == d["s"])).first()):
            return render(req, "login.html", error="That student ID already has an account.", titles=TITLES)
        u = User(email=email, name=d["n"], student_id=d["s"], handle=slugify(s, d["n"]), is_admin=email in ADMIN_EMAILS)
        if fac: u.role, u.faculty, u.faculty_url, u.title, u.faculty_status = "faculty", d.get("d", ""), d.get("p", ""), d.get("t", ""), "pending"
        s.add(u); s.commit(); s.refresh(u)
        if fac: run_faculty_check(s, u)
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
async def profile_save(req: Request, name: str = Form(...), bio: str = Form(""), skills: str = Form(""),
                 contact: str = Form(""), faculty: str = Form(""), hours: int = Form(4), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    form = await req.form()
    name = " ".join(name.split())[:60]
    if len(name) < 2 or not re.search(r"\w", name): return render(req, "profile.html", user, error="Please enter your full name.")
    try: links = {f: clean_link(f, str(form.get(f, ""))) for f, *_ in PRO_LINKS}
    except LinkError as e: return render(req, "profile.html", user, error=str(e))
    for f in ("line", "instagram", "discord"): setattr(user, f, clean_handle(str(form.get(f, ""))))
    for f, v in links.items(): setattr(user, f, v)
    if name != user.name: user.handle = slugify(s, name, user.id)   # the web address follows the name
    user.name, user.bio, user.contact = name, bio[:500], clean_contact(contact, 100)
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

@app.post("/profile/faculty", dependencies=[limited("faccheck", 6, 3600)])
def faculty_recheck(page: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user or user.role != "faculty" or user.faculty_status == "verified": return go("/profile")
    page = page.strip()[:300] or user.faculty_url
    if nthu_url(page): user.faculty_url = page; run_faculty_check(s, user)
    else: user.faculty_note = "The link must be on an nthu.edu.tw website."; s.add(user); s.commit()
    return go("/profile#faculty")

@app.post("/profile/photo", dependencies=[limited("photo", 20, 3600)])
def profile_photo(file: UploadFile = File(...), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return JSONResponse({"error": "Please log in again."}, status_code=401)
    try: data = make_avatar(file.file.read(MAX_UPLOAD + 1))
    except PhotoError as e: return JSONResponse({"error": str(e)}, status_code=400)
    a = s.get(Avatar, user.id)
    if a: a.data = data
    else: s.add(Avatar(user_id=user.id, data=data))
    user.avatar_v = (user.avatar_v or 0) + 1; s.add(user); s.commit()
    return {"url": f"/avatar/{user.id}?v={user.avatar_v}"}

@app.post("/profile/photo/delete")
def profile_photo_delete(user=Depends(me), s: Session = Depends(get_session)):
    if user:
        s.exec(delete(Avatar).where(Avatar.user_id == user.id)); user.avatar_v = 0; s.add(user); s.commit()
    return go("/profile")

@app.get("/avatar/{uid}")
def avatar(uid: int, s: Session = Depends(get_session)):
    u = s.get(User, uid); a = s.get(Avatar, uid) if u and u.avatar_v and not u.banned else None
    if not a: raise HTTPException(404)
    # the address changes on every upload (?v=), so browsers can keep it for a long time
    return Response(a.data, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})

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
            s.exec(delete(Remark).where(Remark.project_id == pid)); s.delete(s.get(Project, pid))
        for a in s.exec(select(Application).where(Application.user_id == user.id)): s.delete(a)
        s.exec(delete(Remark).where(Remark.author_id == user.id))
        s.exec(delete(Avatar).where(Avatar.user_id == user.id))
        s.exec(delete(SignupLog).where(SignupLog.email == email)); s.delete(user); s.commit(); req.session.clear()
    return go("/")

@app.get("/u/{handle}")
def public_profile(req: Request, handle: str, reported: str = "", user=Depends(me), s: Session = Depends(get_session)):
    p = s.exec(select(User).where(User.handle == handle)).first()
    if not p or p.banned: raise HTTPException(404)
    mine = s.exec(select(Project).where(Project.owner_id == p.id, Project.status == "open").order_by(Project.created.desc())).all()
    return render(req, "public.html", user, p=p, skills=sorted(tags(p.skills)), reported=bool(reported), projects=mine)

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
        days = days_left(pr.deadline)
        if not roles or (days is not None and days < 0): continue   # full or past its join-by date
        text = (pr.title + pr.description + pr.category + " ".join(r.name + r.skills for r in roles)).lower()
        if q and q.lower() not in text: continue
        if kind and kind_of(pr) != kind: continue
        owner = owners.get(pr.owner_id)
        # no match score on your own project
        best = max((match_pct(user, r, pr, owner) for r in roles), default=0) if user and user.id != pr.owner_id else None
        rows.append(dict(p=pr, roles=roles, owner=owner, score=best, total=len(allr), days=days))
    rows.sort(key=lambda r: -(r["score"] or 0))
    soon = {}   # nearest program deadline within 30 days, per project kind
    for prog in s.exec(select(Program).where(Program.active == True)).all():
        d = days_left(prog.next_deadline)
        if d is not None and 0 <= d <= 30 and (prog.for_kind not in soon or d < soon[prog.for_kind][1]): soon[prog.for_kind] = (prog.name.split(" (")[0], d)
    allc = s.exec(select(Competition).order_by(Competition.needs_review, Competition.id.desc())).all()
    cats = sorted({c.category for c in allc})
    comps = [c for c in allc if (not cat or c.category == cat) and (not q or q.lower() in (c.title + c.description).lower())][:60]
    return render(req, "board.html", user, rows=rows, comps=comps, q=q, cat=cat, cats=cats, kind=kind, kinds=PROJECT_KINDS, soon=soon)

def project_form(req, user, s, pr=None, seats=None, error="", **kw):
    kind = kw.get("kind", pr.kind if pr else "")
    return render(req, "new.html", user, pr=pr, seats=seats or [], error=error, filled=kw.get("filled", []), kind=kind, kinds=PROJECT_KINDS, sel=kw.get("sel", str(pr.competition_id or "") if pr else ""),
                  today=datetime.utcnow().date().isoformat(), comps=s.exec(select(Competition).order_by(Competition.title)).all())

def read_project_form(form, pr=None):
    """Check the project form. Returns (fields, seat lines, error)."""
    f = {k: str(form.get(k, "")).strip() for k in ("title", "description", "competition_id", "hours", "deadline", "roles", "kind", "category", "stage")}
    kind = f["kind"] if f["kind"] in PROJECT_KINDS else "Other"
    seats = []
    for line in f["roles"].splitlines():          # one seat per line: "UI designer: figma, ux", existing seats start with "#<id> "
        m = re.match(r"#(\d+) (.*)", line); rid = int(m.group(1)) if m else None; line = m.group(2) if m else line
        adv = line.startswith("@"); line = line[1:] if adv else line   # "@" marks an advisor seat
        name, _, sk = line.partition(":")
        if name.strip(): seats.append((name.strip()[:60], ",".join(t.strip() for t in sk.split(",") if t.strip())[:200], rid, adv))
    try: hours = int(f["hours"] or 4)
    except ValueError: hours = 0
    err = ""
    if len(f["title"]) < 3: err = "Give the project a title (at least 3 characters)."
    elif not 1 <= hours <= 60: err = "Hours per week must be a number from 1 to 60."
    elif f["deadline"] and days_left(f["deadline"]) is None: err = "The join-by date is not a valid date."
    elif f["deadline"] and days_left(f["deadline"]) < 0 and not (pr and pr.deadline == f["deadline"]): err = "The join-by date is in the past. Pick a future date or leave it empty."
    elif len(seats) > 12: err = "A project can have at most 12 seats."
    cats = guide.STARTUP_CATEGORIES if kind == "Startup" else guide.RESEARCH_FIELDS if kind == "Research" else []
    out = dict(title=f["title"][:120], description=f["description"][:2000], kind=kind, hours_per_week=hours if 1 <= hours <= 60 else 4,
               deadline=f["deadline"][:10], category=f["category"] if f["category"] in cats else "",
               stage=f["stage"] if kind == "Startup" and f["stage"] in [n for n, _ in guide.STARTUP_STAGES] else "",
               competition_id=int(f["competition_id"]) if f["competition_id"].isdigit() and kind == "Competition" else None)
    return out, seats, err

@app.get("/projects/new")
def new_project(req: Request, comp: str = "", kind: str = "", user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    kind = kind if kind in PROJECT_KINDS else ("Competition" if comp else "")
    return project_form(req, user, s, kind=kind, sel=comp)

@app.post("/projects/new", dependencies=[limited("newproj", 10, 3600)])
async def create_project(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    f, seats, err = read_project_form(await req.form())
    if not seats and not err: err = "Add at least one open seat, so people know who you need."
    if err:
        draft = Project(owner_id=user.id, **f)
        return project_form(req, user, s, pr=draft, seats=seats, error=err, kind=f["kind"], sel=str(f["competition_id"] or ""))
    pr = Project(owner_id=user.id, **f); s.add(pr); s.commit(); s.refresh(pr)
    for n, sk, _, adv in seats: s.add(Role(project_id=pr.id, name=n, skills=sk, advisor=adv))
    s.commit(); return go(f"/projects/{pr.id}")

@app.get("/projects/{pid}/edit")
def edit_project(req: Request, pid: int, user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if not pr: raise HTTPException(404)
    if not user or user.id != pr.owner_id: return go(f"/projects/{pid}")
    roles = s.exec(select(Role).where(Role.project_id == pid).order_by(Role.id)).all()
    return project_form(req, user, s, pr=pr, seats=[(r.name, r.skills, r.id, r.advisor) for r in roles if not r.filled], filled=[r for r in roles if r.filled])

@app.post("/projects/{pid}/edit", dependencies=[limited("editproj", 30, 3600)])
async def save_project(req: Request, pid: int, user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if not pr: raise HTTPException(404)
    if not user or user.id != pr.owner_id: return go(f"/projects/{pid}")
    f, seats, err = read_project_form(await req.form(), pr)
    roles = s.exec(select(Role).where(Role.project_id == pid).order_by(Role.id)).all()
    open_roles = [r for r in roles if not r.filled]
    if err:
        for k, v in f.items(): setattr(pr, k, v)
        s.expunge(pr)   # show what they typed without saving it
        return project_form(req, user, s, pr=pr, seats=seats, error=err)
    if not seats and not any(r.filled for r in roles): return project_form(req, user, s, pr=pr, seats=seats, error="Keep at least one seat.")
    for k, v in f.items(): setattr(pr, k, v)
    keep = {rid: (n, sk, adv) for n, sk, rid, adv in seats if rid}
    for r in open_roles:   # edited seats keep their applicants; removed seats take their applications with them
        if r.id in keep: r.name, r.skills, r.advisor = keep[r.id]
        else:
            for a in s.exec(select(Application).where(Application.role_id == r.id)).all(): s.delete(a)
            s.delete(r)
    ids = {r.id for r in open_roles}
    for n, sk, rid, adv in seats:
        if rid not in ids: s.add(Role(project_id=pid, name=n, skills=sk, advisor=adv))
    s.commit(); return go(f"/projects/{pid}")

@app.post("/projects/{pid}/status")
def project_status(pid: int, status: str = Form(...), user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if pr and user and user.id == pr.owner_id and status in ("open", "closed"): pr.status = status; s.commit()
    return go(f"/projects/{pid}")

@app.get("/projects/{pid}")
def project(req: Request, pid: int, user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if not pr: raise HTTPException(404)
    owner = s.get(User, pr.owner_id); is_owner = bool(user and user.id == owner.id); out = []
    for r in s.exec(select(Role).where(Role.project_id == pid)):
        apps = []
        for a in s.exec(select(Application).where(Application.role_id == r.id)):
            # application notes are private: only the project lead, the applicant and admins see them
            if is_owner or (user and (a.user_id == user.id or user.is_admin)): apps.append((a, s.get(User, a.user_id)))
        pct = match_pct(user, r, pr, owner) if user and not r.filled and not is_owner and not r.advisor else None
        out.append(dict(r=r, apps=apps, mine=any(u.id == (user.id if user else 0) for _, u in apps),
                        pct=pct, why=why(user, r, pct) if pct is not None else ""))
    reveal = bool(user and any(a.status == "accepted" and u.id == user.id for r in out for a, u in r["apps"]))
    days = days_left(pr.deadline)
    accepting = pr.status == "open" and not (days is not None and days < 0)
    acc = s.exec(select(Application, Role).join(Role, Role.id == Application.role_id).where(Role.project_id == pid, Application.status == "accepted")).all()
    team = [a.user_id for a, r in acc if not r.advisor]; advisors = [a.user_id for a, r in acc if r.advisor]
    fac = {u.id for u in s.exec(select(User).where(User.id.in_(team or [-1]), User.is_faculty == True))}
    students = 1 + len([t for t in team if t not in fac])
    k = kind_of(pr); checks = []
    if k in ("Startup", "Research"):
        for prog in s.exec(select(Program).where(Program.active == True, Program.for_kind.in_([k, "Any"])).order_by(Program.sort)).all():
            items = guide.readiness(prog, pr, 1 + len(team), students, len(advisors))
            checks.append(dict(p=prog, lines=items, ready=not any(st == "miss" for st, _, _ in items), days=days_left(prog.next_deadline)))
    my_adv = bool(user and any(x["r"].advisor and a.status == "accepted" and u.id == user.id for x in out for a, u in x["apps"]))
    insider = bool(user and (is_owner or user.is_admin or reveal or my_adv))
    rq = select(Remark).where(Remark.project_id == pid).order_by(Remark.created.desc())
    remarks = s.exec(rq if insider else rq.where(Remark.public == True)).all()
    rauthors = {u.id: u for u in s.exec(select(User).where(User.id.in_([r.author_id for r in remarks] or [-1])))}
    return render(req, "project.html", user, checks=checks, remarks=remarks, rauthors=rauthors, can_remark=my_adv, insider=insider, accepting=accepting, notice=req.query_params.get("n", ""), pr=pr, owner=owner, is_owner=is_owner, roles=out, reveal=reveal, mytags=tags(user.skills) if user else set(), days=days,
                  comp=s.get(Competition, pr.competition_id) if pr.competition_id else None)

@app.post("/projects/{pid}/delete")
def delete_project(pid: int, user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if user and pr and (pr.owner_id == user.id or user.is_admin):
        for r in s.exec(select(Role).where(Role.project_id == pid)).all():
            for a in s.exec(select(Application).where(Application.role_id == r.id)).all(): s.delete(a)
            s.delete(r)
        s.exec(delete(Remark).where(Remark.project_id == pid)); s.delete(pr); s.commit()
    return go("/")

@app.post("/roles/{rid}/apply", dependencies=[limited("apply", 30, 3600)])
def apply(rid: int, message: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    r = s.get(Role, rid); pr = s.get(Project, r.project_id) if r else None
    if not pr: raise HTTPException(404)
    d = days_left(pr.deadline)
    if r.filled or pr.status != "open" or (d is not None and d < 0): return go(f"/projects/{pr.id}?n=closed")
    if pr.owner_id == user.id: return go(f"/projects/{pr.id}")
    dup = s.exec(select(Application).where(Application.role_id == rid, Application.user_id == user.id)).first()
    if dup and dup.status == "withdrawn": dup.status, dup.message, dup.at = "pending", message.strip()[:500], datetime.utcnow(); s.commit()
    elif not dup: s.add(Application(role_id=rid, user_id=user.id, message=message.strip()[:500])); s.commit()
    return go(f"/projects/{pr.id}?n=sent")

@app.post("/applications/{aid}/{decision}")
def decide(aid: int, decision: str, user=Depends(me), s: Session = Depends(get_session)):
    a = s.get(Application, aid); r = s.get(Role, a.role_id) if a else None; pr = s.get(Project, r.project_id) if r else None
    if not pr: raise HTTPException(404)
    if not user: return go("/login")
    if decision == "withdrawn" and a.user_id == user.id and a.status == "pending":
        a.status = "withdrawn"; s.commit(); return go(f"/projects/{pr.id}?n=withdrawn")
    if user.id == pr.owner_id and a.status == "pending" and decision in ("accepted", "rejected") and not r.filled:
        a.status = decision
        if decision == "accepted":
            r.filled = True   # the seat is taken: close the other applications for it
            for o in s.exec(select(Application).where(Application.role_id == r.id, Application.id != a.id, Application.status == "pending")).all(): o.status = "closed"
        s.commit()
    return go(f"/projects/{pr.id}")

@app.get("/activity")
def activity(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    mine = s.exec(select(Project).where(Project.owner_id == user.id).order_by(Project.created.desc())).all()
    roles = {r.id: r for r in s.exec(select(Role).where(Role.project_id.in_([p.id for p in mine] or [-1])))}
    pend = defaultdict(int); seats = defaultdict(lambda: [0, 0])
    for r in roles.values(): seats[r.project_id][0] += 1; seats[r.project_id][1] += int(r.filled)
    for a in s.exec(select(Application).where(Application.role_id.in_(list(roles) or [-1]), Application.status == "pending")): pend[roles[a.role_id].project_id] += 1
    apps = s.exec(select(Application).where(Application.user_id == user.id).order_by(Application.at.desc())).all()
    aroles = {r.id: r for r in s.exec(select(Role).where(Role.id.in_([a.role_id for a in apps] or [-1])))}
    aprojs = {p.id: p for p in s.exec(select(Project).where(Project.id.in_([r.project_id for r in aroles.values()] or [-1])))}
    sent = [(a, aroles[a.role_id], aprojs[aroles[a.role_id].project_id]) for a in apps if a.role_id in aroles and aroles[a.role_id].project_id in aprojs]
    return render(req, "activity.html", user, mine=mine, pend=pend, seats=seats, sent=sent, days_left=days_left)

@app.post("/projects/{pid}/remarks", dependencies=[limited("remark", 30, 3600)])
def add_remark(pid: int, body: str = Form(...), public: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if not s.get(Project, pid): raise HTTPException(404)
    ok = s.exec(select(Application).join(Role, Role.id == Application.role_id).where(Role.project_id == pid, Role.advisor == True,
                Application.user_id == user.id, Application.status == "accepted")).first()
    if ok and body.strip(): s.add(Remark(project_id=pid, author_id=user.id, body=body.strip()[:3000], public=bool(public))); s.commit()
    return go(f"/projects/{pid}#remarks")

@app.post("/remarks/{rid}/delete")
def delete_remark(rid: int, user=Depends(me), s: Session = Depends(get_session)):
    r = s.get(Remark, rid)
    if not r: raise HTTPException(404)
    if user and (user.id == r.author_id or user.is_admin): s.delete(r); s.commit()
    return go(f"/projects/{r.project_id}#remarks")

@app.get("/funding")
def funding(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    progs = s.exec(select(Program).where(Program.active == True).order_by(Program.sort)).all()
    mine = s.exec(select(Project).where(Project.owner_id == user.id, Project.kind.in_(["Startup", "Research"]))).all() if user else []
    return render(req, "funding.html", user, progs=progs, mine=mine, days_left=days_left)

@app.post("/report/{uid}", dependencies=[limited("report", 10, 3600)])
def report(uid: int, reason: str = Form(...), user=Depends(me), s: Session = Depends(get_session)):
    target = s.get(User, uid)
    if not target: raise HTTPException(404)
    if user and user.id != uid and reason.strip() and not s.exec(select(Report).where(Report.reporter_id == user.id, Report.kind == "user", Report.target_user_id == uid, Report.resolved == False)).first():
        s.add(Report(reporter_id=user.id, target_user_id=uid, reason=reason.strip()[:500])); s.commit()
    return go(f"/u/{target.handle}?reported=1")

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
    return render(req, "admin.html", user, users=s.exec(select(User)).all(), staff_email=staff_email,
        fac_requests=s.exec(select(User).where(User.faculty_status == "pending")).all(), programs=s.exec(select(Program).order_by(Program.sort)).all(),
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

@app.post("/admin/program")
async def save_program(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    if not (user and user.is_admin): return go("/")
    f = {k: str(v).strip() for k, v in (await req.form()).items()}
    p = s.get(Program, int(f["id"])) if f.get("id", "").isdigit() else None
    if not p:
        if not f.get("name"): return go("/admin#programs")
        p = Program(key="custom-" + secrets.token_hex(4), name="", sort=99); s.add(p)
    if f.get("next_deadline") and days_left(f["next_deadline"]) is None: f["next_deadline"] = ""
    for k in ("name", "org", "url", "amount", "who", "next_deadline", "deadline_note"):
        if k in f and (f[k] or k in ("next_deadline", "deadline_note")): setattr(p, k, f[k][:300])
    if f.get("for_kind") in ("Startup", "Research", "Any"): p.for_kind = f["for_kind"]
    if "url" in f and f["url"] and not f["url"].startswith("http"): p.url = ""
    p.active = f.get("active") == "on"
    s.commit(); return go("/admin#programs")

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
    elif action in ("approve", "reject", "resolve", "verify"):
        obj = s.get({"approve": Competition, "reject": Competition, "resolve": Report, "verify": User}[action], oid)
        if not obj: return go("/admin")
        if action == "approve": obj.needs_review = False
        elif action == "reject": s.delete(obj)
        elif action == "resolve": obj.resolved = True
        else: obj.verified = True
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
    elif action == "rmphoto":   # remove an inappropriate profile photo
        u = s.get(User, oid)
        if u: s.exec(delete(Avatar).where(Avatar.user_id == oid)); u.avatar_v = 0
    elif action in ("faculty", "unfaculty"):   # admins can approve only people with an NTHU staff email
        u = s.get(User, oid)
        if u and (action == "unfaculty" or staff_email(u.email)):
            u.is_faculty = action == "faculty"; u.faculty_status = "verified" if u.is_faculty else ("rejected" if u.role == "faculty" else "")
            if u.is_faculty: u.role = "faculty"
    elif action == "faccheck":
        u = s.get(User, oid)
        if u and u.faculty_url: run_faculty_check(s, u)
    elif action == "scrape": run_scrapers()
    s.commit(); return go("/admin")
