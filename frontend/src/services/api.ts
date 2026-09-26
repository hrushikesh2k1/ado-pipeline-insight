import type { Options, Recommendation, Runs, Summary, Trends, RunAnalysis, AdoConnection } from '../types/api'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
async function request<T>(path:string, init?:RequestInit):Promise<T>{
  const response = await fetch(`${API_BASE}${path}`, {headers:{'Accept':'application/json',...(init?.headers||{})}, ...init})
  if(!response.ok){let detail='Request failed'; try{const body=await response.json(); detail=body.detail||body.error||detail}catch{} throw new Error(`${response.status}: ${detail}`)}
  return response.json()
}
export const api = {
  options:()=>request<Options>('/api/v1/options'),
  summary:(pipelineId:number|null,days:number)=>request<Summary>(`/api/v1/summary?days=${days}${pipelineId?`&pipeline_id=${pipelineId}`:''}`),
  trends:(pipelineId:number|null,days:number)=>request<Trends>(`/api/v1/trends?days=${days}${pipelineId?`&pipeline_id=${pipelineId}`:''}`),
  runs:(pipelineId:number|null,days?:number,page=1,pageSize=500)=>request<Runs>(`/api/v1/runs?page=${page}&page_size=${pageSize}${pipelineId?`&pipeline_id=${pipelineId}`:''}${days?`&days=${days}`:''}`),
  recommendations:(pipelineId:number)=>request<{pipeline_id:number;findings:Recommendation[]}>(`/api/v1/pipelines/${pipelineId}/recommendations`),
  runAnalysis:(runId:number)=>request<RunAnalysis>(`/api/v1/runs/${runId}/analysis`),
  connectAdo:(organization:string,pat:string)=>request<AdoConnection>('/api/v1/ado/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({organization,pat})}),
  ingestAdo:(organization:string,pat:string,project:string,pipelineId:number,days:number)=>request<any>('/api/v1/ado/ingest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({organization,pat,project,pipeline_id:pipelineId,days})}),
  ingestStatus:(organization?:string,pipelineId?:number|null)=>{
    const p = new URLSearchParams()
    if (organization) p.set('organization', organization)
    if (pipelineId) p.set('pipeline_id', String(pipelineId))
    const qs = p.toString() ? `?${p.toString()}` : ''
    return request<{status:'idle'|'running'|'completed'|'failed';organization?:string;project?:string;pipeline_id?:number;pipeline_name?:string;processed_runs:number;total_runs:number|null;current_run_date?:string|null;records_upserted:number;error?:string|null}>(`/api/v1/ado/ingest/status${qs}`)
  },
  analyze:(pipelineId:number,months:number)=>request<{pipeline_id:number;findings:Recommendation[];message?:string}>(`/api/v1/pipelines/${pipelineId}/analyze`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({months})}),
}
