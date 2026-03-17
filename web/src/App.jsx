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
          <a className={cx('navLink', path === '/alerts' && 'navLinkActive')} href="#/alerts">
            Alerts
          </a>
          <a className={cx('navLink', path === '/processes' && 'navLinkActive')} href="#/processes">
            Prozesse
          </a>
          <a className={cx('navLink', path === '/analytics' && 'navLinkActive')} href="#/analytics">
            Analytics
          </a>
          <a className={cx('navLink', path === '/settings' && 'navLinkActive')} href="#/settings">
            Settings
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

      {path === '/stats' && <Stats metrics={metrics} />}
      {path === '/alerts' && <AlertsView metrics={metrics} api={api} />}
      {path === '/processes' && <ProcessesView metrics={metrics} />}
      {path === '/analytics' && <AnalyticsView metrics={metrics} />}
      {path === '/settings' && <SettingsView />}
      {(!path || path === '/dashboard') && <Dashboard metrics={metrics} onAckAlerts={() => api.ackAlerts()} />}

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

function AlertsView({ metrics, api }) {
  const active = metrics?.alerts_active || []
  const unack = metrics?.alerts_active_unacknowledged || active
  const log = Array.isArray(metrics?.alerts_log) ? metrics.alerts_log : []

  return (
    <main className="grid">
      <Card title="Status">
        <div className="rows">
          <div className="row"><span>Active</span><strong style={{ color: active.length ? 'var(--danger)' : 'var(--success)' }}>{active.length}</strong></div>
          <div className="row"><span>Unacked</span><strong style={{ color: unack.length ? 'var(--warn)' : 'var(--success)' }}>{unack.length}</strong></div>
        </div>
        <div className="meta" style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <button className="button buttonPrimary" onClick={() => api.ackAlerts()} disabled={!active.length}>Ack all</button>
          {active.map((k) => (
            <button key={k} className="button" onClick={() => api.ackAlerts([k])}>Ack {k}</button>
          ))}
        </div>
      </Card>
      <Card title="Log">
        <div className="rows">
          {log.slice().reverse().slice(0, 30).map((e) => (
            <div key={String(e.id ?? `${e.ts}-${e.type}`)} className="row" style={{ alignItems: 'flex-start' }}>
              <span style={{ color: 'var(--text-muted)' }}>{new Date((e.ts || 0) * 1000).toLocaleTimeString()}</span>
              <strong style={{ color: e.event === 'resolved' ? 'var(--success)' : e.event === 'anomaly' ? 'var(--warn)' : 'var(--danger)', textAlign: 'right' }}>
                {e.message || e.type}
              </strong>
            </div>
          ))}
          {log.length === 0 && <div className="meta">Keine Alerts.</div>}
        </div>
      </Card>
    </main>
  )
}

function ProcessesView({ metrics }) {
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('cpu')
  const procs = Array.isArray(metrics?.processes) ? metrics.processes : []

  const rows = useMemo(() => {
    const filtered = procs.filter((p) => {
      const name = String(p?.name || p?.comm || '')
      return !q || name.toLowerCase().includes(q.toLowerCase())
    })
    const sorted = filtered.slice().sort((a, b) => {
      if (sort === 'ram') return (Number(b?.rss_kb || 0) - Number(a?.rss_kb || 0))
      return (Number(b?.cpu_time || 0) - Number(a?.cpu_time || 0))
    })
    return sorted
  }, [procs, q, sort])

  return (
    <main className="grid">
      <Card title="Prozesse">
        <div className="toolbar">
          <input className="input" placeholder="Suche…" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="select" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="cpu">Sort: CPU</option>
            <option value="ram">Sort: RAM</option>
          </select>
        </div>
        <div className="meta">Quelle: Live-Metriken (Top Prozesse)</div>
        <table className="table" style={{ marginTop: '0.5rem' }}>
          <thead>
            <tr>
              <th>Name</th>
              <th>PID</th>
              <th>RSS</th>
              <th>CPU time</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={String(p.pid)}>
                <td title={p.comm || ''}>{p.name || p.comm || '?'}</td>
                <td>{p.pid}</td>
                <td>{p.rss_kb ? `${(p.rss_kb / 1024).toFixed(1)} MB` : '—'}</td>
                <td>{p.cpu_time ?? '—'}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={4} className="meta">Keine Daten.</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </main>
  )
}

