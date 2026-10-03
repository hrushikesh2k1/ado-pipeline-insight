import React from 'react'
import { Activity, GitPullRequest, FolderKanban, Puzzle, Rocket, ShieldAlert } from 'lucide-react'
import { usePlugins } from '../context/PluginContext'

export type NavPage = 'pipelines' | 'pull-requests' | 'sprints' | 'releases' | 'irp'

interface NavSidebarProps {
  activePage: NavPage
  onSelectPage: (page: NavPage) => void
}

export const NavSidebar: React.FC<NavSidebarProps> = ({ activePage, onSelectPage }) => {
  const { setIsPluginModalOpen, activeCount, totalCount } = usePlugins()

  return (
    <aside className="navSidebar" aria-label="Main Navigation">
      <div className="navSidebarTop">
        <button
          type="button"
          className={`navSidebarBtn ${activePage === 'pipelines' ? 'active' : ''}`}
          onClick={() => onSelectPage('pipelines')}
          aria-label="Pipeline Insights"
        >
          <div className="navSidebarActiveIndicator" />
          <div className="navIconWrapper">
            <Activity size={20} strokeWidth={2.2} />
          </div>
          <span className="navTooltip">Pipeline Insights</span>
        </button>

        <button
          type="button"
          className={`navSidebarBtn ${activePage === 'pull-requests' ? 'active' : ''}`}
          onClick={() => onSelectPage('pull-requests')}
          aria-label="Pull Requests"
        >
          <div className="navSidebarActiveIndicator" />
          <div className="navIconWrapper">
            <GitPullRequest size={20} strokeWidth={2.2} />
          </div>
          <span className="navTooltip">Pull Requests</span>
        </button>

        <button
          type="button"
          className={`navSidebarBtn ${activePage === 'sprints' ? 'active' : ''}`}
          onClick={() => onSelectPage('sprints')}
          aria-label="Azure Boards Sprints"
        >
          <div className="navSidebarActiveIndicator" />
          <div className="navIconWrapper">
            <FolderKanban size={20} strokeWidth={2.2} />
          </div>
          <span className="navTooltip">Sprint Boards</span>
        </button>

        <button
          type="button"
          className={`navSidebarBtn ${activePage === 'releases' ? 'active' : ''}`}
          onClick={() => onSelectPage('releases')}
          aria-label="Release Readiness Scorecard"
        >
          <div className="navSidebarActiveIndicator" />
          <div className="navIconWrapper">
            <Rocket size={20} strokeWidth={2.2} />
          </div>
          <span className="navTooltip">Release Readiness</span>
        </button>

        <button
          type="button"
          className={`navSidebarBtn ${activePage === 'irp' ? 'active' : ''}`}
          onClick={() => onSelectPage('irp')}
          aria-label="Incident Response Plan (IRP) Studio"
        >
          <div className="navSidebarActiveIndicator" />
          <div className="navIconWrapper">
            <ShieldAlert size={20} strokeWidth={2.2} />
          </div>
          <span className="navTooltip">IRP Studio</span>
        </button>
      </div>

      {/* Bottom section with Plugin Marketplace button */}
      <div className="navSidebarBottom">
        <button
          type="button"
          data-testid="plugin-nav-btn"
          className={`navSidebarBtn pluginNavBtn ${activeCount > 0 ? 'hasActive' : 'allDetached'}`}
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            setIsPluginModalOpen(true)
          }}
          aria-label="ADO Insight Plugins & Extensions"
          title="Plugins & Extensions"
        >
          <div className="navIconWrapper">
            <Puzzle size={20} strokeWidth={2.2} />
          </div>
          {activeCount > 0 && (
            <span className="navPluginBadge" title={`${activeCount} active plugins`}>
              {activeCount}
            </span>
          )}
          <span className="navTooltip">
            Plugins & Extensions ({activeCount}/{totalCount} Active)
          </span>
        </button>
      </div>
    </aside>
  )
}
