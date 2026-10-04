import React, { useState } from 'react'
import {
  ShieldAlert,
  Sparkles,
  Copy,
  Check,
  FileText,
  Upload,
  Download,
  Terminal,
  Code2,
  HelpCircle,
  FileCode2,
  Trash2,
  AlertTriangle,
  Info,
  Layers,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { api } from '../services/api'
import type { IrpGenerateResponse } from '../types/api'

interface IncidentResponsePageProps {
  organization?: string
  project?: string
  pat?: string
  projects?: Array<{ id: string; name: string }>
  onOrganizationChange?: (org: string) => void
  onProjectChange?: (proj: string) => void
  onPatChange?: (pat: string) => void
  theme?: 'dark' | 'light'
}

const DEFAULT_ALERT_PRESETS = [
  {
    name: 'VPN Tunnel Disconnected',
    cvrd: 'CVRD-NET-8821',
    columns: 'TimeGenerated, ResourceGroup, GatewayName, ConnectionState, PeerIP, DisconnectReason',
    details: 'IPsec Phase 2 tunnel dropped between on-prem datacenter and Azure Virtual Network Gateway. High risk of database replication drop and internal API failure.',
    arm: `{\n  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",\n  "contentVersion": "1.0.0.0",\n  "resources": [\n    {\n      "type": "Microsoft.Network/virtualNetworkGateways",\n      "apiVersion": "2023-04-01",\n      "name": "vnet-gw-prod-east",\n      "location": "eastus",\n      "properties": {\n        "gatewayType": "Vpn",\n        "vpnType": "RouteBased",\n        "enableBgp": true,\n        "sku": { "name": "VpnGw2", "tier": "VpnGw2" }\n      }\n    }\n  ]\n}`,
    severity: 'Sev-1',
    resource: 'vnet-gw-prod-east (Microsoft.Network/virtualNetworkGateways)',
    trigger: 'Gateway Connection Status != Connected for > 2 minutes',
    team: 'Cloud Network Operations',
  },
  {
    name: 'High CPU & Request Queuing on App Service',
    cvrd: 'CVRD-COMP-4019',
    columns: 'TimeGenerated, AppName, InstanceId, CpuPercentage, MemoryPercentage, HttpQueueLength, Http5xxCount',
    details: 'Production web application exceeding 90% CPU threshold across all P2v3 scale workers with elevated HTTP 503 errors.',
    arm: `{\n  "type": "Microsoft.Web/serverfarms",\n  "apiVersion": "2022-03-01",\n  "name": "asp-prod-checkout",\n  "sku": { "name": "P2v3", "tier": "PremiumV3", "capacity": 4 }\n}`,
    severity: 'Sev-2',
    resource: 'asp-prod-checkout (Microsoft.Web/serverfarms)',
    trigger: 'CpuPercentage >= 85% for 5 continuous minutes',
    team: 'Platform SRE',
  },
  {
    name: 'Storage Account Throttling & 503 Errors',
    cvrd: 'CVRD-STR-1022',
    columns: 'TimeGenerated, AccountName, ApiName, StatusCode, ClientIpAddress, ServerTimeoutMs',
    details: 'Blob container ingress throughput hitting partition IOPS limits resulting in HTTP 503 ClientOtherErrors.',
    arm: `{\n  "type": "Microsoft.Storage/storageAccounts",\n  "apiVersion": "2022-09-01",\n  "name": "stprodanalyticsdata",\n  "sku": { "name": "Standard_ZRS" },\n  "kind": "StorageV2"\n}`,
    severity: 'Sev-2',
    resource: 'stprodanalyticsdata (Microsoft.Storage/storageAccounts)',
    trigger: 'ClientOtherErrorCount > 100 in 5 minutes',
    team: 'Data Platform Operations',
  },
]

export const IncidentResponsePage: React.FC<IncidentResponsePageProps> = () => {
  // Alert Details & ARM context
  const [alertName, setAlertName] = useState<string>('VPN Tunnel Disconnected')
  const [cvrd, setCvrd] = useState<string>('CVRD-NET-8821')
  const [alertOutputColumns, setAlertOutputColumns] = useState<string>(
    'TimeGenerated, ResourceGroup, GatewayName, ConnectionState, PeerIP, DisconnectReason'
  )
  const [alertDetails, setAlertDetails] = useState<string>(
    'IPsec Phase 2 tunnel dropped between on-prem datacenter and Azure Virtual Network Gateway. High risk of database replication drop and internal API failure.'
  )
  const [armTemplateContext, setArmTemplateContext] = useState<string>(
    DEFAULT_ALERT_PRESETS[0].arm
  )
  const [targetResource, setTargetResource] = useState<string>(
    'vnet-gw-prod-east (Microsoft.Network/virtualNetworkGateways)'
  )
  const [severity, setSeverity] = useState<string>('Sev-1')
  const [triggerCondition, setTriggerCondition] = useState<string>(
    'Gateway Connection Status != Connected for > 2 minutes'
  )
  const [owningTeam, setOwningTeam] = useState<string>('Cloud Network Operations')
  const [environment, setEnvironment] = useState<string>('Production')
  const [additionalNotes, setAdditionalNotes] = useState<string>('')

  // Uploaded Template & Example
  const [irpTemplate, setIrpTemplate] = useState<string>('')
  const [irpTemplateFileName, setIrpTemplateFileName] = useState<string>('')
  const [irpExample, setIrpExample] = useState<string>('')
  const [irpExampleFileName, setIrpExampleFileName] = useState<string>('')

  // UI expand collapse states
  const [showArmBox, setShowArmBox] = useState<boolean>(true)
  const [showTemplateBox, setShowTemplateBox] = useState<boolean>(true)
  const [showExampleBox, setShowExampleBox] = useState<boolean>(true)

  // Output & Generation State
  const [isGenerating, setIsGenerating] = useState<boolean>(false)
  const [generatedIrp, setGeneratedIrp] = useState<string>('')
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [viewMode, setViewMode] = useState<'preview' | 'raw'>('preview')
  const [copied, setCopied] = useState<boolean>(false)

  // Handle Preset Selection
  const applyPreset = (preset: typeof DEFAULT_ALERT_PRESETS[0]) => {
    setAlertName(preset.name)
    setCvrd(preset.cvrd)
    setAlertOutputColumns(preset.columns)
    setAlertDetails(preset.details)
    setArmTemplateContext(preset.arm)
    setSeverity(preset.severity)
    setTargetResource(preset.resource)
    setTriggerCondition(preset.trigger)
    setOwningTeam(preset.team)
  }

  // File Upload Handlers
  const handleTemplateFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setIrpTemplateFileName(file.name)
    const reader = new FileReader()
    reader.onload = (event) => {
      const content = event.target?.result as string
      setIrpTemplate(content || '')
    }
    reader.readAsText(file)
  }

  const handleExampleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setIrpExampleFileName(file.name)
    const reader = new FileReader()
    reader.onload = (event) => {
      const content = event.target?.result as string
      setIrpExample(content || '')
    }
    reader.readAsText(file)
  }

  // Handle Generation
  const handleGenerate = async () => {
    if (!alertName.trim()) {
      setErrorMessage('Please provide an Alert Name.')
      return
    }

    setIsGenerating(true)
    setErrorMessage('')

    try {
      const res: IrpGenerateResponse = await api.generateIrp({
        alert_name: alertName,
        cvrd: cvrd.trim() || undefined,
        alert_output_columns: alertOutputColumns.trim() || undefined,
        arm_template_context: armTemplateContext.trim() || undefined,
        alert_details: alertDetails.trim() || undefined,
        target_resource: targetResource.trim() || undefined,
        severity,
        trigger_condition: triggerCondition.trim() || undefined,
        owning_team: owningTeam.trim() || undefined,
        environment,
        irp_template: irpTemplate.trim() || undefined,
        irp_example: irpExample.trim() || undefined,
        additional_notes: additionalNotes.trim() || undefined,
      })

      setGeneratedIrp(res.markdown_content)
    } catch (err: any) {
      setErrorMessage(err?.response?.data?.detail || err?.message || 'Failed to generate Incident Response Plan.')
    } finally {
      setIsGenerating(false)
    }
  }

  // Copy to Clipboard
  const handleCopyClipboard = async () => {
    if (!generatedIrp) return
    try {
      await navigator.clipboard.writeText(generatedIrp)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      // Fallback
      const el = document.createElement('textarea')
      el.value = generatedIrp
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    }
  }

  // Download Markdown
  const handleDownload = () => {
    if (!generatedIrp) return
    const blob = new Blob([generatedIrp], { type: 'text/markdown;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    const fileName = `${alertName.replace(/[^a-zA-Z0-9_-]/g, '_')}_IRP.md`
    link.href = url
    link.setAttribute('download', fileName)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  // Formatted Markdown Preview Renderer matching Azure DevOps Wiki Document standard
  const renderInlineMarkdown = (text: string): React.ReactNode => {
    if (!text) return null

    // Replace literal <br> or <br/> tags
    const parts = text.split(/(<br\s*\/?>)/gi)

    return parts.map((part, pIdx) => {
      if (part.toLowerCase().startsWith('<br')) {
        return <br key={`br-${pIdx}`} />
      }

      // Tokenize for **bold**, *italic*, `inline code`, [link](url)
      const tokenRegex = /(\*\*[\s\S]*?\*\*|\*[\s\S]*?\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g
      const tokens = part.split(tokenRegex)

      return (
        <React.Fragment key={`inline-${pIdx}`}>
          {tokens.map((tok, tIdx) => {
            if (!tok) return null

            // **bold**
            if (tok.startsWith('**') && tok.endsWith('**') && tok.length >= 4) {
              const inner = tok.slice(2, -2)
              return (
                <strong key={tIdx} className="irpWikiBold">
                  {renderInlineMarkdown(inner)}
                </strong>
              )
            }

            // *italic*
            if (tok.startsWith('*') && tok.endsWith('*') && tok.length >= 2 && !tok.startsWith('**')) {
              const inner = tok.slice(1, -1)
              return (
                <em key={tIdx} className="irpWikiItalic">
                  {renderInlineMarkdown(inner)}
                </em>
              )
            }

            // `code`
            if (tok.startsWith('`') && tok.endsWith('`') && tok.length >= 2) {
              return (
                <code key={tIdx} className="irpWikiInlineCode">
                  {tok.slice(1, -1)}
                </code>
              )
            }

            // [link](url)
            const linkMatch = tok.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
            if (linkMatch) {
              return (
                <a
                  key={tIdx}
                  href={linkMatch[2]}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="irpWikiLink"
                >
                  {linkMatch[1]}
                </a>
              )
            }

            return <span key={tIdx}>{tok}</span>
          })}
        </React.Fragment>
      )
    })
  }

  const splitTableRow = (r: string): string[] => {
    let trimmed = r.trim()
    if (trimmed.startsWith('|')) trimmed = trimmed.slice(1)
    if (trimmed.endsWith('|')) trimmed = trimmed.slice(0, -1)

    const cells: string[] = []
    let current = ''
    let inCode = false

    for (let idx = 0; idx < trimmed.length; idx++) {
      const char = trimmed[idx]
      const prev = idx > 0 ? trimmed[idx - 1] : ''

      if (char === '`' && prev !== '\\') {
        inCode = !inCode
        current += char
      } else if (char === '|' && !inCode && prev !== '\\') {
        cells.push(current.trim())
        current = ''
      } else {
        current += char
      }
    }
    cells.push(current.trim())
    return cells
  }

  const renderMarkdownPreview = (rawContent: string) => {
    if (!rawContent) return null

    // Clean initial backticks if response is wrapped in ```markdown ... ```
    let text = rawContent.trim()
    if (text.startsWith('```markdown')) {
      text = text.replace(/^```markdown\s*/, '').replace(/```\s*$/, '')
    } else if (text.startsWith('```')) {
      text = text.replace(/^```\s*/, '').replace(/```\s*$/, '')
    }

    // Strip any Authoring Checklist section completely
    text = text.replace(/\n*#+\s*(?:IRP\s+)?Authoring\s+Checklist[\s\S]*$/i, '').trim()

    // Split text into distinct markdown blocks while preserving code blocks and tables
    const lines = text.split('\n')
    const blocks: Array<{ type: string; content: string; lang?: string; rows?: string[][] }> = []

    let i = 0
    while (i < lines.length) {
      const line = lines[i]
      const trimmed = line.trim()

      // Empty line
      if (!trimmed) {
        i++
        continue
      }

      // Code Block: ```lang
      if (trimmed.startsWith('```')) {
        const lang = trimmed.replace('```', '').trim() || 'bash'
        const codeLines: string[] = []
        i++
        while (i < lines.length && !lines[i].trim().startsWith('```')) {
          codeLines.push(lines[i])
          i++
        }
        if (i < lines.length) i++ // skip closing ```
        blocks.push({
          type: 'code',
          lang,
          content: codeLines.join('\n'),
        })
        continue
      }

      // Table Block: starts with |
      if (trimmed.startsWith('|')) {
        const tableLines: string[] = []
        while (i < lines.length && lines[i].trim().startsWith('|')) {
          tableLines.push(lines[i].trim())
          i++
        }

        if (tableLines.length >= 2) {
          let headers = splitTableRow(tableLines[0])
          
          // Check if this is the Remediation Steps table
          const isRemediationTable = headers.some((h) => /steps/i.test(h)) && headers.some((h) => /action/i.test(h))
          if (isRemediationTable) {
            headers = ['**STEPS**', '**ACTION**', '**ADDITIONAL COMMENTS**']
          }

          const expectedCols = headers.length

          // Skip divider row (row 1 like |---|---|)
          const dataRows = tableLines.slice(2).map((r) => {
            const rawCells = splitTableRow(r)
            if (rawCells.length === expectedCols) {
              return rawCells
            }
            if (rawCells.length > expectedCols && expectedCols === 3) {
              // Merge overflow cells (from KQL unescaped pipes) into the ACTION column (index 1)
              const first = rawCells[0]
              const last = rawCells[rawCells.length - 1]
              const middle = rawCells.slice(1, rawCells.length - 1).join(' | ')
              return [first, middle, last]
            }
            if (rawCells.length > expectedCols) {
              const head = rawCells.slice(0, expectedCols - 1)
              const tail = rawCells.slice(expectedCols - 1).join(' | ')
              return [...head, tail]
            }
            // Pad if fewer cells
            const padded = [...rawCells]
            while (padded.length < expectedCols) {
              padded.push('')
            }
            return padded
          })

          blocks.push({
            type: 'table',
            content: '',
            rows: [headers, ...dataRows],
          })
          continue
        }
      }

      // Header 1: # Title
      if (trimmed.startsWith('# ')) {
        blocks.push({
          type: 'h1',
          content: trimmed.replace(/^#\s+/, ''),
        })
        i++
        continue
      }

      // Header 2: ## Section
      if (trimmed.startsWith('## ')) {
        blocks.push({
          type: 'h2',
          content: trimmed.replace(/^##\s+/, ''),
        })
        i++
        continue
      }

      // Header 3: ### Sub-section
      if (trimmed.startsWith('### ')) {
        blocks.push({
          type: 'h3',
          content: trimmed.replace(/^###\s+/, ''),
        })
        i++
        continue
      }

      // Blockquote: > Quote
      if (trimmed.startsWith('>')) {
        const quoteLines: string[] = []
        while (i < lines.length && lines[i].trim().startsWith('>')) {
          quoteLines.push(lines[i].trim().replace(/^>\s*/, ''))
          i++
        }
        blocks.push({
          type: 'blockquote',
          content: quoteLines.join('\n'),
        })
        continue
      }

      // List (unordered, ordered, or checklist)
      if (
        trimmed.startsWith('- ') ||
        trimmed.startsWith('* ') ||
        trimmed.startsWith('- [ ]') ||
        trimmed.startsWith('- [x]') ||
        /^\d+\.\s+/.test(trimmed)
      ) {
        const listItems: string[] = []
        while (
          i < lines.length &&
          lines[i].trim() &&
          (lines[i].trim().startsWith('- ') ||
            lines[i].trim().startsWith('* ') ||
            lines[i].trim().startsWith('- [') ||
            /^\d+\.\s+/.test(lines[i].trim()))
        ) {
          listItems.push(lines[i].trim())
          i++
        }
        blocks.push({
          type: 'list',
          content: listItems.join('\n'),
        })
        continue
      }

      // Horizontal Rule
      if (trimmed === '---' || trimmed === '***' || trimmed === '___') {
        blocks.push({
          type: 'hr',
          content: '',
        })
        i++
        continue
      }

      // Paragraph: collect until blank line or next block element
      const pLines: string[] = []
      while (
        i < lines.length &&
        lines[i].trim() &&
        !lines[i].trim().startsWith('#') &&
        !lines[i].trim().startsWith('```') &&
        !lines[i].trim().startsWith('|') &&
        !lines[i].trim().startsWith('>') &&
        !lines[i].trim().startsWith('- ') &&
        !lines[i].trim().startsWith('* ') &&
        !/^\d+\.\s+/.test(lines[i].trim())
      ) {
        pLines.push(lines[i].trim())
        i++
      }

      blocks.push({
        type: 'p',
        content: pLines.join(' '),
      })
    }

    return (
      <div className="irpWikiPaper">
        {/* Azure DevOps Wiki Breadcrumb & Page Ribbon */}
        <div className="irpWikiPaperHeader">
          <div className="irpWikiBreadcrumb">
            <span className="irpWikiBreadcrumbOrg">Azure DevOps Wiki</span>
            <span className="irpWikiBreadcrumbSep">/</span>
            <span className="irpWikiBreadcrumbFolder">Incident-Response-Plans</span>
            <span className="irpWikiBreadcrumbSep">/</span>
            <span className="irpWikiBreadcrumbPage">{alertName || 'Incident Response Plan'}</span>
          </div>
          <div className="irpWikiBadge">
            <span className="irpWikiBadgeDot" /> Production IRP Runbook
          </div>
        </div>

        {/* Wiki Document Content */}
        <div className="irpWikiDocument">
          {blocks.map((block, idx) => {
            // H1
            if (block.type === 'h1') {
              return (
                <h1 key={idx} className="irpWikiH1">
                  <span className="irpWikiH1Accent" />
                  <span>{renderInlineMarkdown(block.content)}</span>
                </h1>
              )
            }

            // H2
            if (block.type === 'h2') {
              return (
                <h2 key={idx} className="irpWikiH2">
                  <span className="irpWikiH2Accent" />
                  <span>{renderInlineMarkdown(block.content)}</span>
                </h2>
              )
            }

            // H3
            if (block.type === 'h3') {
              return (
                <h3 key={idx} className="irpWikiH3">
                  {renderInlineMarkdown(block.content)}
                </h3>
              )
            }

            // Code Block
            if (block.type === 'code') {
              return (
                <div key={idx} className="irpWikiCodeBlock">
                  <div className="irpWikiCodeHeader">
                    <div className="irpWikiCodeHeaderLeft">
                      <Terminal size={12} className="irpWikiCodeIcon" />
                      <span>{block.lang || 'bash'}</span>
                    </div>
                    <button
                      type="button"
                      className="irpWikiCodeCopyBtn"
                      onClick={() => {
                        navigator.clipboard.writeText(block.content)
                      }}
                      title="Copy code"
                    >
                      <Copy size={12} />
                      <span>Copy</span>
                    </button>
                  </div>
                  <pre className="irpWikiCodePre">
                    <code>{block.content}</code>
                  </pre>
                </div>
              )
            }

            // Table
            if (block.type === 'table' && block.rows && block.rows.length > 0) {
              const headers = block.rows[0]
              const bodyRows = block.rows.slice(1)
              return (
                <div key={idx} className="irpWikiTableWrapper">
                  <table className="irpWikiTable">
                    <thead>
                      <tr>
                        {headers.map((h, hIdx) => (
                          <th key={hIdx}>{renderInlineMarkdown(h)}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {bodyRows.map((row, rIdx) => (
                        <tr key={rIdx}>
                          {row.map((cell, cIdx) => (
                            <td key={cIdx}>{renderInlineMarkdown(cell)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }

            // Blockquote
            if (block.type === 'blockquote') {
              return (
                <blockquote key={idx} className="irpWikiQuote">
                  {renderInlineMarkdown(block.content)}
                </blockquote>
              )
            }

            // List
            if (block.type === 'list') {
              const items = block.content.split('\n')
              const isNumbered = /^\d+\.\s+/.test(items[0])

              if (isNumbered) {
                return (
                  <ol key={idx} className="irpWikiOl">
                    {items.map((it, itIdx) => {
                      const clean = it.replace(/^\d+\.\s+/, '')
                      return <li key={itIdx}>{renderInlineMarkdown(clean)}</li>
                    })}
                  </ol>
                )
              }

              return (
                <ul key={idx} className="irpWikiUl">
                  {items.map((it, itIdx) => {
                    const isChecklist = it.includes('[ ]') || it.includes('[x]')
                    const isChecked = it.includes('[x]')
                    const clean = it.replace(/^[-*]\s*(\[[ x]\]\s*)?/, '')
                    return (
                      <li key={itIdx} className={isChecklist ? 'irpWikiCheckItem' : 'irpWikiListItem'}>
                        {isChecklist && (
                          <input
                            type="checkbox"
                            checked={isChecked}
                            readOnly
                            className="irpWikiCheckbox"
                          />
                        )}
                        <span>{renderInlineMarkdown(clean)}</span>
                      </li>
                    )
                  })}
                </ul>
              )
            }

            // Horizontal Rule
            if (block.type === 'hr') {
              return <hr key={idx} className="irpWikiHr" />
            }

            // Paragraph
            return (
              <p key={idx} className="irpWikiParagraph">
                {renderInlineMarkdown(block.content)}
              </p>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div className="irpPageContainer">
      {/* Top Banner */}
      <div className="irpHeaderBanner">
        <div className="irpHeaderTitleBlock">
          <div className="irpHeaderIconWrap">
            <ShieldAlert size={28} />
          </div>
          <div>
            <h1 className="irpHeaderTitle">Incident Response Plan (IRP) Studio</h1>
            <p className="irpHeaderSubtitle">
              Generate production-grade runbooks adhering strictly to your organization's IRP template, schema example, and official Azure documentation.
            </p>
          </div>
        </div>
      </div>

      {/* Preset Pills */}
      <div className="irpPresetsBar">
        <span className="irpPresetsLabel">
          <Sparkles size={14} style={{ color: '#818cf8', marginRight: '6px' }} /> Quick Fill Alert Preset:
        </span>
        <div className="irpPresetPillList">
          {DEFAULT_ALERT_PRESETS.map((preset) => (
            <button
              key={preset.name}
              type="button"
              className={`irpPresetPill ${alertName === preset.name ? 'active' : ''}`}
              onClick={() => applyPreset(preset)}
            >
              {preset.name}
            </button>
          ))}
        </div>
      </div>

      {/* Main 2-Column Split: 3 Input Sections Left, 1 Output Section Right */}
      <div className="irpStudioGrid">
        {/* ================= LEFT COLUMN: 3 CONFIG SECTIONS ================= */}
        <div className="irpLeftCol">
          {/* SECTION 1: ALERT & ARM DETAILS */}
          <div className="irpCardSection">
            <div className="irpCardHeader">
              <div className="irpCardHeaderTitle">
                <FileCode2 size={18} className="irpSectionIcon" />
                <span>1. Alert & ARM Template Details</span>
              </div>
              <span className="irpBadgeSev">{severity}</span>
            </div>

            <div className="irpFormGrid">
              <div className="irpInputGroup">
                <label className="irpLabel">
                  Alert Name <span className="irpReq">*</span>
                </label>
                <input
                  type="text"
                  className="irpInput"
                  value={alertName}
                  onChange={(e) => setAlertName(e.target.value)}
                  placeholder="e.g. VPN Tunnel Disconnected"
                />
              </div>

              <div className="irpInputGroup">
                <label className="irpLabel">CVRD / Alert Identifier</label>
                <input
                  type="text"
                  className="irpInput"
                  value={cvrd}
                  onChange={(e) => setCvrd(e.target.value)}
                  placeholder="e.g. CVRD-NET-8821"
                />
              </div>

              <div className="irpInputGroup fullWidth">
                <label className="irpLabel">Alert Output Columns (from KQL / Telemetry Query)</label>
                <input
                  type="text"
                  className="irpInput"
                  value={alertOutputColumns}
                  onChange={(e) => setAlertOutputColumns(e.target.value)}
                  placeholder="e.g. TimeGenerated, ResourceGroup, GatewayName, ConnectionState, PeerIP, DisconnectReason"
                />
              </div>

              <div className="irpInputGroup fullWidth">
                <label className="irpLabel">Alert Description / Report Context</label>
                <textarea
                  className="irpTextarea"
                  rows={2}
                  value={alertDetails}
                  onChange={(e) => setAlertDetails(e.target.value)}
                  placeholder="Describe what report or service this alert monitors and the symptoms triggered..."
                />
              </div>

              <div className="irpInputGroup fullWidth">
                <div
                  className="irpToggleHeader"
                  onClick={() => setShowArmBox(!showArmBox)}
                  style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}
                >
                  <label className="irpLabel" style={{ marginBottom: 0, cursor: 'pointer' }}>
                    <Code2 size={14} style={{ display: 'inline', marginRight: '6px' }} />
                    ARM Template / Bicep / Resource Context
                  </label>
                  {showArmBox ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </div>
                {showArmBox && (
                  <textarea
                    className="irpTextarea codeFont"
                    rows={4}
                    value={armTemplateContext}
                    onChange={(e) => setArmTemplateContext(e.target.value)}
                    placeholder="Paste your ARM Template JSON, Bicep snippet, or resource configuration..."
                  />
                )}
              </div>

              <div className="irpInputGroup">
                <label className="irpLabel">Target Resource / Service</label>
                <input
                  type="text"
                  className="irpInput"
                  value={targetResource}
                  onChange={(e) => setTargetResource(e.target.value)}
                  placeholder="e.g. vnet-gw-prod-east"
                />
              </div>

              <div className="irpInputGroup">
                <label className="irpLabel">Severity</label>
                <select className="irpSelect" value={severity} onChange={(e) => setSeverity(e.target.value)}>
                  <option value="Sev-1">Sev-1 (Critical Outage)</option>
                  <option value="Sev-2">Sev-2 (High Degradation)</option>
                  <option value="Sev-3">Sev-3 (Moderate Warning)</option>
                </select>
              </div>

              <div className="irpInputGroup">
                <label className="irpLabel">Trigger Condition</label>
                <input
                  type="text"
                  className="irpInput"
                  value={triggerCondition}
                  onChange={(e) => setTriggerCondition(e.target.value)}
                  placeholder="e.g. Gateway Connection Status != 1 for > 2 mins"
                />
              </div>

              <div className="irpInputGroup">
                <label className="irpLabel">Owning Team</label>
                <input
                  type="text"
                  className="irpInput"
                  value={owningTeam}
                  onChange={(e) => setOwningTeam(e.target.value)}
                  placeholder="e.g. Cloud Network Operations"
                />
              </div>
            </div>
          </div>

          {/* SECTION 2: IRP TEMPLATE UPLOAD */}
          <div className="irpCardSection">
            <div className="irpCardHeader">
              <div className="irpCardHeaderTitle">
                <Layers size={18} className="irpSectionIcon" />
                <span>2. Organization IRP Template</span>
              </div>
              <div
                className="irpToggleHeader"
                onClick={() => setShowTemplateBox(!showTemplateBox)}
                style={{ cursor: 'pointer' }}
              >
                {showTemplateBox ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </div>
            </div>

            <p className="irpSectionHint">
              Upload your company's standard markdown IRP template. The AI will strictly follow its exact structure and headings.
            </p>

            <div className="irpUploadRow">
              <label className="irpUploadBtn">
                <Upload size={14} style={{ marginRight: '6px' }} />
                {irpTemplateFileName ? `Uploaded: ${irpTemplateFileName}` : 'Upload Template (.md, .txt, .json)'}
                <input
                  type="file"
                  accept=".md,.txt,.json,.doc,.docx"
                  style={{ display: 'none' }}
                  onChange={handleTemplateFileUpload}
                />
              </label>
              {irpTemplate && (
                <button
                  type="button"
                  className="irpClearBtn"
                  onClick={() => {
                    setIrpTemplate('')
                    setIrpTemplateFileName('')
                  }}
                  title="Clear Template"
                >
                  <Trash2 size={14} /> Clear
                </button>
              )}
            </div>

            {showTemplateBox && (
              <textarea
                className="irpTextarea codeFont"
                rows={3}
                value={irpTemplate}
                onChange={(e) => setIrpTemplate(e.target.value)}
                placeholder="Or paste your markdown IRP template here (e.g. # [Alert] Incident Response Plan&#10;## 1. Overview&#10;## 2. Immediate Triage...)"
                style={{ marginTop: '8px' }}
              />
            )}
          </div>

          {/* SECTION 3: IRP EXAMPLE UPLOAD */}
          <div className="irpCardSection">
            <div className="irpCardHeader">
              <div className="irpCardHeaderTitle">
                <FileText size={18} className="irpSectionIcon" />
                <span>3. Reference IRP Example (Schema Guide)</span>
              </div>
              <div
                className="irpToggleHeader"
                onClick={() => setShowExampleBox(!showExampleBox)}
                style={{ cursor: 'pointer' }}
              >
                {showExampleBox ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </div>
            </div>

            <p className="irpSectionHint">
              Upload a completed reference IRP. The AI will mirror this exact schema, depth, checklist format, and command style.
            </p>

            <div className="irpUploadRow">
              <label className="irpUploadBtn">
                <Upload size={14} style={{ marginRight: '6px' }} />
                {irpExampleFileName ? `Uploaded: ${irpExampleFileName}` : 'Upload Example (.md, .txt)'}
                <input
                  type="file"
                  accept=".md,.txt,.json"
                  style={{ display: 'none' }}
                  onChange={handleExampleFileUpload}
                />
              </label>
              {irpExample && (
                <button
                  type="button"
                  className="irpClearBtn"
                  onClick={() => {
                    setIrpExample('')
                    setIrpExampleFileName('')
                  }}
                  title="Clear Example"
                >
                  <Trash2 size={14} /> Clear
                </button>
              )}
            </div>

            {showExampleBox && (
              <textarea
                className="irpTextarea codeFont"
                rows={3}
                value={irpExample}
                onChange={(e) => setIrpExample(e.target.value)}
                placeholder="Or paste a completed reference IRP markdown here to guide schema and tone..."
                style={{ marginTop: '8px' }}
              />
            )}
          </div>

          {/* GENERATE BUTTON */}
          <div className="irpGenerateRow">
            <button
              type="button"
              className="irpGenerateBtn"
              onClick={handleGenerate}
              disabled={isGenerating || !alertName.trim()}
            >
              {isGenerating ? (
                <>
                  <div className="irpSpinner" /> Generating IRP from Official Docs & Template...
                </>
              ) : (
                <>
                  <Sparkles size={18} style={{ marginRight: '8px' }} /> Generate Incident Response Plan (IRP)
                </>
              )}
            </button>
          </div>

          {errorMessage && (
            <div className="irpErrorNotice">
              <AlertTriangle size={16} style={{ marginRight: '8px', flexShrink: 0 }} />
              <span>{errorMessage}</span>
            </div>
          )}
        </div>

        {/* ================= RIGHT COLUMN: GENERATED IRP ================= */}
        <div className="irpRightCol">
          <div className="irpOutputCard">
            <div className="irpOutputHeader">
              <div className="irpOutputHeaderLeft">
                <div className="irpOutputTitle">Generated Incident Response Plan</div>
                <div className="irpViewToggle">
                  <button
                    type="button"
                    className={`irpToggleBtn ${viewMode === 'preview' ? 'active' : ''}`}
                    onClick={() => setViewMode('preview')}
                  >
                    Formatted Preview
                  </button>
                  <button
                    type="button"
                    className={`irpToggleBtn ${viewMode === 'raw' ? 'active' : ''}`}
                    onClick={() => setViewMode('raw')}
                  >
                    Raw Markdown
                  </button>
                </div>
              </div>

              <div className="irpOutputHeaderRight">
                <button
                  type="button"
                  className={`irpActionBtn ${copied ? 'copied' : ''}`}
                  onClick={handleCopyClipboard}
                  disabled={!generatedIrp}
                  title="Copy generated IRP markdown to clipboard"
                >
                  {copied ? (
                    <>
                      <Check size={15} style={{ color: '#10b981', marginRight: '6px' }} />
                      <span>Copied to Clipboard!</span>
                    </>
                  ) : (
                    <>
                      <Copy size={15} style={{ marginRight: '6px' }} />
                      <span>Copy to Clipboard</span>
                    </>
                  )}
                </button>

                <button
                  type="button"
                  className="irpActionBtn secondary"
                  onClick={handleDownload}
                  disabled={!generatedIrp}
                  title="Download as .md file"
                >
                  <Download size={15} style={{ marginRight: '6px' }} />
                  <span>Download .md</span>
                </button>
              </div>
            </div>

            <div className="irpOutputBody">
              {generatedIrp ? (
                viewMode === 'preview' ? (
                  renderMarkdownPreview(generatedIrp)
                ) : (
                  <textarea
                    className="irpRawTextarea"
                    value={generatedIrp}
                    onChange={(e) => setGeneratedIrp(e.target.value)}
                    placeholder="Generated raw markdown will appear here..."
                  />
                )
              ) : (
                <div className="irpEmptyState">
                  <div className="irpEmptyIconWrap">
                    <ShieldAlert size={36} />
                  </div>
                  <h3>Ready to Generate Your IRP</h3>
                  <p>
                    Fill in your alert details on the left, optionally upload your organization's IRP template or reference example, and click <strong>Generate Incident Response Plan</strong>.
                  </p>
                  <div className="irpGuidanceList">
                    <div className="irpGuidanceItem">
                      <Check size={14} style={{ color: '#10b981', marginRight: '6px' }} />
                      <span>Official Azure documentation CLI commands, PowerShell, and KQL queries</span>
                    </div>
                    <div className="irpGuidanceItem">
                      <Check size={14} style={{ color: '#10b981', marginRight: '6px' }} />
                      <span>Strict compliance with your uploaded template and example schema</span>
                    </div>
                    <div className="irpGuidanceItem">
                      <Check size={14} style={{ color: '#10b981', marginRight: '6px' }} />
                      <span>One-click Copy to Clipboard to paste directly into your ADO Wiki</span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {generatedIrp && (
              <div className="irpOutputFooter">
                <Info size={14} style={{ marginRight: '6px', opacity: 0.7 }} />
                <span>
                  Tip: Use <strong>Copy to Clipboard</strong> to paste directly into your Azure DevOps Wiki page or SRE Runbook portal.
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
