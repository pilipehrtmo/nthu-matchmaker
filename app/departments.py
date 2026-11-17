"""NTHU colleges, departments and programs (app/departments.json) and the rules for choosing one.

A profile keeps its free-text `faculty` exactly as it was; the department link lives next to it:
  dept_id     unit id ("eecs-cs"), "c:<college>" for "college, department not chosen yet", or "" (none)
  dept_track  IBP track id, only with dept_id "thc-ibp"
  dept_status ""        nothing to do
              "ok"      linked to a department (or college)
              "review"  an old free-text entry that could not be matched safely: waits for an admin
              "other"   the student picked "Other / not listed": waits for an admin
              "kept"    an admin looked at it and left it without a department
  dept_src    who set the link: "user", "admin" or "migration" (rollback clears only "migration")
  faculty_orig  the free text as it was before the first department link (never changed afterwards)
"""
import json, os, re

_D = json.load(open(os.path.join(os.path.dirname(__file__), "departments.json"), encoding="utf-8"))
COLLEGES = {c["id"]: c for c in _D["colleges"]}
UNITS = {u["id"]: u for u in _D["units"]}
LEGACY = _D["legacy_aliases"]
IBP = "thc-ibp"
TRACKS = {t["id"]: t for t in UNITS[IBP].get("tracks", [])}
OTHER, NONE = "other", "none"
OTHER_MIN, OTHER_MAX = 2, 60
REVIEW_STATES = ("review", "other")
NOT_CHOSEN = {"en": " (department not chosen yet)", "zh": "（尚未選系）"}


def _name(x, lang): return x["zh"] if lang == "zh" else x["en"]


def valid(dept_id: str, track: str = "", for_new: bool = True) -> bool:
    """A choice a student may make (for_new) or that may be stored (admin, migration: phased-out units allowed)."""
    if dept_id.startswith("c:"): return dept_id[2:] in COLLEGES and COLLEGES[dept_id[2:]]["kind"] != "phased_out"
    u = UNITS.get(dept_id)
    if not u or (for_new and not u["active"]): return False
    if dept_id == IBP: return track in TRACKS
    return not track


def label(dept_id: str, track: str = "", lang: str = "en", short: bool = False) -> str:
    if not dept_id: return ""
    if dept_id.startswith("c:"):
        c = COLLEGES.get(dept_id[2:])
        return f"{_name(c, lang)}{NOT_CHOSEN[lang]}" if c and not short else (_name(c, lang) if c else "")
    u = UNITS.get(dept_id)
    if not u: return ""
    if dept_id == IBP:
        base = "清華學院國際學士班" if lang == "zh" else "IBP"
        t = TRACKS.get(track)
        return f"{base} · {_name(t, lang)}" if t else _name(u, lang)
    return _name(u, lang)


def colleges_of(dept_id: str) -> set:
    if dept_id.startswith("c:"): return {dept_id[2:]}
    return set(UNITS[dept_id]["colleges"]) if dept_id in UNITS else set()


def display(u, lang: str = "en") -> str:
    """What a profile shows: the linked department in the reader's language, otherwise the free text as typed."""
    return label(getattr(u, "dept_id", "") or "", getattr(u, "dept_track", "") or "", lang) or (u.faculty or "").strip()


def key(u) -> str:
    """For filters and 'from another department': the link when there is one, otherwise the typed text."""
    d = getattr(u, "dept_id", "") or ""
    return d if d else (u.faculty or "").strip().lower()


def groups(lang: str = "en", admin: bool = False):
    """Dropdown content: [(group label, [(value, label), ...]), ...]. Phased-out units only for admins."""
    out, seen = [], set()
    for c in COLLEGES.values():
        if c["kind"] == "phased_out" and not admin: continue
        opts = [] if c["kind"] == "phased_out" else [(f"c:{c['id']}", f"{_name(c, lang)}{NOT_CHOSEN[lang]}")]
        for u in UNITS.values():
            if c["id"] not in u["colleges"] or (not u["active"] and not admin) or u["id"] in seen: continue
            seen.add(u["id"])   # a program shared by two colleges is listed once, under the first, naming the other
            if u["id"] == IBP and admin:
                opts += [(f"{IBP}|{t}", label(IBP, t, lang)) for t in TRACKS]
            else:
                also = [_name(COLLEGES[x], lang) for x in u["colleges"] if x != c["id"]]
                opts.append((u["id"], _name(u, lang) + ((f"（亦屬{'、'.join(also)}）" if lang == "zh" else f" (also {', '.join(also)})") if also else "")))
        out.append((_name(c, lang), opts))
    return out


# Short names students actually type (search only; never shown as names): 資工, 電機, ...
ALIASES = {"eecs-cs": "資工 資工系 cs", "eecs-ee": "電機 電機系 ee", "eecs-bs": "電資院學士班 電資班", "eng-che": "化工 化工系",
           "eng-pme": "動機 動機系", "eng-mse": "材料 材料系 材料科學", "eng-ieem": "工工 工工系", "nuc-ess": "工科 工科系",
           "nuc-bmes": "醫環 醫環系", "tm-econ": "經濟 經濟系", "tm-qf": "計財 計財系 finance", "lsm-ls": "生科 生科系",
           "lsm-ms": "醫科 醫科系", "lsm-pbm": "學士後醫 醫學系 medicine", "hss-cl": "中文 中文系", "hss-fl": "外語 外語系 外文 english literature",
           "sci-math": "數學 math", "sci-phys": "物理", "sci-chem": "化學", "sci-stat": "統計 統計所 data science",
           "edu-ei": "英教 英教系", "edu-kin": "運科 運科系 sports", "edu-elt": "教科 教科系", "edu-epc": "教心 教心系",
           "edu-se": "特教 特教系", "edu-ece": "幼教 幼教系", "arts-ad": "藝設 藝設系 art design", "arts-mus": "音樂 音樂系",
           "thc-ibp": "ibp 國際學士班 international bachelor", "thc-bs": "清華學院學士班 不分系 undeclared"}


