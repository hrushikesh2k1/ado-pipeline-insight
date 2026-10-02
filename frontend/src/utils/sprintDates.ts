/** Sprint dates as Azure DevOps shows them: "October 1 - October 31". Dates are UTC calendar days (no timezone shift). */
export function formatSprintRange(start?: string | null, finish?: string | null, locale?: string): string | null {
  if (!start || !finish) return null
  const s = new Date(start)
  const f = new Date(finish)
  if (Number.isNaN(s.getTime()) || Number.isNaN(f.getTime())) return null
  const part = (d: Date) => `${d.toLocaleString(locale, { month: 'long', timeZone: 'UTC' })} ${d.getUTCDate()}`
  return `${part(s)} - ${part(f)}`
}

/** "20 work days remaining" (singular for 1); null when the backend could not work it out. */
export function formatWorkDaysRemaining(days?: number | null): string | null {
  if (days === undefined || days === null) return null
  return `${days} work day${days === 1 ? '' : 's'} remaining`
}

type Dated = { id?: string; start_date?: string | null; finish_date?: string | null }

/** Prefer the board's iteration, but take missing dates from the sprint list entry for the same sprint. */
export function withListedDates<T extends Dated>(board: T | null | undefined, listed: T | Dated | null | undefined): T | null {
  if (!board) return (listed as T | null | undefined) ?? null
  if (board.start_date && board.finish_date) return board
  return { ...board, start_date: board.start_date || listed?.start_date, finish_date: board.finish_date || listed?.finish_date }
}
