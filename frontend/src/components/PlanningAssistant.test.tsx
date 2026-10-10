// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PlanningAssistant, PlanningResponseForm } from './PlanningAssistant'
let root: Root
let host: HTMLDivElement
const settings = { planning_day:7, reminder_days:[1,3,5], period:'current', leave_recipients:['alice'], lead_emails:['lead@example.com'], leave_automatic:false, priorities_automatic:false }
const data = { settings, members:[{id:'alice',name:'Alice',email:'alice@example.com'}], responses:{}, proposal:null }
const props = { organization:'org', project:'Project', team:'monitoring', teamName:'CloudOps-Monitoring', iterationId:'sept' }
let submissions: any[]
const click = (text:string) => Array.from(host.querySelectorAll('button')).find(b=>b.textContent?.includes(text))!.click()
beforeEach(() => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  host=document.createElement('div'); document.body.append(host); root=createRoot(host); submissions=[]
  vi.stubGlobal('fetch',vi.fn(async (url:string,init?:RequestInit) => {
    if (url.includes('/draft?')) return Response.json({to:['hrushikeshboora@gmail.com'],intended_person:'Alice',token:'test-link',sprint:'September',kind:'leave',test_mode:true})
    if (url.includes('/settings?')) return Response.json({settings})
    if (url.includes('/response?')) {
      if (init?.method==='POST') {submissions.push(JSON.parse(init.body as string)); return Response.json({saved:true})}
      return Response.json({kind:'leave',person_id:'alice',scope:['org','Project','monitoring','sept'],sprint:'September',existing:null,test_mode:true})
    }
    return Response.json(data)
  }))
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:vi.fn().mockResolvedValue(undefined)}})
})
afterEach(async()=>{await act(async()=>root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.clearAllMocks()})
it('prepares a manual test draft to the approved test email with an app response link',async()=>{
  await act(async()=>root.render(<PlanningAssistant {...props}/>))
  expect(host.textContent).toContain('Awaiting response')
  expect(Array.from(host.querySelectorAll('input[type=checkbox]')).filter((c:any)=>c.disabled)).toHaveLength(2)
  await act(async()=>click('Prepare test reminder'))
  expect(host.textContent).toContain('To: hrushikeshboora@gmail.com')
  expect(host.querySelector('textarea')?.value).toContain('planning_response=test-link')
  await act(async()=>click('Copy Email'))
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('To: hrushikeshboora@gmail.com'))
})
it('captures an explicit no-leave response with the signed-link identity',async()=>{
  await act(async()=>root.render(<PlanningResponseForm token="test-link"/>))
  await act(async()=>{(host.querySelector('input[type=checkbox]') as HTMLInputElement).click()})
  await act(async()=>click('Submit response'))
  expect(submissions).toEqual([{person_id:'alice',no_leave:true,leave:[],priorities:[]}])
  expect(host.textContent).toContain('Response saved')
})
it('shows a save failure instead of claiming the response was saved',async()=>{
  await act(async()=>root.render(<PlanningResponseForm token="test-link"/>))
  vi.mocked(fetch).mockResolvedValueOnce(Response.json({detail:'Storage unavailable'},{status:503}))
  await act(async()=>click('Submit response'))
  expect(host.querySelector('[role=alert]')?.textContent).toContain('Storage unavailable')
  expect(host.textContent).not.toContain('Response saved')
})
