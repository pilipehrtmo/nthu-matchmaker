"""Embedding similarity + a small ML ranker. Falls back to plain tag overlap if the libraries are missing."""
import os, functools
import numpy as np
from .config import MATCH_MODE
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"   # multilingual, ~120 MB, runs on CPU
RANKER_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ranker.joblib")

import threading
_lock = threading.Lock(); _model = None; _cache = {}

def _cross(user, owner):
    """1.0 when the two people come from different departments (the linked department when there is one, else the typed text)."""
    from .departments import key
    if not (owner and key(user) and key(owner)): return 0.0
    return 1.0 if key(user) != key(owner) else 0.0

def load_now():
    """Load the embedding model (slow the first time). Returns True if it is available."""
    global _model
    with _lock:
        if _model is None:
            try:
                from sentence_transformers import SentenceTransformer
                try: _model = SentenceTransformer(MODEL_NAME, local_files_only=True)   # cached copy: no network wait
                except Exception: _model = SentenceTransformer(MODEL_NAME)
            except Exception as e: print("Embedding model unavailable, using tag overlap only:", e)
    return _model is not None

def warm(): threading.Thread(target=load_now, daemon=True).start()   # load in the background so pages never hang

def embed(text):
    if _model is None: return None    # not loaded yet: callers fall back to tag overlap instead of blocking
    v = _cache.get(text)
    if v is None: v = _cache[text] = _model.encode(text, normalize_embeddings=True)
    return v

def tagset(t): return {x.strip().lower() for x in t.split(",") if x.strip()}
def jaccard(a, b):
    a, b = tagset(a), tagset(b); u = a | b
    return len(a & b) / len(u) if u else 0.0

def similarity(a, b):
    if not a.strip() or not b.strip(): return None
    ea, eb = embed(a), embed(b)
    return None if ea is None or eb is None else float(max(0.0, np.dot(ea, eb)))

def features(sim, tags_a, tags_b, hours_ok, cross):
    return [sim, jaccard(tags_a, tags_b), hours_ok, cross]   # order matters: train.py uses the same

@functools.lru_cache(1)
def _ranker():
    try:
        import joblib; return joblib.load(RANKER_PATH)
    except Exception: return None

def score(student_text, student_tags, seat_text, seat_tags, hours_ok, cross):
    j = jaccard(student_tags, seat_tags)
    if MATCH_MODE == "tags": return j
    sim = similarity(student_text, seat_text)
    if sim is None: return j
    if MATCH_MODE == "embeddings": return sim
    f = features(sim, student_tags, seat_tags, hours_ok, cross); r = _ranker()
    if r is not None: return float(r.predict_proba([f])[0][1])
    return 0.7 * sim + 0.3 * f[1]

def match_pct(user, role, project, owner):
    hours_ok = min(user.hours / max(project.hours_per_week, 1), 1.0)
    cross = _cross(user, owner)
    s = score(f"{user.skills}. {user.bio}", user.skills, f"{role.name}. {role.skills}", role.skills, hours_ok, cross)
    return int(round(100 * min(max(s, 0.0), 1.0)))

def why(user, role, pct):
    shared = tagset(user.skills) & tagset(role.skills)
    if shared: return "Shares: " + ", ".join(sorted(shared))
    return "Similar meaning" if pct >= 50 else "Little overlap"
