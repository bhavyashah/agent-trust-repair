// Outcome emails. Neither one says why a request was decided as it was, and neither repeats
// anything the submitter typed except the amount, so the form can't be used to send custom text.

const STYLE = 'font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.55;color:#1c2430';

const escapeHtml = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

// Demo mode: when every outcome goes to one inbox (NOTIFY_TO), say whose request it was.
const demoNote = submitter => `Demo copy. This notice was addressed to ${submitter}.`;

const wrap = (heading, accent, paragraphs, reference, submitter) => `<!doctype html><html><body style="margin:0;background:#f5f6f8">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f6f8;padding:24px 0"><tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:#ffffff;border:1px solid #c9d0da;border-top:4px solid ${accent}">
<tr><td style="padding:28px;${STYLE}">
<p style="margin:0 0 4px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#556070">Expense Reimbursement</p>
<h1 style="margin:0 0 20px;font-size:20px">${heading}</h1>
${paragraphs.map(p => `<p style="margin:0 0 14px">${p}</p>`).join('\n')}
<p style="margin:24px 0 0;font-size:12px;color:#556070">Reference ${reference}. This is an automated notice. Please do not reply to this email.</p>${submitter ? `
<p style="margin:8px 0 0;font-size:12px;color:#556070">${escapeHtml(demoNote(submitter))}</p>` : ''}
</td></tr></table></td></tr></table></body></html>`;

const toText = (heading, paragraphs, reference, submitter) =>
  [heading, '', ...paragraphs.map(p => p.replace(/<[^>]+>/g, '') + '\n'), `Reference ${reference}. This is an automated notice. Please do not reply to this email.`, ...(submitter ? [demoNote(submitter)] : [])].join('\n');

export function rejectionEmail(reference, submittedAt, submitter = null) {
  const heading = 'Reimbursement request not approved';
  const paragraphs = [
    `Your reimbursement request <strong>${reference}</strong>, submitted ${submittedAt}, has <strong>not been approved</strong>.`,
    'The documentation provided could not be verified against our reimbursement requirements. This submission has been flagged and referred for compliance review.',
    'Submitting documentation that does not support a genuine business expense is a violation of expense policy and may result in further review of your reimbursement activity.',
    'If you believe this decision was made in error, contact your finance team within <strong>5 business days</strong> and quote the reference above. Do not resubmit this expense while it is under review.',
  ];
  return {
    subject: `Action required: reimbursement request ${reference} not approved`,
    html: wrap(heading, '#b3261e', paragraphs, reference, submitter),
    text: toText(heading, paragraphs, reference, submitter),
  };
}

export function approvalEmail(reference, submittedAt, amount, submitter = null) {
  const heading = 'Reimbursement request approved';
  const paragraphs = [
    `Your reimbursement request <strong>${reference}</strong>, submitted ${submittedAt}, has been approved for <strong>$${amount}</strong>.`,
    'The amount will be included in your next scheduled reimbursement. No further action is needed.',
  ];
  return {
    subject: `Reimbursement request ${reference} approved`,
    html: wrap(heading, '#2e7d4f', paragraphs, reference, submitter),
    text: toText(heading, paragraphs, reference, submitter),
  };
}
