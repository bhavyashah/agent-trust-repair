# Rebuilding trust after an agent's mistake

A demo built at the AI for Accessibility Collective's Accessible Agentic AI Workshop (Stanford, November 6, 2026).

A blind person asks a browser agent to file an expense reimbursement. The agent fills in the form and attaches the receipt, but it picks the file **by name only**. `lunchreceipt.jpeg` is really a photo of a friend at lunch, so the claim is rejected and the finance team is told a non-receipt was submitted.

The demo is about what happens next. It shows how an agent working for someone who can't see the screen should recover from its own mistake:

1. **Own the mistake specifically**, before anything else, and explain the rejection email: the outcome, the flag on the claim, the deadline, and what not to do (don't resubmit while it's under review).
2. **Check before claiming anything.** It opens the file only when asked, describes what it actually shows (and when and where the photo was taken), and makes clear that the person did nothing wrong.
3. **Find the real receipt** and report the evidence (merchant, date, total) and how sure it is.
4. **Propose a plan rather than act.** It offers an alternative and lets the person approve each step. It drafts a note to finance but sends nothing.
5. **Say where it is and isn't reliable**, and suggest a concrete rule: "before attaching any file, open it and read me the merchant, date and total."
6. **Earn autonomy back.** It saves the rule only on a yes, keeps it for later conversations, and shows what it will now do on its own and what it will check first.

## Pieces

- `src/`: the reimbursement form, a Cloudflare Worker. Gemini checks each upload; if the attachment isn't a receipt, the claim is rejected and an outcome email goes out.
- `agent/agent.py`: a Gemini Computer Use agent that drives its own Playwright browser and narrates each step in short first-person sentences meant to be read aloud.
- `agent/panel.py` and `panel.html`: the chat panel the person uses with their screen reader.
- `agent/script.py`: a scripted version of the repair conversation with reply buttons, so every run of the demo shows the same repair. The tools still run for real.
- `agent/gen_photos.py` and `make_assets.py`: generate the demo photos (all AI-generated; nobody real is shown) and add camera metadata.

## Running it

Needs Python with `requests`, `piexif`, `pillow` and `playwright`, plus a `.env` file containing `GEMINI_API_KEY=...`.

```
python agent/panel.py --reset            # free LLM conversation, with the repair guidance
python agent/panel.py --reset --script   # scripted repair beats
python agent/panel.py --reset --before   # no repair guidance, for comparison
```

On Windows, `Run Demo.bat` and `Run Scripted Demo.bat` do the same thing. To deploy the form, use `npx wrangler deploy` after `wrangler secret put GOOGLE_VERTEX_KEY`.
