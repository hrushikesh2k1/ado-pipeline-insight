import type { IrpCase, IrpCommand, IrpScoreCheck, IrpScorecard } from '../types/api'

export const MAX_CASES = 8

/** The cases to send: trimmed, without empty names, at most the number the server accepts. */
export function casesForRequest(cases: IrpCase[]): IrpCase[] {
  return cases
    .map(c => ({ name: c.name.trim(), signal: (c.signal ?? '').trim() }))
    .filter(c => c.name)
    .slice(0, MAX_CASES)
}

/** Changes whenever something an analysis was made from changes, so a stale analysis can be told from a current one. */
export function inputsKey(parts: Array<string | number | undefined | null>): string {
  return JSON.stringify(parts.map(p => (p ?? '').toString().trim()))
}

export const STATUS_LABEL: Record<IrpScoreCheck['status'], string> = { pass: 'Passed', warn: 'Check', fail: 'Fix', info: 'Info' }

export function scoreHeadline(card: IrpScorecard): string {
  if (card.status === 'pass') return `All ${card.total} checks passed`
  const problems = card.checks.filter(c => c.status === 'fail').length
  const warnings = card.checks.filter(c => c.status === 'warn').length
  const parts = [problems && `${problems} to fix`, warnings && `${warnings} to check`].filter(Boolean)
  return `${card.passed} of ${card.total} checks passed: ${parts.join(', ')}`
}

/** The commands as one block for QA: a heading per row, then the command and where to run it. */
export function commandsAsText(commands: IrpCommand[]): string {
  const lines: string[] = []
  let row = ''
  for (const command of commands) {
    if (command.row !== row) {
      row = command.row
      lines.push(`# ${row}`)
    }
    lines.push(`${command.where ? `[${command.where}] ` : ''}${command.text}`)
  }
  return lines.join('\n')
}

export const LANGUAGE_LABEL: Record<IrpCommand['language'], string> = { kql: 'KQL', cli: 'CLI', powershell: 'PowerShell' }

/** Commands with a known problem first, so QA starts with them. */
export function commandsByRisk(commands: IrpCommand[]): IrpCommand[] {
  const weight = (c: IrpCommand) => (c.issues.some(i => i.severity === 'fail') ? 0 : c.issues.length ? 1 : 2)
  return [...commands].sort((a, b) => weight(a) - weight(b))
}
