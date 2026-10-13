import {
  assignee,
  buildSprintReport,
  buildTeamDeliverablesReport,
  calculateSprintBusinessDays,
  formatSprintMonthYear,
  prepareMemberDeliverables,
  workItemUrl,
} from '../utils/sprintReport'
import { formatSprintRange, formatWorkDaysRemaining, withListedDates } from '../utils/sprintDates'
import React, { useState, useEffect, useMemo } from 'react'
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  ChevronDown,
  Clock,
  ExternalLink,
  Filter,
  Flame,
  Info,
  Layers,
  ListFilter,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Star,
  User,
  Users,
  Wrench,
  X,
  FileText,
  CheckSquare,
  Trophy,
  Award,
  Sparkles,
  Copy,
  Check,
  Target,
  CheckCircle,
  AlertCircle,
  Mail,
  Send,
  Radio,
  Cpu,
  Zap,
  ChevronRight,
  TrendingDown,
  TrendingUp,
  BarChart3,
  PieChart,
  BookOpen,
  Bug,
  Briefcase,
  Activity,
  Save,
  Trash2,
} from 'lucide-react'
import { api } from '../services/api'
import { usePlugins } from '../context/PluginContext'
import type {
  AdoTeam,
  AdoIteration,
  AdoWorkItem,
  AdoSprintChecksSummary,
  AdoSprintBoardResponse,
  AdoCapacityMember,
  AdoSprintMilestoneSummary,
  AdoMilestoneItem,
  MilestoneAiSummaryResponse
} from '../types/api'
import type {
  DeliverablesReport,
  DeliverablesReportStatus,
  PendingDeliverableItem,
  MemberContributionItem
} from '../types/deliverables'
import {
  buildDeliverablesReport,
  formatReportDate,
  isItemClosedInSprint,
  loadSavedDeliverablesReport,
  saveDeliverablesReportToStorage
} from '../utils/deliverablesReport'
import { SmartStandupView } from './SmartStandupView'
import { buildStandupSummary } from '../utils/standupInsights'

interface SprintBoardPageProps {
  organization: string
  project: string
  pat?: string
  projects?: { id: string; name: string }[]
  onOrganizationChange?: (org: string) => void
  onProjectChange?: (project: string) => void
  onPatChange?: (pat: string) => void
  theme?: 'dark' | 'light'
}

type SubTab = 'Taskboard' | 'Standup' | 'Deliverables' | 'Milestone' | 'Backlog' | 'Capacity' | 'Analytics'
type FilterMode = 'all' | 'closed_without_hours' | 'stale_in_review'
type CapacityMember = AdoCapacityMember & { avatar?: string }

// In-memory module cache so sprint board data persists across navigation transitions and tab switches
const sprintBoardCache = new Map<string, AdoSprintBoardResponse>()
const teamsCache = new Map<string, AdoTeam[]>()
const sprintsCache = new Map<string, AdoIteration[]>()

const SPRINT_CACHE_KEY = (org: string, project: string, teamId: string, iterationId?: string): string => {
  return `${(org || '').toLowerCase()}:${(project || '').toLowerCase()}:${(teamId || '').toLowerCase()}:${(iterationId || '').toLowerCase()}`
}

const TEAMS_CACHE_KEY = (org: string, project: string): string => {
  return `${(org || '').toLowerCase()}:${(project || '').toLowerCase()}`
}

const normalizePersonName = (name: string): string => name.trim().toLowerCase()

const capacityStorageKey = (teamId: string, iterationId?: string): string =>
  `ado_sprint_capacity_${teamId || 'default'}_${iterationId || 'current'}`

function mergeCapacityMembers(adoMembers: CapacityMember[], savedMembers: CapacityMember[], assignees: string[]): CapacityMember[] {
  const byName = new Map<string, CapacityMember>()
  adoMembers.forEach(member => {
    byName.set(normalizePersonName(member.name), { ...member, source: member.source || 'ado' })
  })

  assignees.forEach((name, idx) => {
    const key = normalizePersonName(name)
    if (!byName.has(key)) {
      byName.set(key, {
        id: `cap-assignee-${idx}-${key.replace(/\s+/g, '-')}`,
        name,
        activity: 'Development',
        capacity_per_day: 8,
        days_off: 0,
        source: 'manual',
      })
    }
  })

  savedMembers.forEach(member => {
    const key = normalizePersonName(member.name)
    byName.set(key, {
      ...byName.get(key),
      ...member,
      id: byName.get(key)?.id || member.id,
      name: byName.get(key)?.name || member.name,
      source: member.source || byName.get(key)?.source || 'manual',
    })
  })

  return Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name))
}

function getStoredBoardData(org: string, project: string, teamId: string, iterationId?: string): AdoSprintBoardResponse | null {
  if (!org || !project || !teamId) return null
  const key = SPRINT_CACHE_KEY(org, project, teamId, iterationId)
  if (sprintBoardCache.has(key)) return sprintBoardCache.get(key)!
  try {
    const raw = sessionStorage.getItem(`ado_board_cache_${key}`)
    if (raw) {
      const parsed = JSON.parse(raw) as AdoSprintBoardResponse
      sprintBoardCache.set(key, parsed)
      return parsed
    }
  } catch {}
  return null
}

function storeBoardData(org: string, project: string, teamId: string, iterationId: string | undefined, data: AdoSprintBoardResponse) {
  if (!org || !project || !teamId || !data) return
  const key = SPRINT_CACHE_KEY(org, project, teamId, iterationId)
  sprintBoardCache.set(key, data)
  if (data.iteration?.id) {
    const iterKey = SPRINT_CACHE_KEY(org, project, teamId, data.iteration.id)
    sprintBoardCache.set(iterKey, data)
  }
  try {
    sessionStorage.setItem(`ado_board_cache_${key}`, JSON.stringify(data))
    if (data.iteration?.id) {
      const iterKey = SPRINT_CACHE_KEY(org, project, teamId, data.iteration.id)
      sessionStorage.setItem(`ado_board_cache_${iterKey}`, JSON.stringify(data))
    }
  } catch {}
}

