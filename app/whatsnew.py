"""What's new: a short slideshow shown once after a release that adds features.

To announce a feature, add an item to the newest release in RELEASES (or a new release on top). That's all:
  * logged-in people who joined before the release see it once (newest first), then it stays quiet until the next release;
  * people who join after a release never see it (the Getting started list and the tour cover them);
  * an item with a `step` is added automatically to the "What's new" guided tour, and its slide gets a Show me button;
  * the How it works page lists the latest release.
Fields of an item: key, kind ("Feature" / "Improvement"), roles ("all" / "student" / "prof"), icon, en and zh (each a (title, text) pair),
cta (button text as (English, 繁體中文)), href (where the button goes, or "replay" for the tutorial), step (optional tour step: path, sel, need, en, zh).
"""
from datetime import datetime
from .main import templates

def I(key, kind, roles, icon, en, zh, cta, href, step=None): return dict(key=key, kind=kind, roles=roles, icon=icon, en=en, zh=zh, cta=cta, href=href, step=step)   # en / zh = (title, text)

RELEASES = [
    dict(id="2026-11-13", date=datetime(2026, 11, 13, 9, 0), items=[
        I("tour", "Feature", "all", "compass",
          ("Guided tutorial", "A step-by-step tour that points at the real buttons: create an account, add your skills, apply for a seat. Professors get their own tour. Replay it any time from the menu under your name."),
          ("互動式導覽", "一步步指著真正的按鈕：建立帳號、加上技能、申請職位。教授也有專屬導覽。隨時可以從你名字下方的選單重播。"),
          ("Replay the tutorial", "重播導覽"), "replay",
          step=dict(path=r".*", sel=".nme summary|.tabbar a[href='/profile']", need=".nme",
                    en=("Replay any time", "The tutorial is in the menu under your name: Replay the tutorial."),
                    zh=("隨時重播", "導覽在你名字下方的選單裡：「重播導覽」。"))),
        I("checklist", "Feature", "all", "checklist",
          ("Getting started checklist", "Your first steps, ticked off from what you've really done. Each one links to the right page, with a Guide me button if you want help."),
          ("新手上路清單", "你的第一步，會依你實際完成的事自動打勾。每一項都連到對應頁面，需要時可以按「帶我做」。"),
          ("Open Activity", "打開動態"), "/activity",
          step=dict(path=r"^/activity$", sel="#onboard|h1",
                    en=("Getting started", "Your checklist lives here and on the home page until everything is done."),
                    zh=("新手上路", "清單會顯示在這裡和首頁，直到全部完成。"))),
        I("verify", "Feature", "prof", "shield",
          ("Professor verification", "Confirm your email, give your official NTHU page, and get verified automatically when they match, or by an admin. Adjunct, visiting and jointly appointed faculty are supported."),
          ("教授驗證", "確認信箱並提供清大官方頁面，資料相符就會自動通過，否則由管理員審核。兼任、客座和合聘教師都適用。"),
          ("Open verification", "前往驗證"), "/verification",
          step=dict(path=r"^/verification$", sel=".vstatus",
                    en=("Your verification", "Your status, what's missing and the admin's message, if any, are all on this page."),
                    zh=("你的驗證", "你的狀態、還缺什麼，以及管理員的訊息都在這一頁。"))),
        I("funding", "Improvement", "all", "calendar",
          ("Funding deadlines checked daily", "Every funding program's official page is checked each morning, so deadlines stay current without waiting for an admin."),
          ("資金截止日每天檢查", "每天早上會自動檢查每個資金計畫的官方頁面，截止日期不用等管理員更新。"),
          ("Open Funding", "打開資金"), "/funding",
          step=dict(path=r"^/funding$", sel=".pcheck",
                    en=("Checked every day", "This line shows when the official page was last checked."),
                    zh=("每天檢查", "這一行顯示官方頁面最近一次檢查的時間。"))),
        I("help", "Improvement", "all", "help",
          ("How it works", "A short guide to joining a team and finding teammates, linked from the footer and your menu."),
          ("使用說明", "加入團隊和找隊友的簡短說明，可以從頁尾和你的選單打開。"),
          ("Read the guide", "閱讀說明"), "/help"),
    ]),
]

def _role(u): return "prof" if u and u.role == "faculty" else "student"

def whatsnew_data(user, lang):
    """Items for this person's role. "fresh" ones (released after they joined) open by themselves once; all of them can be reopened."""
    if not user: return None
    zh = lang == "zh"; role = _role(user); out = []
    for r in RELEASES:
        fresh = not (user.created and user.created >= r["date"])   # joined after this release: shown only if they open What's new themselves
        for it in r["items"]:
            if it["roles"] not in ("all", role): continue
            out.append(dict(release=r["id"], key=it["key"], kind=it["kind"] if not zh else {"Feature": "新功能", "Improvement": "改進"}[it["kind"]], icon=it["icon"],
                            title=it["zh" if zh else "en"][0], text=it["zh" if zh else "en"][1], cta=it["cta"][1 if zh else 0], href=it["href"],
                            tour=f"new:wn_{it['key']}" if it["step"] else "", fresh=fresh))
    return dict(items=out, latest=RELEASES[0]["id"] if RELEASES else "", uid=user.id,
                labels=dict(title="What's new" if not zh else "最新功能", sub=("New on NTHU Matchmaker" if not zh else "NTHU Matchmaker 的新功能"),
                            prev="Previous" if not zh else "上一個", next="Next" if not zh else "下一個", done="Done" if not zh else "完成",
                            show="Show me" if not zh else "帶我看", close="Close" if not zh else "關閉"))

def tour_steps(role, lang):
    """The "What's new" tour: one step per announced item that has a step, for this role, then a closing step."""
    zh = lang == "zh"; steps = []
    for r in RELEASES[:1]:
        for it in r["items"]:
            st = it["step"]
            if not st or it["roles"] not in ("all", role): continue
            t, x = st["zh" if zh else "en"]
            steps.append(dict(key=f"wn_{it['key']}", path=st["path"], sel=st["sel"], act="next", title=t, text=x, go=it["href"] if it["href"].startswith("/") else "/",
                              **({"need": st["need"]} if st.get("need") else {})))
    if steps:
        steps.append(dict(key="wn_done", path=r".*", sel="", act="done", title="That's what's new" if not zh else "新功能就是這些",
                          text="You can open What's new again from the menu under your name." if not zh else "你可以從名字下方的選單再次打開「最新功能」。", alt=True))
    return steps

def latest_release():
    return RELEASES[0] if RELEASES else None
templates.env.globals.update(whatsnew_data=whatsnew_data, latest_release=latest_release)
