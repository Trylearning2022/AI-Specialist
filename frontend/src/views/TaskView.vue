<template>
  <div class="page">
    <PageHeader :title="t?.title || 'Tác vụ'" :icon="kind.icon" :desc="t ? `${kind.label} · tạo ${fmtDate(t.created_at)}` : ''">
      <template v-if="t">
        <span :class="['tstatus', 'lg', st.cls]">{{ st.label }}</span>
        <button v-if="['cho', 'dang_chay', 'cho_xac_nhan'].includes(t.status)" class="btn ghost sm" @click="cancel"><Icon name="stop" :size="14" /> Hủy</button>
        <button v-if="['loi', 'da_huy'].includes(t.status)" class="btn sm" @click="retry"><Icon name="refresh" :size="14" /> Chạy lại</button>
        <button v-if="t.status === 'xong'" class="btn sm" @click="exportDocx()"><Icon name="download" :size="14" /> Xuất DOCX</button>
        <button class="icon-btn" title="Xóa tác vụ" @click="remove"><Icon name="trash" /></button>
      </template>
    </PageHeader>
    <p v-if="error" class="err">{{ error }}</p>

    <div v-if="t" class="taskpage">
      <!-- ============ Cột trái: tiến trình ============ -->
      <aside class="card progress-card">
        <div class="ring-row">
          <svg class="ring" viewBox="0 0 44 44" aria-hidden="true">
            <circle cx="22" cy="22" r="19" class="ring-bg" />
            <circle cx="22" cy="22" r="19" :class="['ring-fg', st.cls]" :stroke-dasharray="`${(t.progress / 100) * 119.4} 119.4`" />
          </svg>
          <div><b class="ring-pct">{{ t.progress }}%</b>
            <div class="muted small">{{ t.started_at ? 'Thời gian: ' + elapsed(t) : 'Chưa bắt đầu' }}</div>
            <div v-if="t.status === 'cho' && t.queue_pos" class="muted small">Chờ {{ t.queue_pos }} tác vụ trước</div></div>
        </div>
        <p v-if="t.note" class="note"><Icon :name="t.status === 'cho_xac_nhan' ? 'pause' : 'info'" :size="14" /> {{ t.note }}</p>
        <StepTimeline :steps="t.plan" />
        <p v-if="t.status === 'loi'" class="err small">{{ t.error }}</p>
        <div v-for="w in t.warnings" :key="w" class="warnbox"><Icon name="alert" :size="14" /> {{ w }}</div>
        <details v-if="t.log?.length" class="tlog"><summary>Nhật ký tác vụ ({{ t.log.length }})</summary>
          <div v-for="(l, i) in t.log" :key="i"><span class="muted">{{ new Date(l.t).toLocaleTimeString('vi-VN') }}</span> {{ l.msg }}</div>
        </details>
      </aside>

      <!-- ============ Cột phải: duyệt dàn ý / kết quả ============ -->
      <section>
        <div v-if="t.status === 'cho_xac_nhan' && t.awaiting === 'dan_y'" class="card">
          <div class="row"><h3 class="grow">Duyệt dàn ý trước khi viết</h3>
            <button class="btn" :disabled="saving" @click="confirmOutline"><Icon name="check" :size="15" /> Xác nhận, viết văn bản</button></div>
          <p class="muted small">Sửa tên phần, ý chính (mỗi dòng một ý), chọn căn cứ cho từng phần. Mỗi phần chỉ được viết từ các căn cứ đã chọn.</p>
          <div v-for="(p, i) in outline" :key="i" class="ol-sec">
            <div class="row"><span class="ol-n">{{ i + 1 }}</span><input v-model="p.tieu_de" class="grow ol-title" />
              <button class="icon-btn xs" title="Bỏ phần này" @click="outline.splice(i, 1)"><Icon name="trash" :size="14" /></button></div>
            <p v-if="p.huong_dan" class="muted small">{{ p.huong_dan }}</p>
            <textarea v-model="p.ytext" rows="3" class="field" placeholder="Ý chính, mỗi dòng một ý" />
            <div class="ol-src">
              <span class="muted small">Căn cứ:</span>
              <button v-for="s in t.confirm_sources || []" :key="s.label" :class="['src-tog', { on: p.nguon.includes(s.label), b: s.nguon === 'B' }]"
                      :title="`${s.title} › ${s.breadcrumb}\n\n${s.trich}`" @click="toggle(p, s.label)">
                {{ s.label }} · {{ s.so_hieu || s.title }}</button>
            </div>
          </div>
          <button class="btn ghost sm" @click="outline.push({ tieu_de: 'Phần mới', huong_dan: '', ytext: '', nguon: [] })"><Icon name="plus" :size="14" /> Thêm phần</button>
        </div>

        <GopYConfirm v-else-if="t.status === 'cho_xac_nhan' && t.awaiting === 'tong_hop' && t.confirm"
                     :key="t.id" :task-id="t.id" :payload="t.confirm" @done="reload" />

        <div v-else-if="t.status !== 'xong'" class="card empty">
          <span v-if="['cho', 'dang_chay'].includes(t.status)" class="spin lg" />
          <p>{{ ['cho', 'dang_chay'].includes(t.status) ? 'Kết quả sẽ hiển thị khi tác vụ hoàn thành. Đồng chí có thể chuyển sang việc khác; tiến trình hiển thị ở thanh bên.' : 'Tác vụ chưa có kết quả.' }}</p>
        </div>

        <template v-else>
          <div class="tabs">
            <button v-for="x in tabs" :key="x.id" :class="{ on: tab === x.id }" @click="tab = x.id">{{ x.label }}
              <span v-if="x.n" class="seg-n">{{ x.n }}</span></button>
          </div>

          <!-- Báo cáo / văn bản (xem, sửa, xuất) -->
          <div v-if="tab === 'kq'" class="card">
            <div class="row" style="margin-bottom:.6rem">
              <div v-if="isDraft" class="seg narrow">
                <button :class="{ on: ban === 'sach' }" @click="ban = 'sach'">Bản sạch</button>
                <button :class="{ on: ban === 'can_cu' }" @click="ban = 'can_cu'">{{ isGopY ? 'Bản kèm nguồn tra cứu' : 'Bản kèm căn cứ' }}</button>
              </div>
              <span class="grow" />
              <button v-if="isDraft" class="btn ghost sm" :disabled="!!a.luu_kho" :title="a.luu_kho ? 'Đã gửi vào kho, chờ kiểm duyệt' : 'Sau khi văn bản được ký ban hành: đưa bản sạch vào kho để làm tiền lệ cho lần tham mưu sau'"
                      @click="archive"><Icon name="database" :size="14" /> {{ a.luu_kho ? 'Đã gửi vào kho' : 'Đưa vào kho văn bản đã ban hành' }}</button>
              <button class="btn ghost sm" @click="copy"><Icon name="copy" :size="14" /> Sao chép</button>
              <button class="btn ghost sm" @click="editing = !editing"><Icon name="edit" :size="14" /> {{ editing ? 'Xem' : 'Chỉnh sửa' }}</button>
              <button class="btn sm" @click="exportDocx(ban === 'can_cu' ? 'can_cu' : '')"><Icon name="download" :size="14" /> DOCX</button>
            </div>
            <div v-if="editing" class="editor">
              <textarea v-model="draft" />
              <div class="preview md" v-html="render(draft)" />
              <div class="row"><button class="btn sm" @click="save"><Icon name="check" :size="14" /> Lưu</button>
                <button class="btn ghost sm" @click="editing = false">Hủy</button></div>
            </div>
            <div v-else class="md doc-view" v-html="html" />
          </div>

          <!-- Tham gia ý kiến: danh sách ý kiến đã chọn -->
          <div v-if="tab === 'y-kien'" class="issues">
            <div v-for="m in (a.muc || []).filter((x) => x.chon !== false)" :key="m.id" :class="['issue', m.muc_do]">
              <div class="row"><span :class="['sev', m.muc_do]">{{ SEVL[m.muc_do] }}</span>
                <span class="muted small">{{ ASPECT[m.khia_canh] || m.khia_canh }} · {{ m.vi_tri }}</span></div>
              <p>{{ m.nhan_xet }}</p>
              <div v-if="m.de_nghi_sua" class="proposal"><Icon name="pen" :size="13" /> {{ m.de_nghi_sua }}</div>
              <div v-if="m.can_cu" class="muted small"><Icon name="scale" :size="12" /> {{ m.can_cu }}</div>
            </div>
          </div>

          <!-- Phân tích: vấn đề theo tiêu chí -->
          <div v-if="tab === 'van-de'" class="issues">
            <div class="toolbar"><div class="seg narrow">
              <button v-for="f in SEV" :key="f.id" :class="{ on: sev === f.id }" @click="sev = f.id">{{ f.label }} <span class="seg-n">{{ countSev(f.id) }}</span></button>
            </div></div>
            <div v-for="r in issues" :key="r.id" :class="['issue', r.muc_do_kq]">
              <div class="row"><span :class="['sev', r.muc_do_kq]"><Icon :name="r.muc_do_kq === 'cao' ? 'alert' : 'info'" :size="13" /> {{ SEVL[r.muc_do_kq] }}</span>
                <span class="muted small">{{ r.nhom }}</span></div>
              <b>{{ r.hoi }}</b>
              <p>{{ r.nhan_dinh }}</p>
              <div v-if="r.can_cu" class="muted small"><Icon name="scale" :size="12" /> Căn cứ đối chiếu: {{ r.can_cu }}</div>
              <blockquote v-for="q in r.trich_dan" :key="q">“{{ q }}”</blockquote>
              <div v-if="r.vi_tri?.length" class="muted small"><Icon name="file" :size="12" /> {{ r.vi_tri.join('; ') }}</div>
              <div v-if="r.kb?.length" class="muted small"><Icon name="database" :size="12" /> Liên quan: {{ r.kb.map((k) => k.so_hieu || k.title).join('; ') }}</div>
              <div v-if="r.de_xuat" class="proposal"><Icon name="sparkle" :size="13" /> {{ r.de_xuat }} <span class="muted">(tham khảo)</span></div>
            </div>
            <p v-if="!issues.length" class="empty">Không có vấn đề ở mức này.</p>
          </div>

          <!-- Phân tích: nhiệm vụ, thời hạn -->
          <div v-if="tab === 'nhiem-vu'" class="card">
            <h3>Nhiệm vụ được giao</h3>
            <table><tr><th>Chủ thể</th><th>Việc</th><th>Nội dung</th><th>Vị trí</th></tr>
              <tr v-for="x in a.assignments" :key="x.cau"><td><b>{{ x.chu_the }}</b></td><td>{{ x.hanh_dong }}</td><td>{{ x.cau }}</td><td class="muted small">{{ x.vi_tri }}</td></tr></table>
            <h3 style="margin-top:1.2rem">Mốc thời gian, thời hạn</h3>
            <table><tr><th>Mốc</th><th>Nội dung</th><th>Vị trí</th></tr>
              <tr v-for="d in a.deadlines" :key="d.cau"><td><b>{{ d.moc.join(', ') }}</b></td><td>{{ d.cau }}</td><td class="muted small">{{ d.vi_tri }}</td></tr></table>
          </div>

          <!-- Phân tích: đối chiếu cơ sở tri thức -->
          <div v-if="tab === 'doi-chieu'" class="card">
            <h3>Văn bản được viện dẫn</h3>
            <table><tr><th>Số hiệu</th><th>Trong kho văn bản chuẩn</th><th>Hiệu lực</th></tr>
              <tr v-for="r in a.refs" :key="r.so_hieu"><td><b>{{ r.so_hieu }}</b></td>
                <td><span v-if="r.co_trong_kho" class="tag ok"><Icon name="check" :size="12" /> Có</span><span v-else class="tag err">Chưa có</span> {{ r.ten }}</td>
                <td>{{ r.co_trong_kho ? (STATUS[r.trang_thai] || r.trang_thai || 'Còn hiệu lực') : '—' }}</td></tr></table>
            <h3 style="margin-top:1.2rem">Tài liệu nội bộ liên quan</h3>
            <div v-for="x in a.related" :key="x.doc_id + x.breadcrumb" class="src"><b>{{ x.title }}</b> <span class="muted small">› {{ x.breadcrumb }}</span>
              <span v-if="x.nguon === 'B'" class="tag b">chuẩn</span></div>
          </div>

          <!-- Tổng hợp: bảng số liệu; Soạn thảo: căn cứ -->
          <div v-if="tab === 'so-lieu'" class="card">
            <table><tr><th>Chỉ tiêu</th><th>Đơn vị tính</th><th class="num-c">Tổng</th><th>Chi tiết</th></tr>
              <tr v-for="r in a.table" :key="r.chi_tieu + r.don_vi_tinh"><td>{{ r.chi_tieu }}</td><td>{{ r.don_vi_tinh }}</td><td class="num-c"><b>{{ r.tong }}</b></td>
                <td class="muted small">{{ r.chi_tiet.map((c) => `${c.nguon}: ${c.gia_tri}`).join('; ') }}</td></tr></table>
            <p class="muted small">Số liệu do chương trình tính từ các giá trị có thật trong văn bản nguồn.</p>
          </div>
          <div v-if="tab === 'can-cu'" class="card">
            <div v-for="s in a.sources" :key="s.label" class="src"><span class="num">{{ s.label.slice(1) }}</span>
              <b>{{ s.title }}</b> <span class="muted small">› {{ s.breadcrumb }} {{ s.so_hieu ? '(' + s.so_hieu + ')' : '' }}</span>
              <span v-if="s.nguon === 'B'" class="tag b">văn bản chuẩn</span>
              <div class="muted small clamp">{{ s.trich }}</div></div>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { STATUS, fmtDate, render } from '../md'
