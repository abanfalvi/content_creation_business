import { ArrowLeft, Pencil } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, api, type Notebook, type Source } from '../api'
import AddSourcesModal from '../components/AddSourcesModal'
import ChatPanel from '../components/ChatPanel'
import ConfirmModal from '../components/ConfirmModal'
import MessageModal from '../components/MessageModal'
import SourcesPanel from '../components/SourcesPanel'
import StudioPanel from '../components/StudioPanel'
import TitleInput from '../components/TitleInput'
import { POLL_FAST, POLL_IDLE, usePersistentState, usePolling } from '../hooks'
import { homeHref } from '../router'

// Poll quickly only while a source is being processed; otherwise just a slow heartbeat (also keeps the offline banner honest).
const sourcesPace = (list: Source[]) => (list.some((s) => s.status === 'processing') ? POLL_FAST : POLL_IDLE)

const narrow = typeof window !== 'undefined' && window.innerWidth < 1000

/** One notebook: its sources, the chat about them and the studio. Mounted afresh for each notebook (see App). */
export default function NotebookPage({ id }: { id: string }) {
  // Panel layout is a per-browser preference shared by all notebooks.
  const [leftOpen, setLeftOpen] = usePersistentState('leftOpen', !narrow)
  const [rightOpen, setRightOpen] = usePersistentState('rightOpen', !narrow)
  const [adding, setAdding] = useState(false)

  const [notebook, setNotebook] = useState<Notebook | null>(null)
  const [missing, setMissing] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [removing, setRemoving] = useState<Source | null>(null) // the source the remove dialog is asking about
  const [problem, setProblem] = useState('') // an error to show in a dialog

  useEffect(() => {
    api.notebook(id).then(setNotebook).catch((e) => setMissing(e instanceof ApiError && e.status === 404))
  }, [id])

  async function rename(title: string) {
    setRenaming(false)
    try {
      setNotebook(await api.renameNotebook(id, title))
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not rename the notebook.')
    }
  }

  const { data: sources, error: offline, refresh } = usePolling(() => api.sources(id), sourcesPace, [] as Source[])

  // Which sources the chat and the studio work with. New sources are ticked as soon as they are ready.
  const [selected, setSelected] = usePersistentState<string[]>(`${id}:selected`, [])
  const [seen, setSeen] = usePersistentState<string[]>(`${id}:seenReady`, [])
  useEffect(() => {
    const fresh = sources.filter((s) => s.status === 'ready' && !seen.includes(s.slug)).map((s) => s.slug)
    if (fresh.length) {
      setSeen([...seen, ...fresh])
      setSelected([...selected, ...fresh])
    }
  }, [sources, seen, selected, setSeen, setSelected])

  const selectedReady = useMemo(
    () => sources.filter((s) => s.status === 'ready' && selected.includes(s.slug)).map((s) => s.slug),
    [sources, selected],
  )

  // Errors are thrown to the confirm dialog, which shows them and stays open.
  async function remove(source: Source) {
    await api.deleteSource(source.slug)
    setSelected(selected.filter((s) => s !== source.slug))
    await refresh()
  }

  if (missing) {
    return (
      <div className="app">
        <header className="topbar">
          <a className="icon-btn" href={homeHref} aria-label="All notebooks" title="All notebooks"><ArrowLeft size={20} /></a>
          <img src="/logo.jpg" alt="" className="logo" />
          <h1>Level Up Lab</h1>
        </header>
        <div className="page-empty">
          <h2>This notebook does not exist</h2>
          <p className="muted">It may have been removed, or the link is wrong.</p>
          <a className="btn primary" href={homeHref}>Back to all notebooks</a>
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <a className="icon-btn" href={homeHref} aria-label="All notebooks" title="All notebooks"><ArrowLeft size={20} /></a>
        <img src="/logo.jpg" alt="" className="logo" />
        {notebook &&
          (renaming ? (
            <TitleInput className="notebook-title-input" value={notebook.title} label="Notebook title" onSave={(t) => void rename(t)} onCancel={() => setRenaming(false)} />
          ) : (
            <h1 className="notebook-title">
              <button className="title-btn" title="Rename notebook" onClick={() => setRenaming(true)}>
                <span>{notebook.title}</span>
                <Pencil size={15} aria-hidden="true" />
              </button>
            </h1>
          ))}
        {offline && <span className="offline" role="status">Can’t reach the server</span>}
      </header>

      <div
        className="workspace"
        style={{ gridTemplateColumns: `${leftOpen ? 'var(--side-w)' : 'var(--rail-w)'} minmax(0, 1fr) ${rightOpen ? 'var(--side-w)' : 'var(--rail-w)'}` }}
      >
        <SourcesPanel
          open={leftOpen}
          onToggle={() => setLeftOpen(!leftOpen)}
          sources={sources}
          selected={selected}
          onSelectedChange={setSelected}
          onAdd={() => setAdding(true)}
          onDelete={setRemoving}
        />
        <ChatPanel notebookId={id} selectedSlugs={selectedReady} />
        <StudioPanel notebookId={id} open={rightOpen} onToggle={() => setRightOpen(!rightOpen)} sources={sources} selectedSlugs={selectedReady} />
      </div>

      {adding && <AddSourcesModal notebookId={id} onClose={() => setAdding(false)} onUploaded={() => void refresh()} />}
      {removing && (
        <ConfirmModal
          title="Remove source?"
          confirmLabel="Remove"
          danger
          onConfirm={() => remove(removing)}
          onClose={() => setRemoving(null)}
        >
          <p><strong>{removing.title}</strong> will be removed from this notebook.</p>
        </ConfirmModal>
      )}
      {problem && <MessageModal title="Something went wrong" message={problem} onClose={() => setProblem('')} />}
    </div>
  )
}
