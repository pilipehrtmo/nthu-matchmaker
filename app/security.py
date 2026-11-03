"""Passwords and one-time links (email verification, password reset).
Passwords are stored only as salted scrypt hashes; links are stored only as SHA-256 hashes, so a database leak reveals neither."""
import hashlib, hmac, secrets, threading
from datetime import datetime, timedelta

_HASHING = threading.BoundedSemaphore(3)   # scrypt uses 16 MB per hash: at most 3 at once keeps memory low on the free server

def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    with _HASHING: h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${h.hex()}"

def check_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt": return False
        with _HASHING: got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(h) // 2)
        return hmac.compare_digest(got.hex(), h)
    except (ValueError, TypeError):
        return False

def password_problem(pw: str, email: str = "", name: str = "") -> str:
    if len(pw) < 8: return "Use at least 8 characters for your password."
    if len(pw) > 128: return "That password is too long (128 characters at most)."
    low = pw.lower()
    if email and low == email.lower(): return "Your password cannot be your email."
    if low in {"password", "12345678", "123456789", "1234567890", "qwerty123", "password1", "11111111", "abcd1234", "nthu1234"}:
        return "That password is too easy to guess. Pick something less common."
    return ""

def new_token() -> tuple[str, str]:
    """Returns (token to put in the link, hash to store)."""
    t = secrets.token_urlsafe(32)
    return t, token_hash(t)

def token_hash(t: str) -> str: return hashlib.sha256(t.encode()).hexdigest()

def expires_in(hours: float) -> datetime: return datetime.utcnow() + timedelta(hours=hours)
