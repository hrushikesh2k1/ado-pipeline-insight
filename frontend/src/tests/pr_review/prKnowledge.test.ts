import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../services/api'
import type { PullRequestKnowledgeCheck } from '../../types/api'
import {
  KNOWLEDGE_EXAMPLE, KNOWLEDGE_HELP, KNOWLEDGE_MAX_CHARS, KNOWLEDGE_STATUS_LABEL, KNOWLEDGE_STATUS_TIP, KNOWLEDGE_STORAGE_KEY,
  knowledgeChanged, knowledgeCount, knowledgeCounts, loadKnowledge, normalizeKnowledge, saveKnowledge,
} from '../../utils/prReview'

function fakeStorage(initial: Record<string, string> = {}, broken = false) {
  const data = { ...initial }
  const guard = () => { if (broken) throw new Error('storage is blocked') }
  return {
    data,
    getItem: (key: string) => { guard(); return key in data ? data[key] : null },
    setItem: (key: string, value: string) => { guard(); data[key] = value },
    removeItem: (key: string) => { guard(); delete data[key] },
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('how many checks the text holds', () => {
  it('counts one per line and skips blank lines, notes, lone bullets and lone scopes', () => {
    const text = '# my checks\n\n- [PowerShell] Avoid `Write-Host`\n2. [Python] Docstrings\nplain check\n-\n[SQL]\n   \n'
    expect(knowledgeCount(text)).toBe(3)
  })
  it('counts nothing for nothing', () => {
    for (const text of ['', '   ', '# only a note', null, undefined]) expect(knowledgeCount(text)).toBe(0)
  })
  it('uses at most 40, as the backend does', () => {
    expect(knowledgeCount(Array.from({ length: 100 }, (_, n) => `check ${n}`).join('\n'))).toBe(40)
  })
  it('counts the example it offers', () => {
    expect(knowledgeCount(KNOWLEDGE_EXAMPLE)).toBe(6)
  })
})

describe('what counts as a change of the knowledge base', () => {
  it('is not a change of spacing, blank lines or line endings', () => {
    expect(normalizeKnowledge('  one   check \r\n\r\n\n[PowerShell]  two ')).toBe('one check\n[PowerShell] two')
    expect(knowledgeChanged('one check\n[PowerShell] two', '  one   check \n\n[PowerShell]  two ')).toBe(false)
  })
  it('is a change of the words', () => {
    expect(knowledgeChanged('one check', 'one other check')).toBe(true)
    expect(knowledgeChanged('one check', '')).toBe(true)
    expect(knowledgeChanged('', 'one check')).toBe(true)
  })
  it('is the same when there was none and there is none', () => {
    expect(knowledgeChanged(undefined, '')).toBe(false)
    expect(knowledgeChanged(null, '   \n ')).toBe(false)
  })
  it('only reads the first 6,000 characters, like the backend', () => {
    const long = 'a'.repeat(KNOWLEDGE_MAX_CHARS)
    expect(knowledgeChanged(long, long + ' more words beyond the limit')).toBe(false)
  })
})

describe('keeping the text in this browser', () => {
  it('saves and loads it', () => {
    const storage = fakeStorage()
    vi.stubGlobal('localStorage', storage)
    saveKnowledge('[PowerShell] Avoid `Write-Host`')
    expect(storage.data[KNOWLEDGE_STORAGE_KEY]).toBe('[PowerShell] Avoid `Write-Host`')
    expect(loadKnowledge()).toBe('[PowerShell] Avoid `Write-Host`')
  })
  it('forgets it when it is cleared', () => {
    const storage = fakeStorage({ [KNOWLEDGE_STORAGE_KEY]: 'something' })
    vi.stubGlobal('localStorage', storage)
    saveKnowledge('   ')
    expect(KNOWLEDGE_STORAGE_KEY in storage.data).toBe(false)
    expect(loadKnowledge()).toBe('')
  })
  it('keeps working when the browser blocks storage', () => {
    vi.stubGlobal('localStorage', fakeStorage({}, true))
    expect(() => saveKnowledge('a check')).not.toThrow()
    expect(loadKnowledge()).toBe('')
  })
  it('keeps working when there is no storage at all', () => {
    vi.stubGlobal('localStorage', undefined)
    expect(() => saveKnowledge('a check')).not.toThrow()
    expect(loadKnowledge()).toBe('')
  })
})

describe('what the user is told', () => {
  it('explains the format, including scopes, backticks and notes', () => {
    for (const part of ['one check per line', '[PowerShell]', '[PR]', '`backticks`', 'a line with no scope is used for every file', 'Lines starting with # are notes']) {
      expect(KNOWLEDGE_HELP).toContain(part)
    }
  })
  it('says honestly what "no problem reported" means', () => {
    expect(KNOWLEDGE_STATUS_LABEL.nothing_reported).toBe('No problem reported')
    expect(KNOWLEDGE_STATUS_TIP.nothing_reported).toContain('Nothing was run')
    expect(`${Object.values(KNOWLEDGE_STATUS_LABEL).join(' ')}`).not.toMatch(/passed|verified|ok\b/i)
  })
  it('counts the checks by what became of them', () => {
    const check = (status: PullRequestKnowledgeCheck['status'], number: number): PullRequestKnowledgeCheck => ({ number, text: 'x', scope: 'all files', status, files: 1, findings: 0, hits: [] })
    expect(knowledgeCounts([check('raised', 1), check('nothing_reported', 2), check('nothing_reported', 3), check('not_applicable', 4), check('could_not_check', 5)]))
      .toEqual({ raised: 1, nothing_reported: 2, not_applicable: 1, could_not_check: 1 })
  })
})

describe('sending the knowledge base with a review', () => {
  it('puts it in the request that starts the review', async () => {
    const bodies: unknown[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      bodies.push(JSON.parse(String(init?.body)))
      return new Response(JSON.stringify({ job_id: 'abcdefgh12345678', status: 'done', message: 'Done', done: 1, total: 1, elapsed_seconds: 0, result: { pull_request_id: 1, verdict: 'APPROVED', summary: 's', scorecard: {}, comments: [], posted_to_ado: false } }), { status: 202 })
    }))
    await api.reviewPullRequest({ organization: 'o', project: 'p', repository_id: 'r', pull_request_id: 1, knowledge: '[PowerShell] Avoid `Write-Host`' }, undefined, 0)
    expect(bodies[0]).toMatchObject({ knowledge: '[PowerShell] Avoid `Write-Host`', pull_request_id: 1 })
  })
})
