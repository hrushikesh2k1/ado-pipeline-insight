export type DeliverableItem = {
  id: number; title: string; type: string; completed_at: string; iteration_path: string
  cross_iteration: boolean; parent_id: number | null; recorded_hours: number | null
  status: 'delivered' | 'recompleted' | 'reopened_in_period'; reopened_after_period: boolean
  completion_events_in_period: number; web_url: string
}
export type DeliverablePerson = {
  id: string; name: string; email: string | null; available_hours: number | null
  delivered_count: number; completed_tasks: number; recorded_hours: number; missing_effort_count: number
  capacity_breakdown?: { source:string; daily_hours:number|null; available_days:number|null; working_days_before_leave?:number; days_off_on_working_days?:number|null; working_days:string[]; individual_days_off:{start:string;end:string}[]; team_days_off:{start:string;end:string}[] }
  items: DeliverableItem[]
}
export type DeliverablesReport = {
  team: string; sprint: string; iteration_path: string; start: string; end_exclusive: string
  generated_at: string; provisional: boolean; delivered_count: number; completed_tasks: number
  recorded_hours: number; missing_effort_count: number; cross_iteration_count: number
  people: DeliverablePerson[]; recipients: string[]; missing_recipient_names: string[]
  recipients_verified: boolean; warnings: string[]; snapshot_saved?:boolean; from_snapshot?:boolean
}
export function buildDeliverablesText(report: DeliverablesReport, teamName: string, emailOnly=false): string {
  const selected = (item: DeliverableItem) => !emailOnly || ['user story', 'bug'].includes(item.type.toLowerCase())
  const delivered = report.people.flatMap(p => p.items).filter(i => selected(i) && i.status === 'delivered')
  return [
    `Sprint Deliverables — ${teamName} — ${report.sprint}${report.provisional ? ' (Provisional)' : ''}`,
    `Period: ${report.start.slice(0, 10)} through ${new Date(Date.parse(report.end_exclusive) - 1).toISOString().slice(0, 10)} (UTC)`,
    emailOnly ? `${delivered.length} user stories and bugs delivered; ${delivered.filter(i => i.cross_iteration).length} completed in a different assigned iteration.` : `${report.delivered_count} work items delivered; ${report.completed_tasks} completed tasks; ${report.cross_iteration_count} completed in a different assigned iteration.`,
    `Recorded effort on completed tasks: ${report.recorded_hours} hours; ${report.missing_effort_count} task(s) missing effort.`,
    '', ...report.warnings, '',
    ...report.people.flatMap(person => [
      `${person.name}: ${emailOnly ? person.items.filter(i => selected(i) && i.status === 'delivered').length : person.delivered_count} delivered ${emailOnly ? 'user stories and bugs' : 'work items'}; ${emailOnly ? '' : person.completed_tasks + ' completed tasks; '}recorded effort ${person.recorded_hours} h; available capacity ${person.available_hours == null ? 'unavailable' : person.available_hours + ' h'}; ${person.missing_effort_count} task(s) missing effort.`,
      ...person.items.filter(selected).map(item => `  #${item.id} ${item.type}: ${item.title}\n    Completed ${item.completed_at}; assigned iteration: ${item.iteration_path}; ${item.status}${item.reopened_after_period ? '; reopened after sprint end' : ''}${item.parent_id ? '; parent #' + item.parent_id : ''}${emailOnly ? '' : '; recorded effort ' + (item.recorded_hours == null ? 'not recorded' : item.recorded_hours + ' h')}\n    ${item.web_url}`), '',
    ]),
    `Generated: ${report.generated_at}`,
    ...(report.missing_recipient_names.length ? [`Missing team email addresses: ${report.missing_recipient_names.join(', ')}`] : []),
  ].join('\n')
}
export function outlookDraftUrl(report: DeliverablesReport, teamName: string): string {
  return 'mailto:' + report.recipients.map(encodeURIComponent).join(';') + '?subject=' +
    encodeURIComponent(`Sprint Deliverables — ${teamName} — ${report.sprint}`) + '&body=' +
    encodeURIComponent(buildDeliverablesText(report, teamName, true))
}