import { TASK_KIND, TASK_STATUS, elapsed, refreshActive, useTask } from '../tasks'
import { confirmBox, toast } from '../ui'
import GopYConfirm from '../components/GopYConfirm.vue'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import StepTimeline from '../components/StepTimeline.vue'

const route = useRoute(), router = useRouter()
const { task: t, error, reload } = useTask(() => route.params.id)
const kind = computed(() => TASK_KIND[t.value?.kind] || { label: '', icon: 'tasks' })
const st = computed(() => TASK_STATUS[t.value?.status] || TASK_STATUS.cho)
const a = computed(() => t.value?.artifacts || {})
const tab = ref('kq'), ban = ref('sach'), editing = ref(false), draft = ref(''), saving = ref(false), sev = ref('')
const outline = ref([])
const SEV = [{ id: '', label: 'Tất cả' }, { id: 'cao', label: 'Cao' }, { id: 'trung_binh', label: 'Trung bình' }, { id: 'thap', label: 'Thấp' }]
const SEVL = { cao: 'Mức độ cao', trung_binh: 'Trung bình', thap: 'Thấp' }

const tabs = computed(() => {
  const k = t.value?.kind
  if (k === 'phan_tich') {
    const yes = (a.value.results || []).filter((r) => r.de_cap)
    return [{ id: 'kq', label: 'Báo cáo phân tích' }, { id: 'van-de', label: 'Vấn đề theo tiêu chí', n: yes.length },
      { id: 'nhiem-vu', label: 'Nhiệm vụ, thời hạn', n: (a.value.assignments?.length || 0) + (a.value.deadlines?.length || 0) },
      { id: 'doi-chieu', label: 'Đối chiếu cơ sở tri thức', n: a.value.refs?.length }]
  }
  if (isGopY.value) return [{ id: 'kq', label: 'Công văn tham gia ý kiến' }, { id: 'y-kien', label: 'Ý kiến', n: (a.value.muc || []).filter((x) => x.chon !== false).length }]
  if (k === 'soan_thao') return [{ id: 'kq', label: 'Dự thảo' }, { id: 'can-cu', label: 'Căn cứ', n: a.value.sources?.length }]
  return [{ id: 'kq', label: 'Báo cáo tổng hợp' }, { id: 'so-lieu', label: 'Bảng số liệu', n: a.value.table?.length }]
})
const isDraft = computed(() => ['soan_thao', 'gop_y'].includes(t.value?.kind))
// Công văn – hình thức tham gia ý kiến dự thảo (tác vụ soạn thảo che_do=gop_y; kind gop_y của bản 1.4.0)
const isGopY = computed(() => t.value?.kind === 'gop_y' || t.value?.che_do === 'gop_y')
const ASPECT = { thuat_ngu: 'Thuật ngữ', can_cu: 'Căn cứ pháp lý', nhiem_vu: 'Nhiệm vụ của ngành', ky_thuat: 'Kỹ thuật', khac: 'Khác' }
const text = computed(() => (isDraft.value && ban.value === 'can_cu' ? a.value.ban_can_cu : t.value?.result) || '')
const html = computed(() => render(text.value).replace(/\[(S\d+(?:,\s*S\d+)*)\]/g, '<sup class="scite">[$1]</sup>'))
const issues = computed(() => (a.value.results || []).filter((r) => r.de_cap && (!sev.value || r.muc_do_kq === sev.value)))
const countSev = (s) => (a.value.results || []).filter((r) => r.de_cap && (!s || r.muc_do_kq === s)).length

