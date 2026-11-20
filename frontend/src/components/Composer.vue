<template>
  <div class="composer-wrap">
    <div v-if="slashOpen" class="slash" role="listbox">
      <div class="slash-h muted small">Lệnh nhanh</div>
      <button v-for="(c, i) in slashItems" :key="c.key" :class="['slash-i', { on: i === slashIdx }]" @mousedown.prevent="pick(c)">
        <Icon :name="c.icon" :size="16" /><b>/{{ c.key }}</b><span class="muted">{{ c.hint }}</span>
      </button>
    </div>
    <div class="composer">
      <textarea ref="ta" v-model="chat.draft" rows="1" :placeholder="placeholder" aria-label="Nội dung câu hỏi"
                @input="grow" @keydown="onKey" />
      <div class="composer-bar">
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
        <button v-else class="send" :disabled="!chat.draft.trim()" title="Gửi (Enter)" @click="submit"><Icon name="send" :size="17" /></button>
      </div>
    </div>
    <p class="disclaimer">Nội dung <b>nguyên văn</b> lấy trực tiếp từ kho văn bản chuẩn. Nội dung <b>tham khảo</b> do AI tổng hợp – đối chiếu nguồn trước khi sử dụng.
      Gõ <kbd>/</kbd> để xem lệnh nhanh.</p>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { chat, stop } from '../chat'
import { MODES, visibleExtensions } from '../extensions'
import { LOAI } from '../md'
import Icon from './Icon.vue'

const emit = defineEmits(['send'])
const router = useRouter()
const ta = ref(null), slashIdx = ref(0)

const placeholder = computed(() => ({
  chinh_xac: 'Hỏi về điều, khoản cụ thể – ví dụ: “Điều 5 Quyết định 15/QĐ-ĐVA quy định gì?”',
  ho_tro: 'Mô tả sự cố đang gặp – ví dụ: “Máy in không in được, đèn vẫn sáng”',
  tim_tai_lieu: 'Nhập chủ đề cần tìm tài liệu…',
}[chat.mode] || 'Hỏi bất cứ điều gì về tài liệu, quy định, kỹ thuật…'))

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
  const t = chat.draft.trim()
  if (!t || chat.busy) return
  emit('send', t)
  chat.draft = ''
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
