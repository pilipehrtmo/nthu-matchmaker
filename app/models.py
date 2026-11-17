from datetime import datetime
from typing import Optional
from pydantic import NaiveDatetime
from sqlalchemy import Column, LargeBinary, Text, UniqueConstraint
from sqlmodel import SQLModel, Field

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    handle: str = Field(unique=True, index=True)
    name: str = ""
    student_id: str = Field(default="", index=True)   # admin-only
    faculty: str = ""     # department or major as the person typed it (kept as it is; see departments.py)
    faculty_orig: str = ""   # the free text before the first department link (never changed afterwards)
    dept_id: str = ""        # linked department: unit id, "c:<college>" or "" (departments.py)
    dept_track: str = ""     # IBP track, only with dept_id "thc-ibp"
    dept_status: str = ""    # "" / ok / review / other / kept
    dept_src: str = ""       # user / admin / migration
    degree: str = ""         # students: "" (not set yet), bachelor, master or phd (departments.DEGREES)
    hours: int = 4
    verified: bool = False
    bio: str = ""
    skills: str = ""      # comma-separated lowercase tags
    interests: str = ""   # comma-separated topics they care about (e.g. machine learning, startups); used for "For you"
    roles_wanted: str = ""   # comma-separated roles they want on a team (e.g. frontend developer, designer)
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
    faculty_status: str = ""   # "" / pending / verified / rejected / more_info / suspended (only admins and the automatic check change it)
    faculty_url: str = ""      # official NTHU page that lists them
    faculty_note: str = ""     # result of the last automatic check
    faculty_match: str = ""    # what the automatic check found on that page: comma list of email,name,title,dept
    faculty_reason: str = ""   # the admin's message for a rejection or a request for more information (shown to them)
    faculty_evidence: str = "" # their note for the reviewer (private: admins only)
    faculty_applied_at: Optional[NaiveDatetime] = None
    faculty_reviewed_at: Optional[NaiveDatetime] = None
    faculty_reviewed_by: Optional[int] = None
    title: str = ""            # Professor, Associate Professor, ...
    research: str = ""         # professors: research interests, comma-separated (public)
    lab_name: str = ""         # professors: lab or research group name (public)
    lab_url: str = ""          # professors: lab website (public, https)
    orcid: str = ""            # professors: ORCID link (public); Google Scholar uses the "scholar" field
    email_pref: str = "off"    # notification emails: off / daily (one digest a day) / instant
    lang: str = ""             # interface language chosen in the profile menu: en / zh ("" = not chosen yet)
    competitions: str = ""    # one per line: competitions they entered (public)
    past_projects: str = ""   # one per line: projects they built (public)
    awards: str = ""          # one per line: awards and honours (public)
    password_hash: str = ""   # salted scrypt hash; "" for accounts made before passwords (they set one through a link)
    email_verified: bool = False
    avatar_v: int = 0          # 0 = no photo; otherwise bumped on every upload so browsers fetch the new one
    banned: bool = False
    verified_at: NaiveDatetime = Field(default_factory=datetime.utcnow)
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class FacultyAudit(SQLModel, table=True):   # admin-only: every change to a professor's verification, never edited or deleted
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    actor_id: Optional[int] = None   # None = the automatic check, otherwise the person (the applicant or an admin)
    action: str                      # applied / resubmitted / email_verified / auto_check / approved / rejected / more_info / suspended / reinstated
    status_from: str = ""
    status_to: str = ""
    reason: str = ""
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
    verified_at: Optional[NaiveDatetime] = None   # when an admin last checked it against the official site
    online: bool = False          # can be entered entirely online (shown under the "Online" filter)
    online_checked: bool = False  # the scraper has looked at the page for this

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
    objectives: str = ""  # Research only: research objectives, methodology and expected outcomes
    methodology: str = ""
    outcomes: str = ""
    progress: str = ""    # what the team has done so far, one item per line
    needs: str = ""       # what the team needs (people, help)
    metrics: str = ""     # up to 3 lines "12 | stall owners interviewed"
    tags: str = ""        # "Website:blue,Robotics:orange" (name:colour), at most 6
    event_name: str = ""  # Competition not on the site's list, or the club / event name
    links: str = ""       # JSON list of {label, url, team}: repo, Trello, timeline...; team=True means only the team sees it
    hours_per_week: int = 4
    deadline: str = ""
    status: str = "open"      # open / closed / completed (the lead marked it done; see Contribution)
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[NaiveDatetime] = None

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
    beginner: Optional[bool] = False   # "No prior experience required": beginners are welcome (older rows: NULL = no)

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
    project_id: Optional[int] = Field(default=None, index=True)   # optional: a public discussion about this project
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

