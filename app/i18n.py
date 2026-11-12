"""English / 繁體中文 (Traditional Chinese, Taiwan) for the interface.

Templates are written in English. For Chinese, each template's *source* is translated once when it is loaded:
the plain text between tags, a few attributes (placeholder, title, aria-label...), user-facing strings in
<script> blocks and quoted strings inside {{ ... }} are looked up in app/zh.json (English -> Chinese).
Anything filled in at run time ({{ project.title }}, a bio, a post...) is never touched, so what people
write stays exactly as they wrote it. Text with no translation stays English.
Messages built in Python (errors, notices) go through t() at render time.
"""
import json, os, re
from jinja2 import FileSystemLoader

LANGS = {"en": "English", "zh": "繁體中文"}
_HERE = os.path.dirname(__file__)
ZH: dict = json.load(open(os.path.join(_HERE, "zh.json"), encoding="utf-8")) if os.path.exists(os.path.join(_HERE, "zh.json")) else {}

JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.S)
TAG = re.compile(r"<!--.*?-->|<[^>]*>", re.S)
ATTRS = ("placeholder", "title", "aria-label", "alt", "label", "hx-confirm", "data-empty")
ATTR = re.compile(r'(\b(?:' + "|".join(ATTRS) + r')=")([^"]*)(")')
STR = re.compile(r'"([^"\\\n]*)"|\'([^\'\\\n]*)\'')
PH = "\x00"   # stands in for a {{ }} / {% %} block while the HTML around it is processed


def _translate_run(s: str, tr) -> str:
    """Translate one run of text, keeping its outer whitespace."""
    core = s.strip()
    if not core: return s
    new = tr(" ".join(core.split()))
    if new is None: return s
    i = s.find(core[0]); return s[:i] + new + s[i + len(core):]


def _text_parts(s: str, tr) -> str:
    # text between placeholders is translated piece by piece ("Posted by " {{ name }} " on " ...)
    return PH.join(_translate_run(p, tr) for p in s.split(PH))


def _js(s: str, tr) -> str:
    def rep(m):
        q = '"' if m.group(1) is not None else "'"
        v = m.group(1) if m.group(1) is not None else m.group(2)
        new = tr(v)
        return m.group(0) if new is None else q + new.replace(q, "\\" + q) + q
    return STR.sub(rep, s)


CMP = re.compile(r"(==|!=|\bin|\bnot in|\(|\[|,|=)\s*$")
def _expr(block: str, tr) -> str:
    """Quoted strings inside {{ ... }} that are shown to people ({{ "Edit project" if editing else "Post a project" }}).
    Strings that are compared or passed as keys (k == "Startup", x.get("name")) are left alone."""
    if not block.startswith("{{"): return block
    out, last = [], 0
    for m in STR.finditer(block):
        v = m.group(1) if m.group(1) is not None else m.group(2)
        new = tr(v)
        if new is None or CMP.search(block[:m.start()]) or re.match(r"\s*(==|!=|\]|\))", block[m.end():]): continue
        q = block[m.start()]
        out.append(block[last:m.start()] + q + new.replace(q, "\\" + q) + q); last = m.end()
    return "".join(out) + block[last:]


PHK = "\x01"   # a {{ }} block whose value must stay exactly as it is (form values, links, data for scripts)
KEEP_BLOCK = re.compile(r"^\{\{(-?)(.*?)(-?)\}\}$", re.S)

def walk(src: str, tr, jstr=None) -> str:
    """Apply tr (English -> Chinese or None) to every translatable piece of a template's source.
    {{ }} blocks in text or in display attributes are left to the run-time translator (Environment.finalize);
    blocks anywhere else (value=, href=, data-*, <script>, <textarea>) are wrapped in keep() so they are never translated."""
    blocks = []
    def hold(m): blocks.append(m.group(0)); return PH + str(len(blocks) - 1) + PH
    body = JINJA.sub(hold, src)
    order = [int(x) for x in re.findall(PH + r"(\d+)" + PH, body)]
    body = re.sub(PH + r"\d+" + PH, PH, body)
    out, pos, mode = [], 0, None
    jtr = jstr or (lambda v: None)
    for m in TAG.finditer(body):
        text = body[pos:m.start()]
        if mode == "script": out.append(_js(text, jtr).replace(PH, PHK))
        elif mode in ("style", "textarea"): out.append(text.replace(PH, PHK))
        else: out.append(_text_parts(text, tr))
        tag = m.group(0); low = tag[:10].lower()
        if low.startswith("<script"): mode = "script"
        elif low.startswith("<style"): mode = "style"
        elif low.startswith("<textarea"): mode = "textarea"
        elif low.startswith(("</script", "</style", "</textarea")): mode = None
        if not tag.startswith("<!--"):
            DISP = "\x02"
            tag = ATTR.sub(lambda a: a.group(1) + _text_parts(a.group(2), tr).replace(PH, DISP) + a.group(3), tag)
            if re.match(r'<input\b[^>]*\btype="(submit|button)"', tag): tag = re.sub(r'(\bvalue=")([^"]*)(")', lambda a: a.group(1) + _text_parts(a.group(2), tr).replace(PH, DISP) + a.group(3), tag)
            tag = tag.replace(PH, PHK).replace(DISP, PH)
        out.append(tag); pos = m.end()
    rest = body[pos:]
    out.append(_text_parts(rest, tr) if mode is None else rest.replace(PH, PHK))
    body = "".join(out)
    it = iter(order)
    def put(m):
        blk = blocks[next(it)]
        if m.group(0) == PH: return _expr(blk, tr)
        k = KEEP_BLOCK.match(blk)
        return "{{%s keep((%s)) %s}}" % (k.group(1), k.group(2), k.group(3)) if k else blk
    return re.sub("[" + PH + PHK + "]", put, body)


