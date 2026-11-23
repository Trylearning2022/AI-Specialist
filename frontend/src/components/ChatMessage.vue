<template>
  <div v-if="m.role === 'user'" class="msg user">
    <div class="bubble">
      <div v-if="files.length" class="bubble-files">
        <span v-for="f in files" :key="f" class="filechip"><Icon name="paperclip" :size="13" /> {{ f }}</span>
      </div>{{ m.content }}</div>
  </div>

  <div v-else class="msg bot">
    <img class="avatar" src="/logo.png" alt="" />
    <div class="body">
      <div class="meta-row">
        <span v-if="routeLabel" class="chip-route"><Icon :name="routeIcon" :size="13" /> {{ routeLabel }}</span>
        <span v-if="trust" :class="['trust', trust.kind]" :title="trust.title"><Icon :name="trust.icon" :size="13" /> {{ trust.text }}</span>
        <span v-if="!m.pending && took" class="muted small"><Icon name="clock" :size="12" /> {{ took }}</span>
      </div>

      <!-- Đang xử lý: kế hoạch các bước của lượt trả lời, cập nhật trực tiếp -->
      <div v-if="m.pending && m.plan?.length && !m.content" class="process live">
        <div class="process-h"><span class="spin sm" /> <b>Đang xử lý</b><span class="muted small">{{ elapsed }} giây</span></div>
        <StepTimeline :steps="m.plan" compact />
      </div>
      <div v-else-if="m.pending && !m.content" class="thinking">
        <span class="dots"><i /><i /><i /></span>
        <span>{{ m.status || 'Đang xử lý…' }}</span>
        <span class="muted small">{{ elapsed }} giây</span>
      </div>
      <details v-else-if="m.plan?.length > 1" class="process done" :open="m.pending">
        <summary><Icon name="steps" :size="13" /> Đã xử lý qua {{ m.plan.length }} bước<template v-if="took"> · {{ took }}</template>
          <span v-if="m.pending" class="muted"> – đang soạn câu trả lời…</span></summary>
        <StepTimeline :steps="m.plan" compact />
      </details>

      <div v-if="m.content && !(m.data?.clarify && !m.pending)" class="md answer" v-html="html" @click="onClick" />
      <span v-if="m.pending && m.content" class="caret" />

      <!-- Luồng B: nguyên văn -->
      <div v-for="b in m.data?.exact_blocks || []" :key="b.section_id" class="exact">
        <div class="exact-h">
          <Icon name="quote" :size="15" />
          <b>{{ b.locator || b.heading }}</b><span class="muted">· {{ b.so_hieu }}</span>
          <span v-if="b.trang_thai && b.trang_thai !== 'con_hieu_luc'" class="tag err">{{ STATUS[b.trang_thai] || b.trang_thai }}</span>
        </div>
        <pre>{{ vb(b.text) }}</pre>
        <div class="exact-f">
          <span>Nguyên văn từ kho chuẩn · mã {{ b.section_id }} · phiên bản {{ (b.commit || '').slice(0, 8) }}</span>
          <span class="exact-a">
            <a @click="copy(b.text)"><Icon name="copy" :size="13" /> Sao chép</a>
            <a @click="showDoc(b.doc_id, b.section_id)"><Icon name="book" :size="13" /> Toàn văn</a>
          </span>
        </div>
      </div>
      <div v-if="m.data?.interpretation" class="interp">
        <div class="interp-h"><Icon name="sparkle" :size="14" /> Diễn giải (AI – tham khảo, đã đối chiếu số liệu với nguyên văn)</div>
        <div class="md" v-html="render(m.data.interpretation)" />
      </div>
      <button v-else-if="m.data?.exact_blocks?.length && m.data?.message_id && !m.pending" class="btn ghost sm"
              :disabled="m.interpreting" @click="interpret(m)">
        <Icon name="sparkle" :size="14" /> {{ m.interpreting ? 'Đang diễn giải…' : 'Giải thích ngắn gọn' }}
      </button>

      <!-- Hỏi lại làm rõ -->
      <ClarifyCard v-if="m.data?.clarify && !m.pending" :m="m" />

      <!-- Tác vụ dài (phân tích, soạn thảo, tổng hợp): tiến trình trực tiếp -->
      <TaskCard v-if="m.data?.task" :task="m.data.task" />

      <!-- Hỗ trợ kỹ thuật: chưa khắc phục được → tạo phiếu ngay trong trò chuyện -->
      <div v-if="m.data?.support && !m.pending" class="support-bar">
        <span class="muted small"><Icon name="wrench" :size="13" />
          {{ m.data.support.doi_tuong ? 'Thiết bị/hệ thống: ' + m.data.support.doi_tuong + '. ' : '' }}Chưa khắc phục được?</span>
        <button class="btn ghost sm" :disabled="m.ticket" @click="ticket"><Icon name="ticket" :size="14" /> {{ m.ticket ? 'Đã tạo phiếu ' + m.ticket : 'Tạo phiếu yêu cầu hỗ trợ' }}</button>
      </div>

      <!-- Danh sách tài liệu -->
      <div v-if="m.data?.docs?.length" class="doclist">
        <div v-for="d in m.data.docs" :key="d.doc_id" class="docitem">
          <Icon :name="d.nguon === 'B' ? 'scale' : 'file'" />
          <div class="grow">
            <b>{{ d.title }}</b> <span v-if="d.nguon === 'B'" class="tag b">chuẩn</span>
            <div class="muted small">{{ [d.so_hieu, LOAI[d.loai] || d.loai, d.ngay_ban_hanh].filter(Boolean).join(' · ') }}</div>
            <div v-for="x in (d.doan || []).slice(0, 2)" :key="x.section_id" class="muted small clamp">{{ x.breadcrumb }}: {{ x.text }}</div>
          </div>
        </div>
        <router-link v-if="m.data.open_module === 'tong-hop'" class="btn sm" :to="{ path: '/tac-vu/moi/tong_hop', query: { docs: m.data.docs.map((d) => d.doc_id).join(',') } }">
          <Icon name="layers" :size="14" /> Lập báo cáo từ các tài liệu này</router-link>
      </div>


      <router-link v-if="m.data?.open_module === 'gop-y'" class="btn sm"
                   :to="{ path: '/tac-vu/moi/soan_thao', query: { mau: 'soan-cong-van-gop-y', che_do: 'gop_y' } }">
        <Icon name="pen" :size="14" /> Soạn công văn tham gia ý kiến dự thảo</router-link>
      <div v-for="w in warnings" :key="w" class="warnbox"><Icon name="alert" :size="14" /> {{ w }}</div>
      <p v-if="m.error" class="err small">{{ m.error }}</p>

      <!-- Nguồn rút gọn -->
      <div v-if="!m.pending && m.data?.sources?.length" class="srcchips">
        <button v-for="s in m.data.sources.slice(0, 4)" :key="s.n" class="srcchip" :title="s.breadcrumb" @click="showSources(m.data.sources, s.n)">
          <span class="num">{{ s.n }}</span><span class="clamp1">{{ s.title }}</span>
        </button>
        <button v-if="m.data.sources.length > 4" class="srcchip" @click="showSources(m.data.sources)">+{{ m.data.sources.length - 4 }}</button>
      </div>

      <!-- Thao tác -->
      <div v-if="!m.pending && m.data?.message_id" class="actions">
        <button class="icon-btn" title="Sao chép câu trả lời" @click="copy(plainAnswer)"><Icon name="copy" :size="16" /></button>
        <button :class="['icon-btn', { on: m.rated === 1 }]" title="Câu trả lời đúng" :disabled="!!m.rated" @click="rate(m, 1)"><Icon name="up" :size="16" /></button>
        <button :class="['icon-btn', { on: m.rated === -1 }]" title="Câu trả lời chưa đúng" :disabled="!!m.rated" @click="bad"><Icon name="down" :size="16" /></button>
        <button class="icon-btn" title="Hỏi lại" :disabled="chat.busy" @click="retry(m)"><Icon name="refresh" :size="16" /></button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { api } from '../api'
