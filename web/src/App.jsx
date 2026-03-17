import './App.css'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useEffect, useMemo, useState } from 'react'
import { useHashRoute } from './hooks/useHashRoute'
import { useRaspwatchSocket } from './hooks/useRaspwatchSocket'
import { clamp, formatBytes } from './lib/format'

function App() {
  const { path } = useHashRoute()
  const { connected, lastMessageTs, metrics, api } = useRaspwatchSocket()

  const stale = useMemo(() => {
    if (!lastMessageTs) return true
    return Date.now() - lastMessageTs > 10_000
  }, [lastMessageTs])

  useEffect(() => {
    // theme: keep in sync with localStorage key from legacy UI
    try {
      const raw = localStorage.getItem('raspwatch_settings')
      const s = raw ? JSON.parse(raw) : null
      const theme = s?.theme || 'system'
      const effective =
        theme === 'light'
          ? 'light'
          : theme === 'dark'
            ? 'dark'
            : window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches
              ? 'light'
              : 'dark'
      document.documentElement.setAttribute('data-theme', effective === 'light' ? 'light' : 'dark')
    } catch (e) {}
  }, [])

  if (path === '/overlay') {
    return (
      <div className="app overlay">
        <div className="overlayMain">
          <OverlayBlock label="CPU" value={metrics?.cpu?.usage_percent != null ? `${metrics.cpu.usage_percent} %` : '—'} />
          <OverlayBlock label="RAM" value={metrics?.memory?.usage_percent != null ? `${metrics.memory.usage_percent} %` : '—'} />
          <OverlayBlock label="Temp" value={metrics?.temperature?.cpu != null ? `${metrics.temperature.cpu} °C` : '—'} />
          <OverlayBlock label="Disk" value={metrics?.disk?.usage_percent != null ? `${metrics.disk.usage_percent} %` : '—'} />
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="header">
        <div className="logo">
          <span className="logoDot" />
          <h1>RaspWatch</h1>
        </div>
        <nav className="nav">
          <a className={cx('navLink', path === '/dashboard' && 'navLinkActive')} href="#/dashboard">
            Dashboard
          </a>
          <a className={cx('navLink', path === '/stats' && 'navLinkActive')} href="#/stats">
            Stats
          </a>
          <a className={cx('navLink', path === '/overlay' && 'navLinkActive')} href="#/overlay">
            Overlay
          </a>
        </nav>
        <div className="headerMeta">
          <span className={cx('statusDot', connected && !stale ? 'statusDotLive' : 'statusDotErr')} />
          <span>{connected && !stale ? 'LIVE' : 'OFFLINE'}</span>
        </div>
      </header>

      {path === '/stats' ? <Stats metrics={metrics} /> : <Dashboard metrics={metrics} onAckAlerts={() => api.ackAlerts()} />}

      <footer className="footer">RaspWatch · WebSocket + SSE ready</footer>
    </div>
  )
}

export default App

function cx(...parts) {
  return parts.filter(Boolean).join(' ')
}

function pctBarClass(pct) {
  const n = Number(pct)
  if (Number.isNaN(n)) return ''
  if (n >= 90) return 'barFillDanger'
  if (n >= 75) return 'barFillWarn'
  return ''
}

function Card({ title, children }) {
  return (
    <section className="card">
      <h2 className="cardTitle">{title}</h2>
      <div className="mono">{children}</div>
    </section>
  )
}

function Gauge({ value, pct }) {
  const n = clamp(Number(pct) || 0, 0, 100)
  return (
    <div>
      <div className="gaugeValue">{value}</div>
      <div className="bar">
        <div className={cx('barFill', pctBarClass(n))} style={{ width: `${n}%` }} />
      </div>
    </div>
  )
}

function Dashboard({ metrics, onAckAlerts }) {
  const cpu = metrics?.cpu || {}
  const load = metrics?.load || {}
  const mem = metrics?.memory || {}
  const swap = metrics?.swap || {}
  const disk = metrics?.disk || {}
  const diskIo = metrics?.disk_io || {}
  const temp = metrics?.temperature || {}
  const uptime = metrics?.uptime || {}
  const net = metrics?.network || {}

  const unack = metrics?.alerts_active_unacknowledged || metrics?.alerts_active || []
  const active = metrics?.alerts_active || []

  return (
    <main className="grid">
      <Card title="CPU">
        <Gauge value={cpu.usage_percent != null ? `${cpu.usage_percent} %` : '—'} pct={cpu.usage_percent} />
        <div className="meta">Load: {fmt(load.load_1, 2)} {fmt(load.load_5, 2)} {fmt(load.load_15, 2)} · {cpu.cores ?? '—'} cores</div>
      </Card>
      <Card title="RAM">
        <Gauge value={mem.usage_percent != null ? `${mem.usage_percent} %` : '—'} pct={mem.usage_percent} />
        <div className="meta">{mem.used_mb ?? '—'} / {mem.total_mb ?? '—'} MB</div>
      </Card>
      <Card title="Swap">
        <Gauge value={swap.usage_percent != null ? `${swap.usage_percent} %` : '—'} pct={swap.usage_percent} />
        <div className="meta">{swap.used_mb ?? '—'} / {swap.total_mb ?? '—'} MB</div>
      </Card>
      <Card title="Disk">
        <Gauge value={disk.usage_percent != null ? `${disk.usage_percent} %` : '—'} pct={disk.usage_percent} />
        <div className="meta">{disk.used_gb ?? '—'} / {disk.total_gb ?? '—'} GB</div>
      </Card>
      <Card title="Disk I/O">
        <div className="rows">
          <div className="row"><span>Read</span><strong>{diskIo.read_mb != null ? `${diskIo.read_mb} MB` : '—'}</strong></div>
          <div className="row"><span>Write</span><strong>{diskIo.write_mb != null ? `${diskIo.write_mb} MB` : '—'}</strong></div>
        </div>
      </Card>
      <Card title="Temperature">
        <div className="rows">
          <div className="row"><span>CPU</span><strong>{temp.cpu != null ? `${temp.cpu} °C` : '—'}</strong></div>
          <div className="row"><span>PMIC</span><strong>{temp.pmic != null ? `${temp.pmic} °C` : '—'}</strong></div>
          <div className="row"><span>RP1</span><strong>{temp.rp1 != null ? `${temp.rp1} °C` : '—'}</strong></div>
        </div>
      </Card>
      <Card title="Uptime">
        <div className="gaugeValue">{uptime.formatted ?? '—'}</div>
        <div className="meta">{uptime.seconds != null ? `${uptime.seconds}s` : ''}</div>
      </Card>
      <Card title="Network">
        <div className="rows">
          <div className="row"><span>RX</span><strong>{formatBytes(net.rx_bytes)}</strong></div>
          <div className="row"><span>TX</span><strong>{formatBytes(net.tx_bytes)}</strong></div>
        </div>
      </Card>
      <Card title="Alerts">
        <div className="rows">
          <div className="row"><span>Active</span><strong style={{ color: active.length ? 'var(--danger)' : 'var(--success)' }}>{active.length}</strong></div>
          <div className="row"><span>Unacked</span><strong style={{ color: unack.length ? 'var(--warn)' : 'var(--success)' }}>{unack.length}</strong></div>
        </div>
        <div className="meta" style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <button onClick={onAckAlerts} style={btnStyle(active.length ? 'var(--border)' : 'transparent')} disabled={!active.length}>
            Ack all
          </button>
        </div>
      </Card>
    </main>
  )
}

const btnStyle = (bg) => ({
  padding: '0.35rem 0.6rem',
  borderRadius: '8px',
  border: '1px solid var(--border)',
  background: bg,
  color: 'var(--text)',
  cursor: 'pointer',
})

function Stats({ metrics }) {
  const [history, setHistory] = useState([])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const r = await fetch('/api/history?period=1h')
        const j = await r.json()
        if (!cancelled) setHistory(Array.isArray(j?.data) ? j.data : [])
      } catch (e) {
        if (!cancelled) setHistory([])
      }
    }
    load()
    const t = window.setInterval(load, 15_000)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [])

  const chartData = useMemo(() => {
    return history.map((d) => ({
      t: new Date(d.ts * 1000).toLocaleTimeString(),
      cpu: d.cpu,
      mem: d.mem,
      temp: d.temp_cpu,
    }))
  }, [history])

  const cpuNow = metrics?.cpu?.usage_percent
  const memNow = metrics?.memory?.usage_percent
  const tempNow = metrics?.temperature?.cpu

  return (
    <main className="grid">
      <Card title="CPU (1h)">
        <div className="chartWrap">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <XAxis dataKey="t" hide />
              <YAxis hide domain={[0, 100]} />
              <Tooltip />
              <Line type="monotone" dataKey="cpu" stroke="var(--accent)" dot={false} strokeWidth={2} isAnimationActive />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="meta">Now: {cpuNow != null ? `${cpuNow} %` : '—'}</div>
      </Card>
      <Card title="RAM (1h)">
        <div className="chartWrap">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <XAxis dataKey="t" hide />
              <YAxis hide domain={[0, 100]} />
              <Tooltip />
              <Line type="monotone" dataKey="mem" stroke="var(--accent)" dot={false} strokeWidth={2} isAnimationActive />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="meta">Now: {memNow != null ? `${memNow} %` : '—'}</div>
      </Card>
      <Card title="Temp CPU (1h)">
        <div className="chartWrap">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <XAxis dataKey="t" hide />
              <YAxis hide />
              <Tooltip />
              <Line type="monotone" dataKey="temp" stroke="var(--warn)" dot={false} strokeWidth={2} isAnimationActive />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="meta">Now: {tempNow != null ? `${tempNow} °C` : '—'}</div>
      </Card>
    </main>
  )
}

function OverlayBlock({ label, value }) {
  return (
    <div className="overlayBlock">
      <div className="overlayLabel">{label}</div>
      <div className="overlayValue">{value}</div>
    </div>
  )
}

function fmt(n, digits = 1) {
  const x = Number(n)
  if (Number.isNaN(x)) return '—'
  return x.toFixed(digits)
}
