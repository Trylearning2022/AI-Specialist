<template>
  <div class="page">
    <PageHeader :title="meta.title" :icon="meta.icon" :desc="meta.desc">
      <router-link to="/tac-vu" class="btn ghost sm"><Icon name="tasks" :size="14" /> Tác vụ của tôi</router-link>
    </PageHeader>

    <div class="newtask">
      <div class="card">
        <!-- ===================== Phân tích văn bản ===================== -->
        <template v-if="kind === 'phan_tich'">
          <h3>1. Văn bản cần phân tích</h3>
          <div class="seg narrow" style="margin-bottom:.7rem">
            <button :class="{ on: src === 'file' }" @click="src = 'file'">Tải tệp lên</button>
            <button :class="{ on: src === 'doc' }" @click="src = 'doc'">Tài liệu trong kho</button>
            <button :class="{ on: src === 'text' }" @click="src = 'text'">Dán nội dung</button>
          </div>
          <FileDrop v-if="src === 'file'" v-model="files" :multiple="false" />
          <DocPicker v-if="src === 'doc'" v-model="docs" :multiple="false" />
          <textarea v-if="src === 'text'" v-model="f.text" rows="10" class="field" placeholder="Dán toàn văn văn bản cần phân tích (tối thiểu 80 ký tự)…" />
          <h3>2. Bộ tiêu chí phân tích của ngành</h3>
          <div class="choice-grid">
            <label v-for="c in cat.criteria" :key="c.name" :class="['choice', { on: f.bo_tieu_chi === c.name }]">
              <input v-model="f.bo_tieu_chi" type="radio" :value="c.name" />
              <b>{{ c.description }}</b><span class="muted small">{{ c.so_tieu_chi }} tiêu chí · {{ c.nhom.slice(0, 4).join(', ') }}{{ c.nhom.length > 4 ? '…' : '' }}</span>
            </label>
          </div>
          <h3>3. Yêu cầu riêng (tùy chọn)</h3>
          <input v-model="f.yeu_cau" class="field" placeholder="Ví dụ: Văn bản ảnh hưởng thế nào tới việc cấp phát chứng thư số của đơn vị?" />
          <p class="muted small">Yêu cầu riêng được đưa thành tiêu chí đầu tiên của báo cáo.</p>
        </template>

        <!-- ===================== Soạn văn bản tham mưu ===================== -->
        <template v-if="kind === 'soan_thao'">
          <h3>1. Loại văn bản</h3>
          <div class="choice-grid">
            <label v-for="d in cat.drafts" :key="d.name" :class="['choice', { on: f.mau === d.name }]">
              <input v-model="f.mau" type="radio" :value="d.name" />
              <b>{{ d.ten_loai }}</b><span class="muted small">{{ d.description }}</span>
              <span class="small">{{ d.dan_y.join(' · ') }}</span>
            </label>
          </div>

          <!-- Hình thức (Công văn: trả lời, đề nghị / tham gia ý kiến dự thảo) -->
          <template v-if="modes.length > 1">
            <h3>Hình thức {{ tpl?.ten_loai?.toLowerCase() }}</h3>
            <div class="choice-grid">
              <label v-for="m in modes" :key="m.id" :class="['choice', { on: f.che_do === m.id }]">
                <input v-model="f.che_do" type="radio" :value="m.id" />
                <b>{{ m.ten }}</b><span class="muted small">{{ m.mo_ta }}</span>
              </label>
            </div>
          </template>

          <!-- ---- Tham gia ý kiến dự thảo ---- -->
          <template v-if="isGopY">
            <h3>2. Dự thảo cần tham gia ý kiến *</h3>
            <FileDrop v-model="files" :multiple="false" />
            <h3>3. Văn bản đề nghị tham gia ý kiến <span class="muted small">(phần Căn cứ của công văn)</span></h3>
            <p class="muted small">Tải công văn đề nghị lên để hệ thống tự lấy số hiệu, ngày, cơ quan; hoặc nhập trực tiếp.</p>
            <FileDrop v-model="cvFiles" :multiple="false" compact />
            <div class="form-grid">
              <label>Cơ quan đề nghị<input v-model="f.cv_co_quan" placeholder="Ví dụ: Cục …, Bộ …" /></label>
              <label>Số hiệu công văn đề nghị<input v-model="f.cv_so_hieu" placeholder="123/CV-…" /></label>
              <label>Ngày công văn<input v-model="f.cv_ngay" type="date" /></label>
              <label>Tên dự thảo (nếu cần sửa)<input v-model="f.ten_du_thao" placeholder="dự thảo Nghị định quy định …" /></label>
            </div>
            <h3>4. Khía cạnh rà soát</h3>
            <div class="chips"><span v-for="k in cat.gop_y?.khia_canh || []" :key="k.id" class="tag">{{ k.ten }}</span></div>
            <p class="muted small">Thuật ngữ và căn cứ pháp lý do chương trình đối chiếu với kho văn bản chuẩn; nhiệm vụ của ngành và nội dung kỹ thuật
              do mô hình nhận xét theo điều luật tra được. Ý kiến đơn vị đã tham gia trước đây (kho văn bản đã ban hành) được dùng để giữ nhất quán.</p>
            <label>Yêu cầu thêm<input v-model="f.yeu_cau_them" class="field" placeholder="Ví dụ: tập trung nội dung chữ ký số chuyên dùng" /></label>
          </template>

          <!-- ---- Soạn theo chủ đề ---- -->
          <template v-else>
            <h3>2. Nội dung</h3>
            <div class="form-grid wide">
              <label>Chủ đề (trích yếu) *<input v-model="f.chu_de" placeholder="Ví dụ: cấp bổ sung thiết bị lưu khóa bí mật cho cán bộ mới" /></label>
              <label>Mục đích, yêu cầu<textarea v-model="f.muc_dich" rows="3" class="field" placeholder="Đề nghị cấp trên phê duyệt…; nêu bối cảnh, số liệu đã có…" /></label>
              <label>Yêu cầu thêm<input v-model="f.yeu_cau_them" placeholder="Ví dụ: nhấn mạnh yêu cầu bảo đảm an toàn khi bàn giao" /></label>
            </div>
            <p v-if="gopyHint" class="note"><Icon name="info" :size="14" /> Chủ đề có nội dung tham gia ý kiến –
              <a href="#" @click.prevent="f.che_do = 'gop_y'">chuyển sang hình thức Tham gia ý kiến dự thảo</a> để rà soát trực tiếp trên dự thảo.</p>
          </template>

          <h3>{{ isGopY ? 5 : 3 }}. Thể thức</h3>
          <div class="form-grid">
            <label>Cơ quan cấp trên<input v-model="f.co_quan_cap_tren" placeholder="CƠ QUAN CẤP TRÊN" /></label>
            <label>{{ isGopY ? 'Đơn vị tham gia ý kiến *' : 'Đơn vị soạn' }}<input v-model="f.don_vi" :placeholder="isGopY ? 'Ban Cơ yếu …' : 'Phòng Kỹ thuật'" /></label>
            <label>Ký hiệu<input v-model="f.ky_hieu" :placeholder="isGopY ? 'CV-…' : 'TTr-PKT'" /></label>
            <label>Địa danh<input v-model="f.dia_danh" placeholder="Hà Nội" /></label>
            <label>{{ isGopY ? 'Kính gửi' : 'Nơi nhận / Kính gửi' }}<input v-model="f.noi_nhan" :placeholder="isGopY ? '(mặc định: cơ quan đề nghị)' : 'Thủ trưởng đơn vị'" /></label>
            <label>Người ký<input v-model="f.nguoi_ky" placeholder="TRƯỞNG PHÒNG – Họ tên" /></label>
          </div>
          <template v-if="!isGopY">
            <h3>4. Tài liệu tham khảo thêm (tùy chọn)</h3>
            <p class="muted small">Hệ thống tự tìm căn cứ trong kho văn bản chuẩn, tài liệu nội bộ và văn bản đơn vị đã ban hành; có thể chỉ định thêm tài liệu hoặc tải tệp lên.</p>
            <DocPicker v-model="docs" multiple />
            <FileDrop v-model="files" multiple compact />
          </template>
          <label class="small row" style="margin-top:.6rem"><input v-model="f.auto_confirm" type="checkbox" />
            {{ isGopY ? 'Không cần duyệt danh sách ý kiến' : 'Không cần duyệt dàn ý (viết luôn sau khi lập dàn ý)' }}</label>
        </template>

        <!-- ===================== Tổng hợp báo cáo ===================== -->
        <template v-if="kind === 'tong_hop'">
          <h3>1. Báo cáo riêng lẻ cần tổng hợp</h3>
          <DocPicker v-model="docs" multiple :loai="'bao_cao'" />
          <FileDrop v-model="files" multiple compact />
          <h3>2. Mẫu báo cáo tổng hợp</h3>
          <div class="choice-grid">
            <label v-for="r in cat.reports" :key="r.name" :class="['choice', { on: f.skill === r.name }]">
              <input v-model="f.skill" type="radio" :value="r.name" /><b>{{ r.description }}</b><span class="muted small">{{ r.name }}</span>
            </label>
          </div>
          <h3>3. Thông tin báo cáo</h3>
          <div class="form-grid">
            <label>Tiêu đề *<input v-model="f.title" placeholder="Báo cáo tổng hợp tình hình tuần 45" /></label>
            <label v-for="p in params" :key="p.ten">{{ p.nhan }}<input v-model="f.params[p.ten]" :type="p.kieu === 'date' ? 'date' : 'text'" /></label>
          </div>
        </template>

        <div class="row" style="margin-top:1.2rem">
          <button class="btn" :disabled="!valid || busy" @click="create"><Icon name="play" :size="15" /> {{ busy ? 'Đang tạo…' : 'Bắt đầu' }}</button>
          <span class="muted small">{{ hint }}</span>
        </div>
      </div>

      <aside class="card how">
        <h3><Icon name="steps" :size="16" /> Quy trình xử lý</h3>
        <StepTimeline :steps="meta.steps.map((n, i) => ({ id: String(i), name: n[0], detail: n[1], status: 'cho' }))" compact />
        <p class="muted small" style="margin-top:.6rem">{{ meta.note }}</p>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { refreshActive } from '../tasks'
