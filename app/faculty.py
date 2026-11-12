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

def check_page(email: str, url: str, timeout: float = 8.0):
    """Fetch an NTHU page and look for the email. Returns (found, note)."""
    if not nthu_url(url): return False, "The link is not on an nthu.edu.tw website."
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": "NTHU-Matchmaker faculty check"}) as c:
            for _ in range(4):   # follow at most 3 redirects, and only within nthu.edu.tw
                host = urlparse(url).hostname
                if not _public_host(host): return False, "Could not reach that page."
                r = c.get(url)
                if r.is_redirect:
                    url = urljoin(url, r.headers.get("location", ""))
                    if not nthu_url(url): return False, "The page redirects outside nthu.edu.tw."
                    continue
                break
            if r.status_code != 200: return False, f"The page answered with error {r.status_code}."
            text = r.content[:3_000_000].decode(r.encoding or "utf-8", "ignore")
    except httpx.HTTPError as e:
        return False, f"Could not open the page ({type(e).__name__})."
    if email_on_page(email, text): return True, f"Email found on {url}"
    return False, "Your email was not found on that page."