class ScrapeSeen(SQLModel, table=True):   # competition pages the scraper already opened (kept or skipped), so each is fetched once
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(unique=True)
    kept: bool = False
    at: NaiveDatetime = Field(default_factory=datetime.utcnow)

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
    status: str = "open"      # legacy two-value status, kept in step with `state` (open / resolved)
    state: str = "open"       # feedback: open / in_progress / submitted / resolved / reopened · questions: open / resolved
    doc_id: Optional[int] = Field(default=None, index=True)       # feedback written on a research document...
    version_id: Optional[int] = Field(default=None, index=True)   # ...and on this exact version of it
    anchor: str = ""          # where in the document: a page, section or quoted words
    fixed_in_version_id: Optional[int] = None                     # the version the team says fixes it
    resolved_by: int = 0
    resolved_at: Optional[NaiveDatetime] = None
    deleted_at: Optional[NaiveDatetime] = None                    # soft delete: the thread and others' replies stay
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
    verified_at: Optional[NaiveDatetime] = None   # when an admin last checked it against the official call
    checked_at: Optional[NaiveDatetime] = None    # when the daily check last opened the official page
    check_status: str = ""    # "" / ok / changed / unreachable
    check_note: str = ""
    page_hash: str = ""       # to notice when the official page changes
    deadline_source: str = "" # "" / auto (read from the official page) / admin (typed by an admin; the check never overwrites it)

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


REMARK_STATES = ["open", "in_progress", "submitted", "resolved", "reopened"]

class RemarkEvent(SQLModel, table=True):     # every status change of a feedback thread: who, when, why, which version
    id: Optional[int] = Field(default=None, primary_key=True)
    remark_id: int = Field(index=True)
    actor_id: int = 0
    from_state: str = ""
    to_state: str = ""
    version_id: Optional[int] = None
    note: str = ""
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class Notification(SQLModel, table=True):    # the bell: one row per person per event
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    kind: str = ""
    project_id: Optional[int] = Field(default=None, index=True)
    link: str = ""            # a page on this site (never a file)
    text: str = ""
    read_at: Optional[NaiveDatetime] = None
    emailed_at: Optional[NaiveDatetime] = None
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

DOC_KINDS = ["Proposal", "Literature review", "Dataset", "Presentation", "Paper", "Other"]
DOC_VISIBILITY = ["team", "public", "private"]

class ResearchDoc(SQLModel, table=True):     # a research document of a project; its files are DocVersions
    __tablename__ = "research_doc"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    created_by: int = Field(foreign_key="user.id")
    title: str
    kind: str = "Other"
    visibility: str = "team"  # private (only the uploader) / team (team + advisors) / public (anyone logged in)
    public_version_id: Optional[int] = None   # the ONE version outsiders may open when public
    archived: bool = False
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class DocVersion(SQLModel, table=True):      # one uploaded file; never replaced or edited
    __tablename__ = "doc_version"
    __table_args__ = (UniqueConstraint("doc_id", "number", name="uq_doc_version_number"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    doc_id: int = Field(foreign_key="research_doc.id", index=True)
    number: int
    uploaded_by: int = Field(foreign_key="user.id")
    storage_key: str
    filename: str
    mime: str
    ext: str = ""
    size_bytes: int = 0
    sha256: str = ""
    note: str = ""            # "What changed"
    text_excerpt: str = Field(default="", sa_column=Column(Text, default=""))   # extracted text for the compare view
    superseded: bool = False
    deleted_at: Optional[NaiveDatetime] = None
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class ReviewRequest(SQLModel, table=True):   # "please review v2", sent to every accepted advisor
    __tablename__ = "review_request"
    id: Optional[int] = Field(default=None, primary_key=True)
    doc_id: int = Field(index=True)
    version_id: int = Field(index=True)
    requested_by: int = 0
    message: str = ""
    status: str = "waiting"   # waiting / done / withdrawn
    done_by: int = 0
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[NaiveDatetime] = None

class VersionAddresses(SQLModel, table=True):  # "v2 addresses remark 14", with the student's note
    __tablename__ = "version_addresses"
    id: Optional[int] = Field(default=None, primary_key=True)
    version_id: int = Field(index=True)
    remark_id: int = Field(index=True)
    note: str = ""

class SavedItem(SQLModel, table=True):       # a bookmark: a competition or project someone saved for later
    __tablename__ = "saved_item"
    __table_args__ = (UniqueConstraint("user_id", "kind", "item_id", name="uq_saved_item"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    kind: str                 # competition / project / program
    item_id: int
    status: str = ""          # application tracking for opportunities: "" / planning / applied / accepted / not_selected
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)


class Contribution(SQLModel, table=True):   # one person's part in a completed project: written by the lead, confirmed by the person
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_contribution_project_user"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    role_name: str = ""        # the seat they held ("Project lead" for the lead)
    skills: str = ""           # the seat's skills when the project was completed
    note: str = ""             # the lead's short description of what they did
    is_lead: bool = False
    lead_status: str = "confirmed"   # confirmed / not_included (the lead says they did not take part)
    member_status: str = "pending"   # pending / confirmed / disputed (the person's answer)
    member_note: str = ""      # why they disagree
    admin_status: str = ""     # "" / verified (an admin checked the evidence) / upheld_member / upheld_lead (a dispute decided)
    joined_at: Optional[NaiveDatetime] = None
    decided_by: int = 0
    decided_at: Optional[NaiveDatetime] = None
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)

class Endorsement(SQLModel, table=True):   # a teammate vouches for one strength after a completed project; never negative, never a score
    __table_args__ = (UniqueConstraint("project_id", "from_id", "to_id", "tag", name="uq_endorsement"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    from_id: int = Field(foreign_key="user.id", index=True)
    to_id: int = Field(foreign_key="user.id", index=True)
    tag: str                   # "q:reliable" (a fixed quality) or "s:python" (a skill from their seat)
    created: NaiveDatetime = Field(default_factory=datetime.utcnow)
