// Danh mục tiện ích mở rộng quanh trợ lý trò chuyện. Người dùng tự ghim tiện ích hay dùng lên thanh bên.
import { reactive } from 'vue'
import { auth, has } from './auth'

export const EXTENSIONS = [
  { id: 'van-ban', path: '/chinh-xac', icon: 'scale', name: 'Văn bản chuẩn', group: 'Tra cứu',
    desc: 'Đọc nguyên văn quy định, quyết định đã duyệt hai cấp; mục lục, lịch sử phiên bản, so sánh thay đổi.' },
  { id: 'tai-lieu', path: '/tai-lieu', icon: 'folder', name: 'Danh mục tài liệu', group: 'Tra cứu',
    desc: 'Toàn bộ tài liệu đã nạp: lọc theo loại, luồng, độ mật; xem nội dung, thu hồi.' },
  { id: 'tong-hop', path: '/tong-hop', icon: 'layers', name: 'Tổng hợp báo cáo', group: 'Nghiệp vụ',
    desc: 'Lập báo cáo tổng hợp theo mẫu từ nhiều văn bản; số liệu do chương trình tính; xuất DOCX.' },
  { id: 'ho-tro', path: '/ho-tro', icon: 'wrench', name: 'Hỗ trợ kỹ thuật', group: 'Nghiệp vụ',
    desc: 'Xử lý sự cố theo hướng dẫn từng bước, phiếu yêu cầu hỗ trợ, đề xuất bổ sung tri thức.' },
  { id: 'nap-du-lieu', path: '/nap-du-lieu', icon: 'upload', name: 'Nạp dữ liệu', group: 'Dữ liệu',
    desc: 'Tải tài liệu lên, theo dõi chuyển đổi, chấm điểm chất lượng và kiểm duyệt.' },
  { id: 'quan-tri', path: '/quan-tri', icon: 'shield', name: 'Quản trị', group: 'Quản trị', roles: ['reviewer', 'admin'],
    desc: 'Trạng thái dịch vụ, thống kê, phản hồi người dùng, chất lượng dữ liệu, nhật ký kiểm toán.' },
]

const DEFAULT_PINS = ['van-ban', 'ho-tro', 'tong-hop']
const key = () => 'pins:' + (auth.user?.username || '')

export const pins = reactive({ ids: [] })

export function loadPins() {
  let ids = null
  try { ids = JSON.parse(localStorage.getItem(key()) || 'null') } catch { /* */ }
  pins.ids = Array.isArray(ids) ? ids : [...DEFAULT_PINS]
}

export function togglePin(id) {
  pins.ids = pins.ids.includes(id) ? pins.ids.filter((x) => x !== id) : [...pins.ids, id]
  try { localStorage.setItem(key(), JSON.stringify(pins.ids)) } catch { /* */ }
}

export const allowed = (e) => !e.roles || has(...e.roles)
export const visibleExtensions = () => EXTENSIONS.filter(allowed)
export const pinnedExtensions = () => pins.ids.map((id) => EXTENSIONS.find((e) => e.id === id)).filter((e) => e && allowed(e))
export const extByPath = (path) => EXTENSIONS.find((e) => path === e.path || path.startsWith(e.path + '/'))

// Chế độ trả lời (chip trên ô nhập và lệnh “/”)
export const MODES = [
  { id: 'tu_dong', label: 'Tự động', icon: 'sparkle', hint: 'Hệ thống tự chọn cách xử lý phù hợp' },
  { id: 'chinh_xac', label: 'Nguyên văn', icon: 'scale', cmd: 'nguyenvan', hint: 'Trích nguyên văn điều, khoản từ kho văn bản chuẩn' },
  { id: 'tra_cuu', label: 'Tài liệu', icon: 'book', cmd: 'tailieu', hint: 'Trả lời từ tài liệu nội bộ, có dẫn nguồn' },
  { id: 'ho_tro', label: 'Kỹ thuật', icon: 'wrench', cmd: 'kythuat', hint: 'Hướng dẫn xử lý sự cố từng bước' },
  { id: 'tim_tai_lieu', label: 'Tìm tài liệu', icon: 'search', cmd: 'tim', hint: 'Chỉ liệt kê tài liệu liên quan' },
  { id: 'tac_tu', label: 'Nhiều bước', icon: 'steps', cmd: 'nhieubuoc', hint: 'Trợ lý tự gọi nhiều công cụ (thử nghiệm, chậm)' },
]

// Gợi ý câu hỏi ở màn hình bắt đầu (chỉnh theo dữ liệu thực tế của đơn vị)
export const SUGGESTIONS = [
  { icon: 'scale', title: 'Trích nguyên văn quy định', mode: 'chinh_xac',
    q: 'Theo Điều 5 Quyết định 15/QĐ-ĐVA, thiết bị hư hỏng phải thu hồi trong thời hạn bao lâu?' },
  { icon: 'book', title: 'Hỏi đáp tài liệu nội bộ', mode: 'tra_cuu',
    q: 'Trong tuần 45, Phòng Kỹ thuật đã xử lý bao nhiêu sự cố kỹ thuật?' },
  { icon: 'wrench', title: 'Xử lý sự cố kỹ thuật', mode: 'ho_tro', q: 'Máy in không in được, đèn vẫn sáng' },
  { icon: 'search', title: 'Tìm tài liệu liên quan', mode: 'tim_tai_lieu', q: 'Các báo cáo công tác tuần 45' },
]
