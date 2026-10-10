import { assignee, buildSprintReport, workItemUrl } from '../utils/sprintReport'
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
  ShieldCheck,
  Zap,
  Radio,
  Cpu,
  AlertCircle,
  Mail,
  Send,
} from 'lucide-react'
import { api } from '../services/api'
import { PlanningAssistant } from './PlanningAssistant'
import { BoardDataView } from './BoardDataView'
import { DeliverablesPage } from './DeliverablesPage'
import { usePlugins } from '../context/PluginContext'
import type {
  AdoTeam,
  AdoIteration,
  AdoWorkItem,
  AdoSprintChecksSummary,
  AdoSprintBoardResponse,
  AdoSprintMilestoneSummary,
  AdoMilestoneItem,
  MilestoneAiSummaryResponse
} from '../types/api'

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

type SubTab = 'Taskboard' | 'Milestone' | 'Deliverables' | 'Planning Assistant' | 'Backlog' | 'Capacity' | 'Analytics'
type FilterMode = 'all' | 'closed_without_hours' | 'stale_in_review'

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

  // Auto-switch away from Milestone if milestone plugin is disabled
  useEffect(() => {
    if (!showMilestone && activeSubTab === 'Milestone') {
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
  const [teams, setTeams] = useState<AdoTeam[]>([])
  const [selectedTeamId, setSelectedTeamId] = useState<string>(() => {
    return localStorage.getItem('ado_sprint_selected_team') || ''
  })
  const [iterations, setIterations] = useState<AdoIteration[]>([])
  const [selectedIterationId, setSelectedIterationId] = useState<string>(() => {
    return localStorage.getItem('ado_sprint_selected_iteration') || ''
  })

  // Sprint Board Data
  const [boardData, setBoardData] = useState<AdoSprintBoardResponse | null>(null)
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

  // Milestone Feature States
  const [milestoneCategoryFilter, setMilestoneCategoryFilter] = useState<'all' | 'features' | 'bugs'>('all')
  const [selectedMilestoneStream, setSelectedMilestoneStream] = useState<string>('all')
  const [milestoneSearch, setMilestoneSearch] = useState<string>('')
  const [aiSummary, setAiSummary] = useState<MilestoneAiSummaryResponse | null>(null)
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
    let isCurrent = true
    setIsLoadingTeams(true)
    api.teams(organization, project, pat)
      .then(res => {
        if (!isCurrent) return
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
    let isCurrent = true
    setIsLoadingSprints(true)
    api.sprints(organization, project, selectedTeamId, pat)
      .then(res => {
        if (!isCurrent) return
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
    setIsLoadingBoard(true)
    setErrorMessage(null)

    api.sprintBoard(organization, project, selectedTeamId, iterToUse || undefined, pat)
      .then(res => {
        setBoardData(res)
        if (res.iteration?.id) {
          setSelectedIterationId(res.iteration.id)
          localStorage.setItem('ado_sprint_selected_iteration', res.iteration.id)
        }
      })
      .catch(err => {
        setErrorMessage(err.message || 'Failed to load sprint board')
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
        setTeams(teamList)
        if (teamList.length > 0) {
          teamIdToUse = teamList[0].id
          setSelectedTeamId(teamIdToUse)
        }
      }

      if (teamIdToUse) {
        setIsLoadingSprints(true)
        const sprintList = await api.sprints(organization, project, teamIdToUse, pat)
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

  // Handle Team change
  const handleTeamChange = (teamId: string) => {
    setSelectedTeamId(teamId)
    localStorage.setItem('ado_sprint_selected_team', teamId)
    setSelectedIterationId('')
  }

  // Handle Sprint change
  const handleIterationChange = (iterationId: string) => {
    setSelectedIterationId(iterationId)
    localStorage.setItem('ado_sprint_selected_iteration', iterationId)
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
      closedStates.includes(w.state.toLowerCase())
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
    if (!computedMilestone) return []
    let list = computedMilestone.achieved_items

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
  }, [computedMilestone, selectedMilestoneStream, milestoneCategoryFilter, milestoneSearch])

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

      {/* 2. Sub Navigation Tabs: Taskboard, Milestone, Backlog, Capacity, Analytics */}
      <div className="adoSubNavTabs">
        {(['Taskboard', 'Milestone', 'Deliverables', 'Planning Assistant', 'Backlog', 'Capacity', 'Analytics'] as SubTab[])
          .filter(tab => tab !== 'Milestone' || showMilestone)
          .map(tab => (
          <button
            key={tab}
            type="button"
            className={`adoSubNavTab ${activeSubTab === tab ? 'active' : ''}`}
            onClick={() => setActiveSubTab(tab)}
          >
            {tab === 'Milestone' && <Trophy size={13} style={{ marginRight: '5px' }} />}
            {tab === 'Milestone' ? 'Milestone' : tab}
            {tab === 'Milestone' && computedMilestone && computedMilestone.closed_stories_count > 0 && (
              <span className="adoTabBadge">{computedMilestone.closed_stories_count}</span>
            )}
          </button>
        ))}
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

      {/* 4. Sprint Compliance & Health Checks Bar (Controlled by Plugins) */}
      {(showClosedWithoutHours || showStaleInReview || showEmailReport) && (
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
          {/* Milestone Quick Teaser Banner on Taskboard */}
          {computedMilestone && computedMilestone.total_stories > 0 && (
            <div className="adoTaskboardMilestoneBar" onClick={() => setActiveSubTab('Milestone')}>
              <div className="adoMilestoneBarLeft">
                <Trophy size={15} color="#f59e0b" />
                <span>
                  <b>Sprint Milestone:</b> <b>{computedMilestone.closed_stories_count}</b> of <b>{computedMilestone.total_stories}</b> stories closed ({computedMilestone.completion_rate_pct}% delivered)
                </span>
                {computedMilestone.total_delivered_hours > 0 && (
                  <span className="adoMilestoneHoursPill">
                    ⚡ {computedMilestone.total_delivered_hours}h completed
                  </span>
                )}
              </div>
              <button type="button" className="adoMilestoneViewBtn">
                View Sprint Milestone Deliverables &rarr;
              </button>
            </div>
          )}
          {isLoadingBoard && (
            <div className="adoBoardLoading">
              <RefreshCw size={24} className="spin" color="#0078d4" />
              <span>Loading Sprint Tasks...</span>
            </div>
          )}

          {errorMessage && (
            <div className="adoBoardError">
              <AlertTriangle size={18} color="#ef4444" />
              <span>{errorMessage}</span>
              <button type="button" onClick={fetchBoardData} className="adoRetryBtn">Retry</button>
            </div>
          )}

          {!isLoadingBoard && (
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
      ) : activeSubTab === 'Milestone' ? (
        <div className="adoMilestoneContainer">
          {/* Milestone Overview Hero Banner */}
          <div className="adoMilestoneHero">
            <div className="adoMilestoneHeroLeft">
              <div className="adoMilestoneBadgeRow">
                <span className="adoMilestoneTag">
                  <Trophy size={14} /> Sprint Milestone
                </span>
                <span className={`adoMilestoneStatusBadge ${
                  (computedMilestone?.completion_rate_pct || 0) >= 100
                    ? 'achieved'
                    : (computedMilestone?.completion_rate_pct || 0) >= 50
                    ? 'progress'
                    : 'started'
                }`}>
                  {(computedMilestone?.completion_rate_pct || 0) >= 100
                    ? '🏆 Sprint Goal Complete'
                    : (computedMilestone?.completion_rate_pct || 0) >= 50
                    ? '🚀 High Milestone Progress'
                    : '⚡ Active Sprint Delivery'}
                </span>
              </div>
              <h2 className="adoMilestoneTitle">
                What We Have Achieved in {formatSprintName(currentIteration.name, currentIteration.path)}
              </h2>
              <p className="adoMilestoneSubtitle">
                Dynamic sprint achievements synthesized in real time from completed user stories, backlog items, and resolved bugs.
              </p>

              {/* Progress bar */}
              <div className="adoMilestoneProgressWrap">
                <div className="adoMilestoneProgressHeader">
                  <span>Sprint Deliverables Shipped</span>
                  <b>
                    {computedMilestone?.closed_stories_count || 0} of {computedMilestone?.total_stories || 0} Stories ({computedMilestone?.completion_rate_pct || 0}%)
                  </b>
                </div>
                <div className="adoMilestoneProgressBar">
                  <div
                    className="adoMilestoneProgressFill"
                    style={{ width: `${Math.min(100, computedMilestone?.completion_rate_pct || 0)}%` }}
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
                  disabled={isGeneratingAi || !computedMilestone || computedMilestone.closed_stories_count === 0}
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
                  {computedMilestone?.closed_stories_count || 0} <span className="adoMetricTotal">/ {computedMilestone?.total_stories || 0}</span>
                </div>
                <div className="adoMetricLabel">Stories Delivered</div>
              </div>
            </div>

            <div className="adoMilestoneMetricCard">
              <div className="adoMetricIconWrap green">
                <Clock size={18} />
              </div>
              <div className="adoMetricInfo">
                <div className="adoMetricValue">
                  {computedMilestone?.total_delivered_hours || 0} <span className="adoMetricUnit">hrs</span>
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
                  {computedMilestone?.features_delivered_count || 0}
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
                  {computedMilestone?.bugs_resolved_count || 0}
                </div>
                <div className="adoMetricLabel">Bugs & Issues Resolved</div>
              </div>
            </div>
          </div>

          {/* Milestone Capability Breakdown & Next-Sprint Baseline Graph */}
          {computedMilestone?.graph_data && (
            <div className="adoMilestoneGraphCard">
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
          )}

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
                All Achieved ({computedMilestone?.achieved_items.length || 0})
              </button>
              <button
                type="button"
                className={`adoFilterPill ${milestoneCategoryFilter === 'features' ? 'active' : ''}`}
                onClick={() => setMilestoneCategoryFilter('features')}
              >
                Features & Stories ({computedMilestone?.features_delivered_count || 0})
              </button>
              <button
                type="button"
                className={`adoFilterPill ${milestoneCategoryFilter === 'bugs' ? 'active' : ''}`}
                onClick={() => setMilestoneCategoryFilter('bugs')}
              >
                Bug Fixes ({computedMilestone?.bugs_resolved_count || 0})
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
                {computedMilestone?.closed_stories_count === 0
                  ? 'No Closed User Stories in this Sprint Yet'
                  : 'No deliverables match your search criteria'}
              </h3>
              <p>
                {computedMilestone?.closed_stories_count === 0
                  ? 'As stories and bugs are transitioned to Closed or Done in Azure DevOps, your sprint milestone deliverables will update automatically in real time.'
                  : 'Try clearing your search keyword or switching the category filter above.'}
              </p>
              {computedMilestone?.closed_stories_count === 0 ? (
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
      ) : activeSubTab === 'Deliverables' ? (
        <DeliverablesPage organization={organization} project={project} team={selectedTeamId}
          teamName={teams.find(t => t.id === selectedTeamId)?.name || selectedTeamId}
          iterationId={selectedIterationId} pat={pat} />
      ) : activeSubTab === 'Planning Assistant' ? (
        <PlanningAssistant organization={organization} project={project} team={selectedTeamId} teamName={teams.find(t => t.id === selectedTeamId)?.name || selectedTeamId} iterationId={selectedIterationId} pat={pat}/>
      ) : (
        <BoardDataView view={activeSubTab.toLowerCase()} organization={organization} project={project} team={selectedTeamId} teamName={teams.find(t => t.id === selectedTeamId)?.name || selectedTeamId} iterationId={selectedIterationId} pat={pat}/>
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
        const sprintTitle = currentIteration ? formatSprintName(currentIteration.name, currentIteration.path) : 'Current Sprint'
        const teamTitle = teams.find(t => t.id === selectedTeamId)?.name || selectedTeamId
        const emailSubject = `[Azure Boards Health] Sprint Report: ${sprintTitle} (${teamTitle})`

        const buildReport = () => buildSprintReport({
          sprintTitle,
          teamTitle: String(teamTitle),
          activeWorkItems: boardData?.work_items?.length || 0,
          closedWithoutHours: closedWithoutHoursItems,
          closedWithoutHoursCount: checksSummary.tasks_closed_without_hours_count,
          staleInReview: staleInReviewItems,
          staleInReviewCount: checksSummary.stories_in_review_stale_count,
          milestone: computedMilestone,
          organization,
          project,
          dashboardUrl: window.location.origin,
        })
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
            body = `Hi Team,\n\nThe full Sprint Health & Hygiene Report for ${sprintTitle} (${teamTitle}) is on your clipboard - press Ctrl+V to paste it here.\n`
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
                  <span>Send Sprint Health & Hygiene Report</span>
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
                  <label className="emailFormLabel">Recipient Email Address:</label>
                  <input
                    type="email"
                    className="emailFormInput"
                    value={emailRecipient}
                    onChange={e => setEmailRecipient(e.target.value)}
                    placeholder="e.g. manager@octave.com"
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
                  <div className="emailPreviewHeader">Preview of Report Body:</div>
                  <div className="emailPreviewContent">
                    <p><b>Sprint:</b> {sprintTitle}</p>
                    <p><b>Team:</b> {teamTitle}</p>
                    <p><b>Hygiene Check 1:</b> {checksSummary.tasks_closed_without_hours_count} closed task(s) with blank hours</p>
                    {closedWithoutHoursItems.map(item => (
                      <p key={`c1-${item.id}`} style={{ paddingLeft: 14 }}>
                        • <a href={workItemUrl(item, organization, project)} target="_blank" rel="noreferrer">{item.id}</a> - Assigned to: {assignee(item)}
                      </p>
                    ))}
                    <p><b>Hygiene Check 2:</b> {checksSummary.stories_in_review_stale_count} user story(s) in review &gt; 4 working days</p>
                    {staleInReviewItems.map(item => (
                      <p key={`c2-${item.id}`} style={{ paddingLeft: 14 }}>
                        • <a href={workItemUrl(item, organization, project)} target="_blank" rel="noreferrer">{item.id}</a> - Assigned to: {assignee(item)}
                      </p>
                    ))}
                    {computedMilestone && (
                      <>
                        <p><b>Milestone Completion:</b> {computedMilestone.closed_stories_count}/{computedMilestone.total_stories} stories ({computedMilestone.completion_rate_pct}%)</p>
                        <p><b>Verified Delivered Effort:</b> {computedMilestone.total_delivered_hours} hrs</p>
                      </>
                    )}
                  </div>
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
