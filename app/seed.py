"""Curated annual competitions across faculties. Dates change every year: always open the link."""
from sqlmodel import Session, select
from .db import engine
from .config import DEMO_DATA
from .models import Competition, User, Post, Project, Role
A = "Annual · check site"
SEED = [
 ("Hult Prize", "Business", "https://www.hultprize.org", "Student startups solving a global social challenge. Open to every major."),
 ("CFA Institute Research Challenge", "Business", "https://www.cfainstitute.org/en/programs/research-challenge", "Analyse a listed company and pitch a stock report to professionals. Finance, economics, management."),
 ("MIT Solve Global Challenges", "Social Impact", "https://solve.mit.edu", "Tech-for-good solutions for health, climate and learning. Open to all backgrounds."),
 ("Falling Walls Lab", "Science & Health", "https://falling-walls.com/lab", "3-minute pitches of research ideas from any discipline, humanities included."),
 ("iGEM", "Science & Health", "https://igem.org", "Synthetic biology team competition. Needs biologists, but also designers, writers and coders."),
 ("James Dyson Award", "Design & Arts", "https://www.jamesdysonaward.org", "Design a product that solves a real problem. Engineers, industrial designers, medical students."),
 ("A' Design Award", "Design & Arts", "https://competition.adesignaward.com", "Large international award across graphic, architecture, fashion and interaction design."),
 ("Golden Pin Design Award", "Design & Arts", "https://www.goldenpin.org.tw", "Taiwan's best-known design award for Chinese-language markets."),
 ("Red Dot Design Award", "Design & Arts", "https://www.red-dot.org", "Product, brand and communication design. Student concept category available."),
 ("Student Academy Awards", "Design & Arts", "https://www.oscars.org/student-academy-awards", "Film competition for student filmmakers. Needs directors, writers, editors, sound."),
 ("Philip C. Jessup Moot Court", "Law & Policy", "https://www.ilsa.org/jessup", "International law moot. Team of law students, with research and speaking roles."),
 ("Willem C. Vis Moot", "Law & Policy", "https://vismoot.pace.edu", "International commercial arbitration moot for law students."),
 ("COMAP MCM/ICM Modeling Contest", "Science & Health", "https://www.contest.comap.com", "4-day math modeling contest. Math, stats, coding and writing roles."),
 ("Kaggle Competitions", "Tech & Data", "https://www.kaggle.com/competitions", "Data science contests. Pair data people with domain experts from health, finance or social science."),
 ("Google Solution Challenge", "Tech & Data", "https://developers.google.com/community/gdsc-solution-challenge", "Build an app for the UN SDGs. Developers plus designers and subject experts."),
 ("NSTC Undergraduate Research Grant (大專學生研究計畫)", "Science & Health", "https://www.nstc.gov.tw", "Taiwan's national grant for undergraduate research projects, all fields. Needs an advisor."),
]
# Taiwan competitions with known dates (deadline, online). Checked against the official site.
TW_SEED = [
 ("DeployAI — An AI Case Competition", "Tech & Data", "https://www.deployai-case.com/",
  "AI case competition by Celadon Partners with NTHU University Science Park and NTHU Startup Garage. Teams of 3-4 students from any university and major; 11-day remote build sprint, in-person finals at NTHU. NT$100,000 first prize.",
  "2026-10-27", False),
]
ONLINE_URLS = {"https://www.kaggle.com/competitions", "https://www.contest.comap.com", "https://developers.google.com/community/gdsc-solution-challenge",
               "https://www.jamesdysonaward.org", "https://competition.adesignaward.com"}   # entered entirely online
def seed():
    with Session(engine) as s:
        for title, cat, url, desc in SEED:
            c = s.exec(select(Competition).where(Competition.url == url)).first()
            if not c:
                s.add(Competition(title=title, category=cat, url=url, source="curated", deadline=A, description=desc, needs_review=False, online=url in ONLINE_URLS, online_checked=True))
            elif not c.online_checked:
                c.online, c.online_checked = url in ONLINE_URLS, True; s.add(c)
        for title, cat, url, desc, deadline, online in TW_SEED:
            if not s.exec(select(Competition).where(Competition.url == url)).first():
                s.add(Competition(title=title, category=cat, url=url, source="curated", deadline=deadline, description=desc, needs_review=False, online=online, online_checked=True))
        s.commit()

