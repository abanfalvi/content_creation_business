import { AlertCircle, FileText, Loader2, PanelLeftClose, PanelLeftOpen, Plus, Trash2 } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { Source } from '../api'

interface Props {
  open: boolean
  onToggle: () => void
  sources: Source[]
  selected: string[]
  onSelectedChange: (slugs: string[]) => void
  onAdd: () => void
  onDelete: (source: Source) => void
}

export default function SourcesPanel({ open, onToggle, sources, selected, onSelectedChange, onAdd, onDelete }: Props) {
  const selectAllRef = useRef<HTMLInputElement>(null)
  const ready = sources.filter((s) => s.status === 'ready')
  const chosen = ready.filter((s) => selected.includes(s.slug))
  const allChosen = ready.length > 0 && chosen.length === ready.length

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = chosen.length > 0 && !allChosen
  }, [chosen.length, allChosen])

  if (!open) {
    return (
      <aside className="panel rail" aria-label="Sources (collapsed)">
        <button className="icon-btn" aria-label="Open sources panel" title="Open sources" onClick={onToggle}>
          <PanelLeftOpen size={20} />
        </button>
        {chosen.length > 0 && <span className="rail-count" title={`${chosen.length} sources selected`}>{chosen.length}</span>}
      </aside>
    )
  }

  const toggle = (slug: string) =>
    onSelectedChange(selected.includes(slug) ? selected.filter((s) => s !== slug) : [...selected, slug])

  return (
    <aside className="panel" aria-label="Sources">
      <header className="panel-head">
        <h2>Sources</h2>
        <button className="icon-btn" aria-label="Close sources panel" title="Close sources" onClick={onToggle}>
          <PanelLeftClose size={20} />
        </button>
      </header>

      <button className="btn wide-btn" onClick={onAdd}>
        <Plus size={18} /> Add sources
      </button>

      {sources.length > 0 && (
        <label className="select-all">
          <span>Select all</span>
          <input
            ref={selectAllRef}
            type="checkbox"
            checked={allChosen}
            disabled={ready.length === 0}
            onChange={() => onSelectedChange(allChosen ? [] : ready.map((s) => s.slug))}
          />
        </label>
      )}

      {sources.length === 0 ? (
        <div className="empty">
          <FileText size={28} />
          <p>Saved sources will appear here.</p>
          <p className="muted">Add PDF books to start a conversation or make an episode.</p>
        </div>
      ) : (
        <ul className="source-list">
          {sources.map((s) => (
            <li key={s.slug} className={`source ${s.status}`}>
              <FileText size={20} className="source-icon" />
              <div className="source-main">
                <span className="source-title" title={s.title}>{s.title}</span>
                <span className="source-meta" title={s.status === 'failed' ? s.error : undefined}>
                  {s.status === 'ready' && `${s.pages} ${s.pages === 1 ? 'page' : 'pages'}`}
                  {s.status === 'processing' && `${s.stage || 'Processing'}…`}
                  {s.status === 'failed' && (s.error || 'Processing failed')}
                </span>
              </div>
              {s.status !== 'processing' && (
                <button className="icon-btn danger source-delete" aria-label={`Remove ${s.title}`} title="Remove" onClick={() => onDelete(s)}>
                  <Trash2 size={16} />
                </button>
              )}
              {s.status === 'processing' && <Loader2 size={18} className="spin" aria-label="Processing" />}
              {s.status === 'failed' && <AlertCircle size={18} className="bad" aria-label="Failed" />}
              {s.status === 'ready' && (
                <input
                  type="checkbox"
                  aria-label={`Use ${s.title}`}
                  checked={selected.includes(s.slug)}
                  onChange={() => toggle(s.slug)}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
