import React, { useState, useEffect } from 'react'
import {
  ShieldAlert,
  Sparkles,
  BookOpen,
  FileText,
  Copy,
  Check,
  UploadCloud,
  RefreshCw,
  Search,
  ChevronRight,
  ExternalLink,
  Layers,
  Flame,
  CheckCircle2,
  AlertTriangle,
  Server,
  Zap,
} from 'lucide-react'
import { api } from '../services/api'
import type { AdoProject, AdoWiki, AdoWikiPage } from '../types/api'

interface IncidentResponsePageProps {
  organization: string
  project: string
  pat: string
  projects?: AdoProject[]
  onOrganizationChange?: (org: string) => void
  onProjectChange?: (proj: string) => void
  onPatChange?: (pat: string) => void
  theme?: 'dark' | 'light'
}

type TabMode = 'generator' | 'explorer'

const ALERT_PRESETS = [
  {
    name: 'VPN Tunnel Disconnected',
    resource: 'Azure Virtual Network Gateway (Site-to-Site)',
    severity: 'Sev-1',
    trigger: 'Gateway Connection Status == 0 for > 5 minutes',
    team: 'Cloud Network Engineering',
    notes: 'IPsec Phase 2 or BGP peering disconnection between corporate on-premises and Azure hub.',
  },
  {
    name: 'High CPU on App Service Plan',
    resource: 'Azure App Service Plan (P2v3)',
    severity: 'Sev-2',
    trigger: 'CPU Utilization >= 85% for 10 continuous minutes',
    team: 'Core Platform Engineering',
    notes: 'Risk of HTTP 503 Service Unavailable and thread starvation across web workers.',
  },
  {
    name: 'SQL Database Deadlock Spike',
    resource: 'Azure SQL Database (General Purpose)',
    severity: 'Sev-1',
    trigger: 'Deadlock count > 50 in 5 minutes & transaction rollback rate spike',
    team: 'Database Operations',
    notes: 'Lock escalation blocking critical customer checkout and order processing workflows.',
  },
  {
    name: 'Disk IOPS Throttled on VM',
    resource: 'Azure Managed Disk (Premium SSD P30)',
    severity: 'Sev-2',
    trigger: 'Disk Read/Write IOPS at 100% burst consumption limit',
    team: 'Infrastructure SRE',
    notes: 'Severe storage I/O latency impacting background worker queues.',
  },
]

