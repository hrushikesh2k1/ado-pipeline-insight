/** Builds the Sprint Health & Hygiene report as plain text (for mailto:/Outlook) and as HTML (rich copy/paste). */

export type FlaggedItem = { id: number; assigned_to_name?: string | null; web_url?: string | null }

export type ReportMilestone = {
  closed_stories_count: number
  total_stories: number
  completion_rate_pct: number
  total_delivered_hours: number
  features_delivered_count: number
  bugs_resolved_count: number
}

export type SprintReportInput = {
  sprintTitle: string
  teamTitle: string
  activeWorkItems: number
  closedWithoutHours: FlaggedItem[]
  closedWithoutHoursCount: number
  staleInReview: FlaggedItem[]
  staleInReviewCount: number
  milestone?: ReportMilestone | null
  organization: string
  project: string
  dashboardUrl: string
}

export function workItemUrl(item: FlaggedItem, organization: string, project: string): string {
  return item.web_url || `https://dev.azure.com/${encodeURIComponent(organization)}/${encodeURIComponent(project)}/_workitems/edit/${item.id}`
}

export function assignee(item: FlaggedItem): string {
  return item.assigned_to_name?.trim() || 'Unassigned'
}

export function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

type Line = { text: string; html: string }
const plain = (text: string): Line => ({ text, html: escapeHtml(text) })

/**
 * One line per flagged work item: "<work item> - Assigned to: <name>".
 * Plain text cannot carry a hyperlink on the number, so the work item URL (which ends in the number) stands in for it
 * and is clickable in Outlook; the HTML version makes the number itself the link.
 */
function itemLine(item: FlaggedItem, organization: string, project: string): Line {
  const url = workItemUrl(item, organization, project)
  const who = assignee(item)
  return {
    text: `   • ${url} - Assigned to: ${who}`,
    html: `&nbsp;&nbsp;&nbsp;• <a href="${escapeHtml(url)}">${item.id}</a> - Assigned to: ${escapeHtml(who)}`,
  }
}

export function buildSprintReport(input: SprintReportInput): { text: string; html: string } {
  const rule = '========================================================='
  const lines: Line[] = [
    plain('Hi Team,'),
    plain(''),
    plain(`Here is the Azure Boards Sprint Health & Hygiene Report for ${input.sprintTitle} (${input.teamTitle}):`),
    plain(''),
    plain(rule),
    plain('📌 SPRINT SUMMARY'),
    plain(`• Sprint: ${input.sprintTitle}`),
    plain(`• Team: ${input.teamTitle}`),
    plain(`• Active Work Items: ${input.activeWorkItems}`),
    plain(''),
    plain('🔍 PROCESS HYGIENE CHECKS'),
    plain(`• Check 1 (Closed Tasks without Completed Hours): ${input.closedWithoutHoursCount} violation(s)`),
    ...input.closedWithoutHours.map(i => itemLine(i, input.organization, input.project)),
    plain(`• Check 2 (User Stories In Review > 4 Work Days): ${input.staleInReviewCount} violation(s)`),
    ...input.staleInReview.map(i => itemLine(i, input.organization, input.project)),
    plain(''),
  ]
  const m = input.milestone
  if (m) {
    lines.push(
      plain('🎯 MILESTONE & CAPACITY BREAKDOWN'),
      plain(`• Milestone Story Progress: ${m.closed_stories_count}/${m.total_stories} completed (${m.completion_rate_pct}%)`),
      plain(`• Verified Delivered Hours: ${m.total_delivered_hours} hrs`),
      plain(`• Features Delivered: ${m.features_delivered_count} | Bug Fixes: ${m.bugs_resolved_count}`),
      plain(''),
    )
  }
  lines.push(
    plain(rule),
    plain('Generated via ADO Pipeline Insight & Azure Boards Extension'),
    plain(`Dashboard URL: ${input.dashboardUrl}`),
  )
  return {
    text: lines.map(l => l.text).join('\n') + '\n',
    html: `<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.5">${lines.map(l => l.html).join('<br>')}</div>`,
  }
}
