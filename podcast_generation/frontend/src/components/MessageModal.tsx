import Modal from './Modal'

interface Props {
  title: string
  message: string
  onClose: () => void
}

/** The app's own notice dialog (instead of the browser's alert box). */
export default function MessageModal({ title, message, onClose }: Props) {
  return (
    <Modal title={title} onClose={onClose} footer={<button className="btn primary" autoFocus onClick={onClose}>OK</button>}>
      <p>{message}</p>
    </Modal>
  )
}
