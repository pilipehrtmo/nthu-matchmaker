from datetime import datetime
from typing import Optional
from pydantic import NaiveDatetime
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
