import { describe, expect, it } from 'vitest'
import { IRP_SEVERITIES } from '../../components/IncidentResponsePage'

describe('IRP Studio severity list', () => {
  it('is the five Azure Monitor severities, Sev0 to Sev4, in that order', () => {
    expect([...IRP_SEVERITIES]).toEqual(['Sev0 (Critical)', 'Sev1 (Error)', 'Sev2 (Warning)', 'Sev3 (Informational)', 'Sev4 (Verbose)'])
  })

  it('starts with Critical, which is the page default', () => {
    expect(IRP_SEVERITIES[0]).toBe('Sev0 (Critical)')
  })

  it('has a plain name in brackets for every level, which is what the IRP writes', () => {
    for (const level of IRP_SEVERITIES) expect(level).toMatch(/^Sev[0-4] \([A-Za-z]+\)$/)
  })
})
