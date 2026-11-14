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
KEYWORDS = r"(截止|收件|申請期間|申請時間|報名期間|報名時間|報名截止|徵件期間|徵件時間|受理|deadline|due date|apply by|applications? close|closing date|submission)"
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_PATTERNS = [
    (re.compile(r"(20\d\d)\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"(?<![\d-])(1[01]\d)\s*[年/.-]\s*(\d{1,2})\s*[月/.-]\s*(\d{1,2})"), lambda m: (int(m[1]) + 1911, int(m[2]), int(m[3]))),   # ROC year, e.g. 115年11月30日, 115-12-15
    (re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d\d)", re.I), lambda m: (int(m[3]), MONTHS[m[1][:3].lower()], int(m[2]))),
    (re.compile(r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(20\d\d)", re.I), lambda m: (int(m[3]), MONTHS[m[2][:3].lower()], int(m[1]))),
]

# A deadline is only taken when the program's own name stands right before the deadline word. Several official URLs are
# an agency's home page full of other news, so a date next to "截止" alone could belong to anything.
# Programs with no terms here (open all year, or no reliable page) are checked for reachability only.
NAME_TERMS = {"ustart": ["U-start", "創新創業計畫"], "fiti": ["FITI", "創新創業激勵計畫"], "nstc": ["大專學生研究計畫", "大專生研究計畫"],
              "appworks": ["AppWorks Accelerator", "AW#"], "sinica-summer": ["暑期大專生", "暑期研習"], "macronix": ["金矽獎", "Golden Silicon"]}

def today_tw():
    return datetime.now(timezone(timedelta(hours=8))).date()

def page_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "nav", "footer", "header"]): t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()

SEP = re.compile(r"\s*日?\s*(?:[（(][^）)]{1,3}[）)])?\s*(\d{1,2}:\d{2})?\s*(起至|至|到|~|～|–|—|-|to|through|until)\s*", re.I)   # "28日（一）10:00 至 "
MD = re.compile(r"(\d{1,2})\s*[月/]\s*(\d{1,2})\s*日?")   # "11月17日" / "11/17": a period's end that leaves out the year

def _scan(text, terms=None):
    """Every date written right after a deadline word. A period ("9月28日至11月17日", "2026/10/01 - 2026/11/30")
    counts by its end; any other later date in the window (a demo day, an event) is ignored."""
    text = text.replace("\u2011", "-").replace("\uff0d", "-").replace("\uff5e", "~")
    for k in re.finditer(KEYWORDS, text, re.I):
        if terms is not None and not any(t.lower() in text[max(0, k.start() - 150):k.start()].lower() for t in terms): continue
        window = text[k.end():k.end() + 80]
        hits = sorted((m.start(), m.end(), parts(m)) for rx, parts in DATE_PATTERNS for m in rx.finditer(window))
        if not hits: continue
        first = hits[0]; pick = first[2]
        nxt = [h for h in hits[1:] if h[0] >= first[1]]
        sep = SEP.match(window, first[1])
        if sep and nxt and nxt[0][0] == sep.end(): pick = nxt[0][2]
        elif sep:   # the end of the period without a year: same year, or the next one if it comes before the start
            md = MD.match(window, sep.end())
            if md:
                y = first[2][0]; m, d = int(md.group(1)), int(md.group(2))
                pick = (y + 1 if (m, d) < first[2][1:] else y, m, d)
        try: yield date(*pick)
        except (ValueError, KeyError, TypeError): continue

def find_deadline(text, today=None, terms=None):
    """The deadline written after a deadline word (a period counts by its last date); the soonest future one, or None."""
    today = today or today_tw()
    found = [d for d in _scan(text, terms) if today <= d <= today + timedelta(days=400)]
    return min(found) if found else None

def deadline_dates(text):
    """Every date written right after a deadline word, past or future."""
    return list(_scan(text))

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
    terms = NAME_TERMS.get(p.key)
    d = find_deadline(text, today, terms) if terms else None
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
