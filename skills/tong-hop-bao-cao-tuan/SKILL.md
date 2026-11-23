---
name: tong-hop-bao-cao-tuan
loai: tong_hop
description: Tổng hợp báo cáo tuần công tác cơ yếu, an ninh mạng, chứng thực số từ báo cáo của các đơn vị trực thuộc
tools: [search_docs, compute_table]
output_template: mau.md
params:
  - {ten: tu_ngay, nhan: "Từ ngày", kieu: date}
  - {ten: den_ngay, nhan: "Đến ngày", kieu: date}
---

# Kỹ năng: Tổng hợp báo cáo tuần công tác cơ yếu

## Đầu vào
Báo cáo tuần của các đơn vị (loại văn bản "bao_cao").

## Các bước
1. Với từng báo cáo: trích kết quả bảo đảm liên lạc, mã hóa; quản lý sản phẩm mật mã; chứng thực số; an ninh mạng; sự cố; tồn tại; kiến nghị; số liệu định lượng.
2. Số liệu tổng hợp do chương trình tính, KHÔNG tự tính.
3. Gộp theo đề mục của mẫu; mỗi ý ghi nguồn [S#].
4. Sự cố trong tuần liệt kê đủ từng sự cố, kèm biện pháp đã xử lý và tình trạng báo cáo cấp trên (nếu nguồn nêu) (Điều 19 Luật Cơ yếu; Điều 40 Luật An ninh mạng).
5. Kiến nghị giữ nguyên ý của đơn vị; tách kiến nghị chuyên môn, nghiệp vụ (gửi tổ chức cơ yếu cấp trên) và kiến nghị về tổ chức, bảo đảm (gửi người đứng đầu cơ quan) theo khoản 3 Điều 22 Luật Cơ yếu.
6. Không đưa thông tin về tổ chức, mạng liên lạc cơ yếu, sản phẩm mật mã ngoài nội dung báo cáo nguồn (Điều 8 Luật Cơ yếu).

## Tiêu chí kiểm tra
- Mỗi đề mục có ít nhất 01 nguồn hoặc ghi rõ "Các đơn vị không báo cáo".
- Mọi số liệu trùng khớp bảng số liệu do chương trình tính.
- Không bỏ sót đơn vị, sự cố nào trong danh sách đầu vào.
