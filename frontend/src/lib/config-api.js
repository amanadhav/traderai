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

export const configApi = {
  get:     () => req('/api/config'),
  presets: () => req('/api/config/presets'),
  save:    (config) => req('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config }),
  }),
}
