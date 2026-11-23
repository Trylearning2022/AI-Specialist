<template>
  <div :class="['chatpage', { 'with-panel': chat.panel.open }]">
    <section class="chatmain">
      <header class="chat-h">
        <button class="icon-btn only-mobile" title="Danh mục" @click="$emit('menu')"><Icon name="menu" /></button>
        <div class="grow clamp1 chat-title">{{ title }}</div>
        <button v-if="chat.messages.length" class="icon-btn" title="Cuộc trò chuyện mới" @click="fresh"><Icon name="plus" /></button>
        <button :class="['icon-btn', { on: chat.panel.open }]" title="Nguồn tham chiếu" @click="chat.panel.open = !chat.panel.open"><Icon name="panel" /></button>
      </header>

      <div ref="box" class="thread" @scroll="onScroll">
        <div v-if="!chat.messages.length" class="welcome">
          <img src="/logo.png" class="welcome-logo" alt="" />
          <h2>Xin chào{{ name ? ' đồng chí ' + name : '' }}</h2>
          <p class="muted">Trợ lý AI nội bộ – tra cứu văn bản, hỗ trợ kỹ thuật, phân tích văn bản mới, soạn văn bản tham mưu. Mọi dữ liệu xử lý trong mạng nội bộ.</p>
          <div class="suggest">
            <button v-for="s in SUGGESTIONS" :key="s.q" class="sugg" @click="ask(s.q, s.mode)">
              <span class="sugg-ico"><Icon :name="s.icon" :size="18" /></span>
              <b>{{ s.title }}</b>
              <span class="muted small">{{ s.q }}</span>
            </button>
          </div>
          <div class="ext-strip">
            <span class="muted small">Tiện ích:</span>
            <router-link v-for="e in exts" :key="e.id" :to="e.path" class="ext-chip"><Icon :name="e.icon" :size="14" /> {{ e.name }}</router-link>
          </div>
        </div>
        <div v-else class="thread-in">
          <ChatMessage v-for="(m, i) in chat.messages" :key="m.id || i" :m="m" />
        </div>
      </div>
      <button v-if="!atBottom" class="to-bottom" title="Xuống cuối" @click="scroll(true)"><Icon name="right" :size="16" style="transform:rotate(90deg)" /></button>

      <Composer ref="comp" @send="ask" />
    </section>
    <SidePanel />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { auth } from '../auth'
import { chat, newConv, openConv, send } from '../chat'
import { SUGGESTIONS, visibleExtensions } from '../extensions'
import { toast } from '../ui'
import ChatMessage from '../components/ChatMessage.vue'
import Composer from '../components/Composer.vue'
import Icon from '../components/Icon.vue'
import SidePanel from '../components/SidePanel.vue'

defineEmits(['menu'])
const route = useRoute(), router = useRouter()
const box = ref(null), comp = ref(null), atBottom = ref(true)
const name = computed(() => auth.user?.name || '')
const exts = computed(() => visibleExtensions().slice(0, 5))
const title = computed(() => chat.convs.find((c) => c.id === chat.convId)?.title || (chat.messages.length ? 'Cuộc trò chuyện' : 'Cuộc trò chuyện mới'))

function onScroll() {
  const el = box.value
  if (el) atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}
function scroll(force = false) {
  nextTick(() => { const el = box.value; if (el && (force || atBottom.value)) el.scrollTop = el.scrollHeight })
}
watch(() => [chat.messages.length, chat.messages[chat.messages.length - 1]?.content, chat.messages[chat.messages.length - 1]?.pending], () => scroll())

async function load() {
  const id = route.params.id
  try {
    if (id) { await openConv(id); scroll(true) } else if (chat.convId) router.replace('/c/' + chat.convId)
  } catch (e) { toast(e.message, 'err'); router.replace('/') }
}
watch(() => route.params.id, load)
onMounted(load)

function ask(text, att = [], mode) {
  if (typeof att === 'string') { mode = att; att = [] }  // gọi từ gợi ý: ask(câu hỏi, chế độ)
  atBottom.value = true
  send(text, { mode, attachments: att, onConv: (id) => router.replace('/c/' + id) })
  scroll(true)
}
function fresh() { newConv(); router.push('/'); comp.value?.focus() }
</script>
