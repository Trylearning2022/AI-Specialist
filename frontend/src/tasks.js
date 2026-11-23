// Tác vụ dài (agent): tạo, thăm dò tiến trình, danh sách tác vụ đang chạy (huy hiệu trên thanh bên).
// Giao diện thăm dò GET /agent/tasks/{id} mỗi 1,5 giây khi tác vụ còn chạy – đơn giản, bền với proxy, mạng nội bộ.
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { api } from './api'

export const TASK_KIND = {
  phan_tich: { label: 'Phân tích văn bản', icon: 'scan', path: '/tac-vu/moi/phan_tich' },
  soan_thao: { label: 'Soạn văn bản tham mưu', icon: 'pen', path: '/tac-vu/moi/soan_thao' },
  gop_y: { label: 'Soạn văn bản tham mưu', icon: 'pen', path: '/tac-vu/moi/soan_thao?mau=soan-cong-van-gop-y&che_do=gop_y' },  // tác vụ 1.4.0
  tong_hop: { label: 'Tổng hợp báo cáo', icon: 'merge', path: '/tac-vu/moi/tong_hop' },
}
export const TASK_STATUS = {
  cho: { label: 'Đang chờ', cls: 'wait' }, dang_chay: { label: 'Đang xử lý', cls: 'run' },
  cho_xac_nhan: { label: 'Chờ xác nhận', cls: 'confirm' }, xong: { label: 'Hoàn thành', cls: 'ok' },
  loi: { label: 'Lỗi', cls: 'err' }, da_huy: { label: 'Đã hủy', cls: 'mute' },
}
export const isActive = (s) => ['cho', 'dang_chay'].includes(s)

/** Thăm dò một tác vụ; tự dừng khi tác vụ kết thúc hoặc thành phần bị hủy. */
export function useTask(idRef) {
  const task = ref(null), error = ref('')
  let timer = null
  async function load() {
    const id = typeof idRef === 'function' ? idRef() : idRef.value ?? idRef
    if (!id) return
    try {
      task.value = await api.get('/agent/tasks/' + id)
      error.value = ''
    } catch (e) { error.value = e.message; stop() }
    if (task.value && !isActive(task.value.status)) stop()
  }
  function start() { stop(); load(); timer = setInterval(load, 1500) }
  function stop() { if (timer) clearInterval(timer); timer = null }
  watch(() => (typeof idRef === 'function' ? idRef() : idRef.value ?? idRef), start, { immediate: true })
  onBeforeUnmount(stop)
  return { task, error, reload: start }
}

// Tác vụ đang chạy của người dùng (thanh bên): cập nhật mỗi 8 giây
export const active = reactive({ items: [] })
let poll = null
export async function refreshActive() {
  try { active.items = await api.get('/agent/tasks', { status: 'cho,dang_chay,cho_xac_nhan', limit: 20 }) } catch { /* */ }
}
export function startActivePoll() {
  stopActivePoll()
  refreshActive()
  poll = setInterval(refreshActive, 8000)
}
export function stopActivePoll() { if (poll) clearInterval(poll); poll = null }

export async function uploadFile(file) {
  const fd = new FormData()
  fd.append('file', file)
  return api.upload('/agent/uploads', fd)
}

export const fmtMs = (ms) => {
  if (ms == null) return ''
  const s = ms / 1000
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)} giây`
  const m = Math.floor(s / 60)
  return `${m} phút ${Math.round(s % 60)} giây`
}
export function elapsed(t) {
  if (!t?.started_at) return ''
  const end = t.finished_at ? new Date(t.finished_at) : new Date()
  return fmtMs(end - new Date(t.started_at))
}
