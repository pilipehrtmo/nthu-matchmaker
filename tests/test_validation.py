"""Unit tests for app/validate.py. Run: python -m pytest tests/ (pytest is a development tool, not in requirements.txt)."""
import pytest
from app import validate as v


# 1. names
@pytest.mark.parametrize("name", ["John Smith", "王小明", "Anne-Marie", "O'Connor", "O’Brien", "José Álvarez", "Nguyễn Văn An",
                                  "Pilipe Hartomo Yee", "Mary J. Blige", "阿迪力·吐尔逊", "  Lena   Lead  ", "李"+"明"])
def test_names_accepted(name):
    assert v.name_problem(name) == ""

@pytest.mark.parametrize("name,why", [("asdf123", "numbers"), ("🔥🔥🔥", "letters"), ("A", "at least 2"), ("", "at least 2"), ("John_Smith", "letters"),
                                      ("<script>", "letters"), ("Lena 🔥", "letters"), ("x" * 61, "at most 60"), ("1234", "numbers"), ("--", "at least 2")])
def test_names_rejected(name, why):
    assert why in v.name_problem(name)


# 2. skills
def test_skills_trim_and_dedupe_case_insensitive():
    assert v.split_skills("  Python, python ,Figma,, figma , UI   design") == ["Python", "Figma", "UI design"]

def test_skills_chinese_commas():
    assert v.split_skills("Python，Figma、行銷") == ["Python", "Figma", "行銷"]

def test_skill_count_limit():
    assert v.skills_problem([f"s{i}" for i in range(20)]) == ""
    assert "at most 20" in v.skills_problem([f"s{i}" for i in range(21)])

def test_skill_length_limit():
    assert v.skills_problem(["x" * 30]) == ""
    assert "at most 30" in v.skills_problem(["x" * 31])

def test_custom_skills_allowed():
    assert v.skills_problem(["taiwanese sign language", "bubble tea making"]) == ""


# 3. skill typo suggestions (never applied, only offered)
@pytest.mark.parametrize("typo,want", [("phyton", "Python"), ("javasript", "JavaScript"), ("htlm", "HTML"), ("Figam", "Figma"), ("pytohn", "Python"),
                                       ("photshop", "Photoshop"), ("tensorflwo", "TensorFlow"), ("javascipt", "JavaScript")])
def test_skill_suggestions(typo, want):
    assert v.skill_suggestion(typo) == want

@pytest.mark.parametrize("ok", ["python", "Python", "figma", "ui design", "bubble tea making", "go", "r", "c++", "行銷", "law"])
def test_no_suggestion_for_correct_or_custom(ok):
    assert v.skill_suggestion(ok) == ""


# 4. email
@pytest.mark.parametrize("typo,want", [("john@gmial.com", "john@gmail.com"), ("john@gmail.con", "john@gmail.com"), ("a.b@yahooo.com", "a.b@yahoo.com"),
                                       ("x@outlok.com", "x@outlook.com"), ("x@hotmial.com", "x@hotmail.com"), ("s1@gap.nthu.edu.tw", "s1@gapp.nthu.edu.tw"),
                                       ("x@gmaill.com", "x@gmail.com"), ("x@gamil.com", "x@gmail.com")])
def test_email_suggestions(typo, want):
    assert v.email_suggestion(typo) == want

@pytest.mark.parametrize("ok", ["john@gmail.com", "s114006212@m114.nthu.edu.tw", "prof@cs.nthu.edu.tw", "x@gapp.nthu.edu.tw", "a@ntu.edu.tw", "b@nctu.edu.tw", "c@mail.ncku.edu.tw", "me@company.io"])
def test_no_email_suggestion(ok):
    assert v.email_suggestion(ok) == ""

@pytest.mark.parametrize("email,ok", [("john@gmail.com", True), ("a.b+tag@m114.nthu.edu.tw", True), ("no-at-sign", False), ("a@b", False),
                                      ("a@@b.com", False), ("a b@c.com", False), (".a@b.com", False), ("a..b@c.com", False), ("a@-b.com", False)])
