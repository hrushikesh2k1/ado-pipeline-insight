import React, { useState, useEffect, useMemo } from 'react'
import {
  Trophy,
  Medal,
  Award,
  Search,
  RefreshCw,
  AlertTriangle,
  ExternalLink,
  ChevronDown,
  Copy,
  Check,
  Calendar,
  Sparkles,
  Users,
  Flame,
  ArrowUpDown,
  X,
  FileCode,
  Database,
  Clock,
} from 'lucide-react'
import { api } from '../services/api'
import type { InnerSourceLeaderboardResponse, InnerSourcePerson, InnerSourceStory } from '../types/api'

interface InnerSourceLeaderboardPageProps {
  organization: string
  project: string
  pat: string
  projects: { id: string; name: string }[]
  onOrganizationChange: (org: string) => void
  onProjectChange: (proj: string) => void
  onPatChange?: (pat: string) => void
  theme?: 'dark' | 'light'
}

const AVAILABLE_YEARS = [2026, 2025, 2024, 2023]
const QUARTERS = [
  { id: 1, label: 'Quarter 1', sub: 'Jan – Mar' },
  { id: 2, label: 'Quarter 2', sub: 'Apr – Jun' },
  { id: 3, label: 'Quarter 3', sub: 'Jul – Sep' },
  { id: 4, label: 'Quarter 4', sub: 'Oct – Dec' },
]

