import { BookOpen, FileText, Loader2, MessageSquare, Mic, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { api, type Notebook } from '../api'
import ConfirmModal from '../components/ConfirmModal'
import TitleInput from '../components/TitleInput'
import { POLL_IDLE, forgetPersistentState, formatTime, usePolling } from '../hooks'
import { navigate, notebookHref } from '../router'

const count = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** The landing page: every notebook created so far, most recently used first. */
export default function HomePage() {
  // Counts only change while you are inside a notebook (or when a background job finishes), so a slow refresh is enough.
  const { data: notebooks, error: offline, loaded, refresh } = usePolling(() => api.notebooks(), POLL_IDLE, [] as Notebook[])
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<Notebook | null>(null) // the notebook the delete dialog is asking about
  const [error, setError] = useState('')

  async function create() {
    setCreating(true)
    setError('')
    try {
      const notebook = await api.createNotebook()
      navigate(notebookHref(notebook.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the notebook.')
      setCreating(false)
    }
  }

  async function rename(id: string, title: string) {
    setEditingId(null)
    setError('')
    try {
      await api.renameNotebook(id, title)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not rename the notebook.')
    }
  }

  // Errors are thrown to the confirm dialog, which shows them (e.g. "still being processed") and stays open.
  async function remove(n: Notebook) {
    await api.deleteNotebook(n.id)
    forgetPersistentState(`${n.id}:`)
    await refresh()
  }

  return (
    <div className="app">
      <header className="topbar">
        <img src="/logo.jpg" alt="" className="logo" />
        <h1>Level Up Lab</h1>
        {offline && <span className="offline" role="status">Can’t reach the server</span>}
      </header>

      <main className="home">
        <div className="home-inner">
          <div className="home-head">
            <h2>Your notebooks</h2>
            <button className="btn primary" disabled={creating} onClick={() => void create()}>
              {creating ? <Loader2 size={18} className="spin" /> : <Plus size={18} />} New notebook
            </button>
          </div>
          {error && <p className="notice bad" role="alert">{error}</p>}

          {!loaded ? (
            <p className="muted">{offline ? 'Can’t load your notebooks right now. Trying again…' : 'Loading…'}</p>
          ) : notebooks.length === 0 ? (
            <div className="empty">
              <BookOpen size={36} />
              <p>You have no notebooks yet.</p>
              <p className="muted">A notebook holds the sources you add, your chats about them and the episodes you make.</p>
            </div>
          ) : (
            <ul className="nb-grid">
              {notebooks.map((n) => (
                <li key={n.id} className="nb-card">
                  <div className="nb-top">
                    {editingId === n.id ? (
                      <TitleInput value={n.title} label="Notebook title" onSave={(t) => void rename(n.id, t)} onCancel={() => setEditingId(null)} />
                    ) : (
                      <>
                        <a className="nb-title" href={notebookHref(n.id)}>{n.title}</a>
                        <button className="icon-btn nb-action" aria-label={`Rename ${n.title}`} title="Rename" onClick={() => setEditingId(n.id)}>
                          <Pencil size={16} />
                        </button>
                        <button className="icon-btn danger nb-action" aria-label={`Delete ${n.title}`} title="Delete" onClick={() => setDeleting(n)}>
                          <Trash2 size={16} />
                        </button>
                      </>
                    )}
                  </div>
                  <div className="nb-stats muted">
                    <span><FileText size={15} /> {count(n.source_count, 'source')}</span>
                    <span><MessageSquare size={15} /> {count(n.chat_count, 'chat')}</span>
                    <span><Mic size={15} /> {count(n.episode_count, 'episode')}</span>
                  </div>
                  <span className="muted small">Last used {formatTime(n.updated_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>

      {deleting && (
        <ConfirmModal
          title="Delete notebook?"
          confirmLabel="Delete notebook"
          danger
          onConfirm={() => remove(deleting)}
          onClose={() => setDeleting(null)}
        >
          <p>
            <strong>{deleting.title}</strong> and everything in it will be permanently removed:{' '}
            {count(deleting.source_count, 'source')}, {count(deleting.chat_count, 'chat')} and {count(deleting.episode_count, 'episode')}.
          </p>
          <p className="muted">This cannot be undone.</p>
        </ConfirmModal>
      )}
    </div>
  )
}
