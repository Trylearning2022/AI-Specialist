<template>
  <div class="page">
  <PageHeader title="Quản trị" icon="shield" desc="Trạng thái dịch vụ, chất lượng câu trả lời và dữ liệu, kỹ năng, nhật ký kiểm toán." />
  <div class="tabs">
    <button v-for="t in tabs" :key="t.id" :class="{ on: tab === t.id }" @click="go(t.id)">{{ t.label }}</button>
  </div>

  <div v-if="tab === 'tong-quan'" class="cols">
    <div class="card"><h3>Trạng thái dịch vụ</h3>
      <table><tr v-for="(v, k) in health.services" :key="k"><td><span :class="['dot', { bad: v !== 'ok' }]" />{{ k }}</td><td :class="v === 'ok' ? 'ok' : 'err'">{{ v === 'ok' ? 'Hoạt động' : v }}</td></tr></table>
      <h3>Mô hình đang khai báo (LiteLLM)</h3>
      <p v-if="has('admin')">{{ models.join(', ') || '—' }}</p><p v-else class="muted">Chỉ quản trị viên xem được.</p>
    </div>
    <div class="card"><h3>Thống kê sử dụng</h3>
      <div class="stat">
        <div v-for="(v, k) in flatStats" :key="k"><span class="muted small">{{ k }}</span><b>{{ v }}</b></div>
      </div>
      <h3>Chỉ mục tìm kiếm</h3><p>{{ searchStats.points }} đoạn · {{ searchStats.status }}</p>
    </div>
  </div>

  <div v-if="tab === 'phan-hoi'" class="card">
    <div class="row"><h3 class="grow">Phản hồi của người dùng (vòng cải tiến “mỗi lỗi chỉ xảy ra một lần”)</h3>
      <select v-model="fbStatus" @change="loadFb"><option value="moi">Chưa xử lý</option><option value="da_xu_ly">Đã xử lý</option></select></div>
    <table>
      <tr><th>Câu hỏi</th><th>Câu trả lời</th><th>Phản hồi</th><th></th></tr>
      <tr v-for="f in feedback" :key="f.id">
        <td>{{ f.question }}<br><span class="muted">{{ f.username }} · {{ fmtDate(f.created_at) }} · {{ f.route }}</span></td>
        <td><div class="md" style="max-height:160px;overflow:auto" v-html="render(f.answer)" /></td>
        <td :class="f.rating < 0 ? 'err' : 'ok'">{{ f.rating < 0 ? 'Sai' : 'Đúng' }}<br>{{ f.comment }}<div class="muted">{{ f.resolution }}</div></td>
        <td><button v-if="f.status === 'moi'" class="btn ghost sm" @click="resolve(f)">Ghi nhận xử lý</button></td>
      </tr>
    </table>
    <p class="muted" style="font-size:.85rem">Quy trình: xác định nguyên nhân (dữ liệu / truy xuất / ngữ cảnh / mô hình) → sửa ở tầng tương ứng
      (bổ sung tài liệu, sửa kỹ năng, thuật ngữ, ngưỡng) → bổ sung ca kiểm thử vào bộ golden set.</p>
  </div>

  <div v-if="tab === 'chat-luong'" class="card">
    <div class="md" v-html="render(quality.markdown || '')" />
    <h3>Tài liệu chất lượng thấp</h3>
    <table><tr v-for="x in quality.low_quality || []" :key="x.id"><td><router-link :to="'/kiem-duyet/' + x.id">{{ x.filename }}</router-link></td>
      <td>{{ x.diem }}</td><td class="muted">{{ x.canh_bao.join(' · ') }}</td></tr></table>
  </div>

  <div v-if="tab === 'ky-nang'" class="card">
    <p class="muted">Kỹ năng, chỉ thị, thuật ngữ là các tệp Markdown trong thư mục skills/, prompts/, glossary/ (quản lý phiên bản bằng Git).
      Mọi thay đổi phải chạy bộ kiểm thử hồi quy trước khi áp dụng.</p>
    <div v-for="s in skills" :key="s.name" class="src"><b>{{ s.name }}</b> – {{ s.description }}
      <details><summary>Nội dung</summary><div class="md" v-html="render(s.body)" /></details></div>
    <h3>Công cụ của tác tử (MCP: /api/chat/mcp/)</h3>
    <table><tr v-for="t in tools" :key="t.name"><td><code>{{ t.name }}</code></td><td>{{ t.description }}</td><td>{{ t.writes ? 'ghi' : 'chỉ đọc' }}</td></tr></table>
  </div>

  <div v-if="tab === 'nhat-ky'" class="card">
    <div class="row">
      <input v-model="af.actor" placeholder="Người thực hiện" /><input v-model="af.action" placeholder="Hành động (tiền tố)" />
      <button class="btn sec" @click="loadAudit">Lọc</button>
      <button class="btn sec" @click="verifyAudit">Kiểm tra toàn vẹn chuỗi băm</button>
      <span v-if="verify" :class="verify.ok ? 'ok' : 'err'">{{ verify.ok ? `Toàn vẹn (${verify.checked} bản ghi)` : `Phát hiện sai lệch tại bản ghi ${verify.broken_at}` }}</span>
    </div>
    <p v-if="auditErr" class="err">{{ auditErr }}</p>
    <table>
      <tr><th>Thời điểm</th><th>Người</th><th>Hành động</th><th>Đối tượng</th><th>Chi tiết</th></tr>
      <tr v-for="a in audit" :key="a.id"><td>{{ fmtDate(a.ts) }}</td><td>{{ a.actor }}</td><td>{{ a.action }}</td><td>{{ a.resource }}</td>
        <td class="muted" style="font-size:.8rem;max-width:420px;word-break:break-all">{{ JSON.stringify(a.detail) }}</td></tr>
    </table>
  </div>