STARTER = [
 ("General", "Welcome! How this site works", "1) Browse open seats on the home page or post your own project. 2) Apply with a short note. 3) When a lead accepts you, you see each other's contact. Use this space to ask questions and meet people from other faculties. Posts here by Team 22 are starter prompts, not real users."),
 ("Find a team", "How to write a seat description people reply to", "Name the role, the 2 or 3 skills you need, the hours per week, and the deadline. 'UI designer, Figma, 5 h/week, team by 30 Nov' gets more replies than 'looking for teammates'."),
 ("Find a team", "What skill do you wish your team had?", "Tell us the skill you could never find in your own department. We want to see what people are missing most."),
 ("Business", "Which competition would you enter if you had a designer on your team?", "Share the competition and the kind of teammate you would need."),
 ("Design & Arts", "Designers: what do engineers get wrong when they ask for help?", "Share what makes a request easy or hard to say yes to."),
 ("Law & Policy", "Law students: would you join a tech or business team?", "Tell us what kind of project would make it worth your time."),
 ("Science & Health", "Ideas where health or biology meets data and design", "Post a problem you care about and what skills it would need."),
 ("Social Impact", "Which problem in Hsinchu or on campus would you build for?", "Post an idea and the team it would need."),
 ("Tech & Data", "Tech students: what would make you invite a non-tech teammate?", "Be honest. What do you worry about, and what would help?"),
]
EXAMPLES = [
 ("[Example] Campus health app for a hackathon", "A sample project posted by Team 22 to show how a post looks. Apply to see the match percentage.", [("UI designer", "figma, ux research"), ("Data analyst", "python, statistics"), ("Pitcher", "public speaking, storytelling")], None),
 ("[Example] Social enterprise pitch for the Hult Prize", "A sample project posted by Team 22 to show how a post looks.", [("Financial analyst", "excel, financial modeling"), ("Marketing lead", "social media, branding"), ("Legal advisor", "contract law, policy research")], "https://www.hultprize.org"),
]
def seed_starter():
    """Team account with starter threads and two clearly labelled example projects (removable by admins). Runs once."""
    with Session(engine) as s:
        if s.exec(select(User).where(User.email == "team@matchmaker.local")).first(): return
        t = User(email="team@matchmaker.local", handle="team-22", name="Team 22", student_id="TEAM22", verified=True,
                 bio="The team that built this site. Our posts are starter prompts, not real users.")
        s.add(t); s.commit(); s.refresh(t)
        for topic, title, body in STARTER: s.add(Post(author_id=t.id, topic=topic, title=title, body=body))
        for title, desc, seats, url in ([] if DEMO_DATA else EXAMPLES):   # demo mode loads demo_data.py instead
            comp = s.exec(select(Competition).where(Competition.url == url)).first() if url else None
            pr = Project(owner_id=t.id, title=title, description=desc, hours_per_week=5, deadline="2026-11-30", competition_id=comp.id if comp else None, kind="Competition")
            s.add(pr); s.commit(); s.refresh(pr)
            for name, sk in seats: s.add(Role(project_id=pr.id, name=name, skills=sk))
        s.commit()


def seed_examples():
    """More clearly labelled [Example] projects (startup, research, side project, club). Posted by the team-22 account.
    Adds any that are missing, so it also works on an existing database. Admins can delete them like any project."""
    from datetime import datetime, timedelta
    from .demo_data import PROJECTS
    with Session(engine) as s:
        t = s.exec(select(User).where(User.email == "team@matchmaker.local")).first()
        if not t: return
        today = datetime.utcnow().date()
        for owner, kind, title, desc, hours, days, url, seats in PROJECTS:
            if kind == "Competition": continue          # the Hult Prize example already exists
            title = "[Example] " + title
            if s.exec(select(Project).where(Project.title == title)).first(): continue
            pr = Project(owner_id=t.id, kind=kind, title=title, description=desc, hours_per_week=hours,
                         deadline=(today + timedelta(days=days)).isoformat())
            s.add(pr); s.commit(); s.refresh(pr)
            for name, sk in seats: s.add(Role(project_id=pr.id, name=name, skills=sk))
        s.commit()
