"""Department dataset, choice rules and the profile migration."""
import json, os, re
from sqlalchemy import create_engine, text
from app import departments as D
from app import dept_migrate as M

DATA = json.load(open(os.path.join(os.path.dirname(D.__file__), "departments.json"), encoding="utf-8"))
U = DATA["units"]


# ---- data validation ----
def test_counts():
    assert len(U) == 127
    assert sum(u["en_status"] == "official" for u in U) == 126
    assert [u["id"] for u in U if u["en_status"] == "proposed"] == ["eng-ieem-ex"]
    assert sum(not u["active"] for u in U) == 4


def test_no_duplicates_or_blanks():
    for f in ("id", "zh", "en"):
        vals = [u[f] for u in U]
        assert len(vals) == len(set(vals)), f
    for u in U:
        assert u["zh"].strip() and u["en"].strip()
        assert u["en"] == " ".join(u["en"].split())
        assert "Institute of Institute" not in u["en"] and "Internaional" not in u["en"] and "Envionmental" not in u["en"]


def test_colleges_and_sources():
    for u in U:
        assert u["colleges"] and set(u["colleges"]) <= set(D.COLLEGES)
        assert u["en_source"] in DATA["sources"]
    assert D.UNITS["als"]["colleges"] == ["sci", "nuc"]          # one record, two colleges
    assert {u["id"] for u in U if "oaa" in u["colleges"]} == {"oaa-iphd", "oaa-ims", "oaa-smem", "oaa-sbm", "oaa-rs"}
    assert D.COLLEGES["oaa"]["kind"] == "cross_college" and D.COLLEGES["sus"]["en_status"] == "official"
    assert all(u["colleges"] == ["legacy"] and not u["active"] for u in U if u["id"].startswith("old-"))


def test_reviewed_names():
    want = {"sci-stat": "Institute of Statistics and Data Science", "hss-tws": "Graduate Program of Taiwan Studies for In-service Teachers",
            "tm-demba": "NTHU-UTA Dual EMBA Degree Program", "eecs-sec": "Institute of Information Security", "eng-space": "Institute of Space Engineering",
            "eng-bme": "Institute of Biomedical Engineering", "arts-ita": "Graduate Institute of Art and Technology", "hss-sino": "Institute of Sinophone Studies",
            "eng-pfmi": "Ph.D. Program in Prospective Functional Materials Industry", "lsm-mi": "Master Program in Medical Informatics",
            "lsm-bti": "Ph.D. Program in Bioindustrial Technology", "oaa-sbm": "Ph.D. Program in Biomedical Artificial Intelligence",
            "sus-st": "Master's Program in Sustainable Technology", "sus-isdc": "Institute of Sustainable Development and Climate Policy"}
    for k, v in want.items(): assert D.UNITS[k]["en"] == v and D.UNITS[k]["en_status"] == "official", k


def test_ibp_tracks():
    ibp = D.UNITS["thc-ibp"]
    assert ibp["colleges"] == ["thc"]
    assert [t["en"] for t in ibp["tracks"]] == ["Electrical Engineering & Computer Science", "Business Management", "Engineering Technology",
                                                 "Education Sciences", "International Chinese Language with Multiple Disciplines (Group A)"]
    assert not any("IBP" in u["en"] for u in U if u["id"] != "thc-ibp")   # tracks are not departments


def test_legacy_aliases():
    for k, v in DATA["legacy_aliases"].items():
        if "unit" in v: assert v["unit"] in D.UNITS
        elif "college" in v: assert v["college"] in D.COLLEGES
        else: assert v.get("review")


# ---- choice rules ----
def test_dropdown_groups():
    g = D.groups("en"); vals = [v for _, o in g for v, _ in o]
    assert len(vals) == len(set(vals))
    assert not any(v.startswith("old-") for v in vals)            # phased-out units hidden from students
    assert all(f"c:{c}" in vals for c, x in D.COLLEGES.items() if x["kind"] != "phased_out")   # "not chosen yet" for every college
    assert vals.count("als") == 1
    admin = [v for _, o in D.groups("en", admin=True) for v, _ in o]
    assert "old-am" in admin and "thc-ibp|eecs" in admin and "thc-ibp" not in admin
    assert D.groups("zh")[0][0] == "理學院"


def test_choose():
    f, e = D.choose("eecs-cs"); assert not e and f["dept_id"] == "eecs-cs" and f["dept_status"] == "ok" and f["faculty"] == "Department of Computer Science"
    f, e = D.choose("thc-ibp", "eecs"); assert f["dept_track"] == "eecs" and f["faculty"] == "IBP · Electrical Engineering & Computer Science"
    assert D.choose("thc-ibp", "")[1] == "Choose your IBP track."
    assert D.choose("c:eecs")[0]["dept_id"] == "c:eecs"
    f, e = D.choose("other", "", "  Exchange   student "); assert f["dept_status"] == "other" and f["dept_id"] == "" and f["faculty"] == "Exchange student"
    assert D.choose("other", "", "x")[1] and D.choose("other", "", "x" * 61)[1]
    assert D.choose("old-am")[1] and D.choose("nope")[1] and D.choose("eecs-cs", "eecs")[0]["dept_track"] == ""
    assert D.choose("") == (None, "")
    assert D.choose("none")[0]["dept_id"] == ""


