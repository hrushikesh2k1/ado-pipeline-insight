/** Builds the Sprint Health & Hygiene report as plain text (for mailto:/Outlook) and as HTML (rich copy/paste). */

export type FlaggedItem = { id: number; assigned_to_name?: string | null; assignee?: string | null; web_url?: string | null }

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
  return item.assigned_to_name?.trim() || item.assignee?.trim() || 'Unassigned'
}

export function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

type Line = { text: string; html: string }
const plain = (text: string): Line => ({ text, html: escapeHtml(text) })

function itemLine(item: FlaggedItem, organization: string, project: string): Line {
  const url = workItemUrl(item, organization, project)
  const who = assignee(item)
  return {
    text: `${url} - ${who}`,
    html: `<a href="${escapeHtml(url)}">${item.id}</a> - ${escapeHtml(who)}`,
  }
}

function listOrDots(items: FlaggedItem[], organization: string, project: string): Line[] {
  const rows = items.map(i => itemLine(i, organization, project))
  return rows.length ? rows : [plain('.....')]
}

export function buildSprintReport(input: SprintReportInput): { text: string; html: string } {
  const lines: Line[] = [
    plain('Hi Team,'),
    plain(''),
    plain('Below are our team members who closed the task without filling hours'),
    plain(''),
    ...listOrDots(input.closedWithoutHours, input.organization, input.project),
    plain(''),
    plain('Below are our team members whose work items are in review more than 4 days'),
    plain(''),
    ...listOrDots(input.staleInReview, input.organization, input.project),
    plain(''),
    plain('please let me know the reason for this miss also let us know if any process improvements needed.'),
    plain(''),
    plain('Thanks,'),
    plain('Lalit'),
  ]
  return {
    text: lines.map(l => l.text).join('\n') + '\n',
    html: `<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.5">${lines.map(l => l.html).join('<br>')}</div>`,
  }
}

export interface MemberDeliverableItem {
  name: string
  hoursDelivered: number
  storyTitles: string[]
  bugCount: number
  crossSprintCount?: number
  crossSprintBugCount?: number
}

export interface TeamDeliverablesReportInput {
  sprintLabel: string
  capacityPerPersonHours: number
  teamTitle: string
  members: MemberDeliverableItem[]
}

/** Check if two person names match, tolerating aliases in parentheses, casing, and whitespace. */
export function isSamePerson(nameA?: string | null, nameB?: string | null): boolean {
  if (!nameA || !nameB) return false
  const cleanA = nameA.toLowerCase().replace(/\s*\([^)]*\)/g, '').trim()
  const cleanB = nameB.toLowerCase().replace(/\s*\([^)]*\)/g, '').trim()
  if (!cleanA || !cleanB) return false
  if (cleanA === cleanB) return true
  if (cleanA.includes(cleanB) || cleanB.includes(cleanA)) return true
  return false
}

function normalizeIterationPath(path?: string | null): string {
  return (path || '').trim().replace(/\//g, '\\').replace(/\\+$/g, '').toLowerCase()
}

function iterationLeaf(path?: string | null): string {
  const clean = (path || '').trim().replace(/\//g, '\\')
  return clean.split('\\').filter(Boolean).pop() || clean || 'another sprint'
}

function crossSprintNote(itemIterationPath?: string | null, sprintPath?: string | null, sourceFound = true, hasCompletionEvidence = false): string {
  const itemPath = normalizeIterationPath(itemIterationPath)
  const currentPath = normalizeIterationPath(sprintPath)
  if (!itemPath) {
    return !sourceFound && hasCompletionEvidence ? ' (closed in this sprint; tracked outside selected sprint)' : ''
  }
  if (!currentPath || itemPath === currentPath) return ''
  return ` (closed in this sprint; tracked under ${iterationLeaf(itemIterationPath)})`
}

/** Formats sprint date range or name into a concise month and 2-digit year (e.g. "Sep '26"). */
export function formatSprintMonthYear(
  startDate?: string | null,
  finishDate?: string | null,
  sprintName?: string | null
): string {
  const dateStr = finishDate || startDate
  if (dateStr) {
    const d = new Date(dateStr)
    if (!Number.isNaN(d.getTime())) {
      const month = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' })
      const year = String(d.getUTCFullYear()).slice(-2)
      return `${month} '${year}`
    }
  }
  if (sprintName) {
    const monthMatch = sprintName.match(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*/i)
    const yearMatch = sprintName.match(/\b(20\d{2}|\d{2})\b/)
    if (monthMatch && yearMatch) {
      const m = monthMatch[1].charAt(0).toUpperCase() + monthMatch[1].slice(1, 3).toLowerCase()
      const y = yearMatch[1].slice(-2)
      return `${m} '${y}`
    }
    return sprintName.replace(/\s*Sprint\s*/i, '').trim()
  }
  return 'Current Sprint'
}

/** Calculates total business days (Monday-Friday) in a sprint period. */
export function calculateSprintBusinessDays(
  startStr?: string | null,
  finishStr?: string | null
): number {
  if (!startStr || !finishStr) return 21 // standard monthly default
  const start = new Date(startStr)
  const finish = new Date(finishStr)
  if (Number.isNaN(start.getTime()) || Number.isNaN(finish.getTime())) return 21

  const cur = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate()))
  const target = new Date(Date.UTC(finish.getUTCFullYear(), finish.getUTCMonth(), finish.getUTCDate()))

  if (cur >= target) return 10

  let count = 0
  while (cur < target) {
    cur.setUTCDate(cur.getUTCDate() + 1)
    const day = cur.getUTCDay()
    if (day !== 0 && day !== 6) {
      count++
    }
  }
  return count > 0 ? count : 21
}

