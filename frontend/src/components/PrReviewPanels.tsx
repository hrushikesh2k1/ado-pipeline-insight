import React from 'react'
import { CircleAlert, CircleCheck, CircleHelp, CircleX, FileCode, ListChecks, Info } from 'lucide-react'
import type { PullRequestChecklistCheck, PullRequestReviewedFile } from '../types/api'
import { CHECK_LABEL, checklistCounts, filesCounts } from '../utils/prReview'
import './PrReviewPanels.css'

const CHECK_ICON: Record<PullRequestChecklistCheck['status'], React.ReactNode> = {
  ok: <CircleCheck size={15} />,
  mismatch: <CircleX size={15} />,
  open: <CircleAlert size={15} />,
  unverifiable: <CircleHelp size={15} />,
}

/** The checklist in the description, set against what the pull request really contains. */
export const ChecklistCard: React.FC<{ checks: PullRequestChecklistCheck[] }> = ({ checks }) => {
  if (checks.length === 0) return null
  const counts = checklistCounts(checks)
  const checked = checks.filter(c => c.status !== 'unverifiable')
  const unverifiable = checks.filter(c => c.status === 'unverifiable')
  return (
    <section className="prp prpCard" data-testid="pr-checklist">
      <div className="prpHead">
        <div className="prpTitle"><ListChecks size={15} /> <span>PR checklist against the pull request</span></div>
        <span className="prpMuted">
          {counts.ok} match{counts.mismatch ? `, ${counts.mismatch} not` : ''}{counts.open ? `, ${counts.open} not done` : ''}{counts.unverifiable ? `, ${counts.unverifiable} can't be checked` : ''}
        </span>
      </div>
      {checked.length > 0 && (
        <ul className="prpChecks">
          {checked.map(check => (
            <li key={check.item} className={`prpCheck ${check.status}`} data-testid={`pr-check-${check.status}`}>
              <span className="prpCheckIcon">{CHECK_ICON[check.status]}</span>
              <div>
                <div className="prpCheckTitle">{check.item}{check.checked === null ? '' : <span className="prpMuted"> · {check.checked ? 'ticked' : 'not ticked'}</span>}</div>
                <div className="prpMuted"><b>{CHECK_LABEL[check.status]}:</b> {check.evidence}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {unverifiable.length > 0 && (
        <details className="prpMore" data-testid="pr-checklist-unverifiable">
          <summary>{unverifiable.length} item{unverifiable.length === 1 ? '' : 's'} this review can&apos;t verify</summary>
          <ul className="prpChecks">
            {unverifiable.map(check => (
              <li key={check.item} className="prpCheck unverifiable">
                <span className="prpCheckIcon">{CHECK_ICON.unverifiable}</span>
                <div>
                  <div className="prpCheckTitle">{check.item}{check.checked === null ? '' : <span className="prpMuted"> · {check.checked ? 'ticked' : 'not ticked'}</span>}</div>
                  <div className="prpMuted">{check.evidence}</div>
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}

/** Which files were read, which were not, and why. */
export const FilesCard: React.FC<{ files: PullRequestReviewedFile[] }> = ({ files }) => {
  if (files.length === 0) return null
  const { reviewed, skipped } = filesCounts(files)
  return (
    <details className="prp prpCard" data-testid="pr-files" open={skipped > 0 && reviewed === 0}>
      <summary className="prpSummary">
        <FileCode size={15} /> <span>What was reviewed: {reviewed} of {files.length} changed file{files.length === 1 ? '' : 's'}</span>
      </summary>
      <ul className="prpFiles">
        {files.map(file => (
          <li key={file.path} className={`prpFile ${file.status}`} data-testid={`pr-file-${file.status}`}>
            <code className="prpPath" title={file.path}>{file.path}</code>
            <span className="prpChip">{file.language ?? 'not read'}</span>
            <span className="prpChip">{file.change_type}</span>
            {file.status === 'reviewed'
              ? <span className="prpMuted">{file.findings === 0 ? 'no findings' : `${file.findings} finding${file.findings === 1 ? '' : 's'}`}</span>
              : <span className="prpMuted">not reviewed: {file.reason ?? 'unknown reason'}</span>}
            {file.purpose && <div className="prpPurpose">{file.purpose}</div>}
          </li>
        ))}
      </ul>
    </details>
  )
}

/** What the review had to leave out or remove, and the limit of what it can judge. */
export const NotesCard: React.FC<{ notes: string[]; scopeNote?: string }> = ({ notes, scopeNote }) => {
  if (notes.length === 0 && !scopeNote) return null
  return (
    <section className="prp prpCard" data-testid="pr-notes">
      {scopeNote && <p className="prpScope" data-testid="pr-scope-note"><Info size={14} /> <span>{scopeNote}</span></p>}
      {notes.length > 0 && (
        <ul className="prpNotes">
          {notes.map(note => <li key={note}>{note}</li>)}
        </ul>
      )}
    </section>
  )
}
