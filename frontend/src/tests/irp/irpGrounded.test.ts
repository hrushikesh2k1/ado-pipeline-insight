import { describe, expect, it } from 'vitest'
import type { IrpCommand, IrpScorecard } from '../../types/api'
import { casesForRequest, commandsAsText, commandsByRisk, inputsKey, scoreHeadline } from '../../utils/irpGrounded'

const command = (over: Partial<IrpCommand> = {}): IrpCommand => ({
  id: 'c1', row: 'Case 1: x', kind: 'fix', where: 'Azure Cloud Shell', language: 'cli', text: 'az x', status: 'unverified', issues: [], ...over,
})

describe('cases sent to the server', () => {
  it('are trimmed and empty names are dropped', () => {
    expect(casesForRequest([{ name: '  Tunnel dropped ', signal: ' in the log ' }, { name: '   ', signal: 'x' }, { name: 'PSK', signal: null }])).toEqual([
      { name: 'Tunnel dropped', signal: 'in the log' },
      { name: 'PSK', signal: '' },
    ])
  })
  it('are at most 8, the number the server accepts', () => {
    expect(casesForRequest(Array.from({ length: 12 }, (_, n) => ({ name: `c${n}` })))).toHaveLength(8)
  })
})

describe('inputs key', () => {
  it('is the same for the same inputs, whatever the spacing around them', () => {
    expect(inputsKey(['a', ' b ', undefined, 3])).toBe(inputsKey(['a', 'b', '', '3']))
  })
  it('changes when an input changes, so a stale analysis is noticed', () => {
    expect(inputsKey(['arm text', 'kql'])).not.toBe(inputsKey(['arm text', 'kql changed']))
  })
  it('does not run two inputs together', () => {
    expect(inputsKey(['ab', 'c'])).not.toBe(inputsKey(['a', 'bc']))
  })
})

describe('score headline', () => {
  const card = (over: Partial<IrpScorecard>): IrpScorecard => ({ status: 'warn', passed: 10, total: 14, checks: [], ...over })
  it('says when everything passed', () => {
    expect(scoreHeadline(card({ status: 'pass', passed: 14 }))).toBe('All 14 checks passed')
  })
  it('counts what needs fixing and what needs checking', () => {
    const checks = [
      { id: 'a', title: 'a', status: 'fail' as const, detail: '', items: [] },
      { id: 'b', title: 'b', status: 'warn' as const, detail: '', items: [] },
      { id: 'c', title: 'c', status: 'warn' as const, detail: '', items: [] },
    ]
    expect(scoreHeadline(card({ checks }))).toBe('10 of 14 checks passed: 1 to fix, 2 to check')
  })
})

describe('commands for QA', () => {
  it('are written as one block with a heading per row and where to run each', () => {
    const text = commandsAsText([command({ text: 'az a' }), command({ id: 'c2', text: 'az b', where: '' }), command({ id: 'c3', row: 'Case 2: y', text: 'T | take 1', where: 'Log Analytics' })])
    expect(text).toBe('# Case 1: x\n[Azure Cloud Shell] az a\naz b\n# Case 2: y\n[Log Analytics] T | take 1')
  })
  it('list the ones with a known problem first, and keep the order otherwise', () => {
    const bad = command({ id: 'bad', issues: [{ id: 'r', severity: 'fail', message: 'm', doc: 'd' }] })
    const warn = command({ id: 'warn', issues: [{ id: 'r', severity: 'warn', message: 'm', doc: 'd' }] })
    expect(commandsByRisk([command({ id: 'a' }), warn, command({ id: 'b' }), bad]).map(c => c.id)).toEqual(['bad', 'warn', 'a', 'b'])
  })
})