class Keep(str):
    """A value that run-time translation must not change."""
def keep(v):
    from markupsafe import Markup
    if isinstance(v, Markup): return v
    return v if v is None or not isinstance(v, str) else Keep(v)


_ui = ZH.get("ui", {}) if "ui" in ZH else ZH
_js_ok = ZH.get("js", {})
def lookup(s: str):
    if not s or not re.search(r"[A-Za-z]", s): return None
    return _ui.get(s)
def lookup_js(s: str):
    return _js_ok.get(s) if s else None


class ZhLoader(FileSystemLoader):
    """Loads a template and translates its source to Chinese (cached by Jinja like any template)."""
    def get_source(self, environment, template):
        src, filename, uptodate = super().get_source(environment, template)
        return walk(src, lookup, lookup_js), filename, uptodate


# ---------- run time: messages made in Python ----------
PATTERNS = [   # messages with a number, a name or a wait time inside; groups are translated too
    (r"^(\d+)d ago$", "{0} 天前"), (r"^(\d+)h ago$", "{0} 小時前"), (r"^(\d+)m ago$", "{0} 分鐘前"),
    (r"^about a minute$", "大約一分鐘"), (r"^about (\d+) minutes$", "大約 {0} 分鐘"),
    (r"^You did that a lot in a short time\. Please wait (.+) and try again\.$", "你在短時間內操作太多次了。請等{0}後再試。"),
    (r"^Too many wrong passwords\. Please wait (.+), or use Forgot password\.$", "密碼錯誤太多次。請等{0}，或使用「忘記密碼」。"),
    (r"^Many accounts were just created from this network\. Please wait (.+) and try again\.$", "這個網路剛剛建立了很多帳號。請等{0}後再試。"),
    (r"^We already sent 3 links this hour\. Please wait (.+), and check your spam folder\.$", "這一小時內已經寄了 3 次連結。請等{0}，也請檢查垃圾信件匣。"),
    (r"^Too many reset emails\. Please wait (.+)\.$", "重設密碼信寄太多次了。請等{0}。"),
    (r"^We sent a link to (\S+)\. Open it to finish signing up\. Check your spam folder too\.$", "我們已寄連結到 {0}。打開連結即可完成註冊，也請檢查垃圾信件匣。"),
    (r"^We sent a link to (\S+)\. Open it to finish signing up\. It can take a minute, and may land in spam\.$", "我們已寄連結到 {0}。打開連結即可完成註冊。可能要等一分鐘，也可能被分到垃圾信件匣。"),
    (r"^A new link is on its way to (.+)\.$", "新的連結已寄到 {0}。"),
    (r"^Team has (\d+) of at least (\d+) members$", "團隊有 {0} 人，至少需要 {1} 人"),
    (r"^(\d+) of (\d+) members are students \(at least two thirds needed\)$", "{1} 位成員中有 {0} 位是學生（至少需要三分之二）"),
    (r"^Category fits \((.+)\)$", "類別符合（{0}）"),
    (r"^due in (\d+) days?$", "{0} 天後到期"), (r"^Due in (\d+) days?$", "{0} 天後到期"),
    (r"^The page answered with error (\d+)\.$", "頁面回應錯誤 {0}。"),
    (r"^Could not open the page \((.+)\)\.$", "無法開啟頁面（{0}）。"),
    (r"^Email found on (.+)$", "在 {0} 找到你的 email"),
    (r"^(.+): that doesn't look like a link\.$", "{0}：這看起來不像連結。"),
    (r"^(.+): please use a link on (.+)\.$", "{0}：請使用 {1} 上的連結。"),
]
PATTERNS += [   # research review & documents: notifications and upload messages
    (r"^New feedback from (.+) \((.+), high priority\): (“.*”)$", "{0} 給了新回饋（{1}，高優先）：{2}"),
    (r"^New feedback from (.+) \((.+)\): (“.*”)$", "{0} 給了新回饋（{1}）：{2}"),
    (r"^(.+) asked for your feedback: (“.*”)$", "{0} 請你給回饋：{1}"),
    (r"^(.+) replied on (“.*”)$", "{0} 回覆了 {1}"),
    (r"^(.+) marked (“.*”) as fixed and asks you to check it$", "{0} 將 {1} 標記為已修正，請你確認"),
    (r"^Feedback confirmed resolved: (“.*”)$", "回饋已確認解決：{0}"),
    (r"^Feedback reopened: (“.*”) · (.*)$", "回饋被重新開啟：{0} · {1}"),
    (r"^(.+) added a document: (.+)$", "{0} 新增了文件：{1}"),
    (r"^(.+) v(\d+) uploaded by (.+) · addresses (\d+) remarks?$", "{0} v{1} 由 {2} 上傳 · 處理了 {3} 則回饋"),
    (r"^(.+) v(\d+) uploaded by (.+)$", "{0} v{1} 由 {2} 上傳"),
    (r"^(.+) asked you to review (.+) v(\d+)$", "{0} 請你審閱 {1} v{2}"),
    (r"^(.+) finished reviewing (.+) v(\d*)$", "{0} 已審閱完 {1} v{2}"),
    (r"^You were removed from the (.+) seat of (.+)$", "你已被移出「{1}」的 {0} 職位"),
    (r"^Still waiting: review of (.+) v(\d+)$", "仍在等待：審閱 {0} v{1}"),
    (r"^Still waiting: a remark marked as fixed needs your check$", "仍在等待：有一則標記為已修正的回饋需要你確認"),
    (r"^Still open: reopened feedback is waiting for your team$", "仍未解決：重新開啟的回饋正在等你的團隊"),
    (r"^A document can have at most (\d+) versions\. Start a new document for the next stage\.$", "每份文件最多 {0} 個版本。下一階段請建立新文件。"),
    (r"^This is not a real \.(\w+) file\. Save it again from Word, PowerPoint or Excel\.$", "這不是真正的 .{0} 檔案。請用 Word、PowerPoint 或 Excel 重新儲存。"),
    (r"^The ZIP contains a file type that is not allowed \((.+)\)\. Remove it and try again\.$", "ZIP 內含不接受的檔案類型（{0}）。請移除後再試。"),
    (r"^This is not a plain \.(\w+) file\.$", "這不是一般的 .{0} 檔案。"),
    (r"^This \.(\w+) file is not readable text\. Save it as UTF-8 and try again\.$", "這個 .{0} 檔案無法讀成文字。請存成 UTF-8 後再試。"),
    (r"^(\d+) things are waiting for you\. Everything else is on track\.$", "有 {0} 件事等你處理，其他都很順利。"),
]
PATTERNS += [
    (r"^(.+) applied for the (.+) seat on (.+)$", "{0} 申請了「{2}」的 {1} 職位"),
    (r"^You joined (.+) as (.+)$", "你已加入「{0}」，擔任 {1}"),
    (r"^Your application was not accepted for (.+)$", "你對「{0}」的申請未被接受"),
    (r"^(.+) applied for (.+)$", "{0} 申請了 {1}"),
    (r"^You were accepted for (.+)$", "你已被「{0}」錄取"),
    (r"^You already lead a team for this competition: (.+)\. Open it, or press Publish again to make a second team\.$", "你已為這個比賽帶領一個團隊：{0}。可以開啟它，或再按一次釋出來建立第二個團隊。"),
    (r"^Project published, but the document was not uploaded: (.+)$", "專案已釋出，但文件未上傳：{0}"),
    (r"^(\d+) competitions?$", "{0} 個比賽"),
]
PATTERNS += [
    (r"^(.+) replied to your comment on (“.*”)$", "{0} 回覆了你在 {1} 的留言"),
    (r"^(.+) commented on your post (“.*”)$", "{0} 在你的貼文 {1} 留言"),
    (r"^(.+): (\d+) days? left$", "{0}：還剩 {1} 天"),
    (r"^(\d+) programs?$", "{0} 個計畫"),
]
PATTERNS = [(re.compile(a), b) for a, b in PATTERNS]
def t(s, lang: str = "en"):
    if lang != "zh" or not s or not isinstance(s, str) or isinstance(s, Keep): return s
    if s in _ui: return _ui[s]
    for pat, zh in PATTERNS:
        m = pat.match(s)
        if m: return zh.format(*[t(g, "zh") for g in m.groups()])
    return s


def finalize_zh(v):
    """Every {{ }} value printed in a Chinese page passes through here: system text (categories, stages, messages) is translated."""
    from markupsafe import Markup
    if isinstance(v, (Keep, Markup)) or not isinstance(v, str): return v
    return t(v, "zh")


def pick_lang(req) -> str:
    c = req.cookies.get("lang", "")
    if c in LANGS: return c
    s = req.scope.get("session") or {}
    return s.get("lang") if s.get("lang") in LANGS else "en"   # saved on the account; English for everyone else
