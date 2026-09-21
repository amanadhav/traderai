const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function req(path, opts = {}) {
  const token = import.meta.env.VITE_API_TOKEN
  if (token) {
    opts = { ...opts, headers: { ...opts.headers, 'X-API-Token': token } }
  }
  const res = await fetch(BASE + path, opts)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

function post(path, body) {
  return req(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export const api = {
  positions:   () => req('/api/positions'),
  history:     () => req('/api/history'),
  trades:      () => req('/api/trades'),
  market:      () => req('/api/market'),
  prices:      () => req('/api/prices'),
  actionItems: () => req('/api/action-items'),
  score:       (t) => req(`/api/score/${t}`),
  news:        (t) => req(`/api/news/${t}`),
  chart:       (t, days = 180) => req(`/api/chart/${t}?days=${days}`),
  tradeSetup:  (t, equity) => req(`/api/trade-setup/${t}?equity=${equity}`),
  guardian:    () => req('/api/guardian'),
  macro:       () => req('/api/macro'),
  debate:      (t) => req(`/api/debate/${t}`),
  scanExplanations: () => req('/api/scan-explanations'),

  etfs:        () => req('/api/etfs'),
  macroNews:   () => req('/api/macro-news'),
  scanRun:     (body) => post('/api/scan/run', body),
  scanStatus:  () => req('/api/scan/status'),
  scanResults: () => req('/api/scan-results'),
  newsAll:     () => req('/api/news-all'),

  briefing:       () => req('/api/briefing'),
  briefingLatest: () => req('/api/briefing/latest'),
  chat:        (body) => post('/api/chat', body),

  backtestRun:     (body) => post('/api/backtest/run', body),
  backtestStatus:  () => req('/api/backtest/status'),
  backtestResults: () => req('/api/backtest/results'),

  buy:  (body) => post('/api/buy', body),
  sell: (body) => post('/api/sell', body),
  stop: (body) => post('/api/stop', body),
  cash: (body) => post('/api/cash', body),
}

export function fmt$(n) {
  if (n == null) return '-'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(n)
}

export function fmtPct(n) {
  if (n == null) return '-'
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%'
}

// Tailwind tone class for a P&L number: green for gains, red for losses
export function clsPl(n) {
  if (n == null) return 'text-muted-foreground'
  return n >= 0 ? 'text-gain' : 'text-loss'
}
