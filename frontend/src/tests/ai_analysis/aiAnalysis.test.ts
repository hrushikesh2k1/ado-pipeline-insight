import { describe, expect, it } from 'vitest'
import { diffNewLines, extractYamlFromRemediation, isDiffSnippet, SYSTEM_PROMPT_TEXT } from '../../App'

describe('AI Analysis Test Suite', () => {
  it('extracts explicit yaml blocks from AI remediation markdown', () => {
    const raw = "Add caching to your task:\n\n```yaml\n- task: Cache@2\n  inputs:\n    key: 'test'\n```\n\nEnsure path exists."
    const { text, yaml } = extractYamlFromRemediation(raw, 'caching_opportunity', 'Build')
    expect(yaml).toBe("- task: Cache@2\n  inputs:\n    key: 'test'")
    expect(text).toContain('Add caching to your task:')
  })

  it('extracts a diff against the customer pipeline file', () => {
    const raw = 'In `azure-pipelines.yml` → job `build`, retry the step:\n\n```diff\n--- a/azure-pipelines.yml\n+++ b/azure-pipelines.yml\n@@ -3,2 +3,3 @@\n   displayName: npm ci\n+  retryCountOnTaskFailure: 2\n```'
    const { text, yaml } = extractYamlFromRemediation(raw)
    expect(yaml.startsWith('--- a/azure-pipelines.yml')).toBe(true)
    expect(yaml).toContain('+  retryCountOnTaskFailure: 2')
    expect(text).not.toContain('```')
  })

  it('never invents a YAML snippet when the recommendation has no code block', () => {
    for (const category of ['caching_opportunity', 'flaky_step', 'bottleneck', 'parallelization_opportunity', 'other']) {
      const { text, yaml } = extractYamlFromRemediation('Look at what this step waits on.', category, 'Deploy', 'Helm Upgrade')
      expect(yaml).toBe('')
      expect(text).toBe('Look at what this step waits on.')
    }
  })

  it('tells a diff against the customer file apart from an example snippet', () => {
    expect(isDiffSnippet('--- a/azure-pipelines.yml\n+++ b/azure-pipelines.yml\n@@ -1,2 +1,3 @@')).toBe(true)
    expect(isDiffSnippet('@@ -3,2 +3,3 @@\n+  retryCountOnTaskFailure: 2')).toBe(true)
    expect(isDiffSnippet("- task: Cache@2\n  inputs:\n    key: 'x'")).toBe(false)
    expect(isDiffSnippet('')).toBe(false)
  })

  it('copies only the lines a diff adds, ready to paste into the file', () => {
    const diff = '--- a/azure-pipelines.yml\n+++ b/azure-pipelines.yml\n@@ -9,2 +9,4 @@\n   displayName: npm ci\n+  retryCountOnTaskFailure: 2\n+  timeoutInMinutes: 20\n   script: x'
    expect(diffNewLines(diff)).toBe('  retryCountOnTaskFailure: 2\n  timeoutInMinutes: 20')
    expect(diffNewLines('--- a/f\n+++ b/f\n')).toBe('')
    expect(diffNewLines('key: value')).toBe('')
  })

  it('extracts a pasteable example block and a diff from the same kind of remediation text', () => {
    const example = extractYamlFromRemediation('Define the variable:\n\n```yaml\n# example, not from your file\nvariables:\n  - name: x\n    value: y\n```')
    expect(example.yaml.startsWith('# example, not from your file')).toBe(true)
    expect(isDiffSnippet(example.yaml)).toBe(false)
    expect(example.text).toBe('Define the variable:')
  })

  it('requires every finding to carry root cause, remediation, a YAML fix, and a measured impact', () => {
    expect(SYSTEM_PROMPT_TEXT).toContain('Every finding MUST have all three sections')
    expect(SYSTEM_PROMPT_TEXT).toContain('MUST contain exactly one code block')
    expect(SYSTEM_PROMPT_TEXT).toContain('# example, not from your file')
    expect(SYSTEM_PROMPT_TEXT).toContain('Never promise a result')
    expect(SYSTEM_PROMPT_TEXT).toContain('read all of them before answering')
    expect(SYSTEM_PROMPT_TEXT).toContain('A diff whose lines do not exist in the file is discarded')
  })

  it('no longer caps the model at four findings and asks for every high-severity step', () => {
    expect(SYSTEM_PROMPT_TEXT).not.toContain('between 1 and 4')
    expect(SYSTEM_PROMPT_TEXT).toContain('Return one finding for EVERY task')
    expect(SYSTEM_PROMPT_TEXT).toContain('sorted by failure rate, worst first')
  })

  it('tells the model to read templates, not invent steps it cannot see, and retry only transient failures', () => {
    expect(SYSTEM_PROMPT_TEXT).toContain('templates_not_expanded')
    expect(SYSTEM_PROMPT_TEXT).toContain("invent the step's task type")
    expect(SYSTEM_PROMPT_TEXT).toContain('Recommend a retry only when')
    expect(SYSTEM_PROMPT_TEXT).toContain('do NOT describe the failures as transient')
  })

  it('validates SYSTEM_PROMPT_TEXT contains architect guidelines and thresholds', () => {
    expect(SYSTEM_PROMPT_TEXT).toContain('Principal DevOps Architect')
    expect(SYSTEM_PROMPT_TEXT).toContain('Remediation')
    expect(SYSTEM_PROMPT_TEXT).toContain('yaml')
    expect(SYSTEM_PROMPT_TEXT).toContain('high: Failure rate >= 15%')
  })

  it('tells the model to use the real pipeline file and never repeat what it already does', () => {
    expect(SYSTEM_PROMPT_TEXT).toContain('pipeline_yaml')
    expect(SYSTEM_PROMPT_TEXT).toContain('unified diff')
    expect(SYSTEM_PROMPT_TEXT).toContain('Never recommend something the files already do')
  })
})