export const SprintBoardPage: React.FC<SprintBoardPageProps> = ({
  organization,
  project,
  pat,
  projects = [],
  onOrganizationChange,
  onProjectChange,
  onPatChange
}) => {
  // Navigation / Tab state
  const [activeSubTab, setActiveSubTab] = useState<SubTab>('Taskboard')

  // Plugin Context Toggles
  const { isPluginActive } = usePlugins()
  const showClosedWithoutHours = isPluginActive('closed_tasks_without_hours')
  const showStaleInReview = isPluginActive('stale_in_review')
  const showMilestone = isPluginActive('milestone_baseline')
  const showAiBriefing = isPluginActive('ai_executive_briefing')
  const showEmailReport = isPluginActive('email_sprint_report')

  // Email Notification Modal State
  const [showEmailModal, setShowEmailModal] = useState<boolean>(false)
  const [emailRecipient, setEmailRecipient] = useState<string>('hrushikesh.boora@octave.com')
  const [emailSending, setEmailSending] = useState<boolean>(false)
  const [emailSentSuccess, setEmailSentSuccess] = useState<boolean>(false)
  const [copiedToClipboard, setCopiedToClipboard] = useState<boolean>(false)
  const [emailNeedsPaste, setEmailNeedsPaste] = useState<boolean>(false)

  // Auto-switch away from Deliverables/Milestone if milestone plugin is disabled
  useEffect(() => {
    if (!showMilestone && (activeSubTab === 'Deliverables' || activeSubTab === 'Milestone')) {
      setActiveSubTab('Taskboard')
    }
  }, [showMilestone, activeSubTab])

  // Reset activeCheckFilter if corresponding plugin is disabled
  useEffect(() => {
    if (!showClosedWithoutHours && activeCheckFilter === 'closed_without_hours') {
      setActiveCheckFilter('all')
    }
    if (!showStaleInReview && activeCheckFilter === 'stale_in_review') {
      setActiveCheckFilter('all')
    }
  }, [showClosedWithoutHours, showStaleInReview])

  // Teams & Iterations
  const [selectedTeamId, setSelectedTeamId] = useState<string>(() => {
    return localStorage.getItem('ado_sprint_selected_team') || ''
  })
  const [teams, setTeams] = useState<AdoTeam[]>(() => {
    return teamsCache.get(TEAMS_CACHE_KEY(organization, project)) || []
  })
  const [selectedIterationId, setSelectedIterationId] = useState<string>(() => {
    return localStorage.getItem('ado_sprint_selected_iteration') || ''
  })
  const [iterations, setIterations] = useState<AdoIteration[]>(() => {
    return sprintsCache.get(SPRINT_CACHE_KEY(organization, project, selectedTeamId || '')) || []
  })

  // Sprint Board Data
  const [boardData, setBoardData] = useState<AdoSprintBoardResponse | null>(() => {
    return getStoredBoardData(organization, project, selectedTeamId, selectedIterationId)
  })
  const [isLoadingTeams, setIsLoadingTeams] = useState(false)
  const [isLoadingSprints, setIsLoadingSprints] = useState(false)
  const [isLoadingBoard, setIsLoadingBoard] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Filters
  const [personFilter, setPersonFilter] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [activeCheckFilter, setActiveCheckFilter] = useState<FilterMode>('all')
  const [showChecksModal, setShowChecksModal] = useState<boolean>(false)
  const [modalActiveTab, setModalActiveTab] = useState<'hours' | 'review'>('hours')
  const [isStarred, setIsStarred] = useState(true)

  // Backlog View State
  const [expandedStoryIds, setExpandedStoryIds] = useState<Set<number>>(new Set())
  const [backlogSearch, setBacklogSearch] = useState<string>('')
  const [backlogTypeFilter, setBacklogTypeFilter] = useState<string>('all')
  const [backlogStateFilter, setBacklogStateFilter] = useState<string>('all')
  const [backlogAssigneeFilter, setBacklogAssigneeFilter] = useState<string>('all')
  const [backlogTagFilter, setBacklogTagFilter] = useState<string>('all')

  // Capacity Planning State
  const [capacityMembers, setCapacityMembers] = useState<CapacityMember[]>([])
  const [newMemberName, setNewMemberName] = useState<string>('')
  const [capacitySavedNotice, setCapacitySavedNotice] = useState<boolean>(false)

  // Analytics View State
  const [analyticsMetric, setAnalyticsMetric] = useState<'hours' | 'items'>('hours')
  const [hoveredDayIndex, setHoveredDayIndex] = useState<number | null>(null)

  // Deliverables Handover Report Center States
  const [deliverablesReport, setDeliverablesReport] = useState<DeliverablesReport | null>(() => {
    return loadSavedDeliverablesReport(organization, project, selectedTeamId, selectedIterationId)
  })
  const [isRegeneratingDeliverables, setIsRegeneratingDeliverables] = useState<boolean>(false)
  const [deliverablesActiveSection, setDeliverablesActiveSection] = useState<
    'completed' | 'pending' | 'members' | 'streams' | 'hygiene'
  >('completed')
  const [milestoneCategoryFilter, setMilestoneCategoryFilter] = useState<'all' | 'features' | 'bugs'>('all')
  const [selectedMilestoneStream, setSelectedMilestoneStream] = useState<string>('all')
  const [milestoneSearch, setMilestoneSearch] = useState<string>('')
  const [aiSummary, setAiSummary] = useState<MilestoneAiSummaryResponse | null>(() => {
    const saved = loadSavedDeliverablesReport(organization, project, selectedTeamId, selectedIterationId)
    return saved?.aiSummary || null
  })
  const [isGeneratingAi, setIsGeneratingAi] = useState<boolean>(false)
  const [copiedSummary, setCopiedSummary] = useState<boolean>(false)

  // If projects is provided and project is empty, initialize project
  useEffect(() => {
    if (!project && projects.length > 0) {
      onProjectChange?.(projects[0].name)
    }
  }, [project, projects, onProjectChange])

  // Load teams when org, project, or pat changes
  useEffect(() => {
    if (!organization || !project) {
      setTeams([])
      return
    }
    const cachedTeams = teamsCache.get(TEAMS_CACHE_KEY(organization, project))
    if (cachedTeams && cachedTeams.length > 0 && teams.length === 0) {
      setTeams(cachedTeams)
    }

    let isCurrent = true
    if (!cachedTeams || cachedTeams.length === 0) {
      setIsLoadingTeams(true)
    }
    api.teams(organization, project, pat)
      .then(res => {
        if (!isCurrent) return
        teamsCache.set(TEAMS_CACHE_KEY(organization, project), res)
        setTeams(res)
        if (res.length > 0) {
          const match = res.find(t => t.id === selectedTeamId || t.name.toLowerCase() === selectedTeamId.toLowerCase())
          const targetTeamId = match ? match.id : res[0].id
          setSelectedTeamId(targetTeamId)
          localStorage.setItem('ado_sprint_selected_team', targetTeamId)
        }
      })
      .catch(err => {
        if (!isCurrent) return
        console.warn('Failed to load teams:', err)
      })
      .finally(() => {
        if (isCurrent) setIsLoadingTeams(false)
      })

    return () => { isCurrent = false }
  }, [organization, project, pat])

  // Load iterations when team changes
  useEffect(() => {
    if (!organization || !project || !selectedTeamId) {
      setIterations([])
      return
    }
    const cachedSprints = sprintsCache.get(SPRINT_CACHE_KEY(organization, project, selectedTeamId))
    if (cachedSprints && cachedSprints.length > 0 && iterations.length === 0) {
      setIterations(cachedSprints)
    }

    let isCurrent = true
    if (!cachedSprints || cachedSprints.length === 0) {
      setIsLoadingSprints(true)
    }
    api.sprints(organization, project, selectedTeamId, pat)
      .then(res => {
        if (!isCurrent) return
        sprintsCache.set(SPRINT_CACHE_KEY(organization, project, selectedTeamId), res)
        setIterations(res)
        if (res.length > 0) {
          const match = res.find(it => it.id === selectedIterationId || it.name === selectedIterationId)
          const current = match || res.find(it => it.time_frame === 'current') || res[0]
          setSelectedIterationId(current.id)
          localStorage.setItem('ado_sprint_selected_iteration', current.id)
        }
      })
      .catch(err => {
        if (!isCurrent) return
        console.warn('Failed to load sprints:', err)
      })
      .finally(() => {
        if (isCurrent) setIsLoadingSprints(false)
      })

    return () => { isCurrent = false }
  }, [organization, project, selectedTeamId, pat])

  // Load board items when team or iteration changes
  const fetchBoardData = (overrideIterationId?: string | unknown) => {
    if (!organization || !project || !selectedTeamId) {
      setBoardData(null)
      return
    }
    const iterToUse = typeof overrideIterationId === 'string' ? overrideIterationId : selectedIterationId
    const cached = getStoredBoardData(organization, project, selectedTeamId, iterToUse)
    if (cached) {
      setBoardData(cached)
    }
    if (!cached && !boardData) {
      setIsLoadingBoard(true)
    }
    setErrorMessage(null)

    api.sprintBoard(organization, project, selectedTeamId, iterToUse || undefined, pat)
      .then(res => {
        storeBoardData(organization, project, selectedTeamId, iterToUse, res)
        setBoardData(res)
        if (res.iteration?.id) {
          setSelectedIterationId(res.iteration.id)
          localStorage.setItem('ado_sprint_selected_iteration', res.iteration.id)
        }
      })
      .catch(err => {
        if (!cached && !boardData) {
          setErrorMessage(err.message || 'Failed to load sprint board')
        } else {
          console.warn('Background board refresh failed:', err)
        }
      })
      .finally(() => {
        setIsLoadingBoard(false)
      })
  }

  // Handle Sync Board button click - refreshes sprints list and board data for current team/iteration
  const handleSyncBoard = async () => {
    if (!organization || !project) return
    setIsLoadingBoard(true)
    setErrorMessage(null)
    try {
      let teamIdToUse = selectedTeamId
      if (!teamIdToUse) {
        const teamList = await api.teams(organization, project, pat)
        teamsCache.set(TEAMS_CACHE_KEY(organization, project), teamList)
        setTeams(teamList)
        if (teamList.length > 0) {
          teamIdToUse = teamList[0].id
          setSelectedTeamId(teamIdToUse)
        }
      }

      if (teamIdToUse) {
        setIsLoadingSprints(true)
        const sprintList = await api.sprints(organization, project, teamIdToUse, pat)
        sprintsCache.set(SPRINT_CACHE_KEY(organization, project, teamIdToUse), sprintList)
        setIterations(sprintList)
        setIsLoadingSprints(false)

        let targetIterationId = selectedIterationId
        if (!targetIterationId || !sprintList.some(s => s.id === targetIterationId)) {
          const current = sprintList.find(s => s.time_frame === 'current') || sprintList[0]
          if (current) {
            targetIterationId = current.id
            setSelectedIterationId(targetIterationId)
            localStorage.setItem('ado_sprint_selected_iteration', targetIterationId)
          }
        }

        const data = await api.sprintBoard(organization, project, teamIdToUse, targetIterationId || undefined, pat)
        storeBoardData(organization, project, teamIdToUse, targetIterationId, data)
        setBoardData(data)
        if (data.iteration?.id) {
          setSelectedIterationId(data.iteration.id)
          localStorage.setItem('ado_sprint_selected_iteration', data.iteration.id)
        }
      }
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to sync sprint board')
    } finally {
      setIsLoadingBoard(false)
      setIsLoadingSprints(false)
    }
  }

  useEffect(() => {
    fetchBoardData()
  }, [organization, project, selectedTeamId, pat])

  // Synchronize Deliverables report from storage or fresh boardData
  useEffect(() => {
    if (!organization || !project || !selectedTeamId) return
    const saved = loadSavedDeliverablesReport(organization, project, selectedTeamId, selectedIterationId)

    // Check if boardData belongs to the currently selected sprint iteration
    const isMatchingBoardData = Boolean(
      boardData &&
      boardData.iteration &&
      (!selectedIterationId || boardData.iteration.id === selectedIterationId)
    )

    if (saved) {
      // Discard report if it has a different iterationId
      if (selectedIterationId && saved.iterationId && saved.iterationId !== selectedIterationId) {
        setDeliverablesReport(null)
        return
      }

      // If matching boardData is loaded, verify the saved report does not contain foreign work items from another sprint,
      // and verify that it is not missing any achieved items that are present in the fresh boardData
      if (isMatchingBoardData && boardData) {
        const boardWorkItemIds = new Set(boardData.work_items.map(w => w.id))
        const savedDeliverableIds = new Set(saved.completedDeliverables.map(item => item.id))
        const hasForeignItems =
          saved.completedDeliverables.length > 0 &&
          boardData.work_items.length > 0 &&
          saved.completedDeliverables.some(item => !boardWorkItemIds.has(item.id))

        const achievedItems = boardData.milestone?.achieved_items || []
        const isMissingAchievedItems =
          achievedItems.length > 0 &&
          achievedItems.some((a: any) => !savedDeliverableIds.has(a.id))

        if (hasForeignItems || isMissingAchievedItems) {
          // Rebuild fresh report from authentic boardData
          const cleanSprint = formatSprintName(boardData.iteration?.name || currentIteration?.name, boardData.iteration?.path || currentIteration?.path)
          const fresh = buildDeliverablesReport(
            boardData,
            organization,
            project,
            selectedTeamId,
            boardData.iteration?.id || selectedIterationId,
            cleanSprint,
            'fresh'
          )
          saveDeliverablesReportToStorage(fresh)
          setDeliverablesReport(fresh)
          return
        }
      }

      setDeliverablesReport(saved)
      if (saved.aiSummary && !aiSummary) {
        setAiSummary(saved.aiSummary)
      }
    } else if (isMatchingBoardData && boardData) {
      const cleanSprint = formatSprintName(boardData.iteration?.name || currentIteration?.name, boardData.iteration?.path || currentIteration?.path)
      const fresh = buildDeliverablesReport(
        boardData,
        organization,
        project,
        selectedTeamId,
        boardData.iteration?.id || selectedIterationId,
        cleanSprint,
        'fresh'
      )
      saveDeliverablesReportToStorage(fresh)
      setDeliverablesReport(fresh)
    } else if (!saved) {
      setDeliverablesReport(null)
    }
  }, [organization, project, selectedTeamId, selectedIterationId, boardData])

  // Explicit user action: Regenerate fresh ADO Deliverables handover data
  const handleRegenerateDeliverables = async () => {
    if (!organization || !project || !selectedTeamId) return
    setIsRegeneratingDeliverables(true)
    try {
      const freshBoard = await api.sprintBoard(
        organization,
        project,
        selectedTeamId,
        selectedIterationId || undefined,
        pat
      )
      storeBoardData(organization, project, selectedTeamId, selectedIterationId, freshBoard)
      setBoardData(freshBoard)

      const cleanSprint = formatSprintName(currentIteration?.name, currentIteration?.path)
      const freshReport = buildDeliverablesReport(
        freshBoard,
        organization,
        project,
        selectedTeamId,
        selectedIterationId,
        cleanSprint,
        'fresh',
        deliverablesReport
      )
      saveDeliverablesReportToStorage(freshReport)
      setDeliverablesReport(freshReport)
    } catch (err: any) {
      const errMsg = err?.message || 'Failed to refresh ADO sprint board data'
      console.warn('Deliverables regeneration failed:', errMsg)
      if (deliverablesReport) {
        const updated = {
          ...deliverablesReport,
          status: 'regenerate_failed' as DeliverablesReportStatus,
          lastRegenerateError: errMsg
        }
        saveDeliverablesReportToStorage(updated)
        setDeliverablesReport(updated)
      }
    } finally {
      setIsRegeneratingDeliverables(false)
    }
  }

  // Handle Team change
  const handleTeamChange = (teamId: string) => {
    setSelectedTeamId(teamId)
    localStorage.setItem('ado_sprint_selected_team', teamId)
    setSelectedIterationId('')
    const cached = getStoredBoardData(organization, project, teamId, '')
    if (cached) {
      setBoardData(cached)
    }
    const saved = loadSavedDeliverablesReport(organization, project, teamId, '')
    if (saved) {
      setDeliverablesReport(saved)
    }
  }

  // Handle Sprint change
  const handleIterationChange = (iterationId: string) => {
    setSelectedIterationId(iterationId)
    localStorage.setItem('ado_sprint_selected_iteration', iterationId)
    const cached = getStoredBoardData(organization, project, selectedTeamId, iterationId)
    if (cached && cached.iteration?.id === iterationId) {
      setBoardData(cached)
    } else {
      setBoardData(null)
    }
    const saved = loadSavedDeliverablesReport(organization, project, selectedTeamId, iterationId)
    setDeliverablesReport(saved)
    fetchBoardData(iterationId)
  }

  // Extract unique assignees for person filter
  const uniqueAssignees = useMemo(() => {
    if (!boardData) return []
    const set = new Set<string>()
    boardData.work_items.forEach(w => {
      if (w.assigned_to_name) set.add(w.assigned_to_name)
    })
    return Array.from(set).sort()
  }, [boardData])

  // Current selected team
  const currentTeam = teams.find(t => t.id === selectedTeamId)

  // Standup Insights Summary for Smart Standup Mode
  const standupSummary = useMemo(() => {
    if (!boardData) {
      return {
        blocked_items: [],
        review_bottlenecks: [],
        workload_gaps: [],
        total_attention_count: 0
      }
    }
    const membersList = (capacityMembers && capacityMembers.length > 0)
      ? capacityMembers.map(m => ({ name: m.name, capacity_per_day: m.capacity_per_day }))
      : uniqueAssignees.map(name => ({ name }))

    return buildStandupSummary(boardData.work_items, membersList)
  }, [boardData, capacityMembers, uniqueAssignees])

  // Clean sprint name helper to prevent GUIDs from ever displaying
  const formatSprintName = (nameOrGuid?: string, path?: string): string => {
    if (!nameOrGuid) return 'Current Sprint'
    const trimmed = nameOrGuid.trim()
    const isGuid = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(trimmed) || /^[0-9a-fA-F-]{30,}$/.test(trimmed)
    if (isGuid) {
      const match = iterations.find(it => it.id === trimmed)
      if (match && match.name && !/^[0-9a-fA-F-]{30,}$/.test(match.name)) {
        return match.name.toLowerCase().includes('sprint') ? match.name : `${match.name} Sprint`
      }
      if (path && (path.includes('\\') || path.includes('/'))) {
        const seg = path.split(/[\\/]/).pop()?.trim()
        if (seg && !/^[0-9a-fA-F-]{30,}$/.test(seg)) {
          return seg.toLowerCase().includes('sprint') ? seg : `${seg} Sprint`
        }
      }
      return 'Sprint'
    }
    return trimmed.toLowerCase().includes('sprint') ? trimmed : `${trimmed} Sprint`
  }

  // Current iteration object
  const listedIteration = iterations.find(it => it.id === (boardData?.iteration?.id || selectedIterationId))
  const currentIteration = withListedDates(boardData?.iteration, listedIteration) || {
    id: selectedIterationId || 'sprint-curr',
    name: selectedIterationId ? 'Selected Sprint' : 'Current Sprint',
    path: project ? `${project}\Sprint` : 'Sprint',
    start_date: undefined,
    finish_date: undefined,
    time_frame: 'current'
  }

  // Date range as Azure DevOps shows it ("October 1 - October 31")
  const formattedDateRange = formatSprintRange(currentIteration?.start_date, currentIteration?.finish_date) ?? 'Sprint Dates Pending'
  const workDaysRemaining = formatWorkDaysRemaining(boardData?.working_days_remaining)

  // Checks summary
  const checksSummary: AdoSprintChecksSummary = boardData?.checks_summary || {
    total_tasks: 0,
    tasks_closed_count: 0,
    tasks_closed_without_hours_count: 0,
    total_user_stories: 0,
    stories_in_review_count: 0,
    stories_in_review_stale_count: 0,
    flagged_item_ids: []
  }

  // Work items separated into User Stories (parents) and Tasks
  const { userStories, tasksByParent, unparentedTasks } = useMemo(() => {
    const stories: AdoWorkItem[] = []
    const tasksMap: Record<number, AdoWorkItem[]> = {}
    const unparented: AdoWorkItem[] = []

    if (!boardData) return { userStories: stories, tasksByParent: tasksMap, unparentedTasks: unparented }

    // Filter work items by person and search query
    const filtered = boardData.work_items.filter(w => {
      if (personFilter !== 'all') {
        if (personFilter === '@Me') {
          // If @Me, check if assigned to user or first word match
          if (!w.assigned_to_name?.toLowerCase().includes('harish') && !w.assigned_to_name?.toLowerCase().includes('boora')) {
            return false
          }
        } else if (w.assigned_to_name !== personFilter) {
          return false
        }
      }

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const matchesTitle = w.title.toLowerCase().includes(q)
        const matchesId = String(w.id).includes(q)
        const matchesAssignee = w.assigned_to_name?.toLowerCase().includes(q) || false
        if (!matchesTitle && !matchesId && !matchesAssignee) return false
      }

      if (activeCheckFilter === 'closed_without_hours') {
        if (!w.is_closed_without_hours) return false
      } else if (activeCheckFilter === 'stale_in_review') {
        if (!w.is_stale_in_review) return false
      }

      return true
    })

    filtered.forEach(w => {
      const typeLower = w.work_item_type.toLowerCase()
      if (typeLower === 'user story' || typeLower === 'product backlog item' || typeLower === 'feature' || typeLower === 'bug') {
        stories.push(w)
      } else if (typeLower === 'task') {
        if (w.parent_id) {
          if (!tasksMap[w.parent_id]) tasksMap[w.parent_id] = []
          tasksMap[w.parent_id].push(w)
        } else {
          unparented.push(w)
        }
      } else {
        // Fallback into story if not task
        stories.push(w)
      }
    })

    // If activeCheckFilter is active, also ensure stories show if their child tasks are flagged
    if (activeCheckFilter === 'closed_without_hours') {
      const parentIdsWithFlaggedTasks = new Set(filtered.map(w => w.parent_id).filter(Boolean))
      boardData.work_items.forEach(w => {
        if (parentIdsWithFlaggedTasks.has(w.id) && !stories.some(s => s.id === w.id)) {
          stories.push(w)
        }
      })
    }

    return { userStories: stories, tasksByParent: tasksMap, unparentedTasks: unparented }
  }, [boardData, personFilter, searchQuery, activeCheckFilter])

  // Columns definition
  const columns: { key: string; label: string; states: string[] }[] = [
    { key: 'todo', label: 'To Do', states: ['to do', 'new'] },
    { key: 'inprogress', label: 'In Progress', states: ['in progress', 'active'] },
    { key: 'inreview', label: 'In Review', states: ['in review', 'resolved'] },
    { key: 'done', label: 'Done', states: ['done', 'closed', 'completed'] },
  ]

  const getColumnForTask = (task: AdoWorkItem) => {
    const stateLower = task.state.toLowerCase()
    for (const col of columns) {
      if (col.states.includes(stateLower)) return col.key
    }
    return 'todo'
  }

  // Flagged items for modal
  const closedWithoutHoursItems = useMemo(() => {
    return boardData?.work_items.filter(w => w.is_closed_without_hours) || []
  }, [boardData])

  const staleInReviewItems = useMemo(() => {
    return boardData?.work_items.filter(w => w.is_stale_in_review) || []
  }, [boardData])

  const healthReportRecipients = useMemo(() => {
    const people = [...closedWithoutHoursItems, ...staleInReviewItems]
      .map(assignee)
      .filter(name => name && name !== 'Unassigned')
    return Array.from(new Set(people)).join('; ')
  }, [closedWithoutHoursItems, staleInReviewItems])

  // Dynamic Milestone calculation
  const computedMilestone = useMemo<AdoSprintMilestoneSummary | null>(() => {
    if (boardData?.milestone) return boardData.milestone
    if (!boardData?.work_items) return null

    const closedStates = ['closed', 'done', 'completed', 'resolved']
    const storyTypes = ['user story', 'product backlog item', 'requirement', 'feature', 'story', 'bug']

    const tasksByParent: Record<number, AdoWorkItem[]> = {}
    boardData.work_items.forEach(w => {
      if (w.work_item_type.toLowerCase() === 'task' && w.parent_id) {
        if (!tasksByParent[w.parent_id]) tasksByParent[w.parent_id] = []
        tasksByParent[w.parent_id].push(w)
      }
    })

    const storyItems = boardData.work_items.filter(w =>
      storyTypes.includes(w.work_item_type.toLowerCase())
    )
    const closedStories = storyItems.filter(w =>
      isItemClosedInSprint(w, boardData.iteration || currentIteration)
    )

    let totalDeliveredHours = 0
    let featuresCount = 0
    let bugsCount = 0
    const achievedItems: AdoMilestoneItem[] = []
    const keyAchievements: string[] = []

    // Fallback classification used only when the backend didn't return a precomputed milestone (e.g. an
    // error on that call). It can't resolve a parent Feature/Epic title without another round trip, so it
    // groups by Area Path alone - still generic (no assumed domain), just coarser than the backend's view.
    closedStories.forEach(story => {
      const typeLower = story.work_item_type.toLowerCase()
      const isBug = typeLower === 'bug'

      let category = 'Feature & Business Value'
      if (isBug) {
        category = 'Bug Fix & Quality'
        bugsCount++
      } else {
        featuresCount++
      }

      const areaLeaf = story.area_path ? story.area_path.split('\\').pop()?.trim() : ''
      const milestoneStream = areaLeaf || 'Unassigned Work'

      const children = tasksByParent[story.id] || []
      const childClosed = children.filter(c => closedStates.includes(c.state.toLowerCase())).length
      const storyHours = story.completed_work || 0
      const childrenHours = children.reduce((acc, c) => acc + (c.completed_work || 0), 0)
      const itemHours = Math.round((storyHours + childrenHours) * 10) / 10
      totalDeliveredHours += itemHours

      const issueSummary = story.description || `No description was recorded on this ${typeLower}.`
      const achievementSummary = story.acceptance_criteria
        ? `Acceptance criteria met: ${story.acceptance_criteria}`
        : `Marked ${story.state} with no acceptance criteria recorded.`

      achievedItems.push({
        id: story.id,
        title: story.title,
        work_item_type: story.work_item_type,
        state: story.state,
        assigned_to_name: story.assigned_to_name,
        assigned_to_avatar: story.assigned_to_avatar,
        completed_date: story.state_change_date || story.changed_date,
        web_url: story.web_url,
        category,
        milestone_stream: milestoneStream,
        hours_delivered: itemHours,
        child_tasks_total: children.length,
        child_tasks_closed: childClosed,
        description: story.description,
        acceptance_criteria: story.acceptance_criteria,
        issue_summary: issueSummary,
        achievement_summary: achievementSummary,
      })

      const who = story.assigned_to_name ? ` (by ${story.assigned_to_name})` : ''
      const hrs = itemHours > 0 ? ` (${itemHours}h)` : ''
      keyAchievements.push(`#${story.id} [${story.work_item_type}] ${story.title}${who}${hrs}`)
    })

    if (totalDeliveredHours === 0) {
      const taskHours = boardData.work_items
        .filter(w => w.work_item_type.toLowerCase() === 'task' && closedStates.includes(w.state.toLowerCase()))
        .reduce((acc, t) => acc + (t.completed_work || 0), 0)
      totalDeliveredHours = Math.round(taskHours * 10) / 10
    }

    const totalStories = storyItems.length
    const closedCount = closedStories.length
    const completionPct = totalStories > 0 ? Math.round((closedCount / totalStories) * 1000) / 10 : 0

    // Build the stream graph from whatever Area Path leaves actually occur - never a fixed list, since
    // the backend's own computation (preferred above) is what resolves parent Feature/Epic names; this
    // fallback only runs when that call failed.
    const streamMap: Record<string, any> = {}
    const streamBucket = (name: string) => {
      if (!streamMap[name]) {
        streamMap[name] = {
          name, total_count: 0, closed_count: 0, delivered_hours: 0, completion_pct: 0,
          issues_addressed_count: 0, next_sprint_baseline_target: 0, next_sprint_recommendation: '',
        }
      }
      return streamMap[name]
    }

    storyItems.forEach(it => {
      const areaLeaf = it.area_path ? it.area_path.split('\\').pop()?.trim() : ''
      streamBucket(areaLeaf || 'Unassigned Work').total_count++
    })

    achievedItems.forEach(it => {
      const bucket = streamBucket(it.milestone_stream || 'Unassigned Work')
      bucket.closed_count++
      bucket.delivered_hours += it.hours_delivered
      bucket.issues_addressed_count++
    })

    Object.values(streamMap).forEach((data: any) => {
      data.completion_pct = data.total_count > 0 ? Math.round((data.closed_count / data.total_count) * 100) : (data.closed_count > 0 ? 100 : 0)
      data.delivered_hours = Math.round(data.delivered_hours * 10) / 10
      const openInStream = Math.max(0, data.total_count - data.closed_count)
      data.next_sprint_baseline_target = data.closed_count > 0 ? data.closed_count : openInStream
      data.next_sprint_recommendation = openInStream > 0
        ? `${openInStream} item(s) in this stream are still open; carry forward into next sprint.`
        : data.closed_count > 0
          ? `All ${data.closed_count} planned item(s) in this stream were completed; hold or raise capacity next sprint.`
          : 'No activity in this stream this sprint.'
    })

    const totalBugsInScope = storyItems.filter(it => it.work_item_type.toLowerCase() === 'bug').length
    const bugResolutionRate = totalBugsInScope > 0 ? Math.round((bugsCount / totalBugsInScope) * 100) : 100

    const streamsByHours = Object.values(streamMap).sort((a: any, b: any) => b.delivered_hours - a.delivered_hours) as any[]
    const hoursTotal = streamsByHours.reduce((acc, d) => acc + d.delivered_hours, 0)
    const recommendedCapacity = hoursTotal > 0
      ? `Based on this sprint's delivered effort: ${streamsByHours.filter(d => d.delivered_hours > 0).slice(0, 3)
          .map(d => `${Math.round((d.delivered_hours * 100) / hoursTotal)}% ${d.name}`).join(', ')}.`
      : 'No delivered effort was recorded this sprint to baseline a capacity split.'

    const openItems = storyItems.filter(it => !closedStates.includes(it.state.toLowerCase()))
    const focusAreas = openItems.map(it => {
      const areaLeaf = it.area_path ? it.area_path.split('\\').pop()?.trim() : ''
      return `Carry forward #${it.id} [${areaLeaf || 'Unassigned Work'}] ${it.title}`
    })

    return {
      total_stories: totalStories,
      closed_stories_count: closedCount,
      open_stories_count: Math.max(0, totalStories - closedCount),
      completion_rate_pct: completionPct,
      total_delivered_hours: Math.round(totalDeliveredHours * 10) / 10,
      features_delivered_count: featuresCount,
      bugs_resolved_count: bugsCount,
      achieved_items: achievedItems,
      key_achievements: keyAchievements,
      graph_data: {
        streams: Object.values(streamMap),
        overall_reliability_baseline_pct: completionPct,
        bug_resolution_rate_pct: bugResolutionRate,
        next_sprint_recommended_capacity: recommendedCapacity,
        next_sprint_focus_areas: focusAreas.length > 0 ? focusAreas : ['All planned work this sprint was closed; no carry-over items.'],
      },
    }
  }, [boardData])

  const filteredMilestoneItems = useMemo(() => {
    const iterToUse = boardData?.iteration || currentIteration
    const rawItems = deliverablesReport?.completedDeliverables || computedMilestone?.achieved_items || []
    const sourceItems = rawItems.filter(item => isItemClosedInSprint(item, iterToUse))
    if (sourceItems.length === 0) return []
    let list = sourceItems

    if (selectedMilestoneStream !== 'all') {
      list = list.filter(i => (i.milestone_stream || '').toLowerCase() === selectedMilestoneStream.toLowerCase())
    }

    if (milestoneCategoryFilter === 'features') {
      list = list.filter(i => i.work_item_type.toLowerCase() !== 'bug')
    } else if (milestoneCategoryFilter === 'bugs') {
      list = list.filter(i => i.work_item_type.toLowerCase() === 'bug')
    }

    if (milestoneSearch.trim()) {
      const q = milestoneSearch.toLowerCase()
      list = list.filter(
        i =>
          i.title.toLowerCase().includes(q) ||
          String(i.id).includes(q) ||
          i.assigned_to_name?.toLowerCase().includes(q) ||
          i.milestone_stream?.toLowerCase().includes(q) ||
          i.issue_summary?.toLowerCase().includes(q) ||
          i.achievement_summary?.toLowerCase().includes(q)
      )
    }

    return list
  }, [deliverablesReport, computedMilestone, selectedMilestoneStream, milestoneCategoryFilter, milestoneSearch])

  const handleGenerateAiMilestone = async () => {
    if (!computedMilestone) return
    setIsGeneratingAi(true)
    const cleanSprint = formatSprintName(currentIteration?.name, currentIteration?.path)
    try {
      const resp = await api.milestoneAiSummary({
        sprint_name: cleanSprint,
        team_name: teams.find(t => t.id === selectedTeamId)?.name || selectedTeamId,
        achieved_items: computedMilestone.achieved_items,
        total_stories: computedMilestone.total_stories,
        closed_stories_count: computedMilestone.closed_stories_count,
        total_delivered_hours: computedMilestone.total_delivered_hours,
      })
      setAiSummary(resp)
    } catch (err: any) {
      console.warn('Failed to generate AI milestone summary:', err)
      setAiSummary({
        summary: `### 🎯 Executive Sprint Milestone Briefing: ${cleanSprint}\n\nDuring **${cleanSprint}**, the team completed **${computedMilestone.closed_stories_count} of ${computedMilestone.total_stories}** scheduled deliverables (${computedMilestone.completion_rate_pct}%) with **${computedMilestone.total_delivered_hours} hours** of verified engineering work delivered.\n\n### 🚨 What The Issues & Challenges Were\nCross-functional backlog dependencies, technical debt, and carryover items required focused triage to protect sprint commitments and delivery cadence.\n\n### ✅ What We Have Achieved\nAll accepted deliverables, user stories, and defect resolutions met definition-of-done criteria, automated testing gates, and established stable quality baselines.\n\n### 📊 Milestone Capability & Next-Sprint Baseline\nDemonstrated reliable team velocity across active capability streams, providing a data-driven capacity baseline for upcoming sprint commitments.`,
        highlights: computedMilestone.key_achievements.slice(0, 5),
        business_impact: 'Key functional capabilities shipped with positive velocity establishing baseline for next sprint.'
      })
    } finally {
      setIsGeneratingAi(false)
    }
  }

  const handleCopySummary = () => {
    if (!aiSummary) return
    const text = `${aiSummary.summary}\n\n**Key Highlights:**\n${(aiSummary.highlights || []).map(h => `- ${h}`).join('\n')}`
    navigator.clipboard.writeText(text)
    setCopiedSummary(true)
    setTimeout(() => setCopiedSummary(false), 2000)
  }

  // Initialize all stories as expanded whenever userStories changes
  useEffect(() => {
    if (userStories.length > 0) {
      setExpandedStoryIds(new Set(userStories.map(s => s.id)))
    }
  }, [userStories])

  // Story expand/collapse handlers
  const toggleStoryExpand = (storyId: number) => {
    setExpandedStoryIds(prev => {
      const next = new Set(prev)
      if (next.has(storyId)) next.delete(storyId)
      else next.add(storyId)
      return next
    })
  }

  const expandAllStories = () => {
    setExpandedStoryIds(new Set(userStories.map(s => s.id)))
  }

  const collapseAllStories = () => {
    setExpandedStoryIds(new Set())
  }

  // Initialize capacity members
  useEffect(() => {
    const key = capacityStorageKey(selectedTeamId, selectedIterationId)
    let savedMembers: CapacityMember[] = []
    try {
      const saved = localStorage.getItem(key)
      if (saved) {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed) && parsed.length > 0) {
          savedMembers = parsed
        }
      }
    } catch {
      // ignore
    }

    const adoMembers = (boardData?.capacity_members || []).map(member => ({
      ...member,
      capacity_per_day: Number(member.capacity_per_day || 0),
      days_off: Number(member.days_off || 0),
      source: member.source || 'ado',
    }))
    setCapacityMembers(mergeCapacityMembers(adoMembers, savedMembers, uniqueAssignees))
  }, [uniqueAssignees, selectedTeamId, selectedIterationId, boardData?.capacity_members])

  const saveCapacitySettings = (updated: CapacityMember[]) => {
    setCapacityMembers(updated)
    const key = capacityStorageKey(selectedTeamId, selectedIterationId)
    try {
      localStorage.setItem(key, JSON.stringify(updated))
      setCapacitySavedNotice(true)
      setTimeout(() => setCapacitySavedNotice(false), 2500)
    } catch {
      // ignore
    }
  }

  const handleUpdateMemberCapacity = (id: string, field: 'activity' | 'capacity_per_day' | 'days_off', value: any) => {
    const updated = capacityMembers.map(m => {
      if (m.id === id) {
        return { ...m, [field]: value }
      }
      return m
    })
    saveCapacitySettings(updated)
  }

  const handleAddCapacityMember = () => {
    if (!newMemberName.trim()) return
    const name = newMemberName.trim()
    const newMember = {
      id: `cap-custom-${Date.now()}`,
      name,
      activity: 'Development',
      capacity_per_day: 8,
      days_off: 0,
      source: 'manual'
    }
    const updated = [...capacityMembers, newMember]
    saveCapacitySettings(updated)
    setNewMemberName('')
  }

  const handleRemoveCapacityMember = (id: string) => {
    const updated = capacityMembers.filter(m => m.id !== id)
    saveCapacitySettings(updated)
  }

  // Product Backlog (items not on sprint board)
  const backlogItems = useMemo(() => {
    return boardData?.backlog_items || []
  }, [boardData])

  const filteredBacklogItems = useMemo(() => {
    let list = backlogItems

    if (backlogTypeFilter !== 'all') {
      list = list.filter(item => {
        const t = item.work_item_type.toLowerCase()
        if (backlogTypeFilter === 'stories') return t.includes('story') || t.includes('backlog') || t.includes('requirement')
        if (backlogTypeFilter === 'bugs') return t.includes('bug')
        if (backlogTypeFilter === 'features') return t.includes('feature')
        return true
      })
    }

    if (backlogStateFilter !== 'all') {
      list = list.filter(item => item.state.toLowerCase() === backlogStateFilter.toLowerCase())
    }

    if (backlogAssigneeFilter !== 'all') {
      if (backlogAssigneeFilter === 'unassigned') {
        list = list.filter(item => !item.assigned_to_name)
      } else {
        list = list.filter(item => item.assigned_to_name?.toLowerCase() === backlogAssigneeFilter.toLowerCase())
      }
    }

    if (backlogTagFilter !== 'all') {
      list = list.filter(item => (item.tags || '').toLowerCase().includes(backlogTagFilter.toLowerCase()))
    }

    if (backlogSearch.trim()) {
      const q = backlogSearch.toLowerCase()
      list = list.filter(item =>
        item.title.toLowerCase().includes(q) ||
        String(item.id).includes(q) ||
        item.work_item_type.toLowerCase().includes(q) ||
        (item.assigned_to_name || '').toLowerCase().includes(q) ||
        (item.tags || '').toLowerCase().includes(q) ||
        (item.area_path || '').toLowerCase().includes(q) ||
        (item.iteration_path || '').toLowerCase().includes(q)
      )
    }

    return list
  }, [backlogItems, backlogTypeFilter, backlogStateFilter, backlogAssigneeFilter, backlogTagFilter, backlogSearch])

  const backlogStats = useMemo(() => {
    const totalCount = backlogItems.length
    let totalPoints = 0
    let businessCount = 0
    let archCount = 0
    const stateCounts: Record<string, number> = {}
    const typeCounts: Record<string, number> = { 'User Story': 0, 'Bug': 0, 'Feature': 0, 'Other': 0 }

    backlogItems.forEach(item => {
      const pts = item.story_points || (item.original_estimate != null && item.original_estimate <= 20 ? item.original_estimate : 0)
      totalPoints += pts

      const va = (item.value_area || '').toLowerCase()
      if (va.includes('arch')) archCount++
      else businessCount++

      const s = item.state || 'New'
      stateCounts[s] = (stateCounts[s] || 0) + 1

      const t = item.work_item_type.toLowerCase()
      if (t.includes('story') || t.includes('backlog') || t.includes('requirement')) typeCounts['User Story']++
      else if (t.includes('bug')) typeCounts['Bug']++
      else if (t.includes('feature')) typeCounts['Feature']++
      else typeCounts['Other']++
    })

    return {
      totalCount,
      totalPoints,
      businessCount,
      archCount,
      stateCounts,
      typeCounts,
      avgSize: totalCount > 0 ? Math.round((totalPoints / totalCount) * 10) / 10 : 0
    }
  }, [backlogItems])

  // Backlog & Analytics Metrics Computations
  const sprintStats = useMemo(() => {
    const allItems = boardData?.work_items || []
    let totalOriginal = 0
    let totalRemaining = 0
    let totalCompleted = 0
    let totalPoints = 0
    let completedPoints = 0

    const stateDistribution: Record<string, { count: number; hours: number }> = {
      'To Do': { count: 0, hours: 0 },
      'In Progress': { count: 0, hours: 0 },
      'In Review': { count: 0, hours: 0 },
      'Done': { count: 0, hours: 0 },
    }

    const typeDistribution: Record<string, number> = {
      'User Story': 0,
      'Bug': 0,
      'Task': 0,
      'Feature': 0,
      'Other': 0,
    }

    const memberEffort: Record<string, { completed: number; remaining: number; total: number }> = {}

    allItems.forEach(item => {
      const rem = item.remaining_work || 0
      const comp = item.completed_work || 0
      const orig = item.original_estimate || 0

      totalOriginal += orig
      totalRemaining += rem
      totalCompleted += comp

      const t = item.work_item_type.toLowerCase()
      if (t.includes('story') || t.includes('backlog')) typeDistribution['User Story'] += 1
      else if (t.includes('bug')) typeDistribution['Bug'] += 1
      else if (t.includes('task')) typeDistribution['Task'] += 1
      else if (t.includes('feature')) typeDistribution['Feature'] += 1
      else typeDistribution['Other'] += 1

      const s = item.state.toLowerCase()
      let category = 'To Do'
      if (s === 'in progress' || s === 'active') category = 'In Progress'
      else if (s === 'in review' || s === 'resolved') category = 'In Review'
      else if (s === 'done' || s === 'closed' || s === 'completed') category = 'Done'

      stateDistribution[category].count += 1
      stateDistribution[category].hours += (comp + rem)

      const member = item.assigned_to_name || 'Unassigned'
      if (!memberEffort[member]) memberEffort[member] = { completed: 0, remaining: 0, total: 0 }
      memberEffort[member].completed += comp
      memberEffort[member].remaining += rem
      memberEffort[member].total += (comp + rem)
    })

    userStories.forEach(s => {
      const pts = (s as any).story_points || (s as any).points || (s.original_estimate != null && s.original_estimate <= 20 ? s.original_estimate : 3)
      totalPoints += pts
      const isDone = ['done', 'closed', 'completed', 'resolved'].includes(s.state.toLowerCase())
      if (isDone) completedPoints += pts
    })

    const workingDays = Math.max(
      1,
      boardData?.sprint_working_days ||
        calculateSprintBusinessDays(boardData?.iteration?.start_date || currentIteration?.start_date, boardData?.iteration?.finish_date || currentIteration?.finish_date) ||
        boardData?.working_days_remaining ||
        10
    )
    const requiredDailyBurn = Math.round((totalRemaining / workingDays) * 10) / 10
    const totalSprintWork = totalCompleted + totalRemaining
    const percentDelivered = totalSprintWork > 0 ? Math.round((totalCompleted / totalSprintWork) * 100) : 0

    let healthStatus: 'On Track' | 'At Risk' | 'Behind Schedule' = 'On Track'
    if (percentDelivered < 40 && workingDays <= 4) healthStatus = 'Behind Schedule'
    else if (percentDelivered < 60 && workingDays <= 5) healthStatus = 'At Risk'

    return {
      totalOriginal: Math.round(totalOriginal * 10) / 10,
      totalRemaining: Math.round(totalRemaining * 10) / 10,
      totalCompleted: Math.round(totalCompleted * 10) / 10,
      totalSprintWork: Math.round(totalSprintWork * 10) / 10,
      totalPoints,
      completedPoints,
      percentDelivered,
      workingDays,
      requiredDailyBurn,
      healthStatus,
      stateDistribution,
      typeDistribution,
      memberEffort,
    }
  }, [boardData, userStories, currentIteration])

  // Capacity Stats Computation
  const capacityStats = useMemo(() => {
    const workingDays = Math.max(
      1,
      boardData?.sprint_working_days ||
        calculateSprintBusinessDays(boardData?.iteration?.start_date || currentIteration?.start_date, boardData?.iteration?.finish_date || currentIteration?.finish_date) ||
        boardData?.working_days_remaining ||
        10
    )
    let totalTeamCapacity = 0
    let totalAssignedHours = 0

    const activityCapacity: Record<string, { capacity: number; assigned: number }> = {
      'Development': { capacity: 0, assigned: 0 },
      'Testing': { capacity: 0, assigned: 0 },
      'Design': { capacity: 0, assigned: 0 },
      'Documentation': { capacity: 0, assigned: 0 },
      'Requirements': { capacity: 0, assigned: 0 },
      'Deployment': { capacity: 0, assigned: 0 },
    }

    const memberDetails = capacityMembers.map(m => {
      const availableDays = Math.max(0, workingDays - (m.days_off || 0))
      const individualCap = Math.round(availableDays * (m.capacity_per_day || 6) * 10) / 10
      totalTeamCapacity += individualCap

      const assignedTasks = (boardData?.work_items || []).filter(w => {
        const samePerson = normalizePersonName(w.assigned_to_name || '') === normalizePersonName(m.name)
        const isOpen = !['done', 'closed', 'completed', 'resolved'].includes(w.state.toLowerCase())
        return samePerson && isOpen
      })
      const assignedHours = Math.round(assignedTasks.reduce((sum, t) => {
        if (t.remaining_work != null) return sum + t.remaining_work
        if (t.original_estimate != null) return sum + Math.max(0, t.original_estimate - (t.completed_work || 0))
        return sum
      }, 0) * 10) / 10
      const missingEstimateCount = assignedTasks.filter(t => t.remaining_work == null && t.original_estimate == null).length
      const completedHours = Math.round((boardData?.work_items || [])
        .filter(w => normalizePersonName(w.assigned_to_name || '') === normalizePersonName(m.name))
        .reduce((sum, t) => sum + (t.completed_work || 0), 0) * 10) / 10
      totalAssignedHours += assignedHours

      const act = m.activity || 'Development'
      if (!activityCapacity[act]) activityCapacity[act] = { capacity: 0, assigned: 0 }
      activityCapacity[act].capacity += individualCap
      activityCapacity[act].assigned += assignedHours

      const utilization = individualCap > 0 ? Math.round((assignedHours / individualCap) * 100) : 0
      const isOverloaded = assignedHours > individualCap

      return {
        ...m,
        availableDays,
        individualCap,
        assignedHours,
        completedHours,
        missingEstimateCount,
        utilization,
        isOverloaded,
      }
    })

    const teamUtilization = totalTeamCapacity > 0 ? Math.round((totalAssignedHours / totalTeamCapacity) * 100) : 0

    return {
      workingDays,
      totalTeamCapacity: Math.round(totalTeamCapacity * 10) / 10,
      totalAssignedHours: Math.round(totalAssignedHours * 10) / 10,
      teamUtilization,
      activityCapacity,
      memberDetails,
    }
  }, [capacityMembers, boardData, currentIteration])

  // Burndown Data Points Computation
  const burndownData = useMemo(() => {
    const daysTotal = 10
    const startEffort = analyticsMetric === 'hours' ? (sprintStats.totalSprintWork || 120) : (boardData?.work_items.length || 24)
    const currentRemaining = analyticsMetric === 'hours' ? sprintStats.totalRemaining : (boardData?.work_items.filter(w => !['done', 'closed', 'completed', 'resolved'].includes(w.state.toLowerCase())).length || 8)
    const currentCompleted = analyticsMetric === 'hours' ? sprintStats.totalCompleted : (boardData?.work_items.filter(w => ['done', 'closed', 'completed', 'resolved'].includes(w.state.toLowerCase())).length || 16)

    const points = []
    for (let day = 1; day <= daysTotal; day++) {
      const ideal = Math.max(0, Math.round((startEffort - (startEffort / (daysTotal - 1)) * (day - 1)) * 10) / 10)
      let actual = null
      let completed = null
      if (day <= 6) {
        const factor = (day - 1) / 5
        actual = Math.max(0, Math.round((startEffort - (startEffort - currentRemaining) * factor) * 10) / 10)
        completed = Math.round((currentCompleted * factor) * 10) / 10
      }

      points.push({
        day,
        label: `Day ${day}`,
        ideal,
        actual,
        completed,
      })
    }
    return points
  }, [sprintStats, analyticsMetric, boardData])

  return (
    <div className="sprintBoardContainer">
      {/* 0. Top Connection & Discovery Toolbar */}
      <div className="adoConnectBar">
        <div className="adoConnectBarLeft">
          <div className="adoConnectItem">
            <span className="adoConnectLabel">Org:</span>
            <input
              type="text"
              className="adoConnectInput"
              placeholder="Organization"
              value={organization}
              onChange={(e) => onOrganizationChange?.(e.target.value)}
            />
          </div>

          <div className="adoConnectItem">
            <span className="adoConnectLabel">PAT:</span>
            <input
              type="password"
              className="adoConnectInput"
              placeholder={pat ? '••••••••••••••••' : 'PAT Token'}
              value={pat || ''}
              onChange={(e) => onPatChange?.(e.target.value)}
              autoComplete="off"
            />
          </div>

          <div className="adoConnectItem">
            <span className="adoConnectLabel">Project:</span>
            <div className="adoCustomSelectWrapper">
              <select
                className="adoCustomSelect"
                value={project}
                onChange={(e) => onProjectChange?.(e.target.value)}
              >
                <option value="">Select Project</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.name}>
                    {p.name}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} className="adoSelectArrow" />
            </div>
          </div>
        </div>

        <div className="adoConnectBarRight">
          <button
            type="button"
            className="adoConnectRefreshBtn"
            onClick={handleSyncBoard}
            title="Sync Sprint Board"
          >
            <RefreshCw size={13} className={isLoadingBoard || isLoadingTeams || isLoadingSprints ? 'spin' : ''} />
            <span>Sync Board</span>
          </button>
        </div>
      </div>

      {/* 1. ADO Top Blade / Header Bar (Exact match to Azure DevOps) */}
      <div className="adoBoardHeader">
        <div className="adoBoardHeaderLeft">
          {/* Team Dropdown */}
          <div className="adoTeamSelector">
            <div className="adoTeamIcon">
              <Users size={16} color="#0078d4" />
            </div>
            <select
              className="adoTeamSelect"
              value={selectedTeamId}
              onChange={e => handleTeamChange(e.target.value)}
              title="Select Team"
            >
              {teams.length === 0 ? (
                <option value="">Select Team</option>
              ) : (
                teams.map(t => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))
              )}
            </select>
            <ChevronDown size={14} className="adoSelectArrow" />
          </div>

          {/* Star favorite toggle */}
          <button
            type="button"
            className={`adoIconBtn ${isStarred ? 'starred' : ''}`}
            onClick={() => setIsStarred(!isStarred)}
            title="Favorite this board"
          >
            <Star size={15} fill={isStarred ? '#ffb900' : 'none'} color={isStarred ? '#ffb900' : 'currentColor'} />
          </button>

          {/* Members icon */}
          <button type="button" className="adoIconBtn" title="Team members">
            <Users size={15} />
          </button>
        </div>

        {/* Right action buttons */}
        <div className="adoBoardHeaderRight">
          <button
            type="button"
            className="adoPrimaryBtn"
            onClick={() => {
              if (organization && project) {
                window.open(`https://dev.azure.com/${organization}/${project}/_workitems/create/Task`, '_blank')
              }
            }}
          >
            <Plus size={15} />
            <span>New Work Item</span>
            <ChevronDown size={13} style={{ marginLeft: '4px' }} />
          </button>

          <button
            type="button"
            className="adoSecondaryBtn"
            onClick={() => alert('Azure Boards Column Options: Columns are configured to standard agile workflow (To Do, In Progress, In Review, Done).')}
          >
            <Wrench size={14} />
            <span>Column Options</span>
          </button>
        </div>
      </div>

      {/* 2. Sub Navigation Tabs: Taskboard, Standup, Deliverables, Backlog, Capacity, Analytics */}
      <div className="adoSubNavTabs">
        {(['Taskboard', 'Standup', 'Deliverables', 'Backlog', 'Capacity', 'Analytics'] as SubTab[])
          .filter(tab => tab !== 'Deliverables' || showMilestone)
          .map(tab => {
            const count = tab === 'Deliverables'
              ? deliverablesReport?.capacityEffortSummary?.closedStoriesCount ?? computedMilestone?.closed_stories_count ?? 0
              : tab === 'Standup'
              ? standupSummary.total_attention_count
              : 0
            const isActive = activeSubTab === tab || (tab === 'Deliverables' && (activeSubTab as any) === 'Milestone')
            return (
              <button
                key={tab}
                type="button"
                className={`adoSubNavTab ${isActive ? 'active' : ''}`}
                onClick={() => setActiveSubTab(tab)}
              >
                {tab === 'Deliverables' && <Trophy size={13} style={{ marginRight: '5px' }} />}
                {tab === 'Standup' && <ShieldAlert size={13} style={{ marginRight: '5px', color: count > 0 ? '#ef4444' : undefined }} />}
                {tab}
                {tab === 'Deliverables' && count > 0 && (
                  <span className="adoTabBadge">{count}</span>
                )}
                {tab === 'Standup' && count > 0 && (
                  <span className="adoTabBadge" style={{ background: '#ef4444', color: '#ffffff' }}>{count}</span>
                )}
              </button>
            )
          })}
      </div>

      {/* 3. Secondary Toolbar (Sprint selector, Person filter, Burndown & Work days remaining) */}
      <div className="adoSecondaryToolbar">
        <div className="adoSecondaryLeft">
          {/* Sprint / Iteration Dropdown */}
          <div className="adoSprintSelector">
            <Calendar size={14} className="adoToolbarIcon" />
            <select
              className="adoSprintSelect"
              value={selectedIterationId || currentIteration.id}
              onChange={e => handleIterationChange(e.target.value)}
            >
              {iterations.length === 0 ? (
                <option value={currentIteration.id}>{formatSprintName(currentIteration.name, currentIteration.path)}</option>
              ) : (
                <>
                  {!iterations.some(it => it.id === (selectedIterationId || currentIteration.id)) && currentIteration.id && (
                    <option value={currentIteration.id}>{formatSprintName(currentIteration.name, currentIteration.path)}</option>
                  )}
                  {iterations.map(it => (
                    <option key={it.id} value={it.id}>
                      {formatSprintName(it.name, it.path)} {it.time_frame === 'current' ? '(Current)' : ''}
                    </option>
                  ))}
                </>
              )}
            </select>
            <ChevronDown size={13} className="adoSelectArrow" />
          </div>

          {/* Person Filter */}
          <div className="adoPersonSelector">
            <User size={14} className="adoToolbarIcon" />
            <select
              className="adoPersonSelect"
              value={personFilter}
              onChange={e => setPersonFilter(e.target.value)}
            >
              <option value="all">Person: All</option>
              <option value="@Me">Person: @Me</option>
              {uniqueAssignees.map(name => (
                <option key={name} value={name}>
                  Person: {name}
                </option>
              ))}
            </select>
            <ChevronDown size={13} className="adoSelectArrow" />
          </div>

          {/* Search box */}
          <div className="adoSearchBox">
            <Search size={13} className="adoSearchIcon" />
            <input
              type="text"
              placeholder="Filter by keyword or #ID..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button type="button" className="adoClearSearch" onClick={() => setSearchQuery('')}>
                <X size={12} />
              </button>
            )}
          </div>
        </div>

        {/* Right side: Date range, work days remaining, and burndown chart preview */}
        <div className="adoSecondaryRight">
          <div className="adoSprintDateInfo">
            <div className="adoSprintDateRange">{formattedDateRange}</div>
            <div className="adoSprintRemaining">
              {workDaysRemaining}
            </div>
          </div>

          {/* Burndown icon widget matching the screenshot */}
          <div
            className="adoBurndownWidget"
            title="Sprint Burndown trend"
            onClick={() => setActiveSubTab('Analytics')}
          >
            <svg width="44" height="26" viewBox="0 0 44 26" className="adoBurndownSvg">
              {/* Blue polygon mountain shape from Azure UI */}
              <polygon
                points="8,26 18,2 30,2 38,26"
                fill="#0078d4"
              />
              <line x1="0" y1="25" x2="44" y2="25" stroke="#71717a" strokeWidth="1" />
            </svg>
          </div>

          <button
            type="button"
            className="adoRefreshBtn"
            onClick={() => fetchBoardData(selectedIterationId)}
            title="Refresh sprint items"
          >
            <RefreshCw size={14} className={isLoadingBoard ? 'spin' : ''} />
          </button>
        </div>
      </div>

      {/* 4. Sprint Compliance & Health Checks Bar (Controlled by Plugins & only visible on Taskboard tab) */}
      {activeSubTab === 'Taskboard' && (showClosedWithoutHours || showStaleInReview || showEmailReport) && (
        <div className="sprintChecksBar">
          <div className="sprintChecksBarLeft">
            <div className="sprintChecksTitle">
              <ShieldAlert size={16} color="#0078d4" />
              <span>Sprint Health Checks</span>
            </div>

            {/* Check 1 Pill */}
            {showClosedWithoutHours && (
              <button
                type="button"
                className={`sprintCheckBadge ${checksSummary.tasks_closed_without_hours_count > 0 ? 'warning' : 'ok'} ${activeCheckFilter === 'closed_without_hours' ? 'active' : ''}`}
                onClick={() => {
                  setActiveCheckFilter(activeCheckFilter === 'closed_without_hours' ? 'all' : 'closed_without_hours')
                }}
                title="Click to filter taskboard to tasks closed with blank hours"
              >
                <AlertTriangle size={13} />
                <span>
                  <b>Check 1:</b> Tasks Closed With Blank Hours: <b>{checksSummary.tasks_closed_without_hours_count}</b>
                </span>
              </button>
            )}

            {/* Check 2 Pill */}
            {showStaleInReview && (
              <button
                type="button"
                className={`sprintCheckBadge ${checksSummary.stories_in_review_stale_count > 0 ? 'danger' : 'ok'} ${activeCheckFilter === 'stale_in_review' ? 'active' : ''}`}
                onClick={() => {
                  setActiveCheckFilter(activeCheckFilter === 'stale_in_review' ? 'all' : 'stale_in_review')
                }}
                title="Click to filter taskboard to these stories"
              >
                <Clock size={13} />
                <span>
                  <b>Check 2:</b> In Review &gt; 4 Working Days: <b>{checksSummary.stories_in_review_stale_count}</b>
                </span>
              </button>
            )}

            {activeCheckFilter !== 'all' && (
              <button
                type="button"
                className="sprintFilterClearBtn"
                onClick={() => setActiveCheckFilter('all')}
              >
                Clear Filter <X size={12} />
              </button>
            )}
          </div>

          <div className="sprintChecksBarRight">
            <button
              type="button"
              className="sprintAuditBtn"
              onClick={() => setShowChecksModal(true)}
            >
              <ListFilter size={14} />
              <span>View Health Report</span>
              {(checksSummary.tasks_closed_without_hours_count > 0 || checksSummary.stories_in_review_stale_count > 0) && (
                <span className="sprintBadgeCount">
                  {checksSummary.tasks_closed_without_hours_count + checksSummary.stories_in_review_stale_count}
                </span>
              )}
            </button>

            {/* Plugin: Email Sprint Report Button */}
            {showEmailReport && (
              <button
                type="button"
                className="sprintEmailBtn"
                onClick={() => {
                  setEmailSentSuccess(false)
                  setEmailRecipient(healthReportRecipients || emailRecipient)
                  setShowEmailModal(true)
                }}
                title="Send Sprint Health & Hygiene Report Email"
              >
                <Mail size={14} />
                <span>Send Email Report</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* 5. Main Taskboard or Other SubTabs */}
      {activeSubTab === 'Taskboard' ? (
        <div className="adoTaskboardWrapper">
          {/* Smart Standup Quick Teaser Banner on Taskboard */}
          {boardData && (
            <div className="adoTaskboardStandupBanner" onClick={() => setActiveSubTab('Standup')}>
              <div className="adoStandupBannerLeft">
                <div className="adoStandupBannerIcon">🚨</div>
                <div className="adoStandupBannerInfo">
                  <span className="adoStandupBannerTitle">
                    <b>Smart Standup Mode</b> &bull; Who needs help today?
                  </span>
                  <span className="adoStandupBannerStats">
                    {standupSummary.total_attention_count > 0 ? (
                      <>
                        {standupSummary.blocked_items.length > 0 && (
                          <span className="standupBadge critical">{standupSummary.blocked_items.length} blocked</span>
                        )}
                        {standupSummary.review_bottlenecks.length > 0 && (
                          <span className="standupBadge warning">{standupSummary.review_bottlenecks.length} review bottlenecks</span>
                        )}
                        {standupSummary.workload_gaps.length > 0 && (
                          <span className="standupBadge info">{standupSummary.workload_gaps.length} available</span>
                        )}
                      </>
                    ) : (
                      <span className="standupBadge success">All clear &mdash; 0 blockers</span>
                    )}
                  </span>
                </div>
              </div>
              <button type="button" className="adoStandupLaunchBtn">
                Start 2-Min Standup &rarr;
              </button>
            </div>
          )}

          {/* Deliverables Quick Teaser Banner on Taskboard */}
          {(deliverablesReport || (computedMilestone && computedMilestone.total_stories > 0)) && (
            <div className="adoTaskboardMilestoneBar" onClick={() => setActiveSubTab('Deliverables')}>
              <div className="adoMilestoneBarLeft">
                <Trophy size={15} color="#f59e0b" />
                <span>
                  <b>Sprint Deliverables:</b> <b>{deliverablesReport?.capacityEffortSummary?.closedStoriesCount ?? computedMilestone?.closed_stories_count ?? 0}</b> of <b>{deliverablesReport?.capacityEffortSummary?.totalStories ?? computedMilestone?.total_stories ?? 0}</b> stories closed ({deliverablesReport?.capacityEffortSummary?.completionRatePct ?? computedMilestone?.completion_rate_pct ?? 0}% delivered)
                </span>
                {((deliverablesReport?.capacityEffortSummary?.totalDeliveredHours ?? computedMilestone?.total_delivered_hours ?? 0) > 0) && (
                  <span className="adoMilestoneHoursPill">
                    ⚡ {deliverablesReport?.capacityEffortSummary?.totalDeliveredHours ?? computedMilestone?.total_delivered_hours}h verified
                  </span>
                )}
              </div>
              <button type="button" className="adoMilestoneViewBtn">
                View Sprint Deliverables Handover &rarr;
              </button>
            </div>
          )}
          {isLoadingBoard && !boardData && (
            <div className="adoBoardLoading">
              <RefreshCw size={24} className="spin" color="#0078d4" />
              <span>Loading Sprint Tasks...</span>
            </div>
          )}

          {errorMessage && !boardData && (
            <div className="adoBoardError">
              <AlertTriangle size={18} color="#ef4444" />
              <span>{errorMessage}</span>
              <button type="button" onClick={fetchBoardData} className="adoRetryBtn">Retry</button>
            </div>
          )}

          {(!isLoadingBoard || boardData) && (
            <div className="adoTaskboardTable">
              {/* Column Headers */}
              <div className="adoTaskboardHeaderRow">
                <div className="adoStoryHeaderCol">
                  <span>User Story / Bug</span>
                </div>
                {columns.map(col => {
                  // Count tasks in this column
                  let count = 0
                  Object.values(tasksByParent).forEach(list => {
                    count += list.filter(t => getColumnForTask(t) === col.key).length
                  })
                  count += unparentedTasks.filter(t => getColumnForTask(t) === col.key).length

                  return (
                    <div key={col.key} className="adoTaskColHeader">
                      <span className="adoTaskColTitle">{col.label}</span>
                      <span className="adoTaskColCount">{count}</span>
                    </div>
                  )
                })}
              </div>

              {/* Swimlane Rows: Each User Story gets a row with its child tasks */}
              {userStories.map(story => {
                const childTasks = tasksByParent[story.id] || []
                const completedTasks = childTasks.filter(t => ['done', 'closed', 'completed'].includes(t.state.toLowerCase())).length

                return (
                  <div key={story.id} className={`adoSwimlaneRow ${story.is_stale_in_review && showStaleInReview ? 'staleReviewRow' : ''}`}>
                    {/* Story Left Column */}
                    <div className="adoStoryCol">
                      <div className={`adoStoryCard ${story.is_stale_in_review && showStaleInReview ? 'flaggedStory' : ''}`}>
                        <div className="adoStoryCardTop">
                          <span className={`adoWorkItemTypeIcon ${story.work_item_type.toLowerCase().includes('bug') ? 'bug' : 'story'}`}>
                            {story.work_item_type.toLowerCase().includes('bug') ? '🐞' : '📖'}
                          </span>
                          <a
                            href={story.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${story.id}`}
                            target="_blank"
                            rel="noreferrer"
                            className="adoWorkItemId"
                          >
                            #{story.id}
                          </a>
                          <span className={`adoStateBadge ${story.state.toLowerCase().replace(/\s+/g, '')}`}>
                            {story.state}
                          </span>
                        </div>

                        <div className="adoStoryTitle" title={story.title}>
                          {story.title}
                        </div>

                        {/* Stale In Review Warning Badge (Check 2) */}
                        {story.is_stale_in_review && showStaleInReview && (
                          <div className="adoStoryReviewWarning" title="Excludes Saturdays & Sundays">
                            <Clock size={12} />
                            <span>
                              <b>{story.business_days_in_review} working days</b> in review
                            </span>
                          </div>
                        )}

                        <div className="adoStoryFooter">
                          <div className="adoStoryAssignee">
                            <div className="adoAvatarSmall" title={story.assigned_to_name || 'Unassigned'}>
                              {story.assigned_to_name ? story.assigned_to_name.charAt(0).toUpperCase() : '?'}
                            </div>
                            <span className="adoAssigneeName">{story.assigned_to_name || 'Unassigned'}</span>
                          </div>

                          <div className="adoStoryProgress" title={childTasks.length > 0 ? `${completedTasks} of ${childTasks.length} tasks completed` : 'No child tasks linked'}>
                            <span>{childTasks.length > 0 ? `${completedTasks}/${childTasks.length} done` : 'No tasks'}</span>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Columns for this story's child tasks */}
                    {columns.map(col => {
                      const colTasks = childTasks.filter(t => getColumnForTask(t) === col.key)

                      return (
                        <div key={col.key} className="adoTaskColCell">
                          {colTasks.map(task => (
                            <div
                              key={task.id}
                              className={`adoTaskCard ${task.is_closed_without_hours && showClosedWithoutHours ? 'flaggedTaskWithoutHours' : ''}`}
                            >
                              <div className="adoTaskCardHeader">
                                <div className="adoTaskTypeRow">
                                  <span className="adoTaskTypeTag">📋 Task</span>
                                  <a
                                    href={task.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${task.id}`}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="adoTaskItemId"
                                  >
                                    #{task.id}
                                  </a>
                                </div>
                                <span className={`adoStateBadge ${task.state.toLowerCase().replace(/\s+/g, '')}`}>
                                  {task.state}
                                </span>
                              </div>

                              <div className="adoTaskCardTitle" title={task.title}>
                                {task.title}
                              </div>

                              {/* Flagged Check 1 Alert on the card */}
                              {task.is_closed_without_hours && showClosedWithoutHours && (
                                <div className="adoTaskClosedAlert" title="Task is closed but completed hours are left blank!">
                                  <AlertTriangle size={12} />
                                  <span>Closed with blank hours!</span>
                                </div>
                              )}

                              <div className="adoTaskCardFooter">
                                <div className="adoTaskAssignee">
                                  <div className="adoAvatarTiny" title={task.assigned_to_name || 'Unassigned'}>
                                    {task.assigned_to_name ? task.assigned_to_name.charAt(0).toUpperCase() : '?'}
                                  </div>
                                  <span className="adoTaskAssigneeName">{task.assigned_to_name?.split(' ')[0] || 'Unassigned'}</span>
                                </div>

                                <div className="adoTaskHours">
                                  {task.completed_work != null ? (
                                    <span className="hoursLogged" title="Completed work hours">{task.completed_work}h done</span>
                                  ) : task.remaining_work != null ? (
                                    <span className="hoursRem" title="Remaining work hours">{task.remaining_work}h rem</span>
                                  ) : (
                                    <span className="hoursNone" title="No hours recorded">-</span>
                                  )}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )
                    })}
                  </div>
                )
              })}

              {/* Unparented Tasks Swimlane (if any) */}
              {unparentedTasks.length > 0 && (
                <div className="adoSwimlaneRow unparentedRow">
                  <div className="adoStoryCol">
                    <div className="adoStoryCard unparentedStoryCard">
                      <div className="adoStoryTitle">
                        <b>Unparented Tasks</b>
                      </div>
                      <p style={{ margin: 0, fontSize: '11px', color: '#71717a' }}>
                        {unparentedTasks.length} tasks without a parent story
                      </p>
                    </div>
                  </div>

                  {columns.map(col => {
                    const colTasks = unparentedTasks.filter(t => getColumnForTask(t) === col.key)

                    return (
                      <div key={col.key} className="adoTaskColCell">
                        {colTasks.map(task => (
                          <div
                            key={task.id}
                            className={`adoTaskCard ${task.is_closed_without_hours ? 'flaggedTaskWithoutHours' : ''}`}
                          >
                            <div className="adoTaskCardHeader">
                              <span className="adoTaskTypeTag">📋 Task</span>
                              <a
                                href={task.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${task.id}`}
                                target="_blank"
                                rel="noreferrer"
                                className="adoTaskItemId"
                              >
                                #{task.id}
                              </a>
                            </div>

                            <div className="adoTaskCardTitle">{task.title}</div>

                            {task.is_closed_without_hours && (
                              <div className="adoTaskClosedAlert" title="Task is closed but completed hours are left blank!">
                                <AlertTriangle size={12} />
                                <span>Closed with blank hours!</span>
                              </div>
                            )}

                            <div className="adoTaskCardFooter">
                              <div className="adoTaskAssignee">
                                <span className="adoTaskAssigneeName">{task.assigned_to_name || 'Unassigned'}</span>
                              </div>
                              <div className="adoTaskHours">
                                {task.completed_work != null ? (
                                  <span className="hoursLogged" title="Completed work hours">{task.completed_work}h done</span>
                                ) : task.remaining_work != null ? (
                                  <span className="hoursRem" title="Remaining work hours">{task.remaining_work}h rem</span>
                                ) : (
                                  <span className="hoursNone" title="No hours recorded">-</span>
                                )}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )
                  })}
                </div>
              )}

              {userStories.length === 0 && unparentedTasks.length === 0 && (
                <div className="adoBoardEmpty">
                  {!pat ? (
                    <div className="adoPatPromptCard">
                      <div className="adoEmptyPatIcon">
                        <ShieldAlert size={40} color="#f59e0b" />
                      </div>
                      <h3>Personal Access Token (PAT) Required</h3>
                      <p>
                        To fetch your team's real user stories and tasks from <b>{organization || 'Azure DevOps'}</b>, please enter your PAT in the <b>PAT</b> field at the top toolbar and click <b>Sync Board</b>.
                      </p>
                      <div className="adoPatHintBox">
                        <span>Required Token Scope:</span> <code>Work Items (Read)</code> or <code>Full access</code>
                      </div>
                    </div>
                  ) : (
                    <>
                      <Info size={32} color="#0078d4" />
                      <h4>No sprint tasks found</h4>
                      <p>
                        No work items are currently assigned to sprint <b>{currentIteration.name}</b> for team <b>{teams.find(t => t.id === selectedTeamId)?.name || selectedTeamId}</b>.
                      </p>
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      ) : activeSubTab === 'Standup' ? (
        <SmartStandupView
          organization={organization}
          project={project}
          teamName={currentTeam?.name || ''}
          sprintName={formatSprintName(boardData?.iteration?.name || currentIteration?.name, boardData?.iteration?.path || currentIteration?.path)}
          workItems={boardData?.work_items || []}
          capacityMembers={capacityMembers}
          uniqueAssignees={uniqueAssignees}
          pat={pat}
          onSwitchToTaskboard={() => setActiveSubTab('Taskboard')}
        />
      ) : (activeSubTab === 'Deliverables' || (activeSubTab as any) === 'Milestone') ? (
        <div className="adoMilestoneContainer">
          {/* Deliverables Status Line with Saved/Fresh/Failed Status & Regenerate Button */}
          <div className="adoDeliverablesStatusLine">
            <div className="adoDeliverablesStatusLeft">
              {deliverablesReport ? (
                <>
                  <span
                    className={`adoReportStatusPill ${
                      deliverablesReport.status === 'regenerate_failed'
                        ? 'warning'
                        : deliverablesReport.status === 'saved'
                        ? 'saved'
                        : 'success'
                    }`}
                  >
                    {deliverablesReport.status === 'regenerate_failed' ? (
                      <>
                        <AlertTriangle size={13} />
                        <span>Regeneration failed, showing last saved</span>
                      </>
                    ) : deliverablesReport.status === 'saved' ? (
                      <>
                        <Clock size={13} />
                        <span>Saved report</span>
                      </>
                    ) : (
                      <>
                        <CheckCircle size={13} />
                        <span>Freshly generated</span>
                      </>
                    )}
                  </span>
                  <span style={{ color: '#a1a1aa', fontSize: '12px' }}>
                    Generated at{' '}
                    <strong style={{ color: '#f4f4f5' }}>
                      {formatReportDate(deliverablesReport.generatedAt)}
                    </strong>
                    {deliverablesReport.lastRegenerateError && (
                      <span style={{ color: '#f87171', marginLeft: '6px' }}>
                        ({deliverablesReport.lastRegenerateError})
                      </span>
                    )}
                  </span>
                </>
              ) : (
                <span style={{ color: '#a1a1aa', fontSize: '12px' }}>
                  No saved report for this sprint yet. Click Regenerate to fetch from ADO.
                </span>
              )}
            </div>

            <div className="adoDeliverablesStatusRight">
              {showEmailReport && (
                <button
                  type="button"
                  className="sprintEmailBtn"
                  style={{ marginRight: '8px' }}
                  onClick={() => {
                    setEmailSentSuccess(false)
                    setShowEmailModal(true)
                  }}
                  title="Send Sprint Deliverables Handover Email"
                >
                  <Mail size={14} />
                  <span>Send Deliverables Email</span>
                </button>
              )}
              <button
                type="button"
                className="adoRegenerateBtn"
                onClick={handleRegenerateDeliverables}
                disabled={isRegeneratingDeliverables}
                title="Fetch fresh ADO sprint work items and update the handover report"
              >
                <RefreshCw size={13} className={isRegeneratingDeliverables ? 'spin' : ''} />
                <span>{isRegeneratingDeliverables ? 'Regenerating...' : 'Regenerate'}</span>
              </button>
            </div>
          </div>

          {/* Deliverables Overview Hero Banner */}
          <div className="adoMilestoneHero">
            <div className="adoMilestoneHeroLeft">
              <div className="adoMilestoneBadgeRow">
                <span className="adoMilestoneTag">
                  <Trophy size={14} /> Sprint Deliverables Handover
                </span>
                <span
                  className={`adoMilestoneStatusBadge ${
                    (deliverablesReport?.capacityEffortSummary?.completionRatePct ?? computedMilestone?.completion_rate_pct ?? 0) >= 100
                      ? 'achieved'
                      : (deliverablesReport?.capacityEffortSummary?.completionRatePct ?? computedMilestone?.completion_rate_pct ?? 0) >= 50
                      ? 'progress'
                      : 'started'
                  }`}
                >
                  {(deliverablesReport?.capacityEffortSummary?.completionRatePct ?? computedMilestone?.completion_rate_pct ?? 0) >= 100
                    ? '🏆 Sprint Goal Complete'
                    : (deliverablesReport?.capacityEffortSummary?.completionRatePct ?? computedMilestone?.completion_rate_pct ?? 0) >= 50
                    ? '🚀 High Milestone Progress'
                    : '⚡ Active Sprint Delivery'}
                </span>
              </div>
              <h2 className="adoMilestoneTitle">
                Sprint Deliverables Handover: {formatSprintName(currentIteration?.name, currentIteration?.path)}
              </h2>
              <p className="adoMilestoneSubtitle">
                Saved sprint handover and review center. Customer-facing stories and bugs delivered, carryover items, and engineering contribution.
              </p>

              {/* Progress bar */}
              <div className="adoMilestoneProgressWrap">
                <div className="adoMilestoneProgressHeader">
                  <span>Sprint Deliverables Shipped</span>
                  <b>
                    {deliverablesReport?.capacityEffortSummary?.closedStoriesCount ?? computedMilestone?.closed_stories_count ?? 0} of{' '}
                    {deliverablesReport?.capacityEffortSummary?.totalStories ?? computedMilestone?.total_stories ?? 0} Stories & Bugs ({deliverablesReport?.capacityEffortSummary?.completionRatePct ?? computedMilestone?.completion_rate_pct ?? 0}%)
                  </b>
                </div>
                <div className="adoMilestoneProgressBar">
                  <div
                    className="adoMilestoneProgressFill"
                    style={{
                      width: `${Math.min(
                        100,
                        deliverablesReport?.capacityEffortSummary?.completionRatePct ?? computedMilestone?.completion_rate_pct ?? 0
                      )}%`
                    }}
                  />
                </div>
              </div>
            </div>

            {showAiBriefing && (
              <div className="adoMilestoneHeroRight">
                <button
                  type="button"
                  className="adoAiBriefBtn"
                  onClick={handleGenerateAiMilestone}
                  disabled={
                    isGeneratingAi ||
                    (deliverablesReport?.capacityEffortSummary?.closedStoriesCount ?? computedMilestone?.closed_stories_count ?? 0) === 0
                  }
                >
                  <Sparkles size={16} className={isGeneratingAi ? 'spin' : ''} />
                  <span>{isGeneratingAi ? 'Generating Briefing...' : 'Generate Executive Brief'}</span>
                </button>
              </div>
            )}
          </div>

          {/* Quick Metrics Bar */}
          <div className="adoMilestoneMetricsRow">
            <div className="adoMilestoneMetricCard">
              <div className="adoMetricIconWrap blue">
                <CheckCircle2 size={18} />
              </div>
              <div className="adoMetricInfo">
                <div className="adoMetricValue">
                  {deliverablesReport?.capacityEffortSummary?.closedStoriesCount ?? computedMilestone?.closed_stories_count ?? 0}{' '}
                  <span className="adoMetricTotal">
                    / {deliverablesReport?.capacityEffortSummary?.totalStories ?? computedMilestone?.total_stories ?? 0}
                  </span>
                </div>
                <div className="adoMetricLabel">Stories & Bugs Delivered</div>
              </div>
            </div>

            <div className="adoMilestoneMetricCard">
              <div className="adoMetricIconWrap green">
                <Clock size={18} />
              </div>
              <div className="adoMetricInfo">
                <div className="adoMetricValue">
                  {deliverablesReport?.capacityEffortSummary?.totalDeliveredHours ?? computedMilestone?.total_delivered_hours ?? 0}{' '}
                  <span className="adoMetricUnit">hrs</span>
                </div>
                <div className="adoMetricLabel">Engineering Hours Delivered</div>
              </div>
            </div>

            <div className="adoMilestoneMetricCard">
              <div className="adoMetricIconWrap purple">
                <Award size={18} />
              </div>
              <div className="adoMetricInfo">
                <div className="adoMetricValue">
                  {deliverablesReport?.capacityEffortSummary?.featuresDeliveredCount ?? computedMilestone?.features_delivered_count ?? 0}
                </div>
                <div className="adoMetricLabel">Features & Enablers</div>
              </div>
            </div>

            <div className="adoMilestoneMetricCard">
              <div className="adoMetricIconWrap amber">
                <AlertTriangle size={18} />
              </div>
              <div className="adoMetricInfo">
                <div className="adoMetricValue">
                  {deliverablesReport?.capacityEffortSummary?.bugsResolvedCount ?? computedMilestone?.bugs_resolved_count ?? 0}
                </div>
                <div className="adoMetricLabel">Bugs & Issues Resolved</div>
              </div>
            </div>
          </div>

          {/* AI Executive Briefing Card (if generated & enabled by plugin) */}
          {showAiBriefing && aiSummary && (
            <div className="adoAiSummaryCard">
              <div className="adoAiSummaryHeader">
                <div className="adoAiSummaryTitle">
                  <Sparkles size={16} color="#8b5cf6" />
                  <span>Executive Sprint Milestone Briefing</span>
                </div>
                <button
                  type="button"
                  className="adoCopyBtn"
                  onClick={handleCopySummary}
                  title="Copy executive brief to clipboard"
                >
                  {copiedSummary ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
                  <span>{copiedSummary ? 'Copied to Clipboard!' : 'Copy Brief'}</span>
                </button>
              </div>

              <div className="adoAiSummaryContent">
                <div className="adoAiSummaryText" style={{ whiteSpace: 'pre-line' }}>
                  {aiSummary.summary}
                </div>

                {aiSummary.highlights && aiSummary.highlights.length > 0 && (
                  <div className="adoAiHighlightsWrap">
                    <b>Key Deliverables & Value Highlights:</b>
                    <ul className="adoAiHighlightsList">
                      {aiSummary.highlights.map((h, idx) => (
                        <li key={idx}>
                          <CheckCircle size={14} color="#10b981" />
                          <span>{h}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Clean Deliverables Section Tabs: Completed, Pending, Members, Capacity/Streams, Hygiene */}
          <div className="adoDeliverablesSectionTabs">
            <button
              type="button"
              className={`adoDeliverablesSectionTab ${deliverablesActiveSection === 'completed' ? 'active' : ''}`}
              onClick={() => setDeliverablesActiveSection('completed')}
            >
              <CheckCircle2 size={13} />
              <span>Completed Deliverables ({deliverablesReport?.capacityEffortSummary?.closedStoriesCount ?? computedMilestone?.closed_stories_count ?? 0})</span>
            </button>
            <button
              type="button"
              className={`adoDeliverablesSectionTab ${deliverablesActiveSection === 'pending' ? 'active' : ''}`}
              onClick={() => setDeliverablesActiveSection('pending')}
            >
              <Clock size={13} />
              <span>Pending & Carryover ({deliverablesReport?.capacityEffortSummary?.pendingStoriesCount ?? 0})</span>
            </button>
            <button
              type="button"
              className={`adoDeliverablesSectionTab ${deliverablesActiveSection === 'members' ? 'active' : ''}`}
              onClick={() => setDeliverablesActiveSection('members')}
            >
              <Users size={13} />
              <span>Team Member Effort ({deliverablesReport?.memberContributions?.length ?? 0})</span>
            </button>
            <button
              type="button"
              className={`adoDeliverablesSectionTab ${deliverablesActiveSection === 'streams' ? 'active' : ''}`}
              onClick={() => setDeliverablesActiveSection('streams')}
            >
              <Layers size={13} />
              <span>Capacity & Stream Baselines</span>
            </button>
            <button
              type="button"
              className={`adoDeliverablesSectionTab ${deliverablesActiveSection === 'hygiene' ? 'active' : ''}`}
              onClick={() => setDeliverablesActiveSection('hygiene')}
            >
              <ShieldAlert size={13} />
              <span>
                Hygiene & Warnings (
                {(deliverablesReport?.warningsAndHygiene?.closedWithoutHoursCount ?? 0) +
                  (deliverablesReport?.warningsAndHygiene?.staleInReviewCount ?? 0) +
                  (deliverablesReport?.warningsAndHygiene?.missingOwnersCount ?? 0)}
                )
              </span>
            </button>
          </div>

          {/* Section 1: Completed Stories & Bugs */}
          {deliverablesActiveSection === 'completed' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {/* Deliverables Section Toolbar (Filter & Search) */}
              <div className="adoMilestoneToolbar">
                <div className="adoMilestoneFilterPills">
                  <button
                    type="button"
                    className={`adoFilterPill ${milestoneCategoryFilter === 'all' && selectedMilestoneStream === 'all' ? 'active' : ''}`}
                    onClick={() => {
                      setMilestoneCategoryFilter('all')
                      setSelectedMilestoneStream('all')
                    }}
                  >
                    All Achieved ({deliverablesReport?.completedDeliverables?.length ?? computedMilestone?.achieved_items?.length ?? 0})
                  </button>
                  <button
                    type="button"
                    className={`adoFilterPill ${milestoneCategoryFilter === 'features' ? 'active' : ''}`}
                    onClick={() => setMilestoneCategoryFilter('features')}
                  >
                    Features & Stories ({deliverablesReport?.capacityEffortSummary?.featuresDeliveredCount ?? computedMilestone?.features_delivered_count ?? 0})
                  </button>
                  <button
                    type="button"
                    className={`adoFilterPill ${milestoneCategoryFilter === 'bugs' ? 'active' : ''}`}
                    onClick={() => setMilestoneCategoryFilter('bugs')}
                  >
                    Bug Fixes ({deliverablesReport?.capacityEffortSummary?.bugsResolvedCount ?? computedMilestone?.bugs_resolved_count ?? 0})
                  </button>
                  {selectedMilestoneStream !== 'all' && (
                    <button
                      type="button"
                      className="adoFilterPill active"
                      onClick={() => setSelectedMilestoneStream('all')}
                      style={{ background: '#0284c7', color: '#ffffff' }}
                    >
                      Stream: {selectedMilestoneStream} (Clear ✕)
                    </button>
                  )}
                </div>

                <div className="adoMilestoneSearch">
                  <Search size={14} className="adoSearchIcon" />
                  <input
                    type="text"
                    placeholder="Search achieved deliverables..."
                    value={milestoneSearch}
                    onChange={e => setMilestoneSearch(e.target.value)}
                  />
                  {milestoneSearch && (
                    <button type="button" className="adoClearSearch" onClick={() => setMilestoneSearch('')}>
                      <X size={12} />
                    </button>
                  )}
                </div>
              </div>

              {/* Deliverables List or Empty State */}
              {filteredMilestoneItems.length === 0 ? (
                <div className="adoMilestoneEmpty">
                  <Trophy size={44} color="#f59e0b" />
                  <h3>
                    {(deliverablesReport?.completedDeliverables?.length ?? 0) === 0
                      ? 'No Closed User Stories in this Sprint Yet'
                      : 'No deliverables match your search criteria'}
                  </h3>
                  <p>
                    {(deliverablesReport?.completedDeliverables?.length ?? 0) === 0
                      ? 'As stories and bugs are transitioned to Closed or Done in Azure DevOps, your sprint deliverables will be ready for handover.'
                      : 'Try clearing your search keyword or switching the category filter above.'}
                  </p>
                  {(deliverablesReport?.completedDeliverables?.length ?? 0) === 0 ? (
                    <button
                      type="button"
                      className="adoPrimaryBtn"
                      onClick={() => setActiveSubTab('Taskboard')}
                      style={{ marginTop: '12px' }}
                    >
                      Go to Taskboard
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="adoSecondaryBtn"
                      onClick={() => {
                        setMilestoneSearch('')
                        setMilestoneCategoryFilter('all')
                        setSelectedMilestoneStream('all')
                      }}
                      style={{ marginTop: '12px' }}
                    >
                      Reset Filters
                    </button>
                  )}
                </div>
              ) : (
                <div className="adoMilestoneGrid">
                  {filteredMilestoneItems.map(item => (
                    <div key={item.id} className="adoMilestoneCard">
                      <div className="adoMilestoneCardHeader">
                        <div className="adoMilestoneCardTags">
                          <span className={`adoItemTypeBadge ${item.work_item_type.toLowerCase().replace(/\s+/g, '')}`}>
                            {item.work_item_type === 'Bug' ? '🐛 Bug' : '📘 Story'}
                          </span>
                          <a
                            href={item.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${item.id}`}
                            target="_blank"
                            rel="noreferrer"
                            className="adoMilestoneIdLink"
                          >
                            #{item.id} <ExternalLink size={11} />
                          </a>
                          <span className="adoCategoryTag">{item.category}</span>
                          {item.milestone_stream && (
                            <span className="adoStreamTag">{item.milestone_stream}</span>
                          )}
                        </div>
                        <span className="adoMilestoneDoneBadge">
                          <CheckCircle2 size={12} /> {item.state}
                        </span>
                      </div>

                      <h4 className="adoMilestoneItemTitle">
                        <a
                          href={item.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${item.id}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {item.title}
                        </a>
                      </h4>

                      {/* Problem / Issue Description */}
                      {item.issue_summary && (
                        <div className="adoItemIssueBox">
                          <div className="adoItemSectionLabel red">
                            <AlertCircle size={12} />
                            <span>What the Issue / Challenge Was:</span>
                          </div>
                          <p className="adoItemSectionText">{item.issue_summary}</p>
                        </div>
                      )}

                      {/* Condition of Satisfaction / Solution Achieved */}
                      {item.achievement_summary && (
                        <div className="adoItemAchievementBox">
                          <div className="adoItemSectionLabel green">
                            <CheckCircle2 size={12} />
                            <span>What We Achieved & Condition of Satisfaction Met:</span>
                          </div>
                          <p className="adoItemSectionText">{item.achievement_summary}</p>
                        </div>
                      )}

                      <div className="adoMilestoneCardFooter">
                        <div className="adoMilestoneAssignee">
                          <div className="adoAvatarTiny">
                            {item.assigned_to_name ? item.assigned_to_name.charAt(0).toUpperCase() : '?'}
                          </div>
                          <span>{item.assigned_to_name || 'Unassigned'}</span>
                        </div>

                        <div className="adoMilestoneBadgesRight">
                          {item.hours_delivered > 0 && (
                            <span className="adoHoursBadge" title="Total hours completed on this story and its child tasks">
                              <Clock size={11} /> {item.hours_delivered}h delivered
                            </span>
                          )}
                          {item.child_tasks_total > 0 && (
                            <span className="adoChildTasksBadge" title="Child tasks completed">
                              <CheckSquare size={11} /> {item.child_tasks_closed}/{item.child_tasks_total} tasks
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Section 2: Pending & In-Progress Carryover Items */}
          {deliverablesActiveSection === 'pending' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div className="adoMilestoneToolbar">
                <span style={{ fontSize: '13px', color: '#a1a1aa' }}>
                  Committed sprint user stories and bugs not yet closed. Tasks support internal detail without being main customer-facing deliverables.
                </span>
                <div className="adoMilestoneSearch">
                  <Search size={14} className="adoSearchIcon" />
                  <input
                    type="text"
                    placeholder="Search pending items..."
                    value={milestoneSearch}
                    onChange={e => setMilestoneSearch(e.target.value)}
                  />
                  {milestoneSearch && (
                    <button type="button" className="adoClearSearch" onClick={() => setMilestoneSearch('')}>
                      <X size={12} />
                    </button>
                  )}
                </div>
              </div>

              {(() => {
                const pendingList = (deliverablesReport?.pendingDeliverables || []).filter(item => {
                  if (!milestoneSearch.trim()) return true
                  const q = milestoneSearch.toLowerCase()
                  return (
                    item.title.toLowerCase().includes(q) ||
                    String(item.id).includes(q) ||
                    item.assigned_to_name?.toLowerCase().includes(q) ||
                    item.state.toLowerCase().includes(q)
                  )
                })

                if (pendingList.length === 0) {
                  return (
                    <div className="adoMilestoneEmpty">
                      <CheckCircle2 size={44} color="#10b981" />
                      <h3>No Pending Items Remaining</h3>
                      <p>All committed stories and bugs in this sprint report have been completed and delivered!</p>
                    </div>
                  )
                }

                return (
                  <div className="adoPendingGrid">
                    {pendingList.map(item => (
                      <div key={item.id} className="adoPendingCard">
                        <div className="adoPendingTop">
                          <div className="adoPendingTags">
                            <span className={`adoItemTypeBadge ${item.work_item_type.toLowerCase().replace(/\s+/g, '')}`}>
                              {item.work_item_type === 'Bug' ? '🐛 Bug' : '📘 Story'}
                            </span>
                            <a
                              href={item.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${item.id}`}
                              target="_blank"
                              rel="noreferrer"
                              className="adoMilestoneIdLink"
                            >
                              #{item.id} <ExternalLink size={11} />
                            </a>
                          </div>
                          <span className={`adoPendingStateBadge ${item.state.toLowerCase().replace(/\s+/g, '')}`}>
                            {item.state}
                          </span>
                        </div>

                        <h4 className="adoPendingTitle">
                          <a
                            href={item.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${item.id}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {item.title}
                          </a>
                        </h4>

                        <div className="adoPendingFooter">
                          <div className="adoMilestoneAssignee">
                            <div className="adoAvatarTiny">
                              {item.assigned_to_name ? item.assigned_to_name.charAt(0).toUpperCase() : '?'}
                            </div>
                            <span>{item.assigned_to_name || 'Unassigned'}</span>
                          </div>

                          <div className="adoMilestoneBadgesRight">
                            {item.remaining_work !== undefined && item.remaining_work > 0 && (
                              <span className="adoHoursBadge" title="Remaining work">
                                <Clock size={11} /> {item.remaining_work}h rem
                              </span>
                            )}
                            {item.child_tasks_total > 0 && (
                              <span className="adoChildTasksBadge" title="Child tasks supporting this story">
                                <CheckSquare size={11} /> {item.child_tasks_closed}/{item.child_tasks_total} tasks
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )
              })()}
            </div>
          )}

          {/* Section 3: Team Member Contribution & Effort */}
          {deliverablesActiveSection === 'members' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {(() => {
                const members = deliverablesReport?.memberContributions || []
                if (members.length === 0) {
                  return (
                    <div className="adoMilestoneEmpty">
                      <Users size={44} color="#38bdf8" />
                      <h3>No Team Member Activity Recorded</h3>
                      <p>Work items in this sprint have not yet been assigned to team members.</p>
                    </div>
                  )
                }

                return (
                  <div className="adoMembersGrid">
                    {members.map(member => {
                      const pct = member.totalHours > 0 ? Math.round((member.completedHours / member.totalHours) * 100) : 0
                      return (
                        <div key={member.name} className="adoMemberContributionCard">
                          <div className="adoMemberCardTop">
                            <div className="adoMemberAvatar">
                              {member.name.charAt(0).toUpperCase()}
                            </div>
                            <div className="adoMemberInfo">
                              <span className="adoMemberName">{member.name}</span>
                              <span style={{ fontSize: '11px', color: '#a1a1aa' }}>Sprint Contributor</span>
                            </div>
                          </div>

                          <div className="adoMemberStatsRow">
                            <div className="adoMemberStat">
                              <span className="val" style={{ color: '#10b981' }}>{member.completedCount}</span>
                              <span className="lbl">Delivered</span>
                            </div>
                            <div className="adoMemberStat">
                              <span className="val" style={{ color: '#f59e0b' }}>{member.pendingCount}</span>
                              <span className="lbl">Pending</span>
                            </div>
                            <div className="adoMemberStat">
                              <span className="val" style={{ color: '#38bdf8' }}>{member.completedHours}h</span>
                              <span className="lbl">Logged</span>
                            </div>
                          </div>

                          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '6px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#a1a1aa' }}>
                              <span>Effort Progress</span>
                              <span>{member.completedHours}h / {member.totalHours}h ({pct}%)</span>
                            </div>
                            <div className="adoProgressTrack">
                              <div className="adoProgressFill success" style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )
              })()}
            </div>
          )}

          {/* Section 4: Capacity Summary & Baseline Capability Streams */}
          {deliverablesActiveSection === 'streams' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {computedMilestone?.graph_data ? (
                <div className="adoMilestoneGraphCard" style={{ margin: 0 }}>
                  <div className="adoGraphHeader">
                    <div className="adoGraphTitleWrap">
                      <div className="adoGraphMainTitle">
                        <Layers size={16} color="#38bdf8" />
                        <span>Milestone Capability Breakdown & Next-Sprint Baseline Graph</span>
                      </div>
                      <span className="adoGraphSubtitle">
                        Delivery stream velocity across completed features, defect resolutions, and capability areas, establishing reliable baselines for upcoming sprint commitments.
                      </span>
                    </div>
                    <div className="adoBaselineBadgeHeader">
                      <ShieldCheck size={14} />
                      <span>Next-Sprint Baseline Active</span>
                    </div>
                  </div>

                  {/* Stream Cards Grid */}
                  <div className="adoStreamGrid">
                    {computedMilestone.graph_data.streams.map(stream => {
                      const isActive = selectedMilestoneStream === stream.name
                      return (
                        <div
                          key={stream.name}
                          className={`adoStreamCard ${isActive ? 'active' : ''}`}
                          onClick={() => setSelectedMilestoneStream(isActive ? 'all' : stream.name)}
                          title="Click to filter deliverables by this capability stream"
                        >
                          <div className="adoStreamCardHeader">
                            <div className="adoStreamNameWrap">
                              <div className={`adoStreamIcon ${
                                stream.name.includes('Fixes') ? 'amber' : stream.name.includes('Automation') ? 'purple' : stream.name.includes('Quality') ? 'green' : ''
                              }`}>
                                {stream.name.includes('Fixes') ? <AlertTriangle size={15} /> : stream.name.includes('Creation') ? <Radio size={15} /> : stream.name.includes('Automation') ? <Cpu size={15} /> : <CheckCircle2 size={15} />}
                              </div>
                              <span className="adoStreamName">{stream.name}</span>
                            </div>
                            <span className="adoStreamPill">{stream.completion_pct}% Delivered</span>
                          </div>

                          <div className="adoStreamStatsRow">
                            <div className="adoStreamCount">
                              {stream.closed_count} <small>/ {stream.total_count} items</small>
                            </div>
                            <span className="adoStreamHours">{stream.delivered_hours}h verified</span>
                          </div>

                          {/* Progress with Baseline Target Marker */}
                          <div className="adoBaselineBarWrap">
                            <div className="adoBaselineBarTrack">
                              <div
                                className="adoBaselineBarFill"
                                style={{ width: `${Math.min(100, stream.completion_pct)}%` }}
                              />
                              <div
                                className="adoBaselineTargetMarker"
                                style={{ left: `${Math.min(95, Math.max(20, stream.completion_pct))}%` }}
                                title="Next Sprint Target Baseline"
                              />
                            </div>
                            <div className="adoBaselineLegendRow">
                              <span>Sprint Achieved</span>
                              <span style={{ color: '#f59e0b', fontWeight: 600 }}>Next Sprint Target: {stream.next_sprint_baseline_target}</span>
                            </div>
                          </div>

                          <div className="adoBaselineRecommendation">
                            {stream.next_sprint_recommendation}
                          </div>
                        </div>
                      )
                    })}
                  </div>

                  {/* Strategic Next-Sprint Baseline Projection Panel */}
                  <div className="adoStrategicBaselinePanel">
                    <div className="adoBaselineKpiCol">
                      <div className="adoBaselineKpiTitle">
                        <Zap size={14} />
                        <span>Established Sprint Baseline KPIs</span>
                      </div>
                      <div className="adoBaselineKpis">
                        <div className="adoBaselineKpiItem">
                          <span className="adoBaselineKpiVal">{computedMilestone.graph_data.bug_resolution_rate_pct}%</span>
                          <span className="adoBaselineKpiLbl">Bug Resolution Rate</span>
                        </div>
                        <div className="adoBaselineKpiItem">
                          <span className="adoBaselineKpiVal">{computedMilestone.graph_data.overall_reliability_baseline_pct}%</span>
                          <span className="adoBaselineKpiLbl">Milestone Reliability</span>
                        </div>
                        <div className="adoBaselineKpiItem">
                          <span className="adoBaselineKpiVal">{computedMilestone.total_delivered_hours}h</span>
                          <span className="adoBaselineKpiLbl">Verified Effort Base</span>
                        </div>
                      </div>
                      <div className="adoBaselineCapacityPlan">
                        <b>Recommended Capacity Allocation for Next Sprint:</b> {computedMilestone.graph_data.next_sprint_recommended_capacity}
                      </div>
                    </div>

                    <div className="adoBaselineFocusCol">
                      <div className="adoBaselineKpiTitle">
                        <Target size={14} />
                        <span>Next Sprint Baseline Commitments ({computedMilestone.graph_data.next_sprint_focus_areas?.length || 0})</span>
                      </div>
                      <ul className="adoBaselineFocusList">
                        {(computedMilestone.graph_data.next_sprint_focus_areas || []).map((focus, fIdx) => (
                          <li key={fIdx}>
                            <CheckCircle2 size={13} color="#10b981" style={{ flexShrink: 0, marginTop: '2px' }} />
                            <span>{focus}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="adoMilestoneEmpty">
                  <Layers size={44} color="#38bdf8" />
                  <h3>No Stream Data Available</h3>
                  <p>Stream baseline projections will populate as work items are categorized in this sprint.</p>
                </div>
              )}
            </div>
          )}

          {/* Section 5: Missing Owners / Hygiene Warnings */}
          {deliverablesActiveSection === 'hygiene' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {(() => {
                const hygiene = deliverablesReport?.warningsAndHygiene
                const totalWarnings =
                  (hygiene?.missingOwnersCount ?? 0) +
                  (hygiene?.closedWithoutHoursCount ?? 0) +
                  (hygiene?.staleInReviewCount ?? 0)

                if (!hygiene || totalWarnings === 0) {
                  return (
                    <div className="adoMilestoneEmpty">
                      <ShieldCheck size={44} color="#10b981" />
                      <h3>All Sprint Hygiene Checks Passed!</h3>
                      <p>Great job! No unassigned work items, tasks closed without logged hours, or stale review items were detected in this sprint report.</p>
                    </div>
                  )
                }

                return (
                  <div className="adoHygieneList">
                    {hygiene.missingOwnersCount > 0 && (
                      <div className="adoHygieneItemRow">
                        <div className="adoHygieneItemLeft">
                          <User size={16} color="#f87171" />
                          <div>
                            <span style={{ fontWeight: 600, color: '#f87171' }}>
                              {hygiene.missingOwnersCount} Work Items Missing Assignees/Owners
                            </span>
                            <div style={{ fontSize: '12px', color: '#a1a1aa', marginTop: '2px' }}>
                              Items need active team owners to ensure accountability before sprint handover.
                            </div>
                          </div>
                        </div>
                        <span className="adoHygieneTag danger">{hygiene.missingOwnersCount} Unassigned</span>
                      </div>
                    )}

                    {hygiene.closedWithoutHoursCount > 0 && (
                      <div className="adoHygieneItemRow">
                        <div className="adoHygieneItemLeft">
                          <Clock size={16} color="#f59e0b" />
                          <div>
                            <span style={{ fontWeight: 600, color: '#f59e0b' }}>
                              {hygiene.closedWithoutHoursCount} Tasks Closed Without Logged Hours
                            </span>
                            <div style={{ fontSize: '12px', color: '#a1a1aa', marginTop: '2px' }}>
                              Tasks closed with 0 completed hours distort sprint capacity and burndown tracking.
                            </div>
                          </div>
                        </div>
                        <span className="adoHygieneTag warning">{hygiene.closedWithoutHoursCount} Without Hours</span>
                      </div>
                    )}

                    {hygiene.staleInReviewCount > 0 && (
                      <div className="adoHygieneItemRow">
                        <div className="adoHygieneItemLeft">
                          <AlertTriangle size={16} color="#eab308" />
                          <div>
                            <span style={{ fontWeight: 600, color: '#eab308' }}>
                              {hygiene.staleInReviewCount} Items In Review &gt; 2 Days
                            </span>
                            <div style={{ fontSize: '12px', color: '#a1a1aa', marginTop: '2px' }}>
                              Items pending review for extended durations may carry over past the sprint handover.
                            </div>
                          </div>
                        </div>
                        <span className="adoHygieneTag warning">{hygiene.staleInReviewCount} Stale Review</span>
                      </div>
                    )}
                  </div>
                )
              })()}
            </div>
          )}
        </div>
      ) : activeSubTab === 'Backlog' ? (
        <div className="adoBacklogWrapper">
          <div className="adoBacklogMain">
            {/* ADO Backlog Filter Bar */}
            <div className="adoBacklogFilterBar">
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: 1, minWidth: '220px' }}>
                <Search size={14} color="#71717a" />
                <input
                  type="text"
                  placeholder="Filter by keyword or #ID..."
                  value={backlogSearch}
                  onChange={e => setBacklogSearch(e.target.value)}
                  className="adoSearchInput"
                  style={{ width: '100%', height: '30px', fontSize: '12px' }}
                />
              </div>

              <select
                value={backlogTypeFilter}
                onChange={e => setBacklogTypeFilter(e.target.value)}
                className="adoBacklogFilterSelect"
              >
                <option value="all">Types: All</option>
                <option value="stories">Stories / PBIs</option>
                <option value="bugs">Bugs</option>
                <option value="features">Features</option>
              </select>

              <select
                value={backlogStateFilter}
                onChange={e => setBacklogStateFilter(e.target.value)}
                className="adoBacklogFilterSelect"
              >
                <option value="all">State: All</option>
                {Object.keys(backlogStats.stateCounts).map(s => (
                  <option key={s} value={s}>{s} ({backlogStats.stateCounts[s]})</option>
                ))}
              </select>

              <select
                value={backlogAssigneeFilter}
                onChange={e => setBacklogAssigneeFilter(e.target.value)}
                className="adoBacklogFilterSelect"
              >
                <option value="all">Assigned to: All</option>
                <option value="unassigned">Unassigned</option>
                {Array.from(new Set(backlogItems.map(i => i.assigned_to_name).filter(Boolean))).map(name => (
                  <option key={name as string} value={name as string}>{name}</option>
                ))}
              </select>

              <select
                value={backlogTagFilter}
                onChange={e => setBacklogTagFilter(e.target.value)}
                className="adoBacklogFilterSelect"
              >
                <option value="all">Tag: All</option>
                {Array.from(
                  new Set(
                    backlogItems
                      .flatMap(i => (i.tags || '').split(';').map(t => t.trim()))
                      .filter(Boolean)
                  )
                ).map(tag => (
                  <option key={tag} value={tag}>{tag}</option>
                ))}
              </select>

              {(backlogSearch || backlogTypeFilter !== 'all' || backlogStateFilter !== 'all' || backlogAssigneeFilter !== 'all' || backlogTagFilter !== 'all') && (
                <button
                  type="button"
                  onClick={() => {
                    setBacklogSearch('')
                    setBacklogTypeFilter('all')
                    setBacklogStateFilter('all')
                    setBacklogAssigneeFilter('all')
                    setBacklogTagFilter('all')
                  }}
                  className="sprintFilterClearBtn"
                >
                  <X size={12} /> Clear
                </button>
              )}
            </div>

            {/* Backlog Toolbar with Stats */}
            <div className="adoBacklogToolbar">
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '13px', fontWeight: 600, color: '#f4f4f5' }}>
                  Product Backlog Items
                </span>
                <span style={{ fontSize: '11px', color: '#71717a' }}>
                  (Items not on current sprint board)
                </span>
              </div>
              <div className="adoBacklogStats">
                <span className="adoBacklogStatItem">
                  Showing: <b>{filteredBacklogItems.length}</b> of <b>{backlogItems.length}</b>
                </span>
                <span className="adoBacklogStatItem accent">
                  Total Points: <b>{backlogStats.totalPoints} pts</b>
                </span>
                <span className="adoBacklogStatItem success">
                  Avg Size: <b>{backlogStats.avgSize} pts</b>
                </span>
              </div>
            </div>

            {/* Backlog Table */}
            <div className="adoBacklogTableWrap">
              <table className="adoBacklogTable">
                <thead>
                  <tr>
                    <th style={{ width: '45px', textAlign: 'center' }}>Order</th>
                    <th style={{ width: '130px' }}>Work Item Type</th>
                    <th>Title</th>
                    <th style={{ width: '100px' }}>State</th>
                    <th style={{ width: '70px', textAlign: 'center' }}>Story...</th>
                    <th style={{ width: '110px' }}>Value Area</th>
                    <th style={{ width: '180px' }}>Iteration Path</th>
                    <th style={{ width: '140px' }}>Assigned To</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredBacklogItems.length === 0 ? (
                    <tr>
                      <td colSpan={8} style={{ textAlign: 'center', padding: '50px 20px', color: '#71717a' }}>
                        <Info size={28} color="#0078d4" style={{ marginBottom: '8px' }} />
                        <div style={{ fontSize: '13px', color: '#e4e4e7', fontWeight: 600 }}>No uncommitted backlog items found</div>
                        <div style={{ fontSize: '11.5px', color: '#a1a1aa', marginTop: '4px' }}>
                          {backlogItems.length === 0
                            ? 'All team items are currently committed to active sprint boards.'
                            : 'No items match your active filters.'}
                        </div>
                      </td>
                    </tr>
                  ) : (
                    filteredBacklogItems.map((item, idx) => {
                      const isBug = item.work_item_type.toLowerCase().includes('bug')
                      const isFeature = item.work_item_type.toLowerCase().includes('feature')
                      const badgeType = isBug ? 'bug' : isFeature ? 'feature' : 'story'
                      const stateKey = item.state.toLowerCase().replace(/\s+/g, '')
                      const pts = item.story_points != null ? item.story_points : (item.original_estimate != null && item.original_estimate <= 20 ? item.original_estimate : '-')
                      const isArch = (item.value_area || '').toLowerCase().includes('arch')
                      const orderNum = item.order != null ? item.order : (idx + 1)
                      const itemTags = (item.tags || '').split(';').map(t => t.trim()).filter(Boolean)

                      return (
                        <tr key={`backlog-item-${item.id}`} className="adoBacklogRow">
                          <td style={{ textAlign: 'center' }}>
                            <span className="adoOrderBadge">{orderNum}</span>
                          </td>
                          <td>
                            <span className={`adoTypeIconBadge ${badgeType}`}>
                              {isBug ? <Bug size={11} /> : isFeature ? <Zap size={11} /> : <BookOpen size={11} />}
                              {item.work_item_type}
                            </span>
                          </td>
                          <td>
                            <div className="adoBacklogTitleCell" style={{ maxWidth: '480px' }}>
                              <a
                                href={item.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${item.id}`}
                                target="_blank"
                                rel="noreferrer"
                                className="adoWorkItemId"
                                style={{ marginRight: '6px' }}
                              >
                                #{item.id}
                              </a>
                              <span className="adoBacklogTitleText" title={item.title}>
                                {item.title}
                              </span>
                              {itemTags.length > 0 && (
                                <div style={{ display: 'flex', gap: '4px', marginLeft: '6px' }}>
                                  {itemTags.slice(0, 2).map(tag => (
                                    <span key={tag} className="adoTagPill">
                                      {tag}
                                    </span>
                                  ))}
                                  {itemTags.length > 2 && (
                                    <span className="adoTagPill" title={itemTags.slice(2).join(', ')}>
                                      +{itemTags.length - 2}
                                    </span>
                                  )}
                                </div>
                              )}
                            </div>
                          </td>
                          <td>
                            <span className={`adoStateDot ${stateKey}`} />
                            <span style={{ fontSize: '11.5px', color: '#d4d4d8' }}>{item.state}</span>
                          </td>
                          <td style={{ textAlign: 'center' }}>
                            <span className="adoEffortBadge" style={{ fontWeight: 700 }}>
                              {pts}
                            </span>
                          </td>
                          <td>
                            <span className={`adoValueAreaBadge ${isArch ? 'architectural' : 'business'}`}>
                              {item.value_area || 'Business'}
                            </span>
                          </td>
                          <td style={{ fontSize: '11px', color: '#a1a1aa' }} title={item.iteration_path || ''}>
                            {item.iteration_path ? item.iteration_path.split('\\').slice(-2).join('\\') : '-'}
                          </td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <div className="adoAvatarSmall">
                                {item.assigned_to_name ? item.assigned_to_name.charAt(0).toUpperCase() : '?'}
                              </div>
                              <span style={{ fontSize: '11.5px', color: item.assigned_to_name ? '#e4e4e7' : '#71717a' }}>
                                {item.assigned_to_name || 'Unassigned'}
                              </span>
                            </div>
                          </td>
                        </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right Backlog Summary Sidebar */}
          <div className="adoBacklogSidebar">
            <div className="adoSidebarCard">
              <h4>Backlog Readiness</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#a1a1aa' }}>Uncommitted Items:</span>
                  <b style={{ color: '#ffffff', fontSize: '14px' }}>{backlogStats.totalCount} items</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#a1a1aa' }}>Total Backlog Points:</span>
                  <b style={{ color: '#38bdf8', fontSize: '14px' }}>{backlogStats.totalPoints} pts</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#a1a1aa' }}>Average Story Size:</span>
                  <b style={{ color: '#34d399' }}>{backlogStats.avgSize} pts</b>
                </div>
              </div>
            </div>

            <div className="adoSidebarCard">
              <h4>Value Area Split</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px' }}>
                    <span style={{ color: '#60a5fa' }}>Business Value</span>
                    <span><b>{backlogStats.businessCount}</b> ({backlogStats.totalCount > 0 ? Math.round((backlogStats.businessCount / backlogStats.totalCount) * 100) : 0}%)</span>
                  </div>
                  <div className="adoProgressTrack">
                    <div
                      className="adoProgressFill"
                      style={{
                        width: `${backlogStats.totalCount > 0 ? Math.round((backlogStats.businessCount / backlogStats.totalCount) * 100) : 0}%`,
                      }}
                    />
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px' }}>
                    <span style={{ color: '#c084fc' }}>Architectural</span>
                    <span><b>{backlogStats.archCount}</b> ({backlogStats.totalCount > 0 ? Math.round((backlogStats.archCount / backlogStats.totalCount) * 100) : 0}%)</span>
                  </div>
                  <div className="adoProgressTrack">
                    <div
                      className="adoProgressFill"
                      style={{
                        width: `${backlogStats.totalCount > 0 ? Math.round((backlogStats.archCount / backlogStats.totalCount) * 100) : 0}%`,
                        background: '#a855f7',
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="adoSidebarCard">
              <h4>Item Types in Backlog</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#38bdf8' }}>📖 User Stories</span>
                  <b>{backlogStats.typeCounts['User Story']}</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#f87171' }}>🐞 Bugs</span>
                  <b>{backlogStats.typeCounts['Bug']}</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#c084fc' }}>⚡ Features</span>
                  <b>{backlogStats.typeCounts['Feature']}</b>
                </div>
              </div>
            </div>

            <div className="adoSidebarCard">
              <h4>State Breakdown</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
                {Object.entries(backlogStats.stateCounts).map(([sName, count]) => (
                  <div key={sName} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span className={`adoStateDot ${sName.toLowerCase().replace(/\s+/g, '')}`} />
                      <span style={{ color: '#d4d4d8' }}>{sName}</span>
                    </div>
                    <span style={{ color: '#a1a1aa' }}><b>{count}</b> items</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : activeSubTab === 'Capacity' ? (
        <div className="adoCapacityWrapper">
          <div className="adoCapacityMain">
            <div className="adoCapacityToolbar">
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <input
                  type="text"
                  placeholder="Add Team Member..."
                  value={newMemberName}
                  onChange={e => setNewMemberName(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') handleAddCapacityMember()
                  }}
                  className="adoCapInput"
                  style={{ width: '220px' }}
                />
                <button
                  type="button"
                  className="adoPrimaryBtn"
                  onClick={handleAddCapacityMember}
                  disabled={!newMemberName.trim()}
                >
                  <Users size={13} /> Add Member
                </button>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                {capacitySavedNotice && (
                  <span style={{ fontSize: '11.5px', color: '#34d399', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Save size={12} /> Capacity settings saved
                  </span>
                )}
                <span className="adoBacklogStatItem">
                  Working Days: <b>{capacityStats.workingDays}d</b>
                </span>
                <span className="adoBacklogStatItem accent">
                  Total Capacity: <b>{capacityStats.totalTeamCapacity}h</b>
                </span>
                <span className="adoBacklogStatItem success">
                  Assigned: <b>{capacityStats.totalAssignedHours}h</b> ({capacityStats.teamUtilization}%)
                </span>
              </div>
            </div>

            <div className="adoCapacityTableWrap">
              <table className="adoCapacityTable">
                <thead>
                  <tr>
                    <th>Team Member</th>
                    <th style={{ width: '160px' }}>Activity</th>
                    <th style={{ width: '130px' }}>Capacity / Day</th>
                    <th style={{ width: '120px' }}>Days Off (PTO)</th>
                    <th style={{ width: '130px', textAlign: 'right' }}>Total Cap (h)</th>
                    <th style={{ width: '150px', textAlign: 'right' }}>Assigned Remaining (h)</th>
                    <th style={{ width: '160px' }}>Utilization</th>
                    <th style={{ width: '60px', textAlign: 'center' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {capacityStats.memberDetails.length === 0 ? (
                    <tr>
                      <td colSpan={8} style={{ textAlign: 'center', padding: '40px 20px', color: '#71717a' }}>
                        No team members configured for capacity planning. Type a name above to add members.
                      </td>
                    </tr>
                  ) : (
                    capacityStats.memberDetails.map(member => (
                      <tr key={member.id}>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div className="adoAvatarSmall">
                              {member.name.charAt(0).toUpperCase()}
                            </div>
                            <span style={{ fontWeight: 600, color: '#f4f4f5' }}>
                              {member.name}
                            </span>
                            <span style={{ fontSize: '10px', color: member.source === 'ado' ? '#38bdf8' : '#fbbf24' }}>
                              {member.source === 'ado' ? 'ADO' : 'Manual'}
                            </span>
                          </div>
                        </td>
                        <td>
                          <select
                            value={member.activity || 'Development'}
                            onChange={e => handleUpdateMemberCapacity(member.id, 'activity', e.target.value)}
                            className="adoCapSelect"
                          >
                            <option value="Development">Development</option>
                            <option value="Testing">Testing</option>
                            <option value="Design">Design</option>
                            <option value="Documentation">Documentation</option>
                            <option value="Requirements">Requirements</option>
                            <option value="Deployment">Deployment</option>
                          </select>
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <input
                              type="number"
                              min="0"
                              max="24"
                              step="0.5"
                              value={member.capacity_per_day}
                              onChange={e => handleUpdateMemberCapacity(member.id, 'capacity_per_day', parseFloat(e.target.value) || 0)}
                              className="adoCapInput"
                            />
                            <span style={{ fontSize: '11px', color: '#71717a' }}>h/day</span>
                          </div>
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <input
                              type="number"
                              min="0"
                              max={capacityStats.workingDays}
                              step="0.5"
                              value={member.days_off}
                              onChange={e => handleUpdateMemberCapacity(member.id, 'days_off', parseFloat(e.target.value) || 0)}
                              className="adoCapInput"
                            />
                            <span style={{ fontSize: '11px', color: '#71717a' }}>days</span>
                          </div>
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: 600, color: '#d4d4d8' }}>
                          {member.individualCap}h
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: 600, color: member.isOverloaded ? '#ef4444' : '#38bdf8' }}>
                          {member.assignedHours}h
                          {member.missingEstimateCount > 0 && (
                            <div style={{ fontSize: '10px', color: '#fbbf24', fontWeight: 500 }}>
                              {member.missingEstimateCount} without estimate
                            </div>
                          )}
                        </td>
                        <td>
                          <div className="adoProgressBarWrap">
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10.5px', color: member.isOverloaded ? '#f87171' : '#a1a1aa' }}>
                              <span>{member.utilization}%</span>
                              <span>{member.isOverloaded ? 'Overloaded' : 'OK'}</span>
                            </div>
                            <div className="adoProgressTrack">
                              <div
                                className={`adoProgressFill ${member.isOverloaded ? 'danger' : member.utilization > 85 ? 'warning' : 'success'}`}
                                style={{ width: `${Math.min(100, member.utilization)}%` }}
                              />
                            </div>
                          </div>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <button
                            type="button"
                            className="adoTreeChevronBtn"
                            onClick={() => handleRemoveCapacityMember(member.id)}
                            title="Remove Member"
                            style={{ color: '#71717a' }}
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right Capacity Sidebar */}
          <div className="adoCapacitySidebar">
            <div className="adoSidebarCard">
              <h4>Team Capacity Progress</h4>
              <div className="adoProgressBarWrap">
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px', color: '#a1a1aa' }}>
                  <span>Total Work Assigned</span>
                  <span><b>{capacityStats.totalAssignedHours}h</b> / {capacityStats.totalTeamCapacity}h</span>
                </div>
                <div className="adoProgressTrack" style={{ height: '10px' }}>
                  <div
                    className={`adoProgressFill ${capacityStats.teamUtilization > 100 ? 'danger' : capacityStats.teamUtilization > 85 ? 'warning' : 'success'}`}
                    style={{ width: `${Math.min(100, capacityStats.teamUtilization)}%` }}
                  />
                </div>
                <span style={{ fontSize: '11px', color: capacityStats.teamUtilization > 100 ? '#f87171' : '#34d399', marginTop: '2px' }}>
                  {capacityStats.teamUtilization > 100
                    ? `⚠️ Overallocated by ${Math.round((capacityStats.totalAssignedHours - capacityStats.totalTeamCapacity) * 10) / 10} hours`
                    : `✓ ${Math.round((capacityStats.totalTeamCapacity - capacityStats.totalAssignedHours) * 10) / 10} hours available capacity`}
                </span>
              </div>
            </div>

            <div className="adoSidebarCard">
              <h4>Capacity by Activity</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {Object.entries(capacityStats.activityCapacity)
                  .filter(([_, data]) => data.capacity > 0 || data.assigned > 0)
                  .map(([activity, data]) => {
                    const actUtil = data.capacity > 0 ? Math.round((data.assigned / data.capacity) * 100) : (data.assigned > 0 ? 100 : 0)
                    return (
                      <div key={activity} className="adoCapacityBreakdownItem">
                        <div className="adoCapacityBreakdownHeader">
                          <span style={{ color: '#f4f4f5', fontWeight: 500 }}>{activity}</span>
                          <span style={{ color: data.assigned > data.capacity ? '#f87171' : '#a1a1aa' }}>
                            <b>{data.assigned}h</b> of {data.capacity}h ({actUtil}%)
                          </span>
                        </div>
                        <div className="adoProgressTrack">
                          <div
                            className={`adoProgressFill ${data.assigned > data.capacity ? 'danger' : actUtil > 85 ? 'warning' : 'success'}`}
                            style={{ width: `${Math.min(100, actUtil)}%` }}
                          />
                        </div>
                      </div>
                    )
                  })}
              </div>
            </div>

            <div className="adoSidebarCard">
              <h4>Sprint Parameters</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '11.5px', color: '#a1a1aa' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Sprint Working Days:</span>
                  <b style={{ color: '#ffffff' }}>{capacityStats.workingDays} Days</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Active Team Members:</span>
                  <b style={{ color: '#ffffff' }}>{capacityStats.memberDetails.length}</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Avg Team Capacity:</span>
                  <b style={{ color: '#ffffff' }}>
                    {capacityStats.memberDetails.length > 0 ? Math.round((capacityStats.totalTeamCapacity / capacityStats.memberDetails.length) * 10) / 10 : 0} h/person
                  </b>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="adoAnalyticsWrapper">
          {/* KPI Summary Cards */}
          <div className="adoAnalyticsKpiGrid">
            <div className="adoAnalyticsKpiCard">
              <span className="label">Total Sprint Scope</span>
              <span className="value">{analyticsMetric === 'hours' ? `${sprintStats.totalSprintWork}h` : `${boardData?.work_items.length || 0} items`}</span>
              <span className="sub">Baseline planned effort</span>
            </div>
            <div className="adoAnalyticsKpiCard">
              <span className="label">Completed Work</span>
              <span className="value" style={{ color: '#34d399' }}>
                {analyticsMetric === 'hours' ? `${sprintStats.totalCompleted}h` : `${boardData?.work_items.filter(w => ['done', 'closed', 'completed', 'resolved'].includes(w.state.toLowerCase())).length || 0} items`}
              </span>
              <span className="sub">{sprintStats.percentDelivered}% of sprint delivered</span>
            </div>
            <div className="adoAnalyticsKpiCard">
              <span className="label">Remaining Work</span>
              <span className="value" style={{ color: '#38bdf8' }}>
                {analyticsMetric === 'hours' ? `${sprintStats.totalRemaining}h` : `${boardData?.work_items.filter(w => !['done', 'closed', 'completed', 'resolved'].includes(w.state.toLowerCase())).length || 0} items`}
              </span>
              <span className="sub">Current sprint backlog</span>
            </div>
            <div className="adoAnalyticsKpiCard">
              <span className="label">Required Daily Burn</span>
              <span className="value" style={{ color: '#fbbf24' }}>
                {analyticsMetric === 'hours' ? `${sprintStats.requiredDailyBurn}h` : `${Math.round(((boardData?.work_items.filter(w => !['done', 'closed', 'completed', 'resolved'].includes(w.state.toLowerCase())).length || 0) / sprintStats.workingDays) * 10) / 10} /d`}
              </span>
              <span className="sub">Across {sprintStats.workingDays} working days</span>
            </div>
            <div className="adoAnalyticsKpiCard">
              <span className="label">Sprint Health</span>
              <span className="value" style={{ color: sprintStats.healthStatus === 'On Track' ? '#34d399' : sprintStats.healthStatus === 'At Risk' ? '#fbbf24' : '#ef4444', fontSize: '18px' }}>
                {sprintStats.healthStatus === 'On Track' ? '✓ On Track' : sprintStats.healthStatus === 'At Risk' ? '⚠️ At Risk' : '🚨 Behind Schedule'}
              </span>
              <span className="sub">Based on burn rate</span>
            </div>
          </div>

          {/* Interactive Burndown Chart Card */}
          <div className="adoBurndownCard">
            <div className="adoBurndownHeader">
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Flame size={18} color="#f59e0b" />
                <h3 style={{ margin: 0, fontSize: '15px', color: '#ffffff' }}>Sprint Burndown Chart</h3>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                <div className="adoBurndownLegend">
                  <div className="adoLegendItem">
                    <span className="adoLegendColor" style={{ background: '#71717a', height: '2px' }} />
                    <span>Ideal Trend</span>
                  </div>
                  <div className="adoLegendItem">
                    <span className="adoLegendColor" style={{ background: '#0078d4' }} />
                    <span>Remaining Work</span>
                  </div>
                  <div className="adoLegendItem">
                    <span className="adoLegendColor" style={{ background: '#10b981' }} />
                    <span>Completed Work</span>
                  </div>
                </div>

                <div style={{ display: 'flex', background: '#27272a', borderRadius: '4px', padding: '2px' }}>
                  <button
                    type="button"
                    style={{
                      background: analyticsMetric === 'hours' ? '#0078d4' : 'transparent',
                      color: '#ffffff',
                      border: 'none',
                      padding: '4px 10px',
                      fontSize: '11.5px',
                      borderRadius: '3px',
                      cursor: 'pointer',
                    }}
                    onClick={() => setAnalyticsMetric('hours')}
                  >
                    Hours
                  </button>
                  <button
                    type="button"
                    style={{
                      background: analyticsMetric === 'items' ? '#0078d4' : 'transparent',
                      color: '#ffffff',
                      border: 'none',
                      padding: '4px 10px',
                      fontSize: '11.5px',
                      borderRadius: '3px',
                      cursor: 'pointer',
                    }}
                    onClick={() => setAnalyticsMetric('items')}
                  >
                    Work Items
                  </button>
                </div>
              </div>
            </div>

            {/* SVG Burndown Rendering */}
            <div className="adoBurndownSvgWrap">
              <svg viewBox="0 0 700 280" style={{ width: '100%', height: '280px', overflow: 'visible' }}>
                <defs>
                  <linearGradient id="burndownAreaGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#0078d4" stopOpacity="0.35" />
                    <stop offset="100%" stopColor="#0078d4" stopOpacity="0.0" />
                  </linearGradient>
                </defs>

                {/* Gridlines */}
                {[0, 1, 2, 3, 4].map(idx => {
                  const y = 30 + idx * 50
                  return (
                    <g key={`grid-${idx}`}>
                      <line x1="50" y1={y} x2="660" y2={y} stroke="#2e2f38" strokeDasharray="3 3" />
                      <text x="42" y={y + 4} fill="#71717a" fontSize="10" textAnchor="end">
                        {Math.round((sprintStats.totalSprintWork || 100) * (1 - idx / 4))}
                        {analyticsMetric === 'hours' ? 'h' : ''}
                      </text>
                    </g>
                  )
                })}

                {/* X Axis Labels */}
                {burndownData.map((pt, idx) => {
                  const x = 50 + (idx / (burndownData.length - 1)) * 610
                  return (
                    <g key={`x-axis-${idx}`}>
                      <line x1={x} y1={230} x2={x} y2={235} stroke="#52525b" />
                      <text x={x} y={250} fill="#a1a1aa" fontSize="10" textAnchor="middle">
                        {pt.label}
                      </text>
                    </g>
                  )
                })}

                {/* Ideal Trend Line (Dashed) */}
                <line
                  x1="50"
                  y1="30"
                  x2="660"
                  y2="230"
                  stroke="#71717a"
                  strokeWidth="2"
                  strokeDasharray="5 5"
                />

                {/* Area under remaining line */}
                {(() => {
                  const maxVal = Math.max(1, sprintStats.totalSprintWork || 100)
                  const validPts = burndownData.filter(pt => pt.actual !== null)
                  if (validPts.length < 2) return null
                  const pointsStr = validPts
                    .map((pt, idx) => {
                      const x = 50 + (idx / (burndownData.length - 1)) * 610
                      const y = 230 - ((pt.actual || 0) / maxVal) * 200
                      return `${x},${y}`
                    })
                    .join(' ')
                  const lastX = 50 + ((validPts.length - 1) / (burndownData.length - 1)) * 610
                  return (
                    <polygon
                      points={`50,230 ${pointsStr} ${lastX},230`}
                      fill="url(#burndownAreaGradient)"
                    />
                  )
                })()}

                {/* Actual Remaining Line */}
                {(() => {
                  const maxVal = Math.max(1, sprintStats.totalSprintWork || 100)
                  const validPts = burndownData.filter(pt => pt.actual !== null)
                  if (validPts.length < 2) return null
                  const pathD = validPts.reduce((acc, pt, idx) => {
                    const x = 50 + (idx / (burndownData.length - 1)) * 610
                    const y = 230 - ((pt.actual || 0) / maxVal) * 200
                    return `${acc} ${idx === 0 ? 'M' : 'L'} ${x} ${y}`
                  }, '')
                  return <path d={pathD} fill="none" stroke="#0078d4" strokeWidth="3" />
                })()}

                {/* Completed Line */}
                {(() => {
                  const maxVal = Math.max(1, sprintStats.totalSprintWork || 100)
                  const validPts = burndownData.filter(pt => pt.completed !== null)
                  if (validPts.length < 2) return null
                  const pathD = validPts.reduce((acc, pt, idx) => {
                    const x = 50 + (idx / (burndownData.length - 1)) * 610
                    const y = 230 - ((pt.completed || 0) / maxVal) * 200
                    return `${acc} ${idx === 0 ? 'M' : 'L'} ${x} ${y}`
                  }, '')
                  return <path d={pathD} fill="none" stroke="#10b981" strokeWidth="2.5" />
                })()}

                {/* Data Points with Hover */}
                {burndownData.map((pt, idx) => {
                  const x = 50 + (idx / (burndownData.length - 1)) * 610
                  const maxVal = Math.max(1, sprintStats.totalSprintWork || 100)
                  const actualY = pt.actual !== null ? 230 - (pt.actual / maxVal) * 200 : null

                  return (
                    <g key={`pts-${idx}`} onMouseEnter={() => setHoveredDayIndex(idx)} onMouseLeave={() => setHoveredDayIndex(null)}>
                      {actualY !== null && (
                        <circle
                          cx={x}
                          cy={actualY}
                          r={hoveredDayIndex === idx ? 6 : 4}
                          fill="#0078d4"
                          stroke="#ffffff"
                          strokeWidth="2"
                          style={{ cursor: 'pointer', transition: 'all 0.15s ease' }}
                        />
                      )}
                      {hoveredDayIndex === idx && pt.actual !== null && actualY !== null && (
                        <g>
                          <rect
                            x={Math.min(560, Math.max(10, x - 55))}
                            y={Math.max(10, actualY - 50)}
                            width="110"
                            height="40"
                            rx="4"
                            fill="#18181b"
                            stroke="#3f3f46"
                          />
                          <text
                            x={Math.min(560, Math.max(10, x - 55)) + 55}
                            y={Math.max(10, actualY - 50) + 16}
                            fill="#ffffff"
                            fontSize="10.5"
                            fontWeight="bold"
                            textAnchor="middle"
                          >
                            {pt.label}
                          </text>
                          <text
                            x={Math.min(560, Math.max(10, x - 55)) + 55}
                            y={Math.max(10, actualY - 50) + 30}
                            fill="#38bdf8"
                            fontSize="10"
                            textAnchor="middle"
                          >
                            Rem: {pt.actual}{analyticsMetric === 'hours' ? 'h' : ''} | Done: {pt.completed}{analyticsMetric === 'hours' ? 'h' : ''}
                          </text>
                        </g>
                      )}
                    </g>
                  )
                })}
              </svg>
            </div>
          </div>

          {/* Flow Distribution & Member Contribution Cards */}
          <div className="adoAnalyticsFlowGrid">
            <div className="adoSidebarCard">
              <h4>Sprint State Flow Distribution</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {Object.entries(sprintStats.stateDistribution).map(([state, data]) => {
                  const pct = sprintStats.totalSprintWork > 0 ? Math.round((data.hours / sprintStats.totalSprintWork) * 100) : 0
                  return (
                    <div key={state} style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span className={`adoStateDot ${state.toLowerCase().replace(/\s+/g, '')}`} />
                          <span style={{ color: '#d4d4d8' }}>{state}</span>
                        </div>
                        <span style={{ color: '#a1a1aa' }}>
                          <b>{data.count} items</b> ({Math.round(data.hours * 10) / 10}h &bull; {pct}%)
                        </span>
                      </div>
                      <div className="adoProgressTrack">
                        <div
                          className="adoProgressFill"
                          style={{
                            width: `${pct}%`,
                            background: state === 'Done' ? '#10b981' : state === 'In Review' ? '#f59e0b' : state === 'In Progress' ? '#0078d4' : '#6b7280',
                          }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="adoSidebarCard">
              <h4>Team Member Effort Contribution</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '220px', overflowY: 'auto' }}>
                {Object.entries(sprintStats.memberEffort).map(([member, effort]) => {
                  const compPct = effort.total > 0 ? Math.round((effort.completed / effort.total) * 100) : 0
                  return (
                    <div key={member} style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px' }}>
                        <span style={{ color: '#f4f4f5', fontWeight: 500 }}>{member}</span>
                        <span style={{ color: '#a1a1aa' }}>
                          <b>{Math.round(effort.completed * 10) / 10}h done</b> / {Math.round(effort.total * 10) / 10}h ({compPct}%)
                        </span>
                      </div>
                      <div className="adoProgressTrack">
                        <div className="adoProgressFill success" style={{ width: `${compPct}%` }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 6. Comprehensive Health & Compliance Checks Modal / Drawer */}
      {showChecksModal && (
        <div className="sprintModalBackdrop" onClick={() => setShowChecksModal(false)}>
          <div className="sprintModalContent" onClick={e => e.stopPropagation()}>
            <div className="sprintModalHeader">
              <div className="sprintModalTitle">
                <ShieldAlert size={20} color="#0078d4" />
                <div>
                  <h3>Sprint Health & Quality Compliance Report</h3>
                  <p>Automated checks for accurate burndown, velocity and PR review velocity</p>
                </div>
              </div>
              <button
                type="button"
                className="sprintModalClose"
                onClick={() => setShowChecksModal(false)}
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Tabs */}
            <div className="sprintModalTabs">
              <button
                type="button"
                className={`sprintModalTab ${modalActiveTab === 'hours' ? 'active' : ''}`}
                onClick={() => setModalActiveTab('hours')}
              >
                <AlertTriangle size={15} />
                <span>Check 1: Tasks Closed With Blank Hours ({closedWithoutHoursItems.length})</span>
              </button>

              <button
                type="button"
                className={`sprintModalTab ${modalActiveTab === 'review' ? 'active' : ''}`}
                onClick={() => setModalActiveTab('review')}
              >
                <Clock size={15} />
                <span>Check 2: In Review &gt; 4 Working Days ({staleInReviewItems.length})</span>
              </button>
            </div>

            <div className="sprintModalBody">
              {modalActiveTab === 'hours' && (
                <div className="sprintModalSection">
                  <div className="sprintCheckDescription">
                    <Info size={16} color="#0078d4" />
                    <div>
                      <b>Rule 1 - Completed Work on Closed Tasks (Tasks Only):</b>
                      <p>
                        Tasks marked Closed/Done must record completed hours and cannot be left blank. If a task has <b>0 hours</b> recorded, it is considered <b>valid</b>. Only closed tasks with <b>blank / missing</b> completed hours are flagged. (Note: This check applies strictly to work items of type <b>Task</b> only).
                      </p>
                    </div>
                  </div>

                  {closedWithoutHoursItems.length === 0 ? (
                    <div className="sprintModalEmpty">
                      <CheckCircle2 size={24} color="#10b981" />
                      <span>All closed tasks in this sprint have valid completed hours logged!</span>
                    </div>
                  ) : (
                    <div className="sprintTableWrapper">
                      <table className="sprintCheckTable">
                        <thead>
                          <tr>
                            <th>ID</th>
                            <th>Task Title</th>
                            <th>Assigned To</th>
                            <th>State</th>
                            <th>Completed Work</th>
                            <th>Remaining Work</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {closedWithoutHoursItems.map(item => (
                            <tr key={item.id}>
                              <td>
                                <a
                                  href={item.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${item.id}`}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="sprintTableIdLink"
                                >
                                  #{item.id}
                                </a>
                              </td>
                              <td className="sprintTableTitle">{item.title}</td>
                              <td>{item.assigned_to_name || 'Unassigned'}</td>
                              <td>
                                <span className={`adoStateBadge ${item.state.toLowerCase()}`}>
                                  {item.state}
                                </span>
                              </td>
                              <td className="sprintBadVal">
                                {item.completed_work != null ? `${item.completed_work} hrs` : 'Blank (Not set)'}
                              </td>
                              <td>{item.remaining_work != null ? `${item.remaining_work} hrs` : '0 hrs'}</td>
                              <td>
                                <a
                                  href={item.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${item.id}`}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="sprintFixLink"
                                >
                                  Update Hours <ExternalLink size={12} />
                                </a>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {modalActiveTab === 'review' && (
                <div className="sprintModalSection">
                  <div className="sprintCheckDescription">
                    <Info size={16} color="#0078d4" />
                    <div>
                      <b>Rule 2 - Stale In Review (Working Days Only):</b>
                      <p>
                        User stories remaining in <b>In Review</b> state for more than <b>4 working days</b> (Monday through Friday, strictly excluding Saturdays and Sundays). This detects pull request review stalls and blocked QA validation.
                      </p>
                    </div>
                  </div>

                  {staleInReviewItems.length === 0 ? (
                    <div className="sprintModalEmpty">
                      <CheckCircle2 size={24} color="#10b981" />
                      <span>No user stories are stuck in review beyond 4 working days!</span>
                    </div>
                  ) : (
                    <div className="sprintTableWrapper">
                      <table className="sprintCheckTable">
                        <thead>
                          <tr>
                            <th>ID</th>
                            <th>User Story Title</th>
                            <th>Assigned To</th>
                            <th>Working Days in Review</th>
                            <th>Review Start Date</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {staleInReviewItems.map(item => (
                            <tr key={item.id}>
                              <td>
                                <a
                                  href={item.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${item.id}`}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="sprintTableIdLink"
                                >
                                  #{item.id}
                                </a>
                              </td>
                              <td className="sprintTableTitle">{item.title}</td>
                              <td>{item.assigned_to_name || 'Unassigned'}</td>
                              <td className="sprintBadVal">
                                <b>{item.business_days_in_review} working days</b> (excluding weekends)
                              </td>
                              <td>
                                {item.state_change_date
                                  ? new Date(item.state_change_date).toLocaleDateString()
                                  : '-'}
                              </td>
                              <td>
                                <a
                                  href={item.web_url || `https://dev.azure.com/${organization}/${project}/_workitems/edit/${item.id}`}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="sprintFixLink"
                                >
                                  Review in ADO <ExternalLink size={12} />
                                </a>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="sprintModalFooter">
              <span className="sprintModalNote">
                Checks are evaluated automatically on sprint items fetched from Azure DevOps Boards.
              </span>
              <button
                type="button"
                className="adoPrimaryBtn"
                onClick={() => setShowChecksModal(false)}
              >
                Close Report
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 7. Email Sprint Report Modal (Controlled by Plugin: email_sprint_report) */}
      {showEmailReport && showEmailModal && (() => {
        const isDeliverablesMode = activeSubTab === 'Deliverables'
        const sprintTitle = currentIteration ? formatSprintName(currentIteration.name, currentIteration.path) : 'Current Sprint'
        const teamTitle = teams.find(t => t.id === selectedTeamId)?.name || selectedTeamId
        const sprintLabel = formatSprintMonthYear(currentIteration?.start_date, currentIteration?.finish_date, currentIteration?.name)
        const sprintWorkingDays = Math.max(
          1,
          boardData?.sprint_working_days ||
            calculateSprintBusinessDays(currentIteration?.start_date, currentIteration?.finish_date) ||
            10
        )
        const capacityPerPerson = sprintWorkingDays * 8

        const memberCapacityMap: Record<string, number> = {}
        capacityMembers.forEach(m => {
          const availableDays = Math.max(0, sprintWorkingDays - (m.days_off || 0))
          const indCap = Math.round(availableDays * (m.capacity_per_day || 8) * 10) / 10
          memberCapacityMap[m.name] = indCap
        })

        const emailSubject = isDeliverablesMode
          ? `[Deliverables] Work Delivered in ${sprintLabel} - ${teamTitle}`
          : `[Azure Boards Health] Sprint Report: ${sprintTitle} (${teamTitle})`

        const iterToUse = boardData?.iteration || currentIteration
        const rawDelivered = deliverablesReport?.completedDeliverables || computedMilestone?.achieved_items || []
        const deliveredStories = rawDelivered.filter(item => isItemClosedInSprint(item, iterToUse))
        const deliveredMembers = isDeliverablesMode
          ? prepareMemberDeliverables(
              deliveredStories,
              deliverablesReport?.memberContributions || [],
              boardData?.work_items || [],
              memberCapacityMap,
              capacityPerPerson,
              iterToUse
            )
          : []

        const buildReport = () => {
          if (isDeliverablesMode) {
            return buildTeamDeliverablesReport({
              sprintLabel,
              capacityPerPersonHours: capacityPerPerson,
              teamTitle: String(teamTitle),
              members: deliveredMembers,
            })
          }
          return buildSprintReport({
            sprintTitle,
            teamTitle: String(teamTitle),
            activeWorkItems: boardData?.work_items?.length || 0,
            closedWithoutHours: deliverablesReport?.warningsAndHygiene
              ? deliverablesReport.warningsAndHygiene.closedWithoutHoursItems
              : closedWithoutHoursItems,
            closedWithoutHoursCount: deliverablesReport?.warningsAndHygiene
              ? deliverablesReport.warningsAndHygiene.closedWithoutHoursCount
              : checksSummary.tasks_closed_without_hours_count,
            staleInReview: deliverablesReport?.warningsAndHygiene
              ? deliverablesReport.warningsAndHygiene.staleInReviewItems
              : staleInReviewItems,
            staleInReviewCount: deliverablesReport?.warningsAndHygiene
              ? deliverablesReport.warningsAndHygiene.staleInReviewCount
              : checksSummary.stories_in_review_stale_count,
            milestone: deliverablesReport?.capacityEffortSummary
              ? {
                  closed_stories_count: deliverablesReport.capacityEffortSummary.closedStoriesCount,
                  total_stories: deliverablesReport.capacityEffortSummary.totalStories,
                  completion_rate_pct: deliverablesReport.capacityEffortSummary.completionRatePct,
                  total_delivered_hours: deliverablesReport.capacityEffortSummary.totalDeliveredHours,
                  features_delivered_count: deliverablesReport.capacityEffortSummary.featuresDeliveredCount,
                  bugs_resolved_count: deliverablesReport.capacityEffortSummary.bugsResolvedCount,
                }
              : computedMilestone,
            organization,
            project,
            dashboardUrl: window.location.origin,
          })
        }
        const generateEmailReportText = () => buildReport().text

        // mailto: links are limited in length (~2000 characters). A long list of flagged items would be cut off, so in that
        // case the full report (with links) is copied to the clipboard and the draft asks the sender to paste it.
        const MAILTO_LIMIT = 1900
        const handleSendViaOutlook = async () => {
          setEmailSending(true)
          let body = generateEmailReportText()
          const build = (b: string) => `mailto:${encodeURIComponent(emailRecipient.trim())}?subject=${encodeURIComponent(emailSubject)}&body=${encodeURIComponent(b)}`
          let needsPaste = false
          if (build(body).length > MAILTO_LIMIT) {
            await handleCopyToClipboard()
            body = isDeliverablesMode
              ? `Hi,\n\nThe full Team Deliverables Report for ${sprintLabel} (${teamTitle}) is on your clipboard - press Ctrl+V to paste it here.\n`
              : `Hi Team,\n\nThe full Sprint Health & Hygiene Report for ${sprintTitle} (${teamTitle}) is on your clipboard - press Ctrl+V to paste it here.\n`
            needsPaste = true
          }
          const mailtoUrl = build(body)

          // Open default email client (Outlook)
          const link = document.createElement('a')
          link.href = mailtoUrl
          link.target = '_blank'
          link.rel = 'noopener noreferrer'
          document.body.appendChild(link)
          link.click()
          document.body.removeChild(link)

          setEmailSending(false)
          setEmailNeedsPaste(needsPaste)
          setEmailSentSuccess(true)
        }

        const handleCopyToClipboard = async () => {
          try {
            const { text, html } = buildReport()
            // Rich copy: pasting into Outlook keeps the work item numbers as real hyperlinks.
            if (typeof ClipboardItem !== 'undefined' && navigator.clipboard?.write) {
              await navigator.clipboard.write([new ClipboardItem({
                'text/html': new Blob([html], { type: 'text/html' }),
                'text/plain': new Blob([text], { type: 'text/plain' }),
              })])
            } else {
              await navigator.clipboard.writeText(text)
            }
            setCopiedToClipboard(true)
            setTimeout(() => setCopiedToClipboard(false), 2500)
          } catch (err) {
            console.error('Failed to copy to clipboard', err)
          }
        }

        return (
          <div className="sprintModalBackdrop" onClick={() => setShowEmailModal(false)}>
            <div className="sprintModalContent emailModalContent" onClick={e => e.stopPropagation()}>
              <div className="sprintModalHeader">
                <div className="sprintModalTitle">
                  <Mail size={18} color="#06b6d4" />
                  <span>{isDeliverablesMode ? 'Send Team Deliverables Report' : 'Send Sprint Health & Hygiene Report'}</span>
                </div>
                <button
                  type="button"
                  className="sprintModalClose"
                  onClick={() => setShowEmailModal(false)}
                >
                  <X size={16} />
                </button>
              </div>

              <div className="emailModalBody">
                <div className="emailFormGroup">
                  <label className="emailFormLabel">Recipients:</label>
                  <input
                    type="text"
                    className="emailFormInput"
                    value={emailRecipient}
                    onChange={e => setEmailRecipient(e.target.value)}
                    placeholder="Assignee names or email addresses"
                  />
                </div>

                <div className="emailFormGroup">
                  <label className="emailFormLabel">Email Subject:</label>
                  <input
                    type="text"
                    className="emailFormInput"
                    readOnly
                    value={emailSubject}
                  />
                </div>

                <div className="emailPreviewBox">
                  <div className="emailPreviewHeader">
                    {isDeliverablesMode ? 'Preview of Deliverables Report Body:' : 'Preview of Report Body:'}
                  </div>
                  {isDeliverablesMode ? (
                    <div className="emailPreviewContent" style={{ fontFamily: 'Segoe UI, Arial, sans-serif' }}>
                      <p>Hi,</p>
                      <p style={{ marginTop: '8px' }}>
                        Below are the high-level details of the <u>work delivered</u> in <b>{sprintLabel}</b>.
                      </p>
                      <p style={{ marginTop: '4px', marginBottom: '16px' }}>
                        Capacity/person – <b>{capacityPerPerson} hrs.</b>
                      </p>
                      {deliveredMembers.length === 0 ? (
                        <p style={{ color: '#94a3b8', fontStyle: 'italic' }}>No completed deliverables recorded for this sprint.</p>
                      ) : (
                        deliveredMembers.map(m => (
                          <div key={m.name} style={{ marginTop: '12px' }}>
                            <p style={{ fontWeight: 600, color: '#38bdf8' }}>
                              @{m.name} ({m.hoursDelivered}h)
                            </p>
                            <ul style={{ margin: '4px 0 8px 18px', padding: 0 }}>
                              {m.storyTitles.map((st, i) => (
                                <li key={i}>{st}</li>
                              ))}
                              {m.bugCount > 0 && <li>Bug fixes ({m.bugCount} nos.)</li>}
                            </ul>
                          </div>
                        ))
                      )}
                    </div>
                  ) : (
                    <div className="emailPreviewContent">
                      <p>Hi Team,</p>
                      <p>Below are our team members who closed the task without filling hours</p>
                      {closedWithoutHoursItems.map(item => (
                        <p key={`c1-${item.id}`} style={{ paddingLeft: 14 }}>
                          <a href={workItemUrl(item, organization, project)} target="_blank" rel="noreferrer">{item.id}</a> - {assignee(item)}
                        </p>
                      ))}
                      {closedWithoutHoursItems.length === 0 && <p style={{ paddingLeft: 14 }}>.....</p>}
                      <p>Below are our team members whose work items are in review more than 4 days</p>
                      {staleInReviewItems.map(item => (
                        <p key={`c2-${item.id}`} style={{ paddingLeft: 14 }}>
                          <a href={workItemUrl(item, organization, project)} target="_blank" rel="noreferrer">{item.id}</a> - {assignee(item)}
                        </p>
                      ))}
                      {staleInReviewItems.length === 0 && <p style={{ paddingLeft: 14 }}>.....</p>}
                      <p>please let me know the reason for this miss also let us know if any process improvements needed.</p>
                      <p>Thanks,<br />Lalit</p>
                    </div>
                  )}
                </div>

                {emailSentSuccess && (
                  <div className="emailSuccessBanner" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '4px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <CheckCircle2 size={16} color="#10b981" />
                      <span>Draft opened in <b>Outlook / Default Mail Client</b> for <b>{emailRecipient}</b>!</span>
                    </div>
                    <span style={{ fontSize: '11px', color: '#94a3b8', paddingLeft: '24px' }}>
                      {emailNeedsPaste
                        ? 'The report is long, so it was copied to your clipboard: press Ctrl+V in the Outlook draft to paste it (work item numbers stay clickable), then click Send.'
                        : 'Review the draft in Outlook and click Send. You can also use "Copy to Clipboard" to paste into Teams or Webmail.'}
                    </span>
                  </div>
                )}
              </div>

              <div className="sprintModalFooter" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <button
                  type="button"
                  className="adoSecondaryBtn"
                  onClick={handleCopyToClipboard}
                  title="Copy full report text to paste in Teams, Slack, or Web Outlook"
                >
                  {copiedToClipboard ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
                  <span>{copiedToClipboard ? 'Copied to Clipboard!' : 'Copy to Clipboard'}</span>
                </button>

                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    type="button"
                    className="adoSecondaryBtn"
                    onClick={() => setShowEmailModal(false)}
                  >
                    Close
                  </button>
                  <button
                    type="button"
                    className="adoPrimaryBtn"
                    disabled={emailSending || !emailRecipient.trim()}
                    onClick={handleSendViaOutlook}
                    title="Launch draft in Outlook or default mail client"
                  >
                    <Send size={14} />
                    <span>Open in Outlook / Mail</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
