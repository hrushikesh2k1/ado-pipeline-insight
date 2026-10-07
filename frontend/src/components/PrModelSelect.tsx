import React from 'react'
import { Cpu } from 'lucide-react'
import type { PullRequestReviewModels, ReviewModelChoice } from '../types/api'
import { MODEL_LABEL, MODEL_NOT_SET_UP, MODEL_SELECT_TIP, MODEL_TIP } from '../utils/prReview'
import './PrReviewPanels.css'

interface PrModelSelectProps {
  /** What the server has set up. Nothing is shown until the server has answered and has a standard model. */
  models: PullRequestReviewModels | null | undefined
  value: ReviewModelChoice
  onChange: (choice: ReviewModelChoice) => void
  disabled?: boolean
  testId: string
}

/**
 * Which AI model reviews this one pull request: the standard one or the strong one (which the standard one backs up if it cannot answer).
 * The strong choice is always listed; until the server has a strong model it is greyed out and says so, instead of the selector being missing.
 */
export const PrModelSelect: React.FC<PrModelSelectProps> = ({ models, value, onChange, disabled = false, testId }) => {
  if (!models?.standard) return null
  const strongReady = Boolean(models.strong)
  return (
    <label className="prModelSelect" title={strongReady ? MODEL_SELECT_TIP : MODEL_NOT_SET_UP}>
      <Cpu size={13} aria-hidden="true" />
      <select
        value={strongReady ? value : 'standard'}
        disabled={disabled}
        aria-label="AI review model for this pull request"
        data-testid={testId}
        title={strongReady ? MODEL_TIP[value] : MODEL_NOT_SET_UP}
        onChange={(event) => onChange(event.target.value === 'strong' ? 'strong' : 'standard')}
      >
        <option value="standard">{MODEL_LABEL.standard} · {models.standard}</option>
        <option value="strong" disabled={!strongReady}>{MODEL_LABEL.strong} · {models.strong ?? 'not set up'}</option>
      </select>
    </label>
  )
}
