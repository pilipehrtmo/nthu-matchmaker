import asyncio, hashlib, os, re, secrets, time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse, Response
from markupsafe import Markup, escape
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlmodel import Session, select, delete, func
from starlette.middleware.sessions import SessionMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from .config import *
from .db import init_db, get_session, engine
from .models import *
from .mail import send_mail, email_enabled
from .security import hash_password, check_password, password_problem, new_token, token_hash, expires_in
from .scraper import run_scrapers
from .seed import seed, seed_starter, seed_examples
from .matching import match_pct, why, warm
from .cv import parse_cv, CVError, MAX_BYTES
from .links import CONTACTS, PRO_LINKS, LinkError, clean_contact, clean_handle, clean_link, short
from . import guide
from .photo import make_avatar, PhotoError, MAX_UPLOAD
from .faculty import staff_email, nthu_url, check_page, nthu_email, shared_domain
STUDENT_EMAIL_RULE = os.getenv("STUDENT_EMAIL_RULE", "any")   # "nthu" = students must sign up with an NTHU address (see faculty.nthu_email)
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
# 中文: the same templates, translated when loaded (see i18n.py); globals and filters are shared with the English set
from jinja2 import Environment
from .i18n import ZhLoader, finalize_zh, keep, pick_lang, LANGS
templates_zh = Jinja2Templates(env=Environment(loader=ZhLoader("app/templates"), autoescape=True, finalize=finalize_zh))
templates_zh.env.globals = templates.env.globals; templates_zh.env.filters = templates.env.filters
templates.env.globals.update(keep=keep, LANGS=LANGS)
from jinja2 import pass_context
from .i18n import t as _t
@pass_context
def tr_filter(ctx, s): return keep(_t(s, ctx.get("lang", "en")))   # translate a value on purpose (e.g. for a script's lookup table)
templates.env.filters["tr"] = tr_filter
def tpl(req): return templates_zh if pick_lang(req) == "zh" else templates

def keep_awake():   # Render's free plan sleeps after 15 min with no visitors; a request to our own public URL every 10 min keeps it up
    try:
        import httpx; httpx.get(BASE_URL.rstrip("/") + "/healthz", timeout=20)
    except Exception as e:
        print(">>> keep-awake ping failed:", type(e).__name__, flush=True)

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
    sch.add_job(run_scrapers); sch.add_job(run_scrapers, "cron", hour=3); sch.add_job(purge_logs, "cron", hour=4)
    if PUBLIC and os.getenv("KEEP_AWAKE", "1") == "1": sch.add_job(keep_awake, "interval", minutes=10)
    from .notify import send_digests, send_reminders   # 00:00 UTC = 08:00 Taiwan time
    sch.add_job(send_reminders, "cron", hour=0, minute=0); sch.add_job(send_digests, "cron", hour=0, minute=5)
    from .opps import send_deadline_reminders
    sch.add_job(send_deadline_reminders, "cron", hour=0, minute=2)
    from . import fundscan   # opens every funding program's official page: daily at 09:00 Taiwan time, and once soon after start
    sch.add_job(fundscan.run, "cron", hour=1, minute=0)
    sch.add_job(fundscan.run, "date", run_date=datetime.now() + timedelta(minutes=2))   # set KEEP_AWAKE=0 on Render to let it sleep again
    sch.start()
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
def wait_left(key: str, n: int, secs: int) -> int:
    """Seconds until `key` may act again (0 = allowed now). Does not count this call."""
    q = HITS[key]; now = time.time()
    while q and q[0] < now - secs: q.popleft()
    return int(q[0] + secs - now) + 1 if len(q) >= n else 0
def note(key: str): HITS[key].append(time.time())
def wait_text(secs: int) -> str:
    m = (secs + 59) // 60
    return "about a minute" if m <= 1 else f"about {m} minutes"
def hit(key: str, n: int, secs: int):
    w = wait_left(key, n, secs)
    if w: raise HTTPException(429, f"You did that a lot in a short time. Please wait {wait_text(w)} and try again.")
    note(key)
def limited(name: str, n: int, secs: int):
    # Logged-in actions are limited per account, not per IP: a whole class on campus Wi-Fi shares one public IP.
    def dep(request: Request):
        uid = request.session.get("uid")
        hit(f"{name}:u{uid}" if uid else f"{name}:{ip_of(request)}", n, secs)
    return Depends(dep)

if SECRET == "dev-secret-change-me": print("WARNING: set SECRET_KEY before real use.")
app = FastAPI(lifespan=lifespan, dependencies=[Depends(csrf_check)], docs_url=None, redoc_url=None, openapi_url=None)   # no public API explorer
# At most 10 pages are built at once; the rest wait in line without holding a thread.
# The database pool has 12 connections, so a page never waits for one (no pile-up when a whole class logs in).
SLOTS = asyncio.Semaphore(10)
@app.middleware("http")
async def one_queue(request: Request, call_next):
    if request.url.path.startswith("/static"): return await call_next(request)
    async with SLOTS: return await call_next(request)
# Browser security headers on every response
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; form-action 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("Content-Security-Policy", CSP)
    h.setdefault("X-Frame-Options", "DENY")                 # no one can put the site inside their page (clickjacking)
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if PUBLIC: h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if "session" in request.scope and request.session.get("uid") and not request.url.path.startswith(("/static", "/avatar/")):
        h.setdefault("Cache-Control", "private, no-store")   # pages with someone's data are never kept by shared caches
    return resp
@app.get("/healthz", include_in_schema=False)
def healthz(): return Response("ok", media_type="text/plain")   # tiny page for the keep-awake ping: no database, no login
app.add_middleware(SessionMiddleware, secret_key=SECRET, max_age=60 * 60 * 24 * 30, https_only=PUBLIC, same_site="lax")
if PUBLIC and SECRET == "dev-secret-change-me": raise SystemExit("Set SECRET_KEY before putting the site online.")
if PUBLIC and not SMTP_HOST: print("WARNING: no SMTP settings, so login emails cannot be sent. Set SMTP_HOST/SMTP_USER/SMTP_PASS/SMTP_FROM.")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

ERR_TITLES = {403: "Security check failed", 404: "Page not found", 429: "Slow down a little"}
@app.exception_handler(StarletteHTTPException)
async def http_error(req: Request, exc):
    if req.url.path.startswith(("/profile/cv", "/profile/photo", "/avatar/", "/static")) and not req.url.path.endswith("/delete"): return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    msg = exc.detail if exc.status_code != 404 else "That page does not exist, or it was deleted."
    return tpl(req).TemplateResponse(req, "error.html", {"user": None, "lang": pick_lang(req), "csrf": req.session.get("csrf", "") if "session" in req.scope else "",
        "theme": req.cookies.get("theme", "light"), "inbox": 0, "title": ERR_TITLES.get(exc.status_code, "Something went wrong"), "msg": msg}, status_code=exc.status_code)
@app.exception_handler(RequestValidationError)
async def form_error(req: Request, exc):
    return tpl(req).TemplateResponse(req, "error.html", {"user": None, "lang": pick_lang(req), "csrf": req.session.get("csrf", ""), "theme": req.cookies.get("theme", "light"), "inbox": 0,
        "title": "Please check the form", "msg": "A field was missing or had the wrong format (for example letters in a number box). Go back and try again."}, status_code=422)


