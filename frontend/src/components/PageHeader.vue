<template>
  <header class="page-h">
    <router-link :to="chat.convId ? '/c/' + chat.convId : '/'" class="icon-btn" title="Quay lại trò chuyện"><Icon name="left" /></router-link>
    <div class="page-ico"><Icon :name="icon" :size="20" /></div>
    <div class="grow">
      <h1>{{ title }}</h1>
      <p v-if="desc" class="muted small">{{ desc }}</p>
    </div>
    <slot />
  </header>
</template>

<script setup>
import { chat } from '../chat'
import Icon from './Icon.vue'
defineProps({ title: String, icon: { type: String, default: 'grid' }, desc: String })
</script>
