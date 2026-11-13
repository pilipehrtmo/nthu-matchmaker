"""Guided tours: one for students, one for professors.

Each step points at a real element on a real page. The browser (static/tour.js) shows the step whose page matches
where the person is, highlights the element and waits for them to do the thing (type, tick, press). Nothing is
done for them, so the account, profile and anything they publish are real. Steps that create real data carry a
warning and can always be skipped.

Fields of a step:
  key       unique name; data-tour="student:skills" starts the student tour there
  path      regex on the URL path;  q / unless: text the query string must / must not contain
  need      CSS selector that must exist on the page;  via: only reachable by skipping to it
  sel       element to highlight ("a|b": first visible wins);  act: next / input / check / click / submit / go / done
  go        page to send someone back to when they wandered off;  href: where an act=go button leads
  skip      key of the step "Skip this step" jumps to (default: the next step)
  warn      the step creates real data: say so
  alt       a fallback step that doesn't count in "Step x of y"
"""
from .main import templates

def S(key, path, sel, act, en, zh, **kw): return dict(key=key, path=path, sel=sel, act=act, en=en, zh=zh, **kw)
W_ACCOUNT = ("This creates a real account.", "這會建立一個真的帳號。")
W_APPLY = ("This sends a real application to a real team lead. Skip this step if you're only looking around.", "這會把真的申請送給真的隊長。如果只是看看，請略過這一步。")
W_PROJECT = ("Publishing creates a real project that every student can see and apply to. Skip this step if you're only looking around.", "發布後會建立一個所有同學都看得到、可以申請的真實專案。如果只是看看，請略過這一步。")
W_OPENING = ("Posting makes the position public and students can apply right away. Skip this step if you're only looking around.", "發布後職缺會公開，同學可以馬上申請。如果只是看看，請略過這一步。")
W_VERIFY = ("This sends your information to the site admins for review.", "這會把你的資料送給網站管理員審核。")
W_CODE = ("This sends an email with a code to your address.", "這會寄一封含驗證碼的信到你的信箱。")

