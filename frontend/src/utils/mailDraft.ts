export type MailDraft = { to: string[]; subject: string; body: string };
export function mailDraftUrl(draft: MailDraft, includeBody = true) {
  return (
    `mailto:${draft.to.map(encodeURIComponent).join(";")}?subject=${encodeURIComponent(draft.subject)}` +
    (includeBody ? `&body=${encodeURIComponent(draft.body)}` : "")
  );
}
/** A draft is opened locally; this never sends mail. Large reports are copied in full for paste. */
export async function openMailDraft(draft: MailDraft): Promise<string> {
  const full = mailDraftUrl(draft);
  if (full.length <= 1800) {
    window.location.href = full;
    return "Draft requested in your default mail app. Review the content and click Send in Outlook.";
  }
  await navigator.clipboard.writeText(draft.body);
  window.location.href = mailDraftUrl(draft, false);
  return "Full email body copied. Paste it into the Outlook draft, then review and click Send.";
}
