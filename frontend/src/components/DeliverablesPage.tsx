import { useEffect, useState } from 'react'
import { Copy, Mail, RefreshCw } from 'lucide-react'
import { api } from '../services/api'
import { buildDeliverablesText, outlookDraftUrl, type DeliverablesReport } from '../utils/deliverablesReport'
import './DeliverablesPage.css'

type Props = { organization: string; project: string; team: string; teamName: string; iterationId: string; pat?: string }
export function DeliverablesPage({ organization, project, team, teamName, iterationId, pat }: Props) {
  const [report, setReport] = useState<DeliverablesReport | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [refresh, setRefresh] = useState({ scope: '', version: 0 })
  const scope = JSON.stringify([organization, project, team, iterationId, pat])
  const [notice, setNotice] = useState('')
  const [personId, setPersonId] = useState('all')
  const [query, setQuery] = useState('')
  const [itemType, setItemType] = useState('all')
  const [preview, setPreview] = useState(false)
  useEffect(() => {
    let current = true
    const regenerate = refresh.scope === scope && refresh.version > 0
    if (!regenerate) { setReport(null); setPersonId('all'); setQuery(''); setItemType('all') }
    setError(''); setNotice(''); setPreview(false)
    if (!organization || !project || !team || !iterationId) return
    setLoading(true)
    api.deliverables(organization, project, team, iterationId, pat, regenerate).then(data => {
      if (current) setReport(data)
    }).catch(err => { if (current) setError(String(err.message || err)) })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [organization, project, team, iterationId, pat, refresh, scope])
  async function copyReport() {
    if (!report) return false
    try {
      await navigator.clipboard.writeText(buildDeliverablesText(report, teamName, true))
      setNotice('Full team report copied.'); return true
    } catch { setNotice('Clipboard access is unavailable. Select and copy the report preview below.'); setPreview(true); return false }
  }
  async function draft() {
    if (!report) return
    const url = outlookDraftUrl(report, teamName)
    // Desktop mail handlers have practical URI limits. Preserve the full report via clipboard for large reports.
    if (url.length > 1800) {
      if (!await copyReport()) return
      window.location.href = 'mailto:' + report.recipients.map(encodeURIComponent).join(';') + '?subject=' +
        encodeURIComponent(`Sprint Deliverables — ${teamName} — ${report.sprint}`)
      setNotice('Draft requested from your default mail app. Paste the copied full report into the body, review, and send.')
    } else {
      window.location.href = url
      setNotice('Draft requested from your default mail app. Review recipients and content before sending.')
    }
  }
  return <section className="deliverables" aria-label="Sprint deliverables">
    <header className="deliverablesHeader"><div><h2>Deliverables</h2><p>What {teamName || 'this team'} actually completed, regardless of the assigned sprint.</p></div>
      <button className="adoSecondaryBtn" disabled={loading} onClick={() => setRefresh(v => ({ scope, version: v.version + 1 }))}><RefreshCw size={14} /> Regenerate report</button></header>
    {loading && <p role="status">Verifying completion history and sprint-end attribution…</p>}
    {error && <p role="alert" className="deliverablesWarning">{error}</p>}
    {!iterationId && <p>Select a team and sprint to generate the report.</p>}
    {report && <>
      <p><strong>{report.sprint}</strong> · {report.start.slice(0, 10)} through {new Date(Date.parse(report.end_exclusive) - 1).toISOString().slice(0, 10)} · UTC{report.provisional && ' · Provisional — sprint has not ended'}</p>
      <div className="deliverablesStats">
        <div><strong>{report.delivered_count}</strong><span>Work items delivered</span></div>
        <div><strong>{report.completed_tasks}</strong><span>Completed tasks</span></div>
        <div><strong>{report.recorded_hours} h</strong><span>Recorded task effort</span></div>
        <div><strong>{report.cross_iteration_count}</strong><span>Different assigned iteration</span></div>
      </div>
      <details className="deliverablesRules" open><summary>How this report is calculated</summary>
        <p>Completion determines the period. Ownership and assigned iteration come from the completion revision; effort and completed status are checked at sprint end. Re-completed items and items reopened within the sprint appear for context and are excluded from delivery totals.</p>
        {report.warnings.map(w => <p key={w}>{w}</p>)}
        <p>Available capacity uses configured daily hours and team working days minus individual and team days off. It is separate from recorded effort. {report.missing_effort_count} completed task(s) have missing effort; zero is a valid recorded value.</p>
      </details>
      <p role="status">{report.from_snapshot ? 'Loaded saved snapshot.' : report.snapshot_saved ? 'Report saved.' : 'Report has not been saved; persistent storage needs configuration.'}</p>
      <div className="deliverablesActions">
        <label>Work item type <select value={itemType} onChange={e => setItemType(e.target.value)}><option value="all">All types</option><option value="user story">User Stories</option><option value="bug">Bugs</option><option value="task">Tasks</option></select></label>
        <label>Person <select value={personId} onChange={e => setPersonId(e.target.value)}><option value="all">All people</option>{report.people.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <input aria-label="Search deliverables" placeholder="Search title or work item ID" value={query} onChange={e => setQuery(e.target.value)} />
        <button className="adoSecondaryBtn" onClick={copyReport}><Copy size={14} /> Copy Email Report</button>
        <button className="adoSecondaryBtn" onClick={() => setPreview(v => !v)}>Report Preview</button>
        <button className="adoPrimaryBtn" disabled={!report.recipients_verified || !report.recipients.length} onClick={draft}><Mail size={14} /> Open Outlook Draft</button>
      </div>
      <p className="deliverablesRecipients"><strong>To:</strong> {report.recipients.join('; ') || 'No verified team email addresses.'}</p>
      {report.missing_recipient_names.length > 0 && <p className="deliverablesWarning">Missing email addresses: {report.missing_recipient_names.join(', ')}. These individuals will be omitted from the draft until their addresses are configured.</p>}
      <p className="deliverablesHint">Opens the computer's default mail app. Set Outlook as the default to use Outlook. Copy and email list only user stories and bugs for the full team. Task effort remains in the summary; tasks are not listed.</p>
      {notice && <p role="status">{notice}</p>}
      {preview && <textarea className="deliverablesPreview" readOnly aria-label="Full report preview" value={buildDeliverablesText(report, teamName, true)} />}
      {report.people.filter(p => personId === 'all' || p.id === personId).map(person => {
        const items = person.items.filter(i => (itemType === 'all' || i.type.toLowerCase() === itemType)).filter(i => `${i.id} ${i.title}`.toLowerCase().includes(query.toLowerCase()))
        return <article className="deliverablesPerson" key={person.id}><h3>{person.name}</h3>
          <p>{person.delivered_count} work items · {person.completed_tasks} tasks · Recorded effort: {person.recorded_hours} h · Available capacity: {person.available_hours == null ? 'Unavailable' : `${person.available_hours} h`} · Missing effort: {person.missing_effort_count}</p>
          {person.capacity_breakdown && <details><summary>Capacity calculation and source</summary><p>{person.capacity_breakdown.daily_hours ?? 'unknown'} h/day × {person.capacity_breakdown.available_days ?? 'unknown'} available days = {person.available_hours ?? 'unknown'} h</p><p>{person.capacity_breakdown.working_days_before_leave ?? 'Unknown'} configured working days before leave; {person.capacity_breakdown.days_off_on_working_days ?? 'unknown'} working days off.</p><p>{person.capacity_breakdown.source}</p><p>Working days: {person.capacity_breakdown.working_days.join(', ')}</p><p>Individual days off: {person.capacity_breakdown.individual_days_off.map(d => `${d.start.slice(0,10)} – ${d.end.slice(0,10)}`).join('; ') || 'None recorded'}</p><p>Team days off: {person.capacity_breakdown.team_days_off.map(d => `${d.start.slice(0,10)} – ${d.end.slice(0,10)}`).join('; ') || 'None recorded'}</p></details>}
          {items.length ? <div className="deliverablesTableWrap"><table><thead><tr><th>Work item</th><th>Completed (UTC)</th><th>Assigned iteration</th><th>Recorded effort</th><th>Status</th></tr></thead><tbody>
            {items.map(i => <tr key={i.id}><td><a href={i.web_url} target="_blank" rel="noreferrer">#{i.id}</a> {i.title}<small>{i.type}{i.parent_id && ` · Parent #${i.parent_id}`}</small></td>
              <td>{i.completed_at.slice(0, 10)}</td><td>{i.iteration_path}{i.cross_iteration && <small>Completed in a different assigned iteration</small>}</td>
              <td>{i.recorded_hours == null ? 'Not recorded' : `${i.recorded_hours} h`}</td><td>{i.status.replaceAll('_', ' ')}{i.reopened_after_period && <small>Reopened after sprint end</small>}{i.completion_events_in_period > 1 && <small>Multiple completion events; counted once</small>}</td></tr>)}
          </tbody></table></div> : <p>No matching completion events.</p>}
        </article>
      })}
      {report.people.length === 0 && <p>No completion events or team members found.</p>}
      <p className="deliverablesHint">Generated {new Date(report.generated_at).toLocaleString()}.</p>
    </>}
  </section>
}
