<template>
  <Teleport to="body">
    <div v-if="ui.dialog" class="modal-bg" @mousedown.self="closeDialog(ui.dialog.kind === 'confirm' ? false : null)">
      <div class="modal" role="dialog" aria-modal="true" @keydown.esc="closeDialog(ui.dialog.kind === 'confirm' ? false : null)">
        <h3>{{ ui.dialog.title }}</h3>
        <p v-if="ui.dialog.message" class="muted">{{ ui.dialog.message }}</p>
        <template v-if="ui.dialog.kind === 'prompt'">
          <textarea v-if="ui.dialog.multiline" ref="field" v-model="ui.dialog.value" rows="4" class="field" :placeholder="ui.dialog.placeholder"
                    @keydown.ctrl.enter="submit" />
          <input v-else ref="field" v-model="ui.dialog.value" class="field" :placeholder="ui.dialog.placeholder" @keydown.enter="submit" />
        </template>
        <div class="modal-actions">
          <button class="btn ghost" @click="closeDialog(ui.dialog.kind === 'confirm' ? false : null)">Hủy</button>
          <button :class="['btn', ui.dialog.danger ? 'danger' : '']" :disabled="ui.dialog.kind === 'prompt' && ui.dialog.required && !ui.dialog.value.trim()"
                  @click="submit">{{ ui.dialog.ok }}</button>
        </div>
      </div>
    </div>
    <div class="toasts" aria-live="polite">
      <div v-for="t in ui.toasts" :key="t.id" :class="['toast', t.kind]">
        <Icon :name="t.kind === 'err' ? 'alert' : 'check'" :size="16" />{{ t.text }}
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { ui, closeDialog } from '../ui'
import Icon from './Icon.vue'

const field = ref(null)
watch(() => ui.dialog, (d) => { if (d) nextTick(() => field.value?.focus()) })
function submit() {
  const d = ui.dialog
  if (!d) return
  if (d.kind === 'confirm') return closeDialog(true)
  if (d.required && !d.value.trim()) return
  closeDialog(d.value.trim())
}
</script>