function AnalyticsView({ metrics }) {
  const [period, setPeriod] = useState('today')
  const [metric, setMetric] = useState('cpu')
  const [compare, setCompare] = useState(null)
  const [trend, setTrend] = useState(null)
  const [predict, setPredict] = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const r1 = await fetch(`/api/analytics/compare?metric=${encodeURIComponent(metric)}&period=${encodeURIComponent(period)}`)
        const j1 = await r1.json()
        const r2 = await fetch(`/api/analytics/trend?metric=${encodeURIComponent(metric)}&window_min=30`)
        const j2 = await r2.json()
        const r3 = await fetch(`/api/analytics/predict?metric=${encodeURIComponent(metric)}&threshold=90&window_min=60`)
        const j3 = await r3.json()
        if (cancelled) return
        setCompare(j1)
        setTrend(j2)
        setPredict(j3)
      } catch (e) {
        if (!cancelled) {
          setCompare(null)
          setTrend(null)
          setPredict(null)
        }
      }
    }
    load()
    const t = window.setInterval(load, 20_000)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [metric, period])

  const series = Array.isArray(compare?.series) ? compare.series : []
  const chartData = useMemo(() => series.map((d) => ({ t: new Date(d.ts * 1000).toLocaleString(), avg: d.avg, max: d.max })), [series])
  const dir = trend?.direction

  return (
    <main className="grid">
      <Card title="Analytics">
        <div className="toolbar">
          <select className="select" value={metric} onChange={(e) => setMetric(e.target.value)}>
            <option value="cpu">CPU</option>
            <option value="mem">RAM</option>
            <option value="disk">Disk</option>
            <option value="temp_cpu">Temp CPU</option>
          </select>
          <select className="select" value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="today">Heute</option>
            <option value="yesterday">Gestern</option>
            <option value="week">Woche</option>
            <option value="month">Monat</option>
          </select>
          <span className={cx('pill', dir === 'up' ? 'pillWarn' : dir === 'down' ? 'pillOk' : 'pill')}>
            Trend: {dir || '—'}
          </span>
        </div>
        <div className="chartWrap" style={{ marginTop: '0.75rem' }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <XAxis dataKey="t" hide />
              <YAxis hide />
              <Tooltip />
              <Line type="monotone" dataKey="avg" stroke="var(--accent)" dot={false} strokeWidth={2} isAnimationActive />
              <Line type="monotone" dataKey="max" stroke="var(--warn)" dot={false} strokeWidth={1.5} isAnimationActive />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="meta">
          Prediction (to 90): {predict?.time_to_threshold_sec != null ? `${Math.round(predict.time_to_threshold_sec / 60)} min` : '—'} · confidence {predict?.confidence ?? '—'}
        </div>
      </Card>
      <Card title="Live Snapshot">
        <div className="rows">
          <div className="row"><span>CPU</span><strong>{metrics?.cpu?.usage_percent != null ? `${metrics.cpu.usage_percent} %` : '—'}</strong></div>
          <div className="row"><span>RAM</span><strong>{metrics?.memory?.usage_percent != null ? `${metrics.memory.usage_percent} %` : '—'}</strong></div>
          <div className="row"><span>Disk</span><strong>{metrics?.disk?.usage_percent != null ? `${metrics.disk.usage_percent} %` : '—'}</strong></div>
          <div className="row"><span>Temp</span><strong>{metrics?.temperature?.cpu != null ? `${metrics.temperature.cpu} °C` : '—'}</strong></div>
        </div>
      </Card>
    </main>
  )
}

