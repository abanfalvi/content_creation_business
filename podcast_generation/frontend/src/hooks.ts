import { useCallback, useEffect, useRef, useState } from 'react'

/** Fetch now and then every `ms`. `error` is true while the last attempt failed (e.g. server down). */
export function usePolling<T>(fetcher: () => Promise<T>, ms: number, initial: T) {
  const [data, setData] = useState<T>(initial)
  const [error, setError] = useState(false)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const refresh = useCallback(async () => {
    try {
      setData(await fetcherRef.current())
      setError(false)
    } catch {
      setError(true)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), ms)
    return () => clearInterval(timer)
  }, [refresh, ms])

  return { data, error, refresh }
}

/** useState that survives reloads (per-browser conveniences such as panel state and selection). */
export function usePersistentState<T>(key: string, initial: T) {
  const storageKey = `levelup:${key}`
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(storageKey)
      return raw === null ? initial : (JSON.parse(raw) as T)
    } catch {
      return initial
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(value))
    } catch {
      /* storage unavailable: keep working in memory */
    }
  }, [storageKey, value])
  return [value, setValue] as const
}

export function formatTime(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}
