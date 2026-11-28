import { AlertCircle, CheckCircle2, Loader2, Mic, PanelRightClose, PanelRightOpen, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api, type FormatInfo, type GenerateOptions, type Job, type Source } from '../api'
import { POLL_FAST, POLL_IDLE, formatTime, usePolling } from '../hooks'
import ApprovalModal from './ApprovalModal'
import GenerateModal from './GenerateModal'

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
  const [customizing, setCustomizing] = useState(false) // the "Customize podcast" dialog behind the Generate button

  // The formats are files on the server: load them once. If they cannot be loaded the dialog says so and the server
  // makes the episode in its default format.
  const [formats, setFormats] = useState<FormatInfo[]>([])
  useEffect(() => {
    let cancelled = false
    api.formats().then(
      (list) => {
        if (!cancelled) setFormats(list)
      },
      () => undefined,
    )
    return () => {
      cancelled = true
    }
  }, [])

  const titleOf = (slug: string) => sources.find((s) => s.slug === slug)?.title ?? slug
  // An episode is named after its sources and how it was asked for (`episode_title`). A combined episode has no
  // source of its own, so its title and members are stored on the job too.
  const jobTitle = (j: Job) => {
    if (typeof j.result?.episode_title === 'string') return j.result.episode_title
    return typeof j.result?.title === 'string' ? j.result.title : titleOf(j.slug)
  }
  const jobSources = (j: Job): string[] => (Array.isArray(j.result?.sources) ? (j.result.sources as string[]) : [j.slug])
  // The format an episode run was made in, shown for the ones that are not the default.
  const formatLabel = (j: Job) => {
    const f = formats.find((x) => x.id === j.result?.format)
    return f && !f.default ? f.label : ''
  }
  const isActive = (j: Job) => j.status === 'running' || j.status === 'awaiting_approval'
  const reviewJob = jobs.find((j) => j.id === reviewId && j.status === 'awaiting_approval') ?? null

  // A finished run adds an episode.
  const finished = jobs.filter((j) => j.status === 'done').length
  useEffect(() => void refreshEpisodes(), [finished, refreshEpisodes])

  // Selected sources an unfinished run already uses (on its own or as part of a combined episode).
  const busySelected = selectedSlugs.some((slug) => jobs.some((j) => j.kind === 'generate' && isActive(j) && jobSources(j).includes(slug)))
  const generateHint = useMemo(() => {
    if (selectedSlugs.length === 0) return 'Select a source to make an episode from it, or several to combine them into one episode.'
    if (busySelected) return selectedSlugs.length === 1 ? 'An episode is already being made from this source.' : 'An episode is already being made from one of these sources.'
    if (selectedSlugs.length > 1) return `One episode will be made from all ${selectedSlugs.length} selected sources.`
    return ''
  }, [selectedSlugs.length, busySelected])

  // Starts the episode from the dialog. A refusal (for example a source that is busy) is thrown back to the dialog,
  // which shows it and keeps what the user typed.
  async function generate(options: GenerateOptions) {
    await api.generate(selectedSlugs, options)
    await refreshJobs()
  }

  async function removeJob(id: string) {
    try {
      await api.deleteJob(id)
    } catch {
      return // the list refreshes below either way; a run that is already gone just disappears
    }
    await refreshJobs()
  }

  // Deleting an episode also removes the finished run that made it, so both lists are refreshed.
  async function removeEpisode(id: string) {
    try {
      await api.deleteEpisode(id)
    } catch {
      return
    }
    await Promise.all([refreshEpisodes(), refreshJobs()])
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

  // A failed run is not activity any more: it is listed with the episodes, where it can be removed.
  const visibleJobs = jobs.filter((j) => j.status !== 'failed').slice(0, 6)
  const failedJobs = jobs.filter((j) => j.status === 'failed')

  return (
    <aside className="panel" aria-label="Studio">
      <header className="panel-head">
        <h2>Studio</h2>
        <button className="icon-btn" aria-label="Close studio panel" title="Close studio" onClick={onToggle}>
          <PanelRightClose size={20} />
        </button>
      </header>

      <div className="studio-actions">
        <button className="btn action" disabled={selectedSlugs.length === 0 || busySelected} title={generateHint || 'Generate a podcast episode from the selected sources'} onClick={() => setCustomizing(true)}>
          <Mic size={20} /> Generate podcast
        </button>
      </div>
      {generateHint && <p className="muted small hint">{generateHint}</p>}

      {visibleJobs.length > 0 && (
        <section>
          <h3 className="section-title">Activity</h3>
          <ul className="cards">
            {visibleJobs.map((j) => (
              <li key={j.id} className={`card job ${j.status}`}>
                {j.status === 'awaiting_approval' && (
                  <button
                    className="alert-bubble"
                    aria-label={`Review the ${j.gate?.type === 'audio' ? 'audio' : 'script'} of ${jobTitle(j)}`}
                    title={`Needs your review: open the ${j.gate?.type === 'audio' ? 'audio' : 'script'}`}
                    onClick={() => setReviewId(j.id)}
                  >
                    !
                  </button>
                )}
                <div className="card-top">
                  <strong>Episode · {jobTitle(j)}</strong>
                  <StatusIcon status={j.status} />
                </div>
                {formatLabel(j) && <span className="muted small">{formatLabel(j)}</span>}
                {j.status === 'running' && <p className="muted small">{j.activity || 'Working'}…</p>}
                {j.status === 'awaiting_approval' && (
                  <p className="muted small">{j.gate?.type === 'audio' ? 'The audio' : 'The script'} is ready for your review.</p>
                )}
                {j.status === 'done' && (
                  <p className="muted small">Episode ready — find it below.</p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3 className="section-title">Episodes</h3>
        {episodes.length === 0 && failedJobs.length === 0 ? (
          <div className="empty compact">
            <p>Generated episodes will be saved here.</p>
            <p className="muted">Select one source and choose Generate podcast.</p>
          </div>
        ) : (
          <ul className="cards">
            {failedJobs.map((j) => (
              <li key={j.id} className="card job failed">
                <div className="card-top">
                  <strong>{jobTitle(j)}</strong>
                  <span className="card-actions">
                    <AlertCircle size={16} className="bad" aria-label="Failed" />
                    <button className="icon-btn danger" aria-label={`Delete failed episode ${jobTitle(j)}`} title="Delete" onClick={() => void removeJob(j.id)}>
                      <Trash2 size={15} />
                    </button>
                  </span>
                </div>
                {formatLabel(j) && <span className="muted small">{formatLabel(j)}</span>}
                <p className="bad small">{j.error || 'Something went wrong.'}</p>
              </li>
            ))}
            {episodes.map((e) => (
              <li key={e.id} className="card">
                <div className="card-top">
                  <strong>{e.title}</strong>
                  <button className="icon-btn danger" aria-label={`Delete episode ${e.title}`} title="Delete" onClick={() => void removeEpisode(e.id)}>
                    <Trash2 size={15} />
                  </button>
                </div>
                <span className="muted small">{formatTime(e.created_at)}</span>
                <audio controls preload="none" src={e.audio_url} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {customizing && (
        <GenerateModal
          formats={formats}
          sourceCount={selectedSlugs.length}
          onClose={() => setCustomizing(false)}
          onGenerate={generate}
        />
      )}

      {reviewJob && (
        <ApprovalModal
          key={`${reviewJob.id}:${reviewJob.gate?.type}`}
          job={reviewJob}
          title={jobTitle(reviewJob)}
          onClose={() => setReviewId(null)}
          onDecided={() => void refreshJobs()}
        />
      )}
    </aside>
  )
}

function StatusIcon({ status }: { status: Job['status'] }) {
  if (status === 'running') return <Loader2 size={16} className="spin" aria-label="Running" />
  if (status === 'done') return <CheckCircle2 size={16} className="good" aria-label="Done" />
  if (status === 'failed') return <AlertCircle size={16} className="bad" aria-label="Failed" />
  return null // waiting for review: the card's red bubble says so
}
