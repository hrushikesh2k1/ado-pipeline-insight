import React from 'react'
import { Cpu } from 'lucide-react'
import type { PullRequestReviewModels, ReviewModelChoice } from '../types/api'
import { MODEL_LABEL, MODEL_SELECT_TIP, MODEL_TIP } from '../utils/prReview'
import './PrReviewPanels.css'

interface PrModelSelectProps {
  /** What the server has set up; nothing is shown unless there is a strong model next to the standard one. */
  models: PullRequestReviewModels | null | undefined
  value: ReviewModelChoice
  onChange: (choice: ReviewModelChoice) => void
  disabled?: boolean
  testId: string
}

/** Which AI model reviews this one pull request: the standard one or the strong one (which the standard one backs up if it cannot answer). */
export const PrModelSelect: React.FC<PrModelSelectProps> = ({ models, value, onChange, disabled = false, testId }) => {
  if (!models?.strong || !models.standard) return null
  return (
    <label className="prModelSelect" title={MODEL_SELECT_TIP}>
      <Cpu size={13} aria-hidden="true" />
      <select
        value={value}
        disabled={disabled}
        aria-label="AI review model for this pull request"
        data-testid={testId}
        title={MODEL_TIP[value]}
        onChange={(event) => onChange(event.target.value === 'strong' ? 'strong' : 'standard')}
      >
        {(['standard', 'strong'] as const).map(choice => (
          <option key={choice} value={choice}>{MODEL_LABEL[choice]} · {models[choice]}</option>
        ))}
      </select>
    </label>
  )
}
