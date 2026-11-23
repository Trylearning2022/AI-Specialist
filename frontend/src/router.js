import { createRouter, createWebHistory } from 'vue-router'
import { has } from './auth'

const routes = [
  { path: '/', component: () => import('./views/ChatView.vue'), meta: { title: 'Trò chuyện' } },
  { path: '/c/:id', component: () => import('./views/ChatView.vue'), meta: { title: 'Trò chuyện' } },
  { path: '/tien-ich', component: () => import('./views/LauncherView.vue'), meta: { title: 'Tiện ích' } },
  { path: '/chinh-xac', component: () => import('./views/ExactView.vue'), meta: { title: 'Văn bản chuẩn' } },
  { path: '/tong-hop', redirect: (to) => ({ path: '/tac-vu/moi/tong_hop', query: to.query }) },
  { path: '/tac-vu', component: () => import('./views/TasksView.vue'), meta: { title: 'Tác vụ của tôi' } },
  { path: '/tac-vu/moi/:kind', component: () => import('./views/TaskNewView.vue'), meta: { title: 'Tác vụ mới' } },
  { path: '/tac-vu/:id', component: () => import('./views/TaskView.vue'), meta: { title: 'Tác vụ' } },
  { path: '/ho-tro', component: () => import('./views/SupportView.vue'), meta: { title: 'Phiếu hỗ trợ kỹ thuật' } },
  { path: '/giam-dinh', component: () => import('./views/QualityView.vue'), meta: { title: 'Giám định dữ liệu', roles: ['reviewer', 'admin'] } },
  { path: '/giam-sat', component: () => import('./views/MonitorView.vue'), meta: { title: 'Giám sát hệ thống', roles: ['reviewer', 'admin'] } },
  { path: '/nap-du-lieu', component: () => import('./views/IngestView.vue'), meta: { title: 'Nạp dữ liệu' } },
  { path: '/kiem-duyet/:id', component: () => import('./views/ReviewView.vue'), meta: { title: 'Kiểm duyệt', roles: ['reviewer', 'admin'] } },
  { path: '/tai-lieu', component: () => import('./views/DocumentsView.vue'), meta: { title: 'Danh mục tài liệu' } },
  { path: '/quan-tri', component: () => import('./views/AdminView.vue'), meta: { title: 'Quản trị', roles: ['reviewer', 'admin'] } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({ history: createWebHistory(), routes })
router.beforeEach((to) => {
  if (to.meta.roles && !has(...to.meta.roles)) return '/'
  document.title = `${to.meta.title || ''} – Trợ lý AI nội bộ`
})
