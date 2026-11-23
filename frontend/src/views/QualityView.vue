<template>
  <div class="page">
    <PageHeader title="Giám định dữ liệu" icon="database"
                desc="Tác tử chạy định kỳ khi hệ thống rảnh: phát hiện tài liệu trùng, mâu thuẫn, hết hiệu lực, viện dẫn thiếu, lỗ hổng tri thức.">
      <button class="btn sm" :disabled="running" @click="runNow"><Icon name="play" :size="14" /> {{ running ? 'Đang giám định…' : 'Giám định ngay' }}</button>
    </PageHeader>

    <div class="kpis">
      <Kpi label="Phát hiện chưa xử lý" :value="openTotal" icon="alert" :state="sm.open_by_severity?.cao ? 'bad' : ''"
           :sub="`Cao ${sm.open_by_severity?.cao || 0} · Trung bình ${sm.open_by_severity?.trung_binh || 0} · Thấp ${sm.open_by_severity?.thap || 0}`" />
      <Kpi label="Đã xử lý" :value="sm.by_status?.da_xu_ly || 0" icon="check" :sub="`Bỏ qua: ${sm.by_status?.bo_qua || 0}`" />
      <Kpi label="Lượt gần nhất" :value="last ? fmtShort(last.started_at) : '—'" icon="clock"
           :sub="last ? `${last.mode === 'llm' ? 'Thuật toán + kiểm tra chéo bằng mô hình' : 'Tầng thuật toán'} · ${MODE_TRIGGER[last.trigger]}` : 'Chưa chạy'" />
      <Kpi label="Lịch chạy" :value="sm.schedule?.interval_min ? `${sm.schedule.interval_min} phút` : 'Thủ công'" icon="refresh"
           :sub="sm.schedule?.next_due ? 'Lượt kế tiếp ~ ' + fmtShort(sm.schedule.next_due) + ' (khi hệ thống rảnh)' : ''" />
      <Kpi label="Kiểm tra chéo bằng mô hình" :value="sm.schedule?.llm_allowed_now ? 'Đang cho phép' : 'Tạm hoãn'" icon="cpu"
           :sub="`Chế độ ${sm.schedule?.llm_mode} · giờ rảnh ${sm.schedule?.llm_hours} · ${sm.schedule?.hardware?.toUpperCase()}`" />
    </div>

    <div class="cols q-cols">
      <div class="card">
        <h3>Phát hiện theo loại (chưa xử lý)</h3>
        <BarList :rows="kindRows" />
        <template v-if="last">
          <h3 style="margin-top:1rem">Lượt giám định {{ last.status === 'dang_chay' ? 'đang chạy' : 'gần nhất' }}</h3>
          <StepTimeline :steps="last.plan" compact />
          <p v-if="last.error" class="err small">{{ last.error }}</p>
        </template>
      </div>

      <div>
        <div class="toolbar">
          <div class="seg narrow">
            <button v-for="s in STATUSES" :key="s.id" :class="{ on: status === s.id }" @click="status = s.id; load()">{{ s.label }}</button>
          </div>
          <select v-model="kind" @change="load"><option value="">Mọi loại</option>
            <option v-for="(v, k) in sm.labels" :key="k" :value="k">{{ v }}</option></select>
          <select v-model="severity" @change="load"><option value="">Mọi mức độ</option>
            <option value="cao">Cao</option><option value="trung_binh">Trung bình</option><option value="thap">Thấp</option></select>
        </div>
        <div v-for="f in findings" :key="f.id" :class="['finding', f.severity]">
          <div class="row">
            <span :class="['sev', f.severity]"><Icon :name="f.severity === 'cao' ? 'alert' : 'info'" :size="13" /> {{ SEVL[f.severity] }}</span>
            <span class="tag">{{ f.kind_label }}</span>
            <span v-if="f.verified === 'xac_nhan'" class="tag err" title="Mô hình kiểm tra chéo xác nhận"><Icon name="check" :size="12" /> Đã kiểm tra chéo</span>
            <span v-if="f.verified === 'bac_bo'" class="tag ok" title="Mô hình kiểm tra chéo cho rằng không mâu thuẫn">Có thể không mâu thuẫn</span>
            <span class="grow" /><span class="muted small">{{ fmtShort(f.last_seen) }}</span>
          </div>
          <b class="f-title">{{ f.title }}</b>
          <p class="muted small">{{ f.detail }}</p>
          <div v-if="f.data?.a" class="evidence"><div><span class="muted small">Văn bản chuẩn:</span> {{ f.data.a }}</div>
            <div><span class="muted small">Tài liệu khác:</span> {{ f.data.b }}</div>
            <div v-if="f.data.giai_thich" class="muted small"><Icon name="sparkle" :size="12" /> {{ f.data.giai_thich }}</div></div>
          <div v-if="f.data?.cau" class="evidence">{{ f.data.cau }}</div>
          <ul v-if="f.data?.cau_hoi" class="evidence small"><li v-for="q in f.data.cau_hoi" :key="q.q">{{ q.q }}
            <span class="muted">({{ q.ly_do === 'sai' ? 'bị đánh giá sai' : 'không có căn cứ' }}{{ q.gop_y ? ': ' + q.gop_y : '' }})</span></li></ul>
          <div v-if="f.data?.fix && Object.keys(f.data.fix).length" class="evidence small">Đề xuất sửa: <b>{{ Object.entries(f.data.fix).map(([k, v]) => `${k} = ${v}`).join('; ') }}</b></div>
          <div v-if="f.doc_ids?.length" class="muted small"><Icon name="file" :size="12" /> {{ f.doc_ids.join(', ') }}</div>
          <div v-if="f.resolution" class="muted small"><Icon name="check" :size="12" /> {{ f.resolution }} <template v-if="f.resolved_by">– {{ f.resolved_by }}</template></div>
          <div v-if="f.status === 'moi'" class="row f-actions">
            <button v-if="f.data?.fix && Object.keys(f.data.fix).length && f.data.track !== 'B'" class="btn sm" @click="apply(f)"><Icon name="check" :size="14" /> Áp dụng đề xuất</button>
            <button class="btn ghost sm" @click="resolve(f, 'da_xu_ly')">Đánh dấu đã xử lý</button>
            <button class="btn ghost sm" @click="resolve(f, 'bo_qua')">Bỏ qua</button>
          </div>
          <div v-else class="row f-actions"><button class="btn ghost sm" @click="resolve(f, 'moi')">Mở lại</button></div>
        </div>
        <p v-if="!findings.length" class="empty">Không có phát hiện nào ở bộ lọc này.</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import { promptBox, toast } from '../ui'