/**
 * Builds the Team Deliverables report as plain text and HTML matching the enterprise email format:
 * Hi,
 * Below are the high-level details of the work delivered in Sep '26.
 * Capacity/person – 168 hrs.
 *
 * @BADONI Sachin (160h)
 * • Story 1
 * • Bug fixes (3 nos.)
 */
export function buildTeamDeliverablesReport(
  input: TeamDeliverablesReportInput
): { text: string; html: string } {
  const textLines: string[] = [
    'Hi,',
    '',
    `Below are the high-level details of the work delivered in ${input.sprintLabel}.`,
    'Note: Items marked as tracked under another sprint were assigned to a different iteration path in Azure DevOps, but were closed during this sprint date range.',
    `Capacity/person – ${input.capacityPerPersonHours} hrs.`,
  ]

  const htmlSections: string[] = [
    '<p style="margin: 0 0 12px 0;">Hi,</p>',
    `<p style="margin: 0 0 4px 0;">Below are the high-level details of the <u>work delivered</u> in <b>${escapeHtml(input.sprintLabel)}</b>.</p>`,
    '<p style="margin: 0 0 4px 0; color: #475569;">Note: Items marked as tracked under another sprint were assigned to a different iteration path in Azure DevOps, but were closed during this sprint date range.</p>',
    `<p style="margin: 0 0 16px 0;">Capacity/person – <b>${input.capacityPerPersonHours} hrs.</b></p>`,
  ]

  input.members.forEach(m => {
    // Plain text section
    textLines.push('')
    textLines.push(`@${m.name} (${m.hoursDelivered}h)`)
    m.storyTitles.forEach(st => {
      textLines.push(`• ${st}`)
    })
    if (m.bugCount > 0) {
      const crossSprintBugText = m.crossSprintBugCount ? `; ${m.crossSprintBugCount} tracked under another sprint` : ''
      textLines.push(`• Bug fixes (${m.bugCount} nos.${crossSprintBugText})`)
    }

    // HTML section
    const itemsHtml: string[] = []
    m.storyTitles.forEach(st => {
      itemsHtml.push(`<li>${escapeHtml(st)}</li>`)
    })
    if (m.bugCount > 0) {
      const crossSprintBugText = m.crossSprintBugCount ? `; ${m.crossSprintBugCount} tracked under another sprint` : ''
      itemsHtml.push(`<li>Bug fixes (${m.bugCount} nos.${escapeHtml(crossSprintBugText)})</li>`)
    }

    htmlSections.push(
      `<p style="margin: 16px 0 4px 0;"><b><span style="color: #0078d4;">@${escapeHtml(m.name)}</span> (${m.hoursDelivered}h)</b></p>` +
      `<ul style="margin: 4px 0 12px 0; padding-left: 20px;">${itemsHtml.join('')}</ul>`
    )
  })

  return {
    text: textLines.join('\n') + '\n',
    html: `<div style="font-family: Segoe UI, Arial, sans-serif; font-size: 14px; line-height: 1.5; color: #1e293b;">${htmlSections.join('')}</div>`,
  }
}

