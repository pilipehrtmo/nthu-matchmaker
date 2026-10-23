"""Read a CV (PDF, Word or text) and suggest profile fields.

Runs fully on this computer with simple rules: no cloud AI, and the file is never saved.
The student always checks the suggestions before pressing Save.
"""
import io, re, zipfile
from xml.etree import ElementTree

MAX_BYTES = 5 * 1024 * 1024

# Skills across faculties. Skills already used on the site are added at runtime.
SKILLS = """
python, java, javascript, typescript, c, c++, c#, go, rust, kotlin, swift, php, ruby, r, matlab, sql, html, css,
react, vue, angular, next.js, node.js, django, flask, fastapi, spring, flutter, react native, android, ios, unity, unreal,
git, github, docker, kubernetes, linux, aws, gcp, azure, firebase, mongodb, postgresql, mysql, rest api, graphql,
machine learning, deep learning, pytorch, tensorflow, scikit-learn, pandas, numpy, nlp, computer vision, llm,
data analysis, data visualization, statistics, excel, power bi, tableau, spss, stata, web scraping,
figma, adobe xd, photoshop, illustrator, indesign, premiere pro, after effects, canva, blender, 3d modeling, autocad,
solidworks, ui design, ux research, ui/ux, graphic design, video editing, photography, animation, illustration,
arduino, raspberry pi, embedded systems, pcb design, verilog, fpga, circuit design, robotics, iot, cad,
marketing, digital marketing, social media, seo, copywriting, content writing, branding, market research,
business plan, financial modeling, accounting, finance, valuation, project management, product management,
public speaking, pitching, presentation, negotiation, sales, leadership, teamwork, event planning,
research, lab work, biology, chemistry, physics, bioinformatics, psychology, economics, law, policy, education,
english, chinese, mandarin, japanese, korean, indonesian, translation, writing
"""
ALIASES = {"js": "javascript", "ts": "typescript", "py": "python", "ml": "machine learning", "dl": "deep learning",
           "ps": None, "ux": "ux research", "ui": "ui design", "ppt": "presentation", "powerpoint": "presentation",
           "ms excel": "excel", "microsoft excel": "excel", "reactjs": "react", "react.js": "react", "nodejs": "node.js",
           "vuejs": "vue", "nextjs": "next.js", "postgres": "postgresql", "sklearn": "scikit-learn",
           "golang": "go", "premiere": "premiere pro", "aftereffects": "after effects", "ai": None}
# Words that are skills but also ordinary English; only count them inside a skills section.
AMBIGUOUS = {"c", "r", "go", "swift", "rust", "ruby", "unity", "spring", "flutter", "excel", "research", "writing",
             "english", "chinese", "law", "policy", "education", "finance", "sales", "leadership", "teamwork",
             "physics", "chemistry", "biology", "economics", "psychology", "animation", "photography", "branding"}

SECTION = re.compile(r"^\s*(summary|profile|about me|about|objective|professional summary|自我介紹|簡介|自傳)\s*:?\s*$", re.I)
SKILL_HDR = re.compile(r"(skills?|technical skills|tools|technologies|languages|competenc|專長|技能)", re.I)
HEADER = re.compile(r"^\s*(education|experience|work experience|projects?|skills?|awards?|honors?|activities|"
                    r"leadership|certifications?|languages|publications|volunteer|references|interests|學歷|經歷|專案|技能|獲獎)\s*:?\s*$", re.I)
FAC_PATTERNS = [
    re.compile(r"(?:department|dept\.?|school|college|faculty|institute)\s+of\s+([A-Z][A-Za-z&,\- ]{3,50})", re.I),
    re.compile(r"(?:b\.?s\.?c?\.?|b\.?a\.?|bachelor(?:'s)?(?: of [a-z]+)?|m\.?s\.?|master(?:'s)?(?: of [a-z]+)?)\s*(?:degree\s*)?(?:in|,)\s+([A-Z][A-Za-z&\- ]{3,50})", re.I),
    re.compile(r"\bmajor(?:ing)?\s*(?:in|:)\s*([A-Za-z&\- ]{3,50})", re.I),
    re.compile(r"([一-鿿]{2,12}(?:學系|系|研究所|學院|學位學程))"),
]
CONTACT = [
    ("LINE", re.compile(r"\bline(?:\s*id)?\s*[:：]\s*@?([\w.\-]{3,30})", re.I)),
    ("Discord", re.compile(r"\bdiscord\s*[:：]\s*@?([\w.#\-]{2,40})", re.I)),
    ("IG", re.compile(r"\b(?:ig|instagram)\s*[:：]\s*@?([\w.]{2,30})", re.I)),
    ("IG", re.compile(r"instagram\.com/([\w.]{2,30})", re.I)),
]
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


class CVError(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if len(data) > MAX_BYTES:
        raise CVError("The file is larger than 5 MB.")
    if name.endswith(".pdf") or data[:4] == b"%PDF":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise CVError("PDF reading is not installed. Stop the server, run: pip install pypdf, then start it again.")
        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:6])
        except Exception:
            raise CVError("Could not read this PDF. Try exporting it again, or upload a .docx file.")
        if len(text.strip()) < 30:
            raise CVError("This PDF looks like a scanned image, so there is no text to read. Upload a text PDF or .docx.")
        return text
    if name.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                root = ElementTree.fromstring(z.read("word/document.xml"))
        except Exception:
            raise CVError("Could not read this Word file.")
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        lines = []
        for p in root.iter(ns + "p"):
            lines.append("".join(t.text or "" for t in p.iter(ns + "t")))
        return "\n".join(lines)
    if name.endswith(".txt"):
        return data.decode("utf-8", "ignore")
    raise CVError("Please upload a PDF, .docx or .txt file.")


