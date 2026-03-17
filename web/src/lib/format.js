export function formatBytes(n) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  const bytes = Number(n)
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const val = bytes / Math.pow(1024, i)
  return `${val.toFixed(i > 1 ? 2 : 0)} ${units[i]}`
}

export function clamp(n, min, max) {
  return Math.min(max, Math.max(min, n))
}

