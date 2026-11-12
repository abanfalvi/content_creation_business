import { AlertCircle, CheckCircle2, FileUp, Loader2 } from 'lucide-react'
import { useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { api, type UploadResult } from '../api'
import Modal from './Modal'

interface Props {
  onClose: () => void
  onUploaded: () => void
}

export default function AddSourcesModal({ onClose, onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<UploadResult[]>([])
  const [error, setError] = useState('')

  async function upload(files: File[]) {
    if (files.length === 0 || busy) return
    setError('')
    const isPdf = (f: File) => f.name.toLowerCase().endsWith('.pdf')
    const rejected: UploadResult[] = files
      .filter((f) => !isPdf(f))
      .map((f) => ({ filename: f.name, source: null, error: 'Only PDF files can be added.' }))
    const pdfs = files.filter(isPdf)
    if (pdfs.length === 0) {
      setResults(rejected)
      return
    }

    setBusy(true)
    try {
      const uploaded = await api.uploadSources(pdfs)
      const all = [...rejected, ...uploaded]
      setResults(all)
      onUploaded()
      if (all.every((r) => !r.error)) setTimeout(onClose, 1000) // everything is on its way: get out of the way
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.')
    } finally {
      setBusy(false)
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    void upload(Array.from(e.dataTransfer.files))
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      inputRef.current?.click()
    }
  }

  return (
    <Modal title="Add sources" onClose={onClose}>
      <div
        className={`dropzone${dragging ? ' dragging' : ''}${busy ? ' busy' : ''}`}
        role="button"
        tabIndex={0}
        aria-label="Upload PDF files"
        onClick={() => inputRef.current?.click()}
        onKeyDown={onKey}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        {busy ? <Loader2 size={32} className="spin" /> : <FileUp size={32} />}
        <strong>{busy ? 'Uploading…' : 'Drag and drop PDF files here'}</strong>
        <span className="muted">{busy ? 'This can take a moment for large books.' : 'or click to choose files'}</span>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          hidden
          onChange={(e) => {
            void upload(Array.from(e.target.files ?? []))
            e.target.value = '' // allow choosing the same file again
          }}
        />
      </div>

      <p className="muted small">
        Each PDF is read, indexed and summarised automatically after it is uploaded. Long books take a few minutes; you
        can keep using the app meanwhile.
      </p>

      {error && <p className="notice bad" role="alert">{error}</p>}
      {results.length > 0 && (
        <ul className="upload-results">
          {results.map((r, i) => (
            <li key={`${r.filename}-${i}`} className={r.error ? 'bad' : 'good'}>
              {r.error ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
              <span className="name">{r.filename}</span>
              <span className="muted">{r.error ?? 'Processing started'}</span>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}
