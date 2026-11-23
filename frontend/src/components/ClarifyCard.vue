<template>
  <!-- Hỏi lại làm rõ: chọn một phương án hoặc nhập nội dung bổ sung; chỉ hỏi lại tối đa 01 lần cho mỗi câu hỏi -->
  <div class="clarify">
    <div class="cl-head"><Icon name="help" :size="16" /> <b>{{ c.question }}</b></div>
    <div class="cl-opts">
      <button v-for="o in c.options" :key="o.label" class="opt" :disabled="done || chat.busy" @click="pick(o)">{{ o.label }}</button>
    </div>
    <form class="cl-free" @submit.prevent="free">
      <input v-model="text" :disabled="done || chat.busy" placeholder="Hoặc mô tả cụ thể hơn…" aria-label="Nội dung bổ sung" />
      <button class="btn sm" :disabled="done || chat.busy || !text.trim()">Gửi</button>
    </form>
    <p v-if="done" class="muted small"><Icon name="check" :size="13" /> Đã bổ sung thông tin.</p>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { answerClarify, chat } from '../chat'
import Icon from './Icon.vue'

const props = defineProps({ m: { type: Object, required: true } })
const c = props.m.data.clarify
const text = ref(''), done = ref(!!props.m.clarified)
function pick(o) { done.value = true; props.m.clarified = true; answerClarify(props.m, o.label, o.value) }
function free() { done.value = true; props.m.clarified = true; answerClarify(props.m, text.value.trim(), text.value.trim()) }
</script>
