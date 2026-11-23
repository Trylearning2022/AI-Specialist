<template>
  <!-- Tiến trình từng bước: dùng chung cho câu trả lời trò chuyện, tác vụ dài, lượt giám định dữ liệu -->
  <ol :class="['timeline', { compact }]">
    <li v-for="(s, i) in steps" :key="s.id" :class="['tl-step', s.status || 'cho']">
      <span class="tl-dot" :title="LABEL[s.status] || ''">
        <span v-if="s.status === 'dang_chay'" class="spin" />
        <Icon v-else-if="s.status === 'xong'" name="check" :size="compact ? 11 : 13" />
        <Icon v-else-if="s.status === 'loi'" name="x" :size="compact ? 11 : 13" />
        <Icon v-else-if="s.status === 'cho_xac_nhan'" name="pause" :size="compact ? 11 : 13" />
        <Icon v-else-if="s.status === 'bo_qua'" name="right" :size="compact ? 11 : 13" />
        <span v-else class="tl-n">{{ i + 1 }}</span>
      </span>
      <div class="tl-body">
        <div class="tl-row">
          <span class="tl-name">{{ s.name }}</span>
          <span v-if="s.ms != null && s.status !== 'dang_chay'" class="tl-ms">{{ fmtMs(s.ms) }}</span>
          <span v-else-if="s.status === 'dang_chay' && s.started" class="tl-ms">{{ since(s.started) }}</span>
        </div>
        <div v-if="s.sub && s.status === 'dang_chay'" class="tl-bar" :title="`${s.sub[0]}/${s.sub[1]}`">
          <i :style="{ width: (100 * s.sub[0] / Math.max(1, s.sub[1])) + '%' }" />
        </div>
        <div v-if="s.detail && (s.status !== 'xong' || !s.out)" class="tl-detail">{{ s.detail }}</div>
        <div v-if="s.out && s.status === 'xong'" class="tl-out">{{ s.out }}</div>
      </div>
    </li>
  </ol>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { fmtMs } from '../tasks'
import Icon from './Icon.vue'

defineProps({ steps: { type: Array, default: () => [] }, compact: Boolean })
const LABEL = { xong: 'Hoàn thành', dang_chay: 'Đang thực hiện', loi: 'Lỗi', bo_qua: 'Bỏ qua', cho_xac_nhan: 'Chờ xác nhận', cho: 'Chờ' }
const now = ref(Date.now())
const t = setInterval(() => { now.value = Date.now() }, 1000)
onBeforeUnmount(() => clearInterval(t))
const since = (iso) => fmtMs(now.value - new Date(iso).getTime())
</script>