def me(req: Request, s: Session = Depends(get_session)):
    uid = req.session.get("uid"); u = s.get(User, uid) if uid else None
    if not u or u.banned: return None
    if "pv" not in req.session: req.session["pv"] = pw_stamp(u)   # logged in before this check existed
    elif req.session["pv"] != pw_stamp(u):   # the password changed since this login (or an old cookie): log this device out
        req.session.clear(); return None
    return u

def tags(text: str): return {t.strip().lower() for t in text.split(",") if t.strip()}
def days_left(d):
    try: return (datetime.strptime(d, "%Y-%m-%d").date() - datetime.utcnow().date()).days
    except (ValueError, TypeError): return None
def render(req, name, user=None, **ctx):
    if "csrf" not in req.session: req.session["csrf"] = secrets.token_hex(16)
    theme = req.cookies.get("theme", "light")
    if theme not in ("light", "dark", "system"): theme = "light"
    inbox = bell = 0
    if user:   # applications waiting for this user's decision, shown as a badge on Activity
        with Session(engine) as s:
            from .advisor import attention
            inbox = attention(s, user)["total"]   # the same count the dashboard / Activity page shows
            from .notify import unread
            bell = unread(s, user.id)
    return tpl(req).TemplateResponse(req, name, {"user": user, "csrf": req.session["csrf"], "theme": theme, "inbox": inbox, "bell": bell, "lang": pick_lang(req), **ctx})
def go(url): return RedirectResponse(url, status_code=303)
def kind_of(pr):   # older projects have no kind saved: infer it from the competition link
    return pr.kind or ("Competition" if pr.competition_id else "Side project")
templates.env.globals["kind_of"] = kind_of

@__import__('functools').lru_cache(maxsize=None)
def asset(name: str) -> str:   # /static/x?v=<content hash>: browsers fetch a new copy whenever the file changes
    import hashlib
    try: v = hashlib.md5(open(f"app/static/{name}", "rb").read()).hexdigest()[:10]
    except OSError: v = "0"
    return f"/static/{name}?v={v}"
templates.env.globals["asset"] = asset
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
def facbadge(u):   # green badge for verified professors/advisors, showing the title they chose at sign-up
    if not (u and u.is_faculty): return ""
    return Markup(f'<span class="pill fac" title="Verified NTHU teaching staff">✔ {escape(u.title or "Faculty")}</span>')
templates.env.filters["dn"] = dn; templates.env.globals.update(initials=initials, pic=pic, facbadge=facbadge)

def name_handles():   # one-time: users who still have a random "student-xxxxxx" address get one made from their name
    with Session(engine) as s:
        for u in s.exec(select(User).where(User.handle.like("student-%"))).all():
            if u.name.strip(): u.handle = slugify(s, u.name, u.id); s.commit()

# ---------- auth ----------
SID = re.compile(r"^[A-Za-z0-9]{6,12}$")
HANDLE_RE = re.compile(r"^[a-z0-9._-]{3,30}$")

def verify_required() -> bool:   # only ask people to verify when the server can really send email
    return REQUIRE_VERIFY == "1" or (REQUIRE_VERIFY == "auto" and bool(BREVO_API_KEY))
templates.env.globals["verify_required"] = verify_required
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def make_link(s, u, kind, hours):
    t, h = new_token(); s.add(AuthToken(user_id=u.id, kind=kind, token_hash=h, expires=expires_in(hours))); s.commit()
    return f"{BASE_URL}/{'verify' if kind == 'verify' else 'reset'}/{t}"

def use_token(s, t, kinds):
    tok = s.exec(select(AuthToken).where(AuthToken.token_hash == token_hash(t))).first()
    if not tok or tok.used or tok.kind not in kinds or tok.expires < datetime.utcnow(): return None, None
    return tok, s.get(User, tok.user_id)

def send_verify(s, u):
    link = make_link(s, u, "verify", 48)
    send_mail(u.email, "Confirm your email for NTHU Matchmaker",
              f"Hi {u.name or ''},\n\nConfirm your email to finish creating your NTHU Matchmaker account:\n{link}\n\nThe link works for 48 hours. If you did not sign up, ignore this email.")

def pw_stamp(u): return hashlib.sha256((u.password_hash or "").encode()).hexdigest()[:12]
def start_session(req, u):
    req.session.pop("pending_uid", None); req.session["uid"] = u.id; req.session["pv"] = pw_stamp(u)
    if u.lang in LANGS: req.session["lang"] = u.lang   # the language chosen on any device follows the account

def ip_of(req):
    """The visitor's real IP, for rate limits. On Render, Cloudflare sets CF-Connecting-IP and overwrites any copy the visitor sends.
    X-Forwarded-For is not used: anyone can put a fake address in it and dodge the limits."""
    cf = req.headers.get("cf-connecting-ip", "").strip()
    if PUBLIC and cf: return cf[:64]
    return req.client.host if req.client else "-"

@app.get("/login")
def login_page(req: Request, n: str = "", user=Depends(me)):
    if user: return go("/")
    return render(req, "login.html", notice=n)

@app.post("/login")
def login(req: Request, email: str = Form(""), password: str = Form(""), s: Session = Depends(get_session)):
    email = email.strip().lower()
    back = lambda err, **kw: render(req, "login.html", error=err, email=email, **kw)
    # count only failed attempts: 8 per email and 60 per network in 15 minutes
    w = max(wait_left(f"fail:{email}", 8, 900), wait_left(f"failip:{ip_of(req)}", 60, 900))
    if w: return back(f"Too many wrong passwords. Please wait {wait_text(w)}, or use Forgot password.")
    u = s.exec(select(User).where(User.email == email)).first() if email else None
    if u and not u.password_hash:
        return back("This account was made before the site had passwords. Use Forgot password to set one." if email_enabled() and BREVO_API_KEY
                    else "This account was made before the site had passwords. Ask an admin for a password setup link.")
    if not u or not check_password(password, u.password_hash):
        note(f"fail:{email}"); note(f"failip:{ip_of(req)}")
        return back("That email and password do not match. Check both and try again.")
    if u.banned and email not in ADMIN_EMAILS: return back("This account is banned.")
    if verify_required() and not u.email_verified:
        req.session["pending_uid"] = u.id
        return render(req, "notice.html", title="Confirm your email first", pending=True,
                      msg=f"We sent a link to {u.email}. Open it to finish signing up. Check your spam folder too.")
    if email in ADMIN_EMAILS and (not u.is_admin or u.banned): u.is_admin = True; u.banned = False; s.commit()   # listed admins are never locked out
    if not u.lang and req.cookies.get("lang") in LANGS: u.lang = req.cookies["lang"]; s.add(u); s.commit()   # keep the language they were already using
    start_session(req, u); return go("/")

@app.get("/signup")
def signup_page(req: Request, user=Depends(me)):
    if user: return go("/")
    return render(req, "signup.html", titles=TITLES, form={})

