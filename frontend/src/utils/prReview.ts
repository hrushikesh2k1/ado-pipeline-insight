import type { AdoPullRequest, PullRequestChecklistCheck, PullRequestKnowledgeCheck, PullRequestReviewComment, PullRequestReviewJob, PullRequestReviewModelInfo, PullRequestReviewModels, PullRequestReviewResponse, PullRequestReviewedFile, ReviewModelChoice } from '../types/api'

/** The tool reads code changes; it does not approve a pull request. The wording says what it found, not what to decide. */
const VERDICT_LABEL: Record<string, string> = {
  APPROVED: 'No issues found',
  APPROVED_WITH_SUGGESTIONS: 'Suggestions',
  CHANGES_REQUESTED: 'Changes suggested',
  NOT_REVIEWED: 'Nothing reviewed',
}

export function verdictLabel(verdict: string): string {
  return VERDICT_LABEL[verdict] ?? titleCase(verdict)
}

const SCORE_LABEL: Record<string, string> = {
  NO_FINDINGS: 'No findings',
  EXCELLENT: 'Excellent',
  GOOD: 'Minor suggestions',
  NEEDS_IMPROVEMENT: 'Needs improvement',
  CONCERNING: 'Concerning',
}

export function scoreLabel(score: string): string {
  return SCORE_LABEL[score] ?? titleCase(score)
}

function titleCase(text: string): string {
  const words = text.replace(/_/g, ' ').toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export const CHECK_LABEL: Record<PullRequestChecklistCheck['status'], string> = {
  ok: 'Matches the pull request',
  mismatch: 'Does not match',
  open: 'Not done yet',
  unverifiable: "Can't be verified here",
}

/** What the second check was: another AI reading the code. It did not run the code or the query, and the labels say so. */
export const SECOND_CHECK_AGREED = 'second check agreed'
export const SECOND_CHECK_NOT_RUN = 'second check did not run'
export const SECOND_CHECK_TIP = 'A second AI read of the code agreed with this finding. It has not run the code or the query.'
export const QUERY_NOT_RUN = 'not verified by running the query'

/** Findings in alert templates and KQL are about queries nobody has run: say so next to them. */
export function isAboutQueries(language?: string | null): boolean {
  return language === 'ARM template' || language === 'KQL'
}

/** A finding the code itself made, with no AI in it: said plainly, because it needs no second check. */
export const STATIC_CHECK = 'static check (no AI)'
export const STATIC_CHECK_TIP = 'Found by an exact check made in code, without the AI, from the text of the file. It has not run the code.'

/** What the second check looked at in the repository, as one line; empty when it looked at nothing. */
export function lookedAtLine(items?: string[] | null): string {
  return (items ?? []).filter(Boolean).join('; ')
}

/** Progress of a review that runs in the background: "Reviewed 3 of 12 files (45 s)". */
export function progressText(job: Pick<PullRequestReviewJob, 'message' | 'elapsed_seconds'>): string {
  const seconds = job.elapsed_seconds >= 5 ? ` (${job.elapsed_seconds} s)` : ''
  return `${job.message || 'Working'}${seconds}`
}

// ---------------------------------------------------------------- the user's own checks (the knowledge base)

export const KNOWLEDGE_STORAGE_KEY = 'ado_pr_knowledge_base'
export const KNOWLEDGE_OPEN_KEY = 'ado_pr_knowledge_open'
export const KNOWLEDGE_MAX_CHARS = 6000
export const KNOWLEDGE_MAX_CHECKS = 40
export const KNOWLEDGE_EXAMPLE = [
  '[PowerShell] Never use `Invoke-Expression` on anything a user can influence',
  '[PowerShell] Scripts that change state need `-WhatIf` support',
  '[Python] Every `requests` call has a timeout',
  '[alerts] Every alert has an action group',
  '[SQL] Dates are compared in UTC, not local time',
  '[PR] The description links the regression run',
].join('\n')
export const KNOWLEDGE_HELP = 'Write one check per line. Start a line with [PowerShell], [Python], [C#], [SQL], [alerts], [Markdown] or [PR] to limit it; a line with no scope is used for every file. '
  + 'Put terms in `backticks` and the review shows where they appear in the changed lines. Lines starting with # are notes.'

/** Mirrors what the backend reads: spacing alone is not a change, and blank lines do not count. */
export function normalizeKnowledge(text: string | null | undefined): string {
  return (text ?? '').slice(0, KNOWLEDGE_MAX_CHARS).replace(/\r\n?/g, '\n').split('\n').map(l => l.split(/\s+/).filter(Boolean).join(' ')).filter(Boolean).join('\n')
}

/** The checks in the text: a line that is empty, a note (#), a lone bullet or a lone [scope] is not one. */
export function knowledgeCount(text: string | null | undefined): number {
  const lines = (text ?? '').slice(0, KNOWLEDGE_MAX_CHARS).replace(/\r\n?/g, '\n').split('\n').map(l => l.trim())
  const checks = lines.filter(l => l && !l.startsWith('#')).map(l => l.replace(/^(?:[-*•]|\d{1,2}[.)])(?:\s+|$)/, '').replace(/^\[[^\]\n]{1,60}\]\s*$/, '').trim()).filter(Boolean)
  return Math.min(checks.length, KNOWLEDGE_MAX_CHECKS)
}

