"""The guided tour for a new student: create an account, add skills, open a project, apply for a seat.

Each step points at a real element on a real page. The browser (static/tour.js) shows the step whose page matches
where the person is, highlights the element and waits for them to do the thing (type, tick, press). Nothing is
done for them: the account and the application are real.

Fields of a step: key, path (regex on the URL path), q (text the query string must contain), need (CSS selector that
must exist on the page), sel (element to highlight), act (next / input / check / click / submit / done),
go (where "Take me there" sends someone who is on another page), title and text in en and zh.
"""
from .main import templates

S = lambda key, path, sel, act, en, zh, **kw: dict(key=key, path=path, sel=sel, act=act, en=en, zh=zh, **kw)
STEPS = [
    # ---- before the account exists
    S("start", r"^/$", '.howto-a a[href="/signup"]|.npost[href="/signup"]', "click",
      ("Welcome to NTHU Matchmaker", "This tour takes about two minutes: you create your account, add your skills and apply for a seat on a real team. Press Create an account to begin."),
      ("歡迎來到 NTHU Matchmaker", "這個導覽大約兩分鐘：建立帳號、加上技能，然後申請一個真實團隊的職位。按「建立帳號」開始。"), go="/"),
    S("role", r"^/signup$", ".kind:has(input[value=student])", "next",
      ("You're a student", "Keep Student selected. Professors choose the other option."),
      ("你是學生", "保持選擇「學生」。教授請選另一個選項。"), need="#lf", go="/signup"),
    S("email", r"^/signup$", "#e", "input",
      ("Your email", "Type your NTHU email, for example s114123456@m114.nthu.edu.tw. Only admins see it."),
      ("你的信箱", "輸入你的清大信箱，例如 s114123456@m114.nthu.edu.tw。只有管理員看得到。"), need="#lf"),
    S("name", r"^/signup$", "#n", "input",
      ("Your full name", "Other students see this name on your profile and applications."),
      ("你的全名", "其他同學會在你的個人檔案和申請中看到這個名字。"), need="#lf"),
    S("sid", r"^/signup$", "#s", "input",
      ("Student ID", "One account per student ID. Only admins see it."),
      ("學號", "一個學號只能有一個帳號，只有管理員看得到。"), need="#lf"),
    S("dept", r"^/signup$", "#dp", "next",
      ("Department or major", "Optional. Pick from the list or type it. Teams use it to find people from other departments."),
      ("系所或主修", "可以不填。從清單選或自己輸入，團隊會用它找其他系的人。"), need="#lf"),
    S("pw", r"^/signup$", "#pw", "input",
      ("Choose a password", "At least 8 characters. Don't reuse your school password."),
      ("設定密碼", "至少 8 個字元，不要和學校密碼一樣。"), need="#lf"),
    S("pw2", r"^/signup$", "#pw2", "input",
      ("Type it again", "The same password, to be sure there's no typo."),
      ("再輸入一次", "輸入相同的密碼，確認沒有打錯。"), need="#lf"),
    S("agree", r"^/signup$", "#lf .chk", "check",
      ("Privacy notice", "Tick the box to agree. Your contacts stay private until you join a team."),
      ("隱私權聲明", "勾選同意。加入團隊前，你的聯絡方式都不會公開。"), need="#lf"),
    S("create", r"^/signup$", "#lf > p > button", "submit",
      ("Create your account", "Press Create account. If something is missing, the form tells you what to fix."),
      ("建立帳號", "按「建立帳號」。如果有漏填，表單會告訴你要改哪裡。"), need="#lf"),
    S("inbox", r"^/(signup|login|verify/resend)$", "", "next",
      ("Check your inbox", "Open the link we just emailed you, then log in. The tour continues after that."),
      ("去收信", "打開我們剛寄給你的連結，然後登入。之後導覽會繼續。"), need="body:not(:has(#lf))", alt=True),
    # ---- logged in
    S("skills", r"^/profile$", "#s", "input",
      ("Add your skills", "Type 3 to 5 skills separated by commas, for example figma, python, pitching. Every seat then shows how well you fit."),
      ("加上你的技能", "用逗號分隔輸入 3 到 5 個技能，例如 figma, python, 簡報。每個職位就會顯示你有多適合。"), need="#pform", go="/profile"),
    S("save", r"^/profile$", "#psave", "submit",
      ("Save", "Press Save profile. You can come back and add more later."),
      ("儲存", "按「儲存個人檔案」。之後隨時可以回來補充。"), need="#pform"),
    S("pick", r"^/$", "#plist .pcard", "click",
      ("Pick a project", "Each card is a team looking for people. The % is how well you fit its best seat. Open one that interests you."),
      ("選一個專案", "每張卡片都是一個在找人的團隊，百分比是你和最適合職位的配對度。打開一個你有興趣的。"), need="#plist .pcard", go="/"),
    S("seat", r"^/projects/\d+$", ".applysum", "click",
      ("Choose a seat", "Each seat is one role in the team. Read what it needs, then press Apply for this seat."),
      ("選一個職位", "每個職位是團隊裡的一個角色。看看需要什麼，然後按「申請這個職位」。"), need=".applysum"),
    S("noseat", r"^/projects/\d+$", "", "next",
      ("No seat for you here", "This project has no open seat you can apply for. Go back and open another project."),
      ("這裡沒有適合的職位", "這個專案沒有你可以申請的空位。回到首頁打開另一個專案。"), need="body:not(:has(.applysum))", unless="n=sent", back="/#plist", alt=True),
    S("note", r"^/projects/\d+$", ".seatcard details[open] textarea", "input",
      ("Say why you fit", "One or two sentences and a link to your work are enough."),
      ("說明你為什麼適合", "一兩句話加上作品連結就夠了。"), need=".seatcard details[open] textarea"),
    S("send", r"^/projects/\d+$", ".seatcard details[open] form button", "submit",
      ("Send it", "Press Send application. The team lead gets a notification right away."),
      ("送出", "按「送出申請」，隊長會馬上收到通知。"), need=".seatcard details[open] form button"),
    S("done", r"^/projects/\d+$", ".nbell", "done",
      ("You're all set", "Your application is sent. The bell lights up when the lead answers, and you see their contact once you're accepted. You can follow it on Activity."),
      ("完成了", "你的申請已送出。隊長回覆時鈴鐺會亮起，被接受後就能看到他的聯絡方式。你可以在「動態」追蹤進度。"), q="n=sent"),
]
LABELS = {"en": dict(next="Next", back="Back", skip="End tour", done="Finish", go="Take me there", resume="Continue the tour", step="Step {0} of {1}", fill="Fill this in to continue", tick="Tick the box to continue", press="Press the highlighted button", back2="Back to projects"),
          "zh": dict(next="下一步", back="上一步", skip="結束導覽", done="完成", go="帶我過去", resume="繼續導覽", step="第 {0} 步，共 {1} 步", fill="填好後才能繼續", tick="勾選後才能繼續", press="按下標示的按鈕", back2="回到專案列表")}

def tour_data(lang):
    zh = lang == "zh"
    steps = [{k: v for k, v in dict(st, title=(st["zh"] if zh else st["en"])[0], text=(st["zh"] if zh else st["en"])[1]).items() if k not in ("en", "zh")} for st in STEPS]
    return dict(steps=steps, labels=LABELS["zh" if zh else "en"])
templates.env.globals["tour_data"] = tour_data
