import { useEffect, useMemo, useRef, useState } from 'react'

function getWsUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws`
}

export function useRaspwatchSocket() {
  const [connected, setConnected] = useState(false)
  const [lastMessageTs, setLastMessageTs] = useState(0)
  const [metrics, setMetrics] = useState(null)

  const wsRef = useRef(null)
  const retryRef = useRef({ timer: null, attempt: 0 })

  useEffect(() => {
    let cancelled = false

    const connect = () => {
      if (cancelled) return
      if (wsRef.current) return

      const ws = new WebSocket(getWsUrl())
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        retryRef.current.attempt = 0
      }
      ws.onclose = () => {
        wsRef.current = null
        setConnected(false)
        if (cancelled) return
        const attempt = Math.min(8, (retryRef.current.attempt || 0) + 1)
        retryRef.current.attempt = attempt
        const delay = Math.min(15_000, 500 * Math.pow(2, attempt))
        retryRef.current.timer = window.setTimeout(connect, delay)
      }
      ws.onerror = () => {
        try {
          ws.close()
        } catch (e) {}
      }
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          if (msg?.type === 'metrics') {
            setMetrics(msg.payload || null)
            setLastMessageTs(Date.now())
          }
        } catch (e) {}
      }
    }

    connect()

    return () => {
      cancelled = true
      if (retryRef.current.timer) window.clearTimeout(retryRef.current.timer)
      try {
        wsRef.current?.close()
      } catch (e) {}
      wsRef.current = null
    }
  }, [])

  const api = useMemo(() => {
    return {
      ackAlerts(keys) {
        const ws = wsRef.current
        if (!ws || ws.readyState !== WebSocket.OPEN) return
        ws.send(JSON.stringify(keys?.length ? { type: 'alerts:ack', keys } : { type: 'alerts:ack' }))
      },
    }
  }, [])

  return { connected, lastMessageTs, metrics, api }
}