/** True when the checks used for a review are not the ones written now. A review made without any is compared with the empty text. */
export function knowledgeChanged(used: string | null | undefined, current: string | null | undefined): boolean {
  return normalizeKnowledge(used) !== normalizeKnowledge(current)
}

export function loadKnowledge(): string {
  try { return localStorage.getItem(KNOWLEDGE_STORAGE_KEY) ?? '' } catch { return '' }
}

export function saveKnowledge(text: string): void {
  try {
    if (text.trim()) localStorage.setItem(KNOWLEDGE_STORAGE_KEY, text)
    else localStorage.removeItem(KNOWLEDGE_STORAGE_KEY)
  } catch { /* storage blocked: the text stays on the page for this visit */ }
}

// ---------------------------------------------------------------- which model reviews

export const MODEL_STORAGE_KEY = 'ado_pr_review_model'
export const MODEL_LABEL: Record<ReviewModelChoice, string> = { standard: 'Standard', strong: 'Strong' }
export const MODEL_TIP: Record<ReviewModelChoice, string> = {
  standard: 'The usual model: quicker and cheaper.',
  strong: 'A stronger model: slower and it costs more. If it cannot answer, the standard model finishes the review.',
}
export const MODEL_HELP = 'Choose the model for the next review. A review made with the other model is offered again.'

/** The model a review will use: the one the user chose, when the server has it, otherwise the server's own default. */
export function chosenModel(models: PullRequestReviewModels | null | undefined, saved: ReviewModelChoice | null | undefined): ReviewModelChoice {
  if (!models) return 'standard'
  if (saved && models[saved]) return saved
  return models[models.default] ? models.default : models.strong ? 'strong' : 'standard'
}

/** True when a review was made with another model than the one chosen now. A review the page did not record is not compared. */
export function modelChanged(used: ReviewModelChoice | null | undefined, current: ReviewModelChoice): boolean {
  return Boolean(used) && used !== current
}

export function loadModelChoice(): ReviewModelChoice | null {
  try {
    const saved = localStorage.getItem(MODEL_STORAGE_KEY)
    return saved === 'standard' || saved === 'strong' ? saved : null
  } catch { return null }
}

export function saveModelChoice(choice: ReviewModelChoice): void {
  try { localStorage.setItem(MODEL_STORAGE_KEY, choice) } catch { /* storage blocked: the choice holds for this visit */ }
}

