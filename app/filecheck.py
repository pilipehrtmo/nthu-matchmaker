"""Check an uploaded research file by its CONTENT (not the name the browser sends) and pull out its text.

Allowed: PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), CSV, plain text, ZIP (datasets).
Refused: macro files (.docm/.xlsm/.pptm or any vbaProject), HTML, SVG, scripts and programs,
and anything whose content does not match its extension.
"""
import io, re, zipfile
from xml.etree import ElementTree

MAX_FILE = 25 * 1024 * 1024
MIME = {"pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv", "txt": "text/plain", "zip": "application/zip"}
ALLOWED = list(MIME)
OOXML_MAIN = {"docx": "word/document.xml", "pptx": "ppt/presentation.xml", "xlsx": "xl/workbook.xml"}
BLOCKED_IN_ZIP = re.compile(r"\.(exe|dll|bat|cmd|com|scr|msi|msp|ps1|psm1|vbs|vbe|js|jse|wsf|wsh|hta|jar|apk|app|sh|bash|"
                            r"html?|xhtml|svg|docm|xlsm|pptm|dotm|xltm|potm|lnk|reg|iso|dmg)$", re.I)
MAX_UNZIPPED = 400 * 1024 * 1024   # a zip that grows past this when opened is refused (zip bomb)
MAX_ENTRIES = 5000
MAX_TEXT = 200_000


class FileProblem(Exception): pass


def ext_of(filename):
    name = (filename or "").strip().lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""

def clean_name(filename, ext):
    """A display/download name: no folders, no control or quote characters, sensible length."""
    base = re.split(r"[\\/]", filename or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f\"<>|:*?;]", "", base).strip(" .") or f"file.{ext}"
    stem = base[: -(len(ext) + 1)] if base.lower().endswith("." + ext) else base
    return (stem[:100].strip() or "file") + "." + ext

def check(data: bytes, filename: str):
    """Return (ext, mime) or raise FileProblem with a message for the student."""
    if not data: raise FileProblem("The file is empty.")
    if len(data) > MAX_FILE: raise FileProblem("Files can be at most 25 MB.")
    ext = ext_of(filename)
    if ext in ("docm", "xlsm", "pptm", "dotm", "xltm", "potm"):
        raise FileProblem("Files with macros are not allowed. Save it as .docx, .xlsx or .pptx and upload again.")
    if ext not in ALLOWED:
        raise FileProblem("This file type is not allowed. Upload PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), CSV, TXT or ZIP.")
    if ext == "pdf":
        if not data[:1024].lstrip().startswith(b"%PDF-"): raise FileProblem("This is not a real PDF file.")
        if re.search(rb"/(JavaScript|Launch|EmbeddedFile)\b", data): raise FileProblem("This PDF contains scripts or embedded files, which are not allowed. Export it again as a plain PDF.")
    elif ext in OOXML_MAIN or ext == "zip":
        z = _zip(data)
        names = z.namelist()
        if ext in OOXML_MAIN:
            if "[Content_Types].xml" not in names or OOXML_MAIN[ext] not in names:
                raise FileProblem(f"This is not a real .{ext} file. Save it again from Word, PowerPoint or Excel.")
            types = z.read("[Content_Types].xml").decode("utf-8", "ignore").lower()
            if "macroenabled" in types or any(n.lower().endswith("vbaproject.bin") or "/activex/" in n.lower() for n in names):
                raise FileProblem("Files with macros are not allowed. Save it as a normal .docx, .xlsx or .pptx without macros.")
        else:
            if "[Content_Types].xml" in names and any(n in names for n in OOXML_MAIN.values()):
                raise FileProblem("This looks like an Office file renamed to .zip. Upload it with its real extension.")
            bad = [n for n in names if BLOCKED_IN_ZIP.search(n.rstrip("/"))]
            if bad: raise FileProblem(f"The ZIP contains a file type that is not allowed ({bad[0].split('/')[-1][:60]}). Remove it and try again.")
            if any(n.startswith(("/", "\\")) or ".." in n.replace("\\", "/").split("/") for n in names):
                raise FileProblem("The ZIP has unsafe folder names. Zip the files again.")
            if any(i.flag_bits & 0x1 for i in z.infolist()): raise FileProblem("Password-protected ZIP files are not allowed.")
    else:   # csv / txt
        if b"\x00" in data[:200_000] and not data.startswith((b"\xff\xfe", b"\xfe\xff")): raise FileProblem(f"This is not a plain .{ext} file.")
        if _decode(data) is None: raise FileProblem(f"This .{ext} file is not readable text. Save it as UTF-8 and try again.")
    return ext, MIME[ext]

def _zip(data):
    try: z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError): raise FileProblem("The file is damaged or not what its name says.")
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES: raise FileProblem("The ZIP has too many files in it.")
    total = sum(i.file_size for i in infos)
    if total > MAX_UNZIPPED or any(i.compress_size and i.file_size / i.compress_size > 200 for i in infos if i.file_size > 10_000_000):
        raise FileProblem("The file grows far too large when opened, so it was refused.")
    return z

def _decode(data):
    for enc in ("utf-8-sig", "utf-16", "cp950"):
        if enc == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")): continue
        try: return data.decode(enc)
        except UnicodeDecodeError: pass
    return None


# ---------- text for the compare view ----------
def text_of(data: bytes, ext: str) -> str:
    try: t = _text(data, ext)
    except Exception: t = ""
    t = re.sub(r"[ \t ]+", " ", t or "")
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t).strip()
    return t[:MAX_TEXT]

def _xml_text(xml, tags):
    root = ElementTree.fromstring(xml); out = []; line = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in tags and el.text: line.append(el.text)
        elif tag in ("p", "br") and line: out.append("".join(line)); line = []
    if line: out.append("".join(line))
    return "\n".join(out)

def _text(data, ext):
    if ext == "pdf":
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(data))
        return "\n\n".join((p.extract_text() or "") for p in r.pages[:200])
    if ext in ("csv", "txt"): return _decode(data) or ""
    if ext == "zip":
        z = zipfile.ZipFile(io.BytesIO(data))
        return "Files in this ZIP:\n" + "\n".join(f"{i.filename}  ({i.file_size:,} bytes)" for i in z.infolist()[:500])
    z = zipfile.ZipFile(io.BytesIO(data))
    if ext == "docx": return _xml_text(z.read("word/document.xml"), {"t"})
    if ext == "pptx":
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
        return "\n\n".join(f"— Slide {i} —\n" + _xml_text(z.read(n), {"t"}) for i, n in enumerate(slides[:300], 1))
    if ext == "xlsx":
        if "xl/sharedStrings.xml" not in z.namelist(): return ""
        return _xml_text(z.read("xl/sharedStrings.xml"), {"t"})
    return ""
