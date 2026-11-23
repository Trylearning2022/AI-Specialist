<template>
  <div class="page">
    <PageHeader title="Tác vụ của tôi" icon="tasks" desc="Tác vụ dài chạy nền theo từng bước: phân tích văn bản, soạn văn bản tham mưu, tổng hợp báo cáo.">
      <router-link v-for="(k, id) in TASK_KIND" :key="id" :to="k.path" class="btn sm" :class="{ ghost: id !== 'phan_tich' }">
        <Icon :name="k.icon" :size="14" /> {{ k.label }}</router-link>
    </PageHeader>

    <div class="toolbar">
      <div class="seg narrow">
        <button v-for="f in FILTERS" :key="f.id" :class="{ on: filter === f.id }" @click="filter = f.id">{{ f.label }}
          <span v-if="count(f) " class="seg-n">{{ count(f) }}</span></button>
      </div>
      <select v-model="kind"><option value="">Mọi loại tác vụ</option>
        <option v-for="(k, id) in TASK_KIND" :key="id" :value="id">{{ k.label }}</option></select>
      <button class="icon-btn" title="Làm mới" @click="load"><Icon name="refresh" /></button>
    </div>

    <div class="task-list">
      <router-link v-for="t in shown" :key="t.id" :to="'/tac-vu/' + t.id" :class="['task-row', TASK_STATUS[t.status]?.cls]">
        <span class="tr-ico"><Icon :name="TASK_KIND[t.kind]?.icon || 'tasks'" :size="18" /></span>
        <div class="grow">
          <div class="row"><b class="clamp1 grow">{{ t.title }}</b>
            <span :class="['tstatus', TASK_STATUS[t.status]?.cls]">{{ TASK_STATUS[t.status]?.label }}</span></div>
          <div class="tr-bar"><i :style="{ width: t.progress + '%' }" /></div>
          <div class="muted small">{{ t.kind_label }} · tạo {{ fmtDate(t.created_at) }}<template v-if="t.started_at"> · {{ elapsed(t) }}</template>
            <template v-if="t.status === 'dang_chay' && cur(t)"> · {{ cur(t).name }}</template>
            <template v-if="t.note"> · {{ t.note }}</template></div>
        </div>
      </router-link>
      <div v-if="!shown.length" class="empty">
        <Icon name="tasks" :size="28" /><p>Chưa có tác vụ. Đính kèm văn bản trong ô trò chuyện hoặc chọn một chức năng ở trên để bắt đầu.</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import { fmtDate } from '../md'
import { TASK_KIND, TASK_STATUS, elapsed } from '../tasks'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'

const FILTERS = [{ id: '', label: 'Tất cả' }, { id: 'chay', label: 'Đang chạy', st: ['cho', 'dang_chay'] },
  { id: 'xn', label: 'Chờ xác nhận', st: ['cho_xac_nhan'] }, { id: 'xong', label: 'Hoàn thành', st: ['xong'] },
  { id: 'loi', label: 'Lỗi, đã hủy', st: ['loi', 'da_huy'] }]
const items = ref([]), filter = ref(''), kind = ref('')
const shown = computed(() => {
  const f = FILTERS.find((x) => x.id === filter.value)
  return items.value.filter((t) => (!f.st || f.st.includes(t.status)) && (!kind.value || t.kind === kind.value))
})
const count = (f) => (f.st ? items.value.filter((t) => f.st.includes(t.status)).length : 0)
const cur = (t) => t.plan?.find((p) => p.id === t.current)
async function load() { items.value = await api.get('/agent/tasks', { limit: 200 }) }
let timer
onMounted(() => { load(); timer = setInterval(load, 4000) })
onBeforeUnmount(() => clearInterval(timer))
</script>
