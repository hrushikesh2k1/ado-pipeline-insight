import React, { useState, useEffect, useMemo } from 'react'
import {
  GitPullRequest,
  GitBranch,
  ExternalLink,
  Search,
  RefreshCw,
  CheckCircle2,
  Clock3,
  AlertTriangle,
  User,
  GitMerge,
  Filter,
  Check,
  ChevronDown,
  Sparkles,
} from 'lucide-react'
import { api } from '../services/api'
import type { AdoRepository, AdoPullRequest, AdoReviewer, PullRequestReviewResponse } from '../types/api'
import { PrReviewDrawer } from './PrReviewDrawer'
import { progressText, reviewIsStale } from '../utils/prReview'
import { usePlugins } from '../context/PluginContext'

interface PullRequestsPageProps {
  organization: string
  project: string
  pat: string
  projects: { id: string; name: string }[]
  onOrganizationChange: (org: string) => void
  onProjectChange: (proj: string) => void
  onPatChange?: (pat: string) => void
  theme?: 'dark' | 'light'
}

function timeAgo(dateString: string): string {
  try {
    const date = new Date(dateString)
    const now = new Date()
    const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000)
    if (diffSec < 60) return 'just now'
    const diffMin = Math.floor(diffSec / 60)
    if (diffMin < 60) return `${diffMin}m ago`
    const diffHours = Math.floor(diffMin / 60)
    if (diffHours < 24) return `${diffHours}h ago`
    const diffDays = Math.floor(diffHours / 24)
    if (diffDays < 30) return `${diffDays}d ago`
    return date.toLocaleDateString()
  } catch {
    return dateString
  }
}

