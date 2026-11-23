// Trạng thái trò chuyện dùng chung: giữ nguyên khi người dùng chuyển sang tiện ích khác rồi quay lại,
// câu trả lời đang sinh vẫn tiếp tục chạy nền.
import { reactive } from 'vue'
import { api } from './api'
import { refreshActive } from './tasks'
import { toast } from './ui'

export const chat = reactive({
  convs: [], convId: null, messages: [], busy: false, mode: 'tu_dong', loai: '', draft: '', files: [],
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
  chat.messages = c.messages.map((m, i, all) => ({
    ...m, data: { ...(m.data || {}), message_id: m.id, route: m.route },
    plan: m.data?.trace?.steps || [],
    // câu hỏi lại đã được trả lời (có tin nhắn người dùng phía sau) thì không cho chọn lại
    clarified: !!m.data?.clarify && i < all.length - 1,
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

/** Gửi câu hỏi. opts: mode, onConv(id) khi máy chủ cấp mã hội thoại mới, attachments [{id, filename}],
 *  clarify {original, answer} khi trả lời câu hỏi làm rõ. */
export async function send(text, { mode, onConv, attachments = [], clarify = null } = {}) {
  text = (text || '').trim()
  if (!text || chat.busy) return
  chat.busy = true
  chat.messages.push({ role: 'user', content: text, data: { files: attachments.map((a) => a.filename) } })
  const m = reactive({ role: 'assistant', content: '', data: {}, plan: [], pending: true, status: 'Đang tiếp nhận câu hỏi…', t0: Date.now() })
  chat.messages.push(m)
  ctrl = new AbortController()
  ticker = setInterval(() => { chat.now = Date.now() }, 500)
  const f = chat.loai ? { loai: chat.loai } : {}
  try {
    await api.stream('/chat/chat', {
      message: text, conversation_id: chat.convId, mode: clarify ? 'tu_dong' : (mode || chat.mode), filters: f, stream: true,
      attachments: attachments.map((a) => a.id), clarify,
    }, (ev, d) => {
      if (ev === 'start') {
        m.data.route = d.route; m.data.route_label = d.route_label
        if (!chat.convId) { chat.convId = d.conversation_id; onConv?.(d.conversation_id) }
      } else if (ev === 'status') m.status = d.text
      else if (ev === 'plan') m.plan = d.steps.map((x) => ({ ...x, status: 'cho' }))
      else if (ev === 'step') {
        const x = m.plan.find((p) => p.id === d.id)
        const upd = { ...d, ...(d.status === 'dang_chay' ? { started: new Date().toISOString() } : {}) }
        if (x) Object.assign(x, upd); else m.plan.push(upd)
      } else if (ev === 'meta') {
        if (d.sources) { m.data.sources = d.sources; chat.panel.sources = d.sources }
        if (d.exact_blocks) m.data.exact_blocks = d.exact_blocks
      } else if (ev === 'delta') { if (!m.first) m.first = Date.now(); m.content += d.text; m.status = '' }
      else if (ev === 'final') {
        m.content = d.answer; m.data = { ...m.data, ...d }; m.pending = false; m.t1 = Date.now()
        if (d.trace?.steps?.length) m.plan = d.trace.steps
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
    if (m.data?.task) refreshActive()
  }
}

/** Trả lời câu hỏi làm rõ: hiển thị lựa chọn, gửi kèm câu hỏi gốc để máy chủ ghép và không hỏi lại lần hai. */
export function answerClarify(m, label, value) {
  const c = m.data.clarify
  send(label, { clarify: { original: c.original, answer: value ?? label } })
}

/** Hỏi lại câu hỏi ngay trước câu trả lời m */
export function retry(m) {
  const i = chat.messages.indexOf(m)
  const q = [...chat.messages.slice(0, i)].reverse().find((x) => x.role === 'user')
  const keep = ['chinh_xac', 'tra_cuu', 'ho_tro', 'tim_tai_lieu', 'tac_tu']
  if (q) send(q.content, { mode: keep.includes(m.data?.route) ? m.data.route : undefined })
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
