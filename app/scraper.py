"""Competition sources. Each source is a small generator registered in SOURCES; run_scrapers() runs them all
(at start-up and every 6 hours) and adds what's new as "not checked by an admin yet".

Taiwan sources:
  * bhuntr   - 獎金獵人 (bhuntr.com), Taiwan's largest competition listing. Read through its public sitemap
               (robots.txt allows crawling and points to it) and the schema.org Event data on each competition page.
               Only competitions open to university students or adults are kept; kids-only ones are skipped.
  * pages    - announcement pages that list competitions as plain links (built-in TW_PAGES, the NTHU_PAGES setting,
               and pages an admin adds on the admin page). Links whose text names a competition are kept.
  * devpost  - hackathons that are online or in Taiwan (in-person events abroad are skipped).
Rule for every source: held in Taiwan, or hosted abroad but entered entirely online.
Deadlines are only stored when a page really states one; otherwise the date shows as "Date not confirmed".
"""
import json, logging, re, time, urllib.robotparser as rp
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup
from sqlmodel import Session, select
from .db import engine
from .models import Competition, SourcePage, ScrapeLog, ScrapeSeen, SavedItem
from .config import NTHU_PAGES
UA = "NTHU-Matchmaker/0.1 (student project; lists competitions for NTHU students)"
HDRS = {"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("scraper")

# Taiwan pages that post competitions for university students as plain HTML links (checked Nov 2026)
TW_PAGES = [
    # NTHU boards that forward competitions to students (robots.txt allows; lists are plain HTML)
    "https://dsa.site.nthu.edu.tw/p/403-1266-6890-1.php?Lang=zh-tw",          # 清大 學務處課外活動組 一般公告
    "https://dcs.site.nthu.edu.tw/p/403-1174-3304-1.php?Lang=zh-tw",          # 清大 資工系 活動競賽 (TSMC CareerHack, company hackathons)
    "https://career-ctm.site.nthu.edu.tw/p/403-1380-4770-1.php?Lang=zh-tw",   # 清大 科管院 職涯
    "https://ene.site.nthu.edu.tw/p/403-1180-3119-1.php?Lang=zh-tw",          # 清大 工科系 公告
    # elsewhere in Taiwan
    "https://activity.sa.ntnu.edu.tw/category/activity/",            # 臺師大 課外活動指導組: 【競賽資訊】 posts from across Taiwan
    "https://www.csie.ntnu.edu.tw/index.php/category/competition/",  # 臺師大 資工系: competitions category
]
PAGE_DETAILS = 15   # new posts opened per board per run, to read the deadline
# a link names a competition if it has one of these words, and none of the words for results, scholarships or reports
KEYWORDS = ["競賽", "比賽", "徵件", "徵稿", "徵選", "黑客松", "挑戰賽", "大賽", "創業", "提案", "選拔", "hackathon", "competition", "contest", "challenge", "pitch", "award"]
NOT = ["獎學金", "榮獲", "獲獎", "得獎", "奪", "恭喜", "賀", "成果", "頒獎", "名單", "結果", "公告得獎", "scholarship", "winners", "congrat"]

def allowed(url: str) -> bool:
    """robots.txt says we may read this page (RFC 9309: no robots.txt (4xx) means allowed; a server error means not now)."""
    p = urlparse(url)
    try: r = httpx.get(f"{p.scheme}://{p.netloc}/robots.txt", headers=HDRS, timeout=15, follow_redirects=True)
    except httpx.HTTPError as e: raise RuntimeError(f"could not reach {p.netloc} ({type(e).__name__})")
    if r.status_code >= 500: return False
    if r.status_code >= 400: return True
    parser = rp.RobotFileParser(); parser.parse(r.text.splitlines())
    return parser.can_fetch(UA, url)

def is_competition(text: str) -> bool:
    t = text.lower()
    return len(text) >= 6 and any(k.lower() in t for k in KEYWORDS) and not any(k.lower() in t for k in NOT)

def get(url, **kw):
    r = httpx.get(url, headers=HDRS, timeout=25, follow_redirects=True, **kw); r.raise_for_status(); return r

# ---------- devpost ----------
TW_PLACE = re.compile(r"taiwan|taipei|hsinchu|taichung|tainan|kaohsiung|taoyuan|台灣|臺灣|台北|臺北|新竹|台中|臺中|台南|臺南|高雄|桃園", re.I)
def devpost_ok(h):
    """Online (location "Online", or "... + Online"), or held in Taiwan; never invite-only."""
    loc = ((h.get("displayed_location") or {}).get("location") or "")
    return not h.get("invite_only") and (bool(re.search(r"\bonline\b", loc, re.I)) or bool(TW_PLACE.search(loc)))
DEVPOST_URLS = set()   # the hackathons that qualified on this run, for pruning older entries
def devpost():
    r = httpx.get("https://devpost.com/api/hackathons", params=[("status[]", "upcoming"), ("status[]", "open")], headers=HDRS, timeout=20)
    DEVPOST_URLS.clear()
    for h in r.json().get("hackathons", []):
        if not devpost_ok(h): continue
        DEVPOST_URLS.add(h["url"])
        loc = ((h.get("displayed_location") or {}).get("location") or "")
        yield dict(title=h["title"], url=h["url"], deadline=h.get("submission_period_dates", ""), online=loc.strip().lower() == "online")

def prune_devpost():
    """Remove scraped Devpost entries that are no longer listed as online/Taiwan (ended, or in person abroad),
    unless an admin verified one or someone saved it."""
    if not DEVPOST_URLS: return 0
    gone = 0
    with Session(engine) as s:
        saved = set(s.exec(select(SavedItem.item_id).where(SavedItem.kind == "competition")).all())
        for c in s.exec(select(Competition).where(Competition.source == "devpost")).all():
            if c.url in DEVPOST_URLS or c.verified_at or c.id in saved: continue
            s.delete(c); gone += 1
        s.commit()
    return gone

# ---------- announcement pages ----------
def pages():
    with Session(engine) as s: db = [p.url for p in s.exec(select(SourcePage).where(SourcePage.active == True)).all()]
    return list(dict.fromkeys(TW_PAGES + list(NTHU_PAGES) + db))

def page_items(page):
    if not allowed(page): raise RuntimeError("robots.txt does not allow reading this page")
    soup = BeautifulSoup(get(page).text, "html.parser")
    own = urlparse(page).netloc.endswith("nthu.edu.tw")   # another school's internal selections aren't open to NTHU students
    with Session(engine) as s:
        listed = set(s.exec(select(Competition.url)).all())
        seen = set(s.exec(select(ScrapeSeen.url)).all())
    opened = 0
    for a in soup.select("a[href]"):
        t = re.sub(r"\s+", " ", a.get_text(" ", strip=True)); url = urljoin(page, a["href"])
        if not is_competition(t) or (not own and re.search(r"系內|校內|院內", t)): continue
        item = dict(title=t[:200], url=url, deadline="", online=bool(re.search(r"[（(]\s*線上\s*[）)]|線上賽|online", t, re.I)))
        if url in listed: yield item; continue   # already listed: nothing to open
        if url in seen: continue                 # looked at before and left out (deadline passed, or a duplicate)
        if opened >= PAGE_DETAILS: continue      # the rest next run
        opened += 1
        try:
            info = post_info(get(url).text)
        except Exception as e:
            log.warning("post %s: %s", url, e); continue
        with Session(engine) as s: s.add(ScrapeSeen(url=url, kept=info is not None)); s.commit()
        if info: yield {**item, **info, "online": item["online"] or info["online"]}

def post_info(html):
    """Deadline and Online tag from an announcement's own page; None when every deadline it states has passed."""
    from .fundscan import page_text, find_deadline, deadline_dates
    text = page_text(html)[:20000]; today = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    d = find_deadline(text, today); dates = deadline_dates(text)
    if not d and dates and all(x < today for x in dates): return None
    return dict(deadline=d.isoformat() if d else "", online=bool(ONLINE_ENTRY.search(text)) and not PHYSICAL.search(text))

# ---------- 獎金獵人 bhuntr ----------
BH_INDEX = "https://bhuntr.com/sitemap_v2.xml"
BH_MAX_AGE = 180         # days: competitions posted earlier than this are almost all closed
BH_PER_RUN = 80          # competition pages opened per run (new ones only), about one a second
YOUNG = ["國小", "國中", "高中", "高職", "幼兒", "兒童", "國高中", "小學生", "中學生"]
GROWN = ["大學", "大專", "研究所", "研究生", "社會人士", "社會組", "不限", "一般民眾", "青年", "成人", "公開組", "全民"]
GROWN_TITLE = ["大學生", "大專", "研究生", "社會人士", "社會組", "社會大眾", "青年", "不限", "全民", "公開組"]
# held in Taiwan: the text names a Taiwan place, body or currency (bhuntr also lists galleries and awards abroad)
TW = re.compile(r"台灣|臺灣|中華民國|新臺幣|新台幣|全國|國內|台北|臺北|新北|桃園|新竹|苗栗|台中|臺中|彰化|南投|雲林|嘉義|台南|臺南|高雄|屏東|宜蘭|花蓮|台東|臺東|基隆|澎湖|金門|馬祖|"
                r"教育部|文化部|經濟部|環境部|數位發展部|交通部|衛生福利部|衛福部|國科會|農業部|勞動部|內政部|客家委員會|原住民族委員會|青年發展署|市政府|縣政府|國立|大專|大學")
ABROAD = re.compile(r"義大利|德國|法國|英國|美國|日本|韓國|波蘭|希臘|保加利亞|西班牙|荷蘭|加拿大|澳洲|阿拉斯加|慕尼黑|邁阿密|阿爾勒|索菲亞|紐約|倫敦|巴黎|pixiv|Gallery", re.I)
SPORT = ["馬拉松", "路跑", "健走", "超馬", "鐵人"]   # races to sign up for, not competitions to build a team for
NOT_CONTEST = ["申請展", "駐村", "駐館",               # exhibition and residency applications
               "教材教法", "教師", "健康促進學校", "輔導團",  # for teachers and schools
               "FITI", "U-start", "大專學生研究計畫"]       # funding programs: they're on the Funding page
# hosted abroad is fine only if it's entered online and nobody has to travel for a round
ONLINE = re.compile(r"線上|網路投稿|online|上傳|電子檔|數位檔|e-?mail|電子郵件|平台提交|投稿平台|提交平台|網站提交|Picter|Zealous", re.I)
# "Online" tag: work is handed in online and no part takes place somewhere (a venue, a final, posting it in)
ONLINE_ENTRY = re.compile(r"線上投稿|線上提交|線上繳交|線上上傳|上傳至|上傳作品|作品上傳|線上賽|線上競賽|線上進行|線上評選|網路投稿|online|電子檔|數位檔|e-?mail投稿|以e-?mail|寄至.{0,30}@|投稿平台|提交平台|Picter|Zealous", re.I)
PHYSICAL = re.compile(r"實體|現場|報到|決賽地點|活動地點|比賽地點|競賽地點|賽事地點|場地|會場|踩街|遊行|郵寄|掛號|親送|郵戳|寄送.{0,6}作品|紙本|面試|簡報.{0,4}答辯|出席")
IN_PERSON = re.compile(r"實體決賽|現場決賽|親自出席|須親臨|現場參賽|須到場|親赴|實體參與|必須出席|現場評選|現場答辯")
OTHER_SCHOOL = re.compile(r"(臺大|台大|政大|成大|陽明交大|交大|師大|中央大學|中興|中山大學|中正大學|東海|輔大|北科大|台科大|臺科大)學生")

def bh_list(xml):
    """(competition page URL, title, publication date) for every competition in a bhuntr sitemap."""
    out = []
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>https://bhuntr\.com/competitions/([a-z0-9]+)</loc>", block)
        if not loc: continue
        title = re.search(r"<news:title><!\[CDATA\[(.*?)\]\]></news:title>", block, re.S)
        pub = re.search(r"<news:publication_date>(\d{4}-\d{2}-\d{2})", block)
        out.append((f"https://bhuntr.com/tw/competitions/{loc.group(1)}", title.group(1).strip() if title else "", pub.group(1) if pub else ""))
    return out

def bh_sitemaps(index_xml, today):
    """This year's competition sitemap (and last year's in January), then the 'latest' one."""
    locs = re.findall(r"<loc>([^<]+)</loc>", index_xml)
    want = [f"_contest_{today.year}.xml"] + ([f"_contest_{today.year - 1}.xml"] if today.month == 1 else []) + ["_contest_latest.xml"]
    return [u for w in want for u in locs if u.endswith(w)]

def bh_event(html):
    """The schema.org Event on a competition page, or None."""
    for tag in BeautifulSoup(html, "html.parser").select('script[type="application/ld+json"]'):
        try: data = json.loads(tag.string or "")
        except Exception: continue
        for x in (data.get("@graph", [data]) if isinstance(data, dict) else data):
            if isinstance(x, dict) and x.get("@type") == "Event": return x
    return None

def bh_item(url, ev, now=None):
    """Turn a bhuntr Event into a Competition row, or None to skip it (kids only, or already closed).
    The deadline comes only from the description ("報名截止：2026/12/21"). The Event's endDate is the end of the
    whole event (or, often, just the time of the request), so it's used only to drop competitions that are over."""
    from .fundscan import find_deadline, deadline_dates
    now = now or datetime.now(timezone.utc); today = (now + timedelta(hours=8)).date()
    name = (ev.get("name") or "").strip(); kw = ev.get("keywords") or ""; desc = re.sub(r"\s+", " ", ev.get("description") or "").strip()
    # for school children only: a school level in the tags or title, and nothing that opens it to university students or
    # adults (in the title only words for people count: "清華大學" as an organiser doesn't make a camp open to students)
    if any(y in f"{kw} {name}" for y in YOUNG) and not (any(g in kw for g in GROWN) or any(g in name for g in GROWN_TITLE)): return None
    if any(x in f"{name} {kw}" for x in SPORT): return None
    if OTHER_SCHOOL.search(name): return None                                    # only for another university's students
    if any(x in name for x in NOT_CONTEST): return None
    abroad = bool(ABROAD.search(name)) or not TW.search(f"{name} {kw} {desc}")
    if abroad and (not ONLINE.search(f"{kw} {desc}") or IN_PERSON.search(desc)): return None   # abroad and not entered online
    end = ev.get("endDate") or ""
    try:
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if e.tzinfo is None: e = e.replace(tzinfo=timezone.utc)
        if abs((e - now).total_seconds()) > 3 * 3600 and e < now: return None   # the whole event is over
    except ValueError: pass
    d = find_deadline(desc, today)
    if not d and any(deadline_dates(desc)) and all(x < today for x in deadline_dates(desc)): return None   # every deadline it states has passed
    deadline = d.isoformat() if d else ""
    text = f"{kw} {desc}"
    online = bool(ONLINE_ENTRY.search(text)) and not PHYSICAL.search(text)
    c = categorize(name)   # the title says what it's about; bhuntr's tags are broad, so they only fill in when the title doesn't
    return dict(title=name[:200], url=url, deadline=deadline, description=desc[:300], category=c if c != "Other" else categorize(kw), online=online)

def bh_recheck(limit=BH_PER_RUN):
    """Set the Online tag on bhuntr competitions saved before it existed: open each page once more."""
    with Session(engine) as s:
        rows = s.exec(select(Competition).where(Competition.source == "bhuntr", Competition.online_checked == False).limit(limit)).all()
        for c in rows:
            try:
                ev = bh_event(get(c.url).text)
                if ev:
                    desc = re.sub(r"\s+", " ", ev.get("description") or ""); text = f"{ev.get('keywords') or ''} {desc}"
                    c.online = bool(ONLINE_ENTRY.search(text)) and not PHYSICAL.search(text)
                c.online_checked = True; s.add(c); s.commit()
            except Exception as e: log.warning("bhuntr recheck %s: %s", c.url, e)
            time.sleep(1)

def bhuntr():
    if not allowed(BH_INDEX): raise RuntimeError("robots.txt does not allow reading the sitemap")
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date(); oldest = (today - timedelta(days=BH_MAX_AGE)).isoformat()
    listed = {}
    for sm in bh_sitemaps(get(BH_INDEX).text, today):
        for u, t, pub in bh_list(get(sm).text): listed.setdefault(u, (t, pub))
    with Session(engine) as s:
        seen = set(s.exec(select(ScrapeSeen.url)).all())
        have = set(s.exec(select(Competition.url)).all())
    fresh = sorted(((pub, u) for u, (t, pub) in listed.items() if pub >= oldest and u not in seen and u not in have), reverse=True)   # newest first
    bh_recheck()
    for pub, u in fresh[:BH_PER_RUN]:
        item = None
        try:
            ev = bh_event(get(u).text)
            if ev: item = bh_item(u, ev)
        except Exception as e:
            log.warning("bhuntr %s: %s", u, e); continue   # try again next run
        with Session(engine) as s: s.add(ScrapeSeen(url=u, kept=item is not None)); s.commit()
        if item: yield item
        time.sleep(1)

# first match wins; English words match whole words only ("art" isn't in "smart")
CATS = [("Tech & Data", ["hackathon", "ai", "data", "code", "coding", "software", "robot", "robotics", "app", "黑客松", "程式", "編程", "人工智慧", "資料", "數據", "資訊", "資通", "半導體", "機器人", "無人機", "量子", "軟體", "電腦", "ai創新", "大數據"]),
        ("Law & Policy", ["law", "moot", "policy", "法律", "法學", "政策", "模擬法庭", "法創"]),
        ("Science & Health", ["bio", "health", "science", "chem", "climate", "醫", "科學", "環境", "健康", "長照", "天文", "生醫"]),
        ("Design & Arts", ["design", "art", "arts", "film", "photo", "photography", "music", "設計", "藝術", "影片", "影像", "短片", "微電影", "攝影", "迷因", "梗圖", "繪畫", "插畫", "文學", "寫作", "徵文", "音樂", "動畫", "漫畫", "書法", "詩", "建築", "播客", "短影音"]),
        ("Business", ["startup", "business", "pitch", "entrepreneur", "finance", "marketing", "創業", "創新", "行銷", "商業", "金融", "個案", "經營", "募資"]),
        ("Social Impact", ["social", "sdg", "sustainability", "impact", "永續", "公益", "社會創新", "志工", "環保", "關懷"])]
def categorize(title: str) -> str:
    t = title.lower()
    def hit(k): return re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", t) if k.isascii() else k in t
    return next((c for c, ks in CATS if any(hit(k) for k in ks)), "Other")

SOURCES = {"bhuntr": bhuntr, "devpost": devpost}

def _note(name, count, error=""):
    with Session(engine) as s: s.add(ScrapeLog(source=name, count=count, error=error[:200])); s.commit()

def _norm(t): return re.sub(r"[\s\W_]+", "", (t or "").lower())

def _save(name, items):
    new = 0
    with Session(engine) as s:
        titles = {_norm(t) for t in s.exec(select(Competition.title)).all()}
        for it in items:
            if not it.get("title"): continue
            old = s.exec(select(Competition).where(Competition.url == it["url"])).first()
            if old:
                if "online" in it and old.source == name and not old.verified_at: old.online, old.online_checked = it["online"], True; s.add(old)
                continue
            if _norm(it["title"]) in titles: continue
            it.setdefault("category", categorize(it["title"]))
            s.add(Competition(source=name, online_checked="online" in it, **it)); titles.add(_norm(it["title"])); new += 1
        s.commit()
    return new

def prune_titles():
    """Apply the title rules to entries already saved from scraped sources (rules can get stricter over time),
    unless an admin verified one or someone saved it."""
    gone = 0
    with Session(engine) as s:
        saved = set(s.exec(select(SavedItem.item_id).where(SavedItem.kind == "competition")).all())
        for c in s.exec(select(Competition).where((Competition.source == "bhuntr") | Competition.source.like("page:%"))).all():
            if c.verified_at or c.id in saved: continue
            t = c.title
            kids = c.source == "bhuntr" and any(y in t for y in YOUNG) and not any(g in t for g in GROWN_TITLE)
            bad = kids or any(x in t for x in SPORT + NOT_CONTEST) or bool(OTHER_SCHOOL.search(t)) or (c.source.startswith("page:") and "nthu.edu.tw" not in c.source and re.search(r"系內|校內|院內", t))
            if bad: s.delete(c); gone += 1
            else:
                k = categorize(c.title); c.category = k if k != "Other" else categorize(c.description[:300]); s.add(c)   # keep categories in step with the rules
        s.commit()
    return gone

def run_scrapers():
    try:
        n = prune_titles()
        if n: log.info("removed %d saved entries that no longer pass the rules", n)
    except Exception as e: log.error("prune failed: %s", e)
    jobs = list(SOURCES.items()) + [(f"page:{urlparse(p).netloc}", (lambda p=p: page_items(p))) for p in pages()]
    for name, fn in jobs:
        try: items = list(fn())
        except Exception as e: log.error("source %s failed: %s", name, e); _note(name, 0, f"{type(e).__name__}: {e}"); continue
        new = _save(name, items)
        if name == "devpost":
            gone = prune_devpost()
            if gone: log.info("devpost: removed %d entries that are not online or in Taiwan", gone)
        # bhuntr opens only pages it hasn't seen, so 0 new is normal once it has caught up
        if not items and name != "bhuntr": log.warning("source %s returned 0 items", name); _note(name, 0, "returned 0 items (blocked, empty, or layout changed)"); continue
        _note(name, new); log.info("source %s: %d items, %d new", name, len(items), new)
