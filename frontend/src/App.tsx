import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import ReactECharts from 'echarts-for-react'
import { Activity, AlertTriangle, BrainCircuit, CheckCircle2, ChevronDown, Clock3, Database, RefreshCw, Server, TriangleAlert, X } from 'lucide-react'
import { useAnalyze, useConnectAdo, useIngestAdo, useOptions, useRecommendations, useRunAnalysis, useRuns, useSummary, useTrends } from './hooks/usePipelineData'
import { formatSeconds as fmt } from './utils'

const WINDOWS = [{ label: 'Last 1 Month', days: 30 }, { label: 'Last 3 Months', days: 90 }, { label: 'Last 6 Months', days: 180 }, { label: 'Last 1 Year', days: 365 }]

function App() {
  const [org, setOrg] = useState('')
  const [adoOrg, setAdoOrg] = useState('')
  const [adoConnected, setAdoConnected] = useState(false)
  const [adoProjects, setAdoProjects] = useState<{ id: string; name: string }[]>([])
  const [adoPipelines, setAdoPipelines] = useState<{ id: number; name: string; project_name: string | null }[]>([])
  const [ingestDays, setIngestDays] = useState(90)
  const [project, setProject] = useState('')
  const [pipelineId, setPipelineId] = useState<number | null>(null)
  const [days, setDays] = useState(90)
  const [selectedRun, setSelectedRun] = useState<number | null>(null)
  const [ingestResult, setIngestResult] = useState<string | null>(null)

  const options = useOptions()
  const connectAdo = useConnectAdo()
  const ingestAdo = useIngestAdo()
  const pipelines = options.data?.pipelines ?? []
  const orgs = options.data?.organizations ?? []
  const projects = useMemo(() => Array.from(new Set(pipelines.filter(p => !org || p.organization_name === org).map(p => p.project_name).filter(Boolean) as string[])), [pipelines, org])
  const filtered = useMemo(() => pipelines.filter(p => (!org || p.organization_name === org) && (!project || p.project_name === project)), [pipelines, org, project])
  const summary = useSummary(pipelineId, days)
  const trends = useTrends(pipelineId, days)
  const runs = useRuns(pipelineId)
  const recs = useRecommendations(pipelineId)
  const analyze = useAnalyze(pipelineId)
  const detail = useRunAnalysis(selectedRun)
  const loading = summary.isFetching || trends.isFetching
  const displayFindings = analyze.data?.findings?.length ? analyze.data.findings : (recs.data?.findings ?? [])
  const discoveredPipelines = adoPipelines.filter(p => p.project_name === project)
  const chartOption = {
    tooltip: { trigger: 'axis' }, legend: { textStyle: { color: '#a1a1aa' } }, grid: { left: 45, right: 20, top: 35, bottom: 35 },
    xAxis: { type: 'category', data: (trends.data?.daily_trend ?? []).map(x => x.run_date), axisLabel: { color: '#71717a' } },
    yAxis: { type: 'value', axisLabel: { color: '#71717a' } },
    series: [
      { name: 'Average duration', type: 'line', smooth: true, data: (trends.data?.daily_trend ?? []).map(x => Math.round(x.avg_duration_seconds || 0)) },
      { name: 'P90 duration', type: 'line', smooth: true, data: (trends.data?.daily_trend ?? []).map(x => Math.round(x.p90_duration_seconds || 0)) },
    ],
  }
  const stageOption = {
    tooltip: { trigger: 'axis' }, grid: { left: 45, right: 20, top: 20, bottom: 55 },
    xAxis: { type: 'category', data: (summary.data?.stages ?? []).slice(0, 10).map(x => x.stage_name), axisLabel: { color: '#a1a1aa', rotate: 25 } },
    yAxis: { type: 'value', axisLabel: { color: '#71717a' } },
    series: [{ type: 'bar', data: (summary.data?.stages ?? []).slice(0, 10).map(x => Math.round(x.avg_duration_seconds || 0)) }],
  }

  return <div className="app">
    <header><div className="brand"><div className="logo">ϟ</div><div><h1>ADO Pipeline Insight</h1><p>Pipeline Performance & AI Duration Optimizer</p></div><span className="enterprise">ENTERPRISE</span></div><div className="controls"><Select label="Org" value={org} options={orgs} placeholder="All Organizations" onChange={v => { setOrg(v); setProject(''); setPipelineId(null) }} /><Select label="Project" value={project} options={projects} placeholder="All Projects" onChange={v => { setProject(v); setPipelineId(null) }} /><Select label="Pipeline" value={pipelineId?.toString() ?? ''} options={filtered.map(p => p.pipeline_id.toString())} labels={Object.fromEntries(filtered.map(p => [p.pipeline_id.toString(), p.pipeline_name]))} placeholder="All Pipelines" onChange={v => setPipelineId(v ? Number(v) : null)} /><Select label="Window" value={days.toString()} options={WINDOWS.map(w => w.days.toString())} labels={Object.fromEntries(WINDOWS.map(w => [w.days.toString(), w.label]))} onChange={v => setDays(Number(v))} /></div><div className="status"><span className={`dot ${options.isError ? 'bad' : ''}`} />{options.isError ? 'ERROR' : 'CONNECTED'}</div></header>
    <main>
      <section className="connectPanel"><div><h2>Connect Azure DevOps</h2><p>Connect once, discover projects and pipelines, then let the Azure Function ingest the selected pipeline history into Azure SQL.</p></div><div className="connectForm"><input aria-label="Azure DevOps organization" placeholder="Organization" value={adoOrg} onChange={e => setAdoOrg(e.target.value)} /><button onClick={() => connectAdo.mutate({ organization: adoOrg }, { onSuccess: data => { setAdoConnected(true); setAdoOrg(data.organization); setOrg(data.organization); setAdoProjects(data.projects); setAdoPipelines(data.pipelines) } })} disabled={!adoOrg || connectAdo.isPending}>{connectAdo.isPending ? 'Connecting...' : 'Connect & Discover'}</button></div>{connectAdo.isError && <div className="connectError">{connectAdo.error instanceof Error ? connectAdo.error.message : 'Azure DevOps connection failed.'}</div>}{adoConnected && <div className="discoveryRow"><Select label="ADO Project" value={project} options={adoProjects.map(p => p.name)} placeholder="Select Project" onChange={v => { setProject(v); setPipelineId(null) }} /><Select label="ADO Pipeline" value={pipelineId?.toString() ?? ''} options={discoveredPipelines.map(p => p.id.toString())} labels={Object.fromEntries(discoveredPipelines.map(p => [p.id.toString(), p.name]))} placeholder="Select Pipeline" onChange={v => setPipelineId(v ? Number(v) : null)} /><Select label="History" value={ingestDays.toString()} options={['30', '90', '180', '365']} labels={{ '30': '30 days', '90': '90 days', '180': '180 days', '365': '1 year' }} onChange={v => setIngestDays(Number(v))} /><button className="ingestButton" disabled={!project || !pipelineId || ingestAdo.isPending} onClick={() => pipelineId && ingestAdo.mutate({ organization: adoOrg, project, pipelineId, days: ingestDays }, { onSuccess: data => setIngestResult(`${data.runs_ingested ?? 0} runs ingested`) })}>{ingestAdo.isPending ? 'Ingesting...' : 'Ingest History'}</button>{ingestResult && <span className="ingestResult">{ingestResult}</span>}</div>}</section>
      {ingestAdo.isError && <ErrorBox message={ingestAdo.error instanceof Error ? ingestAdo.error.message : 'Ingestion failed.'} />}
      {(summary.data?.degraded_runs ?? 0) > 0 && <div className="qualityWarning">{summary.data?.degraded_runs} run(s) contain degraded telemetry. Re-ingest the selected pipeline to replace fallback data with the actual Azure DevOps timeline.</div>}
      <section className="cards"><Metric icon={<Activity />} label="Completed Runs" value={summary.data?.total_runs} suffix="runs" sub={loading ? 'Refreshing' : 'Historical telemetry'} /><Metric icon={<CheckCircle2 />} label="Successful Runs" value={summary.data?.successful_runs} suffix="runs" sub={`Pass rate ${summary.data?.success_rate_pct ?? 0}%`} /><Metric icon={<Clock3 />} label="Build Average Duration" value={summary.data?.average_duration_seconds != null ? fmt(summary.data.average_duration_seconds) : undefined} sub={`P90 ${fmt(summary.data?.p90_duration_seconds ?? null)}`} /><Metric icon={<AlertTriangle />} label="Failed Runs" value={summary.data?.failed_runs} suffix="runs" sub={`Failure rate ${summary.data?.failure_rate_pct ?? 0}%`} /></section>
      <section className="insightStrip"><Metric icon={<Clock3 />} label="Average Queue Time" value={summary.data?.average_queue_seconds != null ? fmt(summary.data.average_queue_seconds) : undefined} sub="Time waiting for an agent" /><Metric icon={<Server />} label="Top Bottleneck" value={summary.data?.stages?.[0]?.stage_name} sub={summary.data?.stages?.[0] ? `${fmt(summary.data.stages[0].avg_duration_seconds)} average` : 'No stage telemetry'} /></section>
      <section className="grid2"><Panel title="Build Duration Trend" icon={<Activity size={16} />}><ReactECharts option={chartOption} style={{ height: 310 }} notMerge /></Panel><Panel title="Stage Average Duration" icon={<Server size={16} />}><ReactECharts option={stageOption} style={{ height: 310 }} notMerge /></Panel></section>
      <section className="grid2"><Panel title="AI Optimization Recommendations" icon={<BrainCircuit size={16} />}><div className="aiToolbar"><button disabled={!pipelineId || analyze.isPending} onClick={() => pipelineId && analyze.mutate(Math.max(1, Math.round(days / 31)))}>{analyze.isPending ? <RefreshCw className="spin" size={13} /> : <BrainCircuit size={13} />} {analyze.isPending ? 'Analyzing' : 'Run AI Analysis'}</button></div><div className="findings">{pipelineId === null ? <Empty text="Select a pipeline to view AI findings." /> : analyze.isError ? <ErrorBox message={analyze.error instanceof Error ? analyze.error.message : 'AI analysis failed.'} /> : analyze.isPending ? <Empty text="Analyzing pipeline telemetry..." /> : displayFindings.length ? displayFindings.slice(0, 6).map((f, i) => <div className="finding" key={f.id ?? i}><div className={`severity ${f.severity}`}>{f.severity.toUpperCase()}</div><div><b>{f.stage_name}{f.task_name ? ` / ${f.task_name}` : ''}</b><p>{f.recommendation}</p><small>{f.evidence}</small></div></div>) : analyze.data?.message ? <Empty text={analyze.data.message} /> : recs.isLoading ? <Empty text="Loading recommendations..." /> : <Empty text="No optimization findings detected." />}</div></Panel>
      <Panel title="Recent Runs" icon={<Database size={16} />}><div className="runs">{(runs.data?.items ?? []).slice(0, 8).map(r => <button className="run runButton" key={r.run_id} onClick={() => setSelectedRun(r.run_id)}><div><b>#{r.build_number || r.run_id}</b><span>{r.pipeline_name}</span><small>{r.source_branch || 'main'} · {fmt(r.duration_seconds)}</small></div><span className={`result ${(r.result || '').toLowerCase()}`}>{r.result || 'unknown'}</span></button>)}{!runs.isLoading && !runs.data?.items.length && <Empty text="No runs found for the selected filter." />}</div></Panel></section>
      <section className="footerInfo"><TriangleAlert size={15} /> Analytics are deterministic. AI recommendations are generated from measured pipeline, stage, job and task telemetry.</section>
    </main>
    {selectedRun !== null && <RunDrawer analysis={detail.data} loading={detail.isLoading} error={detail.error instanceof Error ? detail.error.message : null} onClose={() => setSelectedRun(null)} />}
  </div>
}

function RunDrawer({ analysis, loading, error, onClose }: { analysis: any; loading: boolean; error: string | null; onClose: () => void }) { const metrics = analysis?.metrics; return <div className="drawerBackdrop" onClick={onClose}><aside className="drawer" onClick={e => e.stopPropagation()}><div className="drawerHead"><div><h2>Run #{analysis?.run?.run_id ?? '...'}</h2><p>{analysis?.run?.pipeline_name ?? 'Pipeline run analysis'}</p></div><button className="close" onClick={onClose}><X size={18} /></button></div>{loading ? <Empty text="Loading execution telemetry..." /> : error ? <ErrorBox message={error} /> : analysis && <><div className="detailCards"><Mini label="Run duration" value={fmt(metrics.run_duration_seconds)} /><Mini label="Queue time" value={fmt(metrics.queue_seconds)} /><Mini label="Jobs" value={metrics.job_count} /><Mini label="Tasks" value={metrics.task_count} /></div><div className="insightBox"><b>Execution bottlenecks</b><p>Result: {analysis.run.result || 'unknown'} · Data quality: {analysis.run.data_quality}</p><p>Longest stage: {metrics.longest_stage?.stage_name ?? 'N/A'} · {fmt(metrics.longest_stage?.duration_seconds ?? null)}</p><p>Longest job: {metrics.longest_job?.job_name ?? 'N/A'} · {fmt(metrics.longest_job?.duration_seconds ?? null)}</p><p>Longest task: {metrics.longest_task?.task_name ?? 'N/A'} · {fmt(metrics.longest_task?.duration_seconds ?? null)}</p>{metrics.failed_records > 0 && <p className="failureText">Failed records detected: {metrics.failed_records}</p>}</div><Hierarchy title="Stages" rows={analysis.stages} nameKey="stage_name" /><Hierarchy title="Jobs" rows={analysis.jobs} nameKey="job_name" /><Hierarchy title="Tasks" rows={analysis.tasks} nameKey="task_name" /></>}</aside></div> }
function Hierarchy({ title, rows, nameKey }: { title: string; rows: any[]; nameKey: string }) { return <section className="hierarchy"><h3>{title} <small>{rows.length}</small></h3>{rows.length === 0 ? <Empty text={`No ${title.toLowerCase()} captured.`} /> : rows.map((r, i) => <div className="hierarchyRow" key={r.id ?? i}><div><b>{r[nameKey] ?? 'Unnamed'}</b><small>{r.stage_name && nameKey !== 'stage_name' ? r.stage_name : ''}{r.job_name && nameKey === 'task_name' ? ` / ${r.job_name}` : ''} · retries {r.retry_count ?? 0}</small></div><div><strong>{fmt(r.duration_seconds)}</strong><span className={`result ${(r.result || '').toLowerCase()}`}>{r.result || 'unknown'}</span></div></div>)}</section> }
function Select({ label, value, options, labels, placeholder, onChange }: { label: string; value: string; options: string[]; labels?: Record<string, string>; placeholder?: string; onChange: (v: string) => void }) { return <label className="select"><span>{label}:</span><select value={value} onChange={e => onChange(e.target.value)}><option value="">{placeholder ?? 'Select'}</option>{options.map(v => <option value={v} key={v}>{labels?.[v] ?? v}</option>)}</select><ChevronDown size={14} /></label> }
function Metric({ icon, label, value, suffix, sub }: { icon: ReactNode; label: string; value: number | string | undefined; suffix?: string; sub: string }) { return <div className="metric"><div className="metricIcon">{icon}</div><div><div className="metricLabel">{label}</div><div className="metricValue">{value == null ? '...' : value} {suffix && <small>{suffix}</small>}</div><div className="metricSub">{sub}</div></div></div> }
function Mini({ label, value }: { label: string; value: string | number | null }) { return <div className="mini"><small>{label}</small><b>{value ?? 'N/A'}</b></div> }
function Panel({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) { return <div className="panel"><div className="panelHead"><div>{icon}<h3>{title}</h3></div></div>{children}</div> }
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div> }
function ErrorBox({ message }: { message: string }) { return <div className="errorBox"><TriangleAlert size={16} /><div><b>Backend connection issue</b><p>{message}</p></div></div> }
export default App
