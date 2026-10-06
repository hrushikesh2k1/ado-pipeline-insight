import React, { useState } from 'react'
import {
  X,
  ShieldCheck,
  Sparkles,
  AlertTriangle,
  CheckCircle2,
  Info,
  Copy,
  Check,
  FileCode,
  GitBranch,
  User,
  ThumbsUp,
  RefreshCw,
} from 'lucide-react'
import type { AdoPullRequest, PullRequestReviewResponse, PullRequestReviewComment } from '../types/api'
import { QUERY_NOT_RUN, SECOND_CHECK_AGREED, SECOND_CHECK_NOT_RUN, SECOND_CHECK_TIP, STATIC_CHECK, STATIC_CHECK_TIP, allCommentsAsMarkdown, commentAsMarkdown, isAboutQueries, lineLabel, lookedAtLine, scoreLabel, shortCommit, verdictLabel } from '../utils/prReview'
import { ChecklistCard, FilesCard, NotesCard } from './PrReviewPanels'

interface PrReviewDrawerProps {
  reviewData: {
    pr: AdoPullRequest
    review: PullRequestReviewResponse
  }
  onClose: () => void
  /** The branch has new commits since this review was made. */
  isStale?: boolean
  isReReviewing?: boolean
  onReReview?: () => void
  /** Why the last attempt to review again failed. */
  error?: string | null
}

function getVerdictBadge(verdict: string) {
  const label = verdictLabel(verdict)
  switch (verdict) {
    case 'APPROVED':
      return { label, className: 'verdictApproved', icon: <CheckCircle2 size={13} /> }
    case 'APPROVED_WITH_SUGGESTIONS':
      return { label, className: 'verdictSuggestions', icon: <Sparkles size={13} /> }
    case 'CHANGES_REQUESTED':
      return { label, className: 'verdictChanges', icon: <AlertTriangle size={13} /> }
    default:
      return { label, className: 'verdictNeutral', icon: <Info size={13} /> }
  }
}

function getSeverityBadge(severity: string) {
  switch (severity) {
    case 'critical':
      return {
        label: 'Critical',
        className: 'prSevCritical',
        icon: <AlertTriangle size={12} />,
      }
    case 'warning':
      return {
        label: 'Warning',
        className: 'prSevWarning',
        icon: <AlertTriangle size={12} />,
      }
    case 'suggestion':
      return {
        label: 'Suggestion',
        className: 'prSevSuggestion',
        icon: <Info size={12} />,
      }
    case 'praise':
      return {
        label: 'Praise',
        className: 'prSevPraise',
        icon: <ThumbsUp size={12} />,
      }
    default:
      return {
        label: severity,
        className: 'prSevDefault',
        icon: <Info size={12} />,
      }
  }
}

function getScoreBadgeClass(score: string) {
  switch (score) {
    case 'EXCELLENT':
      return 'scoreExcellent'
    case 'GOOD':
      return 'scoreGood'
    case 'NEEDS_IMPROVEMENT':
      return 'scoreNeedsImprovement'
    case 'CONCERNING':
      return 'scoreConcerning'
    default:
      return 'scoreNeutral'
  }
}

