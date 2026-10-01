import { describe, expect, it } from 'vitest'
import { formatSeconds } from '../../utils'

describe('Build Duration Test Suite', () => {
  it('formats raw seconds to human readable strings', () => {
    expect(formatSeconds(42)).toBe('42s')
  })

  it('formats minutes and seconds accurately', () => {
    expect(formatSeconds(125)).toBe('2m 5s')
    expect(formatSeconds(3600)).toBe('60m 0s')
  })

  it('handles missing or zero duration values gracefully', () => {
    expect(formatSeconds(null)).toBe('0s')
    expect(formatSeconds(undefined)).toBe('0s')
    expect(formatSeconds(0)).toBe('0s')
  })
})
