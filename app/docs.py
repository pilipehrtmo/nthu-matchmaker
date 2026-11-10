"""Research documents: upload, versions, visibility, review requests, compare, and secure downloads.

Rules (all checked here, on the server):
  * A document belongs to one project. Only the team (lead + accepted members) uploads.
  * Versions are never replaced or edited. A new file is always a new version (v1, v2, ...).
    The uploader may delete only the newest version, and only while no review was asked for it
    and no feedback points at it.
  * Visibility:  private = only the uploader (a draft; cannot be sent for review)
                 team    = the team and its advisors (default)
                 public  = also any logged-in user, but ONLY the one version the team chose to publish
    Only the uploader or the project lead changes it; making it more open needs a confirmation step.
  * Files are fetched only through /files/{version_id}. Anyone without access gets 404, the same as
    for a file that does not exist, so a stranger cannot even learn that it exists.
"""
import difflib, hashlib, re, secrets
from datetime import datetime
from fastapi import Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlmodel import Session, select, func
from .db import get_session
from .models import (User, Project, Remark, ResearchDoc, DocVersion, ReviewRequest, VersionAddresses, RemarkEvent, Notification,
                     DOC_KINDS, DOC_VISIBILITY)
from .main import app, render, me, go, limited, templates
from .filecheck import check, text_of, clean_name, FileProblem, MAX_FILE, ALLOWED
from .storage import backend, StorageError
from .advisor import people, roles_of, short

MAX_PROJECT = 200 * 1024 * 1024
MAX_VERSIONS = 10
SITE_CAP = int(float(__import__("os").getenv("STORAGE_CAP_MB", "900")) * 1024 * 1024)   # stay inside Supabase's free 1 GB
VIS_LABEL = {"private": "Only me", "team": "Team and advisors", "public": "Public"}
templates.env.globals.update(VIS_LABEL=VIS_LABEL, DOC_KINDS=DOC_KINDS)

def mb(n): return f"{n / 1024 / 1024:.1f} MB" if n >= 102400 else f"{max(1, round(n / 1024))} KB"
templates.env.filters["mb"] = mb


# ---------- who may see what ----------
def can_open_doc(user, d, r):
    if not user or not d: return False
    if d.visibility == "private": return user.id == d.created_by
    if r["insider"]: return True
    return d.visibility == "public" and bool(d.public_version_id) and not d.archived

def can_open_version(user, d, v, r):
    if not v or v.deleted_at or v.doc_id != d.id or not can_open_doc(user, d, r): return False
    if r["insider"]: return True
    return v.id == d.public_version_id

def can_manage(user, d, pr):   # change visibility, archive
    return bool(user and (user.id in (d.created_by, pr.owner_id)))

def visible_version(s, user, vid, any_logged_in=False):
    """The version if this user (or, with any_logged_in, any logged-in outsider) may open it."""
    v = s.get(DocVersion, vid) if vid else None
    d = s.get(ResearchDoc, v.doc_id) if v else None
    if not v or not d: return None
    if any_logged_in: return v if (d.visibility == "public" and d.public_version_id == v.id and not v.deleted_at and not d.archived) else None
    pr = s.get(Project, d.project_id)
    return v if pr and can_open_version(user, d, v, roles_of(user, people(s, pr))) else None

def version_of_project(s, pr, vid, user):
    try: v = s.get(DocVersion, int(vid))
    except (TypeError, ValueError): return None
    d = s.get(ResearchDoc, v.doc_id) if v else None
    if not d or d.project_id != pr.id or d.visibility == "private": return None
    return v if can_open_version(user, d, v, roles_of(user, people(s, pr))) else None

def doc_versions_for(s, pr, user):
    """For feedback threads: {version_id: (doc, version)} and the versions one may attach feedback to."""
    docs = {d.id: d for d in s.exec(select(ResearchDoc).where(ResearchDoc.project_id == pr.id, ResearchDoc.visibility != "private")).all()}
    if not docs: return {}, []
    vs = s.exec(select(DocVersion).where(DocVersion.doc_id.in_(list(docs))).order_by(DocVersion.doc_id, DocVersion.number.desc())).all()
    info = {v.id: (docs[v.doc_id], v) for v in vs}
    choices = [(v.id, f"{docs[v.doc_id].title} · v{v.number}") for v in vs if not v.deleted_at and not docs[v.doc_id].archived]
    return info, choices
