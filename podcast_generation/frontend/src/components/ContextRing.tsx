import type { ContextUsage } from '../api'

const SIZE = 28
const STROKE = 3.5
const RADIUS = (SIZE - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

const compact = (n: number) => (n >= 1_000_000 ? `${+(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`)

/** A ring that fills as the chat uses up the model's context window. */
export default function ContextRing({ usage }: { usage: ContextUsage }) {
  const fraction = usage.window > 0 ? Math.min(usage.used / usage.window, 1) : 0
  const percent = Math.round(fraction * 100)
  const level = fraction >= 0.9 ? 'bad' : fraction >= 0.7 ? 'warn' : ''
  const label = `Context ${percent}% full: ${compact(usage.used)} of ${compact(usage.window)} tokens`

  return (
    <span className={`context-ring ${level}`} role="img" aria-label={label} title={label}>
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} aria-hidden="true">
        <circle className="ring-track" cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} />
        <circle
          className="ring-fill"
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={CIRCUMFERENCE * (1 - fraction)}
          transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
        />
      </svg>
      <span className="ring-percent">{percent}%</span>
    </span>
  )
}
