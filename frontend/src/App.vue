<template>
  <div v-if="!auth.user" class="login">
    <div class="login-card">
      <img src="/logo.png" alt="Logo" class="login-logo" />
      <h1>Trợ lý AI nội bộ</h1>
      <p class="muted">Tra cứu văn bản · Hỏi đáp tài liệu · Hỗ trợ kỹ thuật<br>Vận hành hoàn toàn trên mạng nội bộ</p>
      <p v-if="auth.error" class="err">{{ auth.error }}</p>
      <template v-if="auth.mode === 'dev'">
        <div class="login-note"><Icon name="info" :size="15" /> Môi trường thử nghiệm – chọn tài khoản</div>
        <button v-for="u in auth.devUsers" :key="u" class="acc" @click="devLogin(u)">
          <span class="avatar-txt">{{ u.slice(0, 2).toUpperCase() }}</span>
          <span class="grow"><b>{{ u }}</b><small class="muted">{{ DEV_DESC[u] || '' }}</small></span>
          <Icon name="right" :size="16" />
        </button>
      </template>
    </div>
  </div>
  <div v-else class="shell">
    <AppSidebar :open="menu" @close="menu = false" />
    <div v-if="menu" class="scrim" @click="menu = false" />
    <main class="content">
      <router-view v-slot="{ Component }">
        <component :is="Component" @menu="menu = true" />
      </router-view>
      <button v-if="!isChat" class="icon-btn fab-menu only-mobile" title="Danh mục" @click="menu = true"><Icon name="menu" /></button>
    </main>
  </div>
  <UiHost />
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { auth, devLogin } from './auth'
import { loadConvs } from './chat'
import { loadPins } from './extensions'
import AppSidebar from './components/AppSidebar.vue'
import Icon from './components/Icon.vue'
import UiHost from './components/UiHost.vue'

const DEV_DESC = { canbo: 'Cán bộ – hỏi đáp, tra cứu, nạp tài liệu', kiemduyet1: 'Kiểm duyệt cấp 1', kiemduyet2: 'Kiểm duyệt cấp 2', quantri: 'Quản trị hệ thống' }
const route = useRoute()
const menu = ref(false)
const isChat = computed(() => route.path === '/' || route.path.startsWith('/c/'))

watch(() => auth.user?.username, (u) => { if (u) { loadPins(); loadConvs() } }, { immediate: true })
</script>
