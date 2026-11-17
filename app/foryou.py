"""'For you': which projects, research positions and competitions suit one student, and why.

Built on the same profile data the match score uses (skills, hours, department) plus two optional profile
fields: interests and roles they want. Every pick comes with the real reasons behind it; nothing is guessed.
A card is marked 'For you' only when there is enough evidence (see the thresholds below), and never for
something the student posted, applied to or joined.
"""
import re
from . import departments as DEP

GENERIC = {"developer", "engineer", "member", "lead", "assistant", "dev", "the", "and", "of", "a", "an", "for", "team", "student"}
CATEGORY_WORDS = {   # competition categories -> words in interests or skills that point to them
    "Tech & Data": ["ai", "machine learning", "ml", "deep learning", "data", "data science", "programming", "coding", "software", "web",
                    "app", "robotics", "hackathon", "cybersecurity", "security", "python", "javascript", "java", "c++", "react", "iot",
                    "人工智慧", "機器學習", "資料", "程式", "軟體", "資安", "機器人"],
    "Business": ["business", "startup", "startups", "entrepreneurship", "marketing", "finance", "management", "pitch", "創業", "商業", "行銷", "金融"],
    "Design & Arts": ["design", "ui", "ux", "ui design", "art", "arts", "film", "music", "photography", "illustration", "figma", "設計", "藝術", "音樂", "攝影"],
    "Law & Policy": ["law", "policy", "public policy", "法律", "政策"],
    "Science & Health": ["health", "medicine", "biology", "biotech", "chemistry", "physics", "science", "neuroscience", "健康", "醫學", "生物", "化學", "物理"],
    "Social Impact": ["social impact", "sustainability", "community", "education", "environment", "climate", "nonprofit", "永續", "社會", "教育", "環境"],
}
T = {   # reasons, in both site languages
    "skills": {"en": "Matches {n} of your skills: {x}", "zh": "符合你 {n} 項技能：{x}"},
    "skill": {"en": "Matches your skill: {x}", "zh": "符合你的技能：{x}"},
    "interest": {"en": "Related to your interest in {x}", "zh": "和你感興趣的「{x}」相關"},
    "role": {"en": "Needs a {x}, a role you want", "zh": "需要「{x}」，是你想擔任的角色"},
    "hours": {"en": "Fits your {n} h/week", "zh": "符合你每週 {n} 小時"},
    "college": {"en": "From another college: {x}", "zh": "來自其他學院：{x}"},
    "category": {"en": "{x}, which fits your interests and skills", "zh": "「{x}」類別，符合你的興趣和技能"},
    "closing": {"en": "Closes in {n} days", "zh": "{n} 天後截止"},
}
CAT_ZH = {"Tech & Data": "科技與資料", "Business": "商業", "Design & Arts": "設計與藝術", "Law & Policy": "法律與政策",
          "Science & Health": "科學與健康", "Social Impact": "社會影響力"}


def _say(key, lang, **kw): return T[key]["zh" if lang == "zh" else "en"].format(**kw)


def tags(text): return [t.strip().lower() for t in re.split(r"[,，、;；\n]", text or "") if t.strip()]


def hit(phrase, text):
    """phrase appears in text as a whole word (English) or anywhere (Chinese)."""
    if not phrase or not text: return False
    if phrase.isascii(): return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9+#])", text) is not None
    return phrase in text


def _words(s): return {w for w in re.findall(r"[a-z0-9+#]+|[^\x00-\x7f]+", (s or "").lower()) if w not in GENERIC and len(w) > 1}


class Me:
    """The parts of a student's profile that recommendations use."""
    def __init__(self, user):
        self.user = user
        self.skills = set(tags(user.skills)) if user else set()
        self.interests = tags(getattr(user, "interests", "")) if user else []
        self.roles = tags(getattr(user, "roles_wanted", "")) if user else []
        self.hours = (user.hours or 0) if user else 0
        self.colleges = DEP.colleges_of(user.dept_id or "") if user and getattr(user, "dept_id", "") else set()

    @property
    def ready(self): return bool(self.skills or self.interests or self.roles)

    def missing(self):
        """What to add to the profile for better picks (for the hint)."""
        out = []
        if not self.skills: out.append("skills")
        if not self.interests: out.append("interests")
        if not self.roles: out.append("roles")
        return out