import { toast } from '../ui'
import DocPicker from '../components/DocPicker.vue'
import FileDrop from '../components/FileDrop.vue'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import StepTimeline from '../components/StepTimeline.vue'

const route = useRoute(), router = useRouter()
const kind = computed(() => route.params.kind)
const cat = ref({ criteria: [], drafts: [], reports: [], gop_y: { khia_canh: [] } })
const files = ref([]), cvFiles = ref([]), docs = ref([]), src = ref('file'), busy = ref(false)
const f = reactive({ text: '', bo_tieu_chi: '', yeu_cau: '', mau: '', chu_de: '', muc_dich: '', yeu_cau_them: '', co_quan_cap_tren: '',
  don_vi: '', ky_hieu: '', dia_danh: '', noi_nhan: '', nguoi_ky: '', auto_confirm: false, skill: '', title: '', params: {},
  cv_co_quan: '', cv_so_hieu: '', cv_ngay: '', ten_du_thao: '', che_do: '' })

const META = {
  phan_tich: { title: 'Phân tích văn bản mới', icon: 'scan', desc: 'Tóm tắt và chỉ ra các vấn đề liên quan đến ngành, có trích dẫn căn cứ; chạy nền, theo dõi từng bước.',
    note: 'Trên máy chủ CPU, văn bản 20–30 trang có thể mất vài chục phút. Tác vụ tự nhường máy chủ mô hình khi có người hỏi đáp trực tiếp.',
    steps: [['Tiếp nhận, chuyển đổi', 'Đọc tệp, nhận dạng ký tự nếu là bản scan'], ['Cấu trúc, trích xuất', 'Chương trình trích thời hạn, nhiệm vụ, văn bản viện dẫn'],
      ['Tóm tắt', 'Từng phần, rồi toàn văn'], ['Đối chiếu cơ sở tri thức', 'Văn bản chuẩn, hiệu lực; tài liệu nội bộ liên quan'],
      ['Áp bộ tiêu chí ngành', 'Mỗi tiêu chí: tìm đoạn liên quan → nhận định có trích dẫn'], ['Lập báo cáo', 'Khung báo cáo cố định'], ['Kiểm chứng', 'Trích dẫn, số liệu có thật trong văn bản']] },
  soan_thao: { title: 'Soạn văn bản tham mưu', icon: 'pen', desc: 'Thu thập căn cứ, lập dàn ý để đồng chí duyệt, viết từng phần chỉ từ căn cứ đã gắn, xuất DOCX.',
    note: 'Dự thảo do AI hỗ trợ soạn; người ký duyệt chịu trách nhiệm nội dung. Bản kèm căn cứ giúp rà soát từng ý.',
    steps: [['Thu thập căn cứ', 'Văn bản chuẩn (nguyên văn), tài liệu nội bộ, tài liệu chỉ định'], ['Lập dàn ý', 'Ý chính và căn cứ cho từng phần'],
      ['Chờ xác nhận dàn ý', 'Đồng chí sửa, duyệt dàn ý'], ['Viết từng phần', 'Mỗi phần chỉ dùng căn cứ đã gắn'], ['Kiểm chứng', 'Đánh dấu câu chưa có căn cứ'], ['Hoàn thiện thể thức', 'Bản sạch và bản kèm căn cứ']] },
  tong_hop: { title: 'Tổng hợp báo cáo chung', icon: 'merge', desc: 'Lập báo cáo chung từ các báo cáo riêng lẻ; số liệu tổng hợp do chương trình tính, mỗi ý ghi nguồn.',
    note: 'Số liệu mô hình trích ra nhưng không có trong văn bản gốc bị loại tự động và được ghi vào cảnh báo.',
    steps: [['Đọc các báo cáo', 'Trong kho và tệp tải lên'], ['Tóm tắt, trích số liệu', 'Từng báo cáo'], ['Tính bảng số liệu', 'Chương trình cộng tổng theo chỉ tiêu'],
      ['Viết báo cáo theo mẫu', 'Mỗi ý ghi nguồn [S#]'], ['Kiểm chứng, phụ lục', 'Bảng số liệu, danh mục nguồn']] },
}
// Công văn – hình thức tham gia ý kiến: cùng phân hệ soạn thảo, quy trình rà soát dự thảo
const GOPY_META = {
 title: 'Tham gia ý kiến dự thảo', icon: 'quote', desc: 'Rà soát dự thảo theo thuật ngữ chuyên môn, căn cứ pháp lý, nhiệm vụ của ngành, kỹ thuật bảo mật – ký số – xác thực; công văn theo kết cấu Căn cứ → Nội dung tham gia ý kiến → Đề xuất, kiến nghị.',
    note: 'Vị trí (điều, khoản) và các phát hiện về thuật ngữ, căn cứ do chương trình xác định; nhận xét của mô hình luôn kèm điều luật tra được để đồng chí kiểm tra.',
    steps: [['Tiếp nhận', 'Dự thảo, công văn đề nghị'], ['Thuật ngữ', 'Danh mục ngành; định nghĩa trong kho văn bản chuẩn'], ['Căn cứ pháp lý', 'Hiệu lực, thiếu căn cứ'],
      ['Nhiệm vụ của ngành', 'Chủ thể, thẩm quyền so với luật'], ['Kỹ thuật', 'Bảo mật, ký số, xác thực'], ['Duyệt ý kiến', 'Đồng chí chọn, sửa từng ý'],
      ['Hoàn thiện công văn', 'Kèm phụ lục bảng đề xuất chỉnh sửa']] }
