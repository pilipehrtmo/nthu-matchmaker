"""Realistic projects for presentations, pitches and demo videos.

Loaded ONLY when DEMO_DATA=1 (run-demo.bat), which also switches to a separate demo.db,
so real students never see or apply to these teams.
"""
from datetime import datetime, timedelta
from sqlmodel import Session, select
from .db import engine
from .models import Competition, Project, Role, User

OWNERS = [  # handle, faculty, bio, skills
    ("yuchen-w", "Quantitative Finance", "Third-year QF student. Ran a used-book stall for two years and want to take it online.", "financial modeling, excel, pitching"),
    ("kai-lab", "Environmental Science", "Undergrad researcher in an atmospheric science lab. Interested in low-cost sensors.", "research, python, arduino"),
    ("hsu-builds", "Computer Science", "I build web apps on weekends and like shipping small tools for campus.", "react, python, sql"),
    ("mira-events", "Foreign Languages", "Organiser in two student clubs. I like bringing different majors into one room.", "event planning, english, social media"),
    ("ting-psy", "Psychology", "Interested in how students choose teammates and why groups fall apart.", "research, statistics, spss"),
]

PROJECTS = [  # owner, kind, title, description, hours, days to deadline, competition url, seats
    ("yuchen-w", "Startup", "ShelfSwap: second-hand textbooks between NTHU students",
     "Students buy and sell last semester's textbooks on campus, no shipping. We already have 40 people on a waiting list from a Google Form. "
     "Next step is a simple web app and a launch before final exams.",
     6, 30, None, [("Full-stack developer", "react, python, sql"), ("Growth marketer", "social media, branding, copywriting"), ("UI designer", "figma, ui design")]),
    ("hsu-builds", "Startup", "StudyBuddy TW: bilingual tutoring matches for international students",
     "International students need help with Mandarin coursework; local students want English practice. We match them for paid or swap sessions. "
     "Looking for co-founders to test it with two dorms this semester.",
     5, 45, None, [("Business lead", "financial modeling, pitching, market research"), ("Content writer (中/EN)", "translation, copywriting, chinese, english")]),
    ("kai-lab", "Research", "Low-cost air quality sensors around Hsinchu",
     "Place ten cheap PM2.5 sensors around campus and nearby streets, compare them with government stations, and map the gaps. "
     "We plan to apply for the NSTC undergraduate research grant with an advisor.",
     4, 25, None, [("Data analyst", "python, pandas, data visualization"), ("Hardware builder", "arduino, iot, circuit design"), ("Grant writer", "research, writing")]),
    ("ting-psy", "Research", "Why student teams fall apart: an interview study",
     "A small qualitative study on how NTHU students form teams for courses and competitions, and what makes them break up. "
     "Interviews in Chinese or English, then coding the answers together.",
     3, 20, None, [("Interviewer", "psychology, research, chinese"), ("Survey designer", "statistics, spss, research")]),
    ("hsu-builds", "Side project", "Open-source course review site for NTHU",
     "Honest, searchable reviews of NTHU courses, written by students and moderated by students. Open source on GitHub so it outlives us.",
     4, 40, None, [("Frontend developer", "react, css, html"), ("Backend developer", "python, fastapi, sql"), ("Community moderator", "social media, writing")]),
    ("mira-events", "Club or event", "Cross-faculty demo night in December",
     "One evening where student teams from any faculty show what they built this semester: apps, research posters, films, business plans. "
     "We need a small crew to run it.",
     3, 35, None, [("Event planner", "event planning, leadership"), ("Video editor", "premiere pro, video editing"), ("Designer for posters", "illustrator, graphic design")]),
    ("yuchen-w", "Competition", "Hult Prize team: clean water for rural schools",
     "A social enterprise that rents water filters to rural schools in Taiwan and Southeast Asia. Pitch due before the on-campus round.",
     5, 28, "https://www.hultprize.org", [("Financial analyst", "excel, financial modeling"), ("Pitcher", "public speaking, storytelling"), ("Field researcher", "research, market research")]),
]


def seed_demo():
    with Session(engine) as s:
        owners = {}
        for i, (handle, faculty, bio, skills) in enumerate(OWNERS, 1):
            u = s.exec(select(User).where(User.handle == handle)).first()
            if not u:
                u = User(email=f"{handle}@demo.local", handle=handle, name=handle, student_id=f"DEMO{i:03d}",
                         faculty=faculty, bio=bio, skills=skills, verified=True, hours=6)
                s.add(u); s.commit(); s.refresh(u)
            owners[handle] = u
        today = datetime.utcnow().date()
        for owner, kind, title, desc, hours, days, url, seats in PROJECTS:
            if s.exec(select(Project).where(Project.title == title)).first():
                continue
            comp = s.exec(select(Competition).where(Competition.url == url)).first() if url else None
            pr = Project(owner_id=owners[owner].id, kind=kind, title=title, description=desc, hours_per_week=hours,
                         deadline=(today + timedelta(days=days)).isoformat(), competition_id=comp.id if comp else None)
            s.add(pr); s.commit(); s.refresh(pr)
            for name, sk in seats:
                s.add(Role(project_id=pr.id, name=name, skills=sk))
        s.commit()
