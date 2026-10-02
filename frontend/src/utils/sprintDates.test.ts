import { describe, expect, it } from 'vitest'
import { formatSprintRange, formatWorkDaysRemaining, withListedDates } from './sprintDates'

describe('formatSprintRange', () => {
  it('matches the Azure DevOps format, repeating the month', () => {
    expect(formatSprintRange('2026-10-01T00:00:00Z', '2026-10-31T00:00:00Z', 'en-US')).toBe('October 1 - October 31')
    expect(formatSprintRange('2026-09-18T00:00:00Z', '2026-10-01T00:00:00Z', 'en-US')).toBe('September 18 - October 1')
  })
  it('uses the UTC calendar day, whatever the viewer timezone is', () => {
    expect(formatSprintRange('2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z', 'en-US')).toBe('October 1 - October 1')
  })
  it('returns null when a date is missing or invalid', () => {
    expect(formatSprintRange(undefined, '2026-10-31T00:00:00Z')).toBeNull()
    expect(formatSprintRange('2026-10-01T00:00:00Z', null)).toBeNull()
    expect(formatSprintRange('nope', '2026-10-31T00:00:00Z')).toBeNull()
  })
})

describe('formatWorkDaysRemaining', () => {
  it('pluralises and never invents a number', () => {
    expect(formatWorkDaysRemaining(20)).toBe('20 work days remaining')
    expect(formatWorkDaysRemaining(1)).toBe('1 work day remaining')
    expect(formatWorkDaysRemaining(0)).toBe('0 work days remaining')
    expect(formatWorkDaysRemaining(null)).toBeNull()
    expect(formatWorkDaysRemaining(undefined)).toBeNull()
  })
})

describe('withListedDates', () => {
  it('fills missing board dates from the sprint list', () => {
    const merged = withListedDates({ id: 'a', start_date: null, finish_date: null }, { id: 'a', start_date: '2026-10-01', finish_date: '2026-10-31' })
    expect(merged?.start_date).toBe('2026-10-01')
    expect(merged?.finish_date).toBe('2026-10-31')
  })
  it('keeps the board dates when it already has them', () => {
    const board = { id: 'a', start_date: '2026-10-02', finish_date: '2026-10-30' }
    expect(withListedDates(board, { start_date: '2026-10-01', finish_date: '2026-10-31' })).toBe(board)
  })
})
