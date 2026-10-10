// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DeliverablesPage } from './DeliverablesPage'
import { api } from '../services/api'
import type { DeliverablesReport } from '../utils/deliverablesReport'

vi.mock('../services/api', () => ({ api: { deliverables: vi.fn() } }))
const report: DeliverablesReport = {
  team: 'team', sprint: 'September', iteration_path: 'Cloud\\September', start: '2026-09-01T00:00:00Z',
  end_exclusive: '2026-10-01T00:00:00Z', generated_at: '2026-10-02T00:00:00Z', provisional: false,
  delivered_count: 1, completed_tasks: 1, recorded_hours: 8, missing_effort_count: 0,
  cross_iteration_count: 1, recipients: ['alice@example.com'], missing_recipient_names: [], recipients_verified: true,
  warnings: [], people: [{ id: 'alice', name: 'Alice', email: 'alice@example.com', available_hours: 160,
    delivered_count: 1, completed_tasks: 1, recorded_hours: 8, missing_effort_count: 0,
    items: [{ id: 42, title: 'August carryover', type: 'User Story', completed_at: '2026-09-15T09:00:00Z',
      iteration_path: 'Cloud\\August', cross_iteration: true, parent_id: 43, recorded_hours: 8,
      status: 'delivered', reopened_after_period: false, completion_events_in_period: 1,
      web_url: 'https://dev.azure.com/org/Cloud/_workitems/edit/42' }] }],
}
let root: Root
let host: HTMLDivElement
const props = { organization: 'org', project: 'Cloud', team: 'team', teamName: 'CloudOps-Monitoring', iterationId: 'sept' }
async function render() { await act(async () => { root.render(<DeliverablesPage {...props} />) }) }
function button(text: string) { return Array.from(host.querySelectorAll('button')).find(b => b.textContent?.includes(text))! }
beforeEach(() => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  vi.mocked(api.deliverables).mockResolvedValue(report)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } })
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.clearAllMocks() })
describe('Deliverables page', () => {
  it('renders carryovers, contributor and capacity with verified recipients', async () => {
    await render()
    expect(host.textContent).toContain('August carryover')
    expect(host.textContent).toContain('Available capacity: 160 h')
    expect(host.textContent).toContain('alice@example.com')
    expect(button('Open Outlook Draft').disabled).toBe(false)
    expect(host.querySelector('a')?.href).toContain('/edit/42')
  })
  it('copies the full team report and offers preview on clipboard failure', async () => {
    await render()
    await act(async () => button('Copy Email Report').click())
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('August carryover'))
    vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new Error('denied'))
    await act(async () => button('Copy Email Report').click())
    expect(host.querySelector('textarea')?.value).toContain('August carryover')
    expect(host.textContent).toContain('Clipboard access is unavailable')
  })
  it('allows verified available addresses while flagging omitted individuals', async () => {
    vi.mocked(api.deliverables).mockResolvedValue({ ...report, missing_recipient_names: ['Bob'] })
    await render()
    expect(button('Open Outlook Draft').disabled).toBe(false)
    expect(host.textContent).toContain('Missing email addresses: Bob')
  })
  it('shows a fetch error without invented report totals', async () => {
    vi.mocked(api.deliverables).mockRejectedValue(new Error('No partial report was generated'))
    await render()
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('No partial report')
    expect(host.querySelector('.deliverablesStats')).toBeNull()
  })
  it('refreshes data from Azure DevOps', async () => {
    await render()
    await act(async () => button('Regenerate report').click())
    expect(api.deliverables).toHaveBeenCalledTimes(2)
  })
})

it('filters task rows without removing stories from the full email report', async () => {
  vi.mocked(api.deliverables).mockResolvedValue({ ...report, people: [{ ...report.people[0], items: [
    ...report.people[0].items, { ...report.people[0].items[0], id:77, type:'Task', title:'Child implementation task' },
  ] }] })
  await render()
  const select=host.querySelector('.deliverablesActions select') as HTMLSelectElement
  await act(async()=>{select.value='task';select.dispatchEvent(new Event('change',{bubbles:true}))})
  expect(host.textContent).toContain('Child implementation task')
  expect(host.textContent).not.toContain('August carryover')
  await act(async()=>button('Copy Email Report').click())
  const copied=vi.mocked(navigator.clipboard.writeText).mock.calls[0][0]
  expect(copied).toContain('August carryover')
  expect(copied).not.toContain('Child implementation task')
})
it('keeps the last successful report visible if regeneration fails', async () => {
  await render()
  vi.mocked(api.deliverables).mockRejectedValue(new Error('Regeneration failed'))
  await act(async()=>button('Regenerate report').click())
  expect(host.textContent).toContain('August carryover')
  expect(host.querySelector('[role=alert]')?.textContent).toContain('Regeneration failed')
  expect(api.deliverables).toHaveBeenLastCalledWith('org','Cloud','team','sept',undefined,true)
})
