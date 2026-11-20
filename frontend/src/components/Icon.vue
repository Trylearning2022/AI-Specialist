<template>
  <svg class="ico" :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       :stroke-width="stroke" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path :d="ICONS[name] || ICONS.info" />
  </svg>
</template>

<script setup>
import { ICONS } from '../icons'
defineProps({ name: { type: String, required: true }, size: { type: [Number, String], default: 18 }, stroke: { type: [Number, String], default: 1.8 } })
</script>
