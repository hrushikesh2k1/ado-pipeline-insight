import React, { useState } from 'react'
import { Check, CircleAlert, CircleCheck, CircleX, Copy, ExternalLink, FlaskConical, Info, ListChecks, Plus, Search, Trash2, TriangleAlert } from 'lucide-react'
import type { IrpAnalyzeResponse, IrpCase, IrpCommand, IrpScoreCheck, IrpScorecard } from '../types/api'
import { LANGUAGE_LABEL, MAX_CASES, ORIGIN_LABEL, STATUS_LABEL, commandsAsText, commandsByRisk, humanDuration, isAiWrittenQuery, scoreHeadline } from '../utils/irpGrounded'
import './IrpGroundedPanels.css'

const lastPart = (id: string) => id.replace(/\/+$/, '').split('/').pop() || id

// ---------------------------------------------------------------- analysis

interface AnalysisCardProps {
  analysis: IrpAnalyzeResponse | null
  stale: boolean
  isAnalyzing: boolean
  error: string
  canAnalyze: boolean
  onAnalyze: () => void
  cases: IrpCase[]
  onCasesChange: (cases: IrpCase[]) => void
  alertName: string
  onUseName: (name: string) => void
}

export const IrpAnalysisCard: React.FC<AnalysisCardProps> = ({ analysis, stale, isAnalyzing, error, canAnalyze, onAnalyze, cases, onCasesChange, alertName, onUseName }) => {
  const facts = analysis?.facts
  const alert = facts?.alert
  const update = (index: number, patch: Partial<IrpCase>) => onCasesChange(cases.map((c, i) => (i === index ? { ...c, ...patch } : c)))

  return (
    <div className="irpg irpgCard" data-testid="irp-analysis">
      <div className="irpgHead">
        <div className="irpgTitle"><Search size={17} /> <span>Analyze the alert</span></div>
        <button type="button" className="irpgBtn" onClick={onAnalyze} disabled={!canAnalyze || isAnalyzing} data-testid="irp-analyze">
          {isAnalyzing ? <><span className="irpgSpin" /> Reading…</> : analysis ? 'Analyze again' : 'Analyze alert'}
        </button>
      </div>
      {!analysis && !error && (
        <p className="irpgHint">
          Reads your ARM template and query, shows what it found, and proposes the root causes of this alert so you can edit them before the IRP is written.
          This step is optional: <b>Generate</b> does it for you.
        </p>
      )}
      {stale && analysis && (
        <div className="irpgNote warn" data-testid="irp-analysis-stale"><TriangleAlert size={14} /> The alert details changed since this analysis. Analyze again to refresh it, or the root causes below are used as they are.</div>
      )}
      {error && <div className="irpgNote fail" data-testid="irp-analysis-error"><CircleX size={14} /> {error}</div>}
      {analysis?.notice && <div className="irpgNote info" data-testid="irp-analysis-notice"><Info size={14} /> {analysis.notice}</div>}

      {facts?.has_definition && (
        <dl className="irpgFacts" data-testid="irp-facts">
          {alert && (
            <>
              <dt>Alert in the template</dt>
              <dd>
                <b>{alert.name}</b>
                {facts.arm.alerts_found.length > 1 && <span className="irpgMuted"> (1 of {facts.arm.alerts_found.length} alerts in the template)</span>}
                {alert.name.trim().toLowerCase() !== alertName.trim().toLowerCase() && (
                  <button type="button" className="irpgLink" onClick={() => onUseName(alert.name)} data-testid="irp-use-name">Use this name</button>
                )}
              </dd>
              <dt>Type</dt>
              <dd>{alert.type === 'log' ? 'Log alert' : 'Metric alert'}{alert.kind ? ` · ${alert.kind}` : ''}{alert.api_version ? ` · API ${alert.api_version}` : ''}{alert.enabled === false ? ' · disabled' : ''}</dd>
              <dt>Fires when</dt>
              <dd>{facts.description_sentence}</dd>
              {facts.severity_name && (<><dt>Severity</dt><dd>{facts.severity_name} <span className="irpgMuted">(taken from the template)</span></dd></>)}
              {(alert.product || alert.scopes.length > 0) && (
                <><dt>Watches</dt><dd>{alert.product ?? ''}{alert.scopes.length > 0 && <span className="irpgMuted"> {alert.product ? '· ' : ''}scope {alert.scopes.map(lastPart).join(', ')}</span>}</dd></>
              )}
              {alert.action_groups.length > 0 && (<><dt>Action groups</dt><dd>{alert.action_groups.join(', ')}</dd></>)}
            </>
          )}
          {facts.kql.query && (
            <>
              <dt>Query</dt>
              <dd>
                {facts.kql.source === 'input' ? 'the query you pasted' : 'from the ARM template'}
                {facts.kql.tables.length > 0 && <> · reads <code>{facts.kql.tables.join(', ')}</code></>}
                {facts.kql.filters.slice(0, 3).map(f => <span key={f.column + f.values.join()} className="irpgChip">{f.column} {f.operator} {f.values.join(', ')}</span>)}
                {facts.kql.time_windows.length > 0 && <div className="irpgMuted" data-testid="irp-lookback">The query looks back {facts.kql.time_windows.join(', ')}{alert?.window_size ? ` (the alert window is ${humanDuration(alert.window_size)})` : ''}</div>}
                {facts.kql.output_columns.length > 0 && <div className="irpgMuted">Output columns: {facts.kql.output_columns.join(', ')}</div>}
              </dd>
            </>
          )}
        </dl>
      )}
      {facts && facts.warnings.length > 0 && (
        <ul className="irpgWarnings" data-testid="irp-facts-warnings">
          {facts.warnings.map(w => <li key={w}><TriangleAlert size={13} /> {w}</li>)}
        </ul>
      )}

      {(analysis || cases.length > 0) && (
        <div className="irpgCases" data-testid="irp-cases">
          <div className="irpgSubHead">Root causes <span className="irpgMuted">(each becomes a Case row; 2 to 5 is easiest to follow)</span></div>
          {cases.length === 0 && <p className="irpgHint">None yet. Add the causes you know, or leave this empty and Generate will propose them from the query.</p>}
          {cases.map((c, i) => (
            <div key={i} className="irpgCaseRow">
              <span className="irpgCaseNo">{i + 1}</span>
              <input className="irpgInput" value={c.name} onChange={e => update(i, { name: e.target.value })} placeholder="What goes wrong, for example: IPsec Phase 2 tunnel dropped" aria-label={`Root cause ${i + 1}`} data-testid={`irp-case-name-${i}`} />
              <input className="irpgInput" value={c.signal ?? ''} onChange={e => update(i, { signal: e.target.value })} placeholder="How to recognise it (a column, a log message, a state)" aria-label={`How to recognise root cause ${i + 1}`} />
              <button type="button" className="irpgIconBtn" onClick={() => onCasesChange(cases.filter((_, j) => j !== i))} aria-label={`Remove root cause ${i + 1}`}><Trash2 size={14} /></button>
            </div>
          ))}
          <button type="button" className="irpgLink" onClick={() => onCasesChange([...cases, { name: '', signal: '' }])} disabled={cases.length >= MAX_CASES} data-testid="irp-add-case"><Plus size={13} /> Add a root cause</button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- scorecard

const ICONS: Record<IrpScoreCheck['status'], React.ReactNode> = {
  pass: <CircleCheck size={16} />, warn: <CircleAlert size={16} />, fail: <CircleX size={16} />, info: <Info size={16} />,
}

export const IrpScorecardCard: React.FC<{ scorecard: IrpScorecard }> = ({ scorecard }) => (
  <div className="irpg irpgCard" data-testid="irp-scorecard">
    <div className="irpgHead">
      <div className="irpgTitle"><ListChecks size={17} /> <span>Quality checklist</span></div>
      <span className={`irpgChip status ${scorecard.status}`} data-testid="irp-scorecard-status">{scoreHeadline(scorecard)}</span>
    </div>
    <ul className="irpgChecks">
      {scorecard.checks.map(check => (
        <li key={check.id} className={`irpgCheck ${check.status}`} data-testid={`irp-check-${check.id}`} data-status={check.status}>
          <span className="irpgCheckIcon">{ICONS[check.status]}</span>
          <div>
            <div className="irpgCheckTitle">{check.title} <span className="irpgMuted">· {STATUS_LABEL[check.status]}</span></div>
            <div className="irpgMuted">{check.detail}</div>
            {check.items.length > 0 && check.id !== 'qa' && (
              <ul className="irpgCheckItems">{check.items.map(item => <li key={item}>{item}</li>)}</ul>
            )}
          </div>
        </li>
      ))}
    </ul>
  </div>
)

// ---------------------------------------------------------------- commands for QA

const CommandItem: React.FC<{ command: IrpCommand }> = ({ command }) => {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command.text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      /* the clipboard can be blocked; nothing else to do */
    }
  }
  return (
    <li className="irpgCommand" data-testid="irp-command">
      <div className="irpgCommandHead">
        <span className="irpgChip lang">{LANGUAGE_LABEL[command.language]}</span>
        <span className={`irpgChip ${command.status}`}>{command.status === 'verified' ? 'Verified by QA' : 'Unverified'}</span>
        {command.origin && command.language === 'kql' && (
          <span className={`irpgChip origin ${isAiWrittenQuery(command) ? 'ai' : 'alert'}`} data-testid="irp-command-origin">
            {isAiWrittenQuery(command) ? 'Written by the AI: test first' : ORIGIN_LABEL[command.origin]}
          </span>
        )}
        <span className="irpgCommandRow">{command.row}{command.where ? ` · ${command.where}` : ''}</span>
        <button type="button" className="irpgIconBtn" onClick={copy} aria-label="Copy command">{copied ? <Check size={14} /> : <Copy size={14} />}</button>
      </div>
      <pre className="irpgCode">{command.text}</pre>
      {command.issues.map(issue => (
        <div key={issue.id} className={`irpgNote ${issue.severity === 'fail' ? 'fail' : 'warn'}`} data-testid="irp-command-issue">
          {issue.severity === 'fail' ? <CircleX size={14} /> : <TriangleAlert size={14} />}
          <span>{issue.message} <a href={issue.doc} target="_blank" rel="noreferrer">Documentation <ExternalLink size={10} /></a></span>
        </div>
      ))}
    </li>
  )
}

export const IrpCommandsCard: React.FC<{ commands: IrpCommand[] }> = ({ commands }) => {
  const [copied, setCopied] = useState(false)
  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(commandsAsText(commands))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      /* ignore */
    }
  }
  const unverified = commands.filter(c => c.status === 'unverified').length
  return (
    <div className="irpg irpgCard" data-testid="irp-commands">
      <div className="irpgHead">
        <div className="irpgTitle"><FlaskConical size={17} /> <span>Commands for QA to test</span></div>
        <button type="button" className="irpgBtn" onClick={copyAll} disabled={commands.length === 0}>{copied ? <Check size={13} /> : <Copy size={13} />} Copy all</button>
      </div>
      <p className="irpgHint">{commands.length} command{commands.length === 1 ? '' : 's'} in this IRP, {unverified} not yet verified by QA. Commands with a known problem come first, then queries the AI wrote.</p>
      <ul className="irpgCommands">{commandsByRisk(commands).map(c => <CommandItem key={c.id} command={c} />)}</ul>
    </div>
  )
}
