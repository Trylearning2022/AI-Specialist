<template>
  <!-- Chọn tài liệu trong kho (sổ đăng ký ingest-svc, đã lọc theo quyền người dùng). v-model = [{doc_id, title, …}] -->
  <div class="docpick">
    <div class="row">
      <div class="sb-search grow"><Icon name="search" :size="15" />
        <input v-model="q" placeholder="Tìm theo tên, số hiệu…" @input="search" @focus="search" /></div>
      <select v-model="flt" @change="search"><option value="">Mọi loại</option>
        <option v-for="(v, k) in LOAI" :key="k" :value="k">{{ v }}</option></select>
    </div>
    <div v-if="results.length && open" class="dp-results">
      <button v-for="d in results" :key="d.doc_id" class="dp-item" :disabled="has(d)" @click="pick(d)">
        <Icon :name="d.track === 'B' ? 'scale' : 'file'" :size="15" />
        <span class="grow clamp1"><b>{{ d.title }}</b> <span class="muted small">{{ [d.so_hieu, LOAI[d.loai], d.ngay_ban_hanh].filter(Boolean).join(' · ') }}</span></span>
        <Icon v-if="has(d)" name="check" :size="14" />
      </button>
    </div>
    <div v-if="modelValue.length" class="att-list" style="margin-top:.5rem">
      <span v-for="(d, i) in modelValue" :key="d.doc_id" class="attchip"><Icon name="file" :size="13" /><span class="clamp1">{{ d.title }}</span>
        <button class="x" title="Bỏ" @click="remove(i)"><Icon name="x" :size="12" /></button></span>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../api'
import { LOAI } from '../md'
import Icon from './Icon.vue'

const props = defineProps({ modelValue: { type: Array, default: () => [] }, multiple: Boolean, loai: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue'])
const q = ref(''), flt = ref(props.loai), results = ref([]), open = ref(false)
let t = null
function search() {
  clearTimeout(t)
  t = setTimeout(async () => {
    results.value = (await api.get('/ingest/documents', { q: q.value, loai: flt.value })).slice(0, 30)
    open.value = true
  }, 250)
}
const has = (d) => props.modelValue.some((x) => x.doc_id === d.doc_id)
function pick(d) {
  emit('update:modelValue', props.multiple ? [...props.modelValue, d] : [d])
  if (!props.multiple) open.value = false
}
function remove(i) { const v = [...props.modelValue]; v.splice(i, 1); emit('update:modelValue', v) }
</script>
