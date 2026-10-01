import { describe, expect, it } from 'vitest'
import { extractProductFromStage } from '../../App'

describe('Recent Runs Test Suite', () => {
  it('extracts Records product from stage name', () => {
    expect(extractProductFromStage('Deploy cops Records Dev')).toBe('Records')
  })

  it('extracts Analytics product from stage name', () => {
    expect(extractProductFromStage('Deploy cops Analytics Dev')).toBe('Analytics')
  })

  it('extracts MFR product from stage name', () => {
    expect(extractProductFromStage('Deploy cops mfr Dev')).toBe('MFR')
  })

  it('extracts OIE product from stage name', () => {
    expect(extractProductFromStage('Deploy cops oie Dev')).toBe('OIE')
  })

  it('extracts Dispatch product from stage name', () => {
    expect(extractProductFromStage('Deploy cops dispatch Dev')).toBe('Dispatch')
  })

  it('extracts OIE product from branch refs/heads/copsoie', () => {
    expect(extractProductFromStage(null, null, 'refs/heads/copsoie')).toBe('OIE')
  })

  it('extracts Records product from branch refs/heads/copsrecords', () => {
    expect(extractProductFromStage(null, null, 'refs/heads/copsrecords')).toBe('Records')
  })

  it('extracts Analytics product from branch refs/heads/copsanalytics', () => {
    expect(extractProductFromStage(null, null, 'refs/heads/copsanalytics')).toBe('Analytics')
  })

  it('extracts MFR product from branch refs/heads/copsmfr', () => {
    expect(extractProductFromStage(null, null, 'refs/heads/copsmfr')).toBe('MFR')
  })

  it('extracts Dispatch product from branch refs/heads/copsdispatch', () => {
    expect(extractProductFromStage(null, null, 'refs/heads/copsdispatch')).toBe('Dispatch')
  })

  it('falls back to General if no known product pattern matches', () => {
    expect(extractProductFromStage('Generic Build Step')).toBe('General')
  })
})
