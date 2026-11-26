import { useEffect, useId, useMemo, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Citation } from '../api'

const MARKER = /\[\[([^[\]]+)\]\]/g
// A marker the model is still typing ("[[1a2b", "[[1a2b]"), or the first bracket of one.
const UNFINISHED = /\[\[[^[\]]*\]?$|\[$/

interface Numbered {
  n: number
  source?: Citation
}

/**
 * Turn the `[[ref]]` markers of an answer into numbered links (`[1](#cite-1)`).
 * Passages are numbered by first appearance, so the highest number is the count of distinct passages cited.
 * Once the answer is complete, a marker whose passage is unknown (an invented reference) is dropped.
 */
export function numberCitations(text: string, sources: Citation[] = [], streaming = false) {
  const byRef = new Map(sources.map((s) => [s.ref, s]))
  const order: string[] = []
  const body = (streaming ? text.replace(UNFINISHED, '') : text).replace(MARKER, (_, inner: string) =>
    inner
      .split(/[,;]/)
      .map((r) => r.trim())
      .filter((ref) => ref && (streaming || byRef.has(ref)))
      .map((ref) => {
        let n = order.indexOf(ref) + 1
        if (!n) n = order.push(ref)
        return `[${n}](#cite-${n})`
      })
      .join(''),
  )
  const cited: Numbered[] = order.map((ref, i) => ({ n: i + 1, source: byRef.get(ref) }))
  return { body, cited }
}

interface Props {
  text: string
  sources?: Citation[]
  streaming: boolean
}

export default function CitedAnswer({ text, sources, streaming }: Props) {
  const { body, cited } = useMemo(() => numberCitations(text, sources, streaming), [text, sources, streaming])

  const components = useMemo<Components>(
    () => ({
      a({ node: _node, href, children, ...rest }) {
        const n = href?.match(/^#cite-(\d+)$/)?.[1]
        if (n) return <CitationBadge n={Number(n)} source={cited[Number(n) - 1]?.source} />
        return <a href={href} {...rest}>{children}</a>
      },
    }),
    [cited],
  )

  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{body}</ReactMarkdown>
    </div>
  )
}

const label = (s: Citation) => `${s.title}${s.chapter ? ` — ${s.chapter}` : ''}`

/** The grey numbered bubble. Hovering (or focusing) it shows the whole passage so the claim can be checked. */
function CitationBadge({ n, source }: { n: number; source?: Citation }) {
  const button = useRef<HTMLButtonElement>(null)
  const popover = useRef<HTMLDivElement>(null)
  const timer = useRef<number | undefined>(undefined)
  const id = useId()
  const [place, setPlace] = useState<CSSProperties | null>(null)

  const show = () => {
    window.clearTimeout(timer.current)
    const el = button.current
    if (!el || !source) return
    const r = el.getBoundingClientRect()
    const width = Math.min(440, window.innerWidth - 24)
    const left = Math.min(Math.max(r.left + r.width / 2 - width / 2, 12), window.innerWidth - width - 12)
    const above = r.top - 18
    const below = window.innerHeight - r.bottom - 18
    setPlace(
      above > below
        ? { left, width, bottom: window.innerHeight - r.top + 6, maxHeight: Math.min(380, above) }
        : { left, width, top: r.bottom + 6, maxHeight: Math.min(380, below) },
    )
  }
  const hideSoon = () => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setPlace(null), 120) // lets the pointer cross the gap into the popover
  }

  useEffect(() => () => window.clearTimeout(timer.current), [])

  // The popover is fixed-positioned: close it when the page moves under it, or on a tap elsewhere (touch has no hover).
  useEffect(() => {
    if (!place) return
    const inside = (t: EventTarget | null) => t instanceof Node && (popover.current?.contains(t) || button.current?.contains(t))
    const close = () => setPlace(null)
    const onScroll = (e: Event) => inside(e.target) || close()
    const onPointer = (e: PointerEvent) => inside(e.target) || close()
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', close)
    document.addEventListener('pointerdown', onPointer)
    return () => {
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', close)
      document.removeEventListener('pointerdown', onPointer)
    }
  }, [place])

  return (
    <>
      <button
        ref={button}
        type="button"
        className={`cite-badge${source ? '' : ' plain'}`}
        aria-label={source ? `Source ${n}: ${label(source)}` : `Source ${n}`}
        aria-expanded={place ? true : undefined}
        aria-describedby={place ? id : undefined}
        onMouseEnter={show}
        onMouseLeave={hideSoon}
        onFocus={show}
        onBlur={hideSoon}
        onClick={show}
        onKeyDown={(e) => e.key === 'Escape' && setPlace(null)}
      >
        {n}
      </button>
      {place && source && createPortal(
        <div ref={popover} id={id} role="tooltip" className="cite-pop" style={place} onMouseEnter={() => window.clearTimeout(timer.current)} onMouseLeave={hideSoon}>
          <div className="cite-pop-head">
            <strong>{label(source)}</strong>
            {source.kind === 'summary' && <span className="cite-tag">Summary</span>}
            {source.url && <a className="cite-link" href={source.url} target="_blank" rel="noreferrer">Watch ↗</a>}
          </div>
          <p>{source.text}</p>
        </div>,
        document.body,
      )}
    </>
  )
}
