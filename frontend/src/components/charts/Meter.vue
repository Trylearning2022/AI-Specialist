<template>
  <!-- Thanh mức sử dụng tài nguyên: ≥ 85% cảnh báo (kèm nhãn chữ) -->
  <div class="meter">
    <div class="meter-h"><span>{{ label }}</span><b>{{ pct == null ? '—' : pct + '%' }}</b></div>
    <div class="meter-t"><i :class="{ warn: pct >= 70, bad: pct >= 85 }" :style="{ width: (pct || 0) + '%' }" /></div>
    <div v-if="sub" class="muted small">{{ sub }}<span v-if="pct >= 85" class="err"> · cao</span></div>
  </div>
</template>

<script setup>
defineProps({ label: String, pct: Number, sub: String })
</script>