import { chat, interpret, rate, retry, showDoc, showSources } from '../chat'
import { MODES } from '../extensions'
import { render, vb, LOAI, STATUS } from '../md'
import { promptBox, toast } from '../ui'
import Icon from './Icon.vue'
import ClarifyCard from './ClarifyCard.vue'
import StepTimeline from './StepTimeline.vue'
import TaskCard from './TaskCard.vue'

const props = defineProps({ m: { type: Object, required: true } })
const files = computed(() => props.m.data?.files || [])
const esc = (s) => String(s || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

const html = computed(() => {
  const srcs = props.m.data?.sources || []
  let h = render(props.m.content, { cites: true })
  // chú thích khi rê chuột lên chỉ số nguồn
  return h.replace(/data-n="(\d+)"/g, (all, n) => {
    const s = srcs.find((x) => x.n === Number(n))
    return s ? `${all} title="${esc(s.title + (s.breadcrumb ? ' › ' + s.breadcrumb : ''))}"` : all
  })
})
const plainAnswer = computed(() => [props.m.content, ...(props.m.data?.exact_blocks || []).map((b) => `${b.locator || ''} ${b.so_hieu}:\n${b.text}`)].join('\n\n'))
const routeLabel = computed(() => props.m.data?.route_label || '')
const ROUTE_ICON = { tong_hop: 'merge', phan_tich: 'scan', soan_thao: 'pen', lam_ro: 'help', bao_ve: 'shield' }
const routeIcon = computed(() => MODES.find((x) => x.id === props.m.data?.route)?.icon || ROUTE_ICON[props.m.data?.route] || 'chat')
const elapsed = computed(() => Math.max(0, Math.round((chat.now - (props.m.t0 || chat.now)) / 1000)))
const took = computed(() => {
  if (!props.m.t0 || !props.m.t1) return ''
  const s = (props.m.t1 - props.m.t0) / 1000
  return s < 1 ? '' : `${s.toFixed(0)} giây`
})
const warnings = computed(() => [...(props.m.data?.warnings || []), ...(props.m.data?.interpret_warnings || [])])
const trust = computed(() => {
  const d = props.m.data || {}
  if (props.m.pending || props.m.stopped || !d.verify || ['chao_hoi', 'lam_ro', 'phan_tich', 'soan_thao', 'tong_hop'].includes(d.route)) return null
  if (d.guard) return { kind: 'bad', icon: 'shield', text: 'Đã chặn theo quy định ATTT', title: 'Nội dung không được xử lý và không được lưu' }
  if (d.exact_blocks?.length) return { kind: 'b', icon: 'lock', text: 'Nguyên văn đã kiểm chứng', title: 'Trích trực tiếp từ kho văn bản chuẩn đã duyệt hai cấp' }
  if (d.verify.ok === false) return { kind: 'bad', icon: 'alert', text: 'Cần đối chiếu', title: 'Câu trả lời chưa qua đủ các bước kiểm chứng' }
  if (d.sources?.length) return { kind: 'good', icon: 'check', text: 'Đã kiểm tra trích dẫn', title: 'Trích dẫn và số liệu đã được đối chiếu với nguồn' }
  return null
})

function onClick(e) {
  const n = e.target?.closest?.('a.cite')?.dataset?.n
  if (n) showSources(props.m.data?.sources, n)
}
const copy = (t) => { navigator.clipboard?.writeText(t); toast('Đã sao chép.') }
async function ticket() {
  const i = chat.messages.indexOf(props.m)
  const q = [...chat.messages.slice(0, i)].reverse().find((x) => x.role === 'user')?.content || ''
  const d = await promptBox('Tạo phiếu yêu cầu hỗ trợ kỹ thuật', {
    message: 'Mô tả thêm vị trí, thời điểm, thông báo lỗi, các bước đã thử. Không ghi mã PIN, mật khẩu.',
    value: `Sự cố: ${q}\nĐã thực hiện theo hướng dẫn của trợ lý nhưng chưa khắc phục được.`, ok: 'Gửi phiếu' })
  if (!d) return
  const t = await api.post('/support/tickets', { title: q.slice(0, 280) || 'Yêu cầu hỗ trợ kỹ thuật', description: d })
  props.m.ticket = t.id
  toast(`Đã tạo phiếu yêu cầu hỗ trợ số ${t.id}.`)
}
async function bad() {
  const c = await promptBox('Câu trả lời chưa đúng ở điểm nào?', { message: 'Góp ý giúp cán bộ quản trị xác định nguyên nhân và khắc phục.', placeholder: 'Ví dụ: số liệu sai, thiếu nguồn, trích sai điều khoản…', required: false })
  if (c !== null) await rate(props.m, -1, c)
}
</script>
