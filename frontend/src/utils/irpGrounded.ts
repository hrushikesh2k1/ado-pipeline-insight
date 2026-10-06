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

/** True for a query the AI wrote itself: a column or a table can be wrong in it even when the brackets balance. */
export const isAiWrittenQuery = (c: IrpCommand) => c.language === 'kql' && c.origin === 'ai-written'

export const ORIGIN_LABEL: Record<NonNullable<IrpCommand['origin']>, string> = {
  'alert-query': "The alert's own query",
  'alert-query-plus': 'The alert query, with operators added',
  'ai-written': 'Written by the AI',
}

/** The order QA should test in: known problems first, then queries the AI wrote, then the rest. */
export function commandsByRisk(commands: IrpCommand[]): IrpCommand[] {
  const weight = (c: IrpCommand) => (c.issues.some(i => i.severity === 'fail') ? 0 : c.issues.length ? 1 : isAiWrittenQuery(c) ? 2 : 3)
  return [...commands].sort((a, b) => weight(a) - weight(b))
}

/** 'PT10M' -> '10 minutes', 'PT2H' -> '2 hours', 'P1D' -> '1 day'; anything that is not an ISO 8601 duration is returned as it is. */
export function humanDuration(iso: string | null | undefined): string {
  const match = /^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/i.exec((iso ?? '').trim())
  if (!match || !match.slice(1).some(Boolean)) return iso ?? ''
  const units: Array<[string | undefined, string]> = [[match[1], 'day'], [match[2], 'hour'], [match[3], 'minute'], [match[4], 'second']]
  return units.filter(([n]) => n).map(([n, unit]) => `${Number(n)} ${unit}${Number(n) === 1 ? '' : 's'}`).join(' ')
}
