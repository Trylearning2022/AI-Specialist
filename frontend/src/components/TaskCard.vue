<template>
  <!-- Thẻ tác vụ dài trong trò chuyện: tiến trình trực tiếp, bước đang làm, mở chi tiết khi xong/chờ xác nhận -->
  <div :class="['taskcard', st.cls]">
    <div class="tc-head">
      <span class="tc-ico"><Icon :name="kind.icon" :size="18" /></span>
      <div class="grow">
        <b class="clamp1">{{ t?.title || task.title }}</b>
        <span class="muted small">{{ kind.label }} · <span :class="['tstatus', st.cls]">{{ st.label }}</span>
          <template v-if="t?.started_at"> · {{ elapsed(t) }}</template></span>
      </div>
      <span v-if="t && t.status !== 'xong'" class="tc-pct">{{ t.progress }}%</span>
    </div>
    <div v-if="t" class="tc-bar"><i :style="{ width: t.progress + '%' }" /></div>
    <div v-if="t && current && t.status !== 'cho_xac_nhan'" class="tc-now">
      <span v-if="t.status === 'dang_chay'" class="spin sm" /><Icon v-else name="pause" :size="13" />
      <span class="clamp1">{{ t.note || current.detail || current.name }}</span>
    </div>
    <p v-if="t?.status === 'cho' && t.queue_pos" class="muted small">Đang chờ {{ t.queue_pos }} tác vụ trước hoàn thành.</p>
    <p v-if="t?.status === 'cho_xac_nhan'" class="tc-confirm"><Icon name="info" :size="14" /> {{ t.note }}</p>
    <p v-if="t?.status === 'loi'" class="err small">{{ t.error }}</p>
    <details v-if="t?.plan?.length" class="tc-steps" :open="open" @toggle="open = $event.target.open">
      <summary>{{ doneCount }}/{{ t.plan.length }} bước</summary>
      <StepTimeline :steps="t.plan" compact />
    </details>
    <div class="tc-actions">
      <router-link :to="'/tac-vu/' + task.id" class="btn sm" :class="{ ghost: t?.status !== 'xong' && t?.status !== 'cho_xac_nhan' }">
        <Icon :name="t?.status === 'cho_xac_nhan' ? 'edit' : 'external'" :size="14" />
        {{ t?.status === 'xong' ? 'Xem kết quả' : t?.status === 'cho_xac_nhan' ? 'Rà soát, xác nhận' : 'Mở chi tiết' }}
      </router-link>
      <button v-if="t && ['cho', 'dang_chay', 'cho_xac_nhan'].includes(t.status)" class="btn ghost sm" @click="cancel">Hủy</button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'
import { TASK_KIND, TASK_STATUS, elapsed, refreshActive, useTask } from '../tasks'
import { confirmBox, toast } from '../ui'
import Icon from './Icon.vue'
import StepTimeline from './StepTimeline.vue'

const props = defineProps({ task: { type: Object, required: true } })
const { task: t, reload } = useTask(() => props.task.id)
const open = ref(false)
const kind = computed(() => TASK_KIND[props.task.kind] || { label: props.task.kind_label, icon: 'tasks' })
const st = computed(() => TASK_STATUS[t.value?.status || props.task.status] || TASK_STATUS.cho)
const current = computed(() => t.value?.plan?.find((p) => p.id === t.value.current) || t.value?.plan?.find((p) => p.status === 'cho_xac_nhan'))
const doneCount = computed(() => (t.value?.plan || []).filter((p) => ['xong', 'bo_qua'].includes(p.status)).length)
async function cancel() {
  if (!(await confirmBox('Hủy tác vụ này?', { ok: 'Hủy tác vụ', danger: true }))) return
  await api.post(`/agent/tasks/${props.task.id}/cancel`)
  toast('Đã hủy tác vụ.'); reload(); refreshActive()
}
</script>