/** "model: gpt-6-sol", or, when the strong one could not answer, "model: gpt-4.1-mini (gpt-6-sol could not answer)". Empty when the server did not say. */
export function modelLine(info?: PullRequestReviewModelInfo | null): string {
  if (!info?.deployment) return ''
  return info.fallback_deployment ? `model: ${info.fallback_deployment} (${info.deployment} could not answer)` : `model: ${info.deployment}`
}

export const KNOWLEDGE_STATUS_LABEL: Record<PullRequestKnowledgeCheck['status'], string> = {
  raised: 'Problem reported',
  nothing_reported: 'No problem reported',
  not_applicable: 'Not applicable here',
  could_not_check: 'Could not check',
}
export const KNOWLEDGE_STATUS_TIP: Record<PullRequestKnowledgeCheck['status'], string> = {
  raised: 'A finding in this review comes from this check.',
  nothing_reported: 'An AI read the changed code with this check in mind and reported no problem. Nothing was run.',
  not_applicable: 'No file in this pull request is of the kind this check names.',
  could_not_check: 'The AI call for this check failed.',
}

export function knowledgeCounts(checks: PullRequestKnowledgeCheck[]): Record<PullRequestKnowledgeCheck['status'], number> {
  const counts = { raised: 0, nothing_reported: 0, not_applicable: 0, could_not_check: 0 }
  for (const check of checks) counts[check.status] += 1
  return counts
}

/** '24' or '24-26'; empty when the comment has no line. */
export function lineLabel(comment: Pick<PullRequestReviewComment, 'line_number' | 'end_line'>): string {
  if (!comment.line_number) return ''
  return comment.end_line && comment.end_line > comment.line_number ? `${comment.line_number}-${comment.end_line}` : `${comment.line_number}`
}

export function shortCommit(commit?: string | null): string {
  return commit ? commit.slice(0, 8) : ''
}

/** A review made at an older commit than the one at the tip of the branch is out of date. Unknown commits are never called out of date. */
export function reviewIsStale(review: PullRequestReviewResponse | undefined, pr: Pick<AdoPullRequest, 'last_source_commit'>): boolean {
  return Boolean(review?.source_commit && pr.last_source_commit && review.source_commit !== pr.last_source_commit)
}

/** The comment as text to paste into an Azure DevOps comment. A suggestion block replaces the lines the comment is placed on. */
export function commentAsMarkdown(comment: PullRequestReviewComment, withLocation = false): string {
  const heading = `**[${comment.severity.toUpperCase()}] ${comment.title}**`
  const where = withLocation && comment.file_path ? `\n\`${comment.file_path}${lineLabel(comment) ? `:${lineLabel(comment)}` : ''}\`` : ''
  const suggestion = comment.suggestion_code ? `\n\n\`\`\`suggestion\n${comment.suggestion_code}\n\`\`\`` : ''
  return `${heading}${where}\n\n${comment.comment}${suggestion}`
}

export function allCommentsAsMarkdown(pr: Pick<AdoPullRequest, 'id' | 'title'>, review: PullRequestReviewResponse): string {
  const head = `# AI review of PR #${pr.id}: ${pr.title}\n\n${review.summary}\n\n`
  const body = review.comments.map((c, i) => `## ${i + 1}. ${commentAsMarkdown(c, true)}`).join('\n\n')
  return head + (body || 'No findings.') + (review.scope_note ? `\n\n_${review.scope_note}_` : '')
}

export function checklistCounts(checks: PullRequestChecklistCheck[]): Record<PullRequestChecklistCheck['status'], number> {
  const counts = { ok: 0, mismatch: 0, open: 0, unverifiable: 0 }
  for (const check of checks) counts[check.status] += 1
  return counts
}

export function filesCounts(files: PullRequestReviewedFile[]): { reviewed: number; skipped: number } {
  const reviewed = files.filter(f => f.status === 'reviewed').length
  return { reviewed, skipped: files.length - reviewed }
}
