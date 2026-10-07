import React from 'react'
import { Cpu } from 'lucide-react'
import type { PullRequestReviewModels, ReviewModelChoice } from '../types/api'
import { MODEL_HELP, MODEL_LABEL, MODEL_TIP } from '../utils/prReview'
import './PrReviewPanels.css'

interface PrModelSwitchProps {
  /** What the server has set up; the switch shows only when there is a strong model next to the standard one. */
  models: PullRequestReviewModels | null
  value: ReviewModelChoice
  onChange: (choice: ReviewModelChoice) => void
}

/** Which AI model reviews the next pull request: the standard one or the strong one (which the standard one backs up if it cannot answer). */
export const PrModelSwitch: React.FC<PrModelSwitchProps> = ({ models, value, onChange }) => {
  if (!models?.strong || !models.standard) return null
  return (
    <section className="prp prpCard prModelSwitch" data-testid="pr-model-switch">
      <span className="prModelTitle"><Cpu size={15} />AI review model</span>
      <div className="prModelOptions" role="radiogroup" aria-label="AI review model">
        {(['standard', 'strong'] as const).map(choice => (
          <button
            key={choice}
            type="button"
            role="radio"
            aria-checked={value === choice}
            className={`prModelOption${value === choice ? ' active' : ''}`}
            data-testid={`pr-model-${choice}`}
            title={MODEL_TIP[choice]}
            onClick={() => onChange(choice)}
          >
            <span>{MODEL_LABEL[choice]}</span>
            <span className="prModelName">{models[choice]}</span>
          </button>
        ))}
      </div>
      <span className="prpMuted" data-testid="pr-model-help">{MODEL_HELP}</span>
    </section>
  )
}
