<template>
  <div class="page">
  <PageHeader title="Danh mục tài liệu" icon="folder" desc="Tài liệu đã nạp và duyệt; phạm vi hiển thị theo quyền và độ mật của tài khoản." />
  <div class="card toolbar">
    <input v-model="q" placeholder="Tên, số hiệu, mã tài liệu" @keyup.enter="load" />
    <select v-model="loai" @change="load"><option value="">Mọi loại</option>
      <option v-for="(v, k) in LOAI" :key="k" :value="k">{{ v }}</option></select>
    <select v-model="track" @change="load"><option value="">Mọi luồng</option>
      <option value="A">Luồng A – tham khảo</option><option value="B">Luồng B – văn bản chuẩn</option></select>
    <button class="btn" @click="load"><Icon name="filter" :size="15" /> Lọc</button>
  </div>
  <div class="card">
    <table>
      <tr><th>Tài liệu</th><th>Loại</th><th>Luồng</th><th>Độ mật</th><th>Phiên bản</th><th></th></tr>
      <tr v-for="d in docs" :key="d.doc_id">
        <td><b>{{ d.title }}</b><br><span class="muted">{{ d.so_hieu }} · {{ d.doc_id }} · {{ d.ngay_ban_hanh }}</span></td>
        <td>{{ LOAI[d.loai] || d.loai }}</td>
        <td><span :class="['tag', d.track === 'B' ? 'b' : '']">{{ d.track === 'B' ? 'Văn bản chuẩn' : 'Tham khảo' }}</span></td>
        <td>{{ DO_MAT[d.do_mat] }}<br><span class="muted">{{ d.don_vi.join(', ') }}</span></td>
        <td>{{ d.version }}<span v-if="d.commit" class="muted"> · {{ d.commit.slice(0, 8) }}</span></td>
        <td>
          <a @click="view(d)">Xem</a>
          <router-link v-if="d.track === 'B'" :to="'/chinh-xac?doc=' + d.doc_id"> · Nguyên văn</router-link>
          <a v-if="has('admin')" class="err" @click="revoke(d)"> · Thu hồi</a>
        </td>
      </tr>
    </table>
    <p v-if="!docs.length" class="empty">Không có tài liệu phù hợp.</p>
  </div>
  <div v-if="cur" class="card"><div class="row"><h3 class="grow">{{ cur.title }}</h3><button class="icon-btn" title="Đóng" @click="cur = null"><Icon name="x" /></button></div>
    <div class="md preview" v-html="render(curMd)" /></div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { has } from '../auth'
import { render, DO_MAT, LOAI } from '../md'
import { confirmBox, toast } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'

const docs = ref([]), q = ref(''), loai = ref(''), track = ref(''), cur = ref(null), curMd = ref('')
onMounted(load)
async function load() { docs.value = await api.get('/ingest/documents', { q: q.value, loai: loai.value, track: track.value }) }
async function view(d) { cur.value = d; curMd.value = (await api.get(`/ingest/documents/${d.doc_id}/markdown`)).replace(/^---[\s\S]*?\n---\n/, '') }
async function revoke(d) {
  if (!(await confirmBox(`Thu hồi tài liệu ${d.doc_id} khỏi mọi kho (chỉ mục tìm kiếm, kho chuẩn)?`, { title: 'Thu hồi tài liệu', ok: 'Thu hồi', danger: true }))) return
  await api.del('/ingest/documents/' + d.doc_id); toast('Đã thu hồi tài liệu.'); load()
}
</script>
