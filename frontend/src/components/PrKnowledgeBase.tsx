import React, { useState } from 'react'
import { BookOpen, ChevronDown, ChevronRight } from 'lucide-react'
import {
  KNOWLEDGE_EXAMPLE, KNOWLEDGE_HELP, KNOWLEDGE_MAX_CHARS, KNOWLEDGE_MAX_CHECKS, KNOWLEDGE_OPEN_KEY, knowledgeCount,
} from '../utils/prReview'
import './PrReviewPanels.css'

interface PrKnowledgeBaseProps {
  value: string
  onChange: (text: string) => void
}

function wasOpen(): boolean {
  try { return localStorage.getItem(KNOWLEDGE_OPEN_KEY) === 'true' } catch { return false }
}

/**
 * The user's own checks for every AI review: things they know go wrong often, or must always be looked at.
 * The text is kept in this browser and sent with each review; the review applies it to every pull request.
 */
export const PrKnowledgeBase: React.FC<PrKnowledgeBaseProps> = ({ value, onChange }) => {
  const [open, setOpen] = useState<boolean>(wasOpen)
  const count = knowledgeCount(value)

  const toggle = () => {
    setOpen(previous => {
      try { localStorage.setItem(KNOWLEDGE_OPEN_KEY, String(!previous)) } catch { /* storage blocked */ }
      return !previous
    })
  }

  return (
    <section className="prp prpCard prKnowledge" data-testid="pr-knowledge">
      <button type="button" className="prKnowledgeToggle" onClick={toggle} aria-expanded={open} data-testid="pr-knowledge-toggle">
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        <BookOpen size={15} />
        <span className="prKnowledgeTitle">Knowledge base: your checks for every AI review</span>
        <span className="prKnowledgeBadge" data-testid="pr-knowledge-badge">{count === 0 ? 'empty' : `${count} check${count === 1 ? '' : 's'}`}</span>
      </button>

      {open && (
        <div className="prKnowledgeBody">
          <p className="prpMuted" data-testid="pr-knowledge-help">{KNOWLEDGE_HELP}</p>
          <textarea
            className="prKnowledgeInput"
            data-testid="pr-knowledge-input"
            aria-label="Knowledge base: one check per line"
            rows={7}
            maxLength={KNOWLEDGE_MAX_CHARS}
            spellCheck={false}
            placeholder={KNOWLEDGE_EXAMPLE}
            value={value}
            onChange={event => onChange(event.target.value)}
          />
          <div className="prKnowledgeFoot">
            <span className="prpMuted" data-testid="pr-knowledge-count">
              {value.length} / {KNOWLEDGE_MAX_CHARS} characters · saved in this browser · the first {KNOWLEDGE_MAX_CHECKS} checks are used
            </span>
            <span className="prKnowledgeButtons">
              {!value.trim() && (
                <button type="button" className="prKnowledgeBtn" onClick={() => onChange(KNOWLEDGE_EXAMPLE)} data-testid="pr-knowledge-example">Insert an example</button>
              )}
              {value.trim() && (
                <button type="button" className="prKnowledgeBtn" onClick={() => onChange('')} data-testid="pr-knowledge-clear">Clear</button>
              )}
            </span>
          </div>
        </div>
      )}
    </section>
  )
}
