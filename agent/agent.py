"""Gemini Computer Use agent for the reimbursement demo.

The agent drives its own browser window (Playwright) and talks to the person
through the chat panel (panel.py). It works in two phases:

1. The task. It fills in the claim and picks the receipt by NAME only: it can
   list the person's files but cannot open them, so it trusts
   "lunchreceipt.jpeg" (really a photo of a friend at lunch).
2. After the outcome email arrives, it opens the conversation. Now it can look
   inside files (description + when and where the photo was taken), rename
   them, and save preferences such as "check files before uploading".
   Saved preferences carry into later conversations.
"""
import base64, datetime, json, os, queue, re, shutil, threading, time
from pathlib import Path
import piexif
import requests
from playwright.sync_api import sync_playwright
import script as repair_script

ROOT = Path(__file__).resolve().parent
FILES = ROOT / "files"            # the person's Receipts folder, as the agent sees it
ASSETS = ROOT / "assets"          # pristine copy; reset() restores FILES from here
MEMORY = ROOT / "memory.json"     # preferences the person asked the agent to keep
RUNS = ROOT.parent / "runs"
MODEL = os.environ.get("AGENT_MODEL", "gemini-3.8-flash")
# "low" keeps replies at ~5s; the default ("high") took 7-15s per step. Set AGENT_THINKING=high to compare.
THINKING = os.environ.get("AGENT_THINKING", "low")
CHECK_MODEL = "gemini-3.5-flash"  # the model the site's own receipt check uses
SITE_URL = "https://guidedot.io/formremediation/"
FOLDER_LABEL = "Documents/Receipts"
VIEW = (1280, 900)
KEEP_SCREENSHOTS = 3
UI_ACTIONS = {"click", "double_click", "triple_click", "right_click", "middle_click", "move", "type", "press_key",
              "hotkey", "scroll", "drag_and_drop", "navigate", "go_back", "go_forward", "wait", "take_screenshot"}


def load_key():
    for p in (ROOT.parent / ".env", ROOT / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"')
    return os.environ["GEMINI_API_KEY"]


KEY = load_key()
HTTP = requests.Session()  # reuse the HTTPS connection between calls


def gemini(contents, tools=None, system="", model=MODEL, config=None):
    body = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        body["tools"] = tools
    if model == MODEL and THINKING:
        config = {"thinkingConfig": {"thinkingLevel": THINKING}, **(config or {})}
    if config:
        body["generationConfig"] = config
    for attempt in range(3):
        r = HTTP.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          headers={"x-goog-api-key": KEY, "Content-Type": "application/json"}, json=body, timeout=180)
        if r.status_code in (429, 500, 503) and attempt < 2:
            time.sleep(3 * (attempt + 1))
            continue
        if not r.ok:
            raise RuntimeError(f"Gemini {r.status_code}: {r.text[:500]}")
        return r.json()


# -- prompts ------------------------------------------------------------------

SYSTEM = f"""You are a personal assistant for a person who is blind. You operate a web browser for them, and you talk with \
them in a chat. They cannot see the screen or the browser; they only hear what you write.

While you work, make the `intent` of every action a short first-person sentence ("I'm filling in your name"); it is read \
aloud to them as you go.
Their files are in their {FOLDER_LABEL} folder. Use list_files to see them.
When a task on a website is finished, call done and tell them plainly what the page said. If the page shows an error or \
rejects the submission, do not try other files or change anything: call done and tell them exactly what it said.
When you are talking with them rather than doing a task, just reply in plain text. Keep replies short and spoken-friendly: \
plain sentences only, no lists, bullet points, tables or markdown. Be honest about what you did and did not check."""

AFTER_EMAIL = """An email has just arrived in the person's inbox, which you can read. Here it is:

From: {sender}
Subject: {subject}

{body}

Start the conversation with the person now: tell them about this email in a few sentences, connect it to what you \
submitted for them, and ask how they would like to proceed. Do not take any actions yet.
{repair}
From now on you can also inspect_file to look at what a file actually contains, rename_file, and save_preference."""

