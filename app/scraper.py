"""Each source is a small generator; add a function and register it in SOURCES."""
import logging, urllib.robotparser as rp
from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup
from sqlmodel import Session, select
from .db import engine
from .models import Competition, SourcePage, ScrapeLog
from .config import NTHU_PAGES, KEYWORDS
UA = "NTHU-Matchmaker/0.1 (student project)"
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("scraper")

def allowed(url: str) -> bool:
    p = urlparse(url); r = rp.RobotFileParser(f"{p.scheme}://{p.netloc}/robots.txt")
    try: r.read()
    except Exception: return False
    return r.can_fetch(UA, url)

def devpost():
    r = httpx.get("https://devpost.com/api/hackathons", params={"status[]": "upcoming"},
                  headers={"User-Agent": UA}, timeout=20)
    for h in r.json().get("hackathons", []):
        yield dict(title=h["title"], url=h["url"], deadline=h.get("submission_period_dates", ""))

def pages():
    with Session(engine) as s: db = [p.url for p in s.exec(select(SourcePage).where(SourcePage.active == True)).all()]
    return list(dict.fromkeys(list(NTHU_PAGES) + db))

def nthu_pages():
    for page in pages():
        if not allowed(page): log.warning("robots.txt blocks %s", page); continue
        soup = BeautifulSoup(httpx.get(page, headers={"User-Agent": UA}, timeout=20).text, "html.parser")
        for a in soup.select("a[href]"):
            t = a.get_text(strip=True)
            if t and any(k.lower() in t.lower() for k in KEYWORDS):
                yield dict(title=t, url=urljoin(page, a["href"]), deadline="")

CATS = [("Social Impact", ["social", "sdg", "sustainab", "永續", "公益", "impact"]),
        ("Law & Policy", ["law", "moot", "policy", "法律", "法學", "政策"]),
        ("Design & Arts", ["design", "設計", "art", "藝術", "film", "photo", "music"]),
        ("Science & Health", ["bio", "health", "science", "醫", "科學", "chem", "climate", "環境"]),
        ("Business", ["startup", "business", "pitch", "創業", "創新", "entrepreneur", "finance", "marketing"]),
        ("Tech & Data", ["hackathon", "ai ", "data", "code", "黑客松", "程式", "software", "robot"])]
def categorize(title: str) -> str:
    t = title.lower()
    return next((c for c, ks in CATS if any(k in t for k in ks)), "Other")

SOURCES = {"devpost": devpost, "nthu": nthu_pages}

def _note(name, count, error=""):
    with Session(engine) as s: s.add(ScrapeLog(source=name, count=count, error=error[:200])); s.commit()

def run_scrapers():
    for name, fn in SOURCES.items():
        if name == "nthu" and not pages(): _note(name, 0, "no pages configured: add one on the admin page"); continue
        try: items = list(fn())
        except Exception as e: log.error("source %s failed: %s", name, e); _note(name, 0, str(e)); continue
        if not items: log.warning("source %s returned 0 items", name); _note(name, 0, "returned 0 items (blocked, empty, or layout changed)"); continue
        new = 0
        with Session(engine) as s:
            for it in items:
                if not s.exec(select(Competition).where(Competition.url == it["url"])).first():
                    s.add(Competition(source=name, category=categorize(it["title"]), **it)); new += 1
            s.commit()
        _note(name, new); log.info("source %s: %d items, %d new", name, len(items), new)