function SettingsView() {
  const [localTheme, setLocalTheme] = useState('system')
  const [server, setServer] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    try {
      const raw = localStorage.getItem('raspwatch_settings')
      const s = raw ? JSON.parse(raw) : null
      setLocalTheme(s?.theme || 'system')
    } catch (e) {}
  }, [])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const r = await fetch('/api/settings')
        const j = await r.json()
        if (!cancelled) setServer(j)
      } catch (e) {
        if (!cancelled) setServer(null)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  const applyTheme = (theme) => {
    setLocalTheme(theme)
    try {
      const raw = localStorage.getItem('raspwatch_settings')
      const s = raw ? JSON.parse(raw) : {}
      s.theme = theme
      localStorage.setItem('raspwatch_settings', JSON.stringify(s))
    } catch (e) {}
    try {
      const effective =
        theme === 'light' ? 'light' : theme === 'dark' ? 'dark' : (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
      document.documentElement.setAttribute('data-theme', effective === 'light' ? 'light' : 'dark')
    } catch (e) {}
  }

  const togglePlugin = (name) => {
    if (!server) return
    const cur = Array.isArray(server.plugins_enabled) ? server.plugins_enabled : []
    const next = cur.includes(name) ? cur.filter((x) => x !== name) : cur.concat([name])
    setServer({ ...server, plugins_enabled: next })
  }

  const saveServer = async () => {
    if (!server) return
    setSaving(true)
    try {
      const r = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(server) })
      const j = await r.json()
      setServer(j)
    } catch (e) {}
    setSaving(false)
  }

  return (
    <main className="grid">
      <Card title="UI Einstellungen">
        <div className="formGrid">
          <div className="formRow">
            <div className="label">Theme</div>
            <select className="select" value={localTheme} onChange={(e) => applyTheme(e.target.value)}>
              <option value="system">System</option>
              <option value="dark">Dark</option>
              <option value="light">Light</option>
            </select>
            <div className="hint">Wird lokal im Browser gespeichert.</div>
          </div>
        </div>
      </Card>

      <Card title="Server Einstellungen">
        {!server && <div className="meta">Lade…</div>}
        {server && (
          <div className="formGrid">
            <div className="formRow">
              <div className="label">Auth enabled</div>
              <select className="select" value={server.auth_enabled ? 'on' : 'off'} onChange={(e) => setServer({ ...server, auth_enabled: e.target.value === 'on' })}>
                <option value="off">Off</option>
                <option value="on">On</option>
              </select>
              <div className="hint">Wenn aktiviert: Login via `/api/auth/login` (api_key Modus).</div>
            </div>

            <div className="formRow">
              <div className="label">Alerts sustain (sec)</div>
              <input className="input" type="number" value={server.alerts_sustain_sec ?? 10} onChange={(e) => setServer({ ...server, alerts_sustain_sec: Number(e.target.value) })} />
              <div className="hint">0 = sofort, {'>'}0 = nur bei länger anhaltenden Problemen.</div>
            </div>

            <div className="formRow">
              <div className="label">Plugins</div>
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                {['autodarts'].map((p) => (
                  <button key={p} className={cx('button', (server.plugins_enabled || []).includes(p) && 'buttonPrimary')} onClick={() => togglePlugin(p)}>
                    {p}
                  </button>
                ))}
              </div>
              <div className="hint">Nach Enable/Disable: Service neu starten, damit Plugins neu geladen werden.</div>
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <button className="button buttonPrimary" onClick={saveServer} disabled={saving}>{saving ? 'Speichere…' : 'Speichern'}</button>
              <button className="button" onClick={() => window.location.reload()} disabled={saving}>Reload</button>
            </div>
          </div>
        )}
      </Card>
    </main>
  )
}
