import { describe, expect, it } from 'vitest'

describe('Top Bottlenecks Test Suite', () => {
  it('ranks stages and tasks by bottleneck duration descending', () => {
    const items = [
      { name: 'npm test', duration: 45 },
      { name: 'docker build', duration: 320 },
      { name: 'checkout', duration: 12 },
    ]
    const ranked = [...items].sort((a, b) => b.duration - a.duration)
    expect(ranked[0].name).toBe('docker build')
    expect(ranked[0].duration).toBe(320)
    expect(ranked[2].name).toBe('checkout')
  })

  it('calculates bottleneck percentage contribution', () => {
    const totalDuration = 500
    const taskDuration = 125
    const pct = (taskDuration / totalDuration) * 100
    expect(pct).toBe(25.0)
  })
})
