<template>
  <div class="tree">
    <div v-if="!sess" class="tree-start">
      <div class="tree-title"><Icon name="steps" /> <b>{{ tree.ten }}</b></div>
      <p v-if="tree.mo_ta" class="muted small">{{ tree.mo_ta }}</p>
      <button class="btn sm" :disabled="busy" @click="start"><Icon name="right" :size="15" /> Bắt đầu xử lý</button>
    </div>
    <template v-else>
      <div class="tree-head">
        <div class="tree-title"><Icon name="steps" /> <b>{{ sess.tree.ten }}</b></div>
        <button class="btn ghost sm" @click="reset"><Icon name="refresh" :size="14" /> Làm lại</button>
      </div>
      <ol v-if="path.length" class="tree-path">
        <li v-for="(p, i) in path" :key="i"><span class="muted">{{ p.hoi }}</span> <b>{{ p.chon }}</b></li>
      </ol>
      <div class="tree-step">
        <p v-if="step.hoi" class="tree-q">{{ step.hoi }}</p>
        <p v-if="step.huong_dan">{{ step.huong_dan }}</p>
        <p v-if="step.thong_bao" class="ok">{{ step.thong_bao }}</p>
      </div>
      <template v-if="!step.ket_thuc && !step.tao_phieu && !ticket">
        <div class="tree-opts">
          <button v-for="(o, i) in step.lua_chon" :key="i" class="opt" :disabled="busy" @click="answer({ lua_chon: i, o })">{{ o }}</button>
        </div>
        <div class="tree-free">
          <input v-model="free" placeholder="Hoặc mô tả tình trạng bằng lời…" @keyup.enter="answer({ text: free })" />
          <button class="btn ghost sm" :disabled="busy || !free.trim()" @click="answer({ text: free })">Gửi</button>
        </div>
        <p v-if="note" class="warn small">{{ note }}</p>
      </template>
      <div v-if="ticket" class="tree-done ok"><Icon name="ticket" /> Đã tạo phiếu yêu cầu hỗ trợ số <b>{{ ticket.id }}</b>
        kèm các bước đã thực hiện. Cán bộ kỹ thuật sẽ liên hệ.</div>
      <div v-else-if="step.ket_thuc" class="tree-done ok"><Icon name="check" /> Hoàn thành hướng dẫn.</div>
    </template>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../api'
import { toast } from '../ui'
import Icon from './Icon.vue'

const props = defineProps({ tree: { type: Object, required: true }, autostart: Boolean })
const emit = defineEmits(['ticket'])
const sess = ref(null), step = ref({}), path = ref([]), ticket = ref(null), free = ref(''), note = ref(''), busy = ref(false)

async function start() {
  busy.value = true
  try {
    const r = await api.post('/support/sessions', { tree_id: props.tree.id })
    sess.value = r; step.value = r.step; path.value = []; ticket.value = null; note.value = ''
  } catch (e) { toast(e.message, 'err') } finally { busy.value = false }
}
function reset() { sess.value = null; if (props.autostart) start() }
async function answer({ lua_chon, text, o }) {
  if (lua_chon == null && !text?.trim()) return
  busy.value = true
  try {
    const r = await api.post(`/support/sessions/${sess.value.session_id}/answer`, lua_chon != null ? { lua_chon } : { text })
    note.value = r.thong_bao && r.can_lam_ro ? r.thong_bao : ''
    if (!r.can_lam_ro) { path.value.push({ hoi: step.value.hoi || step.value.huong_dan, chon: o || text }); step.value = r.step }
    free.value = ''
    if (r.ticket) { ticket.value = r.ticket; emit('ticket', r.ticket) }
  } catch (e) { toast(e.message, 'err') } finally { busy.value = false }
}
if (props.autostart) start()
</script>
