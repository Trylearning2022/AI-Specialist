<template>
  <div class="page">
    <PageHeader title="Giám sát hệ thống" icon="activity" desc="Người dùng, hiệu năng trả lời, tốc độ mô hình, tác vụ, tài nguyên máy chủ; nhật ký hệ thống và kiểm toán.">
      <div class="seg narrow">
        <button v-for="r in RANGES" :key="r.h" :class="{ on: hours === r.h }" @click="hours = r.h; load()">{{ r.label }}</button>
      </div>
      <label class="small row"><input v-model="auto" type="checkbox" /> Tự làm mới</label>
      <button class="icon-btn" title="Làm mới" @click="load"><Icon name="refresh" /></button>
    </PageHeader>

    <div class="tabs">
      <button v-for="x in tabs" :key="x.id" :class="{ on: tab === x.id }" @click="go(x.id)"><Icon :name="x.icon" :size="15" /> {{ x.label }}</button>
    </div>

    <!-- ===================== Tổng quan ===================== -->
    <template v-if="tab === 'tong-quan' && o">
      <div class="kpis">
        <Kpi label="Câu hỏi" :value="k.cau_hoi" icon="chat" :spark="o.series.map((s) => s.cau_hoi)" :sub="`${k.nguoi_dung} người dùng · hỏi lại ${k.hoi_lai}`" />
        <Kpi label="Thời gian trả lời TB" :value="k.tg_tb_s" unit="giây" icon="clock" :spark="o.series.map((s) => s.tg_tb_s)"
             :sub="`P95 ${k.tg_p95_s ?? '—'} giây · ra chữ đầu ${k.tg_chu_dau_s ?? '—'} giây`" :state="k.tg_p95_s > 120 ? 'warn' : ''" />
        <Kpi label="Tốc độ sinh của mô hình" :value="k.toc_do_sinh" unit="token/giây" icon="gauge" :spark="o.series.map((s) => s.toc_do_sinh)"
             :sub="`${k.goi_mo_hinh} lượt gọi · ${fmtN(k.token_vao)} token vào · ${fmtN(k.token_ra)} ra`" />
        <Kpi label="Đạt kiểm chứng" :value="k.ty_le_kiem_chung" unit="%" icon="check"
             :sub="`Không có căn cứ ${k.ty_le_khong_can_cu ?? 0}% · chặn ATTT ${k.chan_attt}`" :state="k.ty_le_kiem_chung != null && k.ty_le_kiem_chung < 70 ? 'warn' : ''" />
        <Kpi label="Lỗi" :value="k.loi_5xx + k.loi_mo_hinh" icon="alert" :spark="o.series.map((s) => s.loi)"
             :sub="`Dịch vụ ${k.loi_5xx} · mô hình ${k.loi_mo_hinh} · tác vụ ${k.tac_vu_loi}`" :state="k.loi_5xx + k.loi_mo_hinh > 0 ? 'bad' : ''" />
      </div>

      <div class="cols">
        <div class="card"><h3>Số câu hỏi theo thời gian</h3>
          <LineChart :series="[{ name: 'Câu hỏi', values: o.series.map((s) => s.cau_hoi) }]" :labels="o.series.map((s) => s.t)" unit="câu" /></div>
        <div class="card"><h3>Thời gian trả lời (giây)</h3>
          <LineChart :series="[{ name: 'Trung bình', values: o.series.map((s) => s.tg_tb_s) }, { name: 'P95', values: o.series.map((s) => s.tg_p95_s) }]"
                     :labels="o.series.map((s) => s.t)" unit="giây" /></div>
      </div>
      <div class="cols">
        <div class="card"><h3>Lượt trả lời theo luồng xử lý</h3>
          <BarList :rows="o.routes.map((r) => ({ label: ROUTE[r.route] || r.route, value: r.so_luot, text: `${r.so_luot} · TB ${r.tg_tb_s} giây`,
                                                 title: `P95 ${r.tg_p95_s} giây · đạt kiểm chứng ${r.ty_le_kiem_chung}%` }))" />
        </div>
        <div class="card"><h3>Tốc độ sinh của mô hình (token/giây)</h3>
          <LineChart :series="[{ name: 'Token/giây', values: o.series.map((s) => s.toc_do_sinh) }]" :labels="o.series.map((s) => s.t)" unit="token/giây" :height="170" />
        </div>
      </div>
      <div class="cols three">
        <div class="card"><h3>Tình trạng dịch vụ</h3>
          <div class="svc-grid">
            <div v-for="s in health.services || []" :key="s.name" :class="['svc', { bad: !s.ok }]" :title="s.error || ''">
              <Icon :name="s.ok ? 'check' : 'x'" :size="13" /><b>{{ SVC[s.name] || s.name }}</b><span class="muted small">{{ s.ok ? s.ms + ' ms' : (s.error || 'lỗi') }}</span>
            </div>
          </div>
          <p v-if="health.services?.find((s) => s.name === 'mo-hinh')?.models?.length" class="muted small">Mô hình: {{ health.services.find((s) => s.name === 'mo-hinh').models.join(', ') }}</p>
        </div>
        <div class="card"><h3>Tài nguyên máy chủ</h3>
          <Meter label="CPU" :pct="o.system.cpu_pct" :sub="`${o.system.cpu_count} lõi${o.system.load ? ' · tải ' + o.system.load.join(' / ') : ''}`" />
          <Meter label="Bộ nhớ" :pct="o.system.ram_pct" :sub="o.system.ram_total_gb ? `${o.system.ram_used_gb}/${o.system.ram_total_gb} GB` : ''" />
          <Meter label="Ổ đĩa dữ liệu" :pct="o.system.disk_pct" :sub="o.system.disk_total_gb ? `${o.system.disk_used_gb}/${o.system.disk_total_gb} GB` : ''" />
        </div>
        <div class="card"><h3>Tác vụ dài</h3>
          <div class="muted small">Đang hỏi đáp trực tiếp: <b>{{ queue.interactive ?? 0 }}</b> · đang chờ/chạy: <b>{{ (queue.by_status?.cho || 0) + (queue.by_status?.dang_chay || 0) }}</b>
            · chờ xác nhận: <b>{{ queue.by_status?.cho_xac_nhan || 0 }}</b></div>
          <div v-for="t in queue.active || []" :key="t.id" class="q-row">
            <Icon :name="TASK_KIND[t.kind]?.icon || 'tasks'" :size="14" /><span class="grow clamp1">{{ t.title }} <span class="muted small">· {{ t.owner }}</span></span>
            <span class="tr-bar sm"><i :style="{ width: t.progress + '%' }" /></span></div>
          <table v-if="o.tasks.length" style="margin-top:.6rem"><tr><th>Loại</th><th>Lượt</th><th>Lỗi</th><th>TB (phút)</th></tr>
            <tr v-for="t in o.tasks" :key="t.kind"><td>{{ TASK_KIND[t.kind]?.label || (t.kind === 'giam_dinh' ? 'Giám định dữ liệu' : t.kind) }}</td><td>{{ t.so_luot }}</td><td>{{ t.loi }}</td><td>{{ t.tg_tb_phut }}</td></tr></table>
        </div>
      </div>
    </template>

    <!-- ===================== Người dùng ===================== -->
    <div v-if="tab === 'nguoi-dung' && o" class="cols">
      <div class="card"><h3>Số câu hỏi theo người dùng</h3>
        <BarList :rows="o.users.slice(0, 15).map((u) => ({ label: u.user, value: u.cau_hoi }))" /></div>
      <div class="card"><h3>Chi tiết</h3>
        <table><tr><th>Người dùng</th><th>Câu hỏi</th><th>TB (giây)</th><th>Không có căn cứ</th><th>Luồng chính</th><th>Lần cuối</th></tr>
          <tr v-for="u in o.users" :key="u.user"><td><b>{{ u.user }}</b></td><td>{{ u.cau_hoi }}</td><td>{{ u.tg_tb_s }}</td><td>{{ u.khong_can_cu }}</td>
            <td class="small">{{ u.luong.map(([r, n]) => `${ROUTE[r] || r} (${n})`).join(', ') }}</td><td class="small muted">{{ new Date(u.lan_cuoi * 1000).toLocaleString('vi-VN') }}</td></tr></table>
        <p v-if="!o.users.length" class="empty">Chưa có hoạt động trong khoảng thời gian này.</p>
      </div>
    </div>

    <!-- ===================== Hiệu năng ===================== -->
    <template v-if="tab === 'hieu-nang' && o">
      <div class="card"><h3>Thời gian theo loại lượt gọi mô hình</h3>
        <p class="muted small">Thời gian trả lời trên CPU ≈ token vào ÷ tốc độ đọc + token ra ÷ tốc độ sinh. Lượt gọi có token vào lớn nên giảm ngân sách ngữ cảnh (CTX_BUDGET_SOURCES, AGENT_PART_TOKENS).</p>
        <table><tr><th>Loại lượt gọi</th><th>Số lượt</th><th>TB (giây)</th><th>Token vào TB</th><th>Token ra TB</th><th>Token/giây</th><th>Lỗi</th></tr>
          <tr v-for="r in o.llm_tasks" :key="r.task"><td><code>{{ r.task }}</code></td><td>{{ r.so_luot }}</td><td><b>{{ r.tg_tb_s }}</b></td><td>{{ r.token_vao_tb }}</td><td>{{ r.token_ra_tb }}</td>
            <td>{{ r.toc_do_sinh ?? '—' }}</td><td :class="{ err: r.loi }">{{ r.loi }}</td></tr></table>
      </div>
      <div class="card"><h3>Yêu cầu theo dịch vụ</h3>
        <table><tr><th>Dịch vụ</th><th>Số yêu cầu</th><th>P95 (ms)</th><th>Lỗi 4xx</th><th>Lỗi 5xx</th></tr>
          <tr v-for="s in o.services" :key="s.service"><td>{{ SVC[s.service] || s.service }}</td><td>{{ s.so_yeu_cau }}</td><td>{{ s.p95_ms }}</td><td>{{ s.loi_4xx }}</td>
            <td :class="{ err: s.loi_5xx }">{{ s.loi_5xx }}</td></tr></table>
      </div>
    </template>

    <!-- ===================== Nhật ký hệ thống ===================== -->
    <div v-if="tab === 'nhat-ky'" class="card logs-card">
      <div class="toolbar">
        <div class="lvl-chips">
          <button v-for="l in LEVELS" :key="l" :class="['lvl', l.toLowerCase(), { on: levels.includes(l) }]" @click="toggleLevel(l)">{{ l }}
            <span class="seg-n">{{ logs.stats?.[l] || 0 }}</span></button>
        </div>
        <select v-model="lsvc" @change="loadLogs"><option value="">Mọi dịch vụ</option><option v-for="s in logs.services" :key="s" :value="s">{{ s }}</option></select>
        <input v-model="lq" placeholder="Tìm trong nhật ký…" @keyup.enter="loadLogs" />
        <label class="small row"><input v-model="live" type="checkbox" /> Trực tiếp</label>
      </div>
      <p v-if="logErr" class="err">{{ logErr }}</p>
      <div class="logview">
        <div v-for="r in logs.rows" :key="r.id" :class="['logline', r.level?.toLowerCase()]" @click="r.open = !r.open">
          <span class="lt">{{ new Date(r.ts * 1000).toLocaleString('vi-VN') }}</span>
          <span :class="['lvl-b', r.level?.toLowerCase()]">{{ r.level }}</span>
          <span class="ls">{{ r.service }}</span>
          <span class="lm">{{ r.event ? `[${r.event}] ` : '' }}{{ r.msg }}</span>
          <pre v-if="r.open && r.exc" class="lexc">{{ r.exc }}</pre>
          <div v-if="r.open" class="muted small">logger: {{ r.logger }}</div>
        </div>
        <p v-if="!logs.rows?.length" class="empty">Không có bản ghi.</p>
      </div>
    </div>

    <!-- ===================== Kiểm toán ===================== -->
    <div v-if="tab === 'kiem-toan'" class="card">
      <div class="toolbar">
        <input v-model="af.actor" placeholder="Người thực hiện" /><input v-model="af.action" placeholder="Hành động (tiền tố)" />
        <button class="btn sec" @click="loadAudit">Lọc</button>
        <button class="btn sec" @click="verifyAudit"><Icon name="shield" :size="14" /> Kiểm tra toàn vẹn chuỗi băm</button>
        <span v-if="verify" :class="verify.ok ? 'ok' : 'err'">{{ verify.ok ? `Toàn vẹn (${verify.checked} bản ghi)` : `Phát hiện sai lệch tại bản ghi ${verify.broken_at}` }}</span>
      </div>
      <div v-if="actions.by_action" class="cols" style="margin-bottom:1rem">
        <div><h3>Hành động ({{ hours >= 24 ? hours / 24 + ' ngày' : hours + ' giờ' }})</h3>
          <BarList :rows="Object.entries(actions.by_action).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([k, v]) => ({ label: k, value: v }))" /></div>
        <div><h3>Người thực hiện</h3>
          <BarList :rows="Object.entries(actions.by_actor).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([k, v]) => ({ label: k, value: v, color: 'var(--series-2)' }))" /></div>
      </div>
      <p v-if="auditErr" class="err">{{ auditErr }}</p>
      <table>
        <tr><th>Thời điểm</th><th>Người</th><th>Hành động</th><th>Đối tượng</th><th>Chi tiết</th></tr>
        <tr v-for="x in audit" :key="x.id"><td class="small">{{ fmtDate(x.ts) }}</td><td>{{ x.actor }}</td><td><code>{{ x.action }}</code></td><td class="small">{{ x.resource }}</td>
          <td class="muted" style="font-size:.8rem;max-width:420px;word-break:break-all">{{ JSON.stringify(x.detail) }}</td></tr>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { has } from '../auth'
