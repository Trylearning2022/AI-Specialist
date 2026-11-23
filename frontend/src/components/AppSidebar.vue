<template>
  <aside :class="['sidebar', { open }]">
    <div class="sb-brand">
      <img src="/logo.png" alt="Logo" />
      <div><b>Trợ lý AI</b><small>Mạng nội bộ</small></div>
      <button class="icon-btn only-mobile" title="Đóng" @click="$emit('close')"><Icon name="x" /></button>
    </div>

    <button class="btn new-chat" @click="startNew"><Icon name="plus" :size="16" /> Cuộc trò chuyện mới</button>

    <div class="sb-search">
      <Icon name="search" :size="15" />
      <input v-model="q" placeholder="Tìm cuộc trò chuyện" aria-label="Tìm cuộc trò chuyện" />
    </div>

    <nav class="sb-convs" aria-label="Lịch sử trò chuyện">
      <template v-for="g in groups" :key="g.label">
        <div v-if="g.items.length" class="sb-label">{{ g.label }}</div>
        <div v-for="c in g.items" :key="c.id" :class="['conv', { on: c.id === chat.convId && route.path.startsWith('/c/') }]">
          <router-link :to="'/c/' + c.id" class="conv-t" :title="c.title" @click="$emit('close')">{{ c.title }}</router-link>
          <button class="icon-btn xs" title="Đổi tên" @click="rename(c)"><Icon name="edit" :size="14" /></button>
          <button class="icon-btn xs" title="Xóa" @click="remove(c)"><Icon name="trash" :size="14" /></button>
        </div>
      </template>
      <p v-if="!chat.convs.length" class="muted small pad">Chưa có cuộc trò chuyện nào.</p>
    </nav>

    <div v-if="active.items.length" class="sb-tasks">
      <div class="sb-label row">Tác vụ đang xử lý <span class="badge">{{ active.items.length }}</span>
        <router-link to="/tac-vu" class="grow tr small" @click="$emit('close')">Tất cả</router-link></div>
      <router-link v-for="t in active.items.slice(0, 4)" :key="t.id" :to="'/tac-vu/' + t.id" class="sb-task" @click="$emit('close')">
        <Icon :name="TASK_KIND[t.kind]?.icon || 'tasks'" :size="15" />
        <span class="grow"><span class="clamp1">{{ t.title }}</span>
          <span class="sb-task-bar"><i :class="t.status" :style="{ width: Math.max(4, t.progress) + '%' }" /></span></span>
        <small v-if="t.status === 'cho_xac_nhan'" class="tag warn-tag">Chờ xác nhận</small>
      </router-link>
    </div>

    <div class="sb-ext">
      <div class="sb-label row">Tiện ích <router-link to="/tien-ich" class="grow tr small" @click="$emit('close')">Tất cả</router-link></div>
      <router-link v-for="e in pinned" :key="e.id" :to="e.path" class="ext-link" @click="$emit('close')">
        <Icon :name="e.icon" :size="17" /> {{ e.name }}
      </router-link>
      <router-link v-if="!pinned.length" to="/tien-ich" class="ext-link muted" @click="$emit('close')"><Icon name="grid" :size="17" /> Chọn tiện ích để ghim</router-link>
    </div>

    <div class="sb-user">
      <div class="avatar-txt">{{ initials }}</div>
      <div class="grow">
        <b class="clamp1">{{ auth.user.name || auth.user.username }}</b>
        <small class="clamp1" :title="auth.user.units.join(', ')">{{ roleText }} · {{ DO_MAT[auth.user.effective_clearance] }}</small>
      </div>
      <button class="icon-btn" :title="ui.theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'" @click="setTheme(ui.theme === 'dark' ? 'light' : 'dark')">
        <Icon :name="ui.theme === 'dark' ? 'sun' : 'moon'" /></button>
      <button class="icon-btn" title="Đăng xuất" @click="logout"><Icon name="logout" /></button>
    </div>
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { auth, logout } from '../auth'
import { chat, deleteConv, newConv, renameConv } from '../chat'
import { pinnedExtensions } from '../extensions'
import { TASK_KIND, active } from '../tasks'
import { DO_MAT } from '../md'
import { confirmBox, promptBox, setTheme, toast, ui } from '../ui'
import Icon from './Icon.vue'

defineProps({ open: Boolean })
const emit = defineEmits(['close'])
const route = useRoute(), router = useRouter()
const q = ref('')
const pinned = computed(() => pinnedExtensions())
const ROLE = { admin: 'Quản trị', reviewer: 'Kiểm duyệt', user: 'Cán bộ' }
const roleText = computed(() => auth.user.roles.map((r) => ROLE[r] || r).join(', '))
const initials = computed(() => (auth.user.name || auth.user.username).split(/\s+/).map((w) => w[0]).slice(-2).join('').toUpperCase())

const groups = computed(() => {
  const k = q.value.trim().toLowerCase()
  const items = chat.convs.filter((c) => !k || c.title.toLowerCase().includes(k))
  const day = 864e5, now = Date.now(), start = new Date().setHours(0, 0, 0, 0)
  const g = [{ label: 'Hôm nay', items: [] }, { label: '7 ngày qua', items: [] }, { label: 'Trước đó', items: [] }]
  for (const c of items) {
    const t = new Date(c.updated_at).getTime()
    g[t >= start ? 0 : now - t < 7 * day ? 1 : 2].items.push(c)
  }
  return g
})

function startNew() { newConv(); router.push('/'); emit('close') }
async function rename(c) {
  const t = await promptBox('Đổi tên cuộc trò chuyện', { value: c.title, multiline: false, ok: 'Lưu' })
  if (t) await renameConv(c.id, t)
}
async function remove(c) {
  if (!(await confirmBox(`Xóa cuộc trò chuyện “${c.title}”?`, { ok: 'Xóa', danger: true }))) return
  await deleteConv(c.id)
  if (route.path === '/c/' + c.id) router.push('/')
  toast('Đã xóa cuộc trò chuyện.')
}
</script>
