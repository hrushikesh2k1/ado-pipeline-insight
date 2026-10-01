import { describe, expect, it } from 'vitest'
import { ThemeToggle } from '../../App'

describe('ThemeToggle Component', () => {
  it('exports ThemeToggle as a defined component function', () => {
    expect(ThemeToggle).toBeDefined()
    expect(typeof ThemeToggle).toBe('function')
  })
})
