<template>
  <div v-if="job" class="page">
    <PageHeader :title="'Kiểm duyệt: ' + job.filename" icon="shield" desc="Kiểm tra nội dung, thông tin mô tả; chọn luồng tri thức và duyệt.">
      <router-link to="/nap-du-lieu" class="btn ghost sm"><Icon name="left" :size="14" /> Danh sách tác vụ</router-link>
    </PageHeader>
    <div class="card">
      <div class="row">
        <span class="tag">{{ STATUS[job.status] }}</span>
        <span class="tag">Định dạng: {{ job.kind }}</span>
        <span :class="['tag', job.quality?.diem < 70 ? 'err' : 'ok']">Điểm chất lượng: {{ job.quality?.diem }}</span>
        <span v-if="job.quality?.can_duyet_bat_buoc" class="tag err">Cần duyệt kỹ</span>
        <a class="grow" style="text-align:right" @click="api.download(`/ingest/jobs/${job.id}/original`, job.filename)">Tải tệp gốc</a>
      </div>
      <div v-for="w in job.warnings" :key="w" class="warnbox">{{ w }}</div>
      <div v-for="d in job.duplicates" :key="d.doc_id" class="warnbox">Gần trùng với {{ d.doc_id }} – {{ d.title }} ({{ Math.round(d.tuong_dong * 100) }}%)</div>
      <div v-if="job.approvals?.length" class="muted" style="margin-top:.4rem">Đã duyệt:
        <span v-for="a in job.approvals" :key="a.at">{{ a.user }} (Luồng {{ a.track }}, {{ fmtDate(a.at) }}) </span></div>
      <p v-if="job.reject_reason" class="err">Lý do từ chối: {{ job.reject_reason }}</p>
      <p v-if="job.status === 'dang_duyet'" class="note"><span class="spin sm" /> Đang lập chỉ mục{{ job.target === 'B' ? ' và ghi vào kho văn bản chuẩn' : '' }}
        – tài liệu dài trên máy chủ CPU có thể mất vài phút. Có thể rời trang, tiến trình vẫn chạy nền.</p>
      <p v-if="job.error && job.status !== 'loi'" class="err">{{ job.error }}</p>
    </div>
    <div class="card">
      <h3>Thông tin mô tả</h3>
      <div class="form-grid">
        <label style="grid-column:1/-1">Tên <input v-model="meta.ten" /></label>
        <label>Số hiệu <input v-model="meta.so_hieu" /></label>
        <label>Loại <select v-model="meta.loai"><option v-for="(v, k) in LOAI" :key="k" :value="k">{{ v }}</option></select></label>
        <label>Ngày ban hành <input v-model="meta.ngay_ban_hanh" placeholder="YYYY-MM-DD" /></label>
        <label>Cơ quan ban hành <input v-model="meta.co_quan_ban_hanh" /></label>
        <label>Trạng thái <select v-model="meta.trang_thai"><option value="con_hieu_luc">Còn hiệu lực</option>
          <option value="het_hieu_luc">Hết hiệu lực</option><option value="bi_thay_the">Bị thay thế</option></select></label>
        <label>Thay thế bởi <input v-model="meta.thay_the_boi" /></label>
        <label>Độ mật <select v-model.number="meta.do_mat"><option v-for="(v, k) in DO_MAT" :key="k" :value="Number(k)">{{ v }}</option></select></label>
        <label>Phạm vi đơn vị <input v-model="donVi" /></label>
      </div>
      <p v-if="meta.tom_tat" class="muted">Tóm tắt (mô hình đề xuất): {{ meta.tom_tat }}</p>
    </div>
    <div class="card">
      <div class="row"><h3 class="grow">Nội dung Markdown</h3>
        <button class="btn ghost sm" @click="previewIds">Xem trước mã định danh (Luồng B)</button></div>
      <div class="editor">
        <textarea v-model="md" :disabled="!editable" />
        <div class="preview md" v-html="render(md)" />
      </div>
    </div>
    <div class="card row">
      <template v-if="editable">
        <button class="btn sec" @click="save">Lưu chỉnh sửa</button>
        <button class="btn" :disabled="job.status === 'cho_duyet_cap_2'" @click="approve('A')">Duyệt – Luồng A (tài liệu tham khảo)</button>
        <button class="btn" @click="approve('B')">{{ job.status === 'cho_duyet_cap_2' ? 'Duyệt cấp 2 – ghi vào kho chuẩn' : 'Duyệt cấp 1 – Luồng B (văn bản chuẩn)' }}</button>
        <button class="btn danger" @click="reject">Từ chối</button>
      </template>
      <button v-if="['loi', 'tu_choi'].includes(job.status)" class="btn sec" @click="retry">Xử lý lại</button>
      <span v-if="msg" :class="err ? 'err' : 'ok'">{{ msg }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import { render, DO_MAT, LOAI, STATUS, fmtDate } from '../md'
import { promptBox } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'

const route = useRoute()
const job = ref(null), md = ref(''), meta = ref({}), donVi = ref(''), msg = ref(''), err = ref(false)
const editable = computed(() => ['cho_duyet', 'cho_duyet_cap_2'].includes(job.value?.status))

onMounted(async () => { await load(); if (job.value?.status === 'dang_duyet') watchApproval() })
async function load() {
  job.value = await api.get('/ingest/jobs/' + route.params.id)
  md.value = job.value.markdown
  meta.value = { trang_thai: 'con_hieu_luc', ...job.value.meta }
  donVi.value = (meta.value.don_vi || ['chung']).join(',')
}
const metaOut = () => ({ ...meta.value, don_vi: donVi.value.split(',').map((s) => s.trim()).filter(Boolean) })
async function run(fn, ok) {
  err.value = false; msg.value = ''
  try { await fn(); msg.value = ok; await load() } catch (e) { err.value = true; msg.value = e.message }
}
const save = () => run(() => api.put('/ingest/jobs/' + job.value.id, { markdown: md.value, meta: metaOut() }), 'Đã lưu.')
// Duyệt: máy chủ kiểm tra điều kiện rồi chuyển phần lập chỉ mục / ghi kho cho tiến trình nền (trạng thái
// "dang_duyet"); trang thăm dò mỗi 2 giây tới khi xong hoặc báo lỗi.
let poll = null
onBeforeUnmount(() => clearInterval(poll))
function watchApproval() {
  clearInterval(poll)
  poll = setInterval(async () => {
    const j = await api.get('/ingest/jobs/' + route.params.id).catch(() => null)
    if (!j || j.status === 'dang_duyet') return
    clearInterval(poll)
    await load()
    if (j.status === 'da_duyet') { err.value = false; msg.value = 'Đã duyệt, lập chỉ mục xong.' + (j.target === 'B' ? ' Văn bản đã ghi vào kho chuẩn.' : '') }
    else if (j.error) { err.value = true; msg.value = j.error }
  }, 2000)
}
async function approve(track) {
  await run(async () => {
    await api.put('/ingest/jobs/' + job.value.id, { markdown: md.value, meta: metaOut() })
    const j = await api.post(`/ingest/jobs/${job.value.id}/approve`, { track })
    if (j.status === 'dang_duyet') watchApproval()
  }, track === 'B' && job.value.status === 'cho_duyet' ? 'Đã ghi nhận duyệt cấp 1.' : 'Đã tiếp nhận duyệt – đang ghi vào kho…')
}
async function reject() {
  const ly_do = await promptBox('Lý do từ chối', { placeholder: 'Nêu rõ lý do để người nạp tài liệu khắc phục…', ok: 'Từ chối' })
  if (ly_do) await run(() => api.post(`/ingest/jobs/${job.value.id}/reject`, { ly_do }), 'Đã từ chối.')
}
const retry = () => run(() => api.post(`/ingest/jobs/${job.value.id}/retry`), 'Đã đưa vào hàng đợi xử lý lại.')
async function previewIds() { md.value = await api.post(`/ingest/jobs/${job.value.id}/normalize-ids`) }
</script>
