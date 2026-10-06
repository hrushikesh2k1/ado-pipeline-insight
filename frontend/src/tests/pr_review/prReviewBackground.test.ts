import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../services/api'
import type { PullRequestReviewJob, PullRequestReviewResponse } from '../../types/api'
import { SECOND_CHECK_AGREED, STATIC_CHECK, STATIC_CHECK_TIP, lookedAtLine, progressText } from '../../utils/prReview'

const PAYLOAD = { organization: 'myorg', project: 'myproj', repository_id: 'repo-1', pull_request_id: 101, pat: 'fake-pat' }

const review = (): PullRequestReviewResponse => ({
  pull_request_id: 101, verdict: 'APPROVED', summary: 'Reviewed 1 of 1 changed files.', scorecard: {}, comments: [], posted_to_ado: false,
})

const job = (over: Partial<PullRequestReviewJob> = {}): PullRequestReviewJob => ({
  job_id: 'abc_DEF-123456789012', status: 'running', message: 'Reviewing 3 files', done: 0, total: 3, elapsed_seconds: 0, result: null, error: null, ...over,
})

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** fetch answers from a list, one answer per call; a function in the list is called (to throw or to build the answer). */
function fetchAnswering(answers: Array<Response | (() => Response)>) {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const next = answers.shift()
    if (!next) throw new Error('fetch was called more often than the test expected')
    return typeof next === 'function' ? next() : next
  })
  vi.stubGlobal('fetch', mock)
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('how a finding made by code is labelled', () => {
  it('says plainly that no AI made it and that the code was not run', () => {
    expect(STATIC_CHECK).toBe('static check (no AI)')
    expect(STATIC_CHECK_TIP).toContain('without the AI')
    expect(STATIC_CHECK_TIP).toContain('has not run the code')
    expect(STATIC_CHECK).not.toContain(SECOND_CHECK_AGREED)
  })
})

describe('what the second check looked at', () => {
  it('is one line, or nothing', () => {
    expect(lookedAtLine(['read src/Api/Api.csproj', 'searched the code for "TrendSeconds"'])).toBe('read src/Api/Api.csproj; searched the code for "TrendSeconds"')
    expect(lookedAtLine([])).toBe('')
    expect(lookedAtLine(undefined)).toBe('')
    expect(lookedAtLine(null)).toBe('')
    expect(lookedAtLine(['', 'read a.cs'])).toBe('read a.cs')
  })
})

describe('progress text', () => {
  it('is the message, with the seconds once a review takes a while', () => {
    expect(progressText({ message: 'Reviewed 3 of 12 files', elapsed_seconds: 2 })).toBe('Reviewed 3 of 12 files')
    expect(progressText({ message: 'Reviewed 3 of 12 files', elapsed_seconds: 45 })).toBe('Reviewed 3 of 12 files (45 s)')
  })
  it('never shows an empty line', () => {
    expect(progressText({ message: '', elapsed_seconds: 0 })).toBe('Working')
  })
})

describe('reviewing a pull request in the background', () => {
  it('starts the review, follows it until it is done and returns the review', async () => {
    const calls = fetchAnswering([
      reply(202, job()),
      reply(200, job({ done: 1, message: 'Reviewed 1 of 3 files' })),
      reply(200, job({ status: 'done', done: 3, message: 'Done', result: review() })),
    ])
    const seen: string[] = []
    const result = await api.reviewPullRequest(PAYLOAD, (j) => seen.push(j.message), 0)
    expect(result).toEqual(review())
    expect(calls[0].url).toBe('/api/v1/ado/pullrequests/review/start')
    expect(calls[0].init?.method).toBe('POST')
    expect(JSON.parse(String(calls[0].init?.body))).toEqual(PAYLOAD)
    expect(calls.slice(1).map(c => c.url)).toEqual(Array(2).fill('/api/v1/ado/pullrequests/review/status/abc_DEF-123456789012'))
    expect(seen).toEqual(['Reviewing 3 files', 'Reviewed 1 of 3 files'])
  })

  it('does not poll when the review is already done', async () => {
    const calls = fetchAnswering([reply(202, job({ status: 'done', result: review() }))])
    expect(await api.reviewPullRequest(PAYLOAD, undefined, 0)).toEqual(review())
    expect(calls).toHaveLength(1)
  })

  it('says why a review failed', async () => {
    fetchAnswering([reply(202, job()), reply(200, job({ status: 'failed', error: { status_code: 422, detail: 'This pull request has no file changes to review.' } }))])
    await expect(api.reviewPullRequest(PAYLOAD, undefined, 0)).rejects.toThrow('This pull request has no file changes to review.')
  })

  it('never returns a review that is not there', async () => {
    fetchAnswering([reply(202, job({ status: 'failed' }))])
    await expect(api.reviewPullRequest(PAYLOAD, undefined, 0)).rejects.toThrow('Nothing was reviewed')
    fetchAnswering([reply(202, job({ status: 'done', result: null }))])
    await expect(api.reviewPullRequest(PAYLOAD, undefined, 0)).rejects.toThrow('Nothing was reviewed')
  })

  it('shows the reason when the review cannot be started', async () => {
    fetchAnswering([reply(503, { detail: 'Azure OpenAI is not configured, so the AI review is unavailable. Nothing was reviewed.' })])
    await expect(api.reviewPullRequest(PAYLOAD, undefined, 0)).rejects.toThrow('503: Azure OpenAI is not configured')
  })

  it('stops at once when the review is gone (the app restarted) and does not ask again', async () => {
    const calls = fetchAnswering([reply(202, job()), reply(404, { detail: 'This review is no longer available. Start it again.' })])
    await expect(api.reviewPullRequest(PAYLOAD, undefined, 0)).rejects.toThrow('404: This review is no longer available')
    expect(calls).toHaveLength(2)
  })

  it('carries on after a connection that drops for a moment', async () => {
    fetchAnswering([
      reply(202, job()),
      () => { throw new Error('Failed to fetch') },
      () => { throw new Error('Failed to fetch') },
      reply(200, job({ status: 'done', result: review() })),
    ])
    expect(await api.reviewPullRequest(PAYLOAD, undefined, 0)).toEqual(review())
  })

  it('gives up after the connection has been down for several tries in a row', async () => {
    const down = () => { throw new Error('Failed to fetch') }
    const calls = fetchAnswering([reply(202, job()), down, down, down, down, reply(200, job({ status: 'done', result: review() }))])
    await expect(api.reviewPullRequest(PAYLOAD, undefined, 0)).rejects.toThrow('Failed to fetch')
    expect(calls).toHaveLength(5)
  })

  it('counts only tries in a row: a good answer in between starts the count again', async () => {
    const down = () => { throw new Error('Failed to fetch') }
    fetchAnswering([
      reply(202, job()), down, down, down, reply(200, job({ done: 1 })), down, down, down, reply(200, job({ status: 'done', result: review() })),
    ])
    expect(await api.reviewPullRequest(PAYLOAD, undefined, 0)).toEqual(review())
  })

  it('writes the job id into the address safely', async () => {
    const calls = fetchAnswering([reply(202, job({ job_id: 'a/b c' })), reply(200, job({ job_id: 'a/b c', status: 'done', result: review() }))])
    await api.reviewPullRequest(PAYLOAD, undefined, 0)
    expect(calls[1].url).toBe('/api/v1/ado/pullrequests/review/status/a%2Fb%20c')
  })
})
