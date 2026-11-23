<template>
  <div class="page">
  <PageHeader title="Nạp dữ liệu" icon="upload" desc="Tự động chuyển sang Markdown, làm sạch, trích thông tin mô tả, chấm điểm chất lượng; chỉ sử dụng sau khi kiểm duyệt." />
  <div class="card">
    <div :class="['drop', { over }]" @click="file.click()" @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop">
      <Icon name="upload" :size="28" />
      <p style="margin:.4rem 0 0"><b>Kéo thả tệp vào đây</b> hoặc bấm để chọn</p>
      <p class="small" style="margin:.2rem 0 0">PDF, DOCX, XLSX, PPTX, HTML, MD, TXT, CSV, ảnh quét</p>
      <p v-if="picked.length" class="small" style="margin:.4rem 0 0;color:var(--text)">Đã chọn: {{ picked.map((f) => f.name).join(', ') }}</p>
    </div>
    <input ref="file" type="file" multiple hidden accept=".pdf,.doc,.docx,.xlsx,.pptx,.html,.htm,.md,.txt,.csv,.png,.jpg,.jpeg,.tif,.tiff" @change="picked = [...file.files]" />
    <div class="row" style="margin-top:.8rem">
      <label class="muted small">Độ mật <select v-model.number="doMat">
        <option v-for="i in allowedLevels" :key="i" :value="i">{{ DO_MAT[i] }}</option></select></label>
      <label class="muted small" title="Văn bản đơn vị đã ban hành được dùng làm tiền lệ khi soạn văn bản, tham gia ý kiến">Nhóm <select v-model="nhom">
        <option value="">Tài liệu tham khảo</option><option value="van_ban_di">Văn bản đơn vị đã ban hành</option>
        <option value="van_ban_den">Văn bản đến</option></select></label>
      <label class="muted small grow">Phạm vi đơn vị <input v-model="donVi" style="width:100%" placeholder="chung hoặc mã đơn vị, cách nhau dấu phẩy" /></label>
      <button class="btn" :disabled="busy || !picked.length" @click="upload"><Icon name="upload" :size="15" /> Tải lên {{ picked.length || '' }}</button>
    </div>
    <p class="muted small">Độ mật tối đa hệ thống được phép xử lý: {{ DO_MAT[auth.user.system_max_clearance] }}.</p>
    <p v-if="msg" :class="err ? 'err' : 'ok'">{{ msg }}</p>
  </div>
  <div class="card">
    <div class="row" style="margin-bottom:.6rem"><h3 class="grow" style="margin:0">Tác vụ nạp</h3>
      <select v-model="status" @change="load"><option value="">Mọi trạng thái</option>
        <option v-for="s in ['moi','dang_xu_ly','cho_duyet','cho_duyet_cap_2','dang_duyet','da_duyet','tu_choi','loi']" :key="s" :value="s">{{ STATUS[s] }}</option></select>
      <button class="btn ghost" @click="load"><Icon name="refresh" :size="15" /> Làm mới</button></div>
    <table>
      <tr><th>Tệp</th><th>Thông tin</th><th>Chất lượng</th><th>Trạng thái</th><th></th></tr>
      <tr v-for="j in jobs" :key="j.id">
        <td>{{ j.filename }}<br><span class="muted small">{{ j.uploader }} · {{ fmtDate(j.created_at) }}</span></td>
        <td>{{ j.meta?.so_hieu }} {{ j.meta?.ten }}<br><span class="muted small">{{ LOAI[j.meta?.loai] || '' }}</span></td>
        <td><span v-if="j.quality?.diem != null" :class="['tag', j.quality.diem < 70 ? 'err' : 'ok']">{{ j.quality.diem }}</span>
          <span v-if="j.warnings?.length" class="warn small"> {{ j.warnings.length }} cảnh báo</span></td>
        <td><span :class="['tag', statusTag(j.status)]">{{ STATUS[j.status] }}</span><span v-if="j.doc_id" class="muted small"><br>{{ j.doc_id }}</span>
          <div v-if="j.error" class="err small">{{ j.error }}</div></td>
        <td><router-link v-if="has('reviewer', 'admin')" :to="'/kiem-duyet/' + j.id" class="btn ghost sm">Kiểm duyệt</router-link></td>
      </tr>
    </table>
    <p v-if="!jobs.length" class="empty">Chưa có tác vụ nạp.</p>
  </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import { auth, has } from '../auth'
import { DO_MAT, LOAI, STATUS, fmtDate } from '../md'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'

const file = ref(null), jobs = ref([]), doMat = ref(0), donVi = ref('chung'), nhom = ref(''), busy = ref(false)
const msg = ref(''), err = ref(false), status = ref(''), picked = ref([]), over = ref(false)
const statusTag = (s) => ({ da_duyet: 'ok', loi: 'err', tu_choi: 'err', cho_duyet: 'b', cho_duyet_cap_2: 'b' })[s] || ''
function onDrop(e) { over.value = false; picked.value = [...(e.dataTransfer?.files || [])] }
const allowedLevels = computed(() => [...Array(Math.min(auth.user.clearance, auth.user.system_max_clearance) + 1).keys()])
let timer
onMounted(() => { load(); timer = setInterval(() => { if (jobs.value.some((j) => ['moi', 'dang_xu_ly', 'dang_duyet'].includes(j.status))) load() }, 3000) })
onUnmounted(() => clearInterval(timer))
async function load() { jobs.value = await api.get('/ingest/jobs', { status: status.value }) }
async function upload() {
  const files = picked.value
  if (!files.length) return
  busy.value = true; err.value = false; msg.value = ''
  let ok = 0
  for (const f of files) {
    const fd = new FormData()
    fd.append('file', f); fd.append('do_mat', doMat.value); fd.append('don_vi', donVi.value); if (nhom.value) fd.append('nhom', nhom.value)
    try { await api.upload('/ingest/jobs', fd); ok++ } catch (e) { err.value = true; msg.value = `${f.name}: ${e.message}` }
  }
  if (!err.value) msg.value = `Đã tải lên ${ok} tệp, đang xử lý.`
  busy.value = false; file.value.value = ''; picked.value = []; load()
}
</script>
