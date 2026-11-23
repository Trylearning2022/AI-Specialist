<template>
  <!-- Vùng kéo-thả tệp: tải lên agent-svc ngay khi chọn; v-model = [{id, filename, size, uploading, error}] -->
  <div>
    <div :class="['drop', { over, compact }]" @click="fi.click()" @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop">
      <Icon name="upload" :size="compact ? 18 : 26" />
      <div><b>Kéo thả tệp vào đây</b> hoặc bấm để chọn<div class="small">PDF, DOCX, XLSX, PPTX, MD, TXT, ảnh scan · không chứa thông tin vượt độ mật cho phép</div></div>
      <input ref="fi" type="file" hidden :multiple="multiple" accept=".pdf,.docx,.xlsx,.pptx,.md,.txt,.html,.csv,.png,.jpg,.jpeg,.tif,.tiff" @change="onPick" />
    </div>
    <div v-if="modelValue.length" class="att-list" style="margin-top:.5rem">
      <span v-for="(f, i) in modelValue" :key="i" :class="['attchip', { err: f.error }]" :title="f.error || f.filename">
        <span v-if="f.uploading" class="spin sm" /><Icon v-else :name="f.error ? 'alert' : 'paperclip'" :size="13" />
        <span class="clamp1">{{ f.filename }}</span>
        <button class="x" title="Bỏ tệp" @click="remove(i)"><Icon name="x" :size="12" /></button>
      </span>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { uploadFile } from '../tasks'
import { toast } from '../ui'
import Icon from './Icon.vue'

const props = defineProps({ modelValue: { type: Array, default: () => [] }, multiple: Boolean, compact: Boolean })
const emit = defineEmits(['update:modelValue'])
const fi = ref(null), over = ref(false)
function onPick(e) { add([...e.target.files]); e.target.value = '' }
function onDrop(e) { over.value = false; add([...(e.dataTransfer?.files || [])]) }
function remove(i) { const v = [...props.modelValue]; v.splice(i, 1); emit('update:modelValue', v) }
async function add(list) {
  if (!props.multiple) list = list.slice(0, 1)
  const items = list.map((file) => reactive({ filename: file.name, size: file.size, uploading: true, id: null, error: '', file }))
  emit('update:modelValue', props.multiple ? [...props.modelValue, ...items] : items)
  for (const it of items) {
    try { it.id = (await uploadFile(it.file)).id } catch (e) { it.error = e.message; toast(`${it.filename}: ${e.message}`, 'err') } finally { it.uploading = false }
  }
}
</script>
