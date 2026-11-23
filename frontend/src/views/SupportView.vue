<template>
  <div class="page">
    <PageHeader title="Phiếu hỗ trợ kỹ thuật" icon="ticket" desc="Tạo, theo dõi phiếu yêu cầu hỗ trợ; ghi kết quả xử lý và đề xuất bổ sung tri thức." />
    <div class="cols">
      <div>
        <div class="card tip-card">
          <h3><Icon name="wrench" :size="16" /> Xử lý sự cố ngay trong trò chuyện</h3>
          <p class="muted small">Mô tả sự cố trong ô trò chuyện (thiết bị, biểu hiện, thông báo lỗi). Trợ lý trích các bước xử lý từ tài liệu
            kỹ thuật của đơn vị, hỏi lại khi chưa rõ thiết bị hoặc triệu chứng; nếu chưa khắc phục được, tạo phiếu ngay từ câu trả lời.</p>
          <router-link class="btn sm" :to="{ path: '/', query: {} }" @click="prefill('', 'ho_tro')"><Icon name="chat" :size="14" /> Hỏi trợ lý</router-link>
        </div>
        <div class="card">
          <h3>Tạo phiếu yêu cầu hỗ trợ</h3>
          <input v-model="tf.title" style="width:100%" placeholder="Tiêu đề, ví dụ: Máy tính phòng 204 không khởi động" />
          <textarea v-model="tf.description" rows="4" class="field" style="margin-top:.5rem" placeholder="Mô tả sự cố, vị trí, thời điểm, các bước đã thử…" />
          <button class="btn" style="margin-top:.5rem" :disabled="!tf.title.trim()" @click="createTicket"><Icon name="ticket" :size="15" /> Gửi phiếu</button>
        </div>
      </div>
      <div class="card">
        <div class="row" style="margin-bottom:.6rem"><h3 class="grow" style="margin:0">Phiếu yêu cầu</h3>
          <label v-if="has('reviewer', 'admin')" class="small"><input v-model="all" type="checkbox" @change="loadTickets" /> Tất cả phiếu</label></div>
        <table>
          <tr><th>Số</th><th>Nội dung</th><th>Trạng thái</th></tr>
          <tr v-for="t in tickets" :key="t.id">
            <td>{{ t.id }}</td>
            <td><b>{{ t.title }}</b><div class="muted small" style="white-space:pre-wrap">{{ t.description }}</div>
              <div v-if="t.result" class="ok small">Kết quả: {{ t.result }}</div>
              <div v-if="has('reviewer', 'admin')" class="row" style="margin-top:.35rem">
                <button v-if="t.status !== 'da_xong'" class="btn ghost sm" @click="finish(t)">Ghi kết quả, đóng phiếu</button>
                <button v-if="t.status === 'da_xong' && !t.kb_job" class="btn ghost sm" @click="propose(t)">Đề xuất bổ sung tri thức</button>
                <span v-if="t.kb_job" class="muted small">Đã đề xuất (tác vụ {{ t.kb_job.slice(0, 8) }})</span>
              </div></td>
            <td><span :class="['tag', t.status === 'da_xong' ? 'ok' : '']">{{ STATUS[t.status] }}</span><br><span class="muted small">{{ t.username }} · {{ fmtDate(t.created_at) }}</span></td>
          </tr>
        </table>
        <p v-if="!tickets.length" class="empty">Chưa có phiếu yêu cầu.</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { has } from '../auth'
import { STATUS, fmtDate } from '../md'
import { promptBox, toast } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import { prefill } from '../chat'

const tickets = ref([]), all = ref(false), tf = reactive({ title: '', description: '' })

onMounted(loadTickets)
async function loadTickets() { tickets.value = await api.get('/support/tickets', { all: all.value }) }
async function createTicket() {
  await api.post('/support/tickets', { ...tf }); tf.title = tf.description = ''
  toast('Đã gửi phiếu yêu cầu hỗ trợ.'); loadTickets()
}
async function finish(t) {
  const result = await promptBox('Kết quả xử lý', { message: `Phiếu số ${t.id}: ${t.title}`, placeholder: 'Nguyên nhân, cách khắc phục…', ok: 'Đóng phiếu' })
  if (result) { await api.patch('/support/tickets/' + t.id, { status: 'da_xong', result }); loadTickets() }
}
async function propose(t) {
  await api.post(`/support/tickets/${t.id}/propose-kb`); loadTickets()
  toast('Đã chuyển đề xuất vào hàng đợi kiểm duyệt dữ liệu.')
}
</script>