export const PrReviewDrawer: React.FC<PrReviewDrawerProps> = ({ reviewData, onClose, isStale = false, isReReviewing = false, onReReview, error = null }) => {
  const { pr, review } = reviewData
  const [severityFilter, setSeverityFilter] = useState<string>('all')
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [copiedAll, setCopiedAll] = useState<boolean>(false)

  const verdictBadge = getVerdictBadge(review.verdict)

  const counts = {
    all: review.comments.length,
    critical: review.comments.filter((c) => c.severity === 'critical').length,
    warning: review.comments.filter((c) => c.severity === 'warning').length,
    suggestion: review.comments.filter((c) => c.severity === 'suggestion').length,
    praise: review.comments.filter((c) => c.severity === 'praise').length,
  }

  const filteredComments = review.comments.filter((c) => {
    if (severityFilter === 'all') return true
    return c.severity === severityFilter
  })

  const copyComment = (comment: PullRequestReviewComment) => {
    navigator.clipboard.writeText(commentAsMarkdown(comment)).then(() => {
      setCopiedId(comment.id)
      setTimeout(() => setCopiedId(null), 2000)
    })
  }

  const copyAllComments = () => {
    navigator.clipboard.writeText(allCommentsAsMarkdown(pr, review)).then(() => {
      setCopiedAll(true)
      setTimeout(() => setCopiedAll(false), 2000)
    })
  }

  return (
    <div className="drawerBackdrop" onClick={onClose}>
      <aside className="drawer prReviewDrawer" onClick={(e) => e.stopPropagation()}>
        {/* Drawer Header */}
        <div className="drawerHead prDrawerHead">
          <div className="prDrawerTitleBlock">
            <div className="prDrawerTitleRow">
              <span className={`prVerdictBadge ${verdictBadge.className}`}>
                {verdictBadge.icon}
                <span>{verdictBadge.label}</span>
              </span>
              <h2>PR #{pr.id}: {pr.title}</h2>
            </div>
            <div className="prDrawerSub">
              <span className="prDrawerSubItem">
                <User size={12} />
                <span>{pr.created_by_name}</span>
              </span>
              <span className="prDrawerSubDot">•</span>
              <span className="prDrawerSubItem">
                <GitBranch size={12} />
                <span>{pr.source_branch} → {pr.target_branch}</span>
              </span>
              {review.source_commit && (
                <>
                  <span className="prDrawerSubDot">•</span>
                  <span className="prDrawerSubItem prCommitItem" data-testid="pr-review-commit" title="The commit that was reviewed">
                    reviewed <span className="prCommit">{shortCommit(review.source_commit)}</span>
                    {review.iterations ? ` (push ${review.iterations})` : ''}
                  </span>
                </>
              )}
            </div>
          </div>
          <div className="prDrawerActions">
            {onReReview && (
              <button type="button" className="prReReview" onClick={onReReview} disabled={isReReviewing} data-testid="pr-rereview">
                <RefreshCw size={12} className={isReReviewing ? 'spin' : ''} />
                <span>{isReReviewing ? 'Reviewing…' : 'Review again'}</span>
              </button>
            )}
            <button className="close" onClick={onClose} aria-label="Close Review Drawer">
              <X size={18} />
            </button>
          </div>
        </div>

        {error && (
          <div className="prStaleNote" data-testid="pr-review-error" role="alert">
            <AlertTriangle size={14} />
            <span>{error}</span>
          </div>
        )}

        {isStale && (
          <div className="prStaleNote" data-testid="pr-review-stale">
            <AlertTriangle size={14} />
            <span>The branch has new commits since this review. Review again to include them.</span>
          </div>
        )}

        {/* Local Review Notice Banner (Crucial Requirement: Comments Not Posted to PR) */}
        <div className="prLocalNoticeBanner">
          <ShieldCheck size={18} className="prNoticeIcon" />
          <div className="prNoticeText">
            <strong>Application Preview Only</strong>
            <p>
              These AI review comments are generated for review in ADO Pipeline Insight and <strong>are NOT posted to Azure DevOps</strong>.
            </p>
          </div>
        </div>

        {/* Executive Summary */}
        <div className="prExecutiveSummary">
          <div className="prSummaryHead">
            <Sparkles size={14} className="prSummaryIcon" />
            <h4>Executive Review Summary</h4>
          </div>
          <p data-testid="pr-review-summary">{review.summary}</p>
        </div>

        {/* What the review could not judge, and what it left out or removed */}
        <NotesCard notes={review.notes ?? []} scopeNote={review.scope_note} />

        {/* Review Inquiries & Process Notes (Cleanly separated from code findings) */}
        {review.clarifications && review.clarifications.length > 0 && (
          <div className="prClarificationsSection">
            <div className="prClarificationsHead">
              <Info size={14} className="prClarificationsIcon" />
              <h4>Review Clarifications & Process Notes</h4>
            </div>
            <ul className="prClarificationsList">
              {review.clarifications.map((item, idx) => (
                <li key={idx} className="prClarificationItem">
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* The checklist in the description, against what the pull request contains */}
        <ChecklistCard checks={review.checklist ?? []} />

        {/* Which files were read */}
        <FilesCard files={review.files ?? []} />

        {/* Review Scorecard */}
        {review.scorecard && Object.keys(review.scorecard).length > 0 && (
          <div className="prScorecardSection">
            <span className="prSectionTitle">Review Scorecard</span>
            <div className="prScorecardGrid">
              {Object.entries(review.scorecard).map(([dimension, score]) => (
                <div key={dimension} className="prScoreCard">
                  <span className="prScoreLabel">{dimension.replace(/_/g, ' ')}</span>
                  <span className={`prScoreValue ${getScoreBadgeClass(score)}`}>
                    {scoreLabel(score)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Comments Toolbar & Filter Pills */}
        <div className="prCommentsHeaderBar">
          <div className="prCommentFilterPills">
            <button
              type="button"
              className={`prFilterPill ${severityFilter === 'all' ? 'active' : ''}`}
              onClick={() => setSeverityFilter('all')}
            >
              All ({counts.all})
            </button>
            {counts.critical > 0 && (
              <button
                type="button"
                className={`prFilterPill pillCrit ${severityFilter === 'critical' ? 'active' : ''}`}
                onClick={() => setSeverityFilter('critical')}
              >
                Critical ({counts.critical})
              </button>
            )}
            {counts.warning > 0 && (
              <button
                type="button"
                className={`prFilterPill pillWarn ${severityFilter === 'warning' ? 'active' : ''}`}
                onClick={() => setSeverityFilter('warning')}
              >
                Warning ({counts.warning})
              </button>
            )}
            {counts.suggestion > 0 && (
              <button
                type="button"
                className={`prFilterPill pillSugg ${severityFilter === 'suggestion' ? 'active' : ''}`}
                onClick={() => setSeverityFilter('suggestion')}
              >
                Suggestion ({counts.suggestion})
              </button>
            )}
            {counts.praise > 0 && (
              <button
                type="button"
                className={`prFilterPill pillPraise ${severityFilter === 'praise' ? 'active' : ''}`}
                onClick={() => setSeverityFilter('praise')}
              >
                Praise ({counts.praise})
              </button>
            )}
          </div>

          <button
            type="button"
            className="prCopyAllBtn"
            onClick={copyAllComments}
            title="Copy all comments formatted as Markdown"
          >
            {copiedAll ? <Check size={13} /> : <Copy size={13} />}
            <span>{copiedAll ? 'Copied All!' : 'Copy All'}</span>
          </button>
        </div>

        {/* Review Comments Feed */}
        <div className="prCommentsFeed">
          {filteredComments.length === 0 ? (
            <div className="prEmptyFeed">
              <CheckCircle2 size={32} />
              <p>
                {counts.all === 0
                  ? review.verdict === 'NOT_REVIEWED'
                    ? 'Nothing was reviewed. See "What was reviewed" for the reason.'
                    : 'No findings in the files reviewed. This review reads the code changes only; run the result and look at it yourself.'
                  : `No comments found for filter "${severityFilter}".`}
              </p>
            </div>
          ) : (
            filteredComments.map((comment) => {
              const sevBadge = getSeverityBadge(comment.severity)
              const isCopied = copiedId === comment.id

              return (
                <div key={comment.id} className={`prCommentCard ${comment.severity}`}>
                  <div className="prCommentTop">
                    <div className="prCommentBadges">
                      <span className={`prSevBadge ${sevBadge.className}`}>
                        {sevBadge.icon}
                        <span>{sevBadge.label}</span>
                      </span>
                      <span className="prCategoryBadge">
                        {comment.category.replace(/_/g, ' ')}
                      </span>
                      {comment.file_path && (
                        <span className="prFileBadge" title={comment.file_path}>
                          <FileCode size={11} />
                          <span>
                            {comment.file_path}
                            {lineLabel(comment) ? `:${lineLabel(comment)}` : ''}
                          </span>
                        </span>
                      )}
                      {comment.existing_thread && (
                        <span className="prChip known" data-testid="pr-comment-known" title="People already raised this in the pull request comments">
                          {comment.existing_thread}
                        </span>
                      )}
                      {comment.source === 'static' && (
                        <span className="prChip checked" data-testid="pr-comment-static" title={STATIC_CHECK_TIP}>{STATIC_CHECK}</span>
                      )}
                      {comment.source !== 'static' && comment.verified === true && (
                        <span className="prChip checked" data-testid="pr-comment-checked" title={SECOND_CHECK_TIP}>{SECOND_CHECK_AGREED}</span>
                      )}
                      {comment.source !== 'static' && comment.verified == null && (
                        <span className="prChip" data-testid="pr-comment-unchecked" title="The second check did not run for this finding">{SECOND_CHECK_NOT_RUN}</span>
                      )}
                      {isAboutQueries(comment.language) && (
                        <span className="prChip" data-testid="pr-comment-query-note" title="Nobody has run this query or deployed this template, and the second check only reads the code">{QUERY_NOT_RUN}</span>
                      )}
                    </div>

                    <button
                      type="button"
                      className="prCopyCommentBtn"
                      onClick={() => copyComment(comment)}
                      title="Copy comment to clipboard"
                    >
                      {isCopied ? <Check size={12} color="#34d399" /> : <Copy size={12} />}
                      <span>{isCopied ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>

                  <h4 className="prCommentTitle">{comment.title}</h4>
                  <div className="prCommentBody">{comment.comment}</div>
                  {comment.failing_case && (
                    <div className="prCaseLine" data-testid="pr-comment-case"><b>Concrete case:</b> {comment.failing_case}</div>
                  )}
                  {comment.evidence && (
                    <div className="prCaseLine"><b>Code it relies on:</b> <code className="prEvidence">{comment.evidence}</code></div>
                  )}
                  {lookedAtLine(comment.checked_with) && (
                    <div className="prCaseLine" data-testid="pr-comment-looked"><b>Second check looked at:</b> {lookedAtLine(comment.checked_with)}</div>
                  )}

                  {comment.suggestion_code && (
                    <div className="prSuggestionBox">
                      <div className="prSuggestionHead">
                        <span>Suggested Remediation</span>
                        <button
                          type="button"
                          className="prCopySnippetBtn"
                          onClick={() => {
                            navigator.clipboard.writeText(comment.suggestion_code || '')
                            setCopiedId(comment.id + '-code')
                            setTimeout(() => setCopiedId(null), 2000)
                          }}
                        >
                          {copiedId === comment.id + '-code' ? (
                            <Check size={11} />
                          ) : (
                            <Copy size={11} />
                          )}
                          <span>
                            {copiedId === comment.id + '-code' ? 'Copied' : 'Copy Code'}
                          </span>
                        </button>
                      </div>
                      <pre className="prSuggestionCode">
                        <code>{comment.suggestion_code}</code>
                      </pre>
                      <p className="prSuggestionHint" data-testid="pr-suggestion-hint">
                        In Azure DevOps, select line{comment.end_line && comment.line_number && comment.end_line > comment.line_number ? 's' : ''} {lineLabel(comment)} of <code>{comment.file_path}</code>,
                        add a comment and paste the copied text: Apply Change then replaces exactly those lines.
                      </p>
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      </aside>
    </div>
  )
}
