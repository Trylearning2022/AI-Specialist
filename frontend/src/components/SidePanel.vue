<template>
  <aside :class="['sidepanel', { open: chat.panel.open }]" aria-label="Ngăn thông tin">
    <div class="sp-head">
      <div class="seg">
        <button :class="{ on: chat.panel.kind === 'sources' }" @click="chat.panel.kind = 'sources'">Nguồn ({{ chat.panel.sources.length }})</button>
        <button :class="{ on: chat.panel.kind === 'doc' }" :disabled="!chat.panel.doc" @click="chat.panel.kind = 'doc'">Văn bản</button>
      </div>
      <button class="icon-btn" title="Đóng" @click="chat.panel.open = false"><Icon name="x" /></button>
    </div>

    <div v-if="chat.panel.kind === 'sources'" ref="list" class="sp-body">
      <p v-if="!chat.panel.sources.length" class="muted small">Nguồn của câu trả lời hiển thị tại đây. Bấm chỉ số [n] trong câu trả lời để xem đoạn tương ứng.</p>
      <article v-for="s in chat.panel.sources" :key="s.n" :id="'src-' + s.n" :class="['srccard', { hl: s.n === chat.panel.hl }]">
        <div class="srccard-h">
          <span class="num">{{ s.n }}</span>
          <div class="grow"><b>{{ s.title }}</b><div class="muted small">{{ s.breadcrumb }}</div></div>
          <span v-if="s.nguon === 'B'" class="tag b">chuẩn</span>
          <span v-if="s.expanded" class="tag" title="Hệ thống đã ghép đủ các đoạn của mục này">cả mục</span>
        </div>
        <div class="md small" v-html="render(s.text)" />
        <a v-if="s.nguon === 'B'" class="link small" @click="showDoc(s.doc_id, s.section_id)">Xem nguyên văn <Icon name="right" :size="13" /></a>
      </article>
    </div>

    <div v-else class="sp-body">
      <p v-if="loading" class="muted small">Đang tải văn bản…</p>
      <template v-if="doc">
        <div class="doc-h">
          <div class="muted small">{{ doc.so_hieu }} · phiên bản {{ doc.commit?.slice(0, 8) }}</div>
          <b>{{ doc.ten }}</b>
          <div><span :class="['tag', doc.trang_thai === 'con_hieu_luc' ? 'ok' : 'err']">{{ STATUS[doc.trang_thai] || doc.trang_thai }}</span></div>
        </div>
        <div v-if="sec" class="exact">
          <div class="exact-h"><Icon name="quote" :size="15" /> <b>{{ sec.path?.slice(1).join(' › ') }}</b></div>
          <pre>{{ vb(sec.text) }}</pre>
          <div class="exact-f"><span>Mã mục {{ sec.section_id }} · SHA-256 {{ sec.sha256?.slice(0, 12) }}…</span>
            <a @click="copy(sec.text)"><Icon name="copy" :size="13" /> Sao chép</a></div>
        </div>
        <div class="toc">
          <div class="muted small" style="margin:.6rem 0 .3rem">Mục lục</div>
          <a v-for="t in doc.toc" :key="t.id" :class="{ on: sec && sec.section_id === t.id }" :style="{ paddingLeft: (t.level - 1) * 12 + 8 + 'px' }"
             @click="openSec(t.id)">{{ t.heading }}</a>
        </div>
        <router-link class="link small" :to="'/chinh-xac?doc=' + doc.doc_id + (sec ? '&sec=' + sec.section_id : '')">
          Mở trong tiện ích Văn bản chuẩn <Icon name="external" :size="13" /></router-link>
      </template>
    </div>
  </aside>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { api } from '../api'
import { chat, showDoc } from '../chat'
import { render, vb, STATUS } from '../md'
import { toast } from '../ui'
import Icon from './Icon.vue'

const doc = ref(null), sec = ref(null), loading = ref(false), list = ref(null)

watch(() => [chat.panel.doc, chat.panel.sec, chat.panel.open], async ([d, s, open]) => {
  if (!open || !d) return
  loading.value = true
  try {
    if (!doc.value || doc.value.doc_id !== d) doc.value = await api.get('/exact/docs/' + d)
    sec.value = s ? await api.get('/exact/sections/' + encodeURIComponent(s)) : null
  } catch (e) { toast(e.message, 'err') } finally { loading.value = false }
}, { immediate: true })

watch(() => [chat.panel.hl, chat.panel.open], ([n]) => {
  if (n) nextTick(() => document.getElementById('src-' + n)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
})

const openSec = (id) => { chat.panel.sec = id }
const copy = (t) => { navigator.clipboard?.writeText(t); toast('Đã sao chép nguyên văn.') }
</script>
