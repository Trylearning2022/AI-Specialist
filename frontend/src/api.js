// Gọi API qua Gateway; hỗ trợ luồng sự kiện (SSE) cho câu trả lời trực tuyến.
import { token } from './auth'

async function headers(extra = {}) {
  return { Authorization: 'Bearer ' + (await token()), ...extra }
}

async function handle(r) {
  if (!r.ok) {
    let msg = r.statusText
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* */ }
    throw new Error(msg || 'Lỗi ' + r.status)
  }
  const ct = r.headers.get('content-type') || ''
  return ct.includes('application/json') ? r.json() : r.text()
}

export const api = {
  async get(path, params) {
    const q = params ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null)) : ''
    return handle(await fetch('/api' + path + q, { headers: await headers() }))
  },
  async send(method, path, body) {
    return handle(await fetch('/api' + path, {
      method, headers: await headers({ 'Content-Type': 'application/json' }),
      body: body === undefined ? undefined : JSON.stringify(body),
    }))
  },
  post: (p, b) => api.send('POST', p, b),
  put: (p, b) => api.send('PUT', p, b),
  patch: (p, b) => api.send('PATCH', p, b),
  del: (p) => api.send('DELETE', p),
  async upload(path, form) {
    return handle(await fetch('/api' + path, { method: 'POST', headers: await headers(), body: form }))
  },
  async download(path, filename) {
    const r = await fetch('/api' + path, { headers: await headers() })
    if (!r.ok) return handle(r)
    const url = URL.createObjectURL(await r.blob())
    const a = Object.assign(document.createElement('a'), { href: url, download: filename })
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  },
  async stream(path, body, onEvent, signal) {
    const r = await fetch('/api' + path, {
      method: 'POST', headers: await headers({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
      body: JSON.stringify(body), signal,
    })
    if (!r.ok) return handle(r)
    const reader = r.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let i
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, i)
        buf = buf.slice(i + 2)
        let ev = 'message', data = ''
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) ev = line.slice(6).trim()
          else if (line.startsWith('data:')) data += line.slice(5).trim()
        }
        if (data) onEvent(ev, JSON.parse(data))
      }
    }
  },
}
