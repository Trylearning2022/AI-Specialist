// Hộp thoại, thông báo nhanh dùng chung (thay prompt/confirm/alert của trình duyệt).
import { reactive } from 'vue'

export const ui = reactive({ dialog: null, toasts: [], theme: 'light' })
let seq = 0

function open(opts) {
  return new Promise((resolve) => { ui.dialog = { value: opts.value || '', ...opts, resolve } })
}

export function closeDialog(result) {
  const d = ui.dialog
  ui.dialog = null
  d?.resolve(result)
}

/** Hộp thoại xác nhận → true/false */
export const confirmBox = (message, { title = 'Xác nhận', ok = 'Đồng ý', danger = false } = {}) =>
  open({ kind: 'confirm', title, message, ok, danger })

/** Hộp thoại nhập văn bản → chuỗi đã nhập hoặc null khi hủy */
export const promptBox = (title, { message = '', placeholder = '', ok = 'Gửi', multiline = true, required = true, value = '' } = {}) =>
  open({ kind: 'prompt', title, message, placeholder, ok, multiline, required, value })

export function toast(text, kind = 'ok', ms = 3500) {
  const id = ++seq
  ui.toasts.push({ id, text, kind })
  setTimeout(() => { ui.toasts = ui.toasts.filter((t) => t.id !== id) }, ms)
}

export function setTheme(t) {
  ui.theme = t
  document.documentElement.dataset.theme = t
  try { localStorage.setItem('theme', t) } catch { /* */ }
}

export function initTheme() {
  let t = null
  try { t = localStorage.getItem('theme') } catch { /* */ }
  if (!t) t = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  setTheme(t)
}