export const IncidentResponsePage: React.FC<IncidentResponsePageProps> = ({
  organization,
  project,
  pat,
  projects = [],
  onOrganizationChange,
  onProjectChange,
  onPatChange,
}) => {
  // Navigation
  const [activeTab, setActiveTab] = useState<TabMode>('generator')

  // Discovery
  const [wikis, setWikis] = useState<AdoWiki[]>([])
  const [selectedWikiId, setSelectedWikiId] = useState<string>('')
  const [isLoadingWikis, setIsLoadingWikis] = useState<boolean>(false)

  // Wiki Pages Explorer
  const [wikiPages, setWikiPages] = useState<AdoWikiPage[]>([])
  const [isLoadingPages, setIsLoadingPages] = useState<boolean>(false)
  const [selectedPagePath, setSelectedPagePath] = useState<string>('')
  const [selectedPageContent, setSelectedPageContent] = useState<string>('')
  const [isLoadingContent, setIsLoadingContent] = useState<boolean>(false)
  const [pageSearchFilter, setPageSearchFilter] = useState<string>('')

  // IRP Generator Form State
  const [alertName, setAlertName] = useState<string>('VPN Tunnel Disconnected')
  const [targetResource, setTargetResource] = useState<string>('Azure Virtual Network Gateway (Site-to-Site)')
  const [severity, setSeverity] = useState<string>('Sev-1')
  const [triggerCondition, setTriggerCondition] = useState<string>('Connection Status == 0 for > 5 minutes')
  const [owningTeam, setOwningTeam] = useState<string>('Cloud Network Engineering')
  const [environment, setEnvironment] = useState<string>('Production')
  const [additionalNotes, setAdditionalNotes] = useState<string>(
    'IPsec Phase 2 or BGP peering disconnection between corporate on-premises and Azure hub.'
  )

  // Generated Output State
  const [generatedMarkdown, setGeneratedMarkdown] = useState<string>('')
  const [suggestedWikiPath, setSuggestedWikiPath] = useState<string>('/Incident-Response-Plans/VPN-Tunnel-Disconnected')
  const [isGenerating, setIsGenerating] = useState<boolean>(false)
  const [irpEditorMode, setIrpEditorMode] = useState<'preview' | 'raw'>('preview')
  const [copiedMarkdown, setCopiedMarkdown] = useState<boolean>(false)

  // Publishing State
  const [isPublishing, setIsPublishing] = useState<boolean>(false)
  const [updateInventoryCheck, setUpdateInventoryCheck] = useState<boolean>(true)
  const [inventoryPagePath, setInventoryPagePath] = useState<string>('/Alert-Inventory')
  const [publishSuccessMsg, setPublishSuccessMsg] = useState<string | null>(null)
  const [publishErrorMsg, setPublishErrorMsg] = useState<string | null>(null)

  // Load Wikis when Project changes
  useEffect(() => {
    if (!organization || !project) return
    let isCurrent = true
    setIsLoadingWikis(true)
    api
      .listWikis(organization, project, pat)
      .then((data) => {
        if (!isCurrent) return
        setWikis(data)
        if (data.length > 0 && !selectedWikiId) {
          setSelectedWikiId(data[0].id)
        }
      })
      .catch(() => {
        if (isCurrent) setWikis([])
      })
      .finally(() => {
        if (isCurrent) setIsLoadingWikis(false)
      })
    return () => {
      isCurrent = false
    }
  }, [organization, project, pat])

  // Load Wiki Pages when selected Wiki changes
  useEffect(() => {
    if (!organization || !project || !selectedWikiId || activeTab !== 'explorer') return
    let isCurrent = true
    setIsLoadingPages(true)
    api
      .getWikiPages(organization, project, selectedWikiId, '/', pat)
      .then((pages) => {
        if (!isCurrent) return
        setWikiPages(pages)
        if (pages.length > 0 && !selectedPagePath) {
          const first = pages[0].path || '/'
          setSelectedPagePath(first)
        }
      })
      .catch(() => {
        if (isCurrent) setWikiPages([])
      })
      .finally(() => {
        if (isCurrent) setIsLoadingPages(false)
      })
    return () => {
      isCurrent = false
    }
  }, [organization, project, selectedWikiId, activeTab, pat])

  // Load Selected Page Content
  useEffect(() => {
    if (!organization || !project || !selectedWikiId || !selectedPagePath || activeTab !== 'explorer') return
    let isCurrent = true
    setIsLoadingContent(true)
    api
      .getWikiPageContent(organization, project, selectedWikiId, selectedPagePath, pat)
      .then((page) => {
        if (!isCurrent) return
        setSelectedPageContent(page.content || '# No content in this page.')
      })
      .catch(() => {
        if (isCurrent) setSelectedPageContent('# Failed to load page content.')
      })
      .finally(() => {
        if (isCurrent) setIsLoadingContent(false)
      })
    return () => {
      isCurrent = false
    }
  }, [organization, project, selectedWikiId, selectedPagePath, activeTab, pat])

  const handleApplyPreset = (preset: typeof ALERT_PRESETS[0]) => {
    setAlertName(preset.name)
    setTargetResource(preset.resource)
    setSeverity(preset.severity)
    setTriggerCondition(preset.trigger)
    setOwningTeam(preset.team)
    setAdditionalNotes(preset.notes)
    setPublishSuccessMsg(null)
    setPublishErrorMsg(null)
  }

  const handleGenerate = async () => {
    if (!alertName.trim() || !targetResource.trim()) return
    setIsGenerating(true)
    setPublishSuccessMsg(null)
    setPublishErrorMsg(null)
    try {
      const res = await api.generateIrp({
        alert_name: alertName,
        target_resource: targetResource,
        severity,
        trigger_condition: triggerCondition,
        owning_team: owningTeam,
        environment,
        additional_notes: additionalNotes,
      })
      setGeneratedMarkdown(res.markdown_content)
      setSuggestedWikiPath(res.suggested_wiki_path)
    } catch (err: any) {
      setPublishErrorMsg(err.message || 'Failed to generate IRP.')
    } finally {
      setIsGenerating(false)
    }
  }

  const handleCopy = () => {
    if (!generatedMarkdown) return
    navigator.clipboard.writeText(generatedMarkdown)
    setCopiedMarkdown(true)
    setTimeout(() => setCopiedMarkdown(false), 2000)
  }

  const handlePublish = async () => {
    if (!organization || !project || !selectedWikiId || !generatedMarkdown.trim()) {
      setPublishErrorMsg('Please select a Wiki and ensure the IRP is generated before publishing.')
      return
    }
    setIsPublishing(true)
    setPublishSuccessMsg(null)
    setPublishErrorMsg(null)
    try {
      const res = await api.publishIrp(
        {
          organization,
          project,
          wiki_id: selectedWikiId,
          path: suggestedWikiPath,
          content: generatedMarkdown,
          comment: `Add AI-generated IRP for alert '${alertName}'`,
          update_inventory: updateInventoryCheck,
          inventory_page_path: inventoryPagePath,
          alert_name: alertName,
          severity,
          owning_team: owningTeam,
        },
        pat
      )
      setPublishSuccessMsg(
        `Successfully published to Wiki at '${res.page_path}'${
          res.inventory_updated ? ' and registered in Alert Inventory!' : '.'
        }`
      )
    } catch (err: any) {
      setPublishErrorMsg(err.message || 'Failed to publish to Wiki. Ensure PAT has Wiki (Write) permissions.')
    } finally {
      setIsPublishing(false)
    }
  }

  // Flatten recursive wiki pages for list view
  const flattenPages = (pages: AdoWikiPage[]): AdoWikiPage[] => {
    const list: AdoWikiPage[] = []
    const recurse = (items: AdoWikiPage[]) => {
      for (const it of items) {
        list.push(it)
        if (it.sub_pages && it.sub_pages.length > 0) {
          recurse(it.sub_pages)
        }
      }
    }
    recurse(pages)
    return list
  }

  const allPages = flattenPages(wikiPages)
  const filteredPages = allPages.filter((p) =>
    p.path.toLowerCase().includes(pageSearchFilter.toLowerCase())
  )

  return (
    <div className="irpPageContainer">
      {/* 0. Top Connection & Discovery Bar */}
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
              placeholder={pat ? '••••••••••••••••' : 'PAT (Wiki scope)'}
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
            </div>
          </div>

          <div className="adoConnectItem">
            <span className="adoConnectLabel">Target Wiki:</span>
            <div className="adoCustomSelectWrapper">
              <select
                className="adoCustomSelect"
                value={selectedWikiId}
                onChange={(e) => setSelectedWikiId(e.target.value)}
                disabled={wikis.length === 0}
              >
                {wikis.length === 0 ? (
                  <option value="">No Wikis Found</option>
                ) : (
                  wikis.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} ({w.type || 'ProjectWiki'})
                    </option>
                  ))
                )}
              </select>
            </div>
          </div>
        </div>

        <div className="adoConnectBarRight">
          <button
            type="button"
            className="adoConnectRefreshBtn"
            onClick={() => {
              if (organization && project) {
                setIsLoadingWikis(true)
                api.listWikis(organization, project, pat).then(setWikis).finally(() => setIsLoadingWikis(false))
              }
            }}
            title="Refresh Wikis from Azure DevOps"
          >
            <RefreshCw size={13} className={isLoadingWikis ? 'spin' : ''} />
            <span>Sync Wikis</span>
          </button>
        </div>
      </div>

      {/* 1. Header Banner */}
      <div className="irpHeaderBanner">
        <div className="irpHeaderLeft">
          <div className="irpHeaderIcon">
            <ShieldAlert size={24} color="#00fbfb" />
          </div>
          <div>
            <h2>Incident Response & Wiki Hub</h2>
            <p>Generate production-ready SRE runbooks from alert signals & publish directly to Azure DevOps Wiki.</p>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="irpTabSwitch">
          <button
            type="button"
            className={`irpTabBtn ${activeTab === 'generator' ? 'active' : ''}`}
            onClick={() => setActiveTab('generator')}
          >
            <Sparkles size={15} />
            <span>AI IRP Generator</span>
          </button>
          <button
            type="button"
            className={`irpTabBtn ${activeTab === 'explorer' ? 'active' : ''}`}
            onClick={() => setActiveTab('explorer')}
          >
            <BookOpen size={15} />
            <span>Wiki Runbook Explorer</span>
          </button>
        </div>
      </div>

      {/* 2. TAB 1: AI IRP GENERATOR */}
      {activeTab === 'generator' && (
        <div className="irpGeneratorGrid">
          {/* Left Panel: Input Parameters */}
          <div className="irpConfigCard">
            <div className="irpCardHead">
              <div className="irpCardHeadTitle">
                <Zap size={16} color="#00fbfb" />
                <h3>Alert Details & Context</h3>
              </div>
              <span className="irpBadgeAi">Azure OpenAI Grounded</span>
            </div>

            <div className="irpCardBody">
              {/* Quick Presets */}
              <div className="irpFormGroup">
                <label className="irpLabel">Quick Presets:</label>
                <div className="irpPresetsWrap">
                  {ALERT_PRESETS.map((p) => (
                    <button
                      key={p.name}
                      type="button"
                      className={`irpPresetPill ${alertName === p.name ? 'active' : ''}`}
                      onClick={() => handleApplyPreset(p)}
                    >
                      {p.name}
                    </button>
                  ))}
                </div>
              </div>

              <div className="irpFormGroup">
                <label className="irpLabel">Alert Name *</label>
                <input
                  type="text"
                  className="irpInput"
                  placeholder="e.g. VPN Tunnel Disconnected"
                  value={alertName}
                  onChange={(e) => setAlertName(e.target.value)}
                />
              </div>

              <div className="irpFormRow">
                <div className="irpFormGroup">
                  <label className="irpLabel">Target Resource / Service *</label>
                  <input
                    type="text"
                    className="irpInput"
                    placeholder="e.g. Azure Virtual Network Gateway"
                    value={targetResource}
                    onChange={(e) => setTargetResource(e.target.value)}
                  />
                </div>

                <div className="irpFormGroup">
                  <label className="irpLabel">Severity Level</label>
                  <select
                    className="irpSelect"
                    value={severity}
                    onChange={(e) => setSeverity(e.target.value)}
                  >
                    <option value="Sev-1">Sev-1 (Critical Outage)</option>
                    <option value="Sev-2">Sev-2 (High Degradation)</option>
                    <option value="Sev-3">Sev-3 (Medium / Warning)</option>
                  </select>
                </div>
              </div>

              <div className="irpFormRow">
                <div className="irpFormGroup">
                  <label className="irpLabel">Owning Engineering Team</label>
                  <input
                    type="text"
                    className="irpInput"
                    placeholder="e.g. Cloud Network Engineering"
                    value={owningTeam}
                    onChange={(e) => setOwningTeam(e.target.value)}
                  />
                </div>

                <div className="irpFormGroup">
                  <label className="irpLabel">Environment</label>
                  <select
                    className="irpSelect"
                    value={environment}
                    onChange={(e) => setEnvironment(e.target.value)}
                  >
                    <option value="Production">Production</option>
                    <option value="Staging">Staging</option>
                    <option value="Disaster Recovery">Disaster Recovery</option>
                  </select>
                </div>
              </div>

              <div className="irpFormGroup">
                <label className="irpLabel">Trigger Logic / Threshold</label>
                <input
                  type="text"
                  className="irpInput"
                  placeholder="e.g. Connection Status == 0 for > 5 minutes"
                  value={triggerCondition}
                  onChange={(e) => setTriggerCondition(e.target.value)}
                />
              </div>

              <div className="irpFormGroup">
                <label className="irpLabel">Additional Operational Notes / Symptoms</label>
                <textarea
                  className="irpTextarea"
                  rows={3}
                  placeholder="e.g. Dependencies, affected VPC peering, on-premise firewall gateway IPs..."
                  value={additionalNotes}
                  onChange={(e) => setAdditionalNotes(e.target.value)}
                />
              </div>

              <button
                type="button"
                className="irpPrimaryBtn"
                onClick={handleGenerate}
                disabled={isGenerating || !alertName.trim()}
              >
                {isGenerating ? (
                  <>
                    <RefreshCw size={15} className="spin" />
                    <span>Synthesizing IRP with OpenAI...</span>
                  </>
                ) : (
                  <>
                    <Sparkles size={16} />
                    <span>Generate Incident Response Plan</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Right Panel: Output & Publishing */}
          <div className="irpOutputCard">
            <div className="irpCardHead">
              <div className="irpCardHeadTitle">
                <FileText size={16} color="#00fbfb" />
                <h3>Generated Incident Response Plan</h3>
              </div>

              <div className="irpCardHeadActions">
                <div className="irpViewToggle">
                  <button
                    type="button"
                    className={`irpViewBtn ${irpEditorMode === 'preview' ? 'active' : ''}`}
                    onClick={() => setIrpEditorMode('preview')}
                  >
                    Formatted Preview
                  </button>
                  <button
                    type="button"
                    className={`irpViewBtn ${irpEditorMode === 'raw' ? 'active' : ''}`}
                    onClick={() => setIrpEditorMode('raw')}
                  >
                    Raw Markdown
                  </button>
                </div>

                <button
                  type="button"
                  className="irpSecondaryBtn"
                  onClick={handleCopy}
                  disabled={!generatedMarkdown}
                  title="Copy Markdown"
                >
                  {copiedMarkdown ? <Check size={14} color="#34d399" /> : <Copy size={14} />}
                  <span>{copiedMarkdown ? 'Copied!' : 'Copy'}</span>
                </button>
              </div>
            </div>

            <div className="irpCardBody irpOutputBody">
              {!generatedMarkdown && !isGenerating && (
                <div className="irpEmptyState">
                  <div className="irpEmptyIconWrap">
                    <ShieldAlert size={36} color="#71717a" />
                  </div>
                  <h4>No Incident Response Plan Generated Yet</h4>
                  <p>
                    Select an alert preset or fill in the alert details on the left, then click{' '}
                    <b>Generate Incident Response Plan</b>.
                  </p>
                </div>
              )}

              {isGenerating && (
                <div className="irpLoadingState">
                  <RefreshCw size={36} className="spin" color="#00fbfb" />
                  <h4>Azure OpenAI Generating Runbook...</h4>
                  <p>Synthesizing triage checklist, diagnostic CLI queries, and recovery options.</p>
                </div>
              )}

              {generatedMarkdown && !isGenerating && (
                <>
                  {irpEditorMode === 'raw' ? (
                    <textarea
                      className="irpRawEditor"
                      value={generatedMarkdown}
                      onChange={(e) => setGeneratedMarkdown(e.target.value)}
                    />
                  ) : (
                    <div className="irpMarkdownPreview">
                      <pre className="irpPreWrap">
                        <code>{generatedMarkdown}</code>
                      </pre>
                    </div>
                  )}

                  {/* Publishing Bar */}
                  <div className="irpPublishPanel">
                    <div className="irpPublishPanelHeader">
                      <div className="irpPublishTitle">
                        <UploadCloud size={16} color="#00fbfb" />
                        <span>Publish to Azure DevOps Wiki</span>
                      </div>
                      <span className="irpWikiTargetBadge">
                        Wiki: {wikis.find((w) => w.id === selectedWikiId)?.name || 'Default Wiki'}
                      </span>
                    </div>

                    <div className="irpPublishRow">
                      <div className="irpPublishPathField">
                        <label>Wiki Page Path:</label>
                        <input
                          type="text"
                          className="irpPublishInput"
                          value={suggestedWikiPath}
                          onChange={(e) => setSuggestedWikiPath(e.target.value)}
                          placeholder="/Incident-Response-Plans/Alert-Name"
                        />
                      </div>

                      <button
                        type="button"
                        className="irpPublishBtn"
                        onClick={handlePublish}
                        disabled={isPublishing || !selectedWikiId}
                      >
                        {isPublishing ? (
                          <>
                            <RefreshCw size={14} className="spin" />
                            <span>Publishing...</span>
                          </>
                        ) : (
                          <>
                            <UploadCloud size={15} />
                            <span>Publish to Wiki</span>
                          </>
                        )}
                      </button>
                    </div>

                    <label className="irpCheckboxLabel">
                      <input
                        type="checkbox"
                        checked={updateInventoryCheck}
                        onChange={(e) => setUpdateInventoryCheck(e.target.checked)}
                      />
                      <span>
                        Auto-register alert in the <b>Alert Inventory</b> Wiki table (
                        <code>{inventoryPagePath}</code>)
                      </span>
                    </label>

                    {publishSuccessMsg && (
                      <div className="irpSuccessBanner">
                        <CheckCircle2 size={16} />
                        <span>{publishSuccessMsg}</span>
                      </div>
                    )}

                    {publishErrorMsg && (
                      <div className="irpErrorBanner">
                        <AlertTriangle size={16} />
                        <span>{publishErrorMsg}</span>
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 3. TAB 2: WIKI RUNBOOK & ALERT INVENTORY EXPLORER */}
      {activeTab === 'explorer' && (
        <div className="irpExplorerLayout">
          {/* Left Sidebar: Pages Tree */}
          <div className="irpExplorerSidebar">
            <div className="irpExplorerSidebarHeader">
              <div className="irpSearchWrap">
                <Search size={14} className="irpSearchIcon" />
                <input
                  type="text"
                  placeholder="Search Wiki pages..."
                  className="irpSearchInput"
                  value={pageSearchFilter}
                  onChange={(e) => setPageSearchFilter(e.target.value)}
                />
              </div>
            </div>

            <div className="irpExplorerPageList">
              {isLoadingPages ? (
                <div className="irpListLoading">
                  <RefreshCw size={18} className="spin" color="#00fbfb" />
                  <span>Loading Wiki Tree...</span>
                </div>
              ) : filteredPages.length === 0 ? (
                <div className="irpListEmpty">No pages found in this Wiki.</div>
              ) : (
                filteredPages.map((page) => (
                  <button
                    key={page.path}
                    type="button"
                    className={`irpPageItemBtn ${selectedPagePath === page.path ? 'active' : ''}`}
                    onClick={() => setSelectedPagePath(page.path)}
                  >
                    <FileText size={14} className="irpPageItemIcon" />
                    <span className="irpPageItemText">{page.path}</span>
                    <ChevronRight size={13} className="irpPageItemArrow" />
                  </button>
                ))
              )}
            </div>
          </div>

          {/* Right Area: Page Content Reader */}
          <div className="irpExplorerContent">
            <div className="irpExplorerContentHead">
              <div className="irpContentPathWrap">
                <Layers size={16} color="#00fbfb" />
                <span className="irpContentPath">{selectedPagePath || 'Select a Wiki Page'}</span>
              </div>

              {selectedPageContent && (
                <button
                  type="button"
                  className="irpSecondaryBtn"
                  onClick={() => {
                    navigator.clipboard.writeText(selectedPageContent)
                  }}
                  title="Copy Page Markdown"
                >
                  <Copy size={14} />
                  <span>Copy Markdown</span>
                </button>
              )}
            </div>

            <div className="irpExplorerBody">
              {isLoadingContent ? (
                <div className="irpLoadingState">
                  <RefreshCw size={28} className="spin" color="#00fbfb" />
                  <span>Loading Page Content...</span>
                </div>
              ) : (
                <pre className="irpExplorerPre">
                  <code>{selectedPageContent || '# Select a page on the left to view its contents.'}</code>
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
