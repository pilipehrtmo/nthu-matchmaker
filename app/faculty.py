"""Professor / advisor accounts: they must use an NTHU staff email, and we cross-check that email against
an NTHU web page that lists them (a department faculty list or their own page on *.nthu.edu.tw)."""
import html, ipaddress, re, socket
from urllib.parse import urlparse, urljoin
import httpx

STUDENT_DOMAINS = re.compile(r"^(gapp|oz|m\d+)\.nthu\.edu\.tw$")   # student mail systems, not staff

def staff_email(email: str) -> bool:
    """name@nthu.edu.tw or name@<dept>.nthu.edu.tw (cs, ee, mx, ...), but not student addresses like @gapp."""
    dom = email.rsplit("@", 1)[-1].lower()
    return (dom == "nthu.edu.tw" or dom.endswith(".nthu.edu.tw")) and not STUDENT_DOMAINS.match(dom)

def nthu_email(email: str) -> bool:
    """Any NTHU address: staff domains, the Google Workspace domain @gapp (students, faculty, staff and alumni),
    the student mail systems @m<year> (e.g. @m114) and the alias domain @oz."""
    dom = email.rsplit("@", 1)[-1].lower()
    return dom == "nthu.edu.tw" or dom.endswith(".nthu.edu.tw")

def shared_domain(email: str) -> bool:   # NTHU addresses anyone at NTHU can hold: a professor using one is checked by an admin
    return bool(STUDENT_DOMAINS.match(email.rsplit("@", 1)[-1].lower()))

def nthu_url(url: str) -> bool:
    u = urlparse(url.strip())
    host = (u.hostname or "").lower()
    return u.scheme in ("http", "https") and (host == "nthu.edu.tw" or host.endswith(".nthu.edu.tw"))

def _public_host(host: str) -> bool:   # never let the server be pointed at an internal address
    try: return all(ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(host, None))
    except (OSError, ValueError): return False

def email_on_page(email: str, text: str) -> bool:
    """True if the email is written on the page, also in forms like 'lai [at] cs.nthu.edu.tw' or 'lai(at)cs...'."""
    local, dom = email.lower().split("@", 1)
    t = html.unescape(text).lower()
    at = r"\s*(?:@|\[at\]|\(at\)|\{at\}|\sat\s|＠)\s*"
    dot = lambda s: re.escape(s).replace(r"\.", r"\s*(?:\.|\[dot\]|\(dot\))\s*")
    return re.search(r"(?<![\w.])" + re.escape(local) + at + dot(dom) + r"(?!\.?[\w-])", t) is not None

def academic_email(email: str) -> bool:
    """Another university or research institute (a jointly appointed or visiting professor): *.edu.tw, *.edu, *.edu.xx, *.ac.xx."""
    dom = email.rsplit("@", 1)[-1].lower()
    return bool(re.search(r"(^|\.)(edu|edu\.[a-z]{2}|ac\.[a-z]{2})$", dom)) or dom.endswith("sinica.edu.tw")

def fetch_page(url: str, timeout: float = 8.0):
    """Open an NTHU page ourselves. Returns (text, final_url, error). Only nthu.edu.tw, public addresses, 3 redirects."""
    if not nthu_url(url): return "", url, "The link is not on an nthu.edu.tw website."
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": "NTHU-Matchmaker faculty check"}) as c:
            for _ in range(4):
                host = urlparse(url).hostname
                if not _public_host(host): return "", url, "Could not reach that page."
                r = c.get(url)
                if r.is_redirect:
                    url = urljoin(url, r.headers.get("location", ""))
                    if not nthu_url(url): return "", url, "The page redirects outside nthu.edu.tw."
                    continue
                break
            if r.status_code != 200: return "", url, f"The page answered with error {r.status_code}."
            return r.content[:3_000_000].decode(r.encoding or "utf-8", "ignore"), url, ""
    except httpx.HTTPError as e:
        return "", url, f"Could not open the page ({type(e).__name__})."

def _plain(text):
    t = html.unescape(re.sub(r"<(script|style)\b.*?</\1>|<[^>]+>", " ", text, flags=re.S | re.I)).lower()
    return re.sub(r"[\s\-‐_.,]+", " ", t)

def name_on_page(name: str, text: str) -> bool:
    """Every part of the name is on the page (any order: 'Wang Hsiao-Ming' matches 'Hsiao-Ming Wang'); a Chinese name as written."""
    t = _plain(text); n = _plain(name).strip()
    if not n: return False
    if re.search(r"[\u4e00-\u9fff]", n): return n.replace(" ", "") in t.replace(" ", "")
    parts = [p for p in n.split() if len(p) >= 2]
    return bool(parts) and all(re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", t) for p in parts)

TITLE_ZH = {"Professor": ["教授"], "Distinguished Professor": ["特聘教授", "講座教授"], "Associate Professor": ["副教授"], "Assistant Professor": ["助理教授"],
            "Adjunct Professor": ["兼任"], "Visiting Professor": ["客座"], "Emeritus Professor": ["榮譽", "名譽"], "Jointly Appointed Faculty": ["合聘"],
            "Lecturer": ["講師"], "Research Fellow": ["研究員"], "Postdoctoral Researcher": ["博士後"]}
def title_on_page(title: str, text: str) -> bool:
    t = _plain(text)
    if title and _plain(title).strip() in t: return True
    return any(z in t for z in TITLE_ZH.get(title, []))

STOP = {"department", "dept", "of", "and", "the", "institute", "graduate", "program", "college", "school", "nthu", "national", "tsing", "hua", "university"}
def dept_on_page(dept: str, text: str) -> bool:
    t = _plain(text); d = _plain(dept)
    if re.search(r"[\u4e00-\u9fff]", d): return d.replace(" ", "") in t.replace(" ", "")
    words = [w for w in d.split() if w not in STOP and len(w) > 2]
    return bool(words) and all(w in t for w in words)

def check_page(email: str, url: str, timeout: float = 8.0):
    """Fetch an NTHU page and look for the email. Returns (found, note)."""
    text, url, err = fetch_page(url, timeout)
    if err: return False, err
    if email_on_page(email, text): return True, f"Email found on {url}"
    return False, "Your email was not found on that page."