def _find_skills(text: str, extra: set[str]) -> list[str]:
    vocab = {s.strip() for s in SKILLS.replace("\n", " ").split(",") if s.strip()} | {e for e in extra if 1 < len(e) < 30}
    low = text.lower()
    # text inside a skills section, where short words like "C" or "R" are safe to count
    skill_zone, on = [], False
    for line in text.splitlines():
        if SKILL_HDR.search(line) and len(line) < 60:
            on = True
            rest = line.split(":", 1)[1] if ":" in line else ""
            skill_zone.append(rest); continue
        if on and HEADER.match(line):
            on = False
        if on:
            skill_zone.append(line)
    zone = "\n".join(skill_zone).lower()

    def where(term, hay):
        m = re.search(r"(?<![\w+#.])" + re.escape(term) + r"(?![\w+#])", hay)
        return m.start() if m else -1

    def present(term, hay):
        return where(term, hay) >= 0

    found = []
    for term in sorted(vocab, key=len, reverse=True):
        hay = zone if term in AMBIGUOUS else low
        if hay and present(term, hay) and term not in found:
            found.append(term)
    for short, full in ALIASES.items():
        if full and full not in found and present(short, zone or low):
            found.append(full)
    # drop parts of longer matches ("react" when "react native" was found)
    found = [f for f in found if not any(f != g and f in g.split() for g in found)]
    order = {t: where(t, zone if t in AMBIGUOUS else low) + (len(low) if t in AMBIGUOUS else 0) for t in found}
    return sorted(found, key=lambda t: order[t])[:15]


def _find_faculty(text: str) -> str:
    for pat in FAC_PATTERNS:
        m = pat.search(text)
        if m:
            fac = re.split(r"\s{2,}|[,|•·\n(]|\s+(?:at|national|university|nthu|20\d\d|19\d\d)\b", m.group(1).strip(), flags=re.I)[0]
            fac = fac.strip(" -&")
            if 3 <= len(fac) <= 40:
                return fac.title() if fac.isascii() else fac
    return ""


FIELD = {"LINE": "line", "IG": "instagram", "Discord": "discord"}
LINKS = [
    ("linkedin", re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%]+/?", re.I)),
    ("github", re.compile(r"(?:https?://)?github\.com/(?!orgs/|features|about)[\w\-]+/?(?![\w/])", re.I)),
    ("behance", re.compile(r"(?:https?://)?(?:www\.)?(?:behance\.net|dribbble\.com)/[\w\-]+/?", re.I)),
    ("scholar", re.compile(r"(?:https?://)?(?:scholar\.google\.[a-z.]+/citations\?user=[\w\-]+|orcid\.org/\d{4}-\d{4}-\d{4}-\d{3}[\dX])", re.I)),
    ("website", re.compile(r"(?:portfolio|website|web|site)\s*[:：]\s*((?:https?://)?[\w\-]+(?:\.[\w\-]+)+(?:/[\w\-./]*)?)", re.I)),
]


def _find_contacts(text: str) -> dict:
    out = {}
    for label, pat in CONTACT:
        m = pat.search(text)
        if m and FIELD[label] not in out:
            out[FIELD[label]] = m.group(1)
    return out


def _find_links(text: str) -> dict:
    out = {}
    for field, pat in LINKS:
        m = pat.search(text)
        if m:
            v = m.group(1) if pat.groups else m.group(0)
            v = v.rstrip("/.,;)")
            out[field] = v if v.lower().startswith("http") else "https://" + v
    return out


def _find_bio(text: str, faculty: str, skills: list[str]) -> str:
    lines = [l.strip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if SECTION.match(line):
            body = []
            for nxt in lines[i + 1:]:
                if HEADER.match(nxt) or SECTION.match(nxt): break
                if nxt: body.append(nxt)
                if sum(map(len, body)) > 400: break
            bio = re.sub(r"\s+", " ", " ".join(body)).strip()
            if len(bio) > 20:
                if len(bio) > 400:
                    cut = bio[:400].rsplit(". ", 1)[0]
                    bio = (cut if len(cut) > 120 else bio[:400].rsplit(" ", 1)[0]) + "."
                return bio
    if faculty or skills:
        who = f"{faculty} student" if faculty else "Student"
        return f"{who} with experience in {', '.join(skills[:4])}." if skills else f"{who}."
    return ""


def parse_cv(filename: str, data: bytes, known_skills: set[str] = frozenset()) -> dict:
    text = extract_text(filename, data)
    text = text.replace(" ", " ").replace("\r", "")
    skills = _find_skills(text, set(known_skills))
    faculty = _find_faculty(text)
    contacts = _find_contacts(text)
    email = EMAIL.search(text)
    return {"skills": skills, "faculty": faculty, "contacts": contacts, "links": _find_links(text),
            "contact": email.group(0) if email and not contacts else "",   # "other" contact only as a fallback
            "bio": _find_bio(text, faculty, skills)}
