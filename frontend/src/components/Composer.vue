<template>
  <div class="composer-wrap">
    <div v-if="slashOpen" class="slash" role="listbox">
      <div class="slash-h muted small">Lệnh nhanh</div>
      <button v-for="(c, i) in slashItems" :key="c.key" :class="['slash-i', { on: i === slashIdx }]" @mousedown.prevent="pick(c)">
        <Icon :name="c.icon" :size="16" /><b>/{{ c.key }}</b><span class="muted">{{ c.hint }}</span>
      </button>
    </div>
    <div :class="['composer', { over }]" @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop">
      <div v-if="chat.files.length" class="att-list">
        <span v-for="(f, i) in chat.files" :key="i" :class="['attchip', { err: f.error, busy: f.uploading }]" :title="f.error || f.filename">
          <span v-if="f.uploading" class="spin sm" /><Icon v-else :name="f.error ? 'alert' : 'paperclip'" :size="13" />
          <span class="clamp1">{{ f.filename }}</span><small v-if="f.size" class="muted">{{ kb(f.size) }}</small>
          <button class="x" title="Bỏ tệp" @click="chat.files.splice(i, 1)"><Icon name="x" :size="12" /></button>
        </span>
      </div>
      <textarea ref="ta" v-model="chat.draft" rows="1" :placeholder="placeholder" aria-label="Nội dung câu hỏi"
                @input="grow" @keydown="onKey" />
      <div class="composer-bar">
        <button class="icon-btn attach" title="Đính kèm văn bản để phân tích, tổng hợp (PDF, DOCX, XLSX, MD…)" @click="pickFile"><Icon name="paperclip" :size="18" /></button>
        <input ref="fi" type="file" multiple hidden accept=".pdf,.docx,.xlsx,.pptx,.md,.txt,.html,.csv,.png,.jpg,.jpeg,.tif,.tiff" @change="onFiles" />
        <div class="modes">
          <button v-for="x in MODES" :key="x.id" :class="['mode', { on: chat.mode === x.id }]" :title="x.hint" @click="chat.mode = x.id">
            <Icon :name="x.icon" :size="14" /> {{ x.label }}
          </button>
          <select v-model="chat.loai" class="mode-sel" title="Giới hạn loại văn bản">
            <option value="">Mọi loại văn bản</option>
            <option v-for="(v, k) in LOAI" :key="k" :value="k">{{ v }}</option>
          </select>
        </div>
        <button v-if="chat.busy" class="send stop" title="Dừng" @click="stop"><Icon name="stop" :size="16" /></button>
        <button v-else class="send" :disabled="!canSend" title="Gửi (Enter)" @click="submit"><Icon name="send" :size="17" /></button>
      </div>
    </div>
    <p class="disclaimer">Nội dung <b>nguyên văn</b> lấy trực tiếp từ kho văn bản chuẩn. Nội dung <b>tham khảo</b> do AI tổng hợp – đối chiếu nguồn trước khi sử dụng.
      Không nhập mã PIN, mật khẩu, khóa bí mật. Gõ <kbd>/</kbd> để xem lệnh nhanh.</p>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { chat, stop } from '../chat'
import { MODES, visibleExtensions } from '../extensions'
import { LOAI } from '../md'
import { uploadFile } from '../tasks'
import { toast } from '../ui'
import Icon from './Icon.vue'

const emit = defineEmits(['send'])
const router = useRouter()
const ta = ref(null), fi = ref(null), slashIdx = ref(0), over = ref(false)
const uploading = computed(() => chat.files.some((f) => f.uploading))
const ready = computed(() => chat.files.filter((f) => f.id))
const canSend = computed(() => !uploading.value && (chat.draft.trim() || ready.value.length))
const kb = (n) => (n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB')

function pickFile() { fi.value?.click() }
function onFiles(e) { addFiles([...e.target.files]); e.target.value = '' }
function onDrop(e) { over.value = false; addFiles([...(e.dataTransfer?.files || [])]) }
async function addFiles(list) {
  for (const file of list) {
    const f = reactive({ filename: file.name, size: file.size, uploading: true, id: null, error: '' })
    chat.files.push(f)
    try { f.id = (await uploadFile(file)).id } catch (err) { f.error = err.message; toast(`${file.name}: ${err.message}`, 'err') } finally { f.uploading = false }
  }
}

const placeholder = computed(() => chat.files.length ? 'Nêu yêu cầu với văn bản đính kèm – ví dụ: “Phân tích các vấn đề liên quan đến công tác chứng thực số” (để trống: phân tích/tổng hợp mặc định)' : ({
  chinh_xac: 'Hỏi về điều, khoản cụ thể – ví dụ: “Điều 5 Quyết định 15/QĐ-ĐVA quy định gì?”',
  ho_tro: 'Mô tả sự cố: thiết bị, biểu hiện – ví dụ: “USB Token cắm vào không nhận, đèn không sáng”',
  tim_tai_lieu: 'Nhập chủ đề cần tìm tài liệu…',
}[chat.mode] || 'Hỏi về quy định, tài liệu, sự cố kỹ thuật… hoặc đính kèm văn bản để phân tích'))

const commands = computed(() => [
  ...MODES.filter((m) => m.cmd).map((m) => ({ key: m.cmd, icon: m.icon, hint: m.hint, mode: m.id })),
  ...visibleExtensions().map((e) => ({ key: e.id, icon: e.icon, hint: 'Mở tiện ích ' + e.name, path: e.path })),
])
const slashOpen = computed(() => /^\/[\w-]*$/.test(chat.draft) && slashItems.value.length > 0)
const slashItems = computed(() => {
  const k = chat.draft.slice(1).toLowerCase()
  return commands.value.filter((c) => c.key.startsWith(k))
})
watch(slashOpen, () => { slashIdx.value = 0 })

function pick(c) {
  chat.draft = ''
  if (c.mode) chat.mode = c.mode
  if (c.path) router.push(c.path)
  nextTick(() => { ta.value?.focus(); grow() })
}
function grow() {
  const el = ta.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 220) + 'px'
}
function submit() {
  if (!canSend.value || chat.busy) return
  const att = ready.value.map((f) => ({ id: f.id, filename: f.filename }))
  const t = chat.draft.trim() || (att.length > 1 ? 'Tổng hợp báo cáo chung từ các báo cáo đính kèm' : 'Phân tích văn bản đính kèm')
  emit('send', t, att)
  chat.draft = ''
  chat.files = []
  nextTick(grow)
}
function onKey(e) {
  if (slashOpen.value) {
    if (e.key === 'ArrowDown') { slashIdx.value = (slashIdx.value + 1) % slashItems.value.length; e.preventDefault(); return }
    if (e.key === 'ArrowUp') { slashIdx.value = (slashIdx.value - 1 + slashItems.value.length) % slashItems.value.length; e.preventDefault(); return }
    if (e.key === 'Enter' || e.key === 'Tab') { pick(slashItems.value[slashIdx.value]); e.preventDefault(); return }
    if (e.key === 'Escape') { chat.draft = ''; return }
  }
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit() }
}
watch(() => chat.draft, () => nextTick(grow))
onMounted(() => { ta.value?.focus(); grow() })
defineExpose({ focus: () => ta.value?.focus() })
</script>