@app.post("/signup")
def signup(req: Request, email: str = Form(""), name: str = Form(""), student_id: str = Form(""), agree: str = Form(""), password: str = Form(""),
           password2: str = Form(""), role: str = Form("student"), dept: str = Form(""), page: str = Form(""), title: str = Form(""), s: Session = Depends(get_session)):
    email = email.strip().lower(); name = " ".join(name.split())[:60]; sid = student_id.strip().upper()
    role = "faculty" if role == "faculty" else "student"; dept = dept.strip()[:60]; page = page.strip()[:300]
    back = lambda err: render(req, "signup.html", error=err, titles=TITLES, form=dict(email=email, name=name, sid=sid, role=role, dept=dept, page=page, title=title))
    # 200 new accounts per network per hour: a whole class on campus Wi-Fi shares one address
    w = wait_left(f"signup:{ip_of(req)}", 200, 3600)
    if w: return back(f"Many accounts were just created from this network. Please wait {wait_text(w)} and try again.")
    if not EMAIL_RE.match(email): return back("Please enter a valid email address.")
    if len(name) < 2: return back("Please enter your full name.")
    if s.exec(select(User).where(User.email == email)).first(): return back("An account with this email already exists. Log in instead, or use Forgot password.")
    if role == "faculty":
        if not nthu_email(email):
            return back("Professor and advisor accounts must use an NTHU email, for example name@cs.nthu.edu.tw, name@mx.nthu.edu.tw or name@gapp.nthu.edu.tw.")
        if not dept: return back("Enter your department.")
        if not nthu_url(page): return back("Paste a link to an NTHU page that lists you with this email, such as your department's faculty page. It must be on nthu.edu.tw.")
        sid = ""
    else:
        if STUDENT_EMAIL_RULE == "nthu" and not nthu_email(email) and email not in ADMIN_EMAILS:
            return back("Use your NTHU email to sign up, for example s114123456@m114.nthu.edu.tw or your @gapp.nthu.edu.tw address.")
        if not SID.match(sid): return back("Enter your student ID (6 to 12 letters or digits).")
        if s.exec(select(User).where(User.student_id == sid)).first(): return back("That student ID already has an account. Log in instead, or use Forgot password.")
    err = password_problem(password, email, name)
    if err: return back(err)
    if password != password2: return back("The two passwords are not the same.")
    if not agree: return back("Please agree to the privacy notice to create an account.")
    u = User(email=email, name=name, student_id=sid, handle=slugify(s, name), is_admin=email in ADMIN_EMAILS, password_hash=hash_password(password))
    u.lang = pick_lang(req)
    if role == "faculty": u.role, u.faculty, u.faculty_url, u.title, u.faculty_status = "faculty", dept, page, title if title in TITLES else "", "pending"
    else: u.faculty = dept   # department or major, shown on the profile and used by the Department filter
    s.add(u); s.add(SignupLog(email=email, ip="-", allowed=True)); s.commit(); s.refresh(u)
    note(f"signup:{ip_of(req)}")
    if role == "faculty": run_faculty_check(s, u)
    if verify_required():
        req.session["pending_uid"] = u.id
        try: send_verify(s, u)
        except Exception as e:
            print(">>> VERIFY EMAIL FAILED", email, type(e).__name__, e)
            return render(req, "notice.html", title="Account created", pending=True, msg="We could not send the confirmation email just now. Press Send again in a minute.")
        return render(req, "notice.html", title="Check your inbox", pending=True,
                      msg=f"We sent a link to {email}. Open it to finish signing up. It can take a minute, and may land in spam.")
    start_session(req, u); return go("/profile")

@app.get("/verify/{t}")
def verify(req: Request, t: str, s: Session = Depends(get_session)):
    tok, u = use_token(s, t, ("verify",))
    if not u: return render(req, "notice.html", title="Link not valid", msg="This confirmation link is wrong, expired or already used. Log in to get a new one.", show_login=True)
    tok.used = True; u.email_verified = True; s.commit()
    start_session(req, u); return go("/profile")

@app.post("/verify/resend")
def verify_resend(req: Request, s: Session = Depends(get_session)):
    uid = req.session.get("pending_uid") or req.session.get("uid"); u = s.get(User, uid) if uid else None
    if not u or u.email_verified: return go("/login")
    w = wait_left(f"verify:{u.id}", 3, 3600)
    if w: return render(req, "notice.html", title="Please wait", pending=True, msg=f"We already sent 3 links this hour. Please wait {wait_text(w)}, and check your spam folder.")
    note(f"verify:{u.id}")
    try: send_verify(s, u)
    except Exception as e:
        print(">>> VERIFY EMAIL FAILED", u.email, type(e).__name__, e)
        return render(req, "notice.html", title="Could not send", pending=True, msg="We could not send the email just now. Try again in a minute.")
    return render(req, "notice.html", title="Sent again", pending=True, msg=f"A new link is on its way to {u.email}.")

@app.get("/forgot")
def forgot_page(req: Request): return render(req, "forgot.html", can_email=bool(BREVO_API_KEY) or not PUBLIC)

@app.post("/forgot")
def forgot(req: Request, email: str = Form(""), s: Session = Depends(get_session)):
    email = email.strip().lower(); can = bool(BREVO_API_KEY) or not PUBLIC
    if not can: return render(req, "forgot.html", can_email=False)
    w = max(wait_left(f"forgot:{email}", 3, 3600), wait_left(f"forgotip:{ip_of(req)}", 30, 3600))
    if w: return render(req, "forgot.html", can_email=True, error=f"Too many reset emails. Please wait {wait_text(w)}.", email=email)
    note(f"forgot:{email}"); note(f"forgotip:{ip_of(req)}")
    u = s.exec(select(User).where(User.email == email)).first()
    if u and not u.banned:
        link = make_link(s, u, "reset", 1)
        try: send_mail(u.email, "Set your NTHU Matchmaker password", f"Hi {u.name or ''},\n\nSet a new password here (the link works for 1 hour):\n{link}\n\nIf you did not ask for this, ignore this email.")
        except Exception as e:
            print(">>> RESET EMAIL FAILED", email, type(e).__name__, e)
            return render(req, "forgot.html", can_email=True, error="We could not send the email just now. Try again in a minute.", email=email)
    # same answer whether or not the account exists, so nobody can test which emails have accounts
    return render(req, "notice.html", title="Check your inbox", msg="If an account uses that email, we sent it a link to set a new password. It works for 1 hour; check spam too.", show_login=True)

@app.get("/reset/{t}")
def reset_page(req: Request, t: str, s: Session = Depends(get_session)):
    tok, u = use_token(s, t, ("reset", "setup"))
    if not u: return render(req, "notice.html", title="Link not valid", msg="This password link is wrong, expired or already used. Ask for a new one.", show_login=True)
    return render(req, "reset.html", t=t, who=u)

@app.post("/reset/{t}")
def reset(req: Request, t: str, password: str = Form(""), password2: str = Form(""), s: Session = Depends(get_session)):
    tok, u = use_token(s, t, ("reset", "setup"))
    if not u: return render(req, "notice.html", title="Link not valid", msg="This password link is wrong, expired or already used. Ask for a new one.", show_login=True)
    err = password_problem(password, u.email, u.name) or ("The two passwords are not the same." if password != password2 else "")
    if err: return render(req, "reset.html", t=t, who=u, error=err)
    u.password_hash = hash_password(password)
    if tok.kind == "reset": u.email_verified = True   # the link came by email, so they own the address
    for x in s.exec(select(AuthToken).where(AuthToken.user_id == u.id, AuthToken.kind.in_(["reset", "setup"]), AuthToken.used == False)).all(): x.used = True
    s.commit()
    if u.banned and u.email not in ADMIN_EMAILS: return render(req, "notice.html", title="Account banned", msg="This account is banned.")
    if u.email in ADMIN_EMAILS and not u.is_admin: u.is_admin = True; s.commit()
    start_session(req, u); return go("/?n=pw")