const meta = computed(() => (kind.value === 'soan_thao' && isGopY.value
  ? { ...META.soan_thao, ...GOPY_META, icon: 'pen', title: 'Soạn văn bản tham mưu – Công văn tham gia ý kiến' } : META[kind.value] || META.phan_tich))
const tpl = computed(() => cat.value.drafts.find((d) => d.name === f.mau))
const modes = computed(() => tpl.value?.che_do || [])
const isGopY = computed(() => kind.value === 'soan_thao' && f.che_do === 'gop_y' && modes.value.some((m) => m.id === 'gop_y'))
const gopyHint = computed(() => modes.value.some((m) => m.id === 'gop_y') && /tham gia ý kiến|góp ý|cho ý kiến/i.test(f.chu_de))
watch(() => f.mau, () => { f.che_do = modes.value[0]?.id || '' })
const params = computed(() => cat.value.reports.find((r) => r.name === f.skill)?.params || [])
const upIds = computed(() => files.value.filter((x) => x.id).map((x) => x.id))
const valid = computed(() => {
  if (files.value.some((x) => x.uploading)) return false
  if (kind.value === 'phan_tich') return src.value === 'file' ? upIds.value.length > 0 : src.value === 'doc' ? docs.value.length > 0 : f.text.trim().length >= 80
  if (kind.value === 'soan_thao' && isGopY.value) return upIds.value.length > 0 && !cvFiles.value.some((x) => x.uploading) && f.don_vi.trim().length >= 2
  if (kind.value === 'soan_thao') return f.mau && f.chu_de.trim().length >= 5
  return f.skill && f.title.trim().length >= 3 && (docs.value.length || upIds.value.length)
})
const hint = computed(() => (valid.value ? 'Tác vụ chạy nền – có thể chuyển sang việc khác, theo dõi ở thanh bên.' : 'Điền các mục bắt buộc (*)'))

