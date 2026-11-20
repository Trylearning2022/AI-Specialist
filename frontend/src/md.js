// Hiển thị Markdown an toàn: tắt HTML thô, lọc lại bằng DOMPurify; trích dẫn [n] thành liên kết.
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const md = new MarkdownIt({ html: false, linkify: false, breaks: false })

export function render(text, { cites = false } = {}) {
  let html = md.render(text || '')
  if (cites) html = html.replace(/\[(\d+(?:,\s*\d+)*)\]/g, (_, g) =>
    g.split(/,\s*/).map((n) => `<a class="cite" data-n="${n}">[${n}]</a>`).join(''))
  return DOMPurify.sanitize(html, { ADD_ATTR: ['data-n'] })
}

/** Hiển thị nguyên văn: bỏ ký hiệu tiêu đề Markdown (#), giữ nguyên câu chữ. Sao chép vẫn dùng văn bản gốc. */
export const vb = (t) => String(t || '').replace(/^#{1,6}\s+/gm, '').replace(/\n{3,}/g, '\n\n').trim()

export const DO_MAT = { 0: 'Thường', 1: 'Mật', 2: 'Tối mật', 3: 'Tuyệt mật' }
export const LOAI = {
  quyet_dinh: 'Quyết định', thong_tu: 'Thông tư', nghi_dinh: 'Nghị định', quy_dinh: 'Quy định',
  huong_dan: 'Hướng dẫn', ke_hoach: 'Kế hoạch', bao_cao: 'Báo cáo', cong_van: 'Công văn', to_trinh: 'Tờ trình',
  bien_ban: 'Biên bản', su_co: 'Sự cố', tai_lieu_ky_thuat: 'Tài liệu kỹ thuật', khac: 'Khác',
}
export const STATUS = {
  moi: 'Mới', dang_xu_ly: 'Đang xử lý', cho_duyet: 'Chờ duyệt', cho_duyet_cap_2: 'Chờ duyệt cấp 2',
  da_duyet: 'Đã duyệt', tu_choi: 'Từ chối', loi: 'Lỗi', cho: 'Chờ', dang_chay: 'Đang chạy', xong: 'Hoàn thành',
  da_xong: 'Đã xong', con_hieu_luc: 'Còn hiệu lực', het_hieu_luc: 'Hết hiệu lực', bi_thay_the: 'Bị thay thế',
}
export const fmtDate = (s) => (s ? new Date(s).toLocaleString('vi-VN') : '')
