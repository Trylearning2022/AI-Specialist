<template>
  <div class="page">
  <PageHeader title="Quản trị" icon="shield" desc="Phản hồi người dùng, chất lượng nạp dữ liệu, kỹ năng (mẫu báo cáo, bộ tiêu chí phân tích, mẫu văn bản), công cụ của tác tử." />
  <div class="tabs">
    <button v-for="t in tabs" :key="t.id" :class="{ on: tab === t.id }" @click="go(t.id)">{{ t.label }}</button>
  </div>

  <div class="card tip-card row">
    <Icon name="activity" :size="18" /><span class="grow">Trạng thái dịch vụ, người dùng, hiệu năng, nhật ký hệ thống và kiểm toán xem tại màn hình <b>Giám sát hệ thống</b>;
      chất lượng cơ sở tri thức tại <b>Giám định dữ liệu</b>.</span>
    <router-link to="/giam-sat" class="btn ghost sm">Giám sát</router-link><router-link to="/giam-dinh" class="btn ghost sm">Giám định</router-link>
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

</div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { render, fmtDate } from '../md'
import { promptBox } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'

const tabs = [{ id: 'phan-hoi', label: 'Phản hồi' }, { id: 'chat-luong', label: 'Chất lượng nạp dữ liệu' },
  { id: 'ky-nang', label: 'Kỹ năng, bộ tiêu chí, công cụ' }]
const tab = ref('phan-hoi')
const feedback = ref([]), fbStatus = ref('moi'), quality = ref({}), skills = ref([]), tools = ref([])

onMounted(() => go('phan-hoi'))
async function go(t) {
  tab.value = t
  if (t === 'phan-hoi') loadFb()
  if (t === 'chat-luong') quality.value = await api.get('/ingest/reports/quality')
  if (t === 'ky-nang') { skills.value = await api.get('/chat/skills'); tools.value = await api.get('/chat/tools') }
}
async function loadFb() { feedback.value = await api.get('/chat/feedback', { status: fbStatus.value }) }
async function resolve(f) {
  const resolution = await promptBox('Ghi nhận xử lý phản hồi', { message: f.question, placeholder: 'Nguyên nhân (dữ liệu / truy xuất / ngữ cảnh / mô hình) và biện pháp đã thực hiện…', ok: 'Lưu' })
  if (resolution) { await api.post(`/chat/feedback/${f.id}/resolve`, { resolution }); loadFb() }
}
</script>
