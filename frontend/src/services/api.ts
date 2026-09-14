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
  runs:(pipelineId:number|null,page=1)=>request<Runs>(`/api/v1/runs?page=${page}&page_size=25${pipelineId?`&pipeline_id=${pipelineId}`:''}`),
  recommendations:(pipelineId:number)=>request<{pipeline_id:number;findings:Recommendation[]}>(`/api/v1/pipelines/${pipelineId}/recommendations`),
  runAnalysis:(runId:number)=>request<RunAnalysis>(`/api/v1/runs/${runId}/analysis`),
  connectAdo:(organization:string,pat:string)=>request<AdoConnection>('/api/v1/ado/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({organization,pat})}),
  ingestAdo:(organization:string,project:string,pipelineId:number,pat:string,days:number)=>request<any>('/api/v1/ado/ingest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({organization,project,pipeline_id:pipelineId,pat,days})}),
  analyze:(pipelineId:number,months:number)=>request<{pipeline_id:number;findings:Recommendation[];message?:string}>(`/api/v1/pipelines/${pipelineId}/analyze`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({months})}),
}
