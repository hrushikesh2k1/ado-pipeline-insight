import React, { useState, useEffect, useMemo } from 'react'
import {
  AlertTriangle,
  Clock,
  UserX,
  Play,
  Pause,
  RotateCcw,
  Copy,
  Check,
  ExternalLink,
  MessageSquare,
  Sparkles,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  ShieldAlert,
  Users
} from 'lucide-react'
import type {
  AdoWorkItem,
  AdoCapacityMember,
  StandupBlockedItem,
  StandupReviewBottleneck,
  StandupWorkloadGap,
  StandupSummary
} from '../types/api'
import {
  buildStandupSummary,
  generateStandupDigest
} from '../utils/standupInsights'
import { api } from '../services/api'

interface SmartStandupViewProps {
  organization: string
  project: string
  teamName: string
  sprintName: string
  workItems: AdoWorkItem[]
  capacityMembers?: AdoCapacityMember[]
  uniqueAssignees?: string[]
  pat?: string
  onSwitchToTaskboard: () => void
}

export const SmartStandupView: React.FC<SmartStandupViewProps> = ({
  organization,
  project,
  teamName,
  sprintName,
  workItems,
  capacityMembers = [],
  uniqueAssignees = [],
  pat,
  onSwitchToTaskboard
}) => {
  // 1. Build standup insights summary
  const summary: StandupSummary = useMemo(() => {
    const membersList = (capacityMembers && capacityMembers.length > 0)
      ? capacityMembers.map(m => ({ name: m.name, capacity_per_day: m.capacity_per_day }))
      : uniqueAssignees.map(name => ({ name }))

    return buildStandupSummary(workItems, membersList)
  }, [workItems, capacityMembers, uniqueAssignees])

  // 2. Standup Timer State (default 2 minutes = 120 seconds)
  const [timerDuration, setTimerDuration] = useState<number>(120)
  const [timeLeft, setTimeLeft] = useState<number>(120)
  const [isTimerRunning, setIsTimerRunning] = useState<boolean>(false)

  useEffect(() => {
    let interval: any = null
    if (isTimerRunning && timeLeft > 0) {
      interval = setInterval(() => {
        setTimeLeft(prev => Math.max(0, prev - 1))
      }, 1000)
    } else if (timeLeft === 0) {
      setIsTimerRunning(false)
    }
    return () => clearInterval(interval)
  }, [isTimerRunning, timeLeft])

  const handleSetDuration = (seconds: number) => {
    setTimerDuration(seconds)
    setTimeLeft(seconds)
    setIsTimerRunning(false)
  }

  const handleResetTimer = () => {
    setTimeLeft(timerDuration)
    setIsTimerRunning(false)
  }

  const formatTimer = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
  }

  const timerProgress = Math.round(((timerDuration - timeLeft) / timerDuration) * 100)

  // 3. Copy Standup Digest State
  const [copiedDigest, setCopiedDigest] = useState<boolean>(false)
  const handleCopyDigest = async () => {
    const digestText = generateStandupDigest(teamName || 'Team', sprintName || 'Current Sprint', summary)
    try {
      await navigator.clipboard.writeText(digestText)
      setCopiedDigest(true)
      setTimeout(() => setCopiedDigest(false), 2500)
    } catch {
      alert('Failed to copy to clipboard.')
    }
  }

  // 4. Comments drawer/expansion state for blocked cards
  const [expandedComments, setExpandedComments] = useState<Record<number, boolean>>({})
  const [commentsLoading, setCommentsLoading] = useState<Record<number, boolean>>({})
  const [commentsCache, setCommentsCache] = useState<Record<number, Array<{ author: string; date: string; text: string }>>>({})

  const toggleComments = async (storyId: number) => {
    const nextState = !expandedComments[storyId]
    setExpandedComments(prev => ({ ...prev, [storyId]: nextState }))

    if (nextState && !commentsCache[storyId]) {
      setCommentsLoading(prev => ({ ...prev, [storyId]: true }))
      try {
        const comments = await api.workItemComments(organization, project, storyId, 3, pat)
        setCommentsCache(prev => ({ ...prev, [storyId]: comments }))
      } catch (err) {
        console.warn('Could not load comments for item', storyId, err)
        setCommentsCache(prev => ({ ...prev, [storyId]: [] }))
      } finally {
        setCommentsLoading(prev => ({ ...prev, [storyId]: false }))
      }
    }
  }

  const renderRecentComments = (workItemId: number) => {
    const isExpanded = expandedComments[workItemId]
    const comments = commentsCache[workItemId]
    const isLoadingComments = commentsLoading[workItemId]

    return (
      <div className="standupCommentsSection">
        <button
          type="button"
          className="standupCommentsToggle"
          onClick={() => toggleComments(workItemId)}
        >
          <MessageSquare size={13} />
          <span>{isExpanded ? 'Hide Recent Comments' : 'View Recent Comments'}</span>
          {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>

        {isExpanded && (
          <div className="standupCommentsDrawer">
            {isLoadingComments && (
              <p className="standupCommentsMuted">Loading latest comments from Azure DevOps...</p>
            )}
            {!isLoadingComments && comments && comments.length === 0 && (
              <p className="standupCommentsMuted">No comments recorded on this item.</p>
            )}
            {!isLoadingComments && comments && comments.length > 0 && (
              <div className="standupCommentsList">
                {comments.map((c, idx) => (
                  <div key={idx} className="standupCommentBubble">
                    <div className="standupCommentHead">
                      <b>{c.author}</b>
                      <span>{c.date ? new Date(c.date).toLocaleDateString() : ''}</span>
                    </div>
                    <p>{c.text}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="standupContainer" data-testid="smart-standup-view">
      {/* Header & Standup Mission Control */}
      <div className="standupHeaderCard">
        <div className="standupHeaderLeft">
          <div className="standupHeaderBadge">
            <Sparkles size={14} className="standupSparkleIcon" />
            <span>Smart Standup Mode</span>
          </div>
          <h2 className="standupTitle">Who Needs Help Today?</h2>
          <p className="standupSubtitle">
            Surfaces exclusively blocked items, code review bottlenecks, and unassigned workload gaps for <b>{teamName || 'Team'}</b> in <b>{sprintName || 'Current Sprint'}</b>.
          </p>
        </div>

        {/* Action Controls & Countdown Timer */}
        <div className="standupHeaderRight">
          {/* Interactive Countdown Timer */}
          <div className="standupTimerBox">
            <div className="standupTimerTop">
              <span className="standupTimerLabel">
                <Clock size={13} />
                <span>Standup Timer</span>
              </span>
              <div className="standupDurationPills">
                <button
                  type="button"
                  className={`standupDurBtn ${timerDuration === 120 ? 'active' : ''}`}
                  onClick={() => handleSetDuration(120)}
                >
                  2m
                </button>
                <button
                  type="button"
                  className={`standupDurBtn ${timerDuration === 300 ? 'active' : ''}`}
                  onClick={() => handleSetDuration(300)}
                >
                  5m
                </button>
              </div>
            </div>

            <div className="standupTimerClock">
              <span className={`standupTimeText ${timeLeft <= 30 && timeLeft > 0 ? 'warning' : ''} ${timeLeft === 0 ? 'expired' : ''}`}>
                {formatTimer(timeLeft)}
              </span>
              <div className="standupTimerControls">
                <button
                  type="button"
                  className="standupTimerBtn"
                  onClick={() => setIsTimerRunning(!isTimerRunning)}
                  title={isTimerRunning ? 'Pause timer' : 'Start timer'}
                >
                  {isTimerRunning ? <Pause size={14} /> : <Play size={14} />}
                </button>
                <button
                  type="button"
                  className="standupTimerBtn"
                  onClick={handleResetTimer}
                  title="Reset timer"
                >
                  <RotateCcw size={14} />
                </button>
              </div>
            </div>

            <div className="standupTimerBar">
              <div className="standupTimerFill" style={{ width: `${timerProgress}%` }} />
            </div>
          </div>

          {/* Quick Actions */}
          <div className="standupActionButtons">
            <button
              type="button"
              className="standupCopyBtn"
              onClick={handleCopyDigest}
              title="Copy formatted standup summary for Teams or Slack"
            >
              {copiedDigest ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
              <span>{copiedDigest ? 'Copied to Clipboard!' : 'Copy Teams / Slack Digest'}</span>
            </button>
            <button
              type="button"
              className="standupSecondaryBtn"
              onClick={onSwitchToTaskboard}
            >
              <span>Back to Taskboard</span>
              <ArrowRight size={14} />
            </button>
          </div>
        </div>
      </div>

      {/* KPI Attention Cards */}
      <div className="standupKpiGrid">
        <div className={`standupKpiCard ${summary.blocked_items.length > 0 ? 'critical' : 'good'}`}>
          <div className="standupKpiIconBox critical">
            <ShieldAlert size={20} />
          </div>
          <div className="standupKpiData">
            <span className="standupKpiCount">{summary.blocked_items.length}</span>
            <span className="standupKpiTitle">Blocked Items</span>
            <span className="standupKpiDesc">
              {summary.blocked_items.length === 0 ? 'No blockers active' : 'Impediments stopping progress'}
            </span>
          </div>
        </div>

        <div className={`standupKpiCard ${summary.review_bottlenecks.length > 0 ? 'warning' : 'good'}`}>
          <div className="standupKpiIconBox warning">
            <Clock size={20} />
          </div>
          <div className="standupKpiData">
            <span className="standupKpiCount">{summary.review_bottlenecks.length}</span>
            <span className="standupKpiTitle">Review Bottlenecks</span>
            <span className="standupKpiDesc">
              {summary.review_bottlenecks.length === 0 ? 'Reviews moving smoothly' : 'Items waiting in review'}
            </span>
          </div>
        </div>

        <div className={`standupKpiCard ${summary.workload_gaps.length > 0 ? 'info' : 'good'}`}>
          <div className="standupKpiIconBox info">
            <UserX size={20} />
          </div>
          <div className="standupKpiData">
            <span className="standupKpiCount">{summary.workload_gaps.length}</span>
            <span className="standupKpiTitle">Workload Gaps</span>
            <span className="standupKpiDesc">
              {summary.workload_gaps.length === 0 ? 'Full active engagement' : 'Members with 0 active tasks'}
            </span>
          </div>
        </div>
      </div>

      {/* Main Focus Sections */}
      <div className="standupSections">
        {/* Section 1: Blocked Work */}
        <section className="standupSection" data-testid="standup-blocked-section">
          <div className="standupSectionHeader">
            <div className="standupSectionTitleGroup">
              <span className="standupSectionIcon critical">🚨</span>
              <h3>Blocked Work & Critical Impediments</h3>
              <span className="standupSectionBadge critical">{summary.blocked_items.length}</span>
            </div>
            <p className="standupSectionHint">Address these first. Stories or tasks flagged with blockers or blocked states.</p>
          </div>

          {summary.blocked_items.length === 0 ? (
            <div className="standupEmptyState good">
              <Sparkles size={24} color="#10b981" />
              <h4>No Blockers Today!</h4>
              <p>All active work items are moving without reported impediments.</p>
            </div>
          ) : (
            <div className="standupCardsGrid">
              {summary.blocked_items.map((item: StandupBlockedItem) => {
                return (
                  <article key={item.id} className="standupCard blocked" data-testid={`standup-blocked-${item.id}`}>
                    <div className="standupCardTop">
                      <div className="standupCardTags">
                        <span className="standupIdBadge">#{item.id}</span>
                        <span className="standupTypeChip">{item.work_item_type}</span>
                        <span className="standupReasonTag critical">{item.reason}</span>
                      </div>
                      {item.web_url && (
                        <a
                          href={item.web_url}
                          target="_blank"
                          rel="noreferrer"
                          className="standupExternalLink"
                          title="Open work item in Azure DevOps"
                        >
                          <ExternalLink size={13} />
                        </a>
                      )}
                    </div>

                    <h4 className="standupCardHeading">{item.title}</h4>

                    <div className="standupCardMeta">
                      <div className="standupAssignee">
                        {item.assigned_to_avatar ? (
                          <img src={item.assigned_to_avatar} alt={item.assigned_to_name || ''} className="standupAvatar" />
                        ) : (
                          <div className="standupAvatarPlaceholder">
                            {(item.assigned_to_name || 'U').charAt(0).toUpperCase()}
                          </div>
                        )}
                        <span className="standupAssigneeName">{item.assigned_to_name || 'Unassigned'}</span>
                      </div>
                      <div className="standupStatsRow">
                        {item.story_points !== null && item.story_points !== undefined && (
                          <span className="standupStatPill">{item.story_points} pts</span>
                        )}
                        {item.remaining_work !== null && item.remaining_work !== undefined && (
                          <span className="standupStatPill">{item.remaining_work}h rem</span>
                        )}
                        {item.area_path && (
                          <span className="standupAreaPill" title={item.area_path}>{item.area_path}</span>
                        )}
                      </div>
                    </div>

                    {/* Expandable Recent Comments from ADO */}
                    {renderRecentComments(item.id)}
                  </article>
                )
              })}
            </div>
          )}
        </section>

        {/* Section 2: Review Bottlenecks */}
        <section className="standupSection" data-testid="standup-review-section">
          <div className="standupSectionHeader">
            <div className="standupSectionTitleGroup">
              <span className="standupSectionIcon warning">⏳</span>
              <h3>Review Bottlenecks</h3>
              <span className="standupSectionBadge warning">{summary.review_bottlenecks.length}</span>
            </div>
            <p className="standupSectionHint">Work items in review status that require peer review attention or merge verification.</p>
          </div>

          {summary.review_bottlenecks.length === 0 ? (
            <div className="standupEmptyState good">
              <Sparkles size={24} color="#10b981" />
              <h4>No Review Bottlenecks!</h4>
              <p>Code reviews are circulating quickly across the team.</p>
            </div>
          ) : (
            <div className="standupCardsGrid">
              {summary.review_bottlenecks.map((item: StandupReviewBottleneck) => {
                const isHighStale = item.business_days_in_review >= 3
                return (
                  <article key={item.id} className="standupCard review" data-testid={`standup-review-${item.id}`}>
                    <div className="standupCardTop">
                      <div className="standupCardTags">
                        <span className="standupIdBadge">#{item.id}</span>
                        <span className="standupTypeChip">{item.work_item_type}</span>
                        <span className={`standupAgeChip ${isHighStale ? 'critical' : 'warning'}`}>
                          <Clock size={11} />
                          <span>
                            {item.business_days_in_review === 1 ? '1 day in review' : `${item.business_days_in_review} days in review`}
                          </span>
                        </span>
                      </div>
                      {item.web_url && (
                        <a
                          href={item.web_url}
                          target="_blank"
                          rel="noreferrer"
                          className="standupExternalLink"
                          title="Open work item in Azure DevOps"
                        >
                          <ExternalLink size={13} />
                        </a>
                      )}
                    </div>

                    <h4 className="standupCardHeading">{item.title}</h4>

                    <div className="standupCardMeta">
                      <div className="standupAssignee">
                        {item.assigned_to_avatar ? (
                          <img src={item.assigned_to_avatar} alt={item.assigned_to_name || ''} className="standupAvatar" />
                        ) : (
                          <div className="standupAvatarPlaceholder">
                            {(item.assigned_to_name || 'U').charAt(0).toUpperCase()}
                          </div>
                        )}
                        <span className="standupAssigneeName">{item.assigned_to_name || 'Unassigned'}</span>
                      </div>
                      <div className="standupStatsRow">
                        {item.story_points !== null && item.story_points !== undefined && (
                          <span className="standupStatPill">{item.story_points} pts</span>
                        )}
                        {item.area_path && (
                          <span className="standupAreaPill" title={item.area_path}>{item.area_path}</span>
                        )}
                      </div>
                    </div>

                    {/* Expandable Recent Comments from ADO */}
                    {renderRecentComments(item.id)}
                  </article>
                )
              })}
            </div>
          )}
        </section>

        {/* Section 3: Workload Gaps */}
        <section className="standupSection" data-testid="standup-gaps-section">
          <div className="standupSectionHeader">
            <div className="standupSectionTitleGroup">
              <span className="standupSectionIcon info">⚠️</span>
              <h3>Workload Gaps & Availability</h3>
              <span className="standupSectionBadge info">{summary.workload_gaps.length}</span>
            </div>
            <p className="standupSectionHint">Engineers who have 0 tasks in progress today and are available to pull queued work or pair.</p>
          </div>

          {summary.workload_gaps.length === 0 ? (
            <div className="standupEmptyState good">
              <Users size={24} color="#10b981" />
              <h4>Full Active Engagement!</h4>
              <p>Every team member has active in-progress tasks assigned for today.</p>
            </div>
          ) : (
            <div className="standupGapsGrid">
              {summary.workload_gaps.map((gap: StandupWorkloadGap) => (
                <article key={gap.member_name} className="standupGapCard" data-testid={`standup-gap-${gap.member_name}`}>
                  <div className="standupGapHeader">
                    <div className="standupGapUser">
                      {gap.avatar ? (
                        <img src={gap.avatar} alt={gap.member_name} className="standupAvatar lg" />
                      ) : (
                        <div className="standupAvatarPlaceholder lg">
                          {gap.member_name.charAt(0).toUpperCase()}
                        </div>
                      )}
                      <div>
                        <h4 className="standupGapName">{gap.member_name}</h4>
                        <span className="standupGapStatusPill">0 active tasks in progress</span>
                      </div>
                    </div>
                    {gap.capacity_per_day && gap.capacity_per_day > 0 && (
                      <span className="standupCapacityPill">{gap.capacity_per_day}h/day cap</span>
                    )}
                  </div>

                  <div className="standupGapBody">
                    <h5 className="standupGapQueueHeading">
                      {gap.next_up_items.length > 0
                        ? `Queued To-Do Items (${gap.to_do_count}):`
                        : 'No assigned to-do items currently:'}
                    </h5>

                    {gap.next_up_items.length > 0 ? (
                      <ul className="standupQueueList">
                        {gap.next_up_items.map(item => (
                          <li key={item.id} className="standupQueueItem">
                            <span className="standupIdPill">#{item.id}</span>
                            <span className="standupQueueTitle" title={item.title}>{item.title}</span>
                            {item.web_url && (
                              <a href={item.web_url} target="_blank" rel="noreferrer" className="standupExternalLink mini">
                                <ExternalLink size={11} />
                              </a>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="standupEmptyQueueNote">
                        Available to pull unassigned backlog stories or pair with teammates on review bottlenecks.
                      </p>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