import BarList from '../components/charts/BarList.vue'
import Kpi from '../components/charts/Kpi.vue'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import StepTimeline from '../components/StepTimeline.vue'

const STATUSES = [{ id: 'moi', label: 'Chưa xử lý' }, { id: 'da_xu_ly', label: 'Đã xử lý' }, { id: 'bo_qua', label: 'Bỏ qua' }]
const SEVL = { cao: 'Cao', trung_binh: 'Trung bình', thap: 'Thấp' }
const MODE_TRIGGER = { lich: 'theo lịch', thu_cong: 'chạy thủ công' }
const sm = ref({}), findings = ref([]), status = ref('moi'), kind = ref(''), severity = ref('')
const last = computed(() => sm.value.runs?.[0])
const running = computed(() => last.value?.status === 'dang_chay')
const openTotal = computed(() => Object.values(sm.value.open_by_kind || {}).reduce((a, b) => a + b, 0))
const kindRows = computed(() => Object.entries(sm.value.open_by_kind || {}).sort((a, b) => b[1] - a[1])
  .map(([k, v]) => ({ label: sm.value.labels?.[k] || k, value: v })))
const fmtShort = (s) => (s ? new Date(s).toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '')

async function loadSummary() { sm.value = await api.get('/agent/quality/summary') }
async function load() { findings.value = await api.get('/agent/quality/findings', { status: status.value, kind: kind.value, severity: severity.value }) }
async function runNow() {
  try { await api.post('/agent/quality/runs'); toast('Đã bắt đầu lượt giám định.'); await loadSummary() } catch (e) { toast(e.message, 'err') }
}
async function resolve(f, st) {
  let resolution = ''
  if (st !== 'moi') {
    resolution = await promptBox(st === 'bo_qua' ? 'Lý do bỏ qua' : 'Ghi nhận xử lý', { message: f.title, required: false,
      placeholder: st === 'bo_qua' ? 'Ví dụ: hai câu nói về hai đối tượng khác nhau' : 'Ví dụ: đã thu hồi tài liệu cũ, cập nhật hiệu lực…', ok: 'Lưu' })
    if (resolution === null) return
  }
  await api.post(`/agent/quality/findings/${f.id}`, { status: st, resolution: resolution || '' })
  load(); loadSummary()
}
async function apply(f) {
  try { await api.post(`/agent/quality/findings/${f.id}/apply`); toast('Đã cập nhật thông tin mô tả tài liệu.'); load(); loadSummary() } catch (e) { toast(e.message, 'err') }
}
let timer
onMounted(() => { loadSummary(); load(); timer = setInterval(() => { loadSummary(); if (running.value) load() }, 4000) })
onBeforeUnmount(() => clearInterval(timer))
</script>
