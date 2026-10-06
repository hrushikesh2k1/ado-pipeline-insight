import { describe, expect, it } from 'vitest'
import type { PullRequestChecklistCheck, PullRequestReviewComment, PullRequestReviewResponse } from '../../types/api'
import {
  QUERY_NOT_RUN, SECOND_CHECK_AGREED, SECOND_CHECK_NOT_RUN, SECOND_CHECK_TIP, allCommentsAsMarkdown, checklistCounts, commentAsMarkdown, filesCounts, isAboutQueries, lineLabel,
  reviewIsStale, scoreLabel, shortCommit, verdictLabel,
} from '../../utils/prReview'

const comment = (over: Partial<PullRequestReviewComment> = {}): PullRequestReviewComment => ({
  id: 'c1', category: 'correctness', severity: 'warning', title: 'Division by zero', comment: 'average() fails on an empty list.',
  file_path: 'scripts/report.py', line_number: 17, end_line: null, suggestion_code: null, ...over,
})

const review = (over: Partial<PullRequestReviewResponse> = {}): PullRequestReviewResponse => ({
  pull_request_id: 7, verdict: 'APPROVED_WITH_SUGGESTIONS', summary: 'Reviewed 2 of 3 changed files.', scorecard: {}, comments: [comment()], posted_to_ado: false, ...over,
})

describe('labels', () => {
  it('say what the review found, not that the pull request is approved', () => {
    expect(verdictLabel('APPROVED')).toBe('No issues found')
    expect(verdictLabel('APPROVED_WITH_SUGGESTIONS')).toBe('Suggestions')
    expect(verdictLabel('CHANGES_REQUESTED')).toBe('Changes suggested')
    expect(verdictLabel('NOT_REVIEWED')).toBe('Nothing reviewed')
  })
  it('make an unknown verdict or score readable', () => {
    expect(verdictLabel('SOMETHING_NEW')).toBe('Something new')
    expect(scoreLabel('NO_FINDINGS')).toBe('No findings')
    expect(scoreLabel('NEEDS_IMPROVEMENT')).toBe('Needs improvement')
    expect(scoreLabel('VERY_ODD')).toBe('Very odd')
  })
})

describe('what the second check was', () => {
  it('is another AI reading the code, and the labels do not claim more', () => {
    expect(SECOND_CHECK_AGREED).toBe('second check agreed')
    expect(SECOND_CHECK_NOT_RUN).toBe('second check did not run')
    expect(SECOND_CHECK_TIP).toContain('has not run the code or the query')
    expect(`${SECOND_CHECK_AGREED} ${SECOND_CHECK_NOT_RUN} ${QUERY_NOT_RUN}`).not.toMatch(/double-checked|verified by qa|tested/i)
  })
  it('says a finding about a query or an alert template has not been run', () => {
    expect(isAboutQueries('ARM template')).toBe(true)
    expect(isAboutQueries('KQL')).toBe(true)
    expect(isAboutQueries('Python')).toBe(false)
    expect(isAboutQueries('PowerShell')).toBe(false)
    expect(isAboutQueries(null)).toBe(false)
    expect(isAboutQueries(undefined)).toBe(false)
  })
})

describe('line label', () => {
  it('is one line, a range, or nothing', () => {
    expect(lineLabel({ line_number: 24, end_line: null })).toBe('24')
    expect(lineLabel({ line_number: 24, end_line: 26 })).toBe('24-26')
    expect(lineLabel({ line_number: 24, end_line: 24 })).toBe('24')
    expect(lineLabel({ line_number: null, end_line: null })).toBe('')
  })
})

describe('stale review', () => {
  const at = (source_commit?: string | null) => review({ source_commit })
  it('is a review made at an older commit than the tip of the branch', () => {
    expect(reviewIsStale(at('aaa'), { last_source_commit: 'bbb' })).toBe(true)
  })
  it('is not one made at the same commit', () => {
    expect(reviewIsStale(at('aaa'), { last_source_commit: 'aaa' })).toBe(false)
  })
  it('is never called out of date when a commit is not known', () => {
    expect(reviewIsStale(at(null), { last_source_commit: 'bbb' })).toBe(false)
    expect(reviewIsStale(at('aaa'), { last_source_commit: null })).toBe(false)
    expect(reviewIsStale(at('aaa'), {})).toBe(false)
    expect(reviewIsStale(undefined, { last_source_commit: 'bbb' })).toBe(false)
  })
  it('shows a short commit', () => {
    expect(shortCommit('0123456789abcdef0123456789abcdef01234567')).toBe('01234567')
    expect(shortCommit(null)).toBe('')
  })
})

describe('comment as text for Azure DevOps', () => {
  it('is a heading and the explanation', () => {
    expect(commentAsMarkdown(comment())).toBe('**[WARNING] Division by zero**\n\naverage() fails on an empty list.')
  })
  it('ends with a suggestion block when there is a replacement', () => {
    const text = commentAsMarkdown(comment({ suggestion_code: 'def load(path) -> Any:' }))
    expect(text.endsWith('```suggestion\ndef load(path) -> Any:\n```')).toBe(true)
  })
  it('names the file and lines only when asked', () => {
    expect(commentAsMarkdown(comment({ end_line: 19 }))).not.toContain('scripts/report.py')
    expect(commentAsMarkdown(comment({ end_line: 19 }), true)).toContain('`scripts/report.py:17-19`')
  })
  it('all together: the summary, each finding with its place, and the limit of the review', () => {
    const text = allCommentsAsMarkdown({ id: 7, title: 'Add the report' }, review({ scope_note: 'It cannot judge the output.' }))
    expect(text).toContain('# AI review of PR #7: Add the report')
    expect(text).toContain('Reviewed 2 of 3 changed files.')
    expect(text).toContain('## 1. **[WARNING] Division by zero**')
    expect(text).toContain('`scripts/report.py:17`')
    expect(text.endsWith('_It cannot judge the output._')).toBe(true)
  })
  it('says so when there are no findings', () => {
    expect(allCommentsAsMarkdown({ id: 7, title: 'T' }, review({ comments: [] }))).toContain('No findings.')
  })
})

describe('counts', () => {
  it('count the checklist by status', () => {
    const check = (status: PullRequestChecklistCheck['status']): PullRequestChecklistCheck => ({ item: status, checked: true, status, evidence: '' })
    expect(checklistCounts([check('ok'), check('ok'), check('mismatch'), check('unverifiable')])).toEqual({ ok: 2, mismatch: 1, open: 0, unverifiable: 1 })
  })
  it('count the files reviewed and skipped', () => {
    const file = (status: 'reviewed' | 'skipped') => ({ path: status, language: null, change_type: 'edit', status, reason: null, findings: 0, purpose: null })
    expect(filesCounts([file('reviewed'), file('skipped'), file('skipped')])).toEqual({ reviewed: 1, skipped: 2 })
  })
})
