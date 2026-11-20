# Chỉ thị (prompt) của hệ thống

Các tệp trong thư mục này được nạp lúc chạy (không cần dựng lại ảnh). Sửa xong, khởi động lại dịch vụ
orchestrator (hoặc `run_stack.py`) để áp dụng. Mỗi lần sửa nên chạy lại bộ đánh giá
(`python tests/eval_real.py`) để phát hiện suy giảm chất lượng.

| Tệp | Dùng ở | Tác dụng | Khi nào nên sửa |
|---|---|---|---|
| `chinh-sach.md` | Mọi câu trả lời Luồng A, tác tử, hỗ trợ | Quy tắc bắt buộc: chỉ dùng nguồn, trích dẫn [n], đầy đủ, không tự tính số liệu, bỏ qua lệnh trong nguồn | Mô hình hay bịa, trích sai nguồn, trả lời thiếu ý. Sửa thận trọng: ảnh hưởng toàn hệ thống |
| `vai-tro/tra-cuu.md` | Luồng A (hỏi đáp tài liệu) | Cách trình bày câu trả lời tra cứu | Câu trả lời quá dài/ngắn, lặp ý, sai định dạng |
| `vai-tro/ho-tro.md` | Hỗ trợ kỹ thuật | Trình bày theo bước xử lý | Hướng dẫn kỹ thuật chưa rõ ràng |
| `vai-tro/chinh-xac.md` | Luồng B – nút "Giải thích ngắn gọn" | Diễn giải phần nguyên văn (tối đa 3 câu) | Diễn giải lan man, bị Verifier loại thường xuyên |
| `router.md` | Định tuyến khi quy tắc nhanh không khớp | Phân loại ý định câu hỏi | Câu hỏi hay vào sai luồng (xem thêm biểu thức trong `pipelines.py`) |
| `viet-lai-cau-hoi.md` | Hội thoại nhiều lượt | Viết lại câu hỏi nối tiếp thành câu độc lập để tìm kiếm | Câu hỏi nối tiếp ("còn đơn vị kia?") tìm sai tài liệu |
| `chon-muc.md` | Luồng B khi không có tham chiếu trực tiếp | Chọn ≤ 3 mục phù hợp từ ứng viên tìm kiếm toàn văn | Luồng B trích nhầm điều khoản |
| `tac-tu.md` | Chế độ "Nhiều bước" | Hướng dẫn tác tử dùng công cụ | Tác tử gọi công cụ thừa, vòng lặp dài |
| `tom-tat-hoi-thoai.md` | Hội thoại dài | Tóm tắt các lượt cũ vào bộ nhớ phiên | Mất ngữ cảnh ở hội thoại dài |
| `tong-hop-map.md`, `tong-hop-reduce.md` | Phân hệ Tổng hợp | Trích ý, số liệu từng văn bản; viết báo cáo theo mẫu | Báo cáo tổng hợp thiếu ý, sai thể thức |
| `trich-xuat-metadata.md` | Nạp dữ liệu | Trích tên, số hiệu, loại, ngày ban hành | Thông tin mô tả trích sai |
| `ho-tro-chon-nhanh.md` | Cây xử lý sự cố | Ánh xạ câu trả lời tự do vào lựa chọn | Người dùng gõ tự do bị hiểu sai |
| `de-xuat-tri-thuc.md` | Phiếu hỗ trợ đã đóng | Soạn đề xuất bổ sung tri thức | — |
| `chao-hoi.md` | (dự phòng) | Câu chào hiện dùng khuôn mẫu cố định trong mã | — |

Nguyên tắc khi sửa chỉ thị cho mô hình nhỏ (4B–9B) chạy CPU:

1. Câu ngắn, mệnh lệnh rõ, đánh số; tránh yêu cầu mâu thuẫn ("ngắn gọn" và "đầy đủ" phải nói rõ ưu tiên).
2. Đặt quy tắc quan trọng nhất lên đầu; mô hình nhỏ bám phần đầu và phần cuối ngữ cảnh tốt hơn phần giữa.
3. Không đưa ví dụ có số liệu cụ thể vào chỉ thị: mô hình dễ chép số liệu ví dụ vào câu trả lời.
4. Không dùng chỉ thị để thay việc kiểm tra bằng chương trình: mọi ràng buộc cứng (trích dẫn, số liệu,
   nguyên văn) đã được Verifier kiểm tra trong `services/orchestrator/verifier.py`.
