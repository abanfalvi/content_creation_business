import { AlertCircle, CheckCircle2, Loader2, Mic, PanelRightClose, PanelRightOpen, Send } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type Job, type Source } from '../api'
import { POLL_FAST, POLL_IDLE, formatTime, usePolling } from '../hooks'
import ApprovalModal from './ApprovalModal'
import PublishModal from './PublishModal'

// Jobs only change on their own while one is running. A job waiting for approval changes when the user decides,
// and that action refreshes immediately.
const jobsPace = (list: Job[]) => (list.some((j) => j.status === 'running') ? POLL_FAST : POLL_IDLE)

interface Props {
  notebookId: string
  open: boolean
  onToggle: () => void
  sources: Source[]
  selectedSlugs: string[] // ready sources currently ticked
}

export default function StudioPanel({ notebookId, open, onToggle, sources, selectedSlugs }: Props) {
  const { data: jobs, refresh: refreshJobs } = usePolling(() => api.jobs(notebookId), jobsPace, [] as Job[])
  // Episodes change only when a job finishes, which refreshes them below; this slow tick is just a safety net.
  const { data: episodes, refresh: refreshEpisodes } = usePolling(() => api.episodes(notebookId), POLL_IDLE, [])
  const [reviewId, setReviewId] = useState<string | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState('')
  const prompted = useRef(new Set<string>())

  const titleOf = (slug: string) => sources.find((s) => s.slug === slug)?.title ?? slug
  const isActive = (j: Job) => j.status === 'running' || j.status === 'awaiting_approval'
  const reviewJob = jobs.find((j) => j.id === reviewId && j.status === 'awaiting_approval') ?? null

  // Open the review dialog by itself the first time a run asks for a decision.
  useEffect(() => {
    for (const j of jobs) {
      const key = `${j.id}:${j.gate?.type}`
      if (j.status === 'awaiting_approval' && j.gate && !prompted.current.has(key)) {
        prompted.current.add(key)
        setReviewId(j.id)
        return
      }
    }
  }, [jobs])

  // A finished run adds an episode.
  const finished = jobs.filter((j) => j.status === 'done').length
  useEffect(() => void refreshEpisodes(), [finished, refreshEpisodes])

  const only = selectedSlugs.length === 1 ? selectedSlugs[0] : null
  const busyWithOnly = only !== null && jobs.some((j) => j.kind === 'generate' && j.slug === only && isActive(j))
  const generateHint = useMemo(() => {
    if (selectedSlugs.length === 0) return 'Select a source to make an episode from it.'
    if (selectedSlugs.length > 1) return 'An episode covers one book: select just one source.'
    if (busyWithOnly) return 'An episode is already being made from this source.'
    return ''
  }, [selectedSlugs.length, busyWithOnly])

  async function generate() {
    if (!only) return
    setError('')
    try {
      await api.generate(only)
      await refreshJobs()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the episode.')
    }
  }

  if (!open) {
    const waiting = jobs.filter((j) => j.status === 'awaiting_approval').length
    return (
      <aside className="panel rail" aria-label="Studio (collapsed)">
        <button className="icon-btn" aria-label="Open studio panel" title="Open studio" onClick={onToggle}>
          <PanelRightOpen size={20} />
        </button>
        {waiting > 0 && <span className="rail-count attention" title="Waiting for your review">{waiting}</span>}
      </aside>
    )
  }

  const visibleJobs = jobs.slice(0, 6)

  return (
    <aside className="panel" aria-label="Studio">
      <header className="panel-head">
        <h2>Studio</h2>
        <button className="icon-btn" aria-label="Close studio panel" title="Close studio" onClick={onToggle}>
          <PanelRightClose size={20} />
        </button>
      </header>

      <div className="studio-actions">
        <button className="btn action" disabled={!only || busyWithOnly} title={generateHint || 'Generate a podcast episode from the selected source'} onClick={() => void generate()}>
          <Mic size={20} /> Generate podcast
        </button>
        <button className="btn action" title="Choose a generated episode to publish" onClick={() => setPublishing(true)}>
          <Send size={20} /> Publish
        </button>
      </div>
      {generateHint && <p className="muted small hint">{generateHint}</p>}
      {error && <p className="notice bad" role="alert">{error}</p>}

      {visibleJobs.length > 0 && (
        <section>
          <h3 className="section-title">Activity</h3>
          <ul className="cards">
            {visibleJobs.map((j) => (
              <li key={j.id} className={`card job ${j.status}`}>
                <div className="card-top">
                  <strong>{j.kind === 'generate' ? 'Episode' : 'Publishing'} · {titleOf(j.slug)}</strong>
                  <StatusIcon status={j.status} />
                </div>
                {j.status === 'running' && <p className="muted small">{j.activity || 'Working'}…</p>}
                {j.status === 'awaiting_approval' && (
                  <button className="btn primary small-btn" onClick={() => setReviewId(j.id)}>
                    Review {j.gate?.type === 'audio' ? 'audio' : 'script'}
                  </button>
                )}
                {j.status === 'done' && (
                  <p className="muted small">
                    {j.kind === 'generate' ? 'Episode ready — find it below.' : String(j.result?.message ?? 'Published.')}
                  </p>
                )}
                {j.status === 'failed' && <p className="bad small">{j.error || 'Something went wrong.'}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3 className="section-title">Episodes</h3>
        {episodes.length === 0 ? (
          <div className="empty compact">
            <p>Generated episodes will be saved here.</p>
            <p className="muted">Select one source and choose Generate podcast.</p>
          </div>
        ) : (
          <ul className="cards">
            {episodes.map((e) => (
              <li key={e.id} className="card">
                <div className="card-top">
                  <strong>{e.title}</strong>
                  {e.published_at && <span className="badge good" title={e.publish_result ?? ''}><CheckCircle2 size={13} /> Published</span>}
                </div>
                <span className="muted small">{formatTime(e.created_at)}</span>
                <audio controls preload="none" src={e.audio_url} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {reviewJob && (
        <ApprovalModal
          key={`${reviewJob.id}:${reviewJob.gate?.type}`}
          job={reviewJob}
          title={titleOf(reviewJob.slug)}
          onClose={() => setReviewId(null)}
          onDecided={() => void refreshJobs()}
        />
      )}
      {publishing && (
        <PublishModal episodes={episodes} onClose={() => setPublishing(false)} onPublished={() => void refreshJobs()} />
      )}
    </aside>
  )
}

function StatusIcon({ status }: { status: Job['status'] }) {
  if (status === 'running') return <Loader2 size={16} className="spin" aria-label="Running" />
  if (status === 'done') return <CheckCircle2 size={16} className="good" aria-label="Done" />
  if (status === 'failed') return <AlertCircle size={16} className="bad" aria-label="Failed" />
  return <span className="badge attention">Needs review</span>
}