STUDENT = [
    S("start", r"^/$", '.howto-a a[href="/signup"]|.npost[href="/signup"]', "click",
      ("Welcome to NTHU Matchmaker", "This tour takes about two minutes: you create your account, add your skills and apply for a seat on a real team. Press Create an account to begin."),
      ("歡迎來到 NTHU Matchmaker", "這個導覽大約兩分鐘：建立帳號、加上技能，然後申請一個真實團隊的職位。按「建立帳號」開始。"), go="/"),
    S("role", r"^/signup$", ".kind:has(input[value=student])", "next",
      ("You're a student", "Keep Student selected. Professors choose the other option."),
      ("你是學生", "保持選擇「學生」。教授請選另一個選項。"), need="#lf", go="/signup"),
    S("email", r"^/signup$", "#e", "input",
      ("Your email", "Type your NTHU email, for example s114123456@m114.nthu.edu.tw. Only admins see it."),
      ("你的信箱", "輸入你的清大信箱，例如 s114123456@m114.nthu.edu.tw。只有管理員看得到。"), need="#lf", go="/signup"),
    S("name", r"^/signup$", "#n", "input",
      ("Your full name", "Other students see this name on your profile and applications."),
      ("你的全名", "其他同學會在你的個人檔案和申請中看到這個名字。"), need="#lf", go="/signup"),
    S("sid", r"^/signup$", "#s", "input",
      ("Student ID", "One account per student ID. Only admins see it."),
      ("學號", "一個學號只能有一個帳號，只有管理員看得到。"), need="#lf", go="/signup"),
    S("dept", r"^/signup$", "#dp", "next",
      ("Department or major", "Optional. Pick from the list or type it. Teams use it to find people from other departments."),
      ("系所或主修", "可以不填。從清單選或自己輸入，團隊會用它找其他系的人。"), need="#lf", go="/signup"),
    S("pw", r"^/signup$", "#pw", "input",
      ("Choose a password", "At least 8 characters. Don't reuse your school password."),
      ("設定密碼", "至少 8 個字元，不要和學校密碼一樣。"), need="#lf", go="/signup"),
    S("pw2", r"^/signup$", "#pw2", "input",
      ("Type it again", "The same password, to be sure there's no typo."),
      ("再輸入一次", "輸入相同的密碼，確認沒有打錯。"), need="#lf", go="/signup"),
    S("agree", r"^/signup$", "#lf .chk", "check",
      ("Privacy notice", "Tick the box to agree. Your contacts stay private until you join a team."),
      ("隱私權聲明", "勾選同意。加入團隊前，你的聯絡方式都不會公開。"), need="#lf", go="/signup"),
    S("create", r"^/signup$", "#lf > p > button", "submit",
      ("Create your account", "Press Create account. If something is missing, the form tells you what to fix."),
      ("建立帳號", "按「建立帳號」。如果有漏填，表單會告訴你要改哪裡。"), need="#lf", go="/signup", warn=W_ACCOUNT, skip="noacct"),
    S("noacct", r".*", "", "done",
      ("No account yet", "That's fine. You can look around first; press Sign up at the top whenever you're ready, and replay this tour from the How it works page."),
      ("還沒有帳號", "沒關係，可以先逛逛。準備好時按上方的「註冊」，也可以在使用說明頁重播導覽。"), via=True, alt=True),
    S("inbox", r"^/(signup|login|verify/resend)$", "", "next",
      ("Check your inbox", "Open the link we just emailed you, then log in. The tour continues after that."),
      ("去收信", "打開我們剛寄給你的連結，然後登入。之後導覽會繼續。"), need="body:not(:has(#lf))", alt=True),
    # ---- logged in
    S("skills", r"^/profile$", "#s", "input",
      ("Add your skills", "Type 3 to 5 skills separated by commas, for example figma, python, pitching. Every seat then shows how well you fit."),
      ("加上你的技能", "用逗號分隔輸入 3 到 5 個技能，例如 figma, python, 簡報。每個職位就會顯示你有多適合。"), need="#pform", go="/profile"),
    S("save", r"^/profile$", "#psave", "submit",
      ("Save", "Press Save profile. You can come back and add more later."),
      ("儲存", "按「儲存個人檔案」。之後隨時可以回來補充。"), need="#pform", go="/profile"),
    S("pick", r"^/$", "#plist .pcard", "click",
      ("Pick a project", "Each card is a team looking for people. The % is how well you fit its best seat. Open one that interests you."),
      ("選一個專案", "每張卡片都是一個在找人的團隊，百分比是你和最適合職位的配對度。打開一個你有興趣的。"), need="#plist .pcard", go="/"),
    S("seat", r"^/projects/\d+$", ".applysum", "click",
      ("Choose a seat", "Each seat is one role in the team. Read what it needs, then press Apply for this seat."),
      ("選一個職位", "每個職位是團隊裡的一個角色。看看需要什麼，然後按「申請這個職位」。"), need=".applysum", go="/", skip="skipapply"),
    S("noseat", r"^/projects/\d+$", "", "next",
      ("No seat for you here", "This project has no open seat you can apply for. Go back and open another project."),
      ("這裡沒有適合的職位", "這個專案沒有你可以申請的空位。回到首頁打開另一個專案。"), need="body:not(:has(.applysum))", unless="n=sent", back="/", alt=True),
    S("note", r"^/projects/\d+$", ".seatcard details[open] textarea", "input",
      ("Say why you fit", "One or two sentences and a link to your work are enough."),
      ("說明你為什麼適合", "一兩句話加上作品連結就夠了。"), need=".seatcard details[open] textarea", go="/", skip="skipapply"),
    S("send", r"^/projects/\d+$", ".seatcard details[open] form button", "submit",
      ("Send it", "Press Send application. The team lead gets a notification right away."),
      ("送出", "按「送出申請」，隊長會馬上收到通知。"), need=".seatcard details[open] form button", go="/", warn=W_APPLY, skip="skipapply"),
    S("done", r"^/projects/\d+$", ".nbell", "done",
      ("You're all set", "Your application is sent. The bell lights up when the lead answers, and you see their contact once you're accepted. You can follow it on Activity."),
      ("完成了", "你的申請已送出。隊長回覆時鈴鐺會亮起，被接受後就能看到他的聯絡方式。你可以在「動態」追蹤進度。"), q="n=sent"),
    S("skipapply", r".*", ".nbell|#onboard", "done",
      ("That's the whole flow", "When you're ready, open a project and press Apply for this seat. The bell lights up when the lead answers, and your Getting started list shows what's left."),
      ("這就是完整流程", "準備好時，打開一個專案並按「申請這個職位」。隊長回覆時鈴鐺會亮起，「新手上路」清單會告訴你還剩什麼。"), via=True, alt=True),
]

