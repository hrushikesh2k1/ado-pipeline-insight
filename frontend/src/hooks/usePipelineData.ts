import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {api} from '../services/api'
export const useOptions=()=>useQuery({queryKey:['options'],queryFn:api.options,staleTime:60_000})
export const useSummary=(pipelineId:number|null,days:number)=>useQuery({queryKey:['summary',pipelineId,days],queryFn:()=>api.summary(pipelineId,days),staleTime:30_000})
export const useTrends=(pipelineId:number|null,days:number)=>useQuery({queryKey:['trends',pipelineId,days],queryFn:()=>api.trends(pipelineId,days),staleTime:30_000})
export const useRuns=(pipelineId:number|null)=>useQuery({queryKey:['runs',pipelineId],queryFn:()=>api.runs(pipelineId),staleTime:15_000})
export const useRunAnalysis=(runId:number|null)=>useQuery({queryKey:['run-analysis',runId],queryFn:()=>api.runAnalysis(runId as number),enabled:runId!==null,staleTime:60_000})
export const useRecommendations=(pipelineId:number|null)=>useQuery({queryKey:['recommendations',pipelineId],queryFn:()=>api.recommendations(pipelineId as number),enabled:pipelineId!==null,staleTime:30_000})

export const useConnectAdo=()=>useMutation({mutationFn:({organization}:{organization:string})=>api.connectAdo(organization)})
export const useIngestAdo=()=>{ const qc=useQueryClient(); return useMutation({mutationFn:({organization,project,pipelineId,days}:{organization:string;project:string;pipelineId:number;days:number})=>api.ingestAdo(organization,project,pipelineId,days),onSuccess:()=>{ qc.invalidateQueries({queryKey:['options']}); qc.invalidateQueries({queryKey:['summary']}); qc.invalidateQueries({queryKey:['trends']}); qc.invalidateQueries({queryKey:['runs']}); qc.invalidateQueries({queryKey:['recommendations']}) }}) }


export const useAnalyze=(pipelineId:number|null)=>{ const qc=useQueryClient(); return useMutation({mutationFn:(months:number)=>api.analyze(pipelineId as number,months),onSuccess:(data)=>{ qc.setQueryData(['recommendations',pipelineId],data); qc.invalidateQueries({queryKey:['recommendations',pipelineId]}) }}) }
