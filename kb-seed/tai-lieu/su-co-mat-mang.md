---
ten: "Sự cố mất kết nối mạng nội bộ trên máy trạm"
loai: su_co
co_quan_ban_hanh: "Phòng Kỹ thuật"
---

# Sự cố mất kết nối mạng nội bộ trên máy trạm

## Triệu chứng

Máy trạm không truy cập được hệ thống nghiệp vụ; biểu tượng mạng báo "No network access".

## Nguyên nhân thường gặp

- Cáp mạng lỏng hoặc hỏng.
- Máy trạm nhận sai địa chỉ IP do cấu hình tĩnh cũ.

## Cách xử lý

1. Kiểm tra đèn tín hiệu tại cổng mạng của máy tính; cắm lại cáp mạng.
2. Mở Command Prompt, chạy lệnh `ipconfig /release` rồi `ipconfig /renew`.
3. Nếu vẫn không kết nối được, báo Phòng Kỹ thuật qua phiếu yêu cầu hỗ trợ.
