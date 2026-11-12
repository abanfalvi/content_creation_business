import { useEffect, useMemo, useState } from 'react'
import { api, type Source } from './api'
import AddSourcesModal from './components/AddSourcesModal'
import ChatPanel from './components/ChatPanel'
import SourcesPanel from './components/SourcesPanel'
import StudioPanel from './components/StudioPanel'
import { usePersistentState, usePolling } from './hooks'

const narrow = typeof window !== 'undefined' && window.innerWidth < 1000

export default function App() {
  const [leftOpen, setLeftOpen] = usePersistentState('leftOpen', !narrow)
  const [rightOpen, setRightOpen] = usePersistentState('rightOpen', !narrow)
  const [adding, setAdding] = useState(false)

  const { data: sources, error: offline, refresh } = usePolling(() => api.sources(), 2500, [] as Source[])

  // Which sources the chat and the studio work with. New sources are ticked as soon as they are ready.
  const [selected, setSelected] = usePersistentState<string[]>('selected', [])
  const [seen, setSeen] = usePersistentState<string[]>('seenReady', [])
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

  async function remove(source: Source) {
    if (!window.confirm(`Remove “${source.title}” from your sources?`)) return
    try {
      await api.deleteSource(source.slug)
      setSelected(selected.filter((s) => s !== source.slug))
      await refresh()
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Could not remove the source.')
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <img src="/logo.jpg" alt="" className="logo" />
        <h1>Level Up Lab</h1>
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
          onDelete={(s) => void remove(s)}
        />
        <ChatPanel selectedSlugs={selectedReady} />
        <StudioPanel open={rightOpen} onToggle={() => setRightOpen(!rightOpen)} sources={sources} selectedSlugs={selectedReady} />
      </div>

      {adding && <AddSourcesModal onClose={() => setAdding(false)} onUploaded={() => void refresh()} />}
    </div>
  )
}