templates.env.globals["doc_versions_for"] = doc_versions_for


def _doc(s, did, user):
    d = s.get(ResearchDoc, did)
    pr = s.get(Project, d.project_id) if d else None
    if not pr: raise HTTPException(404)
    ppl = people(s, pr); r = roles_of(user, ppl)
    if not can_open_doc(user, d, r): raise HTTPException(404)   # same answer as "does not exist"
    return d, pr, ppl, r

def live_versions(s, did):
    return s.exec(select(DocVersion).where(DocVersion.doc_id == did, DocVersion.deleted_at == None).order_by(DocVersion.number.desc())).all()

def project_bytes(s, pid):
    return s.exec(select(func.coalesce(func.sum(DocVersion.size_bytes), 0)).join(ResearchDoc, ResearchDoc.id == DocVersion.doc_id)
                  .where(ResearchDoc.project_id == pid, DocVersion.deleted_at == None)).one()

def site_bytes(s):
    return s.exec(select(func.coalesce(func.sum(DocVersion.size_bytes), 0)).where(DocVersion.deleted_at == None)).one()

def uploads_on(): return backend() is not None


# ---------- the documents card on the project page ----------
def project_docs(s, pr, user, ppl):
    r = roles_of(user, ppl)
    rows = []
    for d in s.exec(select(ResearchDoc).where(ResearchDoc.project_id == pr.id).order_by(ResearchDoc.created.desc())).all():
        if not can_open_doc(user, d, r) or (d.archived and not r["insider"]): continue
        vs = live_versions(s, d.id)
        shown = vs[0] if r["insider"] or d.visibility == "private" else next((v for v in vs if v.id == d.public_version_id), None)
        if not shown: continue
        openr = len(s.exec(select(Remark.id).where(Remark.doc_id == d.id, Remark.parent_id == None, Remark.deleted_at == None, Remark.state != "resolved")).all()) if r["insider"] else 0
        waiting = s.exec(select(ReviewRequest).where(ReviewRequest.doc_id == d.id, ReviewRequest.status == "waiting")).first() if r["insider"] else None
        rows.append(dict(d=d, v=shown, n=len(vs), open=openr, waiting=waiting))
    used = project_bytes(s, pr.id) if r["team"] else 0
    return dict(rows=rows, can_upload=r["team"], uploads_on=uploads_on(), used=used, cap=MAX_PROJECT,
                kinds=DOC_KINDS, allowed=ALLOWED, has_adv=bool(ppl["advisors"]))


# ---------- upload ----------
async def _read(file: UploadFile):
    data = await file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE: raise FileProblem("Files can be at most 25 MB.")
    return data

def _store(s, d, pr, user, data, filename, note):
    """Check, store and record one new version. Returns the version or raises FileProblem."""
    b = backend()
    if not b: raise FileProblem("File uploads are not switched on for this site yet. Ask the site admin to connect file storage.")
    ext, mime = check(data, filename)
    if project_bytes(s, pr.id) + len(data) > MAX_PROJECT: raise FileProblem("This project has used its 200 MB of storage. Delete an old version you don't need, or upload a smaller file.")
    if site_bytes(s) + len(data) > SITE_CAP: raise FileProblem("The site's file storage is full right now. Please tell the site admin.")
    if len(live_versions(s, d.id)) >= MAX_VERSIONS: raise FileProblem(f"A document can have at most {MAX_VERSIONS} versions. Start a new document for the next stage.")
    number = (s.exec(select(func.max(DocVersion.number)).where(DocVersion.doc_id == d.id)).one() or 0) + 1   # numbers are never reused
    key = f"research/{pr.id}/{d.id}/v{number}-{secrets.token_hex(8)}.{ext}"
    try: b.put(key, data, mime)
    except StorageError as e:
        print(">>> storage upload failed:", e, flush=True); raise FileProblem("The file could not be saved. Please try again in a minute.")
    v = DocVersion(doc_id=d.id, number=number, uploaded_by=user.id, storage_key=key, filename=clean_name(filename, ext), mime=mime, ext=ext,
                   size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), note=note, text_excerpt=text_of(data, ext))
    try:
        s.add(v)
        for old in s.exec(select(DocVersion).where(DocVersion.doc_id == d.id, DocVersion.superseded == False)).all(): old.superseded = True; s.add(old)
        s.commit(); s.refresh(v)
    except Exception:
        s.rollback()
        try: b.delete(key)
        except StorageError: pass
        raise FileProblem("Someone uploaded a version at the same moment. Reload the page and try again.")
    return v

