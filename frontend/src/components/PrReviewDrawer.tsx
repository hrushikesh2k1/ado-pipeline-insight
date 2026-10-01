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
} from 'lucide-react'
import type { AdoPullRequest, PullRequestReviewResponse, PullRequestReviewComment } from '../types/api'

interface PrReviewDrawerProps {
  reviewData: {
    pr: AdoPullRequest
    review: PullRequestReviewResponse
  }
  onClose: () => void
}

function getVerdictBadge(verdict: string) {
  switch (verdict) {
    case 'APPROVED':
      return {
        label: 'Approved',
        className: 'verdictApproved',
        icon: <CheckCircle2 size={13} />,
      }
    case 'APPROVED_WITH_SUGGESTIONS':
      return {
        label: 'Approved with Suggestions',
        className: 'verdictSuggestions',
        icon: <Sparkles size={13} />,
      }
    case 'CHANGES_REQUESTED':
      return {
        label: 'Changes Requested',
        className: 'verdictChanges',
        icon: <AlertTriangle size={13} />,
      }
    default:
      return {
        label: verdict.replace(/_/g, ' '),
        className: 'verdictNeutral',
        icon: <Info size={13} />,
      }
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

export const PrReviewDrawer: React.FC<PrReviewDrawerProps> = ({ reviewData, onClose }) => {
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
    let text = `### [${comment.severity.toUpperCase()}] ${comment.title}\n`
    if (comment.file_path) {
      text += `**File**: \`${comment.file_path}${comment.line_number ? `:${comment.line_number}` : ''}\`\n\n`
    }
    text += `${comment.comment}\n\n`
    if (comment.suggestion_code) {
      text += `\`\`\`suggestion\n${comment.suggestion_code}\n\`\`\`\n`
    }
    navigator.clipboard.writeText(text).then(() => {
      setCopiedId(comment.id)
      setTimeout(() => setCopiedId(null), 2000)
    })
  }

  const copyAllComments = () => {
    let fullText = `# AI PR Review for PR #${pr.id}: ${pr.title}\n`
    fullText += `**Verdict**: ${review.verdict}\n`
    fullText += `**Summary**: ${review.summary}\n\n`
    fullText += `## Review Comments\n\n`
    review.comments.forEach((c, idx) => {
      fullText += `### ${idx + 1}. [${c.severity.toUpperCase()}] ${c.title}\n`
      if (c.file_path) {
        fullText += `**File**: \`${c.file_path}${c.line_number ? `:${c.line_number}` : ''}\`\n\n`
      }
      fullText += `${c.comment}\n\n`
      if (c.suggestion_code) {
        fullText += `\`\`\`suggestion\n${c.suggestion_code}\n\`\`\`\n\n`
      }
    })
    navigator.clipboard.writeText(fullText).then(() => {
      setCopiedAll(true)
      setTimeout(() => setCopiedAll(false), 2000)
    })
  }

  return (
    <div className="drawerBackdrop" onClick={onClose}>
      <aside className="drawer prReviewDrawer" onClick={(e) => e.stopPropagation()}>
        {/* Drawer Header */}
        <div className="drawerHead prDrawerHead">
          <div>
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
            </div>
          </div>
          <button className="close" onClick={onClose} aria-label="Close Review Drawer">
            <X size={18} />
          </button>
        </div>

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
          <p>{review.summary}</p>
        </div>

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

        {/* Review Scorecard */}
        {review.scorecard && Object.keys(review.scorecard).length > 0 && (
          <div className="prScorecardSection">
            <span className="prSectionTitle">Review Scorecard</span>
            <div className="prScorecardGrid">
              {Object.entries(review.scorecard).map(([dimension, score]) => (
                <div key={dimension} className="prScoreCard">
                  <span className="prScoreLabel">{dimension.replace(/_/g, ' ')}</span>
                  <span className={`prScoreValue ${getScoreBadgeClass(score)}`}>
                    {score.replace(/_/g, ' ')}
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
                  ? 'No code defects or regressions identified. All examined changes look clean and well-grounded.'
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
                            {comment.line_number ? `:${comment.line_number}` : ''}
                          </span>
                        </span>
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
