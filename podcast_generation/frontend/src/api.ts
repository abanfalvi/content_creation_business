// Types and calls for the Level Up Lab API (podcast_generation/api/routes.py).

export interface Notebook {
  id: string
  title: string
  created_at: number
  updated_at: number
  source_count: number
  chat_count: number
  episode_count: number
}

export type SourceStatus = 'processing' | 'ready' | 'failed'

export interface Source {
  slug: string
  title: string
  filename: string
  pages: number
  status: SourceStatus
  stage: string
  error: string
  created_at: number
}

export interface UploadResult {
  filename: string
  source: Source | null
  error: string | null
}

export interface Session {
  id: string
  title: string
  created_at: number
  updated_at: number
}

export interface Citation {
  title: string
  chapter: string
  snippet: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  sources?: Citation[]
  error?: boolean
}

export type Gate =
  | { type: 'script'; instructions: string; script: string }
  | { type: 'audio'; message: string; audio_url: string; rubric: Record<string, number | string> | null }

export type JobStatus = 'running' | 'awaiting_approval' | 'done' | 'failed'

export interface Job {
  id: string
  kind: 'generate' | 'publish'
  slug: string
  episode_id: string | null
  status: JobStatus
  stage: string
  gate: Gate | null
  result: Record<string, unknown> | null
  error: string
  activity: string
  created_at: number
  updated_at: number
}

export interface Episode {
  id: string
  slug: string
  title: string
  created_at: number
  published_at: number | null
  publish_result: string | null
  audio_url: string
}

export type ChatEvent =
  | { type: 'status'; text: string }
  | { type: 'token'; text: string }
  | { type: 'sources'; sources: Citation[] }
  | { type: 'done' }
  | { type: 'error'; message: string }

/** An error response from the API; `status` is the HTTP status (404 = it does not exist). */
export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function failure(res: Response): Promise<ApiError> {
  let detail = `${res.status} ${res.statusText}`
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') detail = body.detail
    else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join('; ')
  } catch {
    /* not JSON */
  }
  return new ApiError(detail, res.status)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init)
  if (!res.ok) throw await failure(res)
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

const patch = (body: unknown): RequestInit => ({ ...json(body), method: 'PATCH' })

export const api = {
  notebooks: () => request<Notebook[]>('/notebooks'),
  notebook: (id: string) => request<Notebook>(`/notebooks/${id}`),
  createNotebook: () => request<Notebook>('/notebooks', { method: 'POST' }),
  renameNotebook: (id: string, title: string) => request<Notebook>(`/notebooks/${id}`, patch({ title })),
  deleteNotebook: (id: string) => request<void>(`/notebooks/${id}`, { method: 'DELETE' }),

  // Everything below belongs to one notebook.
  sources: (notebookId: string) => request<Source[]>(`/notebooks/${notebookId}/sources`),
  uploadSources(notebookId: string, files: File[]) {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return request<UploadResult[]>(`/notebooks/${notebookId}/sources`, { method: 'POST', body: form })
  },
  deleteSource: (slug: string) => request<void>(`/sources/${encodeURIComponent(slug)}`, { method: 'DELETE' }),

  sessions: (notebookId: string) => request<Session[]>(`/notebooks/${notebookId}/chat/sessions`),
  createSession: (notebookId: string) => request<Session>(`/notebooks/${notebookId}/chat/sessions`, { method: 'POST' }),
  renameSession: (id: string, title: string) => request<Session>(`/chat/sessions/${id}`, patch({ title })),
  deleteSession: (id: string) => request<void>(`/chat/sessions/${id}`, { method: 'DELETE' }),
  messages: (id: string) => request<ChatMessage[]>(`/chat/sessions/${id}/messages`),

  generate: (sourceSlug: string) => request<Job>('/generate', json({ source_slug: sourceSlug })),
  jobs: (notebookId: string) => request<Job[]>(`/notebooks/${notebookId}/jobs`),
  decide: (jobId: string, approved: boolean, feedback = '') =>
    request<Job>(`/jobs/${jobId}/decision`, json({ approved, feedback })),

  episodes: (notebookId: string) => request<Episode[]>(`/notebooks/${notebookId}/episodes`),
  publish: (episodeId: string) => request<Job>(`/episodes/${episodeId}/publish`, { method: 'POST' }),
}

/** Ask a question and receive the answer as it is written (server-sent events over a POST). */
export async function streamChat(
  sessionId: string,
  message: string,
  sourceSlugs: string[],
  onEvent: (event: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/chat/sessions/${sessionId}/messages`, { ...json({ message, source_slugs: sourceSlugs }), signal })
  if (!res.ok || !res.body) throw await failure(res)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let end: number
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      const data = frame.split('\n').find((l) => l.startsWith('data: '))
      if (data) onEvent(JSON.parse(data.slice(6)) as ChatEvent)
    }
  }
}