export const InnerSourceLeaderboardPage: React.FC<InnerSourceLeaderboardPageProps> = ({
  organization,
  project,
  pat,
  projects,
  onOrganizationChange,
  onProjectChange,
  onPatChange,
}) => {
  const [year, setYear] = useState<number>(2026)
  const [quarter, setQuarter] = useState<number>(2)
  const [tag, setTag] = useState<string>('')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [sortField, setSortField] = useState<'quarter_points' | 'year_total' | 'name'>('quarter_points')
  const [sortAsc, setSortAsc] = useState<boolean>(false)

  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<InnerSourceLeaderboardResponse | null>(null)
  const [selectedPerson, setSelectedPerson] = useState<InnerSourcePerson | null>(null)
  const [copied, setCopied] = useState<boolean>(false)

  const fetchLeaderboard = (forceRefresh = false) => {
    if (!organization || !project) return
    setIsLoading(true)
    setError(null)

    api.innersourceLeaderboard(organization, project, year, quarter, tag.trim() || undefined, pat || undefined, forceRefresh)
      .then((res) => {
        setData(res)
        setIsLoading(false)
      })
      .catch((err) => {
        setIsLoading(false)
        setError(err instanceof Error ? err.message : 'Failed to fetch InnerSource leaderboard')
      })
  }

  useEffect(() => {
    fetchLeaderboard(false)
  }, [organization, project, pat, year, quarter, tag])

  // Filter and sort contributors
  const filteredLeaderboard = useMemo(() => {
    if (!data?.leaderboard) return []
    let list = [...data.leaderboard]

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim()
      list = list.filter((p) => p.name.toLowerCase().includes(q))
    }

    list.sort((a, b) => {
      let comparison = 0
      if (sortField === 'name') {
        comparison = a.name.localeCompare(b.name)
      } else if (sortField === 'quarter_points') {
        comparison = a.quarter_points - b.quarter_points
      } else if (sortField === 'year_total') {
        comparison = a.year_total - b.year_total
      }
      return sortAsc ? comparison : -comparison
    })

    return list
  }, [data, searchQuery, sortField, sortAsc])

  const handleSort = (field: 'quarter_points' | 'year_total' | 'name') => {
    if (sortField === field) {
      setSortAsc(!sortAsc)
    } else {
      setSortField(field)
      setSortAsc(false)
    }
  }

  const copyMarkdownTable = () => {
    if (!data || !filteredLeaderboard.length) return
    const qLabel = `Quarter ${quarter}`
    const yLabel = `${year} Total`
    let md = `| Rank | Name | ${qLabel} | ${yLabel} |\n`
    md += `| :--- | :--- | :---: | :---: |\n`

    filteredLeaderboard.forEach((p, idx) => {
      md += `| ${idx + 1} | ${p.name} | ${p.quarter_points} | ${p.year_total} |\n`
    })

    navigator.clipboard.writeText(md).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    })
  }

  const getRankBadge = (rankIndex: number) => {
    if (rankIndex === 0) return <span className="islRankMedal islGold" title="1st Place"><Medal size={16} /></span>
    if (rankIndex === 1) return <span className="islRankMedal islSilver" title="2nd Place"><Medal size={16} /></span>
    if (rankIndex === 2) return <span className="islRankMedal islBronze" title="3rd Place"><Medal size={16} /></span>
    return <span className="islRankNumber">#{rankIndex + 1}</span>
  }

  return (
    <div className="islPageContainer">
      {/* Top Filter and Discovery Toolbar */}
      <div className="islToolbar">
        <div className="islToolbarLeft">
          <div className="islToolbarItem">
            <span className="islToolbarLabel">Org:</span>
            <input
              type="text"
              className="islInput"
              placeholder="Organization"
              value={organization}
              onChange={(e) => onOrganizationChange(e.target.value)}
            />
          </div>

          <div className="islToolbarItem">
            <span className="islToolbarLabel">Project:</span>
            <select
              className="islSelect"
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
          </div>

          <div className="islToolbarItem">
            <span className="islToolbarLabel">PAT:</span>
            <input
              type="password"
              className="islInput islPatInput"
              placeholder={pat ? '••••••••••••••••' : 'PAT Token'}
              value={pat}
              onChange={(e) => onPatChange?.(e.target.value)}
              autoComplete="off"
            />
          </div>
        </div>

        <div className="islToolbarRight">
          {/* Year selector */}
          <div className="islYearGroup">
            <Calendar size={14} className="islYearIcon" />
            <select
              className="islYearSelect"
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
            >
              {AVAILABLE_YEARS.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            className="islRefreshBtn"
            onClick={() => fetchLeaderboard(true)}
            disabled={isLoading}
            title="Sync latest work items from Azure DevOps and update Azure Blob Storage cache"
          >
            <RefreshCw size={14} className={isLoading ? 'spin' : ''} />
            <span>{isLoading ? 'Syncing...' : 'Sync ADO'}</span>
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      {!organization || !project ? (
        <div className="islPlaceholder">
          <div className="islPlaceholderIcon">
            <Trophy size={42} />
          </div>
          <h3>Select Organization & Project</h3>
          <p>
            Choose an Azure DevOps organization and project from the top toolbar to view InnerSource story points leaderboard.
          </p>
        </div>
      ) : (
        <>
          {/* Quarter Pills Selector */}
          <div className="islQuarterBar">
            <div className="islQuarterTitleWrap">
              <Trophy size={18} className="islTrophyIcon" />
              <h2>InnerSource Leaderboard</h2>
              <span className="islQuarterSubBadge">Year {year}</span>
            </div>

            <div className="islQuarterPills">
              {QUARTERS.map((q) => (
                <button
                  key={q.id}
                  type="button"
                  className={`islQuarterPill ${quarter === q.id ? 'active' : ''}`}
                  onClick={() => setQuarter(q.id)}
                >
                  <span className="islPillLabel">{q.label}</span>
                  <span className="islPillSub">{q.sub}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Azure Blob Storage Cache Status Bar */}
          <div className="islStorageStatusBar">
            <div className="islStorageStatusLeft">
              <span className="islStoragePill">
                <Database size={13} />
                <span>Blob Storage: <b>{data?.storage_blob_name || 'adopipelinefunc5693/innersource-data'}</b></span>
              </span>
              {data?.last_synced_at && (
                <span className="islSyncTimePill">
                  <Clock size={12} />
                  <span>Synced {new Date(data.last_synced_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} ({data.total_cached_items ?? data.stories_evaluated} items cached)</span>
                </span>
              )}
            </div>

            <div className="islStorageStatusRight">
              <button
                type="button"
                className="islSyncBtn"
                onClick={() => fetchLeaderboard(true)}
                disabled={isLoading}
                title="Fetch latest updates from Azure DevOps and update Blob Storage"
              >
                <RefreshCw size={12} className={isLoading ? 'spin' : ''} />
                <span>{isLoading ? 'Syncing with ADO...' : 'Incremental Sync'}</span>
              </button>
            </div>
          </div>

          {/* Stats Summary Cards */}
          <div className="islStatsGrid">
            <div className="islStatCard islCardGold">
              <div className="islStatIcon islIconGold">
                <CrownIcon size={20} />
              </div>
              <div className="islStatContent">
                <span className="islStatLabel">LEADER (Q{quarter})</span>
                <div className="islStatValue">
                  {data?.leader ? data.leader.name : '—'}
                </div>
                <span className="islStatSub">
                  {data?.leader ? `${data.leader.quarter_points} pts in Q${quarter}` : 'No points yet'}
                </span>
              </div>
            </div>

            <div className="islStatCard islCardCyan">
              <div className="islStatIcon islIconCyan">
                <Flame size={20} />
              </div>
              <div className="islStatContent">
                <span className="islStatLabel">TEAM Q{quarter} TOTAL</span>
                <div className="islStatValue">
                  {data?.total_quarter_points ?? 0}
                </div>
                <span className="islStatSub">Sum of all contributors in Q{quarter}</span>
              </div>
            </div>

            <div className="islStatCard islCardPurple">
              <div className="islStatIcon islIconPurple">
                <Award size={20} />
              </div>
              <div className="islStatContent">
                <span className="islStatLabel">TEAM {year} TOTAL</span>
                <div className="islStatValue">
                  {data?.total_year_points ?? 0}
                </div>
                <span className="islStatSub">Sum of all contributors across {year}</span>
              </div>
            </div>

            <div className="islStatCard islCardGreen">
              <div className="islStatIcon islIconGreen">
                <Users size={20} />
              </div>
              <div className="islStatContent">
                <span className="islStatLabel">CONTRIBUTORS</span>
                <div className="islStatValue">
                  {data?.total_contributors ?? 0}
                </div>
                <span className="islStatSub">Active team members</span>
              </div>
            </div>
          </div>

          {/* Action and Search Filter Bar */}
          <div className="islActionBar">
            <div className="islSearchBox">
              <Search size={15} className="islSearchIcon" />
              <input
                type="text"
                placeholder="Search contributor name..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button
                  type="button"
                  className="islClearSearch"
                  onClick={() => setSearchQuery('')}
                >
                  ✕
                </button>
              )}
            </div>

            <div className="islActionButtons">
              <button
                type="button"
                className="islCopyBtn"
                onClick={copyMarkdownTable}
                title="Copy Markdown leaderboard to clipboard for Teams, Slack, or Wiki"
              >
                {copied ? <Check size={14} className="islCheckIcon" /> : <Copy size={14} />}
                <span>{copied ? 'Copied Markdown!' : 'Copy Table'}</span>
              </button>
            </div>
          </div>

          {/* Error Banner */}
          {error && (
            <div className="islAlert islAlertError">
              <AlertTriangle size={16} />
              <div>
                <strong>Error fetching leaderboard:</strong> {error}
              </div>
            </div>
          )}

          {/* Loading or Table State */}
          {isLoading ? (
            <div className="islLoadingState">
              <RefreshCw size={26} className="spin islSpinner" />
              <p>Calculating story points and contributor totals for Q{quarter} {year}...</p>
            </div>
          ) : filteredLeaderboard.length === 0 ? (
            <div className="islPlaceholder">
              <div className="islPlaceholderIcon">
                <Award size={36} />
              </div>
              <h3>No Contributions Found</h3>
              <p>
                {searchQuery
                  ? `No contributors match "${searchQuery}".`
                  : `No completed work items with story points found for Quarter ${quarter} ${year}.`}
              </p>
            </div>
          ) : (
            <div className="islTableContainer">
              <table className="islTable">
                <thead>
                  <tr>
                    <th className="islThRank">Rank</th>
                    <th
                      className="islThName islSortable"
                      onClick={() => handleSort('name')}
                    >
                      <div className="islThInner">
                        <span>Name</span>
                        <ArrowUpDown size={12} className="islSortIcon" />
                      </div>
                    </th>
                    <th
                      className="islThQuarter islSortable"
                      onClick={() => handleSort('quarter_points')}
                    >
                      <div className="islThInner islThCenter">
                        <span>Quarter {quarter}</span>
                        <ArrowUpDown size={12} className="islSortIcon" />
                      </div>
                    </th>
                    <th
                      className="islThTotal islSortable"
                      onClick={() => handleSort('year_total')}
                    >
                      <div className="islThInner islThCenter">
                        <span>{year} Total</span>
                        <ArrowUpDown size={12} className="islSortIcon" />
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLeaderboard.map((person, index) => {
                    const isTopThree = index < 3
                    return (
                      <tr
                        key={person.name}
                        className={`islTableRow ${isTopThree ? `islRowTop islRow${index + 1}` : ''}`}
                        onClick={() => setSelectedPerson(person)}
                        title="Click to view story details"
                      >
                        <td className="islTdRank">
                          {getRankBadge(index)}
                        </td>
                        <td className="islTdName">
                          <div className="islPersonCell">
                            <div className="islAvatar">
                              {person.name.charAt(0).toUpperCase()}
                            </div>
                            <div className="islPersonInfo">
                              <span className="islPersonName">{person.name}</span>
                              {person.stories_count > 0 && (
                                <span className="islStoriesCount">
                                  {person.quarter_stories_count} stories in Q{quarter} · {person.stories_count} total
                                </span>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="islTdQuarter">
                          <span className={`islPointsBadge ${person.quarter_points > 0 ? 'islHasPoints' : 'islZeroPoints'}`}>
                            {person.quarter_points}
                          </span>
                        </td>
                        <td className="islTdTotal">
                          <span className="islTotalPoints">
                            {person.year_total}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* Stories Breakdown Drawer */}
      {selectedPerson && (
        <div className="islDrawerBackdrop" onClick={() => setSelectedPerson(null)}>
          <aside className="islDrawer" onClick={(e) => e.stopPropagation()}>
            <div className="islDrawerHead">
              <div className="islDrawerUser">
                <div className="islDrawerAvatar">
                  {selectedPerson.name.charAt(0).toUpperCase()}
                </div>
                <div>
                  <h3>{selectedPerson.name}</h3>
                  <div className="islDrawerUserMeta">
                    <span>Q{quarter} Points: <b>{selectedPerson.quarter_points}</b></span>
                    <span>•</span>
                    <span>{year} Total: <b>{selectedPerson.year_total}</b></span>
                  </div>
                </div>
              </div>
              <button
                type="button"
                className="islDrawerClose"
                onClick={() => setSelectedPerson(null)}
              >
                <X size={18} />
              </button>
            </div>

            <div className="islDrawerBody">
              <div className="islDrawerSectionTitle">
                <FileCode size={14} />
                <span>Completed Stories Breakdown ({selectedPerson.stories.length})</span>
              </div>

              {selectedPerson.stories.length === 0 ? (
                <div className="islEmptyStories">
                  No individual story details recorded for this contributor.
                </div>
              ) : (
                <div className="islStoriesList">
                  {selectedPerson.stories.map((story) => (
                    <div key={story.id} className="islStoryCard">
                      <div className="islStoryHeader">
                        <div className="islStoryLeft">
                          <span className="islStoryId">#{story.id}</span>
                          <span className="islStoryType">{story.type}</span>
                          {story.quarter === quarter && (
                            <span className="islStoryQBadge">Q{quarter}</span>
                          )}
                        </div>
                        <div className="islStoryPoints">
                          {story.points} pts
                        </div>
                      </div>

                      <div className="islStoryTitle">{story.title}</div>

                      <div className="islStoryFooter">
                        <span className="islStoryDate">Closed {story.closed_date}</span>
                        {story.iteration_path && (
                          <span className="islStoryIteration" title={`Iteration: ${story.iteration_path}`}>
                            {story.iteration_path.split('\\').pop() || story.iteration_path}
                          </span>
                        )}
                        {story.url && (
                          <a
                            href={story.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="islStoryLink"
                          >
                            <span>Open in ADO</span>
                            <ExternalLink size={11} />
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}

function CrownIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 5.5a.5.5 0 0 1 .798.519l-2.834 10.269a4 4 0 0 1-3.86 2.934H8.713a4 4 0 0 1-3.86-2.934L2.019 6.019a.5.5 0 0 1 .798-.519l4.277 3.664a1 1 0 0 0 1.516-.294z"/>
      <path d="M5 21h14"/>
    </svg>
  )
}
