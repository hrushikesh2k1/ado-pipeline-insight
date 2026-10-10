import { describe, expect, it } from 'vitest'
import { buildDeliverablesText, outlookDraftUrl, type DeliverablesReport } from './deliverablesReport'

const report: DeliverablesReport = {
  team: 'team-id', sprint: 'September', iteration_path: 'Cloud\\September',
  start: '2026-09-01T00:00:00+00:00', end_exclusive: '2026-10-01T00:00:00+00:00',
  generated_at: '2026-10-02T00:00:00+00:00', provisional: false,
  delivered_count: 1, completed_tasks: 1, recorded_hours: 8, missing_effort_count: 0,
  cross_iteration_count: 1, recipients: ['alice@example.com', 'bob@example.com'],
  missing_recipient_names: [], recipients_verified: true,
  warnings: ['Cumulative recorded effort; available hours are separate.'],
  people: [{ id: 'alice', name: 'Alice & Bob', email: 'alice@example.com', available_hours: 160,
    delivered_count: 1, completed_tasks: 1, recorded_hours: 8, missing_effort_count: 0,
    items: [{ id: 42, title: 'August carryover & alert fix', type: 'Task', completed_at: '2026-09-30T23:59:59+00:00',
      iteration_path: 'Cloud\\August', cross_iteration: true, parent_id: 43, recorded_hours: 8,
      status: 'delivered', reopened_after_period: true, completion_events_in_period: 1,
      web_url: 'https://dev.azure.com/org/Cloud/_workitems/edit/42' }] }],
}
describe('deliverables report exports', () => {
  it('includes the finish day, carryover context, contributors and separate capacity', () => {
    const text = buildDeliverablesText(report, 'CloudOps-Monitoring')
    expect(text).toContain('2026-09-01 through 2026-09-30 (UTC)')
    expect(text).toContain('assigned iteration: Cloud\\August')
    expect(text).toContain('parent #43')
    expect(text).toContain('reopened after sprint end')
    expect(text).toContain('recorded effort 8 h; available capacity 160 h')
    expect(text).toContain('https://dev.azure.com/org/Cloud/_workitems/edit/42')
  })
  it('encodes recipients and excludes task rows from email without sending', () => {
    const url = outlookDraftUrl(report, 'CloudOps-Monitoring')
    expect(url).toMatch(/^mailto:alice%40example.com;bob%40example.com\?/)
    const params = new URLSearchParams(url.split('?')[1])
    expect(params.get('body')).toBe(buildDeliverablesText(report, 'CloudOps-Monitoring', true))
    expect(params.get('body')).not.toContain('#42 Task')
    expect(params.get('subject')).toContain('September')
    expect(params.get('body')).toContain('Alice & Bob')
  })
  it('marks provisional reports and preserves missing email and capacity details', () => {
    const input = { ...report, provisional: true, missing_recipient_names: ['Charlie'], people: [{ ...report.people[0], available_hours: null }] }
    const text = buildDeliverablesText(input, 'Team')
    expect(text).toContain('(Provisional)')
    expect(text).toContain('available capacity unavailable')
    expect(text).toContain('Missing team email addresses: Charlie')
  })
})