def test_email_format(email, ok):
    assert v.email_ok(email) is ok


# 5. social handles
@pytest.mark.parametrize("kind,raw,clean", [("instagram", "@ben_ig", "ben_ig"), ("instagram", "https://www.instagram.com/ben.ig/", "ben.ig"),
                                            ("line", "Ben.Line", "ben.line"), ("line", "@my-id_1", "my-id_1"), ("discord", "Ben_Dev", "ben_dev"),
                                            ("discord", "a.b", "a.b"), ("instagram", "", "")])
def test_handles_ok(kind, raw, clean):
    assert v.handle_problem(kind, raw) == (clean, "")

@pytest.mark.parametrize("kind,raw", [("instagram", "x" * 31), ("instagram", "ben-ig"), ("instagram", ".ben"), ("instagram", "ben..ig"), ("instagram", "ben ig"),
                                      ("line", "abc"), ("line", "x" * 21), ("line", "李小明"), ("line", "ben line"),
                                      ("discord", "a"), ("discord", "x" * 33), ("discord", "ben#1234"), ("discord", "a..b")])
def test_handles_rejected(kind, raw):
    assert v.handle_problem(kind, raw)[1]


# 6. notes, descriptions, bio
def test_note_limits():
    assert "at least 20" in v.length_problem(v.normalize_text("   too short   "), v.NOTE_MIN, v.NOTE_MAX, "Your note")
    assert "at least 20" in v.length_problem(v.normalize_text(" " * 50), v.NOTE_MIN, v.NOTE_MAX, "Your note")
    assert v.length_problem("x" * 20, v.NOTE_MIN, v.NOTE_MAX, "Your note") == ""
    assert v.length_problem("x" * 1000, v.NOTE_MIN, v.NOTE_MAX, "Your note") == ""
    assert "at most 1000" in v.length_problem("x" * 1001, v.NOTE_MIN, v.NOTE_MAX, "Your note")

def test_windows_line_breaks_count_once():
    assert v.normalize_text("a\r\nb\rc") == "a\nb\nc"
    assert v.length_problem(v.normalize_text("x\r\n" * 250), 0, v.BIO_MAX, "Bio") == ""   # 499 characters as the browser counts them

def test_description_limits():
    assert "at least 30" in v.length_problem("", v.DESC_MIN, v.DESC_MAX, "The description")
    assert v.length_problem("x" * 30, v.DESC_MIN, v.DESC_MAX, "The description") == ""
    assert "at most 2000" in v.length_problem("x" * 2001, v.DESC_MIN, v.DESC_MAX, "The description")

def test_bio_limit():
    assert v.length_problem("x" * 500, 0, v.BIO_MAX, "Your bio") == ""
    assert "at most 500" in v.length_problem("x" * 501, 0, v.BIO_MAX, "Your bio")


# 9. competition links and dates
@pytest.mark.parametrize("url", ["https://example.org/cup", "https://www.bhuntr.com/tw/competitions/123?x=1", "https://sub.domain.nthu.edu.tw/p/1.php"])
def test_https_ok(url):
    assert v.https_url_problem(url) == ""

@pytest.mark.parametrize("url,why", [("http://example.org", "https://"), ("https//example.org", "https://"), ("ftp://x.org", "https://"),
                                     ("https://", "valid"), ("https://localhost/x", "valid"), ("https://exa mple.org", "spaces"),
                                     ("https://user:pw@example.org", "password"), ("https://example", "valid"), ("", "Add"), ("javascript:alert(1)", "https://")])
def test_https_rejected(url, why):
    assert why in v.https_url_problem(url)

def test_parse_date():
    assert str(v.parse_date("2027-03-01")) == "2027-03-01"
    assert v.parse_date("2027-02-30") is None and v.parse_date("30 Nov 2026") is None and v.parse_date("") is None
