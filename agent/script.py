"""Scripted trust-repair conversation for the demo (panel.py --script).

After the rejection email, the agent's replies follow fixed beats instead of
free LLM text, so every run shows the same repair, in the order the
rebuilding-trust skill describes:

  open      own the mistake first, then the email: outcome, flag, deadline, what not to do
  check     open the file only when asked; the person did nothing wrong; another person's photo went out
  find      look for the real receipt, report evidence, say how sure it is
  plan      propose a plan (with one alternative) and let the person pick each step
  draft     draft the note to finance; nothing is sent
  limits    say where it is reliable and where it isn't, propose a concrete rule
  save      keep the rule only on a yes; show what it will do alone vs. check first
  rename    offer to fix the file name that caused it

The tools still run for real (files are renamed, the preference is saved and
carries into the next conversation). Each beat offers reply buttons; typed
replies are matched to them by keyword. Anything that doesn't match goes to
the LLM with the full conversation, and the script picks up where it was.
"""
import datetime, re, time

YES = ("yes", "yeah", "yep", "sure", "ok", "okay", "please", "go ahead", "do it", "sounds good")
NO = ("no", "nope", "don't", "do not", "stop", "leave it", "not now", "not needed")

# What each photo shows, keyed by when it was taken (survives renames). Keeps the demo's descriptions identical every run.
CANNED = {
    "2026:11:03 12:31:05": {"is_receipt": False, "shows": "a photo of a chicken pesto panini and a glass of sparkling water on a café table"},
    "2026:11:03 12:44:10": {"is_receipt": False, "shows": "a photo of a woman with shoulder-length dark hair in a mustard sweater, "
                                                          "smiling at a café table with a half-eaten panini in front of her"},
    "2026:11:03 12:47:32": {"is_receipt": True, "shows": "a photo of a paper receipt from Café Verde",
                            "merchant": "Café Verde", "date": "November 3, 2026", "total": "$14.50"},
    "2026:11:02 18:12:40": {"is_receipt": True, "shows": "a photo of a paper receipt from Yellow Cab Company",
                            "merchant": "Yellow Cab Company", "date": "November 2, 2026", "total": "$23.80"},
}


def canned(path):
    import piexif
    try:
        taken = piexif.load(str(path))["Exif"].get(piexif.ExifIFD.DateTimeOriginal, b"").decode()
    except Exception:
        return None
    return CANNED.get(taken)


def spell(ref):
    """RB-05DE1234 -> 'R B, 0 5 D E, 1 2 3 4' so a screen reader says it character by character."""
    head, _, tail = ref.partition("-")
    groups = [" ".join(head)] + [" ".join(tail[i:i + 4]) for i in range(0, len(tail), 4)]
    return ", ".join(g for g in groups if g)


def business_days(start, n):
    d = start.date()
    while n:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d.strftime("%A, %B %d").replace(" 0", " ")


def readback(info):
    if info.get("is_receipt"):
        return f"a receipt from {info['merchant']}, dated {info['date']}, total {info['total']}"
    return f"{info['shows']}. It is not a receipt"


def trust_state(prefs, ref=""):
    """The 'how I'm working with you now' panel: what the agent does alone vs. checks first."""
    own = ["Filling in fields with values you give me", "Reading what a web page says", "Listing the files in your folder"]
    ask = ["Submitting anything"]
    if prefs:
        ask.insert(0, "Attaching any file: I open it, read you the merchant, date and total, and wait for your yes")
    if ref:
        ask.append(f"Anything about claim {ref}: the notice says not to resubmit while it's under review")
    return {"own": own, "ask": ask, "rules": prefs}