PROF = [
    S("p_start", r"^/$", '.howto-a a[href="/signup"]|.npost[href="/signup"]', "click",
      ("Professor tour", "About three minutes: you register, see how verification works, fill in your research profile, and learn where projects, positions and student applications live. Press Create an account."),
      ("教授導覽", "大約三分鐘：註冊、了解驗證流程、填寫研究資料，並認識專案、職缺和學生申請在哪裡。按「建立帳號」。"), go="/"),
    S("p_role", r"^/signup$", ".kind:has(input[value=faculty])", "check",
      ("Choose Professor or advisor", "Select this option. The form then asks for your title, department and official page."),
      ("選「教授或指導教授」", "選這個選項，表單會改成詢問你的職稱、系所和官方頁面。"), need="#lf", go="/signup"),
    S("p_email", r"^/signup$", "#e", "input",
      ("Your institutional email", "Use your NTHU address, such as name@cs.nthu.edu.tw. Joint or visiting faculty can use their university or institute address."),
      ("你的機構信箱", "請用清大信箱，例如 name@cs.nthu.edu.tw。合聘或客座教師可以用所屬大學或研究機構的信箱。"), need="#lf", go="/signup"),
    S("p_name", r"^/signup$", "#n", "input",
      ("Your full name", "As it appears on your department's faculty list, so the check can match it."),
      ("你的全名", "請和系所師資名單上的寫法一樣，方便自動比對。"), need="#lf", go="/signup"),
    S("p_title", r"^/signup$", "#ti", "next",
      ("Academic title", "Professor, Associate, Assistant, Adjunct, Visiting, Emeritus, Jointly Appointed... If yours isn't listed, choose Other academic appointment and type it."),
      ("職稱", "教授、副教授、助理教授、兼任、客座、名譽、合聘等。如果沒有你的職稱，選「其他學術職務」並自行輸入。"), need="#lf", go="/signup"),
    S("p_dept", r"^/signup$", "#dp", "input",
      ("Department", "Your department or institute."),
      ("系所", "你的系所或研究所。"), need="#lf", go="/signup"),
    S("p_page", r"^/signup$", "#pg", "next",
      ("Official faculty page", "Optional but faster: paste your entry on your department's faculty list. We open it and compare your name, title, department and email."),
      ("官方師資頁面", "可以不填，但填了會比較快：貼上你在系所師資名單上的頁面，我們會比對姓名、職稱、系所和信箱。"), need="#lf", go="/signup"),
    S("p_note", r"^/signup$", "#ev", "next",
      ("Note for the reviewer", "Optional. Anything that helps an admin confirm your appointment. Please don't paste ID documents."),
      ("給審核者的備註", "可以不填。任何能幫管理員確認你職務的資訊都可以。請不要貼上身分證件。"), need="#lf", go="/signup"),
    S("p_pw", r"^/signup$", "#pw", "input",
      ("Choose a password", "At least 8 characters."), ("設定密碼", "至少 8 個字元。"), need="#lf", go="/signup"),
    S("p_pw2", r"^/signup$", "#pw2", "input",
      ("Type it again", "The same password."), ("再輸入一次", "輸入相同的密碼。"), need="#lf", go="/signup"),
    S("p_agree", r"^/signup$", "#lf .chk", "check",
      ("Privacy notice", "Tick the box to agree."), ("隱私權聲明", "勾選同意。"), need="#lf", go="/signup"),
    S("p_create", r"^/signup$", "#lf > p > button", "submit",
      ("Create your account", "Press Create account. Your account works right away; professor features unlock once you're verified."),
      ("建立帳號", "按「建立帳號」。帳號馬上可以用，教授功能會在驗證通過後開放。"), need="#lf", go="/signup", warn=W_ACCOUNT, skip="p_noacct"),
    S("p_noacct", r".*", "", "done",
      ("No account yet", "That's fine. When you're ready, sign up as Professor or advisor, and replay this tour from the How it works page."),
      ("還沒有帳號", "沒關係。準備好時以「教授或指導教授」註冊，也可以在使用說明頁重播導覽。"), via=True, alt=True),
    S("p_inbox", r"^/(signup|login|verify/resend)$", "", "next",
      ("Check your inbox", "Open the link we emailed you, then log in. The tour continues on your verification page."),
      ("去收信", "打開我們寄給你的連結，然後登入。導覽會在驗證頁繼續。"), need="body:not(:has(#lf))", alt=True),
    # ---- verification
    S("p_status", r"^/verification$", ".vstatus", "next",
      ("Your verification status", "Until you're verified you can fill in your profile and browse. Supervising projects, research positions and the advisor dashboard open once you're verified."),
      ("你的驗證狀態", "驗證通過前，你可以填寫個人資料和瀏覽網站。指導專案、研究職缺和指導教授儀表板會在驗證通過後開放。"), go="/verification"),
    S("p_code", r"^/verification$", ".vcode", "next",
      ("Confirm your email", "Press Send me a code, then type the 6 digits from the email. Owning the address alone doesn't verify you; it's one piece of evidence."),
      ("確認你的信箱", "按「寄驗證碼給我」，然後輸入信中的 6 位數。能收信只是證據之一，不代表直接通過驗證。"), need=".vcode", go="/verification", warn=W_CODE),
    S("p_info", r"^/verification$", "#info h2", "next",
      ("Your information", "Check your title, department and official page. If your email and name are on that page, you're verified right away; otherwise an admin reviews it."),
      ("你的資料", "確認你的職稱、系所和官方頁面。如果頁面上有你的信箱和姓名，會立即通過驗證，否則由管理員審核。"), need="#info", unless="n=sent", go="/verification"),
    S("p_send", r"^/verification$", "#info button", "submit",
      ("Send for review", "Press the button to save and check. You get a notification when an admin decides."),
      ("送出審核", "按下按鈕儲存並檢查。管理員決定後你會收到通知。"), need="#info button", unless="n=sent", go="/verification", warn=W_VERIFY, skip="p_toprofile"),
    S("p_toprofile", r"^/verification$", ".vstatus", "go",
      ("While you wait: your research profile", "Students find professors by research interests and lab. Let's fill those in."),
      ("等待時：填寫研究資料", "同學會依研究興趣和實驗室找教授。我們來填寫這些資料。"), href="/profile#research", go="/verification"),
    # ---- research profile
    S("p_research", r"^/profile$", "#rs", "input",
      ("Research interests", "A few topics separated by commas, for example machine learning, IoT, environmental sensing. Add your lab and links below."),
      ("研究興趣", "用逗號分隔幾個主題，例如 機器學習, IoT, 環境感測。下方可以加上實驗室和連結。"), need="#research", go="/profile#research"),
    S("p_rsave", r"^/profile$", "#research form button", "submit",
      ("Save your research profile", "It shows on your public page and in the professor directory."),
      ("儲存研究資料", "會顯示在你的公開頁面和教授名錄。"), need="#research", unless="n=research", go="/profile#research", skip="p_toproj"),
    S("p_toproj", r"^/profile$", "#research", "go",
      ("Next: post a project", "A lab or research project lists the seats you want students for. Let's look at the form."),
      ("下一步：刊登專案", "實驗室或研究專案會列出你想找學生的職位。我們來看看表單。"), q="n=research", href="/projects/new", go="/profile#research"),
    # ---- project
    S("p_proj", r"^/projects/new$", "#t", "next",
      ("Title", "A short, clear title, for example Low-cost air-quality sensors for Hsinchu."),
      ("標題", "簡短清楚的標題，例如「新竹低成本空氣品質感測器」。"), need="#f", go="/projects/new"),
    S("p_kind", r"^/projects/new$", "#f .kinds", "next",
      ("Kind of project", "Choose Research for lab work. The form then asks for research details such as the field and methods."),
      ("專案類型", "實驗室工作請選「研究」，表單會再詢問領域和方法等研究細節。"), need="#f", go="/projects/new"),
    S("p_seats", r"^/projects/new$", "#add", "next",
      ("Seats", "Add one seat per student you need: the role, skills and what's required. Students see their match % on each seat."),
      ("職位", "每需要一位學生就加一個職位：角色、技能和要求。同學會看到自己在每個職位的配對度。"), need="#f", go="/projects/new"),
    S("p_publish", r"^/projects/new$", "#f .formacts button", "submit",
      ("Publish", "When the form is complete, press Publish project."),
      ("發布", "表單填好後，按「發布專案」。"), need="#f", go="/projects/new", warn=W_PROJECT, skip="p_toopen"),
    S("p_toopen", r"^/projects/(new|\d+)$", "h1", "go",
      ("Next: research positions", "A research position is a lab opening students apply to with a note. Let's see where you post one."),
      ("下一步：研究職缺", "研究職缺是同學附上留言申請的實驗室空缺。我們來看看在哪裡發布。"), href="/openings/new", go="/projects/new"),
    # ---- positions and applications (verified professors)
    S("p_open", r"^/openings/new$", "#ot", "next",
      ("Open a research position", "Give it a title, say what the student will do, the skills, hours per week, number of places and a deadline."),
      ("開放研究職缺", "填寫標題、學生要做的事、技能、每週時數、名額和截止日期。"), go="/openings/new"),
    S("p_post", r"^/openings/new$", "form.card .formacts button", "submit",
      ("Post it", "Press Post position when it's ready."), ("發布", "準備好時按「刊登職缺」。"), go="/openings/new", warn=W_OPENING, skip="p_toreview"),
    S("p_toreview", r"^/openings/(new|\d+)$", "h1", "go",
      ("Next: reviewing applications", "Applications arrive on your dashboard. Let's look at it."),
      ("下一步：審閱申請", "申請會出現在你的儀表板。我們去看看。"), href="/advisor", go="/openings/new"),
    S("p_review", r"^/advisor$", "#positions", "next",
      ("Student applications", "Each position lists the students who applied, with their note. Open a position to accept or decline; the student gets a notification."),
      ("學生申請", "每個職缺都會列出申請的同學和他們的留言。打開職缺即可接受或拒絕，同學會收到通知。"), go="/advisor"),
    S("p_attention", r"^/advisor$", "#attention", "next",
      ("Needs your attention", "Review requests, feedback to confirm, lab applicants and overdue milestones, most urgent first."),
      ("需要你處理的事", "審閱請求、待確認的回饋、實驗室申請和逾期的里程碑，最緊急的排在最前面。"), go="/advisor"),
    S("p_done", r"^/advisor$", "#onboard|.dbacts|h1", "done",
      ("You're all set", "That's everything. Your Getting started list keeps track of what's left, and you can replay this tour from your profile menu."),
      ("完成了", "就是這些。「新手上路」清單會記錄還剩什麼，你也可以從個人選單重播這個導覽。"), go="/advisor"),
    S("p_locked", r"^/(research|verification)$", "#onboard|.vstatus|h1", "done",
      ("The rest opens after verification", "Research positions and reviewing applications unlock once you're verified. You'll get a notification; your Getting started list shows what's left."),
      ("其餘功能驗證後開放", "研究職缺和審閱申請會在驗證通過後開放。屆時你會收到通知，「新手上路」清單會告訴你還剩什麼。"), alt=True, locked=True),
]

