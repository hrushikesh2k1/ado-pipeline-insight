import type { Options, Recommendation, Runs, Summary, Trends, RunAnalysis, AdoConnection, UserProfile, AdoRepository, AdoPullRequest, PullRequestReviewResponse, AdoTeam, AdoIteration, AdoSprintBoardResponse, MilestoneAiSummaryResponse, ReleaseBranchCandidate, ReleaseDefinition, ReleaseDefinitionCreate, ReleaseScorecard, ReleaseScorecardHistoryItem } from '../types/api'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
async function request<T>(path:string, init?:RequestInit):Promise<T>{
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'same-origin',
    headers: {'Accept':'application/json', ...(init?.headers||{})},
    ...init
  })
  if(!response.ok){
    let detail = 'Request failed'
    try {
      const text = await response.text()
      try {
        const body = JSON.parse(text)
        detail = body.detail || body.error || detail
      } catch {
        const titleMatch = text.match(/<title>([^<]+)<\/title>/i)
        if (titleMatch) {
          detail = titleMatch[1].trim()
        } else if (text && text.length < 200) {
          detail = text.trim()
        }
      }
    } catch {}
    if(response.status === 401 && !path.startsWith('/api/v1/auth/') && detail.toLowerCase().includes('authentication required')){
      window.dispatchEvent(new Event('auth-expired'))
    }
    throw new Error(`${response.status}: ${detail}`)
  }
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
  repositories:(organization:string,project:string,pat?:string)=>{
    const p = new URLSearchParams({ organization, project })
    if (pat) p.set('pat', pat)
    return request<AdoRepository[]>(`/api/v1/ado/repositories?${p.toString()}`)
  },
  pullRequests:(organization:string,project:string,repositoryId:string,pat?:string,status='active')=>{
    const p = new URLSearchParams({ organization, project, repository_id: repositoryId, status })
    if (pat) p.set('pat', pat)
    return request<AdoPullRequest[]>(`/api/v1/ado/pullrequests?${p.toString()}`)
  },
  reviewPullRequest:(payload:{organization:string;project:string;repository_id:string;pull_request_id:number;pat?:string})=>{
    return request<PullRequestReviewResponse>('/api/v1/ado/pullrequests/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
  },
  teams:(organization:string,project:string,pat?:string)=>{
    const p = new URLSearchParams({ organization, project })
    if (pat) p.set('pat', pat)
    return request<AdoTeam[]>(`/api/v1/ado/teams?${p.toString()}`)
  },
  sprints:(organization:string,project:string,teamId:string,pat?:string)=>{
    const p = new URLSearchParams({ organization, project, team: teamId, team_id: teamId })
    if (pat) p.set('pat', pat)
    return request<AdoIteration[]>(`/api/v1/ado/sprints?${p.toString()}`)
  },
  sprintBoard:(organization:string,project:string,teamId:string,iterationId?:string,pat?:string)=>{
    const p = new URLSearchParams({ organization, project, team: teamId, team_id: teamId })
    if (iterationId) p.set('iteration_id', iterationId)
    if (pat) p.set('pat', pat)
    return request<AdoSprintBoardResponse>(`/api/v1/ado/sprints/board?${p.toString()}`)
  },
  milestoneAiSummary:(payload:{sprint_name?:string;team_name?:string;achieved_items:any[];total_stories:number;closed_stories_count:number;total_delivered_hours:number})=>{
    return request<MilestoneAiSummaryResponse>('/api/v1/sprint-board/milestone-ai-summary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
  },
  version: () => request<{ version: string; git_commit?: string; git_branch?: string; build_timestamp?: string | null }>('/api/v1/version'),
  login: (username: string, password: string) => request<UserProfile>('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  }),
  logout: () => request<{ authenticated: boolean }>('/api/v1/auth/logout', { method: 'POST' }),
  me: async (): Promise<UserProfile> => {
    const signedOut: UserProfile = { authenticated: false, loginRequired: true, userId: null, email: null, name: null, provider: null }
    let backend: UserProfile = signedOut
    try {
      backend = await request<UserProfile>('/api/v1/auth/me')
      if (backend.authenticated) return backend
    } catch {}

    if (backend.loginRequired !== false) {
      return backend
    }

    try {
      const res = await fetch('/.auth/me', { headers: { Accept: 'application/json' } })
      if (res.ok) {
        const list = await res.json()
        if (Array.isArray(list) && list.length > 0) {
          const item = list[0]
          const claims: Array<{ typ: string; val: string }> = item.user_claims || []
          const nameClaim = claims.find(c => c.typ === 'name' || c.typ.endsWith('/name'))?.val
          const emailClaim = claims.find(c => c.typ === 'preferred_username' || c.typ === 'email' || c.typ.endsWith('/emailaddress'))?.val
          return {
            authenticated: true,
            userId: item.user_id || null,
            email: emailClaim || item.user_id || null,
            name: nameClaim || item.user_id || 'User',
            provider: item.provider_name === 'aad' ? 'Microsoft Entra ID' : (item.provider_name || 'Microsoft Entra ID'),
          }
        }
      }
    } catch {}
    return backend
  },
  releaseBranchCandidates: (organization: string, project: string, repositoryId?: string, pipelineId?: number, pat?: string) => {
    const p = new URLSearchParams({ organization, project })
    if (repositoryId) p.set('repository_id', repositoryId)
    if (pipelineId) p.set('pipeline_id', String(pipelineId))
    if (pat) p.set('pat', pat)
    return request<ReleaseBranchCandidate[]>(`/api/v1/releases/branch-candidates?${p.toString()}`)
  },
  createRelease: (payload: ReleaseDefinitionCreate) => {
    return request<ReleaseDefinition>('/api/v1/releases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },
  listReleases: (organization: string, project: string) => {
    const p = new URLSearchParams({ organization, project })
    return request<ReleaseDefinition[]>(`/api/v1/releases?${p.toString()}`)
  },
  getReleaseScorecard: (releaseId: string, pat?: string) => {
    const p = new URLSearchParams()
    if (pat) p.set('pat', pat)
    const qs = p.toString() ? `?${p.toString()}` : ''
    return request<ReleaseScorecard>(`/api/v1/releases/${releaseId}${qs}`)
  },
  deleteRelease: (releaseId: string) => {
    return request<{ success: boolean; release_id: string; message: string }>(`/api/v1/releases/${releaseId}`, {
      method: 'DELETE',
    })
  },
  getReleaseHistory: (releaseId: string, limit = 20) => {
    return request<ReleaseScorecardHistoryItem[]>(`/api/v1/releases/${releaseId}/history?limit=${limit}`)
  },
}

