import { createRouter, createWebHistory } from 'vue-router'
import { has } from './auth'

const routes = [
  { path: '/', component: () => import('./views/ChatView.vue'), meta: { title: 'Trò chuyện' } },
  { path: '/c/:id', component: () => import('./views/ChatView.vue'), meta: { title: 'Trò chuyện' } },
  { path: '/tien-ich', component: () => import('./views/LauncherView.vue'), meta: { title: 'Tiện ích' } },
  { path: '/chinh-xac', component: () => import('./views/ExactView.vue'), meta: { title: 'Văn bản chuẩn' } },
  { path: '/tong-hop', component: () => import('./views/SummaryView.vue'), meta: { title: 'Tổng hợp báo cáo' } },
  { path: '/ho-tro', component: () => import('./views/SupportView.vue'), meta: { title: 'Hỗ trợ kỹ thuật' } },
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
