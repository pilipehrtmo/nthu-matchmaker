"""Profile contacts (private) and professional links (public): field list, cleaning and validation."""
import re
from urllib.parse import urlparse

# private: shown only to teammates after an application is accepted
CONTACTS = [  # (field, label, placeholder)
    ("line", "LINE ID", "e.g. pilipe_yee"),
    ("instagram", "Instagram", "e.g. @pilipe.yee"),
    ("discord", "Discord", "e.g. pilipe#1234 or pilipe"),
    ("contact", "Other (email, phone, WhatsApp…)", "Anything else teammates can use"),
]
# public: shown on your profile and when you apply
PRO_LINKS = [  # (field, label, placeholder, base URL for a bare username, allowed hosts)
    ("linkedin", "LinkedIn", "linkedin.com/in/yourname", "https://www.linkedin.com/in/", ("linkedin.com",)),
    ("github", "GitHub", "github.com/yourname", "https://github.com/", ("github.com",)),
    ("website", "Portfolio or website", "yourname.com", None, ()),
    ("behance", "Behance or Dribbble", "behance.net/yourname", "https://www.behance.net/", ("behance.net", "dribbble.com")),
    ("scholar", "Google Scholar or ORCID", "orcid.org/0000-0000-0000-0000", None, ("scholar.google.com", "orcid.org")),
]
HANDLE = re.compile(r"^[\w.\-]{1,60}$")
ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dXx]$")


class LinkError(ValueError):
    pass


def clean_contact(v: str, limit: int = 60) -> str:
    v = (v or "").strip()
    return v[:limit]


def clean_handle(v: str) -> str:
    """LINE / Instagram / Discord: keep a plain handle, drop a leading @ and any URL around it."""
    v = (v or "").strip()
    v = re.sub(r"^https?://(www\.)?instagram\.com/", "", v, flags=re.I).strip("/")
    return v.lstrip("@")[:40]


def clean_link(field: str, v: str) -> str:
    """Turn what the student typed into a safe https URL, or raise LinkError."""
    spec = next(p for p in PRO_LINKS if p[0] == field)
    _, label, _, base, hosts = spec
    v = (v or "").strip()
    if not v:
        return ""
    if field == "scholar" and ORCID.match(v):
        v = "https://orcid.org/" + v.upper()
    elif base and HANDLE.match(v.lstrip("@")) and "." not in v.lstrip("@"):
        v = base + v.lstrip("@")                      # a bare username
    elif not re.match(r"^[a-z]+://", v, re.I):
        v = "https://" + v                             # "github.com/me" or "me.dev"
    u = urlparse(v)
    if u.scheme.lower() not in ("http", "https") or not u.hostname or "." not in u.hostname:
        raise LinkError(f"{label}: that doesn't look like a link.")
    host = u.hostname.lower()
    if hosts and not any(host == h or host.endswith("." + h) for h in hosts):
        raise LinkError(f"{label}: please use a link on {' or '.join(hosts)}.")
    return ("https://" + v.split("://", 1)[1])[:200]


def short(url: str) -> str:
    """Display form: github.com/me instead of https://github.com/me/"""
    return re.sub(r"^https?://(www\.)?", "", url or "").rstrip("/")
