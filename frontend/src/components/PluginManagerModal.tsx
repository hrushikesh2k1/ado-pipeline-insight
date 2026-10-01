import React from 'react'
import {
  Puzzle,
  X,
  ShieldAlert,
  Clock,
  Trophy,
  Sparkles,
  Mail,
  GitPullRequest,
  CheckCircle2,
  PowerOff,
  Layers,
  Sparkle
} from 'lucide-react'
import { usePlugins, AVAILABLE_PLUGINS, PluginItem } from '../context/PluginContext'

export const PluginManagerModal: React.FC = () => {
  const {
    isPluginModalOpen,
    setIsPluginModalOpen,
    isPluginActive,
    togglePlugin,
    enableAllPlugins,
    disableAllPlugins,
    activeCount,
    totalCount,
  } = usePlugins()

  if (!isPluginModalOpen) return null

  const renderIcon = (name: PluginItem['iconName']) => {
    switch (name) {
      case 'ShieldAlert':
        return <ShieldAlert size={18} color="#ef4444" />
      case 'Clock':
        return <Clock size={18} color="#f59e0b" />
      case 'Trophy':
        return <Trophy size={18} color="#10b981" />
      case 'Sparkles':
        return <Sparkles size={18} color="#8b5cf6" />
      case 'Mail':
        return <Mail size={18} color="#06b6d4" />
      case 'GitPullRequest':
        return <GitPullRequest size={18} color="#ec4899" />
      default:
        return <Puzzle size={18} color="#00fbfb" />
    }
  }

  return (
    <div className="pluginModalBackdrop" onClick={() => setIsPluginModalOpen(false)}>
      <div
        className="pluginModalContainer"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="pluginModalTitle"
      >
        {/* Header */}
        <div className="pluginModalHeader">
          <div className="pluginModalHeaderLeft">
            <div className="pluginModalIconBadge">
              <Puzzle size={22} color="#00fbfb" />
            </div>
            <div>
              <h2 id="pluginModalTitle" className="pluginModalTitle">
                ADO Insights Plugin Marketplace
              </h2>
              <p className="pluginModalSubtitle">
                Attach or detach custom intelligence plugins on top of native Azure DevOps.
              </p>
            </div>
          </div>
          <button
            type="button"
            className="pluginModalCloseBtn"
            onClick={() => setIsPluginModalOpen(false)}
            title="Close"
          >
            <X size={18} />
          </button>
        </div>

        {/* Global Preset Bar */}
        <div className="pluginPresetBar">
          <div className="pluginStatusSummary">
            <span className="pluginStatusDot" />
            <span className="pluginStatusText">
              <b>{activeCount}</b> of <b>{totalCount}</b> plugins currently attached
            </span>
            {activeCount === 0 ? (
              <span className="pluginModeBadge vanilla">Clean Azure DevOps Mode</span>
            ) : activeCount === totalCount ? (
              <span className="pluginModeBadge supercharged">Full Insight Suite Active</span>
            ) : (
              <span className="pluginModeBadge custom">Custom Configuration</span>
            )}
          </div>

          <div className="pluginPresetButtons">
            <button
              type="button"
              className="pluginPresetBtn vanillaBtn"
              onClick={disableAllPlugins}
              title="Detach all custom plugins to get a pure, 100% vanilla Azure DevOps view"
            >
              <PowerOff size={13} />
              <span>Clean Azure DevOps (All Detached)</span>
            </button>
            <button
              type="button"
              className="pluginPresetBtn superchargeBtn"
              onClick={enableAllPlugins}
              title="Attach all plugins for the full intelligence suite"
            >
              <Sparkle size={13} />
              <span>Attach All (Supercharged)</span>
            </button>
          </div>
        </div>

        {/* Plugin Cards List */}
        <div className="pluginList">
          {AVAILABLE_PLUGINS.map((plugin) => {
            const active = isPluginActive(plugin.id)
            return (
              <div
                key={plugin.id}
                className={`pluginCard ${active ? 'active' : 'inactive'}`}
              >
                <div className="pluginCardIconCol">
                  <div className={`pluginIconWrap ${active ? 'active' : ''}`}>
                    {renderIcon(plugin.iconName)}
                  </div>
                </div>

                <div className="pluginCardBody">
                  <div className="pluginCardTitleRow">
                    <span className="pluginName">{plugin.name}</span>
                    <span className="pluginCategoryBadge">{plugin.category}</span>
                    <span className="pluginTargetBadge">
                      <Layers size={11} style={{ marginRight: '3px' }} />
                      {plugin.targetArea}
                    </span>
                  </div>
                  <p className="pluginDescription">{plugin.description}</p>
                </div>

                {/* Toggle Action */}
                <div className="pluginCardAction">
                  <label className="pluginToggleSwitch">
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={() => togglePlugin(plugin.id)}
                      aria-label={`Toggle ${plugin.name}`}
                    />
                    <span className="pluginSlider" />
                  </label>
                  <span className={`pluginToggleStateText ${active ? 'attached' : 'detached'}`}>
                    {active ? 'Attached' : 'Detached'}
                  </span>
                </div>
              </div>
            )
          })}
        </div>

        {/* Footer */}
        <div className="pluginModalFooter">
          <div className="pluginFooterInfo">
            <CheckCircle2 size={14} color="#10b981" />
            <span>Changes apply immediately and persist in your browser session.</span>
          </div>
          <button
            type="button"
            className="pluginModalDoneBtn"
            onClick={() => setIsPluginModalOpen(false)}
          >
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