def search_text(value: str) -> str:
    """The option's own search words: both languages, other official forms, course code, common short names and,
    for IBP, every track. College names are matched separately (and ranked lower) by the page script."""
    if value.startswith("c:"):
        c = COLLEGES.get(value[2:]) or {}
        return " ".join([c.get("zh", ""), c.get("en", ""), NOT_CHOSEN["en"], NOT_CHOSEN["zh"], "college 學院"])
    u = UNITS.get(value)
    if not u: return ""
    words = [u["zh"], u["en"], u.get("code", ""), ALIASES.get(value, "")]
    words += [re.sub(r"\s*\(English page.*\)$", "", x) for x in u.get("en_other_official", [])]
    for t in u.get("tracks", []): words += [t["zh"], t["en"]]
    return " ".join(w for w in words if w)


DEGREES = {"bachelor": {"en": "Bachelor's", "zh": "學士班"}, "master": {"en": "Master's", "zh": "碩士班"}, "phd": {"en": "PhD", "zh": "博士班"}}


def degree_label(code: str, lang: str = "en") -> str:
    d = DEGREES.get(code or "")
    return _name(d, lang) if d else ""


def study(u, lang: str = "en") -> str:
    """Degree and department together, e.g. "Master's · Computer Science". Either part may be missing."""
    return " · ".join(x for x in (degree_label(getattr(u, "degree", "") or "", lang), display(u, lang)) if x)


def tracks(lang: str = "en"): return [(t, _name(x, lang)) for t, x in TRACKS.items()]


def choose(dept: str, track: str = "", other: str = ""):
    """A student's choice on the signup or profile form -> (fields to store, error or "").
    Returns fields=None when the form left the department untouched (nothing chosen)."""
    dept, track, other = (dept or "").strip(), (track or "").strip(), re.sub(r"\s+", " ", other or "").strip()
    if not dept: return None, ""
    if dept == NONE: return dict(dept_id="", dept_track="", dept_status="", dept_src="user", faculty=""), ""
    if dept == OTHER:
        if len(other) < OTHER_MIN: return None, "Type your department or major in the box under Other."
        if len(other) > OTHER_MAX: return None, f"Keep your department or major under {OTHER_MAX} characters."
        return dict(dept_id="", dept_track="", dept_status="other", dept_src="user", faculty=other), ""
    if dept == IBP and track not in TRACKS: return None, "Choose your IBP track."
    if dept != IBP: track = ""
    if not valid(dept, track): return None, "Choose your department from the list, or pick Other."
    return dict(dept_id=dept, dept_track=track, dept_status="ok", dept_src="user", faculty=label(dept, track, "en")), ""


def admin_choice(value: str):
    """The admin's pick in the review queue: 'unit', 'unit|track' or 'c:college' -> (dept_id, track) or None."""
    d, _, t = (value or "").partition("|")
    return (d, t) if valid(d, t, for_new=False) else None


def map_legacy(text: str):
    """Old free text -> dict(dept_id, dept_track, dept_status). Only exact, reviewed aliases are linked;
    anything else that is not empty goes to the admin review queue. Nothing is guessed."""
    t = (text or "").strip()
    if not t: return None
    a = LEGACY.get(t)
    if a and "unit" in a: return dict(dept_id=a["unit"], dept_track=a.get("track", ""), dept_status="ok")
    if a and "college" in a: return dict(dept_id=f"c:{a['college']}", dept_track="", dept_status="ok")
    low = t.lower()
    for u in UNITS.values():   # exact official names (Chinese or English) are safe too
        if u["id"] != IBP and low in {u["zh"].lower(), u["en"].lower()}: return dict(dept_id=u["id"], dept_track="", dept_status="ok")
    return dict(dept_id="", dept_track="", dept_status="review")


def guess(text: str) -> str:
    """For CV import: a unit id only when the text names it exactly (official Chinese or English, or a known
    other official English form). Otherwise ""."""
    low = re.sub(r"\s+", " ", (text or "")).strip().lower()
    if not low: return ""
    for u in UNITS.values():
        if not u["active"] or u["id"] == IBP: continue
        names = {u["zh"].lower(), u["en"].lower()} | {re.sub(r"\s*\(English page.*\)$", "", x).lower() for x in u.get("en_other_official", [])}
        if low in names: return u["id"]
    return ""


def legacy_note(a) -> str:
    return (LEGACY.get((a or "").strip()) or {}).get("review", "")


def set_dept(u, fields):
    """Store a department choice. The text before the first change is frozen in faculty_orig."""
    if not (u.faculty_orig or "").strip() and (u.faculty or "").strip() and fields.get("faculty", u.faculty) != u.faculty: u.faculty_orig = u.faculty
    for k, v in fields.items(): setattr(u, k, v)


def relink_text(u, new_text):
    """A professor's typed department: link it only on an exact, reviewed match; any other text waits for an admin."""
    new_text = (new_text or "").strip()
    if new_text == (u.faculty or "").strip() and (u.dept_id or u.dept_status): return
    m = map_legacy(new_text) or dict(dept_id="", dept_track="", dept_status="")
    set_dept(u, dict(faculty=new_text, dept_src="user" if m["dept_status"] else "", **m))