def test_labels():
    assert D.label("thc-ibp", "bm", "zh") == "清華學院國際學士班 · 商業管理"
    assert D.label("c:hss", "", "en") == "College of Humanities and Social Sciences (department not chosen yet)"
    assert D.label("old-am", "", "en") == "Department of Applied Mathematics" and D.label("zzz") == ""


def test_map_legacy_never_guesses():
    assert D.map_legacy("IBP EECS") == dict(dept_id="thc-ibp", dept_track="eecs", dept_status="ok")
    assert D.map_legacy("Computer Science")["dept_id"] == "eecs-cs"
    assert D.map_legacy("EECS")["dept_status"] == "review" and D.map_legacy("EECS")["dept_id"] == ""
    assert D.map_legacy("Electrical Engineering and Computer Science")["dept_status"] == "review"
    assert D.map_legacy("資訊工程學系")["dept_id"] == "eecs-cs"
    assert D.map_legacy("comp sci")["dept_status"] == "review"
    assert D.map_legacy("") is None and D.map_legacy("   ") is None
    assert D.guess("Department of Computer Science") == "eecs-cs" and D.guess("Computer Science") == "" and D.guess("MBA") == "tm-mba"


def test_admin_choice():
    assert D.admin_choice("thc-ibp|es") == ("thc-ibp", "es") and D.admin_choice("old-hre") == ("old-hre", "")
    assert D.admin_choice("thc-ibp") is None and D.admin_choice("") is None and D.admin_choice("c:legacy") is None


# ---- migration ----
def _db(rows):
    e = create_engine("sqlite://")
    with e.begin() as c:
        c.execute(text('CREATE TABLE "user" (id INTEGER PRIMARY KEY, faculty VARCHAR DEFAULT \'\', faculty_orig VARCHAR DEFAULT \'\', dept_id VARCHAR DEFAULT \'\', '
                       'dept_track VARCHAR DEFAULT \'\', dept_status VARCHAR DEFAULT \'\', dept_src VARCHAR DEFAULT \'\')'))
        for i, f, *rest in rows:
            c.execute(text('INSERT INTO "user" (id, faculty, dept_id, dept_status, dept_src) VALUES (:i, :f, :d, :s, :src)'),
                      dict(i=i, f=f, d=rest[0] if rest else "", s=rest[1] if rest else "", src=rest[2] if rest else ""))
    return e


def _rows(e):
    with e.begin() as c: return {r[0]: tuple(r[1:]) for r in c.execute(text('SELECT id, faculty, faculty_orig, dept_id, dept_track, dept_status, dept_src FROM "user"'))}


PROD = [(1, ""), (2, "IBP EECS"), (3, "IBP EECS"), (4, "Electrical Engineering"), (5, "College of Semiconductor Research"), (6, "EECS"),
        (7, "Electrical Engineering and Computer Science"), (8, "Humanities and Social Sciences"), (9, "Computer Science"),
        (10, "Department of Computer Science"), (11, "College of Life Sciences and Medicine"), (12, " Computer Science "),
        (13, "Physics", "sci-phys", "ok", "user")]


def test_migration_maps_safely_and_keeps_text():
    e = _db(PROD); before = _rows(e)
    M.apply(e); after = _rows(e)
    for i in before: assert after[i][0] == before[i][0]              # faculty never changes
    assert after[2][2:] == ("thc-ibp", "eecs", "ok", "migration") and after[2][1] == "IBP EECS"
    assert after[4][2] == "eecs-ee" and after[5][2] == "c:semi" and after[8][2] == "c:hss" and after[9][2] == after[10][2] == after[12][2] == "eecs-cs"
    assert after[6][2:] == ("", "", "review", "migration") and after[7][4] == "review"   # ambiguous: admin review, no guess
    assert after[1] == ("", "", "", "", "", "")                       # empty stays empty
    assert after[13][2:] == ("sci-phys", "", "ok", "user")            # an existing link is not touched
    assert M.verify(e) == []
    with e.begin() as c: assert c.execute(text("SELECT COUNT(*) FROM dept_migration_backup")).scalar() == len(PROD)


def test_migration_is_repeatable_and_rolls_back():
    e = _db(PROD); M.apply(e); once = _rows(e); M.apply(e); assert _rows(e) == once
    M.rollback(e); back = _rows(e)
    for i, r in back.items():
        if i == 13: assert r[2:] == ("sci-phys", "", "ok", "user")
        else: assert r[2:] == ("", "", "", "")
        assert r[0] == dict((x[0], x[1]) for x in PROD)[i]


def test_sql_matches_apply():
    s = M.sql([f for _, f, *__ in PROD])
    assert s.startswith("BEGIN;") and s.rstrip().endswith("COMMIT;")
    assert "DELETE" not in s.upper() and "DROP" not in s.upper() and "SET faculty =" not in s
    assert "TRIM(faculty) = 'IBP EECS'" in s and "'EECS'" not in s.replace("TRIM(faculty) = 'EECS'", "!")  # ambiguous text gets no link statement
    assert "ENABLE ROW LEVEL SECURITY" in s
