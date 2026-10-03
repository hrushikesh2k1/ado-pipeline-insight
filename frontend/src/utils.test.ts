import {describe,expect,it} from 'vitest'
import {formatSeconds} from './utils'
import {extractProductFromStage, extractYamlFromRemediation, SYSTEM_PROMPT_TEXT} from './App'

describe('formatSeconds',()=>{
  it('formats seconds',()=>expect(formatSeconds(42)).toBe('42s'))
  it('formats minutes',()=>expect(formatSeconds(125)).toBe('2m 5s'))
  it('handles missing values',()=>expect(formatSeconds(null)).toBe('0s'))
})

describe('extractProductFromStage', () => {
  it('extracts Records from Deploy cops Records Dev', () => {
    expect(extractProductFromStage('Deploy cops Records Dev')).toBe('Records')
  })

  it('extracts Analytics from Deploy cops Analytics Dev', () => {
    expect(extractProductFromStage('Deploy cops Analytics Dev')).toBe('Analytics')
  })

  it('extracts MFR from Deploy cops mfr Dev', () => {
    expect(extractProductFromStage('Deploy cops mfr Dev')).toBe('MFR')
  })

  it('extracts OIE from Deploy cops oie Dev', () => {
    expect(extractProductFromStage('Deploy cops oie Dev')).toBe('OIE')
  })

  it('extracts Dispatch from Deploy cops dispatch Dev', () => {
    expect(extractProductFromStage('Deploy cops dispatch Dev')).toBe('Dispatch')
  })

  it('handles lowercase or uppercase variations', () => {
    expect(extractProductFromStage('Deploy cops records Dev')).toBe('Records')
    expect(extractProductFromStage('Deploy cops DISPATCH Dev')).toBe('Dispatch')
  })

  it('extracts OIE from branch refs/heads/copsoie', () => {
    expect(extractProductFromStage(null, null, 'refs/heads/copsoie')).toBe('OIE')
  })

  it('extracts OIE from Deploy copsoie OIE Dev', () => {
    expect(extractProductFromStage('Deploy copsoie OIE Dev')).toBe('OIE')
  })

  it('extracts Records from branch refs/heads/copsrecords', () => {
    expect(extractProductFromStage(null, null, 'refs/heads/copsrecords')).toBe('Records')
  })

  it('falls back to General if no product detected', () => {
    expect(extractProductFromStage('Generic Build Step')).toBe('General')
  })
})


describe('product badge of a finding', () => {
  it('comes from the stage, not from other stages that a merged finding mentions in its text', () => {
    expect(extractProductFromStage('cops - Analytics - DEV - Monitoring', 'Remove access', null)).toBe('Analytics')
    expect(extractProductFromStage('cldops - Stamp - Monitoring', 'Install MDC chart', null)).toBe('General')
    // the old behaviour: the text of a merged finding lists "cops - Records - DEV - Monitoring" and won
    expect(extractProductFromStage('cops - Analytics - DEV - Monitoring', null, 'also fails in cops - Records - DEV - Monitoring')).toBe('Records')
  })
})

describe('extractYamlFromRemediation', () => {
  it('extracts explicit yaml blocks from remediation text', () => {
    const raw = "Add caching to your task:\n\n```yaml\n- task: Cache@2\n  inputs:\n    key: 'test'\n```\n\nEnsure path exists."
    const { text, yaml } = extractYamlFromRemediation(raw, 'caching_opportunity', 'Build')
    expect(yaml).toBe("- task: Cache@2\n  inputs:\n    key: 'test'")
    expect(text).toContain('Add caching to your task:')
  })

  it('extracts a diff block against the customer pipeline file', () => {
    const raw = 'Retry the step:\n\n```diff\n--- a/azure-pipelines.yml\n+++ b/azure-pipelines.yml\n+  retryCountOnTaskFailure: 2\n```'
    expect(extractYamlFromRemediation(raw).yaml).toContain('+  retryCountOnTaskFailure: 2')
  })

  it('never invents a snippet when the recommendation has no code block', () => {
    expect(extractYamlFromRemediation('Configure build caching.', 'caching_opportunity', 'Deploy cops Records Dev', 'npm install').yaml).toBe('')
    expect(extractYamlFromRemediation('Task failed intermittently.', 'flaky_step', 'Deploy cops Analytics Dev', 'Helm Upgrade').yaml).toBe('')
  })
})

describe('SYSTEM_PROMPT_TEXT', () => {
  it('contains strict guidelines and severity thresholds', () => {
    expect(SYSTEM_PROMPT_TEXT).toContain('Principal DevOps Architect')
    expect(SYSTEM_PROMPT_TEXT).toContain('Remediation')
    expect(SYSTEM_PROMPT_TEXT).toContain('yaml')
    expect(SYSTEM_PROMPT_TEXT).toContain('high: Failure rate >= 15%')
  })
})

