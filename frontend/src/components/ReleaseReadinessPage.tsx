import React, { useState, useEffect, useMemo } from 'react'
import {
  Rocket,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  ExternalLink,
  Plus,
  Trash2,
  RefreshCw,
  GitBranch,
  Layers,
  GitPullRequest,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Calendar,
  ShieldCheck,
  ShieldAlert,
  Info,
  Check,
  FolderGit2,
} from 'lucide-react'
import { api } from '../services/api'
import type {
  ReleaseDefinition,
  ReleaseDefinitionCreate,
  ReleaseScorecard,
  ReleaseBranchCandidate,
  ReleaseDimension,
  Pipeline,
  AdoRepository,
} from '../types/api'

interface ReleaseReadinessPageProps {
  organization: string
  project: string
  pat?: string
  pipelines?: Pipeline[]
  projects?: { id: string; name: string }[]
  onOrganizationChange?: (org: string) => void
  onProjectChange?: (project: string) => void
  onPatChange?: (pat: string) => void
  theme?: string
}

export const ReleaseReadinessPage: React.FC<ReleaseReadinessPageProps> = ({
  organization,
  project,
  pat,
  pipelines = [],
  projects = [],
  onOrganizationChange,
  onProjectChange,
  onPatChange,
}) => {
  // State
  const [releases, setReleases] = useState<ReleaseDefinition[]>([])
  const [selectedReleaseId, setSelectedReleaseId] = useState<string | null>(null)
  const [scorecard, setScorecard] = useState<ReleaseScorecard | null>(null)
  const [loadingList, setLoadingList] = useState(false)
  const [loadingScorecard, setLoadingScorecard] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Local editable PAT & organization fallback logic
  const [localPat, setLocalPat] = useState(pat || '')
  useEffect(() => {
    if (pat !== undefined) setLocalPat(pat)
  }, [pat])

  // If organization has spaces or is an alias (e.g. "Deepak login"), auto-resolve to matching pipeline's organization_name
  const effectiveOrg = useMemo(() => {
    if (organization && !organization.includes(' ')) {
      return organization
    }
    const match = pipelines.find(
      p => p.project_name?.toLowerCase() === project?.toLowerCase() && p.organization_name && !p.organization_name.includes(' ')
    )
    if (match?.organization_name) {
      return match.organization_name
    }
    return organization ? organization.replace(/\s+/g, '-') : ''
  }, [organization, project, pipelines])

  // Repositories state
  const [repositories, setRepositories] = useState<AdoRepository[]>([])
  const [loadingRepos, setLoadingRepos] = useState(false)
  const [reposError, setReposError] = useState<string | null>(null)

  // Create Release Modal state
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newRepoId, setNewRepoId] = useState('')
  const [newRepoName, setNewRepoName] = useState('')
  const [newPipelineId, setNewPipelineId] = useState<number | undefined>(undefined)
  const [branchCandidates, setBranchCandidates] = useState<ReleaseBranchCandidate[]>([])
  const [loadingBranches, setLoadingBranches] = useState(false)
  const [newTargetBranch, setNewTargetBranch] = useState('')
  const [newScopeFeature, setNewScopeFeature] = useState('')
  const [newTargetShipDate, setNewTargetShipDate] = useState('')
  const [creating, setCreating] = useState(false)

  // Expanded evidence sections
  const [expandedDims, setExpandedDims] = useState<Record<string, boolean>>({
    delivery_completion: false,
    review_backlog: false,
  })

  // Load saved releases on org/project change
  useEffect(() => {
    if (!effectiveOrg || !project) return
    loadReleases()
    loadRepositories(localPat, effectiveOrg)
  }, [effectiveOrg, project])

  // Load scorecard whenever selected release changes
  useEffect(() => {
    if (!selectedReleaseId) {
      setScorecard(null)
      return
    }
    loadScorecard(selectedReleaseId)
  }, [selectedReleaseId])

  // When repository changes in create modal, load that repository's respective branches!
  useEffect(() => {
    if (!isCreateOpen || !newRepoId || !effectiveOrg || !project) return
    loadBranchCandidates(newRepoId, newPipelineId)
  }, [isCreateOpen, newRepoId, newPipelineId, effectiveOrg, project])

  // When create modal opens, ensure repos are loaded
  useEffect(() => {
    if (isCreateOpen) {
      if (repositories.length === 0) {
        loadRepositories(localPat, effectiveOrg)
      } else if (!newRepoId) {
        setNewRepoId(repositories[0].id)
        setNewRepoName(repositories[0].name)
      }
    }
  }, [isCreateOpen, repositories, newRepoId, effectiveOrg, localPat])

  const loadRepositories = async (customPat?: string, customOrg?: string) => {
    const orgToUse = customOrg || effectiveOrg
    const patToUse = customPat !== undefined ? customPat : localPat
    if (!orgToUse || !project) return
    try {
      setLoadingRepos(true)
      setReposError(null)
      const list = await api.repositories(orgToUse, project, patToUse)
      setRepositories(list)
      if (list.length > 0 && !newRepoId) {
        setNewRepoId(list[0].id)
        setNewRepoName(list[0].name)
      }
    } catch (err: any) {
      console.warn('Could not load repositories:', err)
      const msg = err instanceof Error ? err.message : 'Could not fetch repositories'
      setReposError(msg)
      // Provide project name as fallback repository option if empty
      if (repositories.length === 0 && project) {
        setRepositories([
          {
            id: project,
            name: project,
            default_branch: 'main',
            web_url: null,
          },
        ])
        if (!newRepoId) {
          setNewRepoId(project)
          setNewRepoName(project)
        }
      }
    } finally {
      setLoadingRepos(false)
    }
  }

  const loadReleases = async () => {
    try {
      setLoadingList(true)
      setError(null)
      const list = await api.listReleases(effectiveOrg, project)
      setReleases(list)
      if (list.length > 0 && !selectedReleaseId) {
        setSelectedReleaseId(list[0].release_id)
      } else if (list.length === 0) {
        setSelectedReleaseId(null)
        setScorecard(null)
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load release definitions.')
    } finally {
      setLoadingList(false)
    }
  }

  const loadScorecard = async (relId: string) => {
    try {
      setLoadingScorecard(true)
      setError(null)
      const card = await api.getReleaseScorecard(relId, localPat || pat)
      setScorecard(card)
    } catch (err: any) {
      setError(err.message || 'Failed to compute release scorecard.')
    } finally {
      setLoadingScorecard(false)
    }
  }

  const loadBranchCandidates = async (repoId: string, pipeId?: number) => {
    try {
      setLoadingBranches(true)
      const candidates = await api.releaseBranchCandidates(effectiveOrg, project, repoId, pipeId, localPat || pat)
      setBranchCandidates(candidates)
      if (candidates.length > 0) {
        // Pre-select top candidate or default branch
        const defaultCandidate = candidates.find(c => c.is_default) || candidates[0]
        setNewTargetBranch(defaultCandidate.branch)
      } else {
        // No branches discovered — let the user type one manually.
        setNewTargetBranch('')
      }
    } catch (err) {
      console.warn('Could not load branch candidates for repository:', err)
      setBranchCandidates([])
      setNewTargetBranch('')
    } finally {
      setLoadingBranches(false)
    }
  }

  const handleCreateRelease = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newName.trim() || !newRepoId || !newTargetBranch.trim()) return

    try {
      setCreating(true)
      const payload: ReleaseDefinitionCreate = {
        name: newName.trim(),
        organization_name: effectiveOrg,
        project_name: project,
        repository_id: newRepoId,
        repository_name: newRepoName || undefined,
        pipeline_id: newPipelineId || undefined,
        target_branch: newTargetBranch.trim(),
        scope_feature_title: newScopeFeature.trim() ? newScopeFeature.trim() : null,
        target_ship_date: newTargetShipDate ? newTargetShipDate : null,
      }
      const created = await api.createRelease(payload)
      setReleases(prev => [created, ...prev])
      setSelectedReleaseId(created.release_id)
      setIsCreateOpen(false)
      // Reset form
      setNewName('')
      setNewScopeFeature('')
      setNewTargetShipDate('')
    } catch (err: any) {
      alert(`Failed to create release: ${err.message || err}`)
    } finally {
      setCreating(false)
    }
  }

  const handleDeleteRelease = async (relId: string, relName: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`Are you sure you want to delete the release definition "${relName}"?`)) return
    try {
      await api.deleteRelease(relId)
      setReleases(prev => prev.filter(r => r.release_id !== relId))
      if (selectedReleaseId === relId) {
        const remaining = releases.filter(r => r.release_id !== relId)
        setSelectedReleaseId(remaining.length > 0 ? remaining[0].release_id : null)
      }
    } catch (err: any) {
      alert(`Failed to delete release: ${err.message || err}`)
    }
  }

  const toggleDimExpand = (dimKey: string) => {
    setExpandedDims(prev => ({ ...prev, [dimKey]: !prev[dimKey] }))
  }

  const formatLastBuilt = (dateStr: string | null) => {
    if (!dateStr) return 'No runs recorded'
    try {
      const d = new Date(dateStr)
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    } catch {
      return dateStr
    }
  }

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'green':
        return '#00fbfb'
      case 'yellow':
        return '#f59e0b'
      case 'red':
        return '#ef4444'
      default:
        return '#9ca3af'
    }
  }

  const getStatusBg = (status: string) => {
    switch (status.toLowerCase()) {
      case 'green':
        return 'rgba(0, 251, 251, 0.12)'
      case 'yellow':
        return 'rgba(245, 158, 11, 0.15)'
      case 'red':
        return 'rgba(239, 68, 68, 0.18)'
      default:
        return 'rgba(156, 163, 175, 0.1)'
    }
  }

  const getStatusBorder = (status: string) => {
    switch (status.toLowerCase()) {
      case 'green':
        return 'rgba(0, 251, 251, 0.35)'
      case 'yellow':
        return 'rgba(245, 158, 11, 0.4)'
      case 'red':
        return 'rgba(239, 68, 68, 0.45)'
      default:
        return 'rgba(156, 163, 175, 0.2)'
    }
  }

  const renderStatusBadge = (status: string, label?: string) => {
    const color = getStatusColor(status)
    const bg = getStatusBg(status)
    const border = getStatusBorder(status)
    const text = label || status.toUpperCase()

    let Icon = CheckCircle2
    if (status === 'red') Icon = XCircle
    else if (status === 'yellow') Icon = AlertTriangle

    return (
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          padding: '4px 10px',
          borderRadius: '16px',
          backgroundColor: bg,
          border: `1px solid ${border}`,
          color: color,
          fontSize: '11px',
          fontWeight: 700,
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
          fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace',
        }}
      >
        <Icon size={13} strokeWidth={2.4} />
        {text}
      </span>
    )
  }

  return (
    <div style={{ padding: '26px 30px 50px', maxWidth: '1500px', margin: '0 auto', color: '#f4f4f5' }}>
      {/* 0. Top Connection & Discovery Toolbar */}
      <div className="adoConnectBar">
        <div className="adoConnectBarLeft">
          <div className="adoConnectItem">
            <span className="adoConnectLabel">Org:</span>
            <input
              type="text"
              className="adoConnectInput"
              placeholder="Organization"
              value={effectiveOrg}
              onChange={(e) => {
                const val = e.target.value
                onOrganizationChange?.(val)
              }}
              onBlur={() => {
                loadRepositories(localPat, effectiveOrg)
                loadReleases()
              }}
            />
          </div>

          <div className="adoConnectItem">
            <span className="adoConnectLabel">PAT:</span>
            <input
              type="password"
              className="adoConnectInput"
              placeholder={localPat ? '••••••••••••••••' : 'PAT Token (optional)'}
              value={localPat}
              onChange={(e) => {
                const val = e.target.value
                setLocalPat(val)
                onPatChange?.(val)
                sessionStorage.setItem('ado_session_pat', val)
              }}
              onBlur={() => {
                loadRepositories(localPat, effectiveOrg)
              }}
              autoComplete="off"
            />
          </div>

          {projects.length > 0 && (
            <div className="adoConnectItem">
              <span className="adoConnectLabel">Project:</span>
              <div className="adoSelectWrapper">
                <select
                  className="adoConnectSelect"
                  value={project}
                  onChange={(e) => onProjectChange?.(e.target.value)}
                >
                  {projects.map((p) => (
                    <option key={p.id} value={p.name}>
                      {p.name}
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} className="adoSelectArrow" />
              </div>
            </div>
          )}
        </div>

        <div className="adoConnectBarRight">
          <span style={{ fontSize: '11px', color: repositories.length > 0 ? '#4ade80' : '#facc15', display: 'flex', alignItems: 'center', gap: '5px' }}>
            <FolderGit2 size={13} />
            {loadingRepos
              ? 'Loading repos...'
              : repositories.length > 0
              ? `${repositories.length} repo${repositories.length > 1 ? 's' : ''} available`
              : 'Manual repo mode'}
          </span>
        </div>
      </div>

      {/* Page Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '38px',
                height: '38px',
                borderRadius: '10px',
                background: 'linear-gradient(135deg, rgba(0, 251, 251, 0.2), rgba(168, 85, 247, 0.2))',
                border: '1px solid rgba(0, 251, 251, 0.4)',
                display: 'grid',
                placeItems: 'center',
                color: '#00fbfb',
              }}
            >
              <Rocket size={20} strokeWidth={2.2} />
            </div>
            <div>
              <h1 style={{ fontSize: '22px', fontWeight: 800, margin: 0, color: '#ffffff', letterSpacing: '-0.02em' }}>
                Release Readiness Scorecard
              </h1>
              <p style={{ fontSize: '12px', color: '#9ca3af', margin: '3px 0 0' }}>
                Composite go/no-go quality evaluation combining sprint work item delivery and pull request review backlog.
              </p>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            type="button"
            className="sync"
            onClick={() => {
              loadReleases()
              loadRepositories()
              if (selectedReleaseId) loadScorecard(selectedReleaseId)
            }}
            disabled={loadingList || loadingScorecard}
            style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <RefreshCw size={14} className={loadingList || loadingScorecard ? 'spin' : ''} />
            Refresh
          </button>

          <button
            type="button"
            onClick={() => setIsCreateOpen(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: '#00fbfb',
              color: '#09090b',
              border: 'none',
              padding: '8px 16px',
              borderRadius: '20px',
              fontSize: '12px',
              fontWeight: 700,
              cursor: 'pointer',
              boxShadow: '0 0 15px rgba(0, 251, 251, 0.3)',
              transition: 'all 0.15s ease',
            }}
          >
            <Plus size={15} strokeWidth={2.8} />
            New Release
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            padding: '12px 16px',
            marginBottom: '20px',
            borderRadius: '8px',
            backgroundColor: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            color: '#fca5a5',
            fontSize: '13px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
          }}
        >
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Saved Releases Selection Row */}
      <div style={{ marginBottom: '24px' }}>
        <div style={{ fontSize: '11px', fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '10px' }}>
          Configured Releases ({releases.length})
        </div>

        {releases.length === 0 && !loadingList ? (
          <div
            style={{
              padding: '28px',
              borderRadius: '12px',
              background: '#202026',
              border: '1px dashed #3e4047',
              textAlign: 'center',
              color: '#9ca3af',
            }}
          >
            <Rocket size={32} style={{ margin: '0 auto 10px', opacity: 0.5, color: '#00fbfb' }} />
            <h3 style={{ margin: '0 0 6px', color: '#f4f4f5', fontSize: '15px' }}>No Release Definitions Found</h3>
            <p style={{ margin: '0 0 14px', fontSize: '12px', maxWidth: '480px', marginInline: 'auto' }}>
              Create a release definition to monitor live repository branch telemetry, sprint progress, blocker bugs, and pull requests in one composite scorecard.
            </p>
            <button
              type="button"
              onClick={() => setIsCreateOpen(true)}
              style={{
                backgroundColor: 'rgba(0, 251, 251, 0.15)',
                color: '#00fbfb',
                border: '1px solid rgba(0, 251, 251, 0.4)',
                padding: '6px 14px',
                borderRadius: '16px',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              + Create First Release
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: '12px', overflowX: 'auto', paddingBottom: '6px' }}>
            {releases.map(rel => {
              const isSelected = rel.release_id === selectedReleaseId
              return (
                <div
                  key={rel.release_id}
                  onClick={() => setSelectedReleaseId(rel.release_id)}
                  style={{
                    minWidth: '240px',
                    maxWidth: '300px',
                    padding: '14px 16px',
                    borderRadius: '10px',
                    backgroundColor: isSelected ? '#252630' : '#1c1c22',
                    border: isSelected ? '1px solid #00fbfb' : '1px solid #2e2f38',
                    boxShadow: isSelected ? '0 0 12px rgba(0, 251, 251, 0.18)' : 'none',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                    position: 'relative',
                    flexShrink: 0,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                    <span style={{ fontSize: '14px', fontWeight: 700, color: '#ffffff' }}>{rel.name}</span>
                    <button
                      type="button"
                      title="Delete release definition"
                      onClick={e => handleDeleteRelease(rel.release_id, rel.name, e)}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: '#6b7280',
                        cursor: 'pointer',
                        padding: '2px',
                        display: 'grid',
                        placeItems: 'center',
                      }}
                      onMouseEnter={e => (e.currentTarget.style.color = '#ef4444')}
                      onMouseLeave={e => (e.currentTarget.style.color = '#6b7280')}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>

                  {rel.repository_name && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#a78bfa', marginBottom: '4px' }}>
                      <FolderGit2 size={12} />
                      <span style={{ fontWeight: 600 }}>{rel.repository_name}</span>
                    </div>
                  )}

                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#00fbfb', marginBottom: '6px' }}>
                    <GitBranch size={12} />
                    <span style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {rel.target_branch}
                    </span>
                  </div>

                  {rel.target_ship_date && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '10.5px', color: '#9ca3af' }}>
                      <Calendar size={11} />
                      <span>Ship: {rel.target_ship_date}</span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Main Scorecard View */}
      {loadingScorecard ? (
        <div style={{ padding: '60px', textAlign: 'center', color: '#9ca3af' }}>
          <RefreshCw size={28} className="spin" style={{ margin: '0 auto 12px', color: '#00fbfb' }} />
          <div style={{ fontSize: '14px', fontWeight: 600, color: '#f4f4f5' }}>Computing Release Readiness Scorecard...</div>
          <div style={{ fontSize: '12px', marginTop: '4px' }}>Evaluating sprint work item delivery and pull request reviews.</div>
        </div>
      ) : scorecard ? (
        <div>
          {/* Executive Verdict Banner */}
          <div
            style={{
              padding: '20px 24px',
              borderRadius: '12px',
              backgroundColor: getStatusBg(scorecard.overall_status),
              border: `1.5px solid ${getStatusBorder(scorecard.overall_status)}`,
              marginBottom: '20px',
              boxShadow: `0 4px 20px ${getStatusBg(scorecard.overall_status)}`,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                <div
                  style={{
                    width: '46px',
                    height: '46px',
                    borderRadius: '12px',
                    backgroundColor: getStatusBg(scorecard.overall_status),
                    border: `1px solid ${getStatusBorder(scorecard.overall_status)}`,
                    display: 'grid',
                    placeItems: 'center',
                    color: getStatusColor(scorecard.overall_status),
                  }}
                >
                  {scorecard.overall_status === 'green' ? (
                    <ShieldCheck size={26} strokeWidth={2.4} />
                  ) : (
                    <ShieldAlert size={26} strokeWidth={2.4} />
                  )}
                </div>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 800, color: '#ffffff' }}>
                      {scorecard.overall_status === 'green'
                        ? 'READY TO SHIP'
                        : scorecard.overall_status === 'yellow'
                        ? 'SHIPMENT AT RISK'
                        : 'SHIPMENT BLOCKED'}
                    </h2>
                    {renderStatusBadge(scorecard.overall_status)}
                  </div>
                  <p style={{ margin: '4px 0 0', fontSize: '12.5px', color: '#d1d5db' }}>
                    {scorecard.overall_status === 'green'
                      ? 'Release quality criteria are satisfied. Sprint delivery is on track and pull requests are reviewed.'
                      : scorecard.overall_status === 'yellow'
                      ? 'One or more dimensions have moderate warnings. Review open items before initiating deployment.'
                      : 'Critical blockers detected. Strictly governed: the worst dimension decides the verdict (averaging is forbidden).'}
                  </p>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '12px', color: '#9ca3af' }}>
                {scorecard.release.repository_name && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <FolderGit2 size={13} style={{ color: '#a78bfa' }} />
                    <span style={{ fontWeight: 600, color: '#f4f4f5' }}>{scorecard.release.repository_name}</span>
                  </div>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <GitBranch size={13} style={{ color: '#00fbfb' }} />
                  <span style={{ fontFamily: 'ui-monospace,monospace', color: '#f4f4f5' }}>{scorecard.release.target_branch}</span>
                </div>
                {scorecard.release.target_ship_date && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Calendar size={13} style={{ color: '#f59e0b' }} />
                    <span style={{ color: '#f4f4f5' }}>Target: {scorecard.release.target_ship_date}</span>
                  </div>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#71717a' }}>
                  <Clock size={12} />
                  <span>Computed: {new Date(scorecard.computed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                </div>
              </div>
            </div>
          </div>

          {/* AI Narrative Briefing & Recommendations */}
          <div
            style={{
              padding: '18px 22px',
              borderRadius: '12px',
              backgroundColor: '#1b1b22',
              border: '1px solid #2e2f38',
              marginBottom: '24px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Sparkles size={16} style={{ color: '#a855f7' }} />
                <span style={{ fontSize: '13px', fontWeight: 700, color: '#f4f4f5' }}>
                  Executive Release Verdict Briefing
                </span>
                <span
                  style={{
                    fontSize: '10px',
                    fontFamily: 'ui-monospace,monospace',
                    padding: '2px 8px',
                    borderRadius: '12px',
                    backgroundColor: scorecard.ai_generated ? 'rgba(168, 85, 247, 0.15)' : 'rgba(0, 251, 251, 0.12)',
                    color: scorecard.ai_generated ? '#c084fc' : '#00fbfb',
                    border: scorecard.ai_generated ? '1px solid rgba(168, 85, 247, 0.4)' : '1px solid rgba(0, 251, 251, 0.3)',
                    fontWeight: 600,
                  }}
                >
                  {scorecard.ai_generated ? 'Azure OpenAI Grounded' : 'Deterministic Grounded'}
                </span>
              </div>
            </div>

            <p style={{ margin: '0 0 14px', fontSize: '13.5px', lineHeight: 1.6, color: '#e4e4e7' }}>
              {scorecard.ai_narrative}
            </p>

            {scorecard.recommendations.length > 0 && (
              <div style={{ borderTop: '1px solid #282830', paddingTop: '12px', marginTop: '12px' }}>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '8px' }}>
                  Sign-Off Action Items ({scorecard.recommendations.length})
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {scorecard.recommendations.map((rec, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '12px', color: '#d4d4d8' }}>
                      <Check size={14} style={{ color: '#00fbfb', marginTop: '2px', flexShrink: 0 }} />
                      <span>{rec}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Quality Dimensions Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '16px', marginBottom: '24px' }}>
            {/* Dimension 1: Delivery Completion */}
            {scorecard.dimensions.delivery_completion && renderDimensionCard(
              'delivery_completion',
              scorecard.dimensions.delivery_completion,
              <Layers size={18} style={{ color: '#38bdf8' }} />,
              'Sprint Delivery'
            )}

            {/* Dimension 2: Review Backlog */}
            {scorecard.dimensions.review_backlog && renderDimensionCard(
              'review_backlog',
              scorecard.dimensions.review_backlog,
              <GitPullRequest size={18} style={{ color: '#fbbf24' }} />,
              'PR Review Aging'
            )}
          </div>
        </div>
      ) : null}

      {/* Create Release Modal */}
      {isCreateOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.75)',
            backdropFilter: 'blur(4px)',
            display: 'grid',
            placeItems: 'center',
            zIndex: 1000,
            padding: '20px',
          }}
          onClick={() => setIsCreateOpen(false)}
        >
          <div
            style={{
              backgroundColor: '#1b1b22',
              border: '1px solid #3e4047',
              borderRadius: '14px',
              width: '100%',
              maxWidth: '560px',
              padding: '24px',
              boxShadow: '0 10px 40px rgba(0, 0, 0, 0.7)',
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Rocket size={18} style={{ color: '#00fbfb' }} />
                <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: '#ffffff' }}>Create Release Definition</h3>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateOpen(false)}
                style={{ background: 'transparent', border: 'none', color: '#9ca3af', cursor: 'pointer', fontSize: '18px' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateRelease}>
              {/* Release Name */}
              <div style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#9ca3af', marginBottom: '6px' }}>
                  Release Label / Version Name *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. v2.4.0 or Sprint 42"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    backgroundColor: '#262630',
                    border: '1px solid #3f3f4e',
                    color: '#ffffff',
                    fontSize: '12.5px',
                  }}
                />
              </div>

              {/* Repository Picker */}
              <div style={{ marginBottom: '14px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <label style={{ fontSize: '11px', fontWeight: 600, color: '#9ca3af' }}>
                    Repository *
                  </label>
                  {loadingRepos && (
                    <span style={{ fontSize: '11px', color: '#00fbfb', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <RefreshCw size={11} className="spin" /> Loading repositories...
                    </span>
                  )}
                </div>

                {repositories.length > 0 ? (
                  <select
                    value={newRepoId}
                    onChange={e => {
                      const rId = e.target.value
                      const found = repositories.find(r => r.id === rId)
                      setNewRepoId(rId)
                      setNewRepoName(found ? found.name : rId)
                    }}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '8px',
                      backgroundColor: '#262630',
                      border: '1px solid #00fbfb',
                      color: '#ffffff',
                      fontSize: '12.5px',
                    }}
                  >
                    {repositories.map(repo => (
                      <option key={repo.id} value={repo.id}>
                        {repo.name} {repo.default_branch ? `(default: ${repo.default_branch})` : ''}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div>
                    <input
                      type="text"
                      required
                      placeholder={`e.g. ${project || 'MyRepo'}`}
                      value={newRepoName}
                      onChange={e => {
                        setNewRepoName(e.target.value)
                        setNewRepoId(e.target.value)
                      }}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: '8px',
                        backgroundColor: '#262630',
                        border: '1px solid #3f3f4e',
                        color: '#ffffff',
                        fontSize: '12.5px',
                        marginBottom: '8px',
                      }}
                    />
                    {project && (
                      <button
                        type="button"
                        onClick={() => {
                          setNewRepoId(project)
                          setNewRepoName(project)
                          loadBranchCandidates(project, newPipelineId)
                        }}
                        style={{
                          backgroundColor: 'rgba(0, 251, 251, 0.12)',
                          color: '#00fbfb',
                          border: '1px solid rgba(0, 251, 251, 0.3)',
                          borderRadius: '6px',
                          padding: '4px 10px',
                          fontSize: '11px',
                          cursor: 'pointer',
                          marginBottom: '8px',
                        }}
                      >
                        Use Project Default ({project})
                      </button>
                    )}
                  </div>
                )}

                {/* Inline PAT connect box if repos couldn't be loaded automatically */}
                {repositories.length <= 1 && (
                  <div style={{ marginTop: '8px', padding: '10px 12px', borderRadius: '8px', backgroundColor: '#18181f', border: '1px solid #2e2f38', fontSize: '11.5px' }}>
                    <div style={{ color: '#d1d5db', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <FolderGit2 size={13} style={{ color: '#00fbfb' }} />
                      <span>Connect Azure DevOps PAT to load all project repositories:</span>
                    </div>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <input
                        type="password"
                        placeholder="Azure DevOps PAT with Code (Read)..."
                        value={localPat}
                        onChange={e => {
                          const val = e.target.value
                          setLocalPat(val)
                          onPatChange?.(val)
                          sessionStorage.setItem('ado_session_pat', val)
                        }}
                        style={{
                          flex: 1,
                          padding: '6px 10px',
                          borderRadius: '6px',
                          backgroundColor: '#262630',
                          border: '1px solid #3f3f4e',
                          color: '#ffffff',
                          fontSize: '11.5px',
                        }}
                      />
                      <button
                        type="button"
                        onClick={() => loadRepositories(localPat, effectiveOrg)}
                        disabled={loadingRepos}
                        style={{
                          padding: '6px 12px',
                          borderRadius: '6px',
                          backgroundColor: '#00fbfb',
                          color: '#09090b',
                          border: 'none',
                          fontSize: '11px',
                          fontWeight: 700,
                          cursor: 'pointer',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {loadingRepos ? 'Loading...' : 'Load Repos'}
                      </button>
                    </div>
                    {reposError && (
                      <div style={{ color: '#fca5a5', marginTop: '6px', fontSize: '10.5px' }}>
                        {reposError}
                      </div>
                    )}
                  </div>
                )}

                <div style={{ fontSize: '10.5px', color: '#71717a', marginTop: '4px' }}>
                  Select the Azure DevOps Git repository for this release.
                </div>
              </div>

              {/* Target Branch Dropdown - Live Branches from Selected Repository */}
              <div style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#9ca3af', marginBottom: '6px' }}>
                  Target Release Branch * (from selected repository)
                </label>
                {loadingBranches ? (
                  <div style={{ fontSize: '11.5px', color: '#9ca3af', padding: '8px 0' }}>
                    Loading branches from repository...
                  </div>
                ) : branchCandidates.length > 0 ? (
                  <select
                    value={newTargetBranch}
                    onChange={e => setNewTargetBranch(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '8px',
                      backgroundColor: '#262630',
                      border: '1px solid #00fbfb',
                      color: '#ffffff',
                      fontSize: '12.5px',
                      fontFamily: 'ui-monospace,monospace',
                    }}
                  >
                    {branchCandidates.map(c => {
                      const branchLabel = c.branch.replace('refs/heads/', '')
                      const runText = c.run_count > 0 ? `(${c.run_count} runs, last: ${formatLastBuilt(c.last_built)})` : '(no builds recorded)'
                      return (
                        <option key={c.branch} value={c.branch}>
                          {c.branch} {runText}
                        </option>
                      )
                    })}
                  </select>
                ) : (
                  <div>
                    <div style={{ fontSize: '10.5px', color: '#f59e0b', padding: '4px 0 8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Info size={12} /> No branches discovered for this repository. Type your branch name below.
                    </div>
                    <input
                      type="text"
                      required
                      placeholder="e.g. refs/heads/main, dev, release/2.4"
                      value={newTargetBranch}
                      onChange={e => setNewTargetBranch(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: '8px',
                        backgroundColor: '#262630',
                        border: '1px solid #3f3f4e',
                        color: '#ffffff',
                        fontSize: '12.5px',
                      }}
                    />
                  </div>
                )}
                <div style={{ fontSize: '10.5px', color: '#71717a', marginTop: '4px' }}>
                  Every observed branch is treated equally. Select whichever branch your team cuts releases from.
                </div>
              </div>

              {/* Optional Deployment Pipeline */}
              {pipelines.length > 0 && (
                <div style={{ marginBottom: '14px' }}>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#9ca3af', marginBottom: '6px' }}>
                    Deployment Pipeline (optional)
                  </label>
                  <select
                    value={newPipelineId || 0}
                    onChange={e => setNewPipelineId(Number(e.target.value) || undefined)}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '8px',
                      backgroundColor: '#262630',
                      border: '1px solid #3f3f4e',
                      color: '#ffffff',
                      fontSize: '12.5px',
                    }}
                  >
                    <option value={0}>All project pipelines / Auto-detect</option>
                    {pipelines.map(p => (
                      <option key={p.pipeline_id} value={p.pipeline_id}>
                        {p.pipeline_name} (ID: {p.pipeline_id})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Optional Feature / Epic Scope */}
              <div style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#9ca3af', marginBottom: '6px' }}>
                  Parent Feature / Epic Scope (optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Checkout Redesign (Leave blank for all sprint items)"
                  value={newScopeFeature}
                  onChange={e => setNewScopeFeature(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    backgroundColor: '#262630',
                    border: '1px solid #3f3f4e',
                    color: '#ffffff',
                    fontSize: '12.5px',
                  }}
                />
              </div>

              {/* Optional Target Ship Date */}
              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#9ca3af', marginBottom: '6px' }}>
                  Target Ship Date (optional)
                </label>
                <input
                  type="date"
                  value={newTargetShipDate}
                  onChange={e => setNewTargetShipDate(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    backgroundColor: '#262630',
                    border: '1px solid #3f3f4e',
                    color: '#ffffff',
                    fontSize: '12.5px',
                  }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  style={{
                    padding: '8px 16px',
                    borderRadius: '18px',
                    backgroundColor: 'transparent',
                    border: '1px solid #3f3f4e',
                    color: '#d1d5db',
                    fontSize: '12px',
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  style={{
                    padding: '8px 18px',
                    borderRadius: '18px',
                    backgroundColor: '#00fbfb',
                    border: 'none',
                    color: '#09090b',
                    fontSize: '12px',
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  {creating ? 'Saving...' : 'Save Release'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )

  function renderDimensionCard(
    key: string,
    dim: ReleaseDimension | undefined,
    icon: React.ReactNode,
    subTitle: string
  ) {
    if (!dim) return null
    const isExpanded = !!expandedDims[key]
    const color = getStatusColor(dim.status)

    return (
      <div
        key={key}
        style={{
          backgroundColor: '#1f1f26',
          borderRadius: '12px',
          border: `1px solid ${dim.status === 'red' ? 'rgba(239, 68, 68, 0.45)' : '#2e2f38'}`,
          display: 'flex',
          flexDirection: 'column',
          boxShadow: dim.status === 'red' ? '0 0 16px rgba(239, 68, 68, 0.12)' : 'none',
          overflow: 'hidden',
        }}
      >
        <div style={{ padding: '16px 18px', flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '8px',
                  backgroundColor: '#262630',
                  display: 'grid',
                  placeItems: 'center',
                }}
              >
                {icon}
              </div>
              <div>
                <h4 style={{ margin: 0, fontSize: '13.5px', fontWeight: 700, color: '#ffffff' }}>{dim.name}</h4>
                <div style={{ fontSize: '10.5px', color: '#9ca3af' }}>{subTitle}</div>
              </div>
            </div>
            {renderStatusBadge(dim.status)}
          </div>

          <div style={{ margin: '10px 0 6px' }}>
            <span style={{ fontSize: '22px', fontWeight: 800, color: color }}>
              {dim.score_text}
            </span>
          </div>

          <p style={{ margin: '0 0 12px', fontSize: '12px', lineHeight: 1.5, color: '#d1d5db' }}>
            {dim.summary}
          </p>
        </div>

        {/* Evidence items expander */}
        {dim.evidence_items && dim.evidence_items.length > 0 && (
          <div style={{ borderTop: '1px solid #282830', backgroundColor: '#17171d' }}>
            <button
              type="button"
              onClick={() => toggleDimExpand(key)}
              style={{
                width: '100%',
                padding: '8px 16px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                background: 'transparent',
                border: 'none',
                color: '#9ca3af',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              <span>Evidence Items ({dim.evidence_items.length})</span>
              {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>

            {isExpanded && (
              <div style={{ padding: '0 14px 12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {dim.evidence_items.map((ev, idx) => (
                  <div
                    key={idx}
                    style={{
                      padding: '8px 10px',
                      borderRadius: '6px',
                      backgroundColor: '#212128',
                      border: '1px solid #2e2f38',
                      fontSize: '11px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontFamily: 'ui-monospace,monospace', color: '#00fbfb', fontWeight: 700 }}>
                          #{ev.id}
                        </span>
                        <span style={{ color: '#ffffff', fontWeight: 600 }}>{ev.title}</span>
                      </div>
                      {ev.web_url && (
                        <a
                          href={ev.web_url}
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: '#00fbfb', display: 'grid', placeItems: 'center' }}
                          title="Open in Azure DevOps"
                        >
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                    {ev.details && <div style={{ color: '#9ca3af', fontSize: '10px' }}>{ev.details}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    )
  }
}
