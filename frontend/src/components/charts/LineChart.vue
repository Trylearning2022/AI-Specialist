<template>
  <!-- Biểu đồ đường theo thời gian: nét 2px, lưới mờ, một trục; rê chuột hiện đường dóng + chú thích giá trị -->
  <div ref="root" class="viz line-chart" @mouseleave="hover = -1">
    <div v-if="series.length > 1" class="viz-legend">
      <span v-for="(s, i) in series" :key="s.name"><i :style="{ background: color(i) }" />{{ s.name }}</span>
    </div>
    <svg :viewBox="`0 0 ${W} ${H}`" :height="H" role="img" :aria-label="title || 'Biểu đồ'" @mousemove="move">
      <g class="viz-grid">
        <template v-for="t in ticks" :key="t">
          <line :x1="P.l" :x2="W - P.r" :y1="y(t)" :y2="y(t)" />
          <text :x="P.l - 6" :y="y(t) + 4" text-anchor="end">{{ fmt(t) }}</text>
        </template>
      </g>
      <g class="viz-x">
        <text v-for="(l, i) in labels" v-show="i % step === 0" :key="i" :x="x(i)" :y="H - 6" text-anchor="middle">{{ xfmt(l) }}</text>
      </g>
      <path v-for="(s, i) in series" :key="s.name" :d="path(s.values)" :stroke="color(i)" class="viz-line" />
      <template v-if="hover >= 0">
        <line class="viz-cross" :x1="x(hover)" :x2="x(hover)" :y1="P.t" :y2="H - P.b" />
        <template v-for="(s, i) in series" :key="'d' + s.name">
          <circle v-if="s.values[hover] != null" :cx="x(hover)" :cy="y(s.values[hover])" r="4.5" :fill="color(i)" class="viz-dot" />
        </template>
      </template>
    </svg>
    <div v-if="hover >= 0" class="viz-tip" :style="{ left: Math.min(x(hover) / W * 100, 72) + '%' }">
      <b>{{ xfmt(labels[hover], true) }}</b>
      <div v-for="(s, i) in series" :key="s.name"><i :style="{ background: color(i) }" />{{ s.name }}: <b>{{ s.values[hover] == null ? '—' : fmt(s.values[hover]) }}</b> {{ unit }}</div>
    </div>
    <p v-if="empty" class="viz-empty">Chưa có số liệu trong khoảng thời gian này.</p>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  series: { type: Array, default: () => [] },   // [{name, values: [số | null]}]
  labels: { type: Array, default: () => [] },   // thời điểm (giây Unix) tương ứng từng giá trị
  unit: { type: String, default: '' }, title: String, height: { type: Number, default: 200 },
})
const root = ref(null), W = ref(600), hover = ref(-1)
const H = computed(() => props.height)
const P = { l: 44, r: 12, t: 10, b: 24 }
let ro = null
onMounted(() => { ro = new ResizeObserver(([e]) => { W.value = Math.max(260, e.contentRect.width) }); ro.observe(root.value) })
onBeforeUnmount(() => ro?.disconnect())

// Màu theo thứ tự cố định của bảng màu phân loại (đã kiểm tra mù màu), không theo thứ hạng
const color = (i) => `var(--series-${i + 1})`
const all = computed(() => props.series.flatMap((s) => s.values).filter((v) => v != null))
const empty = computed(() => !all.value.length)
const max = computed(() => {
  const m = Math.max(1, ...all.value)
  const p = 10 ** Math.floor(Math.log10(m)), n = m / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p
})
const ticks = computed(() => [0, 1, 2, 3, 4].map((k) => (max.value * k) / 4))
const x = (i) => P.l + (i * (W.value - P.l - P.r)) / Math.max(1, props.labels.length - 1)
const y = (v) => H.value - P.b - (v / max.value) * (H.value - P.t - P.b)
const step = computed(() => Math.max(1, Math.ceil(props.labels.length / Math.max(2, Math.floor(W.value / 80)))))
function path(vals) {
  let d = '', pen = false
  vals.forEach((v, i) => {
    if (v == null) { pen = false; return }
    d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`
    pen = true
  })
  return d
}
const fmt = (v) => (v >= 1000 ? (v / 1000).toFixed(v >= 10000 ? 0 : 1) + 'k' : Number.isInteger(v) ? v : String(+v.toFixed(v < 1 ? 2 : 1)))
function xfmt(t, full = false) {
  const d = new Date(t * 1000)
  const span = (props.labels.at(-1) - props.labels[0]) || 0
  if (span > 2 * 86400 || full) return d.toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  return d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
}
function move(e) {
  const r = e.currentTarget.getBoundingClientRect()
  const px = ((e.clientX - r.left) / r.width) * W.value
  const i = Math.round(((px - P.l) / (W.value - P.l - P.r)) * (props.labels.length - 1))
  hover.value = Math.max(0, Math.min(props.labels.length - 1, i))
}
</script>
