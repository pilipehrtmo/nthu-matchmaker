from datetime import datetime
from typing import Optional
from pydantic import NaiveDatetime
from sqlalchemy import Column, LargeBinary
from sqlmodel import SQLModel, Field

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    handle: str = Field(unique=True, index=True)
    name: str = ""
    student_id: str = Field(default="", index=True)   # admin-only
    faculty: str = ""
    hours: int = 4
    verified: bool = False
    bio: str = ""
    skills: str = ""      # comma-separated lowercase tags
    contact: str = ""     # "other" contact (email, phone...); private, shown only after an accepted application
    line: str = ""        # private contacts, same rule as above
    instagram: str = ""
    discord: str = ""
    linkedin: str = ""    # public professional links (full https URLs)
    github: str = ""
    website: str = ""
    behance: str = ""
    scholar: str = ""
    is_admin: bool = False
    is_faculty: bool = False   # verified NTHU professor / advisor (staff email + found on an NTHU page, or approved by an admin)
    role: str = "student"      # student / faculty (chosen at sign-up)
    faculty_status: str = ""   # "" / pending / verified / rejected
    faculty_url: str = ""      # NTHU page that lists them
    faculty_note: str = ""     # result of the last automatic check
    title: str = ""            # Professor, Associate Professor, ...
    research: str = ""         # professors: research interests, comma-separated (public)
    lab_name: str = ""         # professors: lab or research group name (public)
    lab_url: str = ""          # professors: lab website (public, https)
    orcid: str = ""            # professors: ORCID link (public); Google Scholar uses the "scholar" field
    competitions: str = ""    # one per line: competitions they entered (public)
    past_projects: str = ""   # one per line: projects they built (public)
    awards: str = ""          # one per line: awards and honours (public)
    password_hash: str = ""   # salted scrypt hash; "" for accounts made before passwords (they set one through a link)
    email_verified: bool = False
    avatar_v: int = 0          # 0 = no photo; otherwise bumped on every upload so browsers fetch the new one
    banned: bool = False
    verified_at: NaiveDatetime = Field(default_factory=datetime.utcnow)
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class SignupLog(SQLModel, table=True):   # admin-only audit trail
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str
    ip: str
    allowed: bool
    at: NaiveDatetime = Field(default_factory=datetime.utcnow)

