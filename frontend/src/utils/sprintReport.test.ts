import { describe, expect, it } from 'vitest'
import {
  assignee,
  buildSprintReport,
  buildTeamDeliverablesReport,
  calculateSprintBusinessDays,
  escapeHtml,
  formatSprintMonthYear,
  isSamePerson,
  prepareMemberDeliverables,
  workItemUrl,
} from './sprintReport'

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
    const c1 = lines.findIndex(l => l.startsWith('Below are our team members who closed'))
    const c2 = lines.findIndex(l => l.startsWith('Below are our team members whose work items'))
    expect(lines[c1 + 2]).toBe('https://dev.azure.com/org/proj/_workitems/edit/1001 - Asha Rao')
    expect(lines[c2 + 2]).toBe('https://dev.azure.com/my%20org/Cloud%20Tech/_workitems/edit/2002 - Ravi <Dev>')
    expect(lines[c2 + 3]).toBe('https://dev.azure.com/my%20org/Cloud%20Tech/_workitems/edit/2003 - Unassigned')
  })

  it('uses the requested short email body and omits the old sprint summary metrics', () => {
    expect(text).toContain('Hi Team,\n\nBelow are our team members who closed the task without filling hours')
    expect(text).toContain('Below are our team members whose work items are in review more than 4 days')
    expect(text).toContain('please let me know the reason for this miss also let us know if any process improvements needed.\n\nThanks,\nLalit\n')
    expect(text).not.toContain('Active Work Items')
    expect(text).not.toContain('MILESTONE')
    expect(text).not.toContain('Generated via ADO Pipeline Insight')
  })

  it('makes the work item number the hyperlink in the HTML version and escapes names', () => {
    expect(html).toContain('<a href="https://dev.azure.com/org/proj/_workitems/edit/1001">1001</a> - Asha Rao')
    expect(html).toContain('Ravi &lt;Dev&gt;')
    expect(html).not.toContain('Ravi <Dev>')
  })

  it('prints placeholder dots under a section that has no items', () => {
    const clean = buildSprintReport({ ...base, closedWithoutHours: [], closedWithoutHoursCount: 0, staleInReview: [], staleInReviewCount: 0, milestone: null }).text
    expect(clean).toContain('Below are our team members who closed the task without filling hours\n\n.....\n\nBelow are our team members whose work items are in review more than 4 days\n\n.....')
  })
})

describe('helpers', () => {
  it('builds an encoded Azure DevOps URL when the item has none', () => {
    expect(workItemUrl({ id: 7 }, 'a b', 'c/d')).toBe('https://dev.azure.com/a%20b/c%2Fd/_workitems/edit/7')
  })
  it('names unassigned items and escapes html', () => {
    expect(assignee({ id: 1, assigned_to_name: '  ' })).toBe('Unassigned')
    expect(assignee({ id: 1, assignee: 'Saved Report Name' })).toBe('Saved Report Name')
    expect(escapeHtml('<a href="x">&')).toBe('&lt;a href=&quot;x&quot;&gt;&amp;')
  })
})

