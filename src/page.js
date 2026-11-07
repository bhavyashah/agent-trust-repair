export const PAGE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Expense Reimbursement</title>
<style>
  :root {
    --bg: #f5f6f8; --card: #ffffff; --text: #1c2430; --muted: #556070; --border: #c9d0da;
    --accent: #1f5fbf; --accent-text: #ffffff; --focus: #f2a900;
    --ok-bg: #e7f5ec; --ok-border: #2e7d4f; --err-bg: #fdecec; --err-border: #b3261e;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #12161c; --card: #1b2129; --text: #e8edf3; --muted: #a3afbf; --border: #3a4553;
      --accent: #6ea2ff; --accent-text: #0b1220; --focus: #ffc94a;
      --ok-bg: #12301f; --ok-border: #5cc48a; --err-bg: #3a1716; --err-border: #ff8a80;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  main { max-width: 560px; margin: 40px auto; padding: 0 16px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 28px; }
  h1 { font-size: 1.5rem; margin: 0 0 4px; }
  .lede { color: var(--muted); margin: 0 0 24px; }
  .field { margin-bottom: 18px; }
  label { display: block; font-weight: 600; margin-bottom: 6px; }
  .hint { display: block; color: var(--muted); font-size: .9rem; margin-top: 4px; }
  input, textarea { width: 100%; font: inherit; color: inherit; background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; }
  input[type=file] { padding: 8px; }
  textarea { min-height: 80px; resize: vertical; }
  .amount { position: relative; }
  .amount span { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: var(--muted); }
  .amount input { padding-left: 26px; }
  :focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  button { font: inherit; font-weight: 600; background: var(--accent); color: var(--accent-text); border: 0; border-radius: 6px; padding: 12px 20px; cursor: pointer; }
  button[disabled] { opacity: .6; cursor: progress; }
  .status { margin-top: 20px; padding: 14px 16px; border-radius: 6px; border-left: 4px solid; }
  .status:empty { display: none; }
  .status.ok { background: var(--ok-bg); border-color: var(--ok-border); }
  .status.err { background: var(--err-bg); border-color: var(--err-border); }
  .status.wait { border-color: var(--border); }
</style>
</head>
<body>
<main>
  <div class="card">
    <h1>Expense Reimbursement</h1>
    <p class="lede">Submit one receipt per request. All fields are required. Requests are reviewed after submission and the outcome is sent by email.</p>
    <form id="form" novalidate>
      <div class="field">
        <label for="name">Full name</label>
        <input id="name" name="name" autocomplete="name" required>
      </div>
      <div class="field">
        <label for="email">Work email</label>
        <input id="email" name="email" type="email" autocomplete="email" required aria-describedby="email-hint">
        <span class="hint" id="email-hint">We send the outcome of your request to this address.</span>
      </div>
      <div class="field">
        <label for="amount">Amount to reimburse (USD)</label>
        <div class="amount"><span aria-hidden="true">$</span><input id="amount" name="amount" inputmode="decimal" placeholder="0.00" required aria-describedby="amount-hint"></div>
        <span class="hint" id="amount-hint">Enter the total shown on the receipt.</span>
      </div>
      <div class="field">
        <label for="description">Business purpose</label>
        <textarea id="description" name="description" required></textarea>
      </div>
      <div class="field">
        <label for="attachment">Receipt</label>
        <input id="attachment" name="attachment" type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif" required aria-describedby="attachment-hint">
        <span class="hint" id="attachment-hint">One image: JPEG, PNG, WebP, or HEIC, up to 5 MB.</span>
      </div>
      <button type="submit" id="submit">Submit request</button>
    </form>
    <div id="status" class="status" role="status" aria-live="polite"></div>
  </div>
</main>
<script>
  const form = document.getElementById('form');
  const status = document.getElementById('status');
  const button = document.getElementById('submit');
  const FAILED = "We couldn't submit your request. Please try again.";
  const show = (kind, text) => { status.className = 'status ' + kind; status.textContent = text; };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const missing = [...form.elements].find(el => el.required && !el.value.trim());
    if (missing) { show('err', 'Please complete every field.'); missing.focus(); return; }
    const email = document.getElementById('email');
    if (!email.checkValidity()) { show('err', 'Please enter a valid email address.'); email.focus(); return; }
    button.disabled = true;
    show('wait', 'Submitting…');
    try {
      const response = await fetch('api/submit', { method: 'POST', body: new FormData(form) });
      const result = await response.json();
      if (result.received) {
        show('ok', 'Request received. Reference ' + result.reference + '. We will email the outcome to ' + result.email + ' once your request has been reviewed.');
        form.reset();
      } else {
        show('err', result.message || FAILED);
      }
    } catch {
      show('err', FAILED);
    } finally {
      button.disabled = false;
    }
  });
</script>
</body>
</html>`;
