// Trạng thái trò chuyện dùng chung: giữ nguyên khi người dùng chuyển sang tiện ích khác rồi quay lại,
// câu trả lời đang sinh vẫn tiếp tục chạy nền.
import { reactive } from 'vue'
import { api } from './api'
import { toast } from './ui'

export const chat = reactive({
  convs: [], convId: null, messages: [], busy: false, mode: 'tu_dong', loai: '', draft: '',
  panel: { open: false, kind: 'sources', sources: [], hl: 0, doc: null, sec: null }, now: Date.now(),
})
let ctrl = null
let ticker = null

export async function loadConvs() {
  try { chat.convs = await api.get('/chat/conversations') } catch { /* */ }
}

export function newConv() {
  if (chat.busy) stop()
  chat.convId = null
  chat.messages = []
  chat.panel = { ...chat.panel, open: false, sources: [], hl: 0 }
}

export async function openConv(id) {
  if (chat.convId === id && chat.messages.length) return
  if (chat.busy) stop()
  const c = await api.get('/chat/conversations/' + id)
  chat.convId = id
  chat.messages = c.messages.map((m) => ({
    ...m, data: { ...(m.data || {}), message_id: m.id, route: m.route },
  }))
  const last = [...chat.messages].reverse().find((m) => m.data?.sources?.length)
  chat.panel.sources = last?.data.sources || []
}

export async function renameConv(id, title) {
  await api.patch('/chat/conversations/' + id, { title })
  await loadConvs()
}

export async function deleteConv(id) {
  await api.del('/chat/conversations/' + id)
  if (chat.convId === id) newConv()
  await loadConvs()
}

export function stop() {
  ctrl?.abort()
}

/** Gửi câu hỏi; onConv(id) được gọi khi máy chủ cấp mã hội thoại mới. */
export async function send(text, { mode, onConv } = {}) {
  text = (text || '').trim()
  if (!text || chat.busy) return
  chat.busy = true
  chat.messages.push({ role: 'user', content: text })
  const m = reactive({ role: 'assistant', content: '', data: {}, steps: [], pending: true, status: 'Đang tiếp nhận câu hỏi…', t0: Date.now() })
  chat.messages.push(m)
  ctrl = new AbortController()
  ticker = setInterval(() => { chat.now = Date.now() }, 500)
  const f = chat.loai ? { loai: chat.loai } : {}
  try {
    await api.stream('/chat/chat', { message: text, conversation_id: chat.convId, mode: mode || chat.mode, filters: f, stream: true },
      (ev, d) => {
        if (ev === 'start') {
          m.data.route = d.route; m.data.route_label = d.route_label
          if (!chat.convId) { chat.convId = d.conversation_id; onConv?.(d.conversation_id) }
        } else if (ev === 'status') m.status = d.text
        else if (ev === 'meta') {
          if (d.sources) { m.data.sources = d.sources; chat.panel.sources = d.sources }
          if (d.exact_blocks) m.data.exact_blocks = d.exact_blocks
          if (d.trees) m.data.trees = d.trees
        } else if (ev === 'delta') { if (!m.first) m.first = Date.now(); m.content += d.text; m.status = '' }
        else if (ev === 'step') m.steps.push(d)
        else if (ev === 'final') {
          m.content = d.answer; m.data = { ...m.data, ...d }; m.pending = false; m.t1 = Date.now()
          if (d.sources?.length) chat.panel.sources = d.sources
        }
      }, ctrl.signal)
  } catch (e) {
    if (e.name === 'AbortError') { m.stopped = true; if (!m.content) m.content = '_Đã dừng theo yêu cầu._' }
    else { m.error = e.message; toast(e.message, 'err') }
  } finally {
    m.pending = false
    if (!m.t1) m.t1 = Date.now()
    chat.busy = false
    clearInterval(ticker)
    ctrl = null
    loadConvs()
  }
}

/** Hỏi lại câu hỏi ngay trước câu trả lời m */
export function retry(m) {
  const i = chat.messages.indexOf(m)
  const q = [...chat.messages.slice(0, i)].reverse().find((x) => x.role === 'user')
  if (q) send(q.content, { mode: m.data?.route && m.data.route !== 'chao_hoi' ? m.data.route : undefined })
}

export async function rate(m, rating, comment = '') {
  await api.post('/chat/feedback', { message_id: m.data.message_id, rating, comment })
  m.rated = rating
  toast(rating > 0 ? 'Cảm ơn đồng chí đã xác nhận.' : 'Đã ghi nhận phản hồi để khắc phục.')
}

export async function interpret(m) {
  m.interpreting = true
  try {
    const r = await api.post(`/chat/messages/${m.data.message_id}/interpret`)
    m.data.interpretation = r.interpretation
    m.data.can_interpret = false
    m.data.interpret_warnings = r.warnings
    if (!r.interpretation) toast('Phần diễn giải không khớp nguyên văn nên đã bị loại; đề nghị đọc nguyên văn.', 'err', 5000)
  } catch (e) { toast(e.message, 'err') } finally { m.interpreting = false }
}

export function showSources(sources, n = 0) {
  chat.panel = { ...chat.panel, open: true, kind: 'sources', sources: sources || chat.panel.sources, hl: Number(n) || 0 }
}

export function showDoc(docId, secId) {
  chat.panel = { ...chat.panel, open: true, kind: 'doc', doc: docId, sec: secId || null }
}

export function prefill(text, mode) {
  chat.draft = text
  if (mode) chat.mode = mode
}
