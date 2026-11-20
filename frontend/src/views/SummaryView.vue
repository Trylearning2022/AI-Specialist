<template>
  <div class="page">
  <PageHeader title="Tổng hợp báo cáo" icon="layers" desc="Lập báo cáo theo mẫu từ nhiều văn bản; số liệu do chương trình tính, mô hình chỉ trình bày." />
  <div class="cols">
    <div class="card">
      <h3>Tạo báo cáo tổng hợp</h3>
      <label class="muted small">Tiêu đề</label>
      <input v-model="form.title" style="width:100%" placeholder="Ví dụ: Tổng hợp tình hình tuần 45" />
      <label class="muted small" style="display:block;margin-top:.6rem">Mẫu báo cáo (kỹ năng)</label>
      <select v-model="form.skill" style="width:100%">
        <option v-for="t in templates" :key="t.name" :value="t.name">{{ t.description }}</option>
      </select>
      <div v-for="p in currentTpl?.params || []" :key="p.ten" style="margin-top:.4rem">
        <label>{{ p.nhan }}</label> <input v-model="form.params[p.ten]" :type="p.kieu === 'date' ? 'date' : 'text'" />
      </div>
      <h3>Chọn văn bản ({{ form.doc_ids.length }})</h3>
      <div class="row">
        <input v-model="q" class="grow" placeholder="Lọc theo tên, số hiệu" @keyup.enter="loadDocs" />
        <select v-model="loai" @change="loadDocs"><option value="">Mọi loại</option>
          <option v-for="(v, k) in LOAI" :key="k" :value="k">{{ v }}</option></select>
        <button class="btn sec" @click="loadDocs">Lọc</button>
      </div>
      <div style="max-height:300px;overflow:auto;margin-top:.5rem">
        <label v-for="d in docs" :key="d.doc_id" style="display:block;padding:.2rem 0">
          <input v-model="form.doc_ids" type="checkbox" :value="d.doc_id" /> {{ d.so_hieu }} {{ d.title }}
          <span class="muted">({{ LOAI[d.loai] || d.loai }}, {{ d.ngay_ban_hanh }})</span>
        </label>
      </div>
      <button class="btn" style="margin-top:.6rem" :disabled="!form.title || !form.skill || !form.doc_ids.length" @click="create"><Icon name="layers" :size="15" /> Lập báo cáo</button>
      <p class="muted small">Số liệu tổng hợp được tính bằng chương trình từ số liệu trích trong văn bản; mô hình chỉ trình bày.</p>
      <p v-if="error" class="err">{{ error }}</p>
      <details v-if="currentTpl"><summary>Xem mẫu</summary><div class="md" v-html="render(currentTpl.template)" /></details>
    </div>
    <div>
      <div class="card">
        <h3>Báo cáo đã lập</h3>
        <table>
          <tr><th>Tiêu đề</th><th>Trạng thái</th><th></th></tr>
          <tr v-if="!jobs.length"><td colspan="3" class="muted">Chưa có báo cáo.</td></tr>
          <tr v-for="j in jobs" :key="j.id">
            <td>{{ j.title }}<br><span class="muted">{{ fmtDate(j.created_at) }}</span></td>
            <td>{{ STATUS[j.status] }} <span class="muted">{{ j.progress }}</span></td>
            <td><a @click="open(j.id)">Mở</a> · <a @click="remove(j.id)">Xóa</a></td>
          </tr>
        </table>
      </div>
      <div v-if="cur" class="card">
        <div class="row"><h3 class="grow">{{ cur.title }}</h3>
          <button class="btn ghost sm" @click="editing = !editing">{{ editing ? 'Xem' : 'Sửa' }}</button>
          <button v-if="editing" class="btn sm" @click="save">Lưu</button>
          <button class="btn sm" :disabled="cur.status !== 'xong'" @click="api.download(`/summary/jobs/${cur.id}/docx`, cur.title + '.docx')">Tải DOCX</button>
        </div>
        <p v-if="cur.error" class="err">{{ cur.error }}</p>
        <div v-for="w in cur.warnings" :key="w" class="warnbox">{{ w }}</div>
        <textarea v-if="editing" v-model="cur.result" rows="24" />
        <div v-else class="md preview" v-html="render(cur.result)" />
      </div>
    </div>
  </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import { render, LOAI, STATUS, fmtDate } from '../md'
import { confirmBox, toast } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'

const route = useRoute()
const templates = ref([]), docs = ref([]), jobs = ref([]), cur = ref(null), editing = ref(false)
const q = ref(''), loai = ref('bao_cao'), error = ref('')
const form = reactive({ title: '', skill: '', doc_ids: [], params: {} })
const currentTpl = computed(() => templates.value.find((t) => t.name === form.skill))
let timer

onMounted(async () => {
  templates.value = await api.get('/summary/templates')
  form.skill = templates.value[0]?.name || ''
  if (route.query.docs) { // mở từ trò chuyện: chọn sẵn các tài liệu được gợi ý
    form.doc_ids = String(route.query.docs).split(',').filter(Boolean)
    loai.value = ''
  }
  await Promise.all([loadDocs(), loadJobs()])
  timer = setInterval(async () => {
    if (jobs.value.some((j) => ['cho', 'dang_chay'].includes(j.status))) {
      await loadJobs()
      if (cur.value && ['cho', 'dang_chay'].includes(cur.value.status)) await open(cur.value.id)
    }
  }, 3000)
})
onUnmounted(() => clearInterval(timer))
async function loadDocs() { docs.value = await api.get('/ingest/documents', { q: q.value, loai: loai.value }) }
async function loadJobs() { jobs.value = await api.get('/summary/jobs') }
async function create() {
  error.value = ''
  try { const r = await api.post('/summary/jobs', { ...form }); await loadJobs(); await open(r.id) } catch (e) { error.value = e.message }
}
async function open(id) { cur.value = await api.get('/summary/jobs/' + id); editing.value = false }
async function save() { await api.put(`/summary/jobs/${cur.value.id}/result`, { result: cur.value.result }); editing.value = false; toast('Đã lưu báo cáo.') }
async function remove(id) {
  if (!(await confirmBox('Xóa báo cáo này?', { ok: 'Xóa', danger: true }))) return
  await api.del('/summary/jobs/' + id); if (cur.value?.id === id) cur.value = null; loadJobs()
}
</script>
