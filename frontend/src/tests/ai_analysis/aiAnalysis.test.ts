import { describe, expect, it } from 'vitest'
import { extractYamlFromRemediation, SYSTEM_PROMPT_TEXT } from '../../App'

describe('AI Analysis Test Suite', () => {
  it('extracts explicit yaml blocks from AI remediation markdown', () => {
    const raw = "Add caching to your task:\n\n```yaml\n- task: Cache@2\n  inputs:\n    key: 'test'\n```\n\nEnsure path exists."
    const { text, yaml } = extractYamlFromRemediation(raw, 'caching_opportunity', 'Build')
    expect(yaml).toBe("- task: Cache@2\n  inputs:\n    key: 'test'")
    expect(text).toContain('Add caching to your task:')
  })

  it('generates contextual Cache@2 YAML when no yaml block is provided in recommendation', () => {
    const { yaml } = extractYamlFromRemediation('Configure build caching.', 'caching_opportunity', 'Deploy cops Records Dev', 'npm install')
    expect(yaml).toContain('task: Cache@2')
    expect(yaml).toContain('Pipeline.Workspace')
  })

  it('generates retry and timeout YAML for flaky steps', () => {
    const { yaml } = extractYamlFromRemediation('Task failed intermittently.', 'flaky_step', 'Deploy cops Analytics Dev', 'Helm Upgrade')
    expect(yaml).toContain('retryCountOnTaskFailure: 2')
    expect(yaml).toContain('Helm Upgrade')
  })

  it('validates SYSTEM_PROMPT_TEXT contains architect guidelines and thresholds', () => {
    expect(SYSTEM_PROMPT_TEXT).toContain('Principal DevOps Architect')
    expect(SYSTEM_PROMPT_TEXT).toContain('Remediation')
    expect(SYSTEM_PROMPT_TEXT).toContain('yaml')
    expect(SYSTEM_PROMPT_TEXT).toContain('high: Failure rate >= 15%')
  })
})