onMounted(async () => {
  if (kind.value === 'gop_y') {  // liên kết cũ (1.4.0): tham gia ý kiến nay là hình thức của Công văn trong phân hệ soạn thảo
    router.replace({ path: '/tac-vu/moi/soan_thao', query: { mau: 'soan-cong-van-gop-y', che_do: 'gop_y' } }); return
  }
  cat.value = await api.get('/agent/catalog')
  f.bo_tieu_chi = cat.value.criteria.find((c) => c.mac_dinh)?.name || cat.value.criteria[0]?.name || ''
  f.mau = cat.value.drafts.find((d) => d.name === (route.query.mau || 'soan-to-trinh'))?.name || cat.value.drafts[0]?.name || ''
  await nextTick()  // watch(f.mau) đặt hình thức mặc định trước, sau đó áp hình thức trong liên kết (?che_do=gop_y)
  if (route.query.che_do && modes.value.some((m) => m.id === route.query.che_do)) f.che_do = String(route.query.che_do)
  f.skill = cat.value.reports.find((r) => r.name === 'tong-hop-bao-cao-chung')?.name || cat.value.reports[0]?.name || ''
  if (route.query.docs) docs.value = String(route.query.docs).split(',').filter(Boolean).map((id) => ({ doc_id: id, title: id }))
})
watch(kind, () => { files.value = []; cvFiles.value = []; docs.value = [] })
watch(isGopY, () => { files.value = []; cvFiles.value = [] })

