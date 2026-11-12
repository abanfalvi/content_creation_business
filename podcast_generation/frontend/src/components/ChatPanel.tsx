import { ArrowUp, BookOpen, ChevronDown, MessageSquare, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, streamChat, type ChatMessage, type Session } from '../api'
import { usePersistentState } from '../hooks'

interface Props {
  selectedSlugs: string[]
}

const SUGGESTIONS = [
  'Summarize the key ideas',
  'What are the main arguments?',
  'Give me three insights worth turning into an episode',
]

export default function ChatPanel({ selectedSlugs }: Props) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = usePersistentState<string | null>('chatSession', null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [status, setStatus] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)

  const noSources = selectedSlugs.length === 0
  const active = sessions.find((s) => s.id === activeId)

  const loadSessions = useCallback(async () => {
    try {
      const list = await api.sessions()
      setSessions(list)
      return list
    } catch {
      return []
    }
  }, [])

  // Restore the last open chat (or the most recent one) on first load.
  useEffect(() => {
    void (async () => {
      const list = await loadSessions()
      const target = list.find((s) => s.id === activeId) ?? list[0]
      if (!target) return setActiveId(null)
      setActiveId(target.id)
      setMessages(await api.messages(target.id).catch(() => []))
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Follow the answer as it streams, unless the reader has scrolled up.
  useEffect(() => {
    const el = listRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [messages])

  // Close the chat list when clicking elsewhere.
  useEffect(() => {
    if (!menuOpen) return
    const close = (e: MouseEvent) => menuRef.current && !menuRef.current.contains(e.target as Node) && setMenuOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])

  // Grow the text box with its content.
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [input])

  const stopStreaming = () => {
    abortRef.current?.abort()
    abortRef.current = null
    setStreaming(false)
    setStatus('')
  }

  async function openSession(id: string) {
    stopStreaming()
    setMenuOpen(false)
    setActiveId(id)
    setMessages([])
    stickRef.current = true
    setMessages(await api.messages(id).catch(() => []))
  }

  async function newChat() {
    stopStreaming()
    setMenuOpen(false)
    if (activeId && messages.length === 0) return inputRef.current?.focus() // already a blank chat
    try {
      const session = await api.createSession()
      setSessions((list) => [session, ...list])
      setActiveId(session.id)
      setMessages([])
      setInput('')
      inputRef.current?.focus()
    } catch {
      /* server unreachable: the banner in the header already says so */
    }
  }

  async function removeSession(id: string) {
    try {
      await api.deleteSession(id)
    } catch {
      return
    }
    const list = await loadSessions()
    if (id === activeId) {
      if (list[0]) await openSession(list[0].id)
      else {
        stopStreaming()
        setActiveId(null)
        setMessages([])
      }
    }
  }

  const patchLast = (fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((list) => (list.length ? [...list.slice(0, -1), fn(list[list.length - 1])] : list))

  async function send(text = input) {
    text = text.trim()
    if (!text || streaming || noSources) return

    let sessionId = activeId
    if (!sessionId) {
      try {
        const session = await api.createSession()
        setSessions((list) => [session, ...list])
        setActiveId(session.id)
        sessionId = session.id
      } catch {
        return
      }
    }

    setInput('')
    stickRef.current = true
    setMessages((list) => [...list, { role: 'user', text }, { role: 'assistant', text: '' }])
    setStreaming(true)
    setStatus('Thinking…')
    const controller = new AbortController()
    abortRef.current = controller

    try {
      await streamChat(sessionId, text, selectedSlugs, (event) => {
        if (event.type === 'status') setStatus(event.text)
        else if (event.type === 'token') {
          setStatus('')
          patchLast((m) => ({ ...m, text: m.text + event.text }))
        } else if (event.type === 'sources') patchLast((m) => ({ ...m, sources: event.sources }))
        else if (event.type === 'error') patchLast((m) => ({ ...m, text: event.message, error: true }))
      }, controller.signal)
    } catch (e) {
      if (!controller.signal.aborted) patchLast((m) => ({ ...m, text: e instanceof Error ? e.message : 'Something went wrong.', error: true }))
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null
        setStreaming(false)
        setStatus('')
      }
      void loadSessions() // the first message names the chat
    }
  }

  return (
    <main className="panel chat" aria-label="Chat">
      <header className="panel-head chat-head">
        <div className="session-picker" ref={menuRef}>
          <button className="session-btn" aria-haspopup="listbox" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>
            <MessageSquare size={18} />
            <span className="session-title">{active?.title ?? 'New chat'}</span>
            <ChevronDown size={16} />
          </button>
          {menuOpen && (
            <div className="menu" role="listbox" aria-label="Chats">
              {sessions.length === 0 && <p className="muted menu-empty">No chats yet.</p>}
              {sessions.map((s) => (
                <div key={s.id} className={`menu-item${s.id === activeId ? ' current' : ''}`}>
                  <button className="menu-main" role="option" aria-selected={s.id === activeId} onClick={() => void openSession(s.id)}>
                    {s.title}
                  </button>
                  <button className="icon-btn danger" aria-label={`Delete chat ${s.title}`} title="Delete chat" onClick={() => void removeSession(s.id)}>
                    <Trash2 size={15} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
        <button className="btn ghost" onClick={() => void newChat()}>
          <Plus size={18} /> New chat
        </button>
      </header>

      <div
        className="messages"
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget
          stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
        }}
      >
        {messages.length === 0 ? (
          <div className="chat-empty">
            <BookOpen size={36} />
            <h3>{noSources ? 'Choose what to talk about' : 'Ask about your sources'}</h3>
            <p className="muted">
              {noSources
                ? 'Add a PDF and select at least one source on the left, then ask your questions here.'
                : 'Answers come only from the sources you have selected, with the passages they are based on.'}
            </p>
            {!noSources && (
              <div className="chips">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chip" onClick={() => void send(s)}>{s}</button>
                ))}
              </div>
            )}
          </div>
        ) : (
          messages.map((m, i) => {
            const last = i === messages.length - 1
            return m.role === 'user' ? (
              <div key={i} className="msg user"><p>{m.text}</p></div>
            ) : (
              <div key={i} className={`msg assistant${m.error ? ' error' : ''}`}>
                {m.text ? (
                  <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown></div>
                ) : (
                  last && streaming && <p className="muted status">{status || 'Thinking…'}</p>
                )}
                {m.text && last && streaming && status && <p className="muted status">{status}</p>}
                {m.sources && m.sources.length > 0 && (
                  <details className="citations">
                    <summary>{m.sources.length} {m.sources.length === 1 ? 'passage' : 'passages'} from your sources</summary>
                    <ul>
                      {m.sources.map((s, j) => (
                        <li key={j}>
                          <strong>{s.title}{s.chapter ? ` — ${s.chapter}` : ''}</strong>
                          <p>{s.snippet}{s.snippet.length >= 400 ? '…' : ''}</p>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )
          })
        )}
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); void send() }}>
        <textarea
          ref={inputRef}
          rows={1}
          value={input}
          disabled={noSources}
          placeholder={noSources ? 'Select at least one source to start chatting' : 'Ask a question about your sources'}
          aria-label="Message"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              void send()
            }
          }}
        />
        <span className="source-count">{selectedSlugs.length} {selectedSlugs.length === 1 ? 'source' : 'sources'}</span>
        <button type="submit" className="send" aria-label="Send" disabled={streaming || noSources || !input.trim()}>
          <ArrowUp size={20} />
        </button>
      </form>
    </main>
  )
}
