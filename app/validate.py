"""Input rules shared by the server and the pages (the pages get the word lists through `client_data()`).

Every rule here is enforced on the server; the browser only repeats them to give quicker feedback.
Nothing in this module changes what a person typed except trimming spaces: suggestions are offered, never applied.
"""
import re, unicodedata
from datetime import date, datetime
from urllib.parse import urlparse

# ---------- names ----------
NAME_MAX = 60
NAME_PUNCT = set(" -'’.·")   # spaces, hyphens, apostrophes, and the dot / middle dot used in some transliterated names

def name_problem(name: str) -> str:
    """"" if the name is fine. Letters from any script count (Latin, 中文, accented, ...); digits, symbols and emoji do not."""
    name = " ".join((name or "").split())
    if len(name) > NAME_MAX: return f"Your name can be at most {NAME_MAX} characters."
    letters = 0
    for ch in name:
        if ch.isalpha(): letters += 1
        elif unicodedata.category(ch).startswith("M") or ch in NAME_PUNCT: continue   # accents written as separate marks
        elif ch.isdigit(): return "Names can't contain numbers."
        else: return "Use only letters, spaces, hyphens (-) and apostrophes (') in your name."
    if letters < 2: return "Please enter your full name (at least 2 letters)."
    return ""

# ---------- skills ----------
MAX_SKILLS, MAX_SKILL_LEN = 20, 30
SPLIT = re.compile(r"[,，、;；\n]")

def split_skills(text: str) -> list[str]:
    """Comma-separated (also Chinese commas), spaces trimmed, duplicates dropped ignoring case, order kept."""
    out, seen = [], set()
    for part in SPLIT.split(text or ""):
        t = re.sub(r"\s+", " ", part).strip()
        if t and t.lower() not in seen: seen.add(t.lower()); out.append(t)
    return out

def skills_problem(items: list[str], limit: int = MAX_SKILLS) -> str:
    long = [t for t in items if len(t) > MAX_SKILL_LEN]
    if long: return f"Each skill can be at most {MAX_SKILL_LEN} characters (“{long[0][:40]}” is longer)."
    if len(items) > limit: return f"Add at most {limit} skills (you have {len(items)})."
    return ""

MAX_INTERESTS, MAX_ROLES, MAX_TAG_LEN = 10, 5, 40
def list_problem(items: list[str], limit: int, what: str) -> str:
    """Interests or roles wanted: at most `limit` items of MAX_TAG_LEN characters."""
    long = [t for t in items if len(t) > MAX_TAG_LEN]
    if long: return f"Each item in {what} can be at most {MAX_TAG_LEN} characters (“{long[0][:40]}” is longer)."
    if len(items) > limit: return f"Add at most {limit} items to {what} (you have {len(items)})."
    return ""

# Canonical spellings we can suggest. Custom skills are always allowed; this list only powers "Did you mean ...?".
CANON = ["Python", "JavaScript", "TypeScript", "HTML", "CSS", "Java", "C", "C++", "C#", "Go", "Rust", "Kotlin", "Swift", "PHP", "Ruby", "R", "MATLAB",
         "SQL", "PostgreSQL", "MySQL", "MongoDB", "React", "Vue", "Angular", "Node.js", "Django", "Flask", "FastAPI", "Flutter", "React Native",
         "Git", "GitHub", "Docker", "Kubernetes", "Linux", "AWS", "Firebase", "TensorFlow", "PyTorch", "scikit-learn", "pandas", "NumPy", "OpenCV",
         "Machine learning", "Deep learning", "Data analysis", "Data visualization", "Statistics", "Excel", "Tableau", "Power BI", "SPSS",
         "Figma", "UI design", "UX research", "User research", "Graphic design", "Illustrator", "Photoshop", "Premiere Pro", "After Effects",
         "Video editing", "Branding", "Marketing", "Social media", "Copywriting", "Public speaking", "Pitching", "Business plan",
         "Financial modeling", "Market research", "Project management", "Arduino", "Raspberry Pi", "Unity", "Blender", "AutoCAD", "SolidWorks",
         "Embedded systems", "Circuit design", "PCB design", "Signal processing", "Web scraping", "REST API", "Writing", "Translation", "Research"]
