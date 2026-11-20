---
name: tong-hop-bao-cao-tuan
loai: tong_hop
description: Tổng hợp báo cáo tình hình tuần từ báo cáo của các đơn vị trực thuộc
tools: [search_docs, compute_table]
output_template: mau.md
params:
  - {ten: tu_ngay, nhan: "Từ ngày", kieu: date}
  - {ten: den_ngay, nhan: "Đến ngày", kieu: date}
---

# Kỹ năng: Tổng hợp báo cáo tuần

## Đầu vào
Báo cáo tuần của các đơn vị (loại văn bản "bao_cao").

## Các bước
1. Với từng báo cáo: trích các mục "Kết quả thực hiện", "Tồn tại, hạn chế", "Kiến nghị"; trích số liệu định lượng.
2. Số liệu tổng hợp do chương trình tính, KHÔNG tự tính.
3. Gộp theo đề mục của mẫu; mỗi ý ghi nguồn [S#].
4. Mục "Kiến nghị": giữ nguyên ý của đơn vị, không thêm kiến nghị mới.

## Tiêu chí kiểm tra
- Mỗi đề mục có ít nhất 01 nguồn.
- Mọi số liệu trùng khớp bảng số liệu do chương trình tính.
- Không bỏ sót đơn vị nào trong danh sách đầu vào.
