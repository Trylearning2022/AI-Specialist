<template>
  <!-- Danh sách thanh ngang có nhãn: so sánh độ lớn giữa các nhóm (luồng trả lời, người dùng, loại phát hiện…) -->
  <div class="barlist">
    <div v-for="r in rows" :key="r.label" class="bl-row" :title="r.title || `${r.label}: ${r.value}`">
      <span class="bl-label clamp1">{{ r.label }}</span>
      <span class="bl-track"><i :style="{ width: (100 * r.value / max) + '%', background: r.color || 'var(--series-1)' }" /></span>
      <span class="bl-val">{{ r.text ?? r.value }}</span>
    </div>
    <p v-if="!rows.length" class="viz-empty">Chưa có số liệu.</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ rows: { type: Array, default: () => [] } })  // [{label, value, text?, color?, title?}]
const max = computed(() => Math.max(1, ...props.rows.map((r) => r.value || 0)))
</script>