CANON_BY_KEY = {c.lower(): c for c in CANON}
KNOWN_TYPOS = {"phyton": "Python", "pyhton": "Python", "pyton": "Python", "pythn": "Python", "javasript": "JavaScript", "javascirpt": "JavaScript",
               "javscript": "JavaScript", "java script": "JavaScript", "htlm": "HTML", "hmtl": "HTML", "typescirpt": "TypeScript", "sqll": "SQL",
               "figam": "Figma", "fgma": "Figma", "photshop": "Photoshop", "photoshp": "Photoshop", "excell": "Excel", "pytorh": "PyTorch",
               "tensorflwo": "TensorFlow", "githbu": "GitHub", "dokcer": "Docker", "nodejs": "Node.js", "node js": "Node.js", "reactjs": "React"}

def edit_distance(a: str, b: str) -> int:
    """Damerau-Levenshtein distance (a swap of two neighbours counts as one edit). The pages use the same algorithm."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1): d[i][0] = i
    for j in range(len(b) + 1): d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]: d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]

def skill_suggestion(skill: str) -> str:
    """A likely intended spelling, or "" when the skill is already a known one or nothing is close enough."""
    k = (skill or "").strip().lower()
    if not k or k in CANON_BY_KEY: return ""
    if k in KNOWN_TYPOS: return KNOWN_TYPOS[k]
    if len(k) < 4: return ""
    allow = 1 if len(k) < 6 else 2
    best = min(CANON_BY_KEY, key=lambda c: (edit_distance(k, c), c))
    return CANON_BY_KEY[best] if edit_distance(k, best) <= allow and abs(len(best) - len(k)) <= allow else ""

# ---------- email ----------
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$")

def email_ok(email: str) -> bool:
    email = (email or "").strip()
    return len(email) <= 254 and bool(EMAIL_RE.match(email)) and ".." not in email.split("@")[0] and not email.startswith(".")

EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "yahoo.com.tw", "outlook.com", "hotmail.com", "icloud.com", "live.com", "msn.com",
                 "gapp.nthu.edu.tw", "nthu.edu.tw", "cs.nthu.edu.tw", "ee.nthu.edu.tw"]
FUZZY_DOMAINS = EMAIL_DOMAINS[:8]   # near-misses are only guessed for big mail providers; university domains use the explicit list below
DOMAIN_TYPOS = {"gmial.com": "gmail.com", "gmai.com": "gmail.com", "gamil.com": "gmail.com", "gnail.com": "gmail.com", "gmal.com": "gmail.com",
                "gmail.co": "gmail.com", "gmail.con": "gmail.com", "gmail.cm": "gmail.com", "gmail.om": "gmail.com", "gmaill.com": "gmail.com",
                "yahooo.com": "yahoo.com", "yaho.com": "yahoo.com", "yahoo.con": "yahoo.com", "outlok.com": "outlook.com", "outllok.com": "outlook.com",
                "outlook.con": "outlook.com", "hotmial.com": "hotmail.com", "hotmai.com": "hotmail.com", "hotmail.con": "hotmail.com",
                "iclod.com": "icloud.com", "icloud.con": "icloud.com", "gap.nthu.edu.tw": "gapp.nthu.edu.tw", "gapp.nthu.edu.com": "gapp.nthu.edu.tw"}

def email_suggestion(email: str) -> str:
    """The same address with a commonly mistyped domain corrected, or "" (also "" for NTHU student mail like @m114.nthu.edu.tw)."""
    email = (email or "").strip()
    if email.count("@") != 1: return ""
    local, dom = email.split("@"); d = dom.lower()
    if not local or not d: return ""
    fix = DOMAIN_TYPOS.get(d)
    if not fix and (d in EMAIL_DOMAINS or re.fullmatch(r"[a-z0-9-]+\.nthu\.edu\.tw", d)): return ""   # NTHU department and student mail are fine
    if not fix and not re.search(r"\.(edu|ac|gov)(\.[a-z]{2})?$|\.edu\.tw$", d):   # other universities (ntu.edu.tw...) are real, never "fixed"
        best = min(FUZZY_DOMAINS, key=lambda c: (edit_distance(d, c), c))
        fix = best if 0 < edit_distance(d, best) <= (1 if len(d) < 8 else 2) else ""
    return f"{local}@{fix}" if fix else ""

# ---------- social handles ----------
def _strip_handle(v: str) -> str:
    v = (v or "").strip()
    v = re.sub(r"^https?://(www\.)?(instagram\.com|line\.me/ti/p|discord(app)?\.com/users)/", "", v, flags=re.I).strip("/")
    return v.lstrip("@~").strip()

def handle_problem(kind: str, value: str):
    """Returns (clean value, problem). Passing these rules doesn't mean the account exists; we never claim that."""
    v = _strip_handle(value)
    if not v: return "", ""
    if kind == "instagram":
        ok = re.fullmatch(r"[A-Za-z0-9._]{1,30}", v) and not v.startswith(".") and not v.endswith(".") and ".." not in v
        return v, "" if ok else "Instagram usernames are 1–30 letters, numbers, periods (.) or underscores (_), and can't start or end with a period."
    if kind == "line":
        v = v.lower()   # LINE IDs are lowercase; typing capitals is harmless
        ok = re.fullmatch(r"[a-z0-9._-]{4,20}", v)
        return v, "" if ok else "A LINE ID is 4–20 lowercase letters, numbers, periods (.), hyphens (-) or underscores (_). Use your LINE ID, not your display name."
    if kind == "discord":
        v = v.lower()
        ok = re.fullmatch(r"[a-z0-9._]{2,32}", v) and ".." not in v
        return v, "" if ok else "Discord usernames are 2–32 lowercase letters, numbers, periods (.) or underscores (_), with no two periods in a row."
    return v, ""