async function create() {
  busy.value = true
  try {
    let input = {}, title = ''
    if (kind.value === 'phan_tich') {
      input = { bo_tieu_chi: f.bo_tieu_chi, yeu_cau: f.yeu_cau.trim() }
      if (src.value === 'file') input.upload_id = upIds.value[0]
      else if (src.value === 'doc') input.doc_id = docs.value[0].doc_id
      else input.text = f.text
    } else if (kind.value === 'soan_thao' && isGopY.value) {
      const { mau, cv_co_quan, cv_so_hieu, cv_ngay, ten_du_thao, yeu_cau_them, co_quan_cap_tren, don_vi, ky_hieu, dia_danh, noi_nhan, nguoi_ky, auto_confirm } = f
      input = { mau, che_do: 'gop_y', upload_id: upIds.value[0], cv_upload_id: cvFiles.value.find((x) => x.id)?.id || '', cv_co_quan, cv_so_hieu,
        cv_ngay, ten_du_thao, yeu_cau_them, co_quan_cap_tren, don_vi, ky_hieu, dia_danh, noi_nhan, nguoi_ky, auto_confirm }
    } else if (kind.value === 'soan_thao') {
      const { mau, chu_de, muc_dich, yeu_cau_them, co_quan_cap_tren, don_vi, ky_hieu, dia_danh, noi_nhan, nguoi_ky, auto_confirm } = f
      input = { mau, che_do: f.che_do, chu_de, muc_dich, yeu_cau_them, co_quan_cap_tren, don_vi, ky_hieu, dia_danh, noi_nhan, nguoi_ky, auto_confirm,
        doc_ids: docs.value.map((d) => d.doc_id), upload_ids: upIds.value }
    } else {
      input = { skill: f.skill, params: f.params, doc_ids: docs.value.map((d) => d.doc_id), upload_ids: upIds.value }
      title = f.title
    }
    const t = await api.post('/agent/tasks', { kind: kind.value, title, input })
    refreshActive()
    toast('Đã tạo tác vụ – đang xử lý nền.')
    router.push('/tac-vu/' + t.id)
  } catch (e) { toast(e.message, 'err') } finally { busy.value = false }
}
</script>