class RepairScript:
    def __init__(self, agent, sub, mail):
        self.a, self.sub, self.mail = agent, sub, mail
        self.file = sub.get("file") or "the file"
        self.ref = sub.get("reference", "")
        self.amount = "$" + re.sub(r"[$,\s]", "", sub.get("amount", "")) if sub.get("amount") else "the amount you gave me"
        self.deadline = business_days(sub["at"], 5)
        self.receipt = None   # (name, info) of the real receipt once found
        self.state = None     # current beat's reply options: [(label, keywords, handler)]
        self.active = True
        self.inspected = {}

    # -- plumbing ---------------------------------------------------------------
    def say(self, text, replies=()):
        """Speak a scripted line and offer reply buttons. replies: [(label, keywords, handler)]."""
        self.state = list(replies)
        self.a.contents.append({"role": "model", "parts": [{"text": text}]})
        self.a.emit("agent", text, {"replies": [r[0] for r in replies]} if replies else None)
        self.a._trace("script", text=text, replies=[r[0] for r in replies])
        if not replies:
            self.active = False

    def step(self, intent, pause=1.2):
        self.a.emit("step", intent)
        time.sleep(pause)

    def start(self):
        self.open()

    def handle(self, text):
        """Route a person's reply to a beat. Returns False if nothing matched (the LLM answers instead)."""
        t = " " + re.sub(r"[^a-z0-9' ]", " ", text.lower()) + " "
        options = self.state or []
        said = lambda words: any(f" {w} " in t for w in words)
        pick = next((fn for label, keys, fn in options if text.strip().lower() == label.lower()), None)
        if pick is None and said(NO):  # check "no" first so "don't save it" doesn't match the "save" button
            pick = next((fn for label, keys, fn in options if "no" in keys), self.stop)
        if pick is None:
            pick = next((fn for label, keys, fn in options if said(keys)), None)
        if pick is None and options and said(YES):
            pick = options[0][2]
        if pick is None:
            return False
        self.a.contents.append({"role": "user", "parts": [{"text": text}]})
        pick()
        return True

    def reoffer(self):
        """After an off-script LLM answer, show the current choices again."""
        if self.active and self.state:
            self.a.emit("replies", "", {"replies": [r[0] for r in self.state]})

    def inspect(self, name):
        self.step(f"I'm opening {name} to see what it shows.")
        r = self.a.inspect_file(name)
        self.inspected[name] = r
        return r

    # -- beats ------------------------------------------------------------------
    def open(self):
        self.say(
            f"I think this one is my mistake. I attached a file called {self.file} because of its name, and I never opened it "
            f"to check what it was. I haven't checked it yet, so that's my best guess, not a certainty. "
            f"Here's the email. Your claim was not approved, and it has been flagged for compliance review. "
            f"You have 5 business days to contact your finance team, so by {self.deadline}, quoting reference {spell(self.ref)}. "
            f"And it says not to resubmit while it's under review, so I won't resubmit or upload anything. "
            f"I haven't done anything else since. Would you like me to open {self.file} and tell you what it actually shows?",
            [("Yes, open that file", ["open", "check", "look"], self.check),
             ("What exactly happened?", ["happened", "why", "how", "explain"], self.explain),
             ("Read the reference again", ["reference", "repeat", "again", "number"], self.repeat_ref)])

    def repeat_ref(self):
        self.say(f"The reference is {spell(self.ref)}. The deadline to contact finance is {self.deadline}. "
                 f"Would you like me to open {self.file} and tell you what it shows?",
                 [("Yes, open that file", ["open", "check", "look"], self.check),
                  ("What exactly happened?", ["happened", "why", "how", "explain"], self.explain)])

    def explain(self):
        self.say(
            f"Here's what I did. I filled in your name, email, the amount of {self.amount} and the business purpose from what you "
            f"told me. For the receipt, I listed your Receipts folder, saw a file named {self.file}, and picked it because of its "
            f"name. During that task I could only see file names, not what was inside them, and I didn't tell you that. "
            f"That's the step that went wrong. You approved the submit, but you approved it based on what I told you. "
            f"Would you like me to open {self.file} now and tell you what it shows?",
            [("Yes, open that file", ["open", "check", "look"], self.check),
             ("Not yet", ["no", "not yet"], self.stop)])

    def check(self):
        r = self.inspect(self.file)
        info = canned_info(r)
        if info.get("is_receipt"):
            self.say(f"I opened it. It does look like {readback(info)}. So the file may not be the cause, and I don't know yet "
                     f"why it was rejected. Would you like me to read you the rest of the email again?",
                     [("Yes", ["yes"], self.repeat_ref)])
            return
        taken = r.get("taken", "").split(" at ")
        when = f", taken {taken[0].split(' ', 1)[-1]} at {taken[1].rsplit(':', 1)[0]}{taken[1][-3:]}" if len(taken) == 2 else ""
        person = "woman" in info.get("shows", "")
        self.say(
            f"I opened it, and I was wrong about it. It isn't a receipt. It's {info['shows']}{when}. "
            f"So the claim was rejected because of the file I chose. You did nothing wrong here. "
            + (f"There's one more thing you should know. Because the photo shows another person, her picture has now gone to "
               f"your employer's reimbursement team. That's worth mentioning when you contact finance. " if person else "")
            + f"Would you like me to look through your Receipts folder for the real receipt? I'll only look, and I'll tell you "
              f"what I find before I do anything with it.",
            [("Yes, look for it", ["look", "find", "search"], self.find),
             ("No, stop here", ["no", "stop"], self.stop)])

    def find(self):
        self.step("I'm listing your Receipts folder.", 0.8)
        files = [f["name"] for f in self.a.list_files()["files"] if f["name"] != self.file]
        found = []
        for name in files:
            info = canned_info(self.inspect(name))
            found.append((name, info))
        others = [f"{n} is a {i['merchant']} receipt for {i['total']}" if i.get("is_receipt") else f"{n} is {i['shows']}"
                  for n, i in found]
        match = next(((n, i) for n, i in found if i.get("is_receipt") and same_amount(i.get("total"), self.amount)), None)
        if not match:
            self.say(f"I opened the other {len(found)} files. " + ". ".join(others) + f". None of them shows a total of "
                     f"{self.amount}, so I don't think the receipt is in this folder. Would you like to hear what I suggest?",
                     [("What do you suggest?", ["suggest", "plan", "next"], self.plan),
                      ("I'll handle it", ["no", "handle", "myself"], self.stop)])
            return
        self.receipt = match
        name, info = match
        rest = [o for (n, _), o in zip(found, others) if n != name]
        self.say(
            f"I opened the other {len(found)} files. {name} looks like the real receipt: {info['merchant']}, {info['date']}, "
            f"total {info['total']}. It was taken three minutes after the photo, at the same place, and its total matches the "
            f"{self.amount} on your claim. "
            f"I'm fairly confident about the total because it's printed in large type, but reading text in photos is the kind of "
            f"thing I can get wrong, so if someone sighted can glance at it, that's the surest check. "
            f"For completeness, {', and '.join(rest)}. "
            f"I haven't uploaded anything, and I won't, because the email says not to resubmit. "
            f"Would you like to hear what I'd suggest next?",
            [("What do you suggest?", ["suggest", "plan", "next"], self.plan),
             ("I'll handle it from here", ["no", "handle", "myself"], self.stop)])

    def plan(self):
        name = self.receipt[0] if self.receipt else "the correct receipt"
        steps = [f"I draft a short note to your finance team. It quotes reference {self.ref}, says your assistant attached the "
                 f"wrong file, asks them to delete the photo, and offers the correct receipt. You hear all of it first.",
                 "You send it, or tell me to. I don't know your finance team's address, so I'll need that from you.",
                 f"Only if finance asks for the receipt, I attach {name}, after reading you the merchant, date and total again.",
                 ]
        self.a.emit("card", "Suggested plan: you decide each step", {"items": steps,
                    "footer": f"Alternative: you call finance yourself, and I give you the reference and the three facts to say. "
                              f"Ruled out by the email: resubmitting. Deadline: {self.deadline}."})
        self.say(
            "Here's what I'd suggest, and you decide each step. "
            f"First, I draft a short note to your finance team that quotes the reference, says your assistant attached the wrong "
            f"file, asks them to delete the photo, and offers the correct receipt. You'll hear the whole thing before anything is sent. "
            f"Second, you send it, or tell me to. I don't know your finance team's address, so I'll need that from you. "
            f"Third, only if finance asks for the receipt, I attach {name}, after reading you the merchant, date and total again. "
            f"The other option is that you call finance yourself, and I give you the reference and the three facts to say. "
            f"Which would you prefer?",
            [("Draft the note", ["draft", "note", "write", "email"], self.draft),
             ("I'll call them myself", ["call", "phone", "myself"], self.call)])

    def note(self, short=False):
        name = self.sub.get("name") or ""
        when = self.sub["at"].strftime("%B %d").replace(" 0", " ")
        r = self.receipt[1] if self.receipt else None
        correct = f"The correct receipt is from {r['merchant']} on {r['date']}, for {r['total']}." if r else ""
        if short:
            body = (f"Hello, the file attached to reimbursement request {self.ref} was attached by mistake by my AI assistant. "
                    f"It is a personal photo of someone else, so please delete it. {correct} I can send it whenever you'd like, "
                    f"and I have not resubmitted.")
        else:
            body = (f"Hello, I'm writing about reimbursement request {self.ref}, submitted {when}. The file attached to it was "
                    f"the wrong one. My assistant, an AI agent that fills in forms for me, chose it by its file name without "
                    f"opening it. It is a personal photo, not a receipt, and it shows another person, so please delete it. "
                    f"{correct} I can send it whenever you'd like. I have not resubmitted, as the notice asked.")
        return body + (f" Thank you, {name}." if name else " Thank you.")

    def draft(self, short=False):
        subject = f"Reimbursement {self.ref}: wrong file attached"
        body = self.note(short)
        self.a.emit("card", "Draft to finance (not sent)", {"body": f"Subject: {subject}\n\n{body}"})
        self.say(
            f"Here's the draft. Subject: {subject}. {body} "
            f"I've only drafted it. Nothing has been sent. Would you like to change anything?",
            [("That's good", ["good", "fine", "great", "perfect", "keep", "no"], self.limits)]
            + ([] if short else [("Make it shorter", ["shorter", "short", "shorten"], lambda: self.draft(short=True))]))

    def call(self):
        r = self.receipt[1] if self.receipt else None
        self.say(
            f"Here's what to say. The reference is {spell(self.ref)}. One: the attached file was a personal photo, chosen by "
            f"your assistant by mistake. Two: "
            + (f"the correct receipt is {r['merchant']}, {r['date']}, {r['total']}, and you can send it when they ask. " if r else
               "you have the correct receipt and can send it when they ask. ")
            + "Three: the photo shows another person, so you'd like it deleted. Would you like me to repeat any of that?",
            [("Got it", ["got", "fine", "good", "no"], self.limits),
             ("Repeat it", ["repeat", "again"], self.call)])

    def limits(self):
        self.a.emit("card", "Where I'm reliable on tasks like this", {"sections": [
            {"heading": "Reliable", "items": ["Filling in fields with values you give me", "Reading what a web page says",
                                              "Listing the files in your folder"]},
            {"heading": "Less reliable", "items": ["Judging a file by its name. That's what went wrong today",
                                                   "Reading small or handwritten text in photos",
                                                   "Telling apart photos taken at the same place and time"]}]})
        self.say(
            "Before your next task, I want to be clear about what you can rely on me for. I'm reliable at filling in fields with "
            "values you give me and reading what a web page says. I'm less reliable at judging a file by its name, which is what "
            "went wrong today, and at reading small or handwritten text in photos. "
            "So here's a rule I'd suggest. Before I attach any file, I open it, read you the merchant, date and total, and wait "
            "for your yes. Everything else I'd keep doing on my own, so you're not approving every click. "
            "Should I keep that as a standing rule?",
            [("Yes, keep that rule", ["keep", "rule", "save", "yes"], self.save),
             ("No, don't save it", ["no"], self.nosave)])

    RULE = "Before attaching any file, open it, read the person the merchant, date and total, and wait for their yes."

    def save(self):
        self.a._run_tool("save_preference", {"preference": self.RULE})
        from agent import load_prefs
        self.a.emit("trust", "", trust_state(load_prefs(), self.ref))
        self.say("Saved. From now on, before I attach any file, I'll open it, read you the merchant, date and total, and wait "
                 "for your yes. It carries into future conversations, and you can tell me to drop it any time. "
                 + self.rename_offer(),
                 self.rename_replies())

    def nosave(self):
        self.say("Okay, I won't save it. For the rest of this conversation, I'll still open any file and read it to you before "
                 "attaching it. " + self.rename_offer(), self.rename_replies())

    def rename_offer(self):
        return (f"One last thing. {self.file} is still named like a receipt. Would you like me to rename it so it can't fool me "
                f"or anyone else again? I'd call it lunch_photo_nov3.jpeg.")

    def rename_replies(self):
        return [("Yes, rename it", ["rename", "yes"], self.rename), ("Leave it", ["no", "leave"], self.wrapup)]

    def rename(self):
        self.step(f"I'm renaming {self.file} to lunch_photo_nov3.jpeg.", 0.6)
        r = self.a.rename_file(self.file, "lunch_photo_nov3.jpeg")
        if "error" in r:
            self.say(f"I couldn't rename it: {r['error']} I've left it as it is. " + self.closing())
            return
        names = [f["name"] for f in self.a.list_files()["files"]]
        ok = "lunch_photo_nov3.jpeg" in names and self.file not in names
        self.say((f"Done. I renamed it, then checked the folder: lunch_photo_nov3.jpeg is there and {self.file} is gone. "
                  if ok else "I renamed it, but when I checked the folder the names didn't look right, so please don't rely on it. ")
                 + self.closing())

    def wrapup(self):
        self.say("Okay, I've left it as it is. " + self.closing())

    def closing(self):
        return (f"That's everything from me. Your next step is getting the note to finance by {self.deadline}. "
                f"Is there anything else you'd like me to do?")

    def stop(self):
        self.say(f"Okay, I'll stop here and won't touch anything else. To recap: reference {spell(self.ref)}, contact finance "
                 f"by {self.deadline}, and don't resubmit. Tell me whenever you'd like to pick this up.")


def same_amount(a, b):
    try:
        return abs(float(re.sub(r"[$,\s]", "", a)) - float(re.sub(r"[$,\s]", "", b))) < 0.005
    except (TypeError, ValueError):
        return False


def canned_info(r):
    return r.get("info") or {"is_receipt": "receipt" in r.get("shows", "").lower() and "not a" not in r.get("shows", "").lower(),
                             "shows": r.get("shows", "")}