# ---------- long text ----------
def normalize_text(v: str) -> str:
    """Browsers count a line break as one character but send two; count like the browser does."""
    return (v or "").replace("\r\n", "\n").replace("\r", "\n").strip()

NOTE_MIN, NOTE_MAX = 20, 1000
BIO_MAX = 500
DESC_MIN, DESC_MAX = 30, 2000

def length_problem(text: str, lo: int, hi: int, what: str) -> str:
    n = len(text)
    if lo and n < lo: return f"{what} needs at least {lo} characters (you have {n})."
    if n > hi: return f"{what} can be at most {hi} characters (you have {n})."
    return ""

# ---------- links and dates ----------
HOST = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")

def https_url_problem(url: str) -> str:
    url = (url or "").strip()
    if not url: return "Add the competition's link."
    if any(c.isspace() for c in url): return "The link can't contain spaces."
    try: p = urlparse(url); host = (p.hostname or "").lower(); port = p.port
    except ValueError: return "That link isn't a valid web address."
    if p.scheme != "https": return "Use a secure link that starts with https://."
    if p.username or p.password: return "The link can't contain a username or password."
    if not HOST.fullmatch(host): return "That link isn't a valid web address."
    return ""

def parse_date(v: str):
    try: return datetime.strptime((v or "").strip(), "%Y-%m-%d").date()
    except ValueError: return None

LABELS = {
    "en": dict(count="{n} / {max}", need="at least {min}", mean="Did you mean {x}?", use="Use {x}", use_email="Use suggestion", keep="Keep original",
               too_many="At most {max} skills: remove {extra}.", too_long="“{x}” is too long (at most {max} characters)."),
    "zh": dict(count="{n} / {max}", need="至少 {min} 個字", mean="你是不是要輸入 {x}？", use="改成 {x}", use_email="使用建議", keep="保留原本的",
               too_many="最多 {max} 個技能：請刪除 {extra} 個。", too_long="「{x}」太長了（最多 {max} 個字）。"),
}

def client_data(lang: str = "en") -> dict:
    """What the pages need to repeat these rules in the browser (word lists and the messages in the page's language)."""
    return dict(canon=CANON, typos=KNOWN_TYPOS, domains=FUZZY_DOMAINS, known_domains=EMAIL_DOMAINS, domain_typos=DOMAIN_TYPOS,
                max_skills=MAX_SKILLS, max_skill_len=MAX_SKILL_LEN, t=LABELS["zh" if lang == "zh" else "en"])
