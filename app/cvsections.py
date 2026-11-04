"""Find competitions, projects and awards in CV text. Simple rules, no cloud AI; the student checks the result before saving."""
import re

SEC_KIND = [  # (kind, header words), checked on short lines only
    ("competitions", re.compile(r"^(competitions?|competition experience|contests?|hackathons?|olympiads?|競賽|比賽)\b", re.I)),
    ("awards", re.compile(r"^(awards?|honou?rs?|achievements?|accomplishments?|awards?\s*(?:&|and)\s*honou?rs?|honou?rs?\s*(?:&|and)\s*awards?|獲獎|榮譽|得獎)", re.I)),
    ("projects", re.compile(r"^((?:selected |personal |academic |side |key )?projects?(?:\s*(?:/|&|and)\s*[a-z]+)?|portfolio|專案|專題|作品)\b", re.I)),
]
ANY_HDR = re.compile(r"^(education|experience|work experience|employment|skills?|technical skills|languages?|leadership|activities|extracurriculars?|"
                     r"volunteer(?:ing)?|certifications?|publications|references|interests|profile|summary|about|contact|at a glance|"
                     r"personality|computer skills|coursework|學歷|經歷|技能|自傳)\b", re.I)
AWARD_START = re.compile(r"^(?:[•▪●\-*–]\s*)?(gold|silver|bronze|champion|winner|finalist|semi-?finalist|honou?rable|best|top\s*\d+|first|second|third|"
                         r"\d+(?:st|nd|rd|th)\b|grand prize|merit|distinction|scholarship|dean|online|national|international|regional)", re.I)
COMP_WORDS = re.compile(r"competition|olympiad|olimpiade|hackathon|contest|challenge|\bcup\b|isqo|osn|ksn|case study|pitch|比賽|競賽|黑客松", re.I)
MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE = re.compile(rf"(?:19|20)\d\d|\bpresent\b|\bnow\b|\bongoing\b|\b{MON}\s+(?:19|20)\d\d", re.I)
SPAN = re.compile(rf"((?:{MON}\s+)?(?:19|20)\d\d(?:\s*[-–—]?\s*(?:(?:{MON}\s+)?(?:19|20)\d\d|present|now|ongoing))?)\s*$", re.I)
BULLET = re.compile(r"^\s*[•▪●◦\-*–]\s+")


def unspace(text: str) -> str:
    """Canva-style PDFs come out as 'G O L D  M E D A L': join single letters, keep double spaces as word gaps."""
    out = []
    for line in text.splitlines():
        toks = line.split(" ")
        if len(toks) > 6 and sum(1 for t in toks if len(t) == 1) / len(toks) > .6:
            line = " ".join(w.replace(" ", "") for w in re.split(r"\s{2,}", line.strip()))
        out.append(line)
    return "\n".join(out)


def _header_kind(line: str):
    l = line.strip().strip(":：").strip()
    if not l or len(l) > 45 or l.endswith("."): return None
    for kind, pat in SEC_KIND:
        if pat.match(l): return kind
    if ANY_HDR.match(l) or (l.isupper() and len(l.split()) <= 4 and not DATE.search(l) and len(l) > 3): return "other"
    return None


CONT = re.compile(r"^((?i:(?:national|international|regional|provincial|school|city|university)[- ]level\b|out of\b|with\b|collaboration\b|participants?\b)|[a-z(]|\d{4}\b\)?\.?$)")
YEAR = re.compile(r"(?:19|20)\d\d")

def _squash(t):   # "I T B" -> "ITB", "( 2 0 2 4 )" -> "(2024)"
    t = re.sub(r"\b(?:\w ){2,}\w\b", lambda m: m.group(0).replace(" ", ""), t)
    return re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", t))

def _entries(lines, kind):
    groups, cur = [], []
    has_bullets = sum(bool(BULLET.match(l)) for l in lines) >= 2
    for raw in lines:
        l = _squash(raw.strip())
        if not l: continue
        bullet = bool(BULLET.match(l)); l = BULLET.sub("", l)
        if kind == "projects":
            if cur and " " not in l and not YEAR.search(l): continue          # rows of tech tags like "PythonFastAPI"
            start = not cur or (bool(SPAN.search(l)) and len(l) < 80) or (bullet and not has_bullets)
        else:
            joined = " ".join(cur)
            start = (not cur or (bullet if has_bullets else False) or bool(AWARD_START.match(l)) and not CONT.match(l)
                     or (cur[-1].rstrip().endswith((".", ")")) and l[:1].isupper() and not CONT.match(l)))
        if start and cur: groups.append(cur); cur = []
        cur.append(l)
    if cur: groups.append(cur)
    out = []
    for g in groups:
        if kind == "projects":
            m = re.match(rf"(.{{3,80}}?)[\s,·|]+((?:{MON}\s+)?(?:19|20)\d\d(?:\W{{1,4}}(?:(?:{MON}\s+)?(?:19|20)\d\d|present|now|ongoing))?)\s*$", g[0], re.I)
            title = f"{m.group(1).strip(' ,·|')} ({re.sub(r'\W{1,4}(?=[A-Za-z]|\d{4})', lambda x: ' – ' if not x.group(0).strip() == '' or len(x.group(0)) > 1 else ' ', m.group(2)).strip()})" if m else g[0]
            if m:
                rest = " ".join(g[1:])
                sub = g[1] if len(g) > 1 and len(g[1]) <= 70 else re.split(r"(?<=[.!?])\s", rest, maxsplit=1)[0]
                t = title + (f" — {sub}" if sub else "")
            else:   # no dates: keep the first sentence of the whole entry
                t = re.split(r"(?<=[.!?])\s", " ".join(g), maxsplit=1)[0]
        else:
            t = " ".join(g)
        t = re.sub(r"\s+", " ", t).strip(" ·|-–")
        if len(t) > 160: t = t[:160].rsplit(" ", 1)[0] + "…"
        if len(t) > 3 and t not in out and not t[:1].islower(): out.append(t)   # skip fragments cut from the middle of a line
    return out[:8]


def find_sections(text: str) -> dict:
    sec, buckets = None, {"competitions": [], "awards": [], "projects": []}
    for line in text.splitlines():
        k = _header_kind(line)
        if k:
            sec = k if k != "other" else None
            continue
        if sec: buckets[sec].append(line)
    out = {k: _entries(v, k) for k, v in buckets.items()}
    # awards that are really competitions ("3rd Place, Business Plan Competition") also go under competitions
    comp = [a for a in out["awards"] if COMP_WORDS.search(a)]
    out["awards"] = [a for a in out["awards"] if a not in comp]
    out["competitions"] = (out["competitions"] + [c for c in comp if c not in out["competitions"]])[:8]
    return out
