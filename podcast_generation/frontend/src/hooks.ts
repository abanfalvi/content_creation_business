import { useCallback, useEffect, useRef, useState } from 'react'

/** Poll quickly while something is in progress on the server, slowly otherwise. */
export const POLL_FAST = 2500
export const POLL_IDLE = 30000

/**
 * Fetch now and then repeatedly. `ms` is the interval, or a function of the latest data so the pace can
 * adapt (e.g. fast while a job runs, slow when idle). `error` is true while the last attempt failed (e.g.
 * server down). Call `refresh` after an action to update immediately instead of waiting for the next tick.
 */
export function usePolling<T>(fetcher: () => Promise<T>, ms: number | ((data: T) => number), initial: T) {
  const [data, setData] = useState<T>(initial)
  const [error, setError] = useState(false)
  const [loaded, setLoaded] = useState(false) // true once a fetch has succeeded, so `initial` is not mistaken for real data
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const refresh = useCallback(async () => {
    try {
      setData(await fetcherRef.current())
      setError(false)
      setLoaded(true)
    } catch {
      setError(true)
    }
  }, [])

  const delay = typeof ms === 'function' ? ms(data) : ms

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Restarts only when the delay changes, without an extra fetch each time.
  useEffect(() => {
    const timer = setInterval(() => void refresh(), delay)
    return () => clearInterval(timer)
  }, [refresh, delay])

  return { data, error, loaded, refresh }
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

/** Forget everything `usePersistentState` saved under keys that start with `prefix` (e.g. `<notebook id>:`). */
export function forgetPersistentState(prefix: string) {
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(`levelup:${prefix}`)) localStorage.removeItem(key)
    }
  } catch {
    /* storage unavailable: nothing was saved */
  }
}

export function formatTime(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}
