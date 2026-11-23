<template>
  <!-- Ô chỉ số: con số chính, đơn vị, mô tả; tùy chọn đường xu hướng nhỏ và trạng thái (kèm biểu tượng, không chỉ màu) -->
  <div :class="['kpi', state]">
    <div class="kpi-h"><Icon v-if="icon" :name="icon" :size="15" /><span>{{ label }}</span>
      <Icon v-if="state === 'warn' || state === 'bad'" name="alert" :size="14" class="kpi-st" /></div>
    <div class="kpi-v">{{ value ?? '—' }}<small v-if="unit && value != null"> {{ unit }}</small></div>
    <svg v-if="spark?.length > 1" class="kpi-spark" viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true">
      <path :d="sparkPath" />
    </svg>
    <div v-if="sub" class="kpi-sub">{{ sub }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import Icon from '../Icon.vue'
const props = defineProps({ label: String, value: [Number, String], unit: String, sub: String, icon: String,
  spark: Array, state: { type: String, default: '' } })
const sparkPath = computed(() => {
  const v = props.spark.map((x) => x ?? 0), m = Math.max(1, ...v)
  return v.map((x, i) => `${i ? 'L' : 'M'}${(i * 100) / (v.length - 1)},${22 - (x / m) * 20}`).join('')
})
</script>
