import { useEffect, useState } from 'react'

// Hash routing: `#/` is the home page and `#/notebook/<id>` is a notebook. The server only ever serves
// index.html, so a refresh or a bookmarked link works without any server-side fallback.

export type Route = { page: 'home' } | { page: 'notebook'; id: string }

export const homeHref = '#/'
export const notebookHref = (id: string) => `#/notebook/${encodeURIComponent(id)}`

function parse(hash: string): Route {
  const match = /^#\/notebook\/([^/?#]+)/.exec(hash)
  return match ? { page: 'notebook', id: decodeURIComponent(match[1]) } : { page: 'home' }
}

export function navigate(href: string) {
  window.location.hash = href
}

export function useRoute(): Route {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return parse(hash)
}