def _back_with(url, problem):
    from urllib.parse import quote
    return go(f"{url}{'&' if '?' in url else '?'}err={quote(str(problem)[:200])}")

@app.post("/projects/{pid}/docs", dependencies=[limited("docnew", 20, 3600)])
async def new_doc(pid: int, title: str = Form(""), kind: str = Form("Other"), visibility: str = Form("team"), note: str = Form(""),
                  file: UploadFile = File(None), user=Depends(me), s: Session = Depends(get_session)):
    from .notify import notify
    if not user: return go("/login")
    pr = s.get(Project, pid)
    if not pr: raise HTTPException(404)
    ppl = people(s, pr)
    if not roles_of(user, ppl)["team"]: raise HTTPException(404)
    back = f"/projects/{pid}#docs"
    title = re.sub(r"\s+", " ", title).strip()[:120]
    if not title: return _back_with(f"/projects/{pid}", "Give the document a title.")
    if not file or not file.filename: return _back_with(f"/projects/{pid}", "Choose a file to upload.")
    if len(s.exec(select(ResearchDoc.id).where(ResearchDoc.project_id == pid)).all()) >= 50: return _back_with(f"/projects/{pid}", "A project can have at most 50 documents.")
    try: data = await _read(file)
    except FileProblem as e: return _back_with(f"/projects/{pid}", e)
    d = ResearchDoc(project_id=pid, created_by=user.id, title=title, kind=kind if kind in DOC_KINDS else "Other",
                    visibility=visibility if visibility in ("team", "private") else "team")   # public only after a check, from the document page
    s.add(d); s.commit(); s.refresh(d)
    try: v = _store(s, d, pr, user, data, file.filename, note.strip()[:1000])
    except FileProblem as e:
        s.delete(d); s.commit(); return _back_with(f"/projects/{pid}", e)
    if d.visibility == "team":
        notify(s, ppl["advisors"] | ppl["team"], "doc_new", f"{user.name or user.handle} added a document: {d.title}", f"/docs/{d.id}", pid, user.id, instant_ok=False)
    return go(f"/docs/{d.id}?n=uploaded")

