"""Where research files live.

On the public site: a PRIVATE Supabase Storage bucket, reached only from this server with the
service key (never sent to a browser). Browsers never get a storage link: every download goes
through /files/{version_id}, which checks permission first.

On a laptop or in tests (no Supabase settings): a folder on disk.
On the public site WITHOUT Supabase settings: uploads are switched off with a clear message,
because Render's disk is wiped on every deploy and files would silently disappear.
"""
import os, pathlib, re
import httpx
from .config import PUBLIC

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "research-docs")
LOCAL_DIR = os.getenv("LOCAL_STORAGE_DIR", "var/uploads")
SAFE_KEY = re.compile(r"^research/\d+/\d+/v\d+-[0-9a-f]{16}\.[a-z]{2,4}$")


class StorageError(Exception): pass


def _check(key):
    if not SAFE_KEY.match(key): raise StorageError("bad storage key")   # keys are made by us; this stops any path trick
    return key


class LocalStorage:
    name = "local folder"
    def __init__(self, root=LOCAL_DIR): self.root = pathlib.Path(root)
    def put(self, key, data, mime):
        p = self.root / _check(key); p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists(): raise StorageError("file already exists")   # versions are never overwritten
        p.write_bytes(data)
    def get(self, key):
        p = self.root / _check(key)
        if not p.is_file(): raise StorageError("missing")
        return p.read_bytes()
    def delete(self, key):
        p = self.root / _check(key)
        if p.exists(): p.unlink()


class SupabaseStorage:
    """Supabase Storage REST API (free tier: 1 GB in total, 50 MB per file)."""
    name = "Supabase Storage (private bucket)"
    def __init__(self, url=SUPABASE_URL, key=SUPABASE_SERVICE_KEY, bucket=STORAGE_BUCKET, transport=None):
        self.base, self.bucket = f"{url}/storage/v1/object", bucket
        self.h = {"Authorization": f"Bearer {key}", "apikey": key}
        self.transport = transport   # tests pass a mock transport
    def _c(self): return httpx.Client(timeout=60, transport=self.transport)
    def put(self, key, data, mime):
        with self._c() as c:
            r = c.post(f"{self.base}/{self.bucket}/{_check(key)}", content=data,
                       headers={**self.h, "Content-Type": mime, "x-upsert": "false", "Cache-Control": "no-store"})
        if r.status_code >= 300: raise StorageError(f"upload failed ({r.status_code})")
    def get(self, key):
        with self._c() as c:
            r = c.get(f"{self.base}/authenticated/{self.bucket}/{_check(key)}", headers=self.h)
        if r.status_code != 200: raise StorageError(f"download failed ({r.status_code})")
        return r.content
    def delete(self, key):
        with self._c() as c:
            r = c.delete(f"{self.base}/{self.bucket}/{_check(key)}", headers=self.h)
        if r.status_code >= 300 and r.status_code != 404: raise StorageError(f"delete failed ({r.status_code})")


_backend = None
def backend():
    """The storage in use, or None when uploads must stay off (public site without Supabase settings)."""
    global _backend
    if _backend is None:
        if SUPABASE_URL and SUPABASE_SERVICE_KEY: _backend = SupabaseStorage()
        elif not PUBLIC: _backend = LocalStorage()
    return _backend

def set_backend(b):   # tests
    global _backend; _backend = b
