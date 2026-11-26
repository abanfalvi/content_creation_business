import { Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type Preference } from '../api'
import Modal from './Modal'

/** A free-form preference is stored as "other:<key>"; show just the key. */
const label = (attribute: string) => (attribute.startsWith('other:') ? attribute.slice(6) : attribute).replace(/_/g, ' ')

interface Props {
  notebookId: string
  onClose: () => void
}

/** What the assistant has remembered about how to answer, with a way to make it forget each item. */
export default function PreferencesModal({ notebookId, onClose }: Props) {
  const [items, setItems] = useState<Preference[] | null>(null)
  const [problem, setProblem] = useState('')

  useEffect(() => {
    api.preferences(notebookId).then(setItems, (e: unknown) => setProblem(e instanceof Error ? e.message : 'Could not load.'))
  }, [notebookId])

  async function forget(id: string) {
    try {
      await api.deletePreference(id)
      setItems((all) => all?.filter((p) => p.id !== id) ?? null)
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not remove it.')
    }
  }

  return (
    <Modal title="How I answer you" onClose={onClose}>
      {problem && <p className="notice bad" role="alert">{problem}</p>}
      {items?.length === 0 && (
        <p className="muted">Nothing saved yet. Tell the assistant how you like answers (for example "keep it short") and it will remember.</p>
      )}
      <ul className="pref-list">
        {items?.map((p) => (
          <li key={p.id} className="pref-item">
            <div className="pref-text">
              <strong>{label(p.attribute)}</strong>: {p.value}
              <span className="muted pref-meta">
                {p.scope === 'global' ? 'All notebooks' : 'This notebook'}
                {p.signal === 'implicit' && ' · inferred'}
              </span>
            </div>
            <button className="icon-btn danger" aria-label={`Forget ${label(p.attribute)}`} title="Forget" onClick={() => void forget(p.id)}>
              <Trash2 size={15} />
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  )
}