</div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { has } from '../auth'
import { render, fmtDate } from '../md'
import { promptBox } from '../ui'
import PageHeader from '../components/PageHeader.vue'

const tabs = [{ id: 'tong-quan', label: 'Tổng quan' }, { id: 'phan-hoi', label: 'Phản hồi' }, { id: 'chat-luong', label: 'Chất lượng dữ liệu' },
  { id: 'ky-nang', label: 'Kỹ năng, công cụ' }, ...(has('admin') ? [{ id: 'nhat-ky', label: 'Nhật ký kiểm toán' }] : [])]
const tab = ref('tong-quan'), health = ref({}), models = ref([]), stats = ref({}), searchStats = ref({})
const feedback = ref([]), fbStatus = ref('moi'), quality = ref({}), skills = ref([]), tools = ref([])
const audit = ref([]), verify = ref(null), auditErr = ref(''), af = reactive({ actor: '', action: '' })

onMounted(() => go('tong-quan'))
const flatStats = computed(() => {
  const out = {}
  for (const [k, v] of Object.entries(stats.value || {})) {
    if (v && typeof v === 'object') for (const [k2, v2] of Object.entries(v)) out[k2] = v2
    else out[k] = v
  }
  return out
})
async function go(t) {
  tab.value = t
  if (t === 'tong-quan') {
    health.value = await fetch('/api/health').then((r) => r.json())
    stats.value = await api.get('/chat/stats')
    searchStats.value = await api.get('/search/stats').catch(() => ({}))
    if (has('admin')) models.value = (await api.get('/chat/models').catch(() => ({ models: [] }))).models
  }
  if (t === 'phan-hoi') loadFb()
  if (t === 'chat-luong') quality.value = await api.get('/ingest/reports/quality')
  if (t === 'ky-nang') { skills.value = await api.get('/chat/skills'); tools.value = await api.get('/chat/tools') }
  if (t === 'nhat-ky') loadAudit()
}
async function loadFb() { feedback.value = await api.get('/chat/feedback', { status: fbStatus.value }) }
async function resolve(f) {
  const resolution = await promptBox('Ghi nhận xử lý phản hồi', { message: f.question, placeholder: 'Nguyên nhân (dữ liệu / truy xuất / ngữ cảnh / mô hình) và biện pháp đã thực hiện…', ok: 'Lưu' })
  if (resolution) { await api.post(`/chat/feedback/${f.id}/resolve`, { resolution }); loadFb() }
}
async function loadAudit() { try { audit.value = await api.get('/audit/logs', af) } catch (e) { auditErr.value = e.message } }
async function verifyAudit() { verify.value = await api.get('/audit/verify') }
</script>
