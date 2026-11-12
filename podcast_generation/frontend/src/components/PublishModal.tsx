import { CheckCircle2, Loader2, Send } from 'lucide-react'
import { useState } from 'react'
import { api, type Episode } from '../api'
import { formatTime } from '../hooks'
import Modal from './Modal'

interface Props {
  episodes: Episode[]
  onClose: () => void
  onPublished: () => void
}

export default function PublishModal({ episodes, onClose, onPublished }: Props) {
  const firstFree = episodes.find((e) => !e.published_at)
  const [selected, setSelected] = useState<string | null>(firstFree?.id ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function publish() {
    if (!selected) return
    setBusy(true)
    setError('')
    try {
      await api.publish(selected)
      onPublished()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start publishing.')
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Publish an episode"
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!selected || busy} onClick={() => void publish()}>
            {busy ? <Loader2 size={16} className="spin" /> : <Send size={16} />} Publish selected
          </button>
        </>
      }
    >
      {episodes.length === 0 ? (
        <div className="empty">
          <p>There is nothing to publish yet.</p>
          <p className="muted">Generate a podcast first, then come back to publish it.</p>
        </div>
      ) : (
        <>
          <p className="muted small">
            Pick the episode to publish. A social post (caption and image) is prepared from its script and scheduled.
          </p>
          <ul className="episode-pick" role="radiogroup" aria-label="Episodes">
            {episodes.map((e) => (
              <li key={e.id} className={`${selected === e.id ? 'current' : ''}${e.published_at ? ' published' : ''}`}>
                <label>
                  <input
                    type="radio"
                    name="episode"
                    checked={selected === e.id}
                    disabled={!!e.published_at}
                    onChange={() => setSelected(e.id)}
                  />
                  <span className="pick-main">
                    <strong>{e.title}</strong>
                    <span className="muted small">{formatTime(e.created_at)}</span>
                  </span>
                  {e.published_at && <span className="badge good"><CheckCircle2 size={13} /> Published</span>}
                </label>
                <audio controls preload="none" src={e.audio_url} />
              </li>
            ))}
          </ul>
        </>
      )}
      {error && <p className="notice bad" role="alert">{error}</p>}
    </Modal>
  )
}