class Competition(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    url: str = Field(unique=True)
    source: str = ""
    deadline: str = ""
    needs_review: bool = True
    category: str = "Other"
    description: str = ""

PROJECT_KINDS = ["Competition", "Startup", "Research", "Side project", "Club or event", "Other"]

class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")
    title: str
    description: str = ""
    competition_id: Optional[int] = Field(default=None, foreign_key="competition.id")
    kind: str = ""        # one of PROJECT_KINDS; "" on old rows (shown as Competition or Side project)
    category: str = ""    # Startup: one of guide.STARTUP_CATEGORIES; Research: one of guide.RESEARCH_FIELDS
    stage: str = ""       # Startup only: Idea / Prototype / Early users / Revenue
    tagline: str = ""     # Startup pitch (used on the project page and the one-pager)
    problem: str = ""
    audience: str = ""    # who has the problem
    solution: str = ""
    progress: str = ""    # what the team has done so far, one item per line
    needs: str = ""       # what the team needs (people, help)
    metrics: str = ""     # up to 3 lines "12 | stall owners interviewed"
    tags: str = ""        # "Website:blue,Robotics:orange" (name:colour), at most 6
    event_name: str = ""  # Competition not on the site's list, or the club / event name
    links: str = ""       # JSON list of {label, url, team}: repo, Trello, timeline...; team=True means only the team sees it
    hours_per_week: int = 4
    deadline: str = ""
    status: str = "open"
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class Role(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    name: str
    skills: str = ""
    filled: bool = False
    advisor: bool = False     # a seat for a professor or mentor; accepted advisors can leave remarks
    about: str = ""           # what this person will do
    must: str = ""            # requirements, one per line
    nice: str = ""            # nice to have, one per line
    years: int = 0            # minimum years of experience (0 = none asked)
    years_in: str = ""        # ... in what, e.g. "Rust"

class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    role_id: int = Field(foreign_key="role.id")
    user_id: int = Field(foreign_key="user.id")
    message: str = ""
    status: str = "pending"   # pending / accepted / rejected / closed (seat filled by someone else) / withdrawn
    at: NaiveDatetime = Field(default_factory=datetime.utcnow)

class Report(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    reporter_id: int
    target_user_id: int
    reason: str
    kind: str = "user"       # user / post / comment
    target_id: int = 0
    resolved: bool = False
    at: NaiveDatetime = Field(default_factory=datetime.utcnow)

class Post(SQLModel, table=True):       # Discuss: a thread
    id: Optional[int] = Field(default=None, primary_key=True)
    author_id: int = Field(foreign_key="user.id", index=True)
    topic: str = "General"
    title: str
    body: str = ""
    hidden: bool = False
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class Comment(SQLModel, table=True):    # Discuss: a reply (parent_id = another comment, or empty for top level)
    id: Optional[int] = Field(default=None, primary_key=True)
    post_id: int = Field(foreign_key="post.id", index=True)
    author_id: int = Field(foreign_key="user.id", index=True)
    parent_id: Optional[int] = None
    body: str
    hidden: bool = False
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class Vote(SQLModel, table=True):       # +1 / -1, one per user per post or comment
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    kind: str                           # "post" or "comment"
    target_id: int = Field(index=True)
    value: int

class SourcePage(SQLModel, table=True):   # announcement pages the scraper scans, managed from the admin page
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(unique=True)
    active: bool = True

class ScrapeLog(SQLModel, table=True):    # health of each scraper source
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str
    count: int = 0
    error: str = ""
    at: NaiveDatetime = Field(default_factory=datetime.utcnow)

FEEDBACK_CATEGORIES = ["Research direction", "Methodology", "Technical", "Literature review", "General"]
FEEDBACK_PRIORITIES = ["High", "Normal", "Low"]

class Remark(SQLModel, table=True):     # research supervision: a feedback thread on a project, or a reply in one
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    author_id: int = Field(foreign_key="user.id")
    body: str
    public: bool = False      # False: only the team, advisors and admins see it (only advisor feedback can be public)
    kind: str = "feedback"    # feedback (advisor starts it) / request (team asks for feedback) / reply
    parent_id: Optional[int] = Field(default=None, index=True)   # the thread a reply belongs to
    category: str = "General" # one of FEEDBACK_CATEGORIES (threads only)
    priority: str = "Normal"  # one of FEEDBACK_PRIORITIES (threads only)
    status: str = "open"      # open / resolved (threads only)
    resources: str = ""       # suggested papers and links, one per line
    last_at: NaiveDatetime = Field(default_factory=datetime.utcnow)   # threads: time of the newest message
    last_by: int = 0          # threads: who wrote the newest message
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class Milestone(SQLModel, table=True):  # research progress: a step the team plans, ticked off when done
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    title: str
    due: str = ""             # YYYY-MM-DD or empty
    done: bool = False
    done_at: Optional[NaiveDatetime] = None
    created_by: int = 0
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class Opening(SQLModel, table=True):    # a research position a professor offers to undergraduates
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    title: str
    description: str = ""
    skills: str = ""          # comma-separated
    requirements: str = ""    # one per line
    hours: str = ""           # e.g. "8-10"
    positions: int = 1
    deadline: str = ""        # YYYY-MM-DD or empty
    process: str = ""         # how to apply and what happens next
    status: str = "open"      # open / closed
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class OpeningApp(SQLModel, table=True): # a student's application for a research position
    id: Optional[int] = Field(default=None, primary_key=True)
    opening_id: int = Field(foreign_key="opening.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    message: str = ""
    status: str = "pending"   # pending / accepted / rejected / closed (positions filled) / withdrawn
    at: NaiveDatetime = Field(default_factory=datetime.utcnow)

class Program(SQLModel, table=True):    # funding and incubation programs on /funding, editable by admins
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(unique=True)
    name: str
    org: str = ""
    url: str = ""
    for_kind: str = "Startup"   # Startup / Research / Any
    amount: str = ""
    who: str = ""
    next_deadline: str = ""     # YYYY-MM-DD once the call is announced
    deadline_note: str = ""     # shown when there is no date yet
    min_members: int = 0
    needs_advisor: bool = False
    categories: str = ""        # comma-separated project categories it suits; empty = any
    self_checks: str = ""       # "|"-separated things the team must check themselves
    sort: int = 0
    active: bool = True

class Avatar(SQLModel, table=True):     # profile photo: a small square WebP, kept in the database so it survives redeploys
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))

class AuthToken(SQLModel, table=True):  # one-time links: email verification and password reset (only a hash is stored)
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    kind: str                 # verify / reset
    token_hash: str = Field(unique=True, index=True)
    expires: NaiveDatetime
    used: bool = False
