import React, { createContext, useContext, useState, useEffect } from 'react'

export interface PluginItem {
  id: string
  name: string
  category: 'Hygiene & Quality' | 'Delivery & Milestones' | 'AI Insights'
  description: string
  iconName: 'Clock' | 'ShieldAlert' | 'Trophy' | 'Sparkles' | 'Mail' | 'GitPullRequest'
  targetArea: string
  defaultEnabled: boolean
}

export const AVAILABLE_PLUGINS: PluginItem[] = [
  {
    id: 'closed_tasks_without_hours',
    name: 'Task Hours Hygiene Audit',
    category: 'Hygiene & Quality',
    description: 'Audits completed tasks and flags work closed with blank or zero hours to ensure billing and effort integrity.',
    iconName: 'ShieldAlert',
    targetArea: 'Sprint Board',
    defaultEnabled: true,
  },
  {
    id: 'stale_in_review',
    name: 'Review SLA Watchdog',
    category: 'Hygiene & Quality',
    description: 'Calculates business days elapsed and highlights user stories or bugs lingering in review for more than 4 business days.',
    iconName: 'Clock',
    targetArea: 'Sprint Board',
    defaultEnabled: true,
  },
  {
    id: 'milestone_baseline',
    name: 'Milestone & Next-Sprint Baseline',
    category: 'Delivery & Milestones',
    description: 'Groups closed stories into dynamic capability streams, plots delivery velocity, and establishes quantitative next-sprint baselines.',
    iconName: 'Trophy',
    targetArea: 'Sprint Board',
    defaultEnabled: true,
  },
  {
    id: 'ai_executive_briefing',
    name: 'Executive AI Briefing',
    category: 'AI Insights',
    description: 'Synthesizes problem descriptions and conditions of satisfaction from backlog items into executive summary briefings.',
    iconName: 'Sparkles',
    targetArea: 'Sprint Board (Milestone)',
    defaultEnabled: true,
  },
  {
    id: 'email_sprint_report',
    name: 'Sprint Health Email Dispatcher',
    category: 'Delivery & Milestones',
    description: 'Enables one-click email report generation and dispatch to stakeholders with sprint health, hygiene violations, and milestones.',
    iconName: 'Mail',
    targetArea: 'Sprint Board',
    defaultEnabled: true,
  },
  {
    id: 'ai_pr_reviewer',
    name: 'AI Pull Request Reviewer',
    category: 'AI Insights',
    description: 'Automates PR code reviews, analyzes diffs, and generates quality scorecards with line-by-line feedback.',
    iconName: 'GitPullRequest',
    targetArea: 'Pull Requests',
    defaultEnabled: true,
  },
]

export type PluginStateMap = Record<string, boolean>

const STORAGE_KEY = 'ado_insight_plugins_state_v1'

interface PluginContextType {
  plugins: PluginStateMap
  isPluginActive: (id: string) => boolean
  togglePlugin: (id: string) => void
  setPluginState: (id: string, enabled: boolean) => void
  enableAllPlugins: () => void
  disableAllPlugins: () => void
  activeCount: number
  totalCount: number
  isPluginModalOpen: boolean
  setIsPluginModalOpen: (open: boolean) => void
}

const PluginContext = createContext<PluginContextType | undefined>(undefined)

export const PluginProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [plugins, setPlugins] = useState<PluginStateMap>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        const initial: PluginStateMap = {}
        AVAILABLE_PLUGINS.forEach((p) => {
          initial[p.id] = parsed[p.id] !== undefined ? parsed[p.id] : p.defaultEnabled
        })
        return initial
      }
    } catch (e) {
      console.warn('Could not read plugins state from localStorage:', e)
    }

    const defaults: PluginStateMap = {}
    AVAILABLE_PLUGINS.forEach((p) => {
      defaults[p.id] = p.defaultEnabled
    })
    return defaults
  })

  const [isPluginModalOpen, setIsPluginModalOpen] = useState(false)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(plugins))
    } catch (e) {
      console.warn('Could not persist plugins state:', e)
    }
  }, [plugins])

  const isPluginActive = (id: string): boolean => {
    return Boolean(plugins[id])
  }

  const togglePlugin = (id: string) => {
    setPlugins((prev) => ({
      ...prev,
      [id]: !prev[id],
    }))
  }

  const setPluginState = (id: string, enabled: boolean) => {
    setPlugins((prev) => ({
      ...prev,
      [id]: enabled,
    }))
  }

  const enableAllPlugins = () => {
    const allOn: PluginStateMap = {}
    AVAILABLE_PLUGINS.forEach((p) => {
      allOn[p.id] = true
    })
    setPlugins(allOn)
  }

  const disableAllPlugins = () => {
    const allOff: PluginStateMap = {}
    AVAILABLE_PLUGINS.forEach((p) => {
      allOff[p.id] = false
    })
    setPlugins(allOff)
  }

  const activeCount = Object.values(plugins).filter(Boolean).length
  const totalCount = AVAILABLE_PLUGINS.length

  return (
    <PluginContext.Provider
      value={{
        plugins,
        isPluginActive,
        togglePlugin,
        setPluginState,
        enableAllPlugins,
        disableAllPlugins,
        activeCount,
        totalCount,
        isPluginModalOpen,
        setIsPluginModalOpen,
      }}
    >
      {children}
    </PluginContext.Provider>
  )
}

export const usePlugins = (): PluginContextType => {
  const ctx = useContext(PluginContext)
  if (!ctx) {
    throw new Error('usePlugins must be used within a PluginProvider')
  }
  return ctx
}