/** Prepares member deliverables by aggregating delivered stories, grouped bugs, and hours per contributor. */
export function prepareMemberDeliverables(
  completedDeliverables: {
    id: number
    title: string
    work_item_type: string
    category?: string
    assigned_to_name?: string | null
    hours_delivered?: number
    iteration_path?: string | null
    completed_date?: string | null
  }[],
  memberContributions: {
    name: string
    completedHours: number
  }[],
  workItems: {
    id: number
    title: string
    work_item_type: string
    state: string
    assigned_to_name?: string | null
    parent_id?: number | null
    completed_work?: number | null
    closed_date?: string | null
    state_change_date?: string | null
    changed_date?: string | null
    iteration_path?: string | null
  }[] = [],
  memberCapacities: Record<string, number> = {},
  defaultCapacity: number = 168,
  iteration?: {
    start_date?: string | null
    finish_date?: string | null
    path?: string | null
  } | null
): MemberDeliverableItem[] {
  const closedStates = ['closed', 'done', 'completed', 'resolved']
  const tasksByParent: Record<number, typeof workItems> = {}
  workItems.forEach(w => {
    if (w.work_item_type.toLowerCase() === 'task' && w.parent_id) {
      if (!tasksByParent[w.parent_id]) tasksByParent[w.parent_id] = []
      tasksByParent[w.parent_id].push(w)
    }
  })

  const memberDeliverablesMap: Record<string, {
    hours: number
    stories: string[]
    bugCount: number
    crossSprintCount: number
    crossSprintBugCount: number
    taskFallbacks: string[]
  }> = {}

  // Seed with memberContributions for total completed hours
  memberContributions.forEach(mc => {
    if (mc.name && mc.name !== 'Unassigned') {
      memberDeliverablesMap[mc.name] = {
        hours: mc.completedHours,
        stories: [],
        bugCount: 0,
        crossSprintCount: 0,
        crossSprintBugCount: 0,
        taskFallbacks: [],
      }
    }
  })

  // Group completed deliverables
  completedDeliverables.forEach(item => {
    const isBug =
      item.work_item_type.toLowerCase().includes('bug') ||
      item.category === 'Bug Fix & Quality'

    let matchedMember = Object.keys(memberDeliverablesMap).find(mName =>
      isSamePerson(mName, item.assigned_to_name)
    )

    if (!matchedMember && item.id && tasksByParent[item.id]) {
      const childTasks = tasksByParent[item.id]
      for (const t of childTasks) {
        if (t.assigned_to_name) {
          const found = Object.keys(memberDeliverablesMap).find(mName =>
            isSamePerson(mName, t.assigned_to_name)
          )
          if (found) {
            matchedMember = found
            break
          }
        }
      }
    }

    if (!matchedMember && item.assigned_to_name && item.assigned_to_name !== 'Unassigned') {
      matchedMember = item.assigned_to_name
      memberDeliverablesMap[matchedMember] = {
        hours: item.hours_delivered || 0,
        stories: [],
        bugCount: 0,
        crossSprintCount: 0,
        crossSprintBugCount: 0,
        taskFallbacks: [],
      }
    }

    if (matchedMember) {
      const sourceItem = workItems.find(w => w.id === item.id)
      const note = crossSprintNote(
        item.iteration_path || sourceItem?.iteration_path,
        iteration?.path,
        Boolean(sourceItem),
        Boolean(item.completed_date)
      )
      if (isBug) {
        memberDeliverablesMap[matchedMember].bugCount += 1
        if (note) {
          memberDeliverablesMap[matchedMember].crossSprintBugCount += 1
          memberDeliverablesMap[matchedMember].crossSprintCount += 1
        }
      } else {
        const storyTitle = `${item.title}${note}`
        if (!memberDeliverablesMap[matchedMember].stories.includes(storyTitle)) {
          memberDeliverablesMap[matchedMember].stories.push(storyTitle)
          if (note) memberDeliverablesMap[matchedMember].crossSprintCount += 1
        }
      }
    }
  })

  // Collect standalone tasks for members who logged completed hours but have no top-level stories
  workItems.forEach(w => {
    if (closedStates.includes(w.state.toLowerCase()) && w.assigned_to_name) {
      if (iteration?.start_date && iteration?.finish_date) {
        const start = new Date(iteration.start_date).getTime()
        const finish = new Date(iteration.finish_date)
        finish.setUTCHours(23, 59, 59, 999)
        const closedRaw = w.closed_date || w.state_change_date || w.changed_date
        if (closedRaw) {
          const cTime = new Date(closedRaw).getTime()
          if (!isNaN(cTime) && (cTime < start || cTime > finish.getTime())) {
            return
          }
        }
      }
      const matchedMember = Object.keys(memberDeliverablesMap).find(mName =>
        isSamePerson(mName, w.assigned_to_name)
      )
      if (matchedMember) {
        const entry = memberDeliverablesMap[matchedMember]
        if (entry.stories.length === 0 && entry.bugCount === 0) {
          if (!entry.taskFallbacks.includes(w.title)) {
            entry.taskFallbacks.push(w.title)
          }
        }
      }
    }
  })

  // Resolve person's planned capacity (not task completed hours)
  const getPersonCapacity = (name: string): number => {
    const matchedKey = Object.keys(memberCapacities).find(k => isSamePerson(k, name))
    if (matchedKey && memberCapacities[matchedKey] !== undefined) {
      return memberCapacities[matchedKey]
    }
    return defaultCapacity
  }

  return Object.entries(memberDeliverablesMap)
    .filter(([_, data]) => data.hours > 0 || data.stories.length > 0 || data.bugCount > 0 || data.taskFallbacks.length > 0)
    .map(([name, data]) => ({
      name,
      hoursDelivered: getPersonCapacity(name),
      storyTitles: data.stories.length > 0 ? data.stories : data.taskFallbacks,
      bugCount: data.bugCount,
      crossSprintCount: data.crossSprintCount,
      crossSprintBugCount: data.crossSprintBugCount,
    }))
    .sort((a, b) => b.hoursDelivered - a.hoursDelivered || b.storyTitles.length - a.storyTitles.length)
}
