import { Check, Loader2, MessageSquareWarning } from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, type Job } from '../api'
import Modal from './Modal'

interface Props {
  job: Job
  title: string
  onClose: () => void
  onDecided: () => void
}

const RUBRIC_LABELS: Record<string, string> = {
  loudness_consistency: 'Loudness consistency',
  noise_clarity: 'Noise & clarity',
  silence_pacing: 'Silence & pacing',
  transitions: 'Transitions',
  technical_compliance: 'Technical compliance',
}

export default function ApprovalModal({ job, title, onClose, onDecided }: Props) {
  const gate = job.gate
  const [asking, setAsking] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (!gate) return null
  const isScript = gate.type === 'script'

  async function decide(approved: boolean) {
    setBusy(true)
    setError('')
    try {
      await api.decide(job.id, approved, feedback.trim())
      onDecided()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send your decision.')
      setBusy(false)
    }
  }

  const footer = asking ? (
    <>
      <button className="btn ghost" disabled={busy} onClick={() => setAsking(false)}>Back</button>
      <button className="btn primary" disabled={busy || !feedback.trim()} onClick={() => void decide(false)}>
        {busy ? <Loader2 size={16} className="spin" /> : <MessageSquareWarning size={16} />} Send feedback
      </button>
    </>
  ) : (
    <>
      <button className="btn ghost" disabled={busy} onClick={() => setAsking(true)}>Request changes</button>
      <button className="btn primary" disabled={busy} onClick={() => void decide(true)}>
        {busy ? <Loader2 size={16} className="spin" /> : <Check size={16} />} {isScript ? 'Approve script' : 'Approve audio'}
      </button>
    </>
  )

  return (
    <Modal title={`${isScript ? 'Review the script' : 'Review the episode'} · ${title}`} onClose={onClose} wide footer={footer}>
      {gate.type === 'script' ? (
        <div className="script markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{gate.script}</ReactMarkdown></div>
      ) : (
        <div className="audio-review">
          <p className="muted">{gate.message || 'Listen to the episode, then approve it or ask for changes.'}</p>
          <audio controls preload="metadata" src={gate.audio_url} />
          {gate.rubric && <Rubric rubric={gate.rubric} />}
        </div>
      )}

      {asking && (
        <label className="feedback">
          <span>{isScript ? 'What should change in the script?' : 'What should change in the audio?'}</span>
          <textarea
            autoFocus
            rows={4}
            value={feedback}
            placeholder={isScript ? 'e.g. Open with the story, keep the intro shorter, cover the counter-argument.' : 'e.g. The expert is too quiet and the pause before the second segment is too long.'}
            onChange={(e) => setFeedback(e.target.value)}
          />
        </label>
      )}
      {error && <p className="notice bad" role="alert">{error}</p>}
    </Modal>
  )
}

function Rubric({ rubric }: { rubric: Record<string, number | string> }) {
  const scores = Object.entries(RUBRIC_LABELS).filter(([key]) => typeof rubric[key] === 'number')
  const evidence = typeof rubric.evidence === 'string' ? rubric.evidence : ''
  return (
    <div className="rubric">
      <h3>Quality check</h3>
      {scores.map(([key, label]) => {
        const score = rubric[key] as number
        return (
          <div key={key} className="score-row">
            <span>{label}</span>
            <div className="bar" aria-hidden="true"><i style={{ width: `${Math.max(0, Math.min(5, score)) * 20}%` }} /></div>
            <b>{score}/5</b>
          </div>
        )
      })}
      {evidence && <p className="muted small">{evidence}</p>}
    </div>
  )
}
