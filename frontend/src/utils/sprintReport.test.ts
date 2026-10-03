import { describe, expect, it } from 'vitest'
import { assignee, buildSprintReport, escapeHtml, workItemUrl } from './sprintReport'

const base = {
  sprintTitle: '26-10 (Oct Work) Sprint',
  teamTitle: 'CloudOps-Monitoring',
  activeWorkItems: 25,
  closedWithoutHours: [{ id: 1001, assigned_to_name: 'Asha Rao', web_url: 'https://dev.azure.com/org/proj/_workitems/edit/1001' }],
  closedWithoutHoursCount: 1,
  staleInReview: [
    { id: 2002, assigned_to_name: 'Ravi <Dev>' },
    { id: 2003, assigned_to_name: null },
  ],
  staleInReviewCount: 2,
  milestone: { closed_stories_count: 0, total_stories: 9, completion_rate_pct: 0, total_delivered_hours: 0.5, features_delivered_count: 0, bugs_resolved_count: 0 },
  organization: 'my org',
  project: 'Cloud Tech',
  dashboardUrl: 'https://app.example',
}

describe('buildSprintReport', () => {
  const { text, html } = buildSprintReport(base)
  const lines = text.split('\n')

  it('lists each flagged item directly under its own check, with who it is assigned to', () => {
    const c1 = lines.findIndex(l => l.startsWith('• Check 1'))
    const c2 = lines.findIndex(l => l.startsWith('• Check 2'))
    expect(lines[c1 + 1]).toBe('   • https://dev.azure.com/org/proj/_workitems/edit/1001 - Assigned to: Asha Rao')
    expect(lines[c1 + 2].startsWith('• Check 2')).toBe(true)
    expect(lines[c2 + 1]).toBe('   • https://dev.azure.com/my%20org/Cloud%20Tech/_workitems/edit/2002 - Assigned to: Ravi <Dev>')
    expect(lines[c2 + 2]).toBe('   • https://dev.azure.com/my%20org/Cloud%20Tech/_workitems/edit/2003 - Assigned to: Unassigned')
  })

  it('leaves every other section exactly as before', () => {
    expect(text).toContain('📌 SPRINT SUMMARY\n• Sprint: 26-10 (Oct Work) Sprint\n• Team: CloudOps-Monitoring\n• Active Work Items: 25\n')
    expect(text).toContain('• Check 1 (Closed Tasks without Completed Hours): 1 violation(s)')
    expect(text).toContain('• Check 2 (User Stories In Review > 4 Work Days): 2 violation(s)')
    expect(text).toContain('🎯 MILESTONE & CAPACITY BREAKDOWN\n• Milestone Story Progress: 0/9 completed (0%)\n• Verified Delivered Hours: 0.5 hrs\n• Features Delivered: 0 | Bug Fixes: 0\n')
    expect(text).toContain('Generated via ADO Pipeline Insight & Azure Boards Extension\nDashboard URL: https://app.example\n')
  })

  it('makes the work item number the hyperlink in the HTML version and escapes names', () => {
    expect(html).toContain('<a href="https://dev.azure.com/org/proj/_workitems/edit/1001">1001</a> - Assigned to: Asha Rao')
    expect(html).toContain('Ravi &lt;Dev&gt;')
    expect(html).not.toContain('Ravi <Dev>')
  })

  it('prints nothing under a check that has no violations and omits the milestone block when absent', () => {
    const clean = buildSprintReport({ ...base, closedWithoutHours: [], closedWithoutHoursCount: 0, staleInReview: [], staleInReviewCount: 0, milestone: null }).text
    expect(clean).toContain('• Check 1 (Closed Tasks without Completed Hours): 0 violation(s)\n• Check 2 (User Stories In Review > 4 Work Days): 0 violation(s)\n')
    expect(clean).not.toContain('MILESTONE')
  })
})

describe('helpers', () => {
  it('builds an encoded Azure DevOps URL when the item has none', () => {
    expect(workItemUrl({ id: 7 }, 'a b', 'c/d')).toBe('https://dev.azure.com/a%20b/c%2Fd/_workitems/edit/7')
  })
  it('names unassigned items and escapes html', () => {
    expect(assignee({ id: 1, assigned_to_name: '  ' })).toBe('Unassigned')
    expect(escapeHtml('<a href="x">&')).toBe('&lt;a href=&quot;x&quot;&gt;&amp;')
  })
})