function cleanBranchName(refName: string): string {
  if (!refName) return ''
  return refName.replace(/^refs\/heads\//, '')
}

function getVoteBadge(vote: number): { label: string; className: string; icon: React.ReactNode } {
  switch (vote) {
    case 10:
      return {
        label: 'Approved',
        className: 'voteApproved',
        icon: <CheckCircle2 size={13} />,
      }
    case 5:
      return {
        label: 'Approved with suggestions',
        className: 'voteSuggestions',
        icon: <Check size={13} />,
      }
    case -5:
      return {
        label: 'Waiting for author',
        className: 'voteWaiting',
        icon: <Clock3 size={13} />,
      }
    case -10:
      return {
        label: 'Rejected',
        className: 'voteRejected',
        icon: <AlertTriangle size={13} />,
      }
    default:
      return {
        label: 'Review pending',
        className: 'votePending',
        icon: <Clock3 size={13} />,
      }
  }
}

export const PullRequestsPage: React.FC<PullRequestsPageProps> = ({
  organization,
  project,
  pat,
  projects,
  onOrganizationChange,
  onProjectChange,
  onPatChange,
}) => {
  const { isPluginActive } = usePlugins()
  const showAiPrReviewer = isPluginActive('ai_pr_reviewer')

  const [repositories, setRepositories] = useState<AdoRepository[]>([])
  const [selectedRepoId, setSelectedRepoId] = useState<string>(() => {
    return localStorage.getItem('ado_pr_selected_repo') || ''
  })
  const [isLoadingRepos, setIsLoadingRepos] = useState<boolean>(false)
  const [reposError, setReposError] = useState<string | null>(null)

  const [pullRequests, setPullRequests] = useState<AdoPullRequest[]>([])
  const [isLoadingPRs, setIsLoadingPRs] = useState<boolean>(false)
  const [prsError, setPrsError] = useState<string | null>(null)

  const [searchQuery, setSearchQuery] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<'active' | 'completed' | 'abandoned' | 'all'>('active')
  const [reviewFilter, setReviewFilter] = useState<'all' | 'approved' | 'waiting' | 'drafts'>('all')

  // PR Review State
  const [reviewingPrId, setReviewingPrId] = useState<number | null>(null)
  const [activeReview, setActiveReview] = useState<{ pr: AdoPullRequest; review: PullRequestReviewResponse } | null>(null)
  const [reviewsCache, setReviewsCache] = useState<Record<number, PullRequestReviewResponse>>({})
  const [reviewError, setReviewError] = useState<{ prId: number; message: string } | null>(null)
  const [reviewProgress, setReviewProgress] = useState<{ prId: number; text: string } | null>(null)

  const handleReviewPR = (targetPr: AdoPullRequest, force = false) => {
    // A review made at the commit that is still at the tip of the branch is shown as it is; after new commits, or when asked, it is made again
    const cached = reviewsCache[targetPr.id]
    if (cached && !force && !reviewIsStale(cached, targetPr)) {
      setActiveReview({ pr: targetPr, review: cached })
      return
    }

    setReviewingPrId(targetPr.id)
    setReviewError(null)
    setReviewProgress({ prId: targetPr.id, text: 'Starting' })

    api.reviewPullRequest({
      organization,
      project,
      repository_id: selectedRepoId,
      pull_request_id: targetPr.id,
      pat,
    }, (job) => setReviewProgress({ prId: targetPr.id, text: progressText(job) }))
      .then((res) => {
        setReviewingPrId(null)
        setReviewProgress(null)
        setReviewsCache((prev) => ({ ...prev, [targetPr.id]: res }))
        setActiveReview({ pr: targetPr, review: res })
      })
      .catch((err) => {
        setReviewingPrId(null)
        setReviewProgress(null)
        setReviewError({
          prId: targetPr.id,
          message: err instanceof Error ? err.message : 'Failed to generate review comments',
        })
      })
  }

  // Fetch repositories whenever org, project, or pat changes
  useEffect(() => {
    let isCurrent = true
    if (!organization || !project) {
      setRepositories([])
      setSelectedRepoId('')
      return
    }

    setIsLoadingRepos(true)
    setReposError(null)

    api.repositories(organization, project, pat)
      .then((repos) => {
        if (!isCurrent) return
        setRepositories(repos)
        setIsLoadingRepos(false)

        // If currently selected repo is not in this new list, select the first one
        if (repos.length > 0) {
          const exists = repos.some(r => r.id === selectedRepoId)
          if (!exists) {
            const firstId = repos[0].id
            setSelectedRepoId(firstId)
            localStorage.setItem('ado_pr_selected_repo', firstId)
          }
        } else {
          setSelectedRepoId('')
          localStorage.removeItem('ado_pr_selected_repo')
        }
      })
      .catch((err) => {
        if (!isCurrent) return
        setIsLoadingRepos(false)
        setReposError(err instanceof Error ? err.message : 'Failed to fetch repositories')
      })

    return () => {
      isCurrent = false
    }
  }, [organization, project, pat])

  // Fetch pull requests when repo or status filter changes
  const fetchPRs = () => {
    if (!organization || !project || !selectedRepoId) {
      setPullRequests([])
      return
    }

    setIsLoadingPRs(true)
    setPrsError(null)

    api.pullRequests(organization, project, selectedRepoId, pat, statusFilter)
      .then((prs) => {
        setPullRequests(prs)
        setIsLoadingPRs(false)
      })
      .catch((err) => {
        setIsLoadingPRs(false)
        setPrsError(err instanceof Error ? err.message : 'Failed to fetch pull requests')
      })
  }

  useEffect(() => {
    fetchPRs()
  }, [organization, project, selectedRepoId, pat, statusFilter])

  const handleRepoChange = (repoId: string) => {
    setSelectedRepoId(repoId)
    localStorage.setItem('ado_pr_selected_repo', repoId)
  }

  // Summary counts
  const stats = useMemo(() => {
    const total = pullRequests.length
    const approved = pullRequests.filter(pr => pr.reviewers?.some(r => r.vote === 10)).length
    const waiting = pullRequests.filter(pr => !pr.reviewers?.length || pr.reviewers.some(r => r.vote === 0 || r.vote === -5)).length
    const drafts = pullRequests.filter(pr => pr.is_draft).length
    return { total, approved, waiting, drafts }
  }, [pullRequests])

  // Filtered PRs by search and review filter
  const filteredPRs = useMemo(() => {
    return pullRequests.filter((pr) => {
      // Review filter
      if (reviewFilter === 'approved' && !pr.reviewers?.some(r => r.vote === 10)) return false
      if (reviewFilter === 'waiting' && pr.reviewers?.some(r => r.vote === 10)) return false
      if (reviewFilter === 'drafts' && !pr.is_draft) return false

      // Search query
      if (!searchQuery.trim()) return true
      const q = searchQuery.toLowerCase().trim()
      const titleMatch = pr.title.toLowerCase().includes(q)
      const idMatch = pr.id.toString().includes(q)
      const authorMatch = pr.created_by_name.toLowerCase().includes(q)
      const sourceMatch = cleanBranchName(pr.source_branch).toLowerCase().includes(q)
      const targetMatch = cleanBranchName(pr.target_branch).toLowerCase().includes(q)

      return titleMatch || idMatch || authorMatch || sourceMatch || targetMatch
    })
  }, [pullRequests, reviewFilter, searchQuery])

  const selectedRepo = repositories.find(r => r.id === selectedRepoId)

  return (
    <div className="prPageContainer">
      {/* Top Filter and Discovery Toolbar */}
      <div className="prToolbar">
        <div className="prToolbarLeft">
          <div className="prToolbarItem">
            <span className="prToolbarLabel">Org:</span>
            <input
              type="text"
              className="prOrgInput"
              placeholder="Organization"
              value={organization}
              onChange={(e) => onOrganizationChange(e.target.value)}
            />
          </div>

          <div className="prToolbarItem">
            <span className="prToolbarLabel">PAT:</span>
            <input
              type="password"
              className="prPatInput"
              placeholder={pat ? '••••••••••••••••' : 'PAT Token'}
              value={pat}
              onChange={(e) => onPatChange?.(e.target.value)}
              autoComplete="off"
            />
          </div>

          <div className="prToolbarItem">
            <span className="prToolbarLabel">Project:</span>
            <div className="prCustomSelectWrapper">
              <select
                className="prCustomSelect"
                value={project}
                onChange={(e) => onProjectChange(e.target.value)}
              >
                <option value="">Select Project</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.name}>
                    {p.name}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} className="prSelectArrow" />
            </div>
          </div>

          <div className="prToolbarItem">
            <span className="prToolbarLabel">Repository:</span>
            <div className="prCustomSelectWrapper">
              <select
                className="prCustomSelect"
                value={selectedRepoId}
                onChange={(e) => handleRepoChange(e.target.value)}
                disabled={isLoadingRepos || repositories.length === 0}
              >
                <option value="">
                  {isLoadingRepos
                    ? 'Loading Repos...'
                    : repositories.length === 0
                    ? 'No Repos Found'
                    : 'Select Repository'}
                </option>
                {repositories.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} className="prSelectArrow" />
            </div>
          </div>
        </div>

        <div className="prToolbarRight">
          <button
            type="button"
            className="prRefreshBtn"
            onClick={fetchPRs}
            disabled={isLoadingPRs || !selectedRepoId}
            title="Refresh Pull Requests"
          >
            <RefreshCw size={14} className={isLoadingPRs ? 'spin' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Repos Error Banner */}
      {reposError && (
        <div className="prAlert prAlertError">
          <AlertTriangle size={16} />
          <div>
            <strong>Error loading repositories:</strong> {reposError}
          </div>
        </div>
      )}

      {/* Main PR Content Area */}
      {!organization || !project ? (
        <div className="prEmptyPlaceholder">
          <div className="prEmptyIcon">
            <GitPullRequest size={36} />
          </div>
          <h3>Select Organization & Project</h3>
          <p>
            Choose an Azure DevOps organization and project from the top toolbar to view repositories and active pull requests.
          </p>
        </div>
      ) : !selectedRepoId ? (
        <div className="prEmptyPlaceholder">
          <div className="prEmptyIcon">
            <GitBranch size={36} />
          </div>
          <h3>Select a Repository</h3>
          <p>
            Choose a Git repository from the dropdown above to discover all active pull requests and reviewer statuses.
          </p>
        </div>
      ) : (
        <>
          {/* Stats Summary Cards */}
          <div className="prStatsGrid">
            <div className="prStatCard">
              <div className="prStatIcon prIconCyan">
                <GitPullRequest size={18} />
              </div>
              <div className="prStatContent">
                <span className="prStatLabel">ACTIVE PRs</span>
                <div className="prStatValue">{stats.total}</div>
                <span className="prStatSub">In {selectedRepo?.name || 'repository'}</span>
              </div>
            </div>

            <div className="prStatCard">
              <div className="prStatIcon prIconGreen">
                <CheckCircle2 size={18} />
              </div>
              <div className="prStatContent">
                <span className="prStatLabel">APPROVED</span>
                <div className="prStatValue">{stats.approved}</div>
                <span className="prStatSub">Ready for merge</span>
              </div>
            </div>

            <div className="prStatCard">
              <div className="prStatIcon prIconAmber">
                <Clock3 size={18} />
              </div>
              <div className="prStatContent">
                <span className="prStatLabel">NEEDS REVIEW</span>
                <div className="prStatValue">{stats.waiting}</div>
                <span className="prStatSub">Pending votes</span>
              </div>
            </div>

            <div className="prStatCard">
              <div className="prStatIcon prIconPurple">
                <GitMerge size={18} />
              </div>
              <div className="prStatContent">
                <span className="prStatLabel">DRAFT PRs</span>
                <div className="prStatValue">{stats.drafts}</div>
                <span className="prStatSub">Work in progress</span>
              </div>
            </div>
          </div>

          {/* Filter & Search Bar */}
          <div className="prFilterBar">
            <div className="prSearchBox">
              <Search size={15} className="prSearchIcon" />
              <input
                type="text"
                placeholder="Search PR title, ID, author, or branch..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button
                  type="button"
                  className="prSearchClear"
                  onClick={() => setSearchQuery('')}
                >
                  ✕
                </button>
              )}
            </div>

            <div className="prFilterPills">
              <button
                type="button"
                className={`prFilterPill ${reviewFilter === 'all' ? 'active' : ''}`}
                onClick={() => setReviewFilter('all')}
              >
                All ({stats.total})
              </button>
              <button
                type="button"
                className={`prFilterPill ${reviewFilter === 'approved' ? 'active' : ''}`}
                onClick={() => setReviewFilter('approved')}
              >
                Approved ({stats.approved})
              </button>
              <button
                type="button"
                className={`prFilterPill ${reviewFilter === 'waiting' ? 'active' : ''}`}
                onClick={() => setReviewFilter('waiting')}
              >
                Needs Review ({stats.waiting})
              </button>
              {stats.drafts > 0 && (
                <button
                  type="button"
                  className={`prFilterPill ${reviewFilter === 'drafts' ? 'active' : ''}`}
                  onClick={() => setReviewFilter('drafts')}
                >
                  Drafts ({stats.drafts})
                </button>
              )}
            </div>
          </div>

          {/* PR List / Status Display */}
          {isLoadingPRs ? (
            <div className="prLoadingState">
              <RefreshCw size={24} className="spin prLoadingSpinner" />
              <p>Fetching active pull requests from Azure DevOps...</p>
            </div>
          ) : prsError ? (
            <div className="prAlert prAlertError">
              <AlertTriangle size={16} />
              <div>
                <strong>Failed to load pull requests:</strong> {prsError}
              </div>
            </div>
          ) : filteredPRs.length === 0 ? (
            <div className="prEmptyPlaceholder">
              <div className="prEmptyIcon">
                <CheckCircle2 size={36} />
              </div>
              <h3>No Active Pull Requests Found</h3>
              <p>
                {searchQuery || reviewFilter !== 'all'
                  ? 'No pull requests match your current filters.'
                  : `There are currently no active pull requests for ${selectedRepo?.name}.`}
              </p>
            </div>
          ) : (
            <div className="prList">
              {filteredPRs.map((pr) => {
                const sourceBranch = cleanBranchName(pr.source_branch)
                const targetBranch = cleanBranchName(pr.target_branch)

                return (
                  <div key={pr.id} className="prCard">
                    <div className="prCardMain">
                      <div className="prCardHeader">
                        <div className="prIdBadge">#{pr.id}</div>
                        <h3 className="prTitle">
                          {pr.web_url ? (
                            <a
                              href={pr.web_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="prTitleLink"
                            >
                              {pr.title}
                              <ExternalLink size={13} className="prExternalIcon" />
                            </a>
                          ) : (
                            pr.title
                          )}
                        </h3>
                        {pr.is_draft && <span className="prTagDraft">Draft</span>}
                        {pr.merge_status === 'conflicts' && (
                          <span className="prTagConflict">Conflicts</span>
                        )}
                      </div>

                      {pr.description && (
                        <p className="prDescription">
                          {pr.description.length > 180
                            ? `${pr.description.substring(0, 180)}...`
                            : pr.description}
                        </p>
                      )}

                      <div className="prCardMeta">
                        <div className="prAuthor">
                          {pr.created_by_avatar ? (
                            <img
                              src={pr.created_by_avatar}
                              alt={pr.created_by_name}
                              className="prAvatar"
                            />
                          ) : (
                            <div className="prAvatarFallback">
                              <User size={12} />
                            </div>
                          )}
                          <span className="prAuthorName">{pr.created_by_name}</span>
                          <span className="prMetaDot">•</span>
                          <span className="prTimeAgo">{timeAgo(pr.creation_date)}</span>
                        </div>

                        <div className="prBranchFlow">
                          <GitBranch size={13} className="prBranchIcon" />
                          <span className="prBranchSource" title={sourceBranch}>
                            {sourceBranch}
                          </span>
                          <span className="prBranchArrow">→</span>
                          <span className="prBranchTarget" title={targetBranch}>
                            {targetBranch}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Reviewers & Actions Column */}
                    <div className="prCardSide">
                      <div className="prReviewersSection">
                        <span className="prReviewersTitle">
                          Reviewers ({pr.reviewers?.length || 0})
                        </span>
                        <div className="prReviewersList">
                          {pr.reviewers && pr.reviewers.length > 0 ? (
                            pr.reviewers.map((rev) => {
                              const badge = getVoteBadge(rev.vote)
                              return (
                                <div
                                  key={rev.id || rev.unique_name || rev.display_name}
                                  className={`prReviewerItem ${badge.className}`}
                                  title={`${rev.display_name}: ${badge.label}`}
                                >
                                  {rev.image_url ? (
                                    <img
                                      src={rev.image_url}
                                      alt={rev.display_name}
                                      className="prReviewerAvatar"
                                    />
                                  ) : (
                                    <div className="prReviewerFallback">
                                      {rev.display_name.charAt(0).toUpperCase()}
                                    </div>
                                  )}
                                  <span className="prReviewerName">{rev.display_name}</span>
                                  <span className="prVoteIcon">{badge.icon}</span>
                                </div>
                              )
                            })
                          ) : (
                            <span className="prNoReviewers">No reviewers assigned</span>
                          )}
                        </div>
                      </div>

                      <div className="prActionButtons">
                        {showAiPrReviewer && (
                          <button
                            type="button"
                            className={`prAddReviewCommentsBtn ${reviewsCache[pr.id] ? 'reviewed' : ''}`}
                            onClick={() => handleReviewPR(pr)}
                            disabled={reviewingPrId === pr.id}
                            title="Review the changes of this pull request with AI and view the findings on screen (nothing is posted to Azure DevOps)"
                          >
                            <Sparkles size={13} className={reviewingPrId === pr.id ? 'spin' : ''} />
                            <span>
                              {reviewingPrId === pr.id
                                ? 'Reviewing...'
                                : reviewsCache[pr.id]
                                ? reviewIsStale(reviewsCache[pr.id], pr) ? 'Review again (new commits)' : 'View AI review'
                                : 'Review with AI'}
                            </span>
                          </button>
                        )}

                        {pr.web_url && (
                          <a
                            href={pr.web_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="prActionLink"
                          >
                            <span>Review in ADO</span>
                            <ExternalLink size={13} />
                          </a>
                        )}
                      </div>

                      {reviewProgress && reviewProgress.prId === pr.id && (
                        <div className="prCardReviewProgress" data-testid="pr-review-progress" role="status">
                          <Clock3 size={11} />
                          <span>{reviewProgress.text}</span>
                        </div>
                      )}

                      {reviewError && reviewError.prId === pr.id && (
                        <div className="prCardReviewError">
                          <AlertTriangle size={12} />
                          <span>{reviewError.message}</span>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}

      {activeReview && (
        <PrReviewDrawer
          reviewData={activeReview}
          onClose={() => setActiveReview(null)}
          isStale={reviewIsStale(activeReview.review, pullRequests.find(p => p.id === activeReview.pr.id) ?? activeReview.pr)}
          isReReviewing={reviewingPrId === activeReview.pr.id}
          onReReview={() => handleReviewPR(activeReview.pr, true)}
          error={reviewError && reviewError.prId === activeReview.pr.id ? reviewError.message : null}
        />
      )}
    </div>
  )
}