describe('buildTeamDeliverablesReport & team deliverable helpers', () => {
  it('formats sprint month and 2-digit year correctly', () => {
    expect(formatSprintMonthYear('2026-09-01T00:00:00Z', '2026-09-30T00:00:00Z')).toBe("Sep '26")
    expect(formatSprintMonthYear(null, null, '26-09 (Sep Work) Sprint')).toBe("Sep '26")
  })

  it('calculates 21 sprint business days and 168h capacity for September', () => {
    const days = calculateSprintBusinessDays('2026-09-01T00:00:00Z', '2026-09-30T00:00:00Z')
    expect(days).toBe(21)
    expect(days * 8).toBe(168)
  })

  it('matches member names resiliently with aliases', () => {
    expect(isSamePerson('BOORA Hrushikesh (Boora)', 'BOORA Hrushikesh')).toBe(true)
    expect(isSamePerson('BADONI Sachin', 'badoni sachin')).toBe(true)
    expect(isSamePerson('ADAPA Rajesh', 'GUDA Sriram')).toBe(false)
  })

  it('builds the exact team deliverables report structure', () => {
    const report = buildTeamDeliverablesReport({
      sprintLabel: "Sep '26",
      capacityPerPersonHours: 168,
      teamTitle: 'CloudOps-Monitoring',
      members: [
        {
          name: 'BADONI Sachin',
          hoursDelivered: 160,
          storyTitles: [
            'Legacy authentication for Container Insights',
            'Update WebAPI Ingress to a 60 second timeout',
          ],
          bugCount: 3,
        },
        {
          name: 'GUDA Sriram',
          hoursDelivered: 144,
          storyTitles: [
            'MDC-related PVs that are in the Released state are to be cleaned up across environments',
          ],
          bugCount: 2,
        },
      ],
    })

    expect(report.text).toContain("Below are the high-level details of the work delivered in Sep '26.")
    expect(report.text).toContain('Capacity/person – 168 hrs.')
    expect(report.text).toContain('@BADONI Sachin (160h)')
    expect(report.text).toContain('• Legacy authentication for Container Insights')
    expect(report.text).toContain('• Bug fixes (3 nos.)')
    expect(report.text).toContain('@GUDA Sriram (144h)')
    expect(report.text).toContain('• Bug fixes (2 nos.)')

    expect(report.html).toContain("work delivered</u> in <b>Sep '26</b>")
    expect(report.html).toContain('Capacity/person – <b>168 hrs.</b>')
    expect(report.html).toContain('@BADONI Sachin</span> (160h)</b>')
    expect(report.html).toContain('<li>Bug fixes (3 nos.)</li>')
  })

  it('prepares member deliverables aggregating stories and bugs', () => {
    const members = prepareMemberDeliverables(
      [
        {
          id: 101,
          title: 'Container Insights feature',
          work_item_type: 'User Story',
          assigned_to_name: 'BADONI Sachin',
          hours_delivered: 40,
        },
        {
          id: 102,
          title: 'Pod restart bug',
          work_item_type: 'Bug',
          assigned_to_name: 'BADONI Sachin',
          hours_delivered: 8,
        },
      ],
      [
        { name: 'BADONI Sachin', completedHours: 88 },
      ],
      [],
      { 'BADONI Sachin': 160 },
      168
    )

    expect(members).toHaveLength(1)
    expect(members[0].name).toBe('BADONI Sachin')
    expect(members[0].hoursDelivered).toBe(160) // Uses person capacity (160), not completed hours (88)
    expect(members[0].storyTitles).toEqual(['Container Insights feature'])
    expect(members[0].bugCount).toBe(1)
  })

  it('labels work items that were tracked under another sprint but closed in the selected sprint', () => {
    const members = prepareMemberDeliverables(
      [
        {
          id: 101,
          title: 'Finish carried-over monitor rules',
          work_item_type: 'User Story',
          assigned_to_name: 'BADONI Sachin',
          hours_delivered: 16,
          iteration_path: 'CloudOps\\26-08',
        },
        {
          id: 102,
          title: 'Fix carried-over alert bug',
          work_item_type: 'Bug',
          assigned_to_name: 'BADONI Sachin',
          hours_delivered: 4,
          iteration_path: 'CloudOps\\26-08',
        },
      ],
      [{ name: 'BADONI Sachin', completedHours: 20 }],
      [
        {
          id: 101,
          title: 'Finish carried-over monitor rules',
          work_item_type: 'User Story',
          state: 'Closed',
          assigned_to_name: 'BADONI Sachin',
          iteration_path: 'CloudOps\\26-08',
        },
        {
          id: 102,
          title: 'Fix carried-over alert bug',
          work_item_type: 'Bug',
          state: 'Closed',
          assigned_to_name: 'BADONI Sachin',
          iteration_path: 'CloudOps\\26-08',
        },
      ],
      { 'BADONI Sachin': 160 },
      168,
      { path: 'CloudOps\\26-09', start_date: '2026-09-01T00:00:00Z', finish_date: '2026-09-30T00:00:00Z' }
    )

    expect(members[0].storyTitles[0]).toContain('closed in this sprint; tracked under 26-08')
    expect(members[0].crossSprintCount).toBe(2)
    expect(members[0].crossSprintBugCount).toBe(1)

    const report = buildTeamDeliverablesReport({
      sprintLabel: "Sep '26",
      capacityPerPersonHours: 168,
      teamTitle: 'CloudOps-Monitoring',
      members,
    })
    expect(report.text).toContain('assigned to a different iteration path')
    expect(report.text).toContain('Bug fixes (1 nos.; 1 tracked under another sprint)')
  })

  it('labels old saved deliverables that are absent from the current sprint board list', () => {
    const members = prepareMemberDeliverables(
      [
        {
          id: 201,
          title: 'Create informational alert from saved report',
          work_item_type: 'User Story',
          assigned_to_name: 'BOORA Hrushikesh',
          hours_delivered: 8,
          completed_date: '2026-09-10T12:00:00Z',
        },
      ],
      [{ name: 'BOORA Hrushikesh', completedHours: 8 }],
      [],
      { 'BOORA Hrushikesh': 160 },
      168,
      { path: 'CloudOps\\26-09', start_date: '2026-09-01T00:00:00Z', finish_date: '2026-09-30T00:00:00Z' }
    )

    expect(members[0].storyTitles[0]).toContain('closed in this sprint; tracked outside selected sprint')
  })
})
