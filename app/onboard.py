"""Onboarding checklist for students and professors.

Every item is worked out from what the person has really done (no "mark as done" button), so the list is the same
on every page that shows it and can't drift. Each item links to the page where it's done, and has a "Guide me"
button that starts the guided tour at that step; nobody is forced through the tour.
"""
from sqlmodel import Session, select
from .db import engine
from .models import User, Project, Role, Application
from .main import templates

def items_for(s, u):
    applied = s.exec(select(Application.id).where(Application.user_id == u.id, Application.status != "withdrawn")).first() is not None
    posted = s.exec(select(Project.id).where(Project.owner_id == u.id)).first() is not None
    joined = s.exec(select(Application.id).join(Role, Role.id == Application.role_id).join(Project, Project.id == Role.project_id)
                    .where(Application.status == "accepted", (Application.user_id == u.id) | (Project.owner_id == u.id))).first() is not None
    if u.role != "faculty":
        return "student", [
            dict(key="skills", label="Add your skills", desc="So every seat can show your match %.", done=bool(u.skills.strip()), href="/profile#s", tour="student:skills"),
            dict(key="dept", label="Add your department or major", desc="Teams use it to find people from other departments.", done=bool((u.faculty or "").strip()), href="/profile#f", tour=""),
            dict(key="act", label="Apply for a seat, or post your own project", desc="Open a project and press Apply for this seat, or post a project and list the seats you need.", done=applied or posted, href="/#plist", tour="student:pick"),
            dict(key="joined", label="Get accepted, or accept someone", desc="The bell lights up when there is news. Contacts appear only after acceptance.", done=joined, href="/activity", tour=""),
        ]
    from .models import Opening, OpeningApp
    ops = s.exec(select(Opening.id).where(Opening.owner_id == u.id)).all()
    reviewed = s.exec(select(OpeningApp.id).where(OpeningApp.opening_id.in_(ops or [-1]), OpeningApp.status != "pending")).first() is not None or \
        s.exec(select(Application.id).join(Role, Role.id == Application.role_id).join(Project, Project.id == Role.project_id)
               .where(Project.owner_id == u.id, Application.status.in_(["accepted", "rejected"]))).first() is not None
    locked = not u.is_faculty
    return "prof", [
        dict(key="email", label="Confirm your email", desc="A 6-digit code or the link we emailed you.", done=bool(u.email_verified), href="/verification#steps", tour="prof:p_code"),
        dict(key="verified", label="Get verified", desc="Your official NTHU page is checked, or an admin reviews your information.", done=u.is_faculty, href="/verification", tour="prof:p_info"),
        dict(key="research", label="Fill in your research profile", desc="Research interests, lab and links, so students can find you.", done=bool((u.research or "").strip()), href="/profile#research", tour="prof:p_research"),
        dict(key="project", label="Post a project", desc="A lab or research project with the seats you want students for.", done=posted, href="/projects/new", tour="prof:p_proj"),
        dict(key="opening", label="Open a research position", desc="Students apply with a note; you choose who joins.", done=bool(ops), href="/openings/new", tour="prof:p_open", locked=locked),
        dict(key="review", label="Review student applications", desc="Accept or decline from your dashboard.", done=reviewed, href="/advisor#positions", tour="prof:p_review", locked=locked),
    ]

def onboarding(u):
    """For templates: None once everything is done, else dict(kind, items, done, total)."""
    if not u: return None
    with Session(engine) as s:
        kind, items = items_for(s, u)
    done = sum(1 for i in items if i["done"])
    return None if done == len(items) else dict(kind=kind, items=items, done=done, total=len(items))
templates.env.globals["onboarding"] = onboarding
