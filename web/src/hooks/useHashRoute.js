import { useEffect, useMemo, useState } from 'react'

function parseHash() {
  const h = (window.location.hash || '#/dashboard').slice(1)
  const path = h.startsWith('/') ? h : `/${h}`
  return path || '/dashboard'
}

export function useHashRoute() {
  const [path, setPath] = useState(() => parseHash())

  useEffect(() => {
    const onChange = () => setPath(parseHash())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return useMemo(() => ({ path }), [path])
}

