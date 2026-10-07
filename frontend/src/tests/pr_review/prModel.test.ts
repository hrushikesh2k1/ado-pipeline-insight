import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../services/api'
import type { PullRequestReviewModels } from '../../types/api'
import { MODEL_LABEL, MODEL_NOT_SET_UP, MODEL_SELECT_TIP, MODEL_TIP, chosenModel, modelChanged, modelLine } from '../../utils/prReview'

const both: PullRequestReviewModels = { standard: 'standard-mini', strong: 'strong-sol', default: 'strong' }
const standardOnly: PullRequestReviewModels = { standard: 'standard-mini', strong: null, default: 'standard' }

afterEach(() => vi.unstubAllGlobals())

describe('which model the next review of a pull request uses', () => {
  it('is the default of the server when none was chosen for the pull request', () => {
    expect(chosenModel(both, null)).toBe('strong')
    expect(chosenModel({ ...both, default: 'standard' }, null)).toBe('standard')
  })
  it('is the choice made for the pull request when the server has that model', () => {
    expect(chosenModel(both, 'standard')).toBe('standard')
    expect(chosenModel(both, 'strong')).toBe('strong')
  })
  it('is the standard one when the server has no strong one, whatever was saved', () => {
    expect(chosenModel(standardOnly, 'strong')).toBe('standard')
    expect(chosenModel(standardOnly, null)).toBe('standard')
  })
  it('is the strong one when it is all the server has', () => {
    expect(chosenModel({ standard: null, strong: 'strong-sol', default: 'strong' }, 'standard')).toBe('strong')
  })
  it('is the standard one before the server has answered, or when it could not', () => {
    expect(chosenModel(null, 'strong')).toBe('standard')
    expect(chosenModel(undefined, null)).toBe('standard')
  })
})

describe('what counts as a change of the model', () => {
  it('is a review made with the other model', () => {
    expect(modelChanged('standard', 'strong')).toBe(true)
    expect(modelChanged('strong', 'standard')).toBe(true)
  })
  it('is not the same model, nor a review the page did not record', () => {
    expect(modelChanged('strong', 'strong')).toBe(false)
    expect(modelChanged(undefined, 'strong')).toBe(false)
    expect(modelChanged(null, 'standard')).toBe(false)
  })
})

describe('what the review says about its model', () => {
  it('names the deployment', () => {
    expect(modelLine({ deployment: 'strong-sol' })).toBe('model: strong-sol')
  })
  it('says when the standard one finished the review', () => {
    expect(modelLine({ deployment: 'strong-sol', fallback_deployment: 'standard-mini', fallback_reason: 'it is busy (rate limit)' })).toBe('model: standard-mini (strong-sol could not answer)')
  })
  it('says nothing when the server did not say', () => {
    for (const info of [null, undefined, { deployment: '' }]) expect(modelLine(info)).toBe('')
  })
})

describe('the words on the switch', () => {
  it('describe both models and make no claim about quality', () => {
    expect(MODEL_LABEL).toEqual({ standard: 'Standard', strong: 'Strong' })
    expect(MODEL_TIP.strong).toContain('standard model finishes the review')
    expect(MODEL_SELECT_TIP).toContain('this pull request')
    expect(MODEL_NOT_SET_UP).toContain('AZURE_OPENAI_REVIEW_DEPLOYMENT')
    expect(MODEL_SELECT_TIP).toContain('the other model is offered again')
  })
})

describe('asking the server', () => {
  const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  it('asks which models there are', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => { calls.push(url); return reply(200, both) }))
    expect(await api.reviewModels()).toEqual(both)
    expect(calls[0]).toContain('/api/v1/ado/pullrequests/review/models')
  })

  it('sends the chosen model with the review, and nothing when none is chosen', async () => {
    const bodies: Array<Record<string, unknown>> = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      bodies.push(JSON.parse(String(init?.body)))
      return reply(202, { job_id: 'abc_DEF-123456789012', status: 'done', message: '', done: 1, total: 1, elapsed_seconds: 0, result: { pull_request_id: 1, verdict: 'APPROVED', summary: '', scorecard: {}, comments: [], posted_to_ado: false } })
    }))
    const payload = { organization: 'o', project: 'p', repository_id: 'r', pull_request_id: 1 }
    await api.reviewPullRequest({ ...payload, model: 'strong' }, undefined, 0)
    await api.reviewPullRequest(payload, undefined, 0)
    expect(bodies[0].model).toBe('strong')
    expect('model' in bodies[1]).toBe(false)
  })
})
