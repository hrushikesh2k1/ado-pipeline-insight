import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import { Activity, AlertTriangle, BrainCircuit, Check, CheckCircle2, ChevronDown, Clock3, Copy, Database, RefreshCw, Server, ShieldAlert, Sparkles, Terminal, TriangleAlert, Wrench, X, Zap } from 'lucide-react'
import { useAnalyze, useConnectAdo, useIngestAdo, useOptions, useRecommendations, useRunAnalysis, useRuns, useSummary, useTrends } from './hooks/usePipelineData'
import { api } from './services/api'
import type { Recommendation } from './types/api'
import { formatSeconds as fmt } from './utils'

const WINDOWS = [{ label: 'Last 1 Month', days: 30 }, { label: 'Last 3 Months', days: 90 }, { label: 'Last 6 Months', days: 180 }, { label: 'Last 1 Year', days: 365 }]

function App() {
  const [org, setOrg] = useState(() => localStorage.getItem('ado_selected_org') || '')
  const [adoOrg, setAdoOrg] = useState(() => localStorage.getItem('ado_connected_org') || '')
  const [adoPat, setAdoPat] = useState(() => sessionStorage.getItem('ado_session_pat') || '')
  const [adoConnected, setAdoConnected] = useState(() => localStorage.getItem('ado_is_connected') === 'true')
  const [adoProjects, setAdoProjects] = useState<{ id: string; name: string }[]>(() => {
    try { return JSON.parse(localStorage.getItem('ado_cached_projects') || '[]') } catch { return [] }
  })
  const [adoPipelines, setAdoPipelines] = useState<{ id: number; name: string; project_name: string | null }[]>(() => {
    try { return JSON.parse(localStorage.getItem('ado_cached_pipelines') || '[]') } catch { return [] }
  })
  const [ingestDays, setIngestDays] = useState(() => Number(localStorage.getItem('ado_ingest_days') || '90'))
  const [project, setProject] = useState(() => localStorage.getItem('ado_selected_project') || '')
  const [pipelineId, setPipelineId] = useState<number | null>(() => {
    const v = localStorage.getItem('ado_selected_pipeline')
    return v ? Number(v) : null
  })
  const [days, setDays] = useState(() => Number(localStorage.getItem('ado_view_days') || '90'))
  const [selectedRun, setSelectedRun] = useState<number | null>(null)
  const [isIngesting, setIsIngesting] = useState(false)
  const [ingestState, setIngestState] = useState<{
    status: 'idle' | 'running' | 'completed' | 'failed'
    pipelineId?: number
    pipelineName?: string
    organization?: string
    project?: string
    processedRuns: number
    totalRuns: number | null
    currentRunDate?: string | null
    recordsUpserted: number
    error?: string | null
  } | null>(null)
  const qc = useQueryClient()

  const updateOrg = (v: string) => {
    setOrg(v)
    localStorage.setItem('ado_selected_org', v)
  }
  const updateProject = (v: string) => {
    setProject(v)
    localStorage.setItem('ado_selected_project', v)
  }
  const updatePipelineId = (v: number | null) => {
    setPipelineId(v)
    if (v != null) localStorage.setItem('ado_selected_pipeline', String(v))
    else localStorage.removeItem('ado_selected_pipeline')
  }
  const updateDays = (v: number) => {
    setDays(v)
    localStorage.setItem('ado_view_days', String(v))
  }
  const updateIngestDays = (v: number) => {
    setIngestDays(v)
    localStorage.setItem('ado_ingest_days', String(v))
  }

  // Check on mount if an ingestion job is already running on the server
  useEffect(() => {
    let active = true
    api.ingestStatus().then(res => {
      if (!active) return
      if (res.status === 'running') {
        setIsIngesting(true)
        setIngestState({
          status: 'running',
          pipelineId: res.pipeline_id,
          pipelineName: res.pipeline_name,
          organization: res.organization,
          project: res.project,
          processedRuns: res.processed_runs,
          totalRuns: res.total_runs,
          currentRunDate: res.current_run_date,
          recordsUpserted: res.records_upserted,
        })
        if (res.pipeline_id && !pipelineId) updatePipelineId(res.pipeline_id)
        if (res.project && !project) updateProject(res.project)
        if (res.organization && !org) updateOrg(res.organization)
      }
    }).catch(() => {})
    return () => { active = false }
  }, [])

  // Poll whenever isIngesting is active
  useEffect(() => {
    if (!isIngesting) return
    const interval = setInterval(async () => {
      try {
        const res = await api.ingestStatus(adoOrg || org, pipelineId || undefined)
        if (res.status === 'running') {
          setIngestState({
            status: 'running',
            pipelineId: res.pipeline_id,
            pipelineName: res.pipeline_name,
            organization: res.organization,
            project: res.project,
            processedRuns: res.processed_runs,
            totalRuns: res.total_runs,
            currentRunDate: res.current_run_date,
            recordsUpserted: res.records_upserted,
          })
          qc.invalidateQueries({ queryKey: ['summary'] })
          qc.invalidateQueries({ queryKey: ['runs'] })
        } else if (res.status === 'completed') {
          setIsIngesting(false)
          setIngestState({
            status: 'completed',
            pipelineId: res.pipeline_id,
            pipelineName: res.pipeline_name,
            organization: res.organization,
            project: res.project,
            processedRuns: res.processed_runs,
            totalRuns: res.total_runs,
            recordsUpserted: res.records_upserted,
          })
          qc.invalidateQueries({ queryKey: ['options'] })
          qc.invalidateQueries({ queryKey: ['summary'] })
          qc.invalidateQueries({ queryKey: ['trends'] })
          qc.invalidateQueries({ queryKey: ['runs'] })
          qc.invalidateQueries({ queryKey: ['recommendations'] })
        } else if (res.status === 'failed') {
          setIsIngesting(false)
          setIngestState({
            status: 'failed',
            processedRuns: res.processed_runs,
            totalRuns: res.total_runs,
            recordsUpserted: res.records_upserted,
            error: res.error || 'Ingestion failed',
          })
        }
      } catch {
        // Keep polling
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [isIngesting, adoOrg, org, pipelineId, qc])

  const options = useOptions()
  const connectAdo = useConnectAdo()
  const ingestAdo = useIngestAdo()
  const pipelines = options.data?.pipelines ?? []
  const orgs = options.data?.organizations ?? []
  const projects = useMemo(() => Array.from(new Set(pipelines.filter(p => !org || p.organization_name === org).map(p => p.project_name).filter(Boolean) as string[])), [pipelines, org])
  const filtered = useMemo(() => pipelines.filter(p => (!org || p.organization_name === org) && (!project || p.project_name === project)), [pipelines, org, project])
  const summary = useSummary(pipelineId, days)
  const trends = useTrends(pipelineId, days)
  const runs = useRuns(pipelineId, days)
  const recs = useRecommendations(pipelineId)
  const analyze = useAnalyze(pipelineId)
  const [trendViewMode, setTrendViewMode] = useState<'individual' | 'daily'>('individual')
  const detail = useRunAnalysis(selectedRun)
  const loading = summary.isFetching || trends.isFetching
  const displayFindings = analyze.data?.findings?.length ? analyze.data.findings : (recs.data?.findings ?? [])
  const showRecommendationMessage = !displayFindings.length && !recs.isLoading && !recs.data?.findings?.length
  const discoveredPipelines = adoPipelines.filter(p => p.project_name === project)

  const builds = trends.data?.build_trend ?? []
  const daily = trends.data?.daily_trend ?? []

  const getResultColor = (res?: string | null) => {
    const r = (res || '').toLowerCase()
    if (r === 'succeeded' || r === 'partiallysucceeded') return '#10b981' // Green
    if (r === 'failed') return '#ef4444' // Red
    if (r === 'canceled' || r === 'cancelled' || r === 'abandoned' || r === 'stopped') return '#6b7280' // Grey
    return '#6b7280'
  }

  const formatRunDate = (dateStr?: string) => {
    if (!dateStr) return ''
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }

  const chartOption = useMemo(() => {
    if (trendViewMode === 'individual') {
      return {
        tooltip: {
          trigger: 'item',
          backgroundColor: '#18181b',
          borderColor: '#3f3f46',
          textStyle: { color: '#f4f4f5' },
          formatter: (params: any) => {
            const idx = params.dataIndex
            const b = builds[idx]
            if (!b) return ''
            const dateStr = new Date(b.run_date).toLocaleString()
            const durStr = fmt(b.duration_seconds)
            const res = (b.result || 'unknown').toLowerCase()
            const color = getResultColor(res)
            const statusLabel = res === 'succeeded' ? 'SUCCESSFUL' : res === 'failed' ? 'FAILED' : res === 'partiallysucceeded' ? 'PARTIALLY SUCCEEDED' : (res || 'UNKNOWN').toUpperCase()
            return `<div style="font-family: Inter, sans-serif; font-size: 11px; line-height: 1.6; padding: 2px;">
              <b style="font-size: 12px; color: #fff;">Run #${b.build_number || b.run_id}</b><br/>
              <span style="color: #94a3b8;">${dateStr}</span><br/>
              <span>Duration: <b>${durStr}</b> (${Math.round(b.duration_seconds)}s)</span><br/>
              <span style="color: ${color}; font-weight: 700; font-size: 11px;">● ${statusLabel}</span>
            </div>`
          },
        },
        legend: { show: false },
        grid: { left: 50, right: 20, top: 25, bottom: builds.length > 20 ? 55 : 40, containLabel: true },
        dataZoom: [
          { type: 'inside', start: 0, end: 100 },
          {
            type: 'slider',
            height: 16,
            bottom: 2,
            borderColor: '#27272a',
            backgroundColor: '#18181b',
            fillerColor: 'rgba(99, 102, 241, 0.25)',
            handleStyle: { color: '#6366f1', borderColor: '#4338ca' },
            textStyle: { color: '#71717a', fontSize: 9 },
          },
        ],
        xAxis: {
          type: 'category',
          data: builds.map(b => formatRunDate(b.run_date)),
          axisLabel: {
            color: '#71717a',
            rotate: 35,
            fontSize: 10,
            interval: builds.length > 40 ? Math.ceil(builds.length / 12) : 'auto',
            hideOverlap: true,
          },
          axisTick: { alignWithLabel: true },
        },
        yAxis: { type: 'value', axisLabel: { color: '#71717a' } },
        series: [
          {
            name: 'Run duration',
            type: 'line',
            smooth: 0.2,
            symbol: 'circle',
            symbolSize: 7,
            lineStyle: { color: '#6366f1', width: 1.5, opacity: 0.6 },
            itemStyle: {
              color: (params: any) => getResultColor(builds[params.dataIndex]?.result),
              borderColor: (params: any) => getResultColor(builds[params.dataIndex]?.result),
            },
            areaStyle: {
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: [
                  { offset: 0, color: 'rgba(99, 102, 241, 0.22)' },
                  { offset: 1, color: 'rgba(99, 102, 241, 0.01)' },
                ],
              },
            },
            data: builds.map(x => Math.round(x.duration_seconds || 0)),
          },
        ],
      }
    }

    return {
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#18181b',
        borderColor: '#3f3f46',
        textStyle: { color: '#f4f4f5' },
        formatter: (params: any[]) => {
          if (!params || !params.length) return ''
          let text = `<b style="font-size: 12px; color: #fff;">${params[0].name}</b><br/>`
          params.forEach(p => {
            text += `<span style="color: ${p.color}; font-size: 11px;">● ${p.seriesName}: <b>${fmt(p.value)}</b> (${p.value}s)</span><br/>`
          })
          return `<div style="font-family: Inter, sans-serif; line-height: 1.5;">${text}</div>`
        },
      },
      legend: { textStyle: { color: '#a1a1aa' } },
      grid: { left: 45, right: 20, top: 35, bottom: 35, containLabel: true },
      xAxis: { type: 'category', data: daily.map(x => x.run_date), axisLabel: { color: '#71717a' } },
      yAxis: { type: 'value', axisLabel: { color: '#71717a' } },
      series: [
        { name: 'Average duration', type: 'line', smooth: true, lineStyle: { color: '#6366f1', width: 2 }, data: daily.map(x => Math.round(x.avg_duration_seconds || 0)) },
        { name: 'P90 duration', type: 'line', smooth: true, lineStyle: { color: '#34d399', width: 2 }, data: daily.map(x => Math.round(x.p90_duration_seconds || 0)) },
      ],
    }
  }, [trendViewMode, builds, daily])

  const stageOption = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#18181b',
      borderColor: '#3f3f46',
      textStyle: { color: '#f4f4f5' },
      formatter: (params: any[]) => {
        if (!params || !params.length) return ''
        const p = params[0]
        const stage = (summary.data?.stages ?? []).find(s => s.stage_name === p.name)
        return `<div style="font-family: Inter, sans-serif; font-size: 11px; line-height: 1.6;">
          <b style="font-size: 12px; color: #fff;">${p.name}</b><br/>
          <span style="color: #818cf8;">Average Duration: <b>${fmt(p.value)}</b> (${p.value}s)</span>
          ${stage?.samples ? `<br/><span style="color: #94a3b8;">Samples: ${stage.samples} · Failures: ${stage.failed_count ?? 0}</span>` : ''}
        </div>`
      },
    },
    grid: { left: 45, right: 20, top: 25, bottom: 95, containLabel: true },
    xAxis: {
      type: 'category',
      data: (summary.data?.stages ?? []).slice(0, 10).map(x => x.stage_name),
      axisLabel: {
        color: '#a1a1aa',
        rotate: 35,
        fontSize: 9,
        interval: 0,
        margin: 10,
      },
      axisTick: { alignWithLabel: true },
    },
    yAxis: { type: 'value', axisLabel: { color: '#71717a' } },
    series: [
      {
        type: 'bar',
        itemStyle: {
          color: '#6366f1',
          borderRadius: [4, 4, 0, 0],
        },
        data: (summary.data?.stages ?? []).slice(0, 10).map(x => Math.round(x.avg_duration_seconds || 0)),
      },
    ],
  }

  return <div className="app">
    <header><div className="brand"><div className="logo">ϟ</div><div><h1>ADO Pipeline Insight</h1><p>Pipeline Performance & AI Duration Optimizer</p></div><span className="enterprise">ENTERPRISE</span></div><div className="controls"><Select testId="organization-select" label="Org" value={org} options={orgs} placeholder="All Organizations" onChange={v => { updateOrg(v); updateProject(''); updatePipelineId(null) }} /><Select testId="project-select" label="Project" value={project} options={projects} placeholder="All Projects" onChange={v => { updateProject(v); updatePipelineId(null) }} /><Select testId="pipeline-select" label="Pipeline" value={pipelineId?.toString() ?? ''} options={filtered.map(p => p.pipeline_id.toString())} labels={Object.fromEntries(filtered.map(p => [p.pipeline_id.toString(), p.pipeline_name]))} placeholder="All Pipelines" onChange={v => updatePipelineId(v ? Number(v) : null)} /><Select testId="window-select" label="Window" value={days.toString()} options={WINDOWS.map(w => w.days.toString())} labels={Object.fromEntries(WINDOWS.map(w => [w.days.toString(), w.label]))} onChange={v => updateDays(Number(v))} /></div><div className="status" data-testid="connection-status"><span className={`dot ${options.isError ? 'bad' : ''}`} />{options.isError ? 'ERROR' : 'CONNECTED'}</div></header>
    <main>
      {ingestState && ingestState.status === 'running' && (
        <div className="ingestBanner">
          <div className="ingestBannerHeader">
            <div className="ingestBannerTitle">
              <RefreshCw className="spin" size={18} color="#818cf8" />
              <div>
                <h4>Historical Ingestion in Progress</h4>
                <p>Ingesting pipeline execution telemetry in the background. You can refresh or navigate freely without interrupting.</p>
              </div>
            </div>
            <div className="ingestBannerBadges">
              <span className="ingestBadge">
                {ingestState.processedRuns} {ingestState.totalRuns ? `/ ${ingestState.totalRuns} runs` : 'runs'}
                {ingestState.totalRuns ? ` (${Math.round((ingestState.processedRuns / ingestState.totalRuns) * 100)}%)` : ''}
              </span>
              {ingestState.recordsUpserted > 0 && (
                <span className="ingestBadge">{ingestState.recordsUpserted.toLocaleString()} records</span>
              )}
              {ingestState.currentRunDate && (
                <span className="ingestBadge">Processing: {new Date(ingestState.currentRunDate).toLocaleDateString()}</span>
              )}
            </div>
          </div>
          {ingestState.totalRuns && ingestState.totalRuns > 0 && (
            <div className="ingestProgressTrack">
              <div
                className="ingestProgressBar"
                style={{ width: `${Math.min(100, Math.round((ingestState.processedRuns / ingestState.totalRuns) * 100))}%` }}
              />
            </div>
          )}
        </div>
      )}
      {ingestState && ingestState.status === 'completed' && (
        <div className="ingestBanner ingestBannerSuccess">
          <div className="ingestBannerHeader">
            <div className="ingestBannerTitle">
              <CheckCircle2 size={18} color="#34d399" />
              <div>
                <h4>Historical Ingestion Complete</h4>
                <p>{ingestState.recordsUpserted > 0 ? `Successfully added missing runs! Total ${ingestState.processedRuns} runs (${ingestState.recordsUpserted.toLocaleString()} new records) are in the database.` : `All ${ingestState.processedRuns} runs in this window are already in the database and up-to-date.`}</p>
              </div>
            </div>
            <button className="ingestBannerDismiss" onClick={() => setIngestState(null)}>Dismiss</button>
          </div>
        </div>
      )}
      {ingestState && ingestState.status === 'failed' && (
        <div className="ingestBanner ingestBannerError">
          <div className="ingestBannerHeader">
            <div className="ingestBannerTitle">
              <TriangleAlert size={18} color="#fb7185" />
              <div>
                <h4>Ingestion Notice</h4>
                <p>{ingestState.error || 'Ingestion encountered an issue.'}</p>
              </div>
            </div>
            <button className="ingestBannerDismiss" onClick={() => setIngestState(null)}>Dismiss</button>
          </div>
        </div>
      )}
      <section className="connectPanel"><div><h2>Connect Azure DevOps</h2><p>Enter your organization and PAT. The PAT is used only for the current session and is not stored in the dashboard database.</p></div><div className="connectForm"><input aria-label="Azure DevOps organization" placeholder="Organization" value={adoOrg} onChange={e => { setAdoOrg(e.target.value); localStorage.setItem('ado_connected_org', e.target.value) }} /><input aria-label="Azure DevOps PAT" type="password" placeholder="PAT" value={adoPat} onChange={e => { setAdoPat(e.target.value); sessionStorage.setItem('ado_session_pat', e.target.value) }} autoComplete="off" /><button data-testid="connect-ado" onClick={() => connectAdo.mutate({ organization: adoOrg, pat: adoPat }, { onSuccess: data => { setAdoConnected(true); localStorage.setItem('ado_is_connected', 'true'); setAdoOrg(data.organization); localStorage.setItem('ado_connected_org', data.organization); updateOrg(data.organization); setAdoProjects(data.projects); localStorage.setItem('ado_cached_projects', JSON.stringify(data.projects)); setAdoPipelines(data.pipelines); localStorage.setItem('ado_cached_pipelines', JSON.stringify(data.pipelines)) } })} disabled={!adoOrg || !adoPat || connectAdo.isPending}>{connectAdo.isPending ? 'Connecting...' : 'Connect & Discover'}</button></div>{connectAdo.isError && <div className="connectError">{connectAdo.error instanceof Error ? connectAdo.error.message : 'Azure DevOps connection failed.'}</div>}{adoConnected && <div className="discoveryRow"><Select testId="ado-project-select" label="ADO Project" value={project} options={adoProjects.map(p => p.name)} placeholder="Select Project" onChange={v => { updateProject(v); updatePipelineId(null) }} /><Select testId="ado-pipeline-select" label="ADO Pipeline" value={pipelineId?.toString() ?? ''} options={discoveredPipelines.map(p => p.id.toString())} labels={Object.fromEntries(discoveredPipelines.map(p => [p.id.toString(), p.name]))} placeholder="Select Pipeline" onChange={v => updatePipelineId(v ? Number(v) : null)} /><Select testId="ado-history-select" label="History" value={ingestDays.toString()} options={['30', '90', '180', '365']} labels={{ '30': '30 days', '90': '90 days', '180': '180 days', '365': '1 year' }} onChange={v => updateIngestDays(Number(v))} /><button className="ingestButton" data-testid="ingest-history" disabled={!project || !pipelineId || isIngesting || ingestAdo.isPending} onClick={() => {
  if (pipelineId) {
    setIsIngesting(true)
    setIngestState({
      status: 'running',
      pipelineId,
      organization: adoOrg || org,
      project,
      processedRuns: summary.data?.total_runs ?? 0,
      totalRuns: null,
      recordsUpserted: 0,
    })
    ingestAdo.mutate(
      { organization: adoOrg, pat: adoPat, project, pipelineId, days: ingestDays },
      {
        onError: (err) => {
          setIsIngesting(false)
          setIngestState({
            status: 'failed',
            processedRuns: 0,
            totalRuns: null,
            recordsUpserted: 0,
            error: err instanceof Error ? err.message : 'Unknown error'
          })
        }
      }
    )
  }
}}>{isIngesting ? 'Ingesting in background...' : 'Ingest History'}</button></div>}</section>
      {ingestAdo.isError && <ErrorBox message={ingestAdo.error instanceof Error ? ingestAdo.error.message : 'Ingestion failed.'} />}
      {(summary.data?.degraded_runs ?? 0) > 0 && <div className="qualityWarning">{summary.data?.degraded_runs} run(s) contain degraded telemetry. Re-ingest the selected pipeline to replace fallback data with the actual Azure DevOps timeline.</div>}
      <section className="cards"><Metric testId="completed-runs" icon={<Activity />} label="Completed Runs" value={summary.data?.total_runs} suffix="runs" sub={loading ? 'Refreshing' : 'Historical telemetry'} /><Metric testId="successful-runs" icon={<CheckCircle2 />} label="Successful Runs" value={summary.data?.successful_runs} suffix="runs" sub={`Pass rate ${summary.data?.success_rate_pct ?? 0}%`} /><Metric testId="build-average-duration" icon={<Clock3 />} label="Build Average Duration" value={summary.data?.average_duration_seconds != null ? fmt(summary.data.average_duration_seconds) : undefined} sub={`P90 ${fmt(summary.data?.p90_duration_seconds ?? null)}`} /><Metric testId="failed-runs" icon={<AlertTriangle />} label="Failed Runs" value={summary.data?.failed_runs} suffix="runs" sub={`Failure rate ${summary.data?.failure_rate_pct ?? 0}%`} /></section>
      <section className="insightStrip"><Metric testId="average-queue-time" icon={<Clock3 />} label="Average Queue Time" value={summary.data?.average_queue_seconds != null ? fmt(summary.data.average_queue_seconds) : undefined} sub="Time waiting for an agent" /><Metric testId="top-bottleneck" icon={<Server />} label="Top Bottleneck" value={summary.data?.stages?.[0]?.stage_name} sub={summary.data?.stages?.[0] ? `${fmt(summary.data.stages[0].avg_duration_seconds)} average` : 'No stage telemetry'} /></section>
      <section className="grid2">
        <Panel
          title="Build Duration Trend"
          icon={<Activity size={16} />}
          action={
            <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
              {trendViewMode === 'individual' && (
                <div className="trendLegend">
                  <span className="legendItem"><span className="legendDot green" /> Success</span>
                  <span className="legendItem"><span className="legendDot red" /> Failed</span>
                  <span className="legendItem"><span className="legendDot grey" /> Cancelled</span>
                </div>
              )}
              <div className="segmentedControl">
                <button
                  type="button"
                  className={`segmentBtn ${trendViewMode === 'individual' ? 'active' : ''}`}
                  onClick={() => setTrendViewMode('individual')}
                >
                  Every Run ({builds.length})
                </button>
                <button
                  type="button"
                  className={`segmentBtn ${trendViewMode === 'daily' ? 'active' : ''}`}
                  onClick={() => setTrendViewMode('daily')}
                >
                  Daily Average ({daily.length})
                </button>
              </div>
            </div>
          }
        >
          <ReactECharts option={chartOption} style={{ height: 325 }} notMerge />
        </Panel>
        <Panel title="Stage Average Duration" icon={<Server size={16} />}><ReactECharts option={stageOption} style={{ height: 325 }} notMerge /></Panel>
      </section>
      <section className="grid2">
        <Panel
          title="AI Optimization Recommendations"
          icon={<BrainCircuit size={16} />}
          action={
            displayFindings.length > 0 ? (
              <span className="aiCountBadge">{displayFindings.length} Findings</span>
            ) : undefined
          }
        >
          <div className="aiToolbar">
            <button
              data-testid="run-ai-analysis"
              disabled={!pipelineId || analyze.isPending}
              onClick={() => pipelineId && analyze.mutate(Math.max(1, Math.round(days / 31)))}
            >
              {analyze.isPending ? <RefreshCw className="spin" size={13} /> : <BrainCircuit size={13} />}
              {analyze.isPending ? 'Analyzing Telemetry & Logs...' : 'Run AI Analysis'}
            </button>
            <div className="aiStatusText">
              {recs.data?.findings?.[0]?.generated_at ? (
                <span>Last analyzed {new Date(recs.data.findings[0].generated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
              ) : null}
            </div>
          </div>
          <div className="findings">
            {pipelineId === null ? (
              <Empty text="Select a pipeline to view AI findings." />
            ) : analyze.isError ? (
              <ErrorBox message={analyze.error instanceof Error ? analyze.error.message : 'AI analysis failed.'} />
            ) : analyze.isPending ? (
              <Empty text="Analyzing pipeline telemetry and failure logs..." />
            ) : displayFindings.length ? (
              displayFindings.slice(0, 6).map((f, i) => <FindingCard f={f} i={i} key={f.id ?? i} />)
            ) : recs.isLoading ? (
              <Empty text="Loading recommendations..." />
            ) : showRecommendationMessage && analyze.data?.message ? (
              <Empty text={analyze.data.message} />
            ) : (
              <Empty text="No optimization findings detected." />
            )}
          </div>
        </Panel>
      <Panel title={`Recent Runs (${runs.data?.items?.length ?? 0})`} icon={<Database size={16} />}>
        <div className="runs">
          {(runs.data?.items ?? []).map(r => (
            <button className="run runButton" key={r.run_id} onClick={() => setSelectedRun(r.run_id)}>
              <div>
                <b>#{r.build_number || r.run_id}</b>
                <span>{r.pipeline_name}</span>
                <small>{r.source_branch || 'main'}{r.start_time ? ` · ${new Date(r.start_time).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}` : ''} · {fmt(r.duration_seconds)}</small>
              </div>
              <span className={`result ${(r.result || '').toLowerCase()}`}>{r.result || 'unknown'}</span>
            </button>
          ))}
          {!runs.isLoading && !runs.data?.items.length && <Empty text="No runs found for the selected filter." />}
        </div>
      </Panel></section>
      <section className="footerInfo"><TriangleAlert size={15} /> Analytics are deterministic. AI recommendations are generated from measured pipeline, stage, job and task telemetry.</section>
    </main>
    {selectedRun !== null && <RunDrawer analysis={detail.data} loading={detail.isLoading} error={detail.error instanceof Error ? detail.error.message : null} onClose={() => setSelectedRun(null)} />}
  </div>
}

function RunDrawer({ analysis, loading, error, onClose }: { analysis: any; loading: boolean; error: string | null; onClose: () => void }) { const metrics = analysis?.metrics; return <div className="drawerBackdrop" onClick={onClose}><aside className="drawer" onClick={e => e.stopPropagation()}><div className="drawerHead"><div><h2>Run #{analysis?.run?.run_id ?? '...'}</h2><p>{analysis?.run?.pipeline_name ?? 'Pipeline run analysis'}</p></div><button className="close" onClick={onClose}><X size={18} /></button></div>{loading ? <Empty text="Loading execution telemetry..." /> : error ? <ErrorBox message={error} /> : analysis && <><div className="detailCards"><Mini label="Run duration" value={fmt(metrics.run_duration_seconds)} /><Mini label="Queue time" value={fmt(metrics.queue_seconds)} /><Mini label="Jobs" value={metrics.job_count} /><Mini label="Tasks" value={metrics.task_count} /></div><div className="insightBox"><b>Execution bottlenecks</b><p>Result: {analysis.run.result || 'unknown'} · Data quality: {analysis.run.data_quality}</p><p>Longest stage: {metrics.longest_stage?.stage_name ?? 'N/A'} · {fmt(metrics.longest_stage?.duration_seconds ?? null)}</p><p>Longest job: {metrics.longest_job?.job_name ?? 'N/A'} · {fmt(metrics.longest_job?.duration_seconds ?? null)}</p><p>Longest task: {metrics.longest_task?.task_name ?? 'N/A'} · {fmt(metrics.longest_task?.duration_seconds ?? null)}</p>{metrics.failed_records > 0 && <p className="failureText">Failed records detected: {metrics.failed_records}</p>}</div><Hierarchy title="Stages" rows={analysis.stages} nameKey="stage_name" /><Hierarchy title="Jobs" rows={analysis.jobs} nameKey="job_name" /><Hierarchy title="Tasks" rows={analysis.tasks} nameKey="task_name" /></>}</aside></div> }
function Hierarchy({ title, rows, nameKey }: { title: string; rows: any[]; nameKey: string }) { return <section className="hierarchy"><h3>{title} <small>{rows.length}</small></h3>{rows.length === 0 ? <Empty text={`No ${title.toLowerCase()} captured.`} /> : rows.map((r, i) => <div className="hierarchyRow" key={r.id ?? i}><div><b>{r[nameKey] ?? 'Unnamed'}</b><small>{r.stage_name && nameKey !== 'stage_name' ? r.stage_name : ''}{r.job_name && nameKey === 'task_name' ? ` / ${r.job_name}` : ''} · retries {r.retry_count ?? 0}</small></div><div><strong>{fmt(r.duration_seconds)}</strong><span className={`result ${(r.result || '').toLowerCase()}`}>{r.result || 'unknown'}</span></div></div>)}</section> }
function Select({ label, value, options, labels, placeholder, onChange, testId }: { label: string; value: string; options: string[]; labels?: Record<string, string>; placeholder?: string; onChange: (v: string) => void; testId?: string }) { return <label className="select"><span>{label}:</span><select data-testid={testId} value={value} onChange={e => onChange(e.target.value)}><option value="">{placeholder ?? 'Select'}</option>{options.map(v => <option value={v} key={v}>{labels?.[v] ?? v}</option>)}</select><ChevronDown size={14} /></label> }
function Metric({ icon, label, value, suffix, sub, testId }: { icon: ReactNode; label: string; value: number | string | undefined; suffix?: string; sub: string; testId?: string }) { return <div className="metric" data-testid={testId}><div className="metricIcon">{icon}</div><div><div className="metricLabel">{label}</div><div className="metricValue">{value == null ? '...' : value} {suffix && <small>{suffix}</small>}</div><div className="metricSub">{sub}</div></div></div> }
function Mini({ label, value }: { label: string; value: string | number | null }) { return <div className="mini"><small>{label}</small><b>{value ?? 'N/A'}</b></div> }
function Panel({ title, icon, children, action }: { title: string; icon: ReactNode; children: ReactNode; action?: ReactNode }) { return <div className="panel"><div className="panelHead"><div>{icon}<h3>{title}</h3></div>{action}</div>{children}</div> }
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div> }
function ErrorBox({ message }: { message: string }) { return <div className="errorBox"><TriangleAlert size={16} /><div><b>Backend connection issue</b><p>{message}</p></div></div> }
function parseRecommendation(text: string) {
  let diagnosis = ''
  let remediation = ''
  let impact = ''

  if (text.includes('**Diagnosis**:') || text.includes('**Remediation**:')) {
    const diagMatch = text.match(/\*\*Diagnosis\*\*:\s*([\s\S]*?)(?=\*\*Remediation\*\*:|$)/i)
    const remMatch = text.match(/\*\*Remediation\*\*:\s*([\s\S]*?)(?=\*\*Impact\*\*:|$)/i)
    const impMatch = text.match(/\*\*Impact\*\*:\s*([\s\S]*?)$/i)
    if (diagMatch) diagnosis = diagMatch[1].trim()
    if (remMatch) remediation = remMatch[1].trim()
    if (impMatch) impact = impMatch[1].trim()
  }

  return { diagnosis, remediation, impact, raw: text }
}

function parseEvidence(evidence: string) {
  let metricsText = evidence
  let errorLog = ''

  const errorMatch = evidence.match(/(?:and\s+|with\s+)?(?:Error Log|Error excerpt|Log excerpt|Log snippet):\s*"?([^"]*)"?/i)
  if (errorMatch) {
    errorLog = errorMatch[1].trim()
    metricsText = evidence.replace(errorMatch[0], '').replace(/\s*(?:with|and|[,|])\s*$/, '').trim()
  }

  return { metricsText, errorLog }
}

function FindingCard({ f, i }: { f: Recommendation; i: number }) {
  const [copied, setCopied] = useState(false)
  const parsed = useMemo(() => parseRecommendation(f.recommendation || ''), [f.recommendation])
  const ev = useMemo(() => parseEvidence(f.evidence || ''), [f.evidence])

  const copyActionPlan = () => {
    const textToCopy = `[${f.severity.toUpperCase()}] ${f.stage_name}${f.task_name ? ` / ${f.task_name}` : ''}\n${f.recommendation}\nEvidence: ${f.evidence}`
    navigator.clipboard.writeText(textToCopy)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const categoryLabels: Record<string, { label: string; icon: ReactNode }> = {
    flaky_step: { label: 'Flaky / Failure', icon: <ShieldAlert size={12} /> },
    bottleneck: { label: 'Duration Bottleneck', icon: <Clock3 size={12} /> },
    regression: { label: 'Performance Regression', icon: <AlertTriangle size={12} /> },
    caching_opportunity: { label: 'Caching Opportunity', icon: <Zap size={12} /> },
    parallelization_opportunity: { label: 'Parallelization', icon: <Sparkles size={12} /> },
    queue_capacity: { label: 'Queue / Capacity', icon: <Server size={12} /> },
  }

  const cat = categoryLabels[f.category] || { label: f.category.replace(/_/g, ' '), icon: <Activity size={12} /> }

  return (
    <div className={`finding findingCard ${f.severity}`} key={f.id ?? i}>
      <div className="findingHeader">
        <div className="findingBreadcrumb">
          <span className={`severity ${f.severity}`}>{f.severity.toUpperCase()}</span>
          <span className="categoryBadge">{cat.icon} {cat.label}</span>
          {parsed.impact && <span className="impactBadge">{parsed.impact}</span>}
        </div>
        <button className="copyBtn" onClick={copyActionPlan} title="Copy Action Plan">
          {copied ? <Check size={12} /> : <Copy size={12} />}
          <span>{copied ? 'Copied' : 'Copy Plan'}</span>
        </button>
      </div>

      <div className="findingBody">
        <b>{f.stage_name}{f.task_name ? ` / ${f.task_name}` : ''}</b>

        <p className="findingText">
          {parsed.diagnosis ? (
            <>
              <span className="findingSectionTitle"><ShieldAlert size={13} /> Root Cause:</span>
              <span className="findingDiagnosis">{parsed.diagnosis}</span>
              <span className="findingSectionTitle"><Wrench size={13} /> Actionable Remediation:</span>
              <span className="findingRemediation">{parsed.remediation}</span>
            </>
          ) : (
            f.recommendation
          )}
        </p>

        <small className="findingEvidence">
          {ev.errorLog && (
            <div className="logExcerptBox">
              <div className="logExcerptHead"><Terminal size={11} /> Captured Failure Excerpt</div>
              <code>{ev.errorLog}</code>
            </div>
          )}
          <span className="metricsProof">{ev.metricsText || f.evidence}</span>
        </small>
      </div>
    </div>
  )
}

export default App