@app.post("/profile/password", dependencies=[limited("pwchange", 10, 3600)])
def change_password(req: Request, current: str = Form(""), password: str = Form(""), password2: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    err = ""
    if user.password_hash and not check_password(current, user.password_hash): err = "Your current password is not right."
    err = err or password_problem(password, user.email, user.name) or ("The two new passwords are not the same." if password != password2 else "")
    if err: return render(req, "profile.html", user, pw_error=err)
    user.password_hash = hash_password(password); s.add(user); s.commit()
    req.session["pv"] = pw_stamp(user)   # stay logged in here; every other device is logged out
    return render(req, "profile.html", user, pw_ok=True)

def run_faculty_check(s, u):
    """Look for the user's email on their NTHU page. Found: verified automatically. Not found: an admin decides."""
    found, note = check_page(u.email, u.faculty_url)
    if found and shared_domain(u.email):   # @gapp / @oz / @m<year> can belong to students too, so a person checks it
        found, note = False, "Email found on the page, but it is a shared NTHU address (@gapp, @oz or @m…), so an admin confirms it."
    u.faculty_note = note[:300]
    if found: u.faculty_status, u.is_faculty = "verified", True
    elif u.faculty_status != "rejected": u.faculty_status, u.is_faculty = "pending", False
    s.add(u); s.commit()


@app.post("/logout")
def logout(req: Request): req.session.clear(); return go("/")

@app.get("/lang/{code}")
def set_lang(req: Request, code: str, next: str = "/", s: Session = Depends(get_session)):
    if code not in LANGS: code = "en"
    uid = req.session.get("uid"); u = s.get(User, uid) if uid else None
    if u: u.lang = code; s.add(u); s.commit()
    req.session["lang"] = code
    back = next if next.startswith("/") and not next.startswith("//") and "\\" not in next else "/"
    r = go(back); r.set_cookie("lang", code, max_age=31536000, samesite="lax", secure=PUBLIC); return r

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
    user.skills = ",".join(sorted(tags(skills)))
    for f in ("competitions", "past_projects", "awards"):   # one item per line, at most 10 lines of 200 characters
        lines = [re.sub(r"\s+", " ", l).strip(" -•*")[:200] for l in str(form.get(f, "")).splitlines()]
        setattr(user, f, "\n".join([l for l in lines if l][:10]))
    s.add(user); s.commit()
    return go("/")

@app.post("/profile/cv", dependencies=[limited("cv", 30, 3600)])
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

@app.post("/profile/photo", dependencies=[limited("photo", 30, 3600)])
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

FORMER = "former-member@deleted.invalid"
def former_member(s):
    """One shared placeholder account that deleted people's kept feedback points to. It can never log in."""
    u = s.exec(select(User).where(User.email == FORMER)).first()
    if not u:
        u = User(email=FORMER, handle="former-member", name="Former member", banned=True, email_verified=False, password_hash="")
        s.add(u); s.flush()
    return u

@app.post("/profile/delete")
def delete_account(req: Request, confirm: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    from .docs import purge_project_docs, purge_private_docs_of
    if user and confirm.strip() == "DELETE":
        email = user.email
        for p in s.exec(select(Post).where(Post.author_id == user.id)).all(): purge_post(s, p.id)
        for c in s.exec(select(Comment).where(Comment.author_id == user.id)).all(): c.body = "[deleted]"
        s.exec(delete(Vote).where(Vote.user_id == user.id))
        for pid in [p.id for p in s.exec(select(Project).where(Project.owner_id == user.id))]:
            for r in s.exec(select(Role).where(Role.project_id == pid)):
                for a in s.exec(select(Application).where(Application.role_id == r.id)): s.delete(a)
                s.delete(r)
            purge_project_docs(s, pid)
            s.exec(delete(Remark).where(Remark.project_id == pid)); s.exec(delete(Milestone).where(Milestone.project_id == pid)); s.delete(s.get(Project, pid))
        for a in s.exec(select(Application).where(Application.user_id == user.id)): s.delete(a)
        # Feedback, replies and document versions on other people's projects stay, credited to "Former member",
        # so a team does not lose its advisor's comments or its own files (see the privacy notice).
        purge_private_docs_of(s, user.id)
        gone = former_member(s).id
        for x in s.exec(select(Remark).where(Remark.author_id == user.id)).all(): x.author_id = gone; s.add(x)
        for x in s.exec(select(Remark).where(Remark.last_by == user.id)).all(): x.last_by = gone; s.add(x)
        for x in s.exec(select(Remark).where(Remark.resolved_by == user.id)).all(): x.resolved_by = gone; s.add(x)
        for x in s.exec(select(RemarkEvent).where(RemarkEvent.actor_id == user.id)).all(): x.actor_id = gone; s.add(x)
        for x in s.exec(select(DocVersion).where(DocVersion.uploaded_by == user.id)).all(): x.uploaded_by = gone; s.add(x)
        for x in s.exec(select(ResearchDoc).where(ResearchDoc.created_by == user.id)).all(): x.created_by = gone; s.add(x)
        for x in s.exec(select(ReviewRequest).where(ReviewRequest.requested_by == user.id)).all(): x.requested_by = gone; s.add(x)
        for x in s.exec(select(ReviewRequest).where(ReviewRequest.done_by == user.id)).all(): x.done_by = gone; s.add(x)
        for x in s.exec(select(Milestone).where(Milestone.created_by == user.id)).all(): x.created_by = gone; s.add(x)
        s.exec(delete(Notification).where(Notification.user_id == user.id))
        for o in s.exec(select(Opening).where(Opening.owner_id == user.id)).all():
            s.exec(delete(OpeningApp).where(OpeningApp.opening_id == o.id)); s.delete(o)
        s.exec(delete(OpeningApp).where(OpeningApp.user_id == user.id))
        s.exec(delete(Avatar).where(Avatar.user_id == user.id))
        s.exec(delete(SignupLog).where(SignupLog.email == email)); s.delete(user); s.commit(); req.session.clear()
    return go("/")

@app.get("/u/{handle}")
def public_profile(req: Request, handle: str, reported: str = "", user=Depends(me), s: Session = Depends(get_session)):
    p = s.exec(select(User).where(User.handle == handle)).first()
    if not p or p.banned: raise HTTPException(404)
    # every project this person leads or has joined, with their role in it
    rows = [(pr, "Founder" if kind_of(pr) == "Startup" else "Project lead", False)
            for pr in s.exec(select(Project).where(Project.owner_id == p.id).order_by(Project.created.desc())).all()]
    for a, r, pr in s.exec(select(Application, Role, Project).join(Role, Role.id == Application.role_id).join(Project, Project.id == Role.project_id)
                           .where(Application.user_id == p.id, Application.status == "accepted").order_by(Application.at.desc())).all():
        rows.append((pr, r.name, r.advisor))
    ids = [pr.id for pr, _, _ in rows] or [-1]
    size, open_seats = defaultdict(lambda: 1), defaultdict(int)   # team size counts the lead
    for r in s.exec(select(Role).where(Role.project_id.in_(ids))).all():
        if r.filled and not r.advisor: size[r.project_id] += 1
        if not r.filled: open_seats[r.project_id] += 1
    projects = [dict(p=pr, role=role, advisor=adv, size=size[pr.id], open=open_seats[pr.id], days=days_left(pr.deadline)) for pr, role, adv in rows]
    openings = []
    if p.is_faculty:
        from .advisor import opening_state
        for o in s.exec(select(Opening).where(Opening.owner_id == p.id, Opening.status == "open").order_by(Opening.created.desc())).all():
            st = opening_state(s, o)
            if st["taking"]: openings.append(dict(o=o, **st))
    return render(req, "public.html", user, p=p, skills=sorted(tags(p.skills)), reported=bool(reported), projects=projects, openings=openings,
                  research=[t.strip() for t in p.research.split(",") if t.strip()])

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
        # filtering and sorting happen in the browser (instant, no reload); the page holds every open project
        owner = owners.get(pr.owner_id)
        # no match score on your own project
        best, reason = None, ""
        if user and user.id != pr.owner_id:
            scored = [(match_pct(user, r, pr, owner), r) for r in roles if not r.advisor or user.is_faculty]
            if scored:
                best, br = max(scored, key=lambda x: x[0]); reason = f"{br.name}: {why(user, br, best)}"
        rows.append(dict(p=pr, roles=roles, owner=owner, score=best, total=len(allr), days=days, reason=reason))
    rows.sort(key=lambda r: -(r["score"] or 0))
    # Recommended: only from real overlap between this person's skills and a seat's skills (no score shown without data)
    recs = [r for r in rows if r["score"] and r["score"] >= 40 and r["reason"] and "Shares:" in r["reason"]][:3] if user and user.skills.strip() else []
    soon = {}   # nearest program deadline within 30 days, per project kind
    for prog in s.exec(select(Program).where(Program.active == True)).all():
        d = days_left(prog.next_deadline)
        if d is not None and 0 <= d <= 30 and (prog.for_kind not in soon or d < soon[prog.for_kind][1]): soon[prog.for_kind] = (short_name(prog.name), d)
    allc = s.exec(select(Competition).order_by(Competition.needs_review, Competition.id.desc())).all()
    cats = sorted({c.category for c in allc})
    from .opps import comp_status, saved_ids
    rank = {"closing": 0, "open": 1, "unknown": 2, "past": 3}
    comps = sorted(allc[:300], key=lambda c: (rank[comp_status(c)[0]], comp_status(c)[2] if comp_status(c)[2] is not None else 9999, -c.id))
    return render(req, "board.html", user, recs=recs, depts=sorted({(r["owner"].faculty or "").strip() for r in rows if r["owner"] and (r["owner"].faculty or "").strip()}), rows=rows, comps=comps, saved_c=saved_ids(s, user, "competition"), comp_cat={c.id: c.category for c in allc}, q=q, cat=cat, cats=cats, kind=kind, kinds=PROJECT_KINDS, soon=soon)

RESEARCH_PLAN = [("objectives", 800), ("methodology", 800), ("outcomes", 600)]
PITCH_FIELDS = [("tagline", 140), ("problem", 600), ("audience", 400), ("solution", 600), ("progress", 600), ("needs", 300), ("metrics", 200)]
def metric_rows(text):   # "12 | stall owners interviewed" -> ("12", "stall owners interviewed"), at most 3
    rows = [tuple(x.strip() for x in line.split("|", 1)) for line in text.splitlines() if "|" in line]
    return [(v[:12], l[:60]) for v, l in rows if v and l][:3]
templates.env.globals["metric_rows"] = metric_rows

def short_name(name):   # "U-start Innovation & Startup Program" -> "U-start", for small badges
    n = name.split(" (")[0]
    return n if len(n) <= 16 else n.split()[0]

def team_info(s, pr):
    """Accepted members, advisors and open seats of a project, plus its funding readiness checks."""
    roles = s.exec(select(Role).where(Role.project_id == pr.id).order_by(Role.id)).all()
    acc = s.exec(select(Application, Role).join(Role, Role.id == Application.role_id).where(Role.project_id == pr.id, Application.status == "accepted")).all()
    people = {u.id: u for u in s.exec(select(User).where(User.id.in_([a.user_id for a, _ in acc] or [-1])))}
    members = [(people[a.user_id], r.name) for a, r in acc if not r.advisor and a.user_id in people]
    advisors = [(people[a.user_id], r.name) for a, r in acc if r.advisor and a.user_id in people]
    students = 1 + len([u for u, _ in members if not u.is_faculty])
    k = kind_of(pr); checks = []
    if k in ("Startup", "Research"):
        for prog in s.exec(select(Program).where(Program.active == True, Program.for_kind.in_([k, "Any"])).order_by(Program.sort)).all():
            items = guide.readiness(prog, pr, 1 + len(members), students, len(advisors))
            checks.append(dict(p=prog, lines=items, ready=not any(st == "miss" for st, _, _ in items), days=days_left(prog.next_deadline)))
    return dict(members=members, advisors=advisors, open=[r for r in roles if not r.filled], checks=checks)

def project_form(req, user, s, pr=None, seats=None, error="", **kw):
    kind = kw.get("kind", pr.kind if pr else "")
    sel = kw.get("sel", ("other" if pr.event_name and pr.kind == "Competition" else str(pr.competition_id or "")) if pr else "")
    comps = s.exec(select(Competition).order_by(Competition.title)).all()
    groups = {}   # competitions grouped by category, open ones first within each group
    for c in sorted(comps, key=lambda c: (days_left(c.deadline) is not None and days_left(c.deadline) < 0, c.title.lower())):
        groups.setdefault(c.category or "Other", []).append(c)
    clubs = sorted({n for n in s.exec(select(Project.event_name).where(Project.kind == "Club or event")).all() if n}, key=str.lower)[:200]
    from .docs import uploads_on
    return render(req, "new.html", user, pr=pr, seats=seats or [], error=error, filled=kw.get("filled", []), dup=kw.get("dup"), uploads_on=uploads_on(), kind=kind, kinds=PROJECT_KINDS, sel=sel,
                  today=datetime.utcnow().date().isoformat(), comps=comps, cgroups=sorted(groups.items(), key=lambda g: (g[0] == "Other", g[0])), clubs=clubs, days_left=days_left)

SEAT_FIELDS = ("name", "skills", "about", "must", "nice", "years", "years_in")
def _lines(v, n=8, w=160): return "\n".join([re.sub(r"\s+", " ", l).strip(" -•*")[:w] for l in str(v or "").splitlines() if l.strip()][:n])
def clean_seat(d):
    try: years = max(0, min(int(d.get("years") or 0), 20))
    except (TypeError, ValueError): years = 0
    try: rid = int(d.get("id") or 0) or None
    except (TypeError, ValueError): rid = None
    return dict(id=rid, adv=bool(d.get("adv")), name=re.sub(r"\s+", " ", str(d.get("name", ""))).strip()[:60],
                skills=",".join(t.strip() for t in str(d.get("skills", "")).split(",") if t.strip())[:200],
                about=str(d.get("about", "")).strip()[:600], must=_lines(d.get("must")), nice=_lines(d.get("nice")),
                years=years, years_in=re.sub(r"\s+", " ", str(d.get("years_in", ""))).strip()[:40] if years else "")

def parse_seats(js, legacy=""):
    """Seats come from the form as JSON; the old one-line-per-seat text ("UI designer: figma") still works."""
    import json
    try: raw = json.loads(js) if js.strip() else None
    except ValueError: raw = None
    if not isinstance(raw, list):
        raw = []
        for line in legacy.splitlines():
            m = re.match(r"#(\d+) (.*)", line); rid = int(m.group(1)) if m else None; line = m.group(2) if m else line
            adv = line.startswith("@"); name, _, sk = (line[1:] if adv else line).partition(":")
            raw.append(dict(id=rid, adv=adv, name=name, skills=sk))
    return [x for x in (clean_seat(d) for d in raw[:13] if isinstance(d, dict)) if x["name"]]

def parse_tags(v):
    out = []
    for part in str(v or "").split(","):
        name, _, color = part.partition(":"); name = re.sub(r"\s+", " ", name).strip()[:24]
        if name and name.lower() not in [n.lower() for n, _ in out]:
            out.append((name, color if color in guide.TAG_COLORS else "slate"))
    return out[:6]
def tags_str(v): return ",".join(f"{n}:{c}" for n, c in parse_tags(v))

def parse_links(v):
    import json
    try: raw = json.loads(v) if isinstance(v, str) and v.strip() else (v or [])
    except ValueError: raw = []
    out = []
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict): continue
        url = str(d.get("url", "")).strip()[:300]
        if url and not re.match(r"^https?://", url, re.I): url = "https://" + url
        if not re.match(r"^https?://[^\s/$.?#][^\s]*\.[^\s]+$", url, re.I): continue
        label = re.sub(r"\s+", " ", str(d.get("label", ""))).strip()[:30] or link_label(url)
        out.append(dict(label=label, url=url, team=bool(d.get("team"))))
    return out[:6]
def link_label(url):
    for label, host in guide.LINK_KINDS:
        if host and host in url.lower(): return label
    return "Link"
def link_icon(url):
    u = url.lower()
    for key in ("github", "trello", "notion", "figma", "google", "gitlab", "miro", "canva", "youtube"):
        if key in u: return key
    return "link"
templates.env.globals.update(parse_tags=parse_tags, parse_links=parse_links, link_icon=link_icon)

def seat_dict(r): return dict(id=r.id, adv=r.advisor, **{k: getattr(r, k) for k in SEAT_FIELDS})

def read_project_form(form, pr=None):
    """Check the project form. Returns (fields, seat lines, error)."""
    f = {k: str(form.get(k, "")).strip() for k in ("title", "description", "competition_id", "hours", "deadline", "roles", "kind", "category", "stage")}
    import json
    pitch = {k: str(form.get(k, "")).replace("\r", "").strip()[:n] for k, n in PITCH_FIELDS}
    kind = f["kind"] if f["kind"] in PROJECT_KINDS else "Other"
    seats = parse_seats(str(form.get("roles_json", "")), f["roles"])
    try: hours = int(f["hours"] or 4)
    except ValueError: hours = 0
    err = ""
    if len(f["title"]) < 3: err = "Give the project a title (at least 3 characters)."
    elif not 1 <= hours <= 60: err = "Hours per week must be a number from 1 to 60."
    elif f["deadline"] and days_left(f["deadline"]) is None: err = "The join-by date is not a valid date."
    elif f["deadline"] and days_left(f["deadline"]) < 0 and not (pr and pr.deadline == f["deadline"]): err = "The join-by date is in the past. Pick a future date or leave it empty."
    elif len(seats) > 12: err = "A project can have at most 12 seats."
    other = kind == "Competition" and f["competition_id"] == "other"
    event = re.sub(r"\s+", " ", str(form.get("event_name", ""))).strip()[:120] if other or kind == "Club or event" else ""
    if not err and other and len(event) < 3: err = "You picked Other: type the competition's name."
    cats = guide.STARTUP_CATEGORIES if kind == "Startup" else guide.RESEARCH_FIELDS if kind == "Research" else []
    out = dict(title=f["title"][:120], description=f["description"][:2000], kind=kind, hours_per_week=hours if 1 <= hours <= 60 else 4,
               deadline=f["deadline"][:10], category=f["category"] if f["category"] in cats else "",
               stage=f["stage"] if kind == "Startup" and f["stage"] in [n for n, _ in guide.STARTUP_STAGES] else "",
               competition_id=int(f["competition_id"]) if f["competition_id"].isdigit() and kind == "Competition" else None, event_name=event)
    for k, _ in PITCH_FIELDS: out[k] = pitch[k] if kind == "Startup" else ""
    for k, n in RESEARCH_PLAN: out[k] = str(form.get(k, "")).replace("\r", "").strip()[:n] if kind == "Research" else ""
    out["tags"] = tags_str(form.get("tags", ""))
    out["links"] = json.dumps(parse_links(str(form.get("links_json", ""))), ensure_ascii=False)
    return out, seats, err

@app.get("/projects/new")
def new_project(req: Request, comp: str = "", kind: str = "", user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    kind = kind if kind in PROJECT_KINDS else ("Competition" if comp else "")
    return project_form(req, user, s, kind=kind, sel=comp)

@app.post("/projects/new", dependencies=[limited("newproj", 20, 3600)])
async def create_project(req: Request, user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    form = await req.form()
    f, seats, err = read_project_form(form)
    if not seats and not err: err = "Add at least one open seat, so people know who you need."
    if err:
        draft = Project(owner_id=user.id, **f)
        return project_form(req, user, s, pr=draft, seats=seats, error=err, kind=f["kind"], sel=str(form.get("competition_id", "")) if f["kind"] == "Competition" else "")
    if f.get("competition_id") and not form.get("again"):   # one click too many should not make two teams for the same competition
        dup = s.exec(select(Project).where(Project.owner_id == user.id, Project.competition_id == f["competition_id"])).first()
        if dup:
            draft = Project(owner_id=user.id, **f)
            return project_form(req, user, s, pr=draft, seats=seats, kind=f["kind"], sel=str(f["competition_id"]), dup=dup,
                                error=f"You already lead a team for this competition: {dup.title}. Open it, or press Publish again to make a second team.")
    pr = Project(owner_id=user.id, **f); s.add(pr); s.commit(); s.refresh(pr)
    for x in seats: s.add(Role(project_id=pr.id, advisor=x["adv"], **{k: x[k] for k in SEAT_FIELDS}))
    s.commit()
    up = form.get("first_file")   # optional first research document, uploaded with the project
    if pr.kind == "Research" and getattr(up, "filename", ""):
        from .docs import first_upload
        problem = await first_upload(s, pr, user, up, str(form.get("first_title", "")), str(form.get("first_kind", "Proposal")), str(form.get("first_vis", "team")))
        if problem:
            from urllib.parse import quote
            return go(f"/projects/{pr.id}?err={quote('Project published, but the document was not uploaded: ' + problem)}#docs")
    return go(f"/projects/{pr.id}")

@app.get("/projects/{pid}/edit")
def edit_project(req: Request, pid: int, user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if not pr: raise HTTPException(404)
    if not user or user.id != pr.owner_id: return go(f"/projects/{pid}")
    roles = s.exec(select(Role).where(Role.project_id == pid).order_by(Role.id)).all()
    return project_form(req, user, s, pr=pr, seats=[seat_dict(r) for r in roles if not r.filled], filled=[r for r in roles if r.filled])

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
    keep = {x["id"]: x for x in seats if x["id"]}
    for r in open_roles:   # edited seats keep their applicants; removed seats take their applications with them
        if r.id in keep:
            for k in SEAT_FIELDS: setattr(r, k, keep[r.id][k])
            r.advisor = keep[r.id]["adv"]
        else:
            for a in s.exec(select(Application).where(Application.role_id == r.id)).all(): s.delete(a)
            s.delete(r)
    ids = {r.id for r in open_roles}
    for x in seats:
        if x["id"] not in ids: s.add(Role(project_id=pid, advisor=x["adv"], **{k: x[k] for k in SEAT_FIELDS}))
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
    for r in s.exec(select(Role).where(Role.project_id == pid).order_by(Role.id)):
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
    checks = team_info(s, pr)["checks"]
    my_adv = bool(user and any(x["r"].advisor and a.status == "accepted" and u.id == user.id for x in out for a, u in x["apps"]))
    insider = bool(user and (is_owner or user.is_admin or reveal or my_adv))
    from .advisor import people, supervision, supervised
    sup = supervision(s, pr, user, people(s, pr))
    sup["show"] = supervised(pr, [x["r"] for x in out]) and (sup["sv"]["insider"] or bool(sup["threads"]))
    from .docs import project_docs
    docsec = project_docs(s, pr, user, people(s, pr)) if user and supervised(pr, [x["r"] for x in out]) else None
    if docsec and not docsec["rows"] and not docsec["can_upload"]: docsec = None
    from .opps import saved_ids
    talks = s.exec(select(Post).where(Post.project_id == pid, Post.hidden == False).order_by(Post.created.desc()).limit(5)).all() if user else []
    return render(req, "project.html", user, talks=talks, checks=checks, sup=sup, docsec=docsec, saved=pid in saved_ids(s, user, "project"), err=req.query_params.get("err", "")[:200], insider=insider, accepting=accepting, notice=req.query_params.get("n", ""), pr=pr, owner=owner, is_owner=is_owner, roles=out, reveal=reveal, mytags=tags(user.skills) if user else set(), days=days,
                  comp=s.get(Competition, pr.competition_id) if pr.competition_id else None)

@app.get("/projects/{pid}/onepager")
def onepager(req: Request, pid: int, user=Depends(me), s: Session = Depends(get_session)):
    """Printable one-page summary of a startup, for the team to save as PDF and share."""
    pr = s.get(Project, pid)
    if not pr or kind_of(pr) != "Startup": raise HTTPException(404)
    if not user: return go("/login")
    info = team_info(s, pr)
    if not (user.id == pr.owner_id or user.is_admin or any(u.id == user.id for u, _ in info["members"] + info["advisors"])):
        return go(f"/projects/{pid}")   # only the team can make the one-pager: it lists who is in the team
    import io, qrcode, qrcode.image.svg
    link = f"{BASE_URL}/projects/{pid}"; buf = io.BytesIO()
    qrcode.make(link, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1).save(buf)
    svg = buf.getvalue().decode(); svg = svg[svg.index("<svg"):]
    return tpl(req).TemplateResponse(req, "onepager.html", dict(lang=pick_lang(req), pr=pr, owner=s.get(User, pr.owner_id), link=link, qr=Markup(svg),
                                      today=datetime.utcnow().strftime("%-d %b %Y"), **info))

@app.post("/projects/{pid}/delete")
def delete_project(pid: int, user=Depends(me), s: Session = Depends(get_session)):
    pr = s.get(Project, pid)
    if user and pr and (pr.owner_id == user.id or user.is_admin):
        for r in s.exec(select(Role).where(Role.project_id == pid)).all():
            for a in s.exec(select(Application).where(Application.role_id == r.id)).all(): s.delete(a)
            s.delete(r)
        from .docs import purge_project_docs
        purge_project_docs(s, pid)   # files in storage, versions, review requests, history, notifications
        s.exec(delete(Remark).where(Remark.project_id == pid)); s.exec(delete(Milestone).where(Milestone.project_id == pid)); s.delete(pr); s.commit()
    return go("/")

@app.post("/roles/{rid}/apply", dependencies=[limited("apply", 60, 3600)])
def apply(rid: int, message: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    r = s.get(Role, rid); pr = s.get(Project, r.project_id) if r else None
    if not pr: raise HTTPException(404)
    d = days_left(pr.deadline)
    if r.filled or pr.status != "open" or (d is not None and d < 0): return go(f"/projects/{pr.id}?n=closed")
    if pr.owner_id == user.id: return go(f"/projects/{pr.id}")
    if r.advisor and not user.is_faculty: return go(f"/projects/{pr.id}?n=facultyonly")
    dup = s.exec(select(Application).where(Application.role_id == rid, Application.user_id == user.id)).first()
    if dup and dup.status == "withdrawn": dup.status, dup.message, dup.at = "pending", message.strip()[:500], datetime.utcnow(); s.commit()
    elif not dup: s.add(Application(role_id=rid, user_id=user.id, message=message.strip()[:500])); s.commit()
    else: return go(f"/projects/{pr.id}?n=sent")   # already applied: no duplicate application or notification
    from .notify import notify
    notify(s, [pr.owner_id], "application", f"{user.name or user.handle} applied for the {r.name} seat on {pr.title}", f"/projects/{pr.id}#seats", pr.id, user.id)
    return go(f"/projects/{pr.id}?n=sent")

@app.post("/applications/{aid}/edit", dependencies=[limited("appedit", 60, 3600)])
def edit_application(aid: int, message: str = Form(""), next: str = Form("/activity"), user=Depends(me), s: Session = Depends(get_session)):
    a = s.get(Application, aid)
    if not a: raise HTTPException(404)
    if user and a.user_id == user.id and a.status == "pending": a.message = message.strip()[:500]; s.commit()
    return go((next if next.startswith(("/activity", "/projects/")) else "/activity") + "?n=edited")

@app.post("/applications/{aid}/{decision}")
def decide(aid: int, decision: str, next: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    a = s.get(Application, aid); r = s.get(Role, a.role_id) if a else None; pr = s.get(Project, r.project_id) if r else None
    if not pr: raise HTTPException(404)
    if not user: return go("/login")
    if decision == "withdrawn" and a.user_id == user.id and a.status == "pending":
        a.status = "withdrawn"; s.commit()
        return go("/activity?n=withdrawn" if next == "/activity" else f"/projects/{pr.id}?n=withdrawn")
    if user.id == pr.owner_id and a.status == "accepted" and decision == "removed" and a.user_id != user.id:   # the lead removes a member or advisor
        a.status = "removed"; r.filled = False; s.commit()
        from .notify import notify
        notify(s, [a.user_id], "removed", f"You were removed from the {r.name} seat of {pr.title}", f"/projects/{pr.id}", pr.id, user.id)
        return go(f"/projects/{pr.id}?n=removed#seats")
    if user.id == pr.owner_id and a.status == "pending" and decision in ("accepted", "rejected") and not r.filled:
        a.status = decision
        from .notify import notify
        notify(s, [a.user_id], "app_decision", f"{'You joined' if decision == 'accepted' else 'Your application was not accepted for'} {pr.title}{' as ' + r.name if decision == 'accepted' else ''}", f"/projects/{pr.id}", pr.id, user.id)
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
    from .advisor import waiting_team
    oapps = s.exec(select(OpeningApp, Opening).join(Opening, Opening.id == OpeningApp.opening_id).where(OpeningApp.user_id == user.id).order_by(OpeningApp.at.desc())).all()
    profs = {u.id: u for u in s.exec(select(User).where(User.id.in_({o.owner_id for _, o in oapps} or {-1})))}
    fb = waiting_team(s, user.id)
    fbp = {p.id: p for p in s.exec(select(Project).where(Project.id.in_({t.project_id for t in fb} or {-1})))}
    from .opps import saved_for
    feed = s.exec(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created.desc()).limit(8)).all()
    return render(req, "activity.html", user, feed=feed, saved=saved_for(s, user), mine=mine, pend=pend, seats=seats, sent=sent, days_left=days_left, oapps=oapps, profs=profs, fb=fb, fbp=fbp)

# /funding lives in opps.py (programs + competitions, saved items, tracking)

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
def discuss(req: Request, topic: str = "", sort: str = "hot", q: str = "", show: str = "", user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    qtext = " ".join(q.split())[:80]
    q = select(Post)
    if topic: q = q.where(Post.topic == topic)
    for w in qtext.split()[:6]:   # every word must appear in the title or the text (parameterised, no SQL built from input)
        like = "%" + w.replace("%", "").replace("_", "") + "%"
        q = q.where((Post.title.ilike(like)) | (Post.body.ilike(like)))
    if show == "mine": q = q.where(Post.author_id == user.id)
    elif show == "projects": q = q.where(Post.project_id != None)
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
    projs = {p.id: p for p in s.exec(select(Project).where(Project.id.in_({p.project_id for p in posts if p.project_id} or {-1}))).all()}
    return render(req, "discuss.html", user, posts=posts[:100], tot=tot, mine=mine, cc=cc, authors=authors, topic=topic, sort=sort, topics=TOPICS, q=qtext, show=show, projs=projs)

@app.get("/discuss/new")
def new_post(req: Request, topic: str = "", project: str = "", user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    pr = s.get(Project, int(project)) if project.isdigit() else None
    return render(req, "newpost.html", user, topics=TOPICS, sel=topic, pr=pr)

@app.post("/discuss/new", dependencies=[limited("post", 20, 3600)])
def create_post(req: Request, title: str = Form(...), body: str = Form(""), topic: str = Form("General"), project_id: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if not title.strip(): return go("/discuss/new")
    pr = s.get(Project, int(project_id)) if project_id.isdigit() else None   # project pages are public, so a public discussion about one is fine
    if len(re.findall(r"https?://", title + body)) > 2:
        return render(req, "newpost.html", user, topics=TOPICS, sel=topic, error="Posts can contain at most 2 links.")
    p = Post(author_id=user.id, title=title.strip()[:150], body=body.strip()[:3000], topic=topic if topic in TOPICS else "General", project_id=pr.id if pr else None)
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
    return render(req, "thread.html", user, p=p, flat=flat, ptot=ptot, pmine=pmine, ctot=ctot, cmine=cmine, authors=authors, ncom=len(cs),
                  about=s.get(Project, p.project_id) if p.project_id else None)

@app.post("/discuss/{pid}/comment", dependencies=[limited("comment", 60, 3600)])
def add_comment(pid: int, body: str = Form(...), parent_id: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if len(re.findall(r"https?://", body)) > 2: raise HTTPException(400, "Comments can contain at most 2 links.")
    par = s.get(Comment, int(parent_id)) if parent_id.isdigit() else None
    post = s.get(Post, pid)
    if body.strip() and post and (not post.hidden or user.is_admin):
        par = par if par and par.post_id == pid else None
        s.add(Comment(post_id=pid, author_id=user.id, parent_id=par.id if par else None, body=body.strip()[:2000])); s.commit()
        from .notify import notify   # the post's author and the person replied to (never yourself; merged within 10 minutes)
        name = user.name or user.handle
        if par: notify(s, [par.author_id], "discuss_reply", f"{name} replied to your comment on “{post.title[:60]}”", f"/discuss/{pid}", None, user.id)
        notify(s, [post.author_id] if not par or par.author_id != post.author_id else [], "discuss_comment", f"{name} commented on your post “{post.title[:60]}”", f"/discuss/{pid}", None, user.id)
    return go(f"/discuss/{pid}")

@app.post("/vote/{kind}/{oid}", dependencies=[limited("vote", 300, 3600)])
def vote(kind: str, oid: int, v: int = Form(...), next: str = Form("/discuss"), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    if kind in ("post", "comment") and v in (1, -1):
        ex = s.exec(select(Vote).where(Vote.user_id == user.id, Vote.kind == kind, Vote.target_id == oid)).first()
        if ex and ex.value == v: s.delete(ex)
        elif ex: ex.value = v
        else: s.add(Vote(user_id=user.id, kind=kind, target_id=oid, value=v))
        s.commit()
    return go(next if next.startswith("/discuss") else "/discuss")

@app.post("/flag/{kind}/{oid}", dependencies=[limited("flag", 30, 3600)])
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
    return render(req, "admin.html", user, users=s.exec(select(User)).all(), staff_email=staff_email, flash_link=req.session.pop("flash_link", None),
        fac_requests=s.exec(select(User).where(User.faculty_status == "pending")).all(), programs=s.exec(select(Program).order_by(Program.sort)).all(),
        logs=s.exec(select(SignupLog).order_by(SignupLog.at.desc()).limit(100)).all(),
        review=s.exec(select(Competition).where(Competition.needs_review == True)).all(), storage=storage_info(s), **extra_admin(s))

def storage_info(s):
    from .docs import site_bytes, SITE_CAP
    from .storage import backend
    b = backend()
    return dict(used=site_bytes(s), cap=SITE_CAP, where=b.name if b else "not connected (uploads are off)",
                docs=len(s.exec(select(ResearchDoc.id)).all()), versions=len(s.exec(select(DocVersion.id).where(DocVersion.deleted_at == None)).all()),
                by_project=s.exec(select(Project.id, Project.title, func.count(DocVersion.id), func.coalesce(func.sum(DocVersion.size_bytes), 0))
                                  .join(ResearchDoc, ResearchDoc.project_id == Project.id).join(DocVersion, DocVersion.doc_id == ResearchDoc.id)
                                  .where(DocVersion.deleted_at == None).group_by(Project.id, Project.title).order_by(func.sum(DocVersion.size_bytes).desc()).limit(30)).all(),
                deleted=len(s.exec(select(DocVersion.id).where(DocVersion.deleted_at != None)).all()))

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
    if "next_deadline" in f and f["next_deadline"] != (p.next_deadline or ""):
        p.deadline_source = "admin" if f["next_deadline"] else ""   # a date typed by an admin wins over the daily check
    for k in ("name", "org", "url", "amount", "who", "next_deadline", "deadline_note"):
        if k in f and (f[k] or k in ("next_deadline", "deadline_note")): setattr(p, k, f[k][:300])
    if f.get("for_kind") in ("Startup", "Research", "Any"): p.for_kind = f["for_kind"]
    if "url" in f and f["url"] and not f["url"].startswith("http"): p.url = ""
    p.active = f.get("active") == "on"
    s.commit(); return go("/admin#programs")

@app.post("/admin/{action}/{oid}")
def admin_act(req: Request, action: str, oid: int, user=Depends(me), s: Session = Depends(get_session)):
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
    elif action == "pwlink":   # one-time link the admin copies and sends to someone who cannot log in
        u = s.get(User, oid)
        if u: req.session["flash_link"] = (u.name or u.email, make_link(s, u, "setup", 48)); s.commit(); return go("/admin#users")
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

from . import advisor   # noqa: E402,F401  research supervision, professor dashboard, research positions (registers its routes on app)
from . import notify, docs, opps   # notifications, research documents, competitions and saved items (after advisor: they use its rules)