def _other_college(me, owner, lang):
    if not me.colleges or not owner: return ""
    theirs = DEP.colleges_of(getattr(owner, "dept_id", "") or "")
    if not theirs or theirs & me.colleges: return ""
    return DEP.label(f"c:{sorted(theirs)[0]}", "", lang, short=True)


def project(me, pr, seats, owner, lang="en"):
    """(for_you, reasons, other_college) for one project card. seats: its open seats the person could take."""
    if not me.ready or not seats: return False, [], ""
    text = " ".join([pr.title, pr.description, pr.category, pr.kind, pr.tags.replace(":", " "), pr.needs,
                     " ".join(f"{r.name} {r.skills}" for r in seats)]).lower()
    best = None
    for r in seats:
        shared = sorted(me.skills & set(tags(r.skills)))
        rw = _words(r.name)
        role = next((x for x in me.roles if _words(x) & rw or hit(x, r.name.lower())), "")
        strength = 2 * min(len(shared), 3) + (2 if role else 0)
        if best is None or strength > best[0]: best = (strength, shared, role, r)
    strength, shared, role, seat = best
    ints = [x for x in me.interests if hit(x, text)][:2]
    strength += 2 * len(ints)
    hours_ok = not me.hours or (pr.hours_per_week or 0) <= me.hours + 1
    other = _other_college(me, owner, lang)
    why = []
    if len(shared) >= 2: why.append(_say("skills", lang, n=len(shared), x=", ".join(shared[:4])))
    elif shared: why.append(_say("skill", lang, x=shared[0]))
    if role: why.append(_say("role", lang, x=seat.name))
    for x in ints: why.append(_say("interest", lang, x=x))
    picked = strength >= 4 and hours_ok
    if picked and me.hours: why.append(_say("hours", lang, n=me.hours))
    if picked and other: why.append(_say("college", lang, x=other))
    return picked, why if picked else [], other


def opening(me, o, prof, lang="en"):
    """(for_you, reasons, other_college) for one research position."""
    if not me.ready or (me.user and me.user.is_faculty): return False, [], ""
    text = " ".join([o.title, o.description, o.skills, o.requirements, getattr(prof, "research", "") or ""]).lower()
    shared = sorted(me.skills & set(tags(o.skills)))
    ints = [x for x in me.interests if hit(x, text)][:2]
    strength = 2 * min(len(shared), 3) + 2 * len(ints) + (1 if any(hit(x, o.title.lower()) for x in ints) else 0)
    other = _other_college(me, prof, lang)
    why = []
    if len(shared) >= 2: why.append(_say("skills", lang, n=len(shared), x=", ".join(shared[:4])))
    elif shared: why.append(_say("skill", lang, x=shared[0]))
    for x in ints: why.append(_say("interest", lang, x=x))
    picked = strength >= 4
    if picked and other: why.append(_say("college", lang, x=other))
    return picked, why if picked else [], other


def competition(me, c, status, days, lang="en"):
    """(for_you, reasons). Only competitions with a confirmed date that has not passed can be picked."""
    if not me.ready or status not in ("open", "closing"): return False, []
    text = f"{c.title} {c.description}".lower()
    ints = [x for x in me.interests if hit(x, text)][:2]
    words = set(me.interests) | me.skills
    cat_fit = c.category in CATEGORY_WORDS and any(w in words for w in CATEGORY_WORDS[c.category])
    why = [_say("interest", lang, x=x) for x in ints]
    if cat_fit and not ints: why.append(_say("category", lang, x=CAT_ZH.get(c.category, c.category) if lang == "zh" else c.category))
    picked = bool(ints) or cat_fit
    if picked and status == "closing" and days is not None: why.append(_say("closing", lang, n=days))
    return picked, why if picked else []
