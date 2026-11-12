"""Daily automatic check of every funding program's official page.

For each program we open its official URL and:
  * record when it was checked and whether the page could be read;
  * notice when the page's text changed since the last check;
  * look for a deadline written next to a deadline word (截止, 收件, 申請期間, deadline, apply by...).
    Only a future date found that way is used; if the page shows none, the deadline stays as it was.
A date an admin typed in by hand is never overwritten by the checker.
"""
import hashlib, logging, re
from datetime import date, datetime, timedelta, timezone
import httpx
from bs4 import BeautifulSoup
from sqlmodel import Session, select
from .db import engine
from .models import Program

log = logging.getLogger("fundscan")
UA = "NTHU-Matchmaker/0.1 (student project; checks public program pages once a day)"
KEYWORDS = r"(截止|收件|申請期間|申請時間|報名期間|報名截止|徵件期間|受理|deadline|due date|apply by|applications? close|closing date|submission)"
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_PATTERNS = [
    (re.compile(r"(20\d\d)\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"(?<!\d)(1[01]\d)\s*[年/.]\s*(\d{1,2})\s*[月/.]\s*(\d{1,2})"), lambda m: (int(m[1]) + 1911, int(m[2]), int(m[3]))),   # ROC year, e.g. 115年11月30日
    (re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d\d)", re.I), lambda m: (int(m[3]), MONTHS[m[1][:3].lower()], int(m[2]))),
    (re.compile(r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(20\d\d)", re.I), lambda m: (int(m[3]), MONTHS[m[2][:3].lower()], int(m[1]))),
]

def today_tw():
    return datetime.now(timezone(timedelta(hours=8))).date()

def page_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "nav", "footer", "header"]): t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()

def find_deadline(text, today=None):
    """The deadline written after a deadline word (a period counts by its last date); the soonest future one, or None."""
    today = today or today_tw(); found = []
    for k in re.finditer(KEYWORDS, text, re.I):
        window, near = text[k.end():k.end() + 80], []
        for rx, parts in DATE_PATTERNS:
            for m in rx.finditer(window):
                try: near.append(date(*parts(m)))
                except (ValueError, KeyError): continue
        if near:
            end = max(near)   # "申請期間 12月1日至1月15日": a period ends on its last date
            if today <= end <= today + timedelta(days=400): found.append(end)
    return min(found) if found else None

def check_program(p, client, today=None):
    """Check one program in place. Returns a short note for the log."""
    now = datetime.utcnow()
    try:
        r = client.get(p.url, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}, timeout=25, follow_redirects=True)
        if r.status_code >= 400: raise httpx.HTTPError(f"HTTP {r.status_code}")
        text = page_text(r.text[:3_000_000])
    except Exception as e:
        p.check_status, p.check_note, p.checked_at = "unreachable", f"Could not open the official page ({type(e).__name__}).", now
        return "unreachable"
    h = hashlib.sha256(text.encode()).hexdigest()
    changed = bool(p.page_hash) and h != p.page_hash
    p.page_hash, p.checked_at = h, now
    d = find_deadline(text, today)
    if d and p.deadline_source != "admin":
        p.next_deadline, p.deadline_source = d.isoformat(), "auto"
        p.check_status, p.check_note = "ok", "Deadline read from the official page."
        return f"deadline {d}"
    if p.deadline_source == "auto" and p.next_deadline and date.fromisoformat(p.next_deadline) < (today or today_tw()):
        p.next_deadline = ""   # the date we read earlier has passed and the page shows no new one
    p.check_status = "changed" if changed else "ok"
    p.check_note = "The page changed since the last check, but no deadline was written on it." if changed else "Page checked; no deadline written on it yet."
    return p.check_status

def run(transport=None):
    with Session(engine) as s, httpx.Client(transport=transport) as client:
        for p in s.exec(select(Program).where(Program.active == True)).all():
            if not p.url.startswith(("http://", "https://")): continue
            note = check_program(p, client); s.add(p); s.commit()
            log.info("program %s: %s", p.key, note)
