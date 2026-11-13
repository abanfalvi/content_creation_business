import { useRef } from 'react'

interface Props {
  value: string
  label: string
  className?: string
  onSave: (title: string) => void
  onCancel: () => void
}

export const MAX_TITLE = 120

/**
 * A text box for renaming. Enter or clicking away saves, Escape cancels. Nothing is sent when the name is
 * blank or unchanged. It appears in place of the title, so it focuses itself with the text selected.
 */
export default function TitleInput({ value, label, className, onSave, onCancel }: Props) {
  const finished = useRef(false) // Enter/Escape also blur the box; make sure that only counts once

  function finish(save: boolean, text: string) {
    if (finished.current) return
    finished.current = true
    const title = text.trim()
    if (save && title && title !== value) onSave(title)
    else onCancel()
  }

  return (
    <input
      className={`title-input${className ? ` ${className}` : ''}`}
      defaultValue={value}
      maxLength={MAX_TITLE}
      aria-label={label}
      autoFocus
      onFocus={(e) => e.currentTarget.select()}
      onClick={(e) => e.stopPropagation()}
      onBlur={(e) => finish(true, e.currentTarget.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
          e.preventDefault()
          finish(true, e.currentTarget.value)
        } else if (e.key === 'Escape') {
          e.preventDefault()
          e.stopPropagation() // do not also close a surrounding dialog or menu
          finish(false, e.currentTarget.value)
        }
      }}
    />
  )
}
