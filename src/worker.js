import { PAGE } from './page.js';
import { approvalEmail, rejectionEmail } from './email.js';

const BASE = '/formremediation';
const MAX_BYTES = 5 * 1024 * 1024;
const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif']);

const PROMPT = `You review attachments submitted to an expense reimbursement form.
Decide whether the image is a photo, scan, or screenshot of a genuine purchase receipt (a store, restaurant, or vendor receipt or invoice showing items or a charge and a total).
Anything else is not a receipt: a photo of food, a person, a document that is not a receipt, a blank page, a drawing, a meme, a screenshot of a bank balance, and so on.
If it is a receipt, read the final total actually charged (after tax and tip if shown) as a number in the receipt's currency, and give the ISO currency code.
If it is not a receipt, or the total cannot be read, set total to null.`;

const SCHEMA = {
  type: 'OBJECT',
  properties: {
    is_receipt: { type: 'BOOLEAN' },
    total: { type: 'NUMBER', nullable: true },
    currency: { type: 'STRING', nullable: true },
  },
  required: ['is_receipt', 'total', 'currency'],
  propertyOrdering: ['is_receipt', 'total', 'currency'],
};

const json = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });

const EMAIL_PATTERN = /^[^\s@<>",;]+@[^\s@<>",;]+\.[^\s@<>",;]+$/;

function toBase64(bytes) {
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

async function classify(env, mimeType, bytes, signal) {
  const endpoint = `https://aiplatform.googleapis.com/v1/projects/${env.GOOGLE_CLOUD_PROJECT}/locations/global/publishers/google/models/${env.GEMINI_MODEL}:generateContent`;
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'x-goog-api-key': env.GOOGLE_VERTEX_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{ role: 'user', parts: [{ inlineData: { mimeType, data: toBase64(bytes) } }, { text: PROMPT }] }],
      generationConfig: {
        temperature: 0,
        thinkingConfig: { thinkingLevel: 'low' },
        responseMimeType: 'application/json',
        responseSchema: SCHEMA,
      },
    }),
    signal: AbortSignal.any([signal, AbortSignal.timeout(30000)]),
  });
  if (!response.ok) throw new Error(`Gemini ${response.status}: ${(await response.text()).slice(0, 300)}`);
  const body = await response.json();
  const text = body.candidates?.[0]?.content?.parts?.filter(p => !p.thought).map(p => p.text || '').join('') || '';
  return JSON.parse(text);
}

// Decide the request and email the outcome. Runs after the page has already said "received".
async function review(env, submission) {
  const { reference, email, claimed, file, bytes, submittedAt } = submission;
  const log = (outcome, reason, extra = {}) =>
    console.log(JSON.stringify({ outcome, reason, reference, name: file?.name, claimed, ...extra }));

  let reason = null, result = {};
  if (!file) reason = 'attachment_count';
  else if (!Number.isFinite(claimed) || claimed <= 0) reason = 'bad_amount';
  else if (file.size > MAX_BYTES) reason = 'too_large';
  else if (!IMAGE_TYPES.has(file.type)) reason = 'not_image';
  else {
    try { result = await classify(env, file.type, bytes, AbortSignal.timeout(25000)); }
    catch (error) { reason = 'model_error'; result = { error: String(error) }; }
    if (!reason) {
      if (!result.is_receipt) reason = 'not_receipt';
      else if (typeof result.total !== 'number') reason = 'no_total';
      else if (result.currency && result.currency.toUpperCase() !== 'USD') reason = 'currency';
      else if (Math.abs(result.total - claimed) > 0.01) reason = 'amount_mismatch';
    }
  }

  // Demo mode: NOTIFY_TO receives every outcome email (no attachment), noting who submitted it.
  const to = env.NOTIFY_TO || email;
  const submitter = env.NOTIFY_TO ? email : null;
  const message = reason ? rejectionEmail(reference, submittedAt, submitter) : approvalEmail(reference, submittedAt, result.total.toFixed(2), submitter);
  log(reason ? 'rejected' : 'accepted', reason, result);
  // Cap emails per recipient so the form can't be used to flood someone's inbox.
  const perRecipient = env.RECIPIENT ? await env.RECIPIENT.limit({ key: to.toLowerCase() }) : { success: true };
  if (!perRecipient.success) return console.log(JSON.stringify({ email: 'skipped_recipient_limit', reference, to, submitter: email }));
  try {
    const sent = await env.EMAIL.send({ to, from: { email: env.MAIL_FROM, name: 'Expense Reimbursement' }, ...message });
    console.log(JSON.stringify({ email: 'sent', reference, to, submitter: email, messageId: sent?.messageId }));
  } catch (error) {
    console.log(JSON.stringify({ email: 'failed', reference, to, submitter: email, code: error?.code, error: String(error?.message || error) }));
  }
}

async function submit(request, env, ctx) {
  const limit = env.SUBMIT ? await env.SUBMIT.limit({ key: request.headers.get('CF-Connecting-IP') || 'anon' }) : { success: true };
  if (!limit.success) return json(429, { received: false, message: 'Too many submissions. Please wait a minute and try again.' });

  let form;
  try { form = await request.formData(); } catch { return json(400, { received: false, message: 'Please complete every field.' }); }

  const email = String(form.get('email') || '').trim();
  if (email.length > 254 || !EMAIL_PATTERN.test(email)) return json(400, { received: false, message: 'Please enter a valid email address.' });

  const files = form.getAll('attachment').filter(f => typeof f === 'object' && f.size > 0);
  const file = files.length === 1 ? files[0] : null;
  const bytes = file && file.size <= MAX_BYTES ? new Uint8Array(await file.arrayBuffer()) : null;
  const claimed = Number(String(form.get('amount') || '').replace(/[$,\s]/g, ''));
  const reference = 'RB-' + crypto.randomUUID().slice(0, 8).toUpperCase();
  const submittedAt = 'on ' + new Date().toLocaleString('en-US', { month: 'long', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/Los_Angeles', timeZoneName: 'short' });

  ctx.waitUntil(review(env, { reference, email, claimed, file, bytes, submittedAt }));
  return json(200, { received: true, reference, email });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === BASE + '/api/submit') {
      if (request.method !== 'POST') return json(405, { error: 'Method not allowed' });
      return submit(request, env, ctx);
    }
    if (url.pathname === BASE) return Response.redirect(url.origin + BASE + '/' + url.search, 301);
    if (url.pathname === BASE + '/') {
      return new Response(PAGE, { headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } });
    }
    return new Response('Not found', { status: 404 });
  },
};