@app.post("/docs/{did}/versions", dependencies=[limited("docver", 30, 3600)])
async def new_version(did: int, req: Request, note: str = Form(""), review: str = Form(""), message: str = Form(""),
                      file: UploadFile = File(None), user=Depends(me), s: Session = Depends(get_session)):
    from .notify import notify
    from .advisor import can_move, move_state
    if not user: return go("/login")
    d, pr, ppl, r = _doc(s, did, user)
    if not r["team"] or d.archived or (d.visibility == "private" and user.id != d.created_by): raise HTTPException(404)
    here = f"/docs/{did}"
    note = note.strip()[:1000]
    if not file or not file.filename: return _back_with(here, "Choose a file to upload.")
    if not note: return _back_with(here, "Write a short note on what changed in this version.")
    try:
        data = await _read(file); v = _store(s, d, pr, user, data, file.filename, note)
    except FileProblem as e: return _back_with(here, e)
    form = await req.form()
    fixed = []
    for raw in form.getlist("addresses")[:50]:   # "this version addresses remark #n"
        try: t = s.get(Remark, int(raw))
        except (TypeError, ValueError): continue
        if not t or t.doc_id != d.id or t.parent_id or t.kind != "feedback": continue
        s.add(VersionAddresses(version_id=v.id, remark_id=t.id, note=note)); s.commit()
        if can_move(s, t, user, r, "submitted", pr):
            move_state(s, t, user, "submitted", f"Addressed in v{v.number}: {note}", v.id, pr, ppl, notify_people=False); fixed.append(t)
    if d.visibility != "private":
        what = f" · addresses {len(fixed)} remark{'s' if len(fixed) != 1 else ''}" if fixed else ""
        # linked to the document (its newest version opens first), so several uploads in a row merge into one notification
        notify(s, ppl["advisors"], "doc_version", f"{d.title} v{v.number} uploaded by {user.name or user.handle}{what}", f"/docs/{d.id}", pr.id, user.id)
        notify(s, ppl["team"], "doc_version", f"{d.title} v{v.number} uploaded by {user.name or user.handle}", f"/docs/{d.id}", pr.id, user.id, instant_ok=False)
        if review and ppl["advisors"]: _request_review(s, d, v, pr, ppl, user, message)
    return go(f"/docs/{d.id}?v={v.id}&n=version")


# ---------- review requests ----------
def _request_review(s, d, v, pr, ppl, user, message):
    from .notify import notify
    if s.exec(select(ReviewRequest).where(ReviewRequest.version_id == v.id, ReviewRequest.status == "waiting")).first(): return
    for old in s.exec(select(ReviewRequest).where(ReviewRequest.doc_id == d.id, ReviewRequest.status == "waiting")).all():
        old.status, old.closed_at = "withdrawn", datetime.utcnow(); s.add(old)   # a newer version replaces the older request
    s.add(ReviewRequest(doc_id=d.id, version_id=v.id, requested_by=user.id, message=message.strip()[:1000])); s.commit()
    notify(s, ppl["advisors"], "review_request", f"{user.name or user.handle} asked you to review {d.title} v{v.number}", f"/docs/{d.id}?v={v.id}", pr.id, user.id)