import { fmtDate } from '../md'
import { TASK_KIND } from '../tasks'
import BarList from '../components/charts/BarList.vue'
import Kpi from '../components/charts/Kpi.vue'
import LineChart from '../components/charts/LineChart.vue'
import Meter from '../components/charts/Meter.vue'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'

const RANGES = [{ h: 1, label: '1 giờ' }, { h: 24, label: '24 giờ' }, { h: 168, label: '7 ngày' }, { h: 720, label: '30 ngày' }]
const ROUTE = { tra_cuu: 'Tra cứu tài liệu', chinh_xac: 'Nguyên văn', ho_tro: 'Hỗ trợ kỹ thuật', tim_tai_lieu: 'Tìm tài liệu', chao_hoi: 'Trò chuyện',
  tong_hop: 'Tổng hợp', phan_tich: 'Phân tích', soan_thao: 'Soạn thảo', tac_tu: 'Nhiều bước', lam_ro: 'Hỏi lại', bao_ve: 'Chặn ATTT' }
const SVC = { orchestrator: 'Điều phối', search: 'Tìm kiếm', exact: 'Văn bản chuẩn', ingest: 'Nạp dữ liệu', summary: 'Tổng hợp (cũ)',
  support: 'Hỗ trợ', agent: 'Tác vụ dài', audit: 'Kiểm toán', gateway: 'Cổng API', 'mo-hinh': 'Máy chủ mô hình' }