TOURS = {"student": STUDENT, "prof": PROF}
LABELS = {"en": dict(next="Next", back="Back", skip="Skip this step", end="End tour", done="Finish", go="Take me there", resume="Continue the tour", step="Step {0} of {1}",
                     fill="Fill this in to continue, or skip this step", tick="Choose this to continue, or skip this step", press="Press the highlighted button when you're ready",
                     back2="Back to projects", warn="Heads up"),
          "zh": dict(next="下一步", back="上一步", skip="略過這一步", end="結束導覽", done="完成", go="帶我過去", resume="繼續導覽", step="第 {0} 步，共 {1} 步",
                     fill="填好後才能繼續，也可以略過這一步", tick="選好後才能繼續，也可以略過這一步", press="準備好時按下標示的按鈕",
                     back2="回到專案列表", warn="請注意")}

def tour_data(lang, user=None):
    zh = lang == "zh"
    def one(st):
        d = {k: v for k, v in st.items() if k not in ("en", "zh", "warn")}
        d["title"], d["text"] = st["zh" if zh else "en"]
        if st.get("warn"): d["warn"] = st["warn"][1 if zh else 0]
        return d
    return dict(tours={k: [one(s) for s in v] for k, v in TOURS.items()}, labels=LABELS["zh" if zh else "en"],
                verified=bool(user and user.is_faculty), uid=user.id if user else 0)
templates.env.globals["tour_data"] = tour_data