@app.post("/docs/{did}/review", dependencies=[limited("review", 30, 3600)])
def ask_review(did: int, version_id: int = Form(...), message: str = Form(""), user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    d, pr, ppl, r = _doc(s, did, user)
    v = s.get(DocVersion, version_id)
    if not r["team"] or d.visibility == "private" or d.archived or not can_open_version(user, d, v, r): raise HTTPException(404)
    if not ppl["advisors"]: return _back_with(f"/docs/{did}?v={v.id}", "This project has no advisor yet.")
    _request_review(s, d, v, pr, ppl, user, message)
    return go(f"/docs/{did}?v={v.id}&n=asked")

@app.post("/reviews/{rid}/{action}")
def close_review(rid: int, action: str, user=Depends(me), s: Session = Depends(get_session)):
    from .notify import notify
    rq = s.get(ReviewRequest, rid)
    if not user or not rq: raise HTTPException(404)
    d, pr, ppl, r = _doc(s, rq.doc_id, user)
    v = s.get(DocVersion, rq.version_id)
    if rq.status == "waiting":
        if action == "done" and r["adv"]:
            rq.status, rq.done_by, rq.closed_at = "done", user.id, datetime.utcnow(); s.add(rq); s.commit()
            notify(s, ppl["team"], "review_done", f"{user.name or user.handle} finished reviewing {d.title} v{v.number if v else ''}", f"/docs/{d.id}?v={rq.version_id}", pr.id, user.id)
        elif action == "withdraw" and r["team"] and user.id in (rq.requested_by, pr.owner_id):
            rq.status, rq.closed_at = "withdrawn", datetime.utcnow(); s.add(rq); s.commit()
    return go(f"/docs/{d.id}?v={rq.version_id}")


# ---------- visibility, archive, delete ----------
@app.post("/docs/{did}/visibility", dependencies=[limited("docvis", 30, 3600)])
def set_visibility(req: Request, did: int, to: str = Form(...), public_version_id: str = Form(""), confirm: str = Form(""),
                   user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    d, pr, ppl, r = _doc(s, did, user)
    if not can_manage(user, d, pr) or to not in DOC_VISIBILITY: raise HTTPException(404)
    here = f"/docs/{did}"
    vs = live_versions(s, did)
    if to == "private":
        if user.id != d.created_by: return _back_with(here, "Only the person who uploaded it can make it private.")
        busy = s.exec(select(Remark.id).where(Remark.doc_id == did, Remark.deleted_at == None)).first() or \
               s.exec(select(ReviewRequest.id).where(ReviewRequest.doc_id == did)).first()
        if busy: return _back_with(here, "This document already has advisor feedback or a review request, so it stays visible to the team.")
    pv = None
    if to == "public":
        try: pv = next(v for v in vs if v.id == int(public_version_id or vs[0].id))
        except (StopIteration, ValueError, IndexError): return _back_with(here, "Choose which version to make public.")
    wider = {"private": 0, "team": 1, "public": 2}
    opening_up = wider[to] > wider[d.visibility] or (to == "public" and pv and pv.id != d.public_version_id)
    if opening_up and confirm != "yes":   # one more look before more people can open it
        return render(req, "doc_confirm.html", user, d=d, pr=pr, to=to, pv=pv, n_team=len(ppl["team"] | ppl["advisors"]))
    d.visibility = to; d.public_version_id = pv.id if pv else None
    s.add(d); s.commit()
    return go(f"{here}?n=visibility")

@app.post("/docs/{did}/archive")
def archive_doc(did: int, user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    d, pr, ppl, r = _doc(s, did, user)
    if not can_manage(user, d, pr): raise HTTPException(404)
    d.archived = not d.archived; s.add(d); s.commit()
    return go(f"/docs/{did}")

@app.post("/versions/{vid}/delete")
def delete_version(vid: int, user=Depends(me), s: Session = Depends(get_session)):
    v = s.get(DocVersion, vid)
    if not user or not v: raise HTTPException(404)
    d, pr, ppl, r = _doc(s, v.doc_id, user)
    vs = live_versions(s, d.id)
    if not can_delete_version(s, user, d, v, vs): return _back_with(f"/docs/{d.id}?v={v.id}", "Only the newest version, with no review request and no feedback yet, can be deleted by the person who uploaded it.")
    try: backend() and backend().delete(v.storage_key)
    except StorageError as e: print(">>> storage delete failed:", e, flush=True)
    v.deleted_at = datetime.utcnow(); v.text_excerpt = ""; s.add(v)
    rest = [x for x in vs if x.id != v.id]
    if rest: rest[0].superseded = False; s.add(rest[0])
    if d.public_version_id == v.id: d.public_version_id = None; d.visibility = "team" if d.visibility == "public" else d.visibility
    if not rest: s.delete(d)   # the only version: the document goes too
    s.commit()
    return go(f"/docs/{d.id}" if rest else f"/projects/{pr.id}#docs")

def can_delete_version(s, user, d, v, vs):
    if not user or v.uploaded_by != user.id or not vs or vs[0].id != v.id: return False
    if s.exec(select(ReviewRequest.id).where(ReviewRequest.version_id == v.id)).first(): return False
    if s.exec(select(Remark.id).where((Remark.version_id == v.id) | (Remark.fixed_in_version_id == v.id))).first(): return False
    return not s.exec(select(VersionAddresses.id).where(VersionAddresses.version_id == v.id)).first()


# ---------- the document page ----------
@app.get("/docs/{did}")
def doc_page(req: Request, did: int, user=Depends(me), s: Session = Depends(get_session)):
    from .advisor import supervision
    if not user: return go("/login")
    d, pr, ppl, r = _doc(s, did, user)
    vs = live_versions(s, did)
    if not r["insider"] and d.visibility == "public": vs = [v for v in vs if v.id == d.public_version_id]
    try: cur = next(v for v in vs if v.id == int(req.query_params.get("v", 0)))
    except (StopIteration, ValueError): cur = vs[0] if vs else None
    if not cur: raise HTTPException(404)
    sup = supervision(s, pr, user, ppl)
    mine = [t for t in sup["threads"] if t.doc_id == d.id]
    sup.update(threads=mine, open_threads=[t for t in mine if t.state != "resolved"], done_threads=[t for t in mine if t.state == "resolved"])
    names = {u.id: u for u in s.exec(select(User).where(User.id.in_({v.uploaded_by for v in vs} | {d.created_by})))}
    reviews = s.exec(select(ReviewRequest).where(ReviewRequest.doc_id == did).order_by(ReviewRequest.created.desc())).all() if r["insider"] else []
    addressed = {}
    if r["insider"]:
        for a in s.exec(select(VersionAddresses).where(VersionAddresses.version_id.in_([v.id for v in vs] or [-1]))).all():
            addressed.setdefault(a.version_id, []).append(a.remark_id)
    fixable = [t for t in mine if t.kind == "feedback" and t.state in ("open", "in_progress", "reopened")]
    return render(req, "doc.html", user, d=d, pr=pr, vs=vs, cur=cur, sup=sup, names=names, reviews=reviews, addressed=addressed,
                  waiting=next((x for x in reviews if x.status == "waiting"), None), fixable=fixable, manage=can_manage(user, d, pr),
                  can_del=can_delete_version(s, user, d, cur, vs), uploads_on=uploads_on(), max_versions=MAX_VERSIONS,
                  notice=req.query_params.get("n", ""), err=req.query_params.get("err", "")[:200], is_owner=user.id == pr.owner_id)


# ---------- secure download ----------
@app.get("/files/{vid}")
def get_file(vid: int, inline: int = 0, user=Depends(me), s: Session = Depends(get_session)):
    if not user: raise HTTPException(404)
    v = s.get(DocVersion, vid); d = s.get(ResearchDoc, v.doc_id) if v else None; pr = s.get(Project, d.project_id) if d else None
    if not pr or not can_open_version(user, d, v, roles_of(user, people(s, pr))): raise HTTPException(404)
    b = backend()
    try: data = b.get(v.storage_key) if b else None
    except StorageError as e:
        print(">>> storage read failed:", e, flush=True); data = None
    if data is None: raise HTTPException(404)
    from urllib.parse import quote
    show = "inline" if inline and v.ext == "pdf" else "attachment"   # only PDFs open in the browser; everything else downloads
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", v.filename)
    return Response(data, media_type=v.mime, headers={
        "Content-Disposition": f"{show}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(v.filename)}",
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:", "Referrer-Policy": "no-referrer"})


# ---------- compare two versions ----------
def diff_rows(a, b):
    """Line-by-line changes: [(kind, old_lines, new_lines)] with kind = same / del / add / chg."""
    al, bl = a.splitlines(), b.splitlines()
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, al, bl, autojunk=False).get_opcodes():
        if tag == "equal":
            seg = al[i1:i2]
            if len(seg) > 6: out += [("same", seg[:2], seg[:2]), ("skip", [str(len(seg) - 4)], []), ("same", seg[-2:], seg[-2:])]
            else: out.append(("same", seg, seg))
        elif tag == "delete": out.append(("del", al[i1:i2], []))
        elif tag == "insert": out.append(("add", [], bl[j1:j2]))
        else: out.append(("chg", al[i1:i2], bl[j1:j2]))
    return out

@app.get("/docs/{did}/compare")
def compare(req: Request, did: int, a: int = 0, b: int = 0, view: str = "changes", user=Depends(me), s: Session = Depends(get_session)):
    if not user: return go("/login")
    d, pr, ppl, r = _doc(s, did, user)
    if not r["insider"] and d.visibility != "private": raise HTTPException(404)   # outsiders see only one version: nothing to compare
    vs = live_versions(s, did)
    if len(vs) < 2: return go(f"/docs/{did}")
    byid = {v.id: v for v in vs}
    vb = byid.get(b) or vs[0]
    va = byid.get(a) or next((v for v in vs if v.number < vb.number), vs[1])
    if va.number > vb.number: va, vb = vb, va
    rows = diff_rows(va.text_excerpt or "", vb.text_excerpt or "")
    added = sum(len(n) for k, o, n in rows if k in ("add", "chg")); removed = sum(len(o) for k, o, n in rows if k in ("del", "chg"))
    fixes = s.exec(select(Remark).join(VersionAddresses, VersionAddresses.remark_id == Remark.id).where(VersionAddresses.version_id == vb.id, Remark.deleted_at == None)).all()
    return render(req, "doc_compare.html", user, d=d, pr=pr, vs=vs, va=va, vb=vb, rows=rows, added=added, removed=removed,
                  view="side" if view == "side" else "changes", fixes=fixes, no_text=not (va.text_excerpt or vb.text_excerpt))


# ---------- clean-up when a project or account goes ----------
def purge_project_docs(s, pid):
    b = backend()
    for d in s.exec(select(ResearchDoc).where(ResearchDoc.project_id == pid)).all():
        for v in s.exec(select(DocVersion).where(DocVersion.doc_id == d.id)).all():
            try: b and not v.deleted_at and b.delete(v.storage_key)
            except StorageError as e: print(">>> storage delete failed:", e, flush=True)
            for a in s.exec(select(VersionAddresses).where(VersionAddresses.version_id == v.id)).all(): s.delete(a)
            s.delete(v)
        for rq in s.exec(select(ReviewRequest).where(ReviewRequest.doc_id == d.id)).all(): s.delete(rq)
        s.flush(); s.delete(d)
    ids = [t.id for t in s.exec(select(Remark).where(Remark.project_id == pid)).all()]
    if ids:
        for e in s.exec(select(RemarkEvent).where(RemarkEvent.remark_id.in_(ids))).all(): s.delete(e)
    for n in s.exec(select(Notification).where(Notification.project_id == pid)).all(): s.delete(n)
    s.flush()

def purge_private_docs_of(s, uid):
    """A deleted account's private drafts go with it (nobody else could ever open them)."""
    b = backend()
    for d in s.exec(select(ResearchDoc).where(ResearchDoc.created_by == uid, ResearchDoc.visibility == "private")).all():
        for v in s.exec(select(DocVersion).where(DocVersion.doc_id == d.id)).all():
            try: b and not v.deleted_at and b.delete(v.storage_key)
            except StorageError: pass
            s.delete(v)
        s.flush(); s.delete(d)
    s.flush()


# ---------- stop oversized uploads before they are read ----------
UPLOAD_PATH = re.compile(r"^/(projects/(\d+)/docs|docs/(\d+)/versions)$")
BODY_LIMIT = MAX_FILE + 512 * 1024   # the file plus the small form fields

class UploadLimit:
    """Upload paths: refuse a body over ~25.5 MB, whether the browser says its size up front or not."""
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        m = UPLOAD_PATH.match(scope.get("path", "")) if scope["type"] == "http" and scope.get("method") == "POST" else None
        if not m: return await self.app(scope, receive, send)
        back = f"/projects/{m.group(2)}" if m.group(2) else f"/docs/{m.group(3)}"
        size = dict(scope.get("headers") or []).get(b"content-length")
        if size and size.isdigit() and int(size) > BODY_LIMIT:
            await send({"type": "http.response.start", "status": 303, "headers": [(b"location", f"{back}?err=Files+can+be+at+most+25+MB.".encode())]})
            await send({"type": "http.response.body", "body": b""}); return
        seen = 0
        async def counted():
            nonlocal seen
            msg = await receive(); seen += len(msg.get("body", b""))
            if seen > BODY_LIMIT: raise HTTPException(413, "Files can be at most 25 MB.")
            return msg
        return await self.app(scope, counted, send)
app.add_middleware(UploadLimit)