watch(() => t.value?.status, (s, old) => {
  if (s === 'cho_xac_nhan' && t.value.confirm?.phan) {
    outline.value = t.value.confirm.phan.map((p) => ({ ...p, ytext: (p.y || []).join('\n'), nguon: [...(p.nguon || [])] }))
  }
  if (old && s !== old) refreshActive()
})
watch(editing, (e) => { if (e) draft.value = text.value })

function toggle(p, lb) { p.nguon = p.nguon.includes(lb) ? p.nguon.filter((x) => x !== lb) : [...p.nguon, lb] }
async function confirmOutline() {
  saving.value = true
  try {
    const phan = outline.value.map((p) => ({ tieu_de: p.tieu_de, huong_dan: p.huong_dan, nguon: p.nguon,
      y: p.ytext.split('\n').map((x) => x.trim()).filter(Boolean) }))
    await api.post(`/agent/tasks/${t.value.id}/confirm`, { phan })
    toast('Đã xác nhận dàn ý – đang viết văn bản.'); reload()
  } catch (e) { toast(e.message, 'err') } finally { saving.value = false }
}
async function cancel() {
  if (!(await confirmBox('Hủy tác vụ này?', { ok: 'Hủy tác vụ', danger: true }))) return
  await api.post(`/agent/tasks/${t.value.id}/cancel`); reload(); refreshActive()
}
async function retry() { await api.post(`/agent/tasks/${t.value.id}/retry`); toast('Đang chạy lại từ bước chưa hoàn thành.'); reload(); refreshActive() }
async function remove() {
  if (!(await confirmBox('Xóa tác vụ và kết quả?', { ok: 'Xóa', danger: true }))) return
  await api.del(`/agent/tasks/${t.value.id}`); refreshActive(); router.push('/tac-vu')
}
async function save() {
  await api.put(`/agent/tasks/${t.value.id}/result`, { result: draft.value, ban: isDraft.value && ban.value === 'can_cu' ? 'can_cu' : '' })
  editing.value = false; toast('Đã lưu.'); reload()
}
function exportDocx(b = '') {
  api.download(`/agent/tasks/${t.value.id}/docx${b ? '?ban=' + b : ''}`, `${t.value.title.slice(0, 80)}.docx`).catch((e) => toast(e.message, 'err'))
}
async function archive() {
  const so = window.prompt('Số, ký hiệu văn bản đã ban hành (để trống nếu chưa có):', '')
  if (so === null) return
  try {
    const r = await api.post(`/agent/tasks/${t.value.id}/archive`, { so_hieu: so.trim(), ngay_ban_hanh: new Date().toISOString().slice(0, 10) })
    toast(`Đã gửi vào kho văn bản đã ban hành (tác vụ nạp ${r.job_id.slice(0, 8)}) – chờ kiểm duyệt.`); reload()
  } catch (e) { toast(e.message, 'err') }
}
function copy() { navigator.clipboard?.writeText(text.value); toast('Đã sao chép.') }
</script>
