import type { AdoPullRequest, PullRequestChecklistCheck, PullRequestReviewComment, PullRequestReviewResponse, PullRequestReviewedFile } from '../types/api'

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
