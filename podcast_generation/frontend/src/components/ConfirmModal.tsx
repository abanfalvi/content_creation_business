import { Loader2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import Modal from './Modal'

interface Props {
  title: string
  children: ReactNode
  confirmLabel: string
  /** Style the confirm button as a destructive action. */
  danger?: boolean
  /** Runs when the user confirms. If it throws, the message is shown in the dialog and the dialog stays open. */
  onConfirm: () => Promise<void>
  onClose: () => void
}

/** The app's own "are you sure?" dialog (instead of the browser's confirm box). */
export default function ConfirmModal({ title, children, confirmLabel, danger, onConfirm, onClose }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function confirm() {
    setBusy(true)
    setError('')
    try {
      await onConfirm()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
      setBusy(false)
    }
  }

  return (
    <Modal
      title={title}
      onClose={busy ? () => {} : onClose}
      footer={
        <>
          <button className="btn ghost" autoFocus disabled={busy} onClick={onClose}>Cancel</button>
          <button className={`btn ${danger ? 'danger' : 'primary'}`} disabled={busy} onClick={() => void confirm()}>
            {busy && <Loader2 size={16} className="spin" />} {confirmLabel}
          </button>
        </>
      }
    >
      {children}
      {error && <p className="notice bad" role="alert">{error}</p>}
    </Modal>
  )
}
