<template>
  <div class="page">
    <PageHeader title="Tiện ích" icon="grid" desc="Các chức năng mở rộng quanh trợ lý trò chuyện. Ghim tiện ích hay dùng để hiển thị trên thanh bên." />
    <template v-for="g in groups" :key="g.name">
      <h2 class="grp">{{ g.name }}</h2>
      <div class="ext-grid">
        <div v-for="e in g.items" :key="e.id" class="ext-card">
          <router-link :to="e.path" class="ext-main">
            <span class="ext-ico"><Icon :name="e.icon" :size="22" /></span>
            <b>{{ e.name }}</b>
            <span class="muted small">{{ e.desc }}</span>
          </router-link>
          <button :class="['pin', { on: pins.ids.includes(e.id) }]" :title="pins.ids.includes(e.id) ? 'Bỏ ghim' : 'Ghim lên thanh bên'" @click="togglePin(e.id)">
            <Icon name="pin" :size="15" /> {{ pins.ids.includes(e.id) ? 'Đã ghim' : 'Ghim' }}
          </button>
        </div>
      </div>
    </template>
    <div class="card tip">
      <Icon name="slash" /> <span>Trong ô trò chuyện, gõ <kbd>/</kbd> để mở nhanh tiện ích hoặc chọn chế độ trả lời (ví dụ <kbd>/nguyenvan</kbd>, <kbd>/kythuat</kbd>, <kbd>/tong-hop</kbd>).</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { pins, togglePin, visibleExtensions } from '../extensions'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'

const groups = computed(() => {
  const out = []
  for (const e of visibleExtensions()) {
    let g = out.find((x) => x.name === e.group)
    if (!g) out.push(g = { name: e.group, items: [] })
    g.items.push(e)
  }
  return out
})
</script>
