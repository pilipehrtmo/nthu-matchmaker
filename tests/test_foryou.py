"""'For you' picks and track-record counting rules (pure logic, no database)."""
from types import SimpleNamespace as NS
from app import foryou as FY
from app.reputation import counts, tag_label, QUALITIES


def student(**kw):
    d = dict(skills="python,sql,react", interests="machine learning,health", roles_wanted="backend developer", hours=8,
             dept_id="eecs-cs", is_faculty=False)
    d.update(kw); return NS(**d)


def proj(**kw):
    d = dict(title="Clinic triage", description="We use machine learning to sort messages", category="", kind="Side project",
             tags="ML:purple", needs="", hours_per_week=6)
    d.update(kw); return NS(**d)


def seat(name="Backend developer", skills="python,sql"): return NS(name=name, skills=skills)
def owner(dept="eecs-cs"): return NS(dept_id=dept)


def test_complete_profile_gets_explained_pick():
    ok, why, other = FY.project(FY.Me(student()), proj(), [seat()], owner())
    assert ok and other == ""
    assert "Matches 2 of your skills: python, sql" in why and "Needs a Backend developer, a role you want" in why
    assert "Related to your interest in machine learning" in why and "Fits your 8 h/week" in why


def test_reasons_in_chinese():
    ok, why, _ = FY.project(FY.Me(student()), proj(), [seat()], owner(), "zh")
    assert ok and "符合你 2 項技能：python, sql" in why and "和你感興趣的「machine learning」相關" in why


def test_empty_profile_gets_nothing_and_says_what_to_add():
    me = FY.Me(student(skills="", interests="", roles_wanted=""))
    assert not me.ready and me.missing() == ["skills", "interests", "roles"]
    assert FY.project(me, proj(), [seat()], owner()) == (False, [], "")


def test_one_weak_signal_is_not_enough():
    me = FY.Me(student(interests="", roles_wanted=""))
    assert not FY.project(me, proj(), [seat(skills="python,docker")], owner())[0]   # one shared skill only
    assert FY.project(me, proj(), [seat(skills="python,sql")], owner())[0]          # two shared skills


def test_too_many_hours_is_not_for_you():
    assert not FY.project(FY.Me(student()), proj(hours_per_week=20), [seat()], owner())[0]


def test_other_college_is_named():
    ok, why, other = FY.project(FY.Me(student()), proj(), [seat()], owner("tm-qf"))
    assert ok and other and any(w.startswith("From another college: ") for w in why)


def test_interest_matches_whole_words_only():
    me = FY.Me(student(skills="", roles_wanted="", interests="ai, art"))
    p = proj(title="Party planning", description="She said the cart was ready", tags="")
    assert not FY.project(me, p, [seat(skills="")], owner())[0]
    assert FY.hit("ai", "applied ai for clinics") and not FY.hit("ai", "said") and FY.hit("c++", "we use c++ here")
    assert FY.hit("機器學習", "用機器學習分類訊息")


def test_research_position():
    o = NS(title="Machine learning for health records", description="Use python to study health data", skills="python,statistics",
           requirements="", owner_id=9)
    ok, why, other = FY.opening(FY.Me(student()), o, NS(research="", dept_id="lsm-ms"))
    assert ok and "Matches your skill: python" in why and other
    assert not FY.opening(FY.Me(student(is_faculty=True)), o, NS(research="", dept_id=""))[0]   # professors are not recommended positions


def test_competitions_never_expired_or_undated():
    me = FY.Me(student())
    c = NS(title="Machine learning cup", description="", category="Tech & Data")
    assert FY.competition(me, c, "open", 30)[0]
    assert not FY.competition(me, c, "past", -3)[0]
    assert not FY.competition(me, c, "unknown", None)[0]
    ok, why = FY.competition(me, c, "closing", 5)
    assert ok and "Closes in 5 days" in why
    other = NS(title="Poetry slam", description="", category="Design & Arts")
    assert not FY.competition(me, other, "open", 30)[0]


def row(**kw):
    d = dict(lead_status="confirmed", member_status="confirmed", is_lead=False); d.update(kw); return NS(**d)


def test_counting_rules():
    assert counts(row())
    assert not counts(row(member_status="pending")) and not counts(row(member_status="disputed"))
    assert not counts(row(lead_status="not_included"))
    assert counts(row(is_lead=True), others_ok=True) and not counts(row(is_lead=True), others_ok=False)


def test_endorsement_labels_are_positive_and_bilingual():
    assert tag_label("q:reliable") == "Reliable communication" and tag_label("q:reliable", "zh") == "溝通可靠"
    assert tag_label("s:python") == "python"
    bad = ("bad", "poor", "lazy", "late", "rude", "unreliable")
    assert not any(b in en.lower() for _, en, _ in QUALITIES for b in bad)
