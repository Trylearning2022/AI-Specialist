<template>
  <div class="page">
    <PageHeader title="Văn bản chuẩn" icon="scale" desc="Nguyên văn từ kho Markdown đã duyệt hai cấp – không qua mô hình, không dùng chỉ mục vector." />
    <div class="card toolbar">
      <input v-model="q" placeholder="Từ khóa, số hiệu, hoặc “Điều 5 khoản 2 …” (gõ có dấu hoặc không dấu)" @keyup.enter="search" />
      <button class="btn" @click="search"><Icon name="search" :size="16" /> Tìm</button>
    </div>
    <div class="cols">
      <div>
        <div v-if="searched" class="card">
          <h3>Kết quả tìm kiếm ({{ hits.length }})</h3>
          <p v-if="!hits.length" class="muted small">Không có mục phù hợp.</p>
          <div v-for="h in hits" :key="h.section_id" class="src">
            <a @click="openSec(h.doc_id, h.section_id)"><b>{{ h.path.slice(1).join(' › ') || h.heading }}</b></a>
            <div class="muted small">{{ h.snippet }}</div>
          </div>
        </div>
        <div class="card">
          <h3>Danh mục văn bản ({{ docs.length }})</h3>
          <table>
            <tr><th>Số hiệu</th><th>Tên văn bản</th><th>Trạng thái</th></tr>
            <tr v-for="d in docs" :key="d.doc_id">
              <td>{{ d.so_hieu }}</td>
              <td><a @click="openDoc(d.doc_id)">{{ d.ten }}</a><br><span class="muted small">{{ LOAI[d.loai] || d.loai }} · {{ d.ngay_ban_hanh }}</span></td>
              <td><span :class="['tag', d.trang_thai === 'con_hieu_luc' ? 'ok' : 'err']">{{ STATUS[d.trang_thai] || d.trang_thai }}</span></td>
            </tr>
          </table>
          <p v-if="!docs.length" class="empty">Kho văn bản chuẩn chưa có văn bản.</p>
        </div>
      </div>
      <div>
        <div v-if="sec" class="card">
          <div class="exact" style="margin:0">
            <div class="exact-h"><Icon name="quote" :size="15" /> <b>{{ sec.path.slice(1).join(' › ') }}</b><span class="muted">· {{ sec.so_hieu }}</span></div>
            <pre>{{ vb(sec.text) }}</pre>
            <div class="exact-f"><span>Mã mục {{ sec.section_id }} · dòng {{ sec.lines.join('–') }} · SHA-256 {{ sec.sha256.slice(0, 16) }}…</span>
              <span class="exact-a"><a @click="copy"><Icon name="copy" :size="13" /> Sao chép</a>
                <a @click="askAbout(sec.path.slice(1).join(' ') + ' ' + sec.so_hieu)"><Icon name="chat" :size="13" /> Hỏi trợ lý</a></span></div>
          </div>
        </div>
        <div v-if="doc" class="card">
          <div class="row"><h3 class="grow" style="margin:0">{{ doc.so_hieu }} – {{ doc.ten }}</h3>
            <button class="btn ghost sm" @click="askAbout(doc.so_hieu)"><Icon name="chat" :size="14" /> Hỏi về văn bản này</button></div>
          <div class="muted small" style="margin:.3rem 0 .6rem">Phiên bản kho {{ doc.commit.slice(0, 8) }} · {{ STATUS[doc.trang_thai] }}
            <span v-if="doc.thay_the_boi"> · thay thế bởi {{ doc.thay_the_boi }}</span></div>
          <div class="toc">
            <a v-for="t in doc.toc" :key="t.id" :class="{ on: sec && sec.section_id === t.id }" :style="{ paddingLeft: (t.level - 1) * 14 + 8 + 'px' }"
               @click="openSec(doc.doc_id, t.id)">{{ t.heading }} <span v-if="!t.explicit" class="tag" title="Mã tự sinh, chưa ổn định">mã tự sinh</span></a>
          </div>
          <button class="btn ghost sm" @click="loadVersions"><Icon name="clock" :size="14" /> Lịch sử phiên bản</button>
          <table v-if="versions.length" style="margin-top:.6rem">
            <tr><th>Thời gian</th><th>Người duyệt</th><th>Nội dung</th><th></th></tr>
            <tr v-for="(v, i) in versions" :key="v.commit">
              <td>{{ fmtDate(v.thoi_gian) }}</td><td>{{ v.tac_gia }}</td><td>{{ v.noi_dung }}</td>
              <td><a v-if="versions[i + 1]" @click="showDiff(versions[i + 1].commit, v.commit)">So sánh</a></td>
            </tr>
          </table>
          <pre v-if="diff" class="preview" style="white-space:pre-wrap;margin-top:.6rem">{{ diff }}</pre>
        </div>
        <div v-if="!doc && !sec" class="card empty"><Icon name="book" :size="28" /><p>Chọn một văn bản để xem mục lục và nguyên văn.</p></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { chat, prefill } from '../chat'
import { LOAI, STATUS, fmtDate, vb } from '../md'
import { toast } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'

const route = useRoute(), router = useRouter()
const q = ref(''), docs = ref([]), hits = ref([]), searched = ref(false), doc = ref(null), sec = ref(null), versions = ref([]), diff = ref('')

onMounted(async () => {
  docs.value = (await api.get('/exact/catalog')).docs
  if (route.query.doc) await openSec(route.query.doc, route.query.sec)
})
watch(() => route.query.doc, (d) => { if (d) openSec(d, route.query.sec) })
async function search() { hits.value = (await api.post('/exact/search', { query: q.value, limit: 15 })).results; searched.value = true }
async function openDoc(id) { doc.value = await api.get('/exact/docs/' + id); versions.value = []; diff.value = ''; sec.value = null }
async function openSec(docId, sid) {
  if (!doc.value || doc.value.doc_id !== docId) await openDoc(docId)
  if (sid) sec.value = await api.get('/exact/sections/' + encodeURIComponent(sid))
}
async function loadVersions() { versions.value = (await api.get(`/exact/docs/${doc.value.doc_id}/versions`)).versions }
async function showDiff(a, b) { diff.value = await api.get(`/exact/docs/${doc.value.doc_id}/diff`, { a, b }) }
const copy = () => { navigator.clipboard?.writeText(sec.value.text); toast('Đã sao chép nguyên văn.') }
function askAbout(ref_) {
  prefill(`Theo ${ref_}, `, 'chinh_xac')
  router.push(chat.convId ? '/c/' + chat.convId : '/')
}
</script>