const LEVELS = ['ERROR', 'WARNING', 'INFO']
const tabs = [{ id: 'tong-quan', label: 'Tổng quan', icon: 'gauge' }, { id: 'nguoi-dung', label: 'Người dùng', icon: 'users' },
  { id: 'hieu-nang', label: 'Hiệu năng', icon: 'cpu' },
  ...(has('admin') ? [{ id: 'nhat-ky', label: 'Nhật ký hệ thống', icon: 'terminal' }, { id: 'kiem-toan', label: 'Kiểm toán', icon: 'shield' }] : [])]
const tab = ref('tong-quan'), hours = ref(24), auto = ref(true), o = ref(null), health = ref({}), queue = ref({})
const logs = ref({}), levels = ref(['ERROR', 'WARNING', 'INFO']), lsvc = ref(''), lq = ref(''), live = ref(true), logErr = ref('')
const audit = ref([]), verify = ref(null), auditErr = ref(''), af = reactive({ actor: '', action: '' }), actions = ref({})
const k = computed(() => o.value?.kpi || {})
const fmtN = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + ' tr' : n >= 1e3 ? (n / 1e3).toFixed(1) + ' nghìn' : n ?? 0)

async function load() {
  try {
    const [ov, h, q] = await Promise.all([api.get('/audit/monitor/overview', { hours: hours.value }), api.get('/audit/monitor/health'),
      api.get('/agent/queue').catch(() => ({}))])
    o.value = ov; health.value = h; queue.value = q
  } catch (e) { logErr.value = e.message }
  if (tab.value === 'kiem-toan') loadAudit()
}
async function loadLogs() {
  try { logs.value = await api.get('/audit/monitor/logs', { level: levels.value.join(','), service: lsvc.value, q: lq.value }); logErr.value = '' } catch (e) { logErr.value = e.message }
}
function toggleLevel(l) { levels.value = levels.value.includes(l) ? levels.value.filter((x) => x !== l) : [...levels.value, l]; loadLogs() }
async function loadAudit() {
  try {
    audit.value = await api.get('/audit/logs', { ...af, hours: hours.value })
    actions.value = await api.get('/audit/actions', { hours: hours.value })
  } catch (e) { auditErr.value = e.message }
}
async function verifyAudit() { verify.value = await api.get('/audit/verify') }
function go(t) { tab.value = t; if (t === 'nhat-ky') loadLogs(); if (t === 'kiem-toan') loadAudit() }

let t1, t2
onMounted(() => {
  load()
  t1 = setInterval(() => { if (auto.value && tab.value !== 'nhat-ky') load() }, 30000)
  t2 = setInterval(() => { if (live.value && tab.value === 'nhat-ky') loadLogs() }, 5000)
})
onBeforeUnmount(() => { clearInterval(t1); clearInterval(t2) })
watch(hours, () => { if (tab.value === 'kiem-toan') loadAudit() })
</script>
