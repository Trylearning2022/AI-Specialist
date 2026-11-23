<template>
  <!-- Duyệt danh sách ý kiến tham gia dự thảo trước khi hoàn thiện công văn.
       Mỗi ý kiến: chọn/bỏ, sửa vị trí, nhận xét, đề nghị sửa, căn cứ. Ý kiến chung, kiến nghị sửa trực tiếp. -->
  <div class="card gy">
    <div class="row"><h3 class="grow">Duyệt ý kiến tham gia dự thảo</h3>
      <button class="btn" :disabled="busy" @click="submit"><Icon name="check" :size="15" /> Xác nhận, hoàn thiện công văn</button></div>
    <p class="muted small">Kết cấu công văn: <b>1. Căn cứ</b> → <b>2. Nội dung tham gia ý kiến</b> (ý kiến chung + ý kiến cụ thể theo khía cạnh)
      → <b>3. Đề xuất, kiến nghị</b> (nếu có). Bỏ chọn ý kiến không phù hợp; sửa trực tiếp nội dung.</p>

    <label class="gy-lbl">2.1. Ý kiến chung<textarea v-model="g.y_kien_chung" rows="2" class="field" /></label>

    <div class="toolbar"><div class="seg narrow">
      <button v-for="k in kinds" :key="k.id" :class="{ on: filter === k.id }" @click="filter = k.id">{{ k.ten }}
        <span class="seg-n">{{ k.n }}</span></button>
    </div><span class="grow" /><span class="muted small">Đã chọn {{ chosen }}/{{ g.muc.length }}</span></div>

    <div v-for="m in shown" :key="m.id" :class="['gy-item', m.muc_do, { off: !m.chon }]">
      <div class="row">
        <label class="row small"><input v-model="m.chon" type="checkbox" /> <b>{{ NAME[m.khia_canh] || m.khia_canh }}</b></label>
        <span :class="['sev', m.muc_do]">{{ SEVL[m.muc_do] || '' }}</span>
        <span v-if="m.boi === 'chuong_trinh'" class="tag" title="Phát hiện bằng quy tắc, không do mô hình">chương trình</span>
        <span class="grow" />
        <input v-model="m.vi_tri" class="gy-pos" placeholder="Vị trí (khoản, điều)" />
      </div>
      <blockquote v-if="m.trich" class="small">{{ m.trich }}</blockquote>
      <textarea v-model="m.nhan_xet" rows="2" class="field" placeholder="Nhận xét" />
      <textarea v-model="m.de_nghi_sua" rows="2" class="field" placeholder="Đề nghị sửa thành / bổ sung…" />
      <input v-model="m.can_cu" class="field" placeholder="Căn cứ (điều, khoản)" />
      <div v-if="m.nguon_tra_cuu?.length" class="muted small"><Icon name="scale" :size="12" /> Tra cứu:
        {{ m.nguon_tra_cuu.map((x) => [x.vi_tri, x.so_hieu || x.title].filter(Boolean).join(' ')).join('; ') }}</div>
    </div>
    <p v-if="!shown.length" class="empty">Không có ý kiến ở khía cạnh này.</p>
    <button class="btn ghost sm" @click="add"><Icon name="plus" :size="14" /> Thêm ý kiến</button>

    <h4>3. Đề xuất, kiến nghị <span class="muted small">(để trống nếu không có – phần này sẽ được bỏ)</span></h4>
    <div v-for="(k, i) in g.kien_nghi" :key="i" class="row">
      <textarea v-model="g.kien_nghi[i]" rows="2" class="field grow" />
      <button class="icon-btn xs" title="Bỏ" @click="g.kien_nghi.splice(i, 1)"><Icon name="trash" :size="14" /></button></div>
    <button class="btn ghost sm" @click="g.kien_nghi.push('')"><Icon name="plus" :size="14" /> Thêm kiến nghị</button>

    <details v-if="payload.tien_le?.length" class="gy-prec"><summary>Ý kiến đơn vị đã tham gia trước đây ({{ payload.tien_le.length }})</summary>
      <div v-for="p in payload.tien_le" :key="p.so_hieu + p.title" class="src"><b>{{ p.so_hieu || p.title }}</b>
        <span class="muted small">{{ p.title }}</span><div class="muted small clamp">{{ p.trich }}</div></div>
    </details>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '../api'
import { toast } from '../ui'
import Icon from './Icon.vue'

const props = defineProps({ taskId: { type: String, required: true }, payload: { type: Object, required: true },
  aspects: { type: Array, default: () => [] } })
const emit = defineEmits(['done'])
const NAME = { thuat_ngu: 'Thuật ngữ', can_cu: 'Căn cứ pháp lý', nhiem_vu: 'Nhiệm vụ của ngành', ky_thuat: 'Kỹ thuật', khac: 'Khác' }
const SEVL = { cao: 'Mức độ cao', trung_binh: 'Trung bình', thap: 'Thấp' }
const g = reactive({ y_kien_chung: props.payload.y_kien_chung || '', kien_nghi: [...(props.payload.kien_nghi || [])],
  muc: (props.payload.muc || []).map((m) => ({ ...m, chon: m.chon !== false })) })
const filter = ref(''), busy = ref(false)
const kinds = computed(() => [{ id: '', ten: 'Tất cả', n: g.muc.length },
  ...Object.keys(NAME).filter((k) => g.muc.some((m) => m.khia_canh === k)).map((k) => ({ id: k, ten: NAME[k], n: g.muc.filter((m) => m.khia_canh === k).length }))])
const shown = computed(() => g.muc.filter((m) => !filter.value || m.khia_canh === filter.value))
const chosen = computed(() => g.muc.filter((m) => m.chon).length)

function add() {
  g.muc.push({ id: 'u' + Date.now(), khia_canh: filter.value || 'khac', vi_tri: '', trich: '', nhan_xet: '', de_nghi_sua: '',
    can_cu: '', muc_do: 'trung_binh', boi: 'nguoi_dung', chon: true })
}
async function submit() {
  busy.value = true
  try {
    await api.post(`/agent/tasks/${props.taskId}/confirm`, { gop_y: { ...g, kien_nghi: g.kien_nghi.filter((k) => k.trim()) } })
    toast('Đã xác nhận – đang hoàn thiện công văn.')
    emit('done')
  } catch (e) { toast(e.message, 'err') } finally { busy.value = false }
}
</script>

<style scoped>
.gy-lbl { display: block; margin: .6rem 0; font-weight: 600 }
.gy-item { border: 1px solid var(--border); border-left: 3px solid var(--border); border-radius: 8px; padding: .6rem .7rem; margin: .5rem 0; display: grid; gap: .35rem }
.gy-item.cao { border-left-color: var(--err, #c0392b) }
.gy-item.trung_binh { border-left-color: var(--warn, #d68910) }
.gy-item.off { opacity: .5 }
.gy-pos { max-width: 16rem; font-size: .85rem }
.gy-prec { margin-top: 1rem }
h4 { margin: 1rem 0 .4rem }
blockquote { margin: 0; padding: .3rem .6rem; border-left: 3px solid var(--border); color: var(--muted) }
</style>