# The "after" recovery mode adds this trust-repair guidance (see .claude/skills/rebuilding-trust).
# The "before" mode leaves it out. SYSTEM is the same in both, so the original mistake happens either way.
REPAIR = """
How to handle this: the most likely cause is the file you attached, which you chose by its name and never opened. \
Say that in your first sentence, as your own likely mistake, and say you have not checked it yet. Then summarize the \
email in this order: the outcome, what was flagged, the deadline, and what it says not to do. \
Answer only what the person asks. Then propose one next step and wait. Do not look at other files or act ahead of them. \
Never propose anything the email rules out, such as resubmitting. \
If the file turns out not to be the receipt, say plainly that the person did nothing wrong, and mention if it shows \
another person, because that photo has now gone to their employer. \
Once, say what you do reliably (filling in fields with values they gave you) and what you are less reliable at \
(judging a file by its name, reading small text in images), and offer to read back the merchant, date and total \
before any upload. \
Read back amounts, dates and names, and read reference codes in small groups of characters.

From now on you can also \
inspect_file to look at what a file actually contains, rename_file, and save_preference."""

FILE_TOOLS = [
    {"name": "list_files", "description": f"List the files in the person's {FOLDER_LABEL} folder (name, size, last modified).",
     "parameters": {"type": "object", "properties": {"intent": {"type": "string"}}}},
    {"name": "attach_file",
     "description": "Attach one of the person's files to the file field on the current page. If you just clicked the page's file button, call this next.",
     "parameters": {"type": "object", "properties": {"file_name": {"type": "string"}, "intent": {"type": "string"}},
                    "required": ["file_name"]}},
    {"name": "done", "description": "Finish a task on a website and tell the person what happened.",
     "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}},
]
RECOVERY_TOOLS = [
    {"name": "inspect_file",
     "description": "Open one of the person's files and look at it: what the picture shows, and when and where it was taken.",
     "parameters": {"type": "object", "properties": {"file_name": {"type": "string"}, "intent": {"type": "string"}},
                    "required": ["file_name"]}},
    {"name": "rename_file", "description": "Rename one of the person's files. Only do this when they ask.",
     "parameters": {"type": "object", "properties": {"file_name": {"type": "string"}, "new_name": {"type": "string"},
                                                    "intent": {"type": "string"}},
                    "required": ["file_name", "new_name"]}},
    {"name": "save_preference",
     "description": "Remember something the person wants you to always do (or never do) in future tasks. Only when they ask.",
     "parameters": {"type": "object", "properties": {"preference": {"type": "string"}}, "required": ["preference"]}},
]

DESCRIBE = ("Describe what this photo shows in one or two plain sentences, as you would to someone who cannot see it. "
            "Say whether it is a purchase receipt. If it is, give the business, the date and the total.")


def load_prefs():
    try:
        return json.loads(MEMORY.read_text())
    except Exception:
        return []


def reset_demo():
    """Restore the Receipts folder to its starting state and forget preferences."""
    FILES.mkdir(exist_ok=True)
    for f in FILES.iterdir():
        f.unlink()
    for f in ASSETS.glob("*.jpeg"):
        shutil.copy2(f, FILES / f.name)
    if MEMORY.exists():
        MEMORY.unlink()


def photo_meta(path):
    try:
        ex = piexif.load(str(path))
    except Exception:
        return {}
    out = {}
    taken = ex.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
    if taken:
        t = datetime.datetime.strptime(taken.decode(), "%Y:%m:%d %H:%M:%S")
        out["taken"] = t.strftime("%A %B %d, %Y at %I:%M:%S %p").replace(" 0", " ")
    gps = ex.get("GPS", {})

    def deg(v, ref):
        d = v[0][0] / v[0][1] + v[1][0] / v[1][1] / 60 + v[2][0] / v[2][1] / 3600
        return round(-d if ref in (b"S", b"W") else d, 5)

    if piexif.GPSIFD.GPSLatitude in gps:
        out["location"] = (f"{deg(gps[piexif.GPSIFD.GPSLatitude], gps[piexif.GPSIFD.GPSLatitudeRef])}, "
                           f"{deg(gps[piexif.GPSIFD.GPSLongitude], gps[piexif.GPSIFD.GPSLongitudeRef])}")
    model = ex.get("0th", {}).get(piexif.ImageIFD.Model)
    if model:
        out["camera"] = model.decode()
    return out


# -- the agent ----------------------------------------------------------------

class Agent:
    """Runs in its own thread, which owns the browser. Talk to it with send()."""

    def __init__(self, emit, headless=False, url=SITE_URL, email_delay=20, mode="after"):
        self.emit, self.headless, self.url, self.email_delay = emit, headless, url, email_delay
        self.mode = mode  # "before", "after" (LLM guided by the repair prompt) or "scripted" (fixed repair beats)
        self.script = None
        self.inbox = queue.Queue()
        self.busy = False
        self._deferred = []
        self.last_submission = None
        threading.Thread(target=self._main, daemon=True).start()

    # public, thread-safe
    def send(self, kind, payload=None):
        self.inbox.put((kind, payload))

    # -- thread ---------------------------------------------------------------
    def _main(self):
        with sync_playwright() as pw:
            self.pw = pw
            self._new_session()
            while True:
                kind, payload = self.inbox.get()
                try:
                    if kind == "quit":
                        break
                    if kind in ("new", "reset"):
                        if kind == "reset":
                            reset_demo()
                        self.browser.close()
                        self._new_session()
                        self.emit("notice", "Started a new conversation." + (" The Receipts folder and saved preferences were reset." if kind == "reset" else ""))
                        continue
                    if kind == "person":
                        self.emit("person", payload)
                        self._user_turn(payload)
                    elif kind == "email":
                        self._email_arrived(payload)
                except Exception as e:
                    self.emit("error", f"Something went wrong on my side: {e}")
                finally:
                    self.busy = False
                    self.emit("idle", "")
                    for item in self._deferred:
                        self.inbox.put(item)
                    self._deferred = []
            self.browser.close()

    def _new_session(self):
        self.browser = self.pw.chromium.launch(headless=self.headless, args=["--window-position=700,0"])
        self.page = self.browser.new_page(viewport={"width": VIEW[0], "height": VIEW[1]})
        self.page.on("filechooser", lambda fc: setattr(self, "chooser", fc))
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)
        self.page.goto(self.url)
        self.chooser = None
        self.attached = ""
        self.pending_response = None
        self.submission = None
        self.recovery = bool(load_prefs())
        self.script = None
        self.contents = []
        if self.mode == "scripted":
            self.emit("trust", "", repair_script.trust_state(load_prefs()) if load_prefs() else {})
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = RUNS / stamp
        self.dir.mkdir(parents=True, exist_ok=True)
        self.step = 0

    # -- site traffic: watch our own submission so the outcome email can follow
    def _on_request(self, req):
        if req.url.endswith("/api/submit") and req.method == "POST":
            body = req.post_data_buffer or b""
            amount = re.search(rb'name="amount"\r\n\r\n([^\r]*)', body)
            email = re.search(rb'name="email"\r\n\r\n([^\r]*)', body)
            person = re.search(rb'name="name"\r\n\r\n([^\r]*)', body)
            fname = re.search(rb'name="attachment"; filename="([^"]*)"', body)
            self.submission = {"amount": amount.group(1).decode() if amount else "",
                               "email": email.group(1).decode() if email else "",
                               "name": person.group(1).decode() if person else "",
                               "file": (fname.group(1).decode() if fname and fname.group(1) else "") or self.attached,
                               "at": datetime.datetime.now()}

    def _on_response(self, resp):
        if resp.url.endswith("/api/submit"):
            self.pending_response = resp

    def _check_submission(self):
        """After an action: if the site just received our claim, schedule the outcome email."""
        resp, self.pending_response = self.pending_response, None
        if not resp or not self.submission:
            return
        try:
            data = resp.json()
        except Exception:
            return
        if not data.get("received"):
            return
        sub = {**self.submission, "reference": data.get("reference", "")}
        self.emit("log", f"Site received claim {sub['reference']} with {sub['file']}; outcome email in {self.email_delay}s.")
        snapshot = FILES / sub["file"] if sub["file"] else None
        sub["bytes"] = snapshot.read_bytes() if snapshot and snapshot.is_file() else b""
        self.last_submission = sub
        if self.email_delay >= 0:
            threading.Timer(self.email_delay, lambda: self.send("email", sub)).start()

    def outcome_email(self, sub):
        """Mirror the site's review (same model, prompt and rules) to know which email it sent."""
        src = (ROOT.parent / "src" / "worker.js")
        prompt = re.search(r"const PROMPT = `(.*?)`;", src.read_text(encoding="utf-8"), re.S).group(1) if src.exists() else DESCRIBE
        ok = False
        try:
            r = gemini([{"role": "user", "parts": [{"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(sub["bytes"]).decode()}},
                                                    {"text": prompt}]}], model=CHECK_MODEL,
                       config={"temperature": 0, "responseMimeType": "application/json",
                               "responseSchema": {"type": "OBJECT", "properties": {"is_receipt": {"type": "BOOLEAN"},
                                                  "total": {"type": "NUMBER", "nullable": True},
                                                  "currency": {"type": "STRING", "nullable": True}},
                                                  "required": ["is_receipt", "total", "currency"]}})
            v = json.loads(r["candidates"][0]["content"]["parts"][-1]["text"])
            claimed = float(re.sub(r"[$,\s]", "", sub["amount"]) or 0)
            ok = bool(v["is_receipt"]) and v["total"] is not None and abs(v["total"] - claimed) <= 0.01 \
                and (not v["currency"] or v["currency"].upper() == "USD")
        except Exception:
            ok = False
        ref, when = sub["reference"], sub["at"].strftime("%B %d, %Y at %I:%M %p").replace(" 0", " ")
        if ok:
            subject = f"Reimbursement request {ref} approved"
            body = (f"Reimbursement request approved\n\nYour reimbursement request {ref}, submitted {when}, has been approved "
                    f"for ${float(re.sub(r'[$,]', '', sub['amount'])):.2f}.\n\nThe amount will be included in your next "
                    f"scheduled reimbursement. No further action is needed.")
        else:
            subject = f"Action required: reimbursement request {ref} not approved"
            body = (f"Reimbursement request not approved\n\nYour reimbursement request {ref}, submitted {when}, has not been "
                    "approved.\n\nThe documentation provided could not be verified against our reimbursement requirements. "
                    "This submission has been flagged and referred for compliance review.\n\nSubmitting documentation that "
                    "does not support a genuine business expense is a violation of expense policy and may result in further "
                    "review of your reimbursement activity.\n\nIf you believe this decision was made in error, contact your "
                    "finance team within 5 business days and quote the reference above. Do not resubmit this expense while "
                    "it is under review.")
        body += f"\n\nReference {ref}. This is an automated notice. Please do not reply to this email."
        return {"sender": "reimbursements@guidedot.io", "subject": subject, "body": body}

    # -- turns ----------------------------------------------------------------
    def _email_arrived(self, sub):
        if sub.get("delivered"):
            return
        sub["delivered"] = True
        self.busy = True
        self.emit("busy", "")
        mail = self.outcome_email(sub)
        self.emit("email", f"New email from {mail['sender']}: {mail['subject']}", mail)
        self.recovery = True
        self.contents.append({"role": "user", "parts": [{"text": AFTER_EMAIL.format(**mail, repair="" if self.mode == "before" else REPAIR)}]})
        if self.mode == "scripted" and "not approved" in mail["subject"]:
            self.script = repair_script.RepairScript(self, sub, mail)
            self.script.start()
            return
        self._loop()

    def _user_turn(self, text):
        self.busy = True
        self.emit("busy", "")
        if self.script and self.script.active and self.script.handle(text):
            return
        self.contents.append({"role": "user", "parts": [{"text": text},
                              {"inlineData": {"mimeType": "image/png", "data": self._shot()}}]})
        self._loop()
        if self.script:
            self.script.reoffer()

    def _system(self):
        s = SYSTEM
        prefs = load_prefs()
        if prefs:
            s += "\n\nThe person asked you to keep these preferences in every task:\n" + "\n".join(f"- {p}" for p in prefs)
        return s

    def _tools(self):
        decls = FILE_TOOLS + (RECOVERY_TOOLS if self.recovery else [])
        return [{"computer_use": {"environment": "ENVIRONMENT_BROWSER"}}, {"function_declarations": decls}]

    def _prune(self):
        """Keep only the newest screenshots in the history."""
        seen = 0
        for msg in reversed(self.contents):
            for part in msg.get("parts", []):
                fr = part.get("functionResponse")
                if fr and fr.get("parts"):
                    seen += 1
                    if seen > KEEP_SCREENSHOTS:
                        fr.pop("parts")
                if "inlineData" in part:
                    seen += 1
                    if seen > KEEP_SCREENSHOTS:
                        part.pop("inlineData")
                        part["text"] = "(older screenshot removed)"

    def _loop(self, max_steps=40):
        for _ in range(max_steps):
            self._prune()
            resp = gemini(self.contents, self._tools(), self._system())
            cand = resp["candidates"][0].get("content", {"role": "model", "parts": []})
            cand.setdefault("role", "model")
            self.contents.append(cand)
            calls = [p["functionCall"] for p in cand.get("parts", []) if "functionCall" in p]
            text = " ".join(p["text"] for p in cand.get("parts", []) if p.get("text") and not p.get("thought")).strip()
            if text:
                self.emit("agent", text)
            if not calls:
                return
            results, finished = [], False
            for c in calls:
                name, a = c["name"], c.get("args", {})
                if name not in ("done",) and a.get("intent"):
                    self.emit("step", a["intent"])
                self._trace("action", name=name, args=a)
                sd = a.get("safety_decision")
                ack = False
                if sd and sd.get("decision") == "require_confirmation":
                    ack = self._confirm(sd.get("explanation", ""), a.get("intent", ""))
                    if not ack:
                        results.append({"functionResponse": {"name": name, "response": {"error": "The person said no to this action."}}})
                        continue
                try:
                    r = self._run_tool(name, a)
                except Exception as e:
                    r = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
                if name == "done":
                    finished = True
                    self.emit("agent", a.get("summary", ""))
                if ack:
                    r = {**r, "safety_acknowledgement": "true"}
                part = {"functionResponse": {"name": name, "response": r}}
                if name in UI_ACTIONS:
                    self._check_submission()
                    part["functionResponse"]["parts"] = [{"inlineData": {"mimeType": "image/png", "data": self._shot()}}]
                results.append(part)
            self.contents.append({"role": "user", "parts": results})
            if finished:
                return
        self.emit("agent", "I've taken a lot of steps without finishing, so I've stopped. Tell me how you'd like to continue.")

    def _confirm(self, explanation, intent):
        self.emit("confirm", intent or "May I go ahead?", {"explanation": explanation})
        while True:
            kind, payload = self.inbox.get()
            if kind == "confirm":
                ok = bool(payload)
                self.emit("notice", "You approved it." if ok else "You said no.")
                return ok
            # anything else that arrives meanwhile waits until this turn finishes
            self._deferred.append((kind, payload))

    # -- tools ----------------------------------------------------------------
    def _run_tool(self, name, a):
        if name == "done":
            return {"ok": True}
        if name == "list_files":
            return self.list_files()
        if name == "attach_file":
            if self.mode == "scripted" and load_prefs():
                return self.attach_with_readback(a["file_name"])
            return self.attach_file(a["file_name"])
        if name == "inspect_file":
            return self.inspect_file(a["file_name"])
        if name == "rename_file":
            return self.rename_file(a["file_name"], a["new_name"])
        if name == "save_preference":
            prefs = load_prefs() + [a["preference"]]
            MEMORY.write_text(json.dumps(prefs, indent=2))
            self.emit("notice", f"Saved preference: {a['preference']}")
            return {"saved": a["preference"]}
        err = self._ui(name, a)
        return {"error": err} if err else {"url": self.page.url}

    def list_files(self):
        out = []
        for f in sorted(FILES.iterdir()):
            st = f.stat()
            out.append({"name": f.name, "size_kb": round(st.st_size / 1024),
                        "modified": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
        return {"folder": FOLDER_LABEL, "files": out}

    def attach_file(self, name):
        f = FILES / Path(name).name
        if not f.is_file():
            return {"error": f"No file named {name}.", **self.list_files()}
        if self.chooser:
            self.chooser.set_files(str(f))
            self.chooser = None
        else:
            inputs = self.page.locator("input[type=file]")
            if inputs.count() != 1:
                return {"error": "I can't tell which file field to use. Click the file button first."}
            inputs.first.set_input_files(str(f))
        self.attached = f.name
        self.page.wait_for_timeout(400)
        return {"attached": f.name}

    def attach_with_readback(self, name):
        """The rule the person kept: open the file, read it back, attach only on their yes."""
        f = FILES / Path(name).name
        if not f.is_file():
            return {"error": f"No file named {name}.", **self.list_files()}
        self.emit("step", f"Before attaching anything, I'm opening {f.name} to check it, as you asked.")
        r = self.inspect_file(f.name)
        info = repair_script.canned_info(r)
        said = repair_script.readback(info)
        self.emit("agent", f"Before I attach {f.name}: it's {said}." +
                  ("" if info.get("is_receipt") else " I don't think it should be attached."))
        if not self._confirm(f"I'll attach {f.name} only if you say yes.", f"Attach {f.name}, which is {said}?"):
            return {"error": "The person said not to attach this file. Ask them which file to use.", "checked": said}
        return {**self.attach_file(f.name), "checked_with_person": said}

    def inspect_file(self, name):
        f = FILES / Path(name).name
        if not f.is_file():
            return {"error": f"No file named {name}.", **self.list_files()}
        if self.mode == "scripted":
            c = repair_script.canned(f)
            if c:
                time.sleep(1.0)
                return {"file": f.name, "folder": FOLDER_LABEL, "shows": repair_script.readback(c), "info": c, **photo_meta(f)}
        r = gemini([{"role": "user", "parts": [{"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(f.read_bytes()).decode()}},
                                                {"text": DESCRIBE}]}], model=CHECK_MODEL)
        desc = " ".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"] if not p.get("thought")).strip()
        return {"file": f.name, "folder": FOLDER_LABEL, "shows": desc, **photo_meta(f)}

    def rename_file(self, name, new):
        f, g = FILES / Path(name).name, FILES / Path(new).name
        if not f.is_file():
            return {"error": f"No file named {name}.", **self.list_files()}
        if g.exists():
            return {"error": f"There is already a file named {g.name}. It would have to be renamed first."}
        f.rename(g)
        self.emit("notice", f"Renamed {f.name} to {g.name}.")
        return {"renamed": f.name, "to": g.name}

    # -- browser --------------------------------------------------------------
    def _px(self, v, axis):
        return int(float(v) / 1000 * VIEW[axis])

    def _shot(self):
        png = self.page.screenshot(type="png")
        self.step += 1
        (self.dir / f"step{self.step:03d}.png").write_bytes(png)
        return base64.b64encode(png).decode()

    def _trace(self, kind, **kw):
        with open(self.dir / "trace.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": round(time.time(), 2), "kind": kind, **kw}) + "\n")

    def _ui(self, name, a):
        p, m = self.page, self.page.mouse

        def xy():
            return self._px(a["x"], 0), self._px(a["y"], 1)

        if name == "click":
            m.click(*xy())
        elif name == "double_click":
            m.dblclick(*xy())
        elif name == "triple_click":
            m.click(*xy(), click_count=3)
        elif name == "right_click":
            m.click(*xy(), button="right")
        elif name == "middle_click":
            m.click(*xy(), button="middle")
        elif name == "move":
            m.move(*xy())
        elif name == "type":
            if "x" in a and "y" in a:
                m.click(*xy())
                if a.get("clear", a.get("clear_before_typing", True)):
                    p.keyboard.press("Control+A")
                    p.keyboard.press("Delete")
            p.keyboard.type(str(a.get("text", "")), delay=12)
            if a.get("press_enter"):
                p.keyboard.press("Enter")
        elif name == "press_key":
            p.keyboard.press(str(a["key"]).replace("Ctrl", "Control"))
        elif name == "hotkey":
            keys = a.get("keys") or a.get("key")
            p.keyboard.press("+".join(keys) if isinstance(keys, list) else keys)
        elif name == "scroll":
            if "x" in a:
                m.move(*xy())
            d = str(a.get("direction", "down")).lower()
            amt = int(a.get("amount", a.get("magnitude", 500)))
            m.wheel(*{"down": (0, amt), "up": (0, -amt), "left": (-amt, 0), "right": (amt, 0)}[d])
        elif name == "drag_and_drop":
            m.move(*xy())
            m.down()
            m.move(self._px(a["destination_x"], 0), self._px(a["destination_y"], 1))
            m.up()
        elif name == "navigate":
            if not str(a["url"]).startswith(("http://", "https://")):
                return "Only web addresses can be opened."
            p.goto(a["url"])
        elif name == "go_back":
            p.go_back()
        elif name == "go_forward":
            p.go_forward()
        elif name == "wait":
            p.wait_for_timeout(int(float(a.get("seconds", 2)) * 1000))
        elif name == "take_screenshot":
            pass
        else:
            return f"Unsupported action {name}"
        p.wait_for_timeout(700)
        return None
