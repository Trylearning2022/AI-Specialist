// Danh mục tiện ích mở rộng quanh trợ lý trò chuyện. Người dùng tự ghim tiện ích hay dùng lên thanh bên.
import { reactive } from 'vue'
import { auth, has } from './auth'

export const EXTENSIONS = [
  { id: 'phan-tich', path: '/tac-vu/moi/phan_tich', icon: 'scan', name: 'Phân tích văn bản', group: 'Tác vụ AI',
    desc: 'Đưa văn bản mới vào: tóm tắt, chỉ ra vấn đề liên quan đến ngành theo bộ tiêu chí, nhiệm vụ – thời hạn, đối chiếu cơ sở tri thức.' },
  { id: 'soan-thao', path: '/tac-vu/moi/soan_thao', icon: 'pen', name: 'Soạn văn bản tham mưu', group: 'Tác vụ AI',
    desc: 'Tờ trình, báo cáo, kế hoạch, công văn (trả lời, đề nghị; tham gia ý kiến dự thảo): thu thập căn cứ, duyệt dàn ý, viết từng phần, xuất DOCX.' },
  { id: 'tong-hop', path: '/tac-vu/moi/tong_hop', icon: 'merge', name: 'Tổng hợp báo cáo', group: 'Tác vụ AI',
    desc: 'Lập báo cáo chung từ các báo cáo riêng lẻ (trong kho hoặc tải lên); số liệu do chương trình tính; xuất DOCX.' },
  { id: 'tac-vu', path: '/tac-vu', icon: 'tasks', name: 'Tác vụ của tôi', group: 'Tác vụ AI',
    desc: 'Theo dõi tiến trình từng bước các tác vụ đang chạy, xem lại kết quả, chạy lại tác vụ lỗi.' },
  { id: 'van-ban', path: '/chinh-xac', icon: 'scale', name: 'Văn bản chuẩn', group: 'Tra cứu',
    desc: 'Đọc nguyên văn quy định, quyết định đã duyệt hai cấp; mục lục, lịch sử phiên bản, so sánh thay đổi.' },
  { id: 'tai-lieu', path: '/tai-lieu', icon: 'folder', name: 'Danh mục tài liệu', group: 'Tra cứu',
    desc: 'Toàn bộ tài liệu đã nạp: lọc theo loại, luồng, độ mật; xem nội dung, thu hồi.' },
  { id: 'ho-tro', path: '/ho-tro', icon: 'ticket', name: 'Phiếu hỗ trợ kỹ thuật', group: 'Hỗ trợ',
    desc: 'Phiếu yêu cầu hỗ trợ (tạo từ trò chuyện hoặc trực tiếp), ghi kết quả xử lý, đề xuất bổ sung tri thức.' },
  { id: 'nap-du-lieu', path: '/nap-du-lieu', icon: 'upload', name: 'Nạp dữ liệu', group: 'Dữ liệu',
    desc: 'Tải tài liệu lên, theo dõi chuyển đổi, chấm điểm chất lượng và kiểm duyệt.' },
  { id: 'giam-dinh', path: '/giam-dinh', icon: 'database', name: 'Giám định dữ liệu', group: 'Dữ liệu', roles: ['reviewer', 'admin'],
    desc: 'Tác tử chạy định kỳ: tài liệu trùng, mâu thuẫn, hết hiệu lực, viện dẫn thiếu, lỗ hổng tri thức; xử lý từng phát hiện.' },
  { id: 'giam-sat', path: '/giam-sat', icon: 'activity', name: 'Giám sát hệ thống', group: 'Quản trị', roles: ['reviewer', 'admin'],
    desc: 'Người dùng, hiệu năng, tốc độ mô hình, tác vụ, tài nguyên máy chủ; nhật ký hệ thống trực tiếp; nhật ký kiểm toán.' },
  { id: 'quan-tri', path: '/quan-tri', icon: 'shield', name: 'Quản trị', group: 'Quản trị', roles: ['reviewer', 'admin'],
    desc: 'Phản hồi người dùng, chất lượng nạp dữ liệu, kỹ năng, bộ tiêu chí, công cụ của tác tử.' },
]

const DEFAULT_PINS = ['phan-tich', 'soan-thao', 'tong-hop', 'van-ban']
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

// Chế độ trả lời (chip trên ô nhập và lệnh “/”). Phân tích, soạn thảo, tổng hợp được nhận diện tự động
// (đính kèm tệp; “soạn tờ trình…”) nên không cần chọn chế độ.
export const MODES = [
  { id: 'tu_dong', label: 'Tự động', icon: 'sparkle', hint: 'Hệ thống tự chọn cách xử lý phù hợp, hỏi lại khi câu hỏi chưa rõ' },
  { id: 'chinh_xac', label: 'Nguyên văn', icon: 'scale', cmd: 'nguyenvan', hint: 'Trích nguyên văn điều, khoản từ kho văn bản chuẩn' },
  { id: 'tra_cuu', label: 'Tài liệu', icon: 'book', cmd: 'tailieu', hint: 'Trả lời từ tài liệu nội bộ, có dẫn nguồn' },
  { id: 'ho_tro', label: 'Kỹ thuật', icon: 'wrench', cmd: 'kythuat', hint: 'Các bước xử lý sự cố trích từ tài liệu kỹ thuật' },
  { id: 'tim_tai_lieu', label: 'Tìm tài liệu', icon: 'search', cmd: 'tim', hint: 'Chỉ liệt kê tài liệu liên quan' },
  { id: 'tac_tu', label: 'Nhiều bước', icon: 'steps', cmd: 'nhieubuoc', hint: 'Trợ lý tự gọi nhiều công cụ (thử nghiệm, chậm)' },
]

// Gợi ý ở màn hình bắt đầu (chỉnh theo dữ liệu thực tế của đơn vị)
export const SUGGESTIONS = [
  { icon: 'scale', title: 'Trích nguyên văn quy định', mode: 'chinh_xac',
    q: 'Theo Điều 5 Quyết định 15/QĐ-ĐVA, thiết bị hư hỏng phải thu hồi trong thời hạn bao lâu?' },
  { icon: 'wrench', title: 'Xử lý sự cố thiết bị lưu khóa', mode: 'tu_dong',
    q: 'USB Token cắm vào máy tính không nhận, đèn không sáng' },
  { icon: 'pen', title: 'Soạn văn bản tham mưu', mode: 'tu_dong',
    q: 'Soạn tờ trình về việc cấp bổ sung thiết bị lưu khóa bí mật cho cán bộ mới' },
  { icon: 'book', title: 'Hỏi đáp tài liệu nội bộ', mode: 'tra_cuu',
    q: 'Trong tuần 45, Phòng Kỹ thuật đã xử lý bao nhiêu sự cố kỹ thuật?' },
]
