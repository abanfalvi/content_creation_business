import { Check, Loader2, Mic } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { FormatInfo, GenerateOptions } from '../api'
import Modal from './Modal'

// The longest custom instructions or episode description the server accepts (MAX_INSTRUCTIONS there).
const MAX_TEXT = 1500

interface Props {
  formats: FormatInfo[] // what the server offers; the default one is preselected
  sourceCount: number // how many sources are selected: they all go into the one episode
  onClose: () => void
  onGenerate: (options: GenerateOptions) => Promise<void> // rejects with the reason the episode could not be started
}

/** The dialog behind "Generate podcast": pick a format, say what the episode should focus on, then start it. */
export default function GenerateModal({ formats, sourceCount, onClose, onGenerate }: Props) {
  const [formatId, setFormatId] = useState(() => formats.find((f) => f.default)?.id ?? '')
  const [instructions, setInstructions] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // The formats normally arrive before the dialog opens; if they come in late, still preselect the default.
  useEffect(() => {
    setFormatId((current) => current || formats.find((f) => f.default)?.id || '')
  }, [formats])

  const needsDescription = formats.find((f) => f.id === formatId)?.needs_description ?? false
  const missingDescription = needsDescription && description.trim() === ''

  async function submit() {
    setBusy(true)
    setError('')
    try {
      await onGenerate({
        format: formatId || undefined,
        instructions: instructions.trim(),
        formatDescription: needsDescription ? description.trim() : undefined,
      })
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the episode.')
      setBusy(false)
    }
  }

  const footer = (
    <>
      <button className="btn ghost" disabled={busy} onClick={onClose}>Cancel</button>
      <button className="btn primary" disabled={busy || missingDescription} title={missingDescription ? 'Describe the episode you want, or choose another format.' : undefined} onClick={() => void submit()}>
        {busy ? <Loader2 size={16} className="spin" /> : <Mic size={16} />} Generate
      </button>
    </>
  )

  return (
    <Modal title="Customize podcast" onClose={onClose} wide footer={footer}>
      <section>
        <h3 className="dialog-label">Format</h3>
        {formats.length > 0 ? (
          <div className="format-grid" role="radiogroup" aria-label="Format">
            {formats.map((f) => {
              const selected = f.id === formatId
              return (
                <label key={f.id} className={`format-card${selected ? ' selected' : ''}`}>
                  <input className="visually-hidden" type="radio" name="episode-format" value={f.id} checked={selected} onChange={() => setFormatId(f.id)} />
                  <span className="format-card-top">
                    <strong>{f.label}</strong>
                    <span className="format-check" aria-hidden="true">{selected && <Check size={14} />}</span>
                  </span>
                  <span className="format-desc">{f.description}</span>
                </label>
              )
            })}
          </div>
        ) : (
          <p className="muted small">The formats could not be loaded, so the episode will be made in the default format.</p>
        )}
      </section>

      <div className="dialog-row">
        <h3 className="dialog-label">Sources</h3>
        <span className="muted">{sourceCount} {sourceCount === 1 ? 'source' : 'sources'} selected</span>
      </div>

      {needsDescription && (
        <label className="field">
          <span className="dialog-label">Describe the episode you want</span>
          <textarea
            className="field-input"
            rows={4}
            maxLength={MAX_TEXT}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={'- Three short segments, one idea each\n- End on a single thing to try this week'}
            autoFocus
          />
        </label>
      )}

      <label className="field">
        <span className="dialog-label">What should the episode focus on? <span className="optional">(optional)</span></span>
        <textarea
          className="field-input"
          rows={4}
          maxLength={MAX_TEXT}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder={'- Explain the core idea for a complete beginner\n- Focus on the practical steps and skip the history'}
        />
      </label>

      {error && <p className="notice bad" role="alert">{error}</p>}
    </Modal>
  )
}
