---
name: nganh-co-yeu
loai: nganh
mac_dinh: true
description: Bối cảnh ngành Cơ yếu – chức năng, quan hệ công tác, phân định thẩm quyền, yêu cầu bắt buộc (Luật Cơ yếu 2011, Luật An ninh mạng 2025)
# Phần thân dưới đây được đưa vào chỉ thị của MỌI lượt phân tích, soạn thảo, tổng hợp → giữ NGẮN (≈ 500 từ):
# trên CPU, mỗi 100 từ thêm vào làm mỗi lượt gọi mô hình chậm thêm khoảng 1–2 giây.
# Nội dung chi tiết từng điều, khoản để cán bộ tra cứu: tham-chieu.md (không đưa vào chỉ thị).
#
# Văn bản đã hết hiệu lực: chương trình tự phát hiện khi văn bản được phân tích còn viện dẫn (không cần mô hình).
#   so_hieu: khớp theo số hiệu · ten_nhan_dien: khớp theo tên khi văn bản không ghi số hiệu (chỉ dùng tên phân biệt được)
#   chi_khi_kem: chỉ báo khi văn bản cùng viện dẫn số hiệu này
van_ban_het_hieu_luc:
  - {so_hieu: "86/2015/QH13", ten: "Luật An toàn thông tin mạng", ten_nhan_dien: "Luật An toàn thông tin mạng", het_hieu_luc_tu: "2026-07-01",
     thay_the_boi: "Luật An ninh mạng số 116/2025/QH15", can_cu: "Điều 44 Luật An ninh mạng 2025"}
  - {so_hieu: "35/2018/QH14", ten: "Luật sửa đổi, bổ sung một số điều của 37 luật có liên quan đến quy hoạch (phần sửa Luật An toàn thông tin mạng)",
     het_hieu_luc_tu: "2026-07-01", thay_the_boi: "Luật An ninh mạng số 116/2025/QH15", can_cu: "Điều 44 Luật An ninh mạng 2025",
     chi_khi_kem: "86/2015/QH13"}
  - {so_hieu: "24/2018/QH14", ten: "Luật An ninh mạng 2018", het_hieu_luc_tu: "2026-07-01",
     thay_the_boi: "Luật An ninh mạng số 116/2025/QH15", can_cu: "Điều 44 Luật An ninh mạng 2025"}
  - {so_hieu: "33/2001/PL-UBTVQH10", ten: "Pháp lệnh Cơ yếu", ten_nhan_dien: "Pháp lệnh Cơ yếu", het_hieu_luc_tu: "2012-02-01",
     thay_the_boi: "Luật Cơ yếu số 05/2011/QH13", can_cu: "Điều 37 Luật Cơ yếu"}
---

BỐI CẢNH NGÀNH CƠ YẾU (dùng để phân tích, soạn thảo; mọi nhận định vẫn phải có căn cứ trong nguồn được cung cấp)

1. Vị trí, nguyên tắc. Lực lượng cơ yếu là lực lượng chuyên trách bảo vệ bí mật nhà nước bằng mật mã, tham mưu cho Đảng, Nhà nước về công tác cơ yếu (Điều 20 Luật Cơ yếu). Nguyên tắc: bảo đảm tuyệt đối bí mật, an toàn, chính xác, kịp thời; quản lý chuyên ngành đặc thù, chế độ công tác nghiêm ngặt (Điều 5).

2. Ba mối quan hệ của tổ chức cơ yếu bộ, ngành (khoản 3 Điều 22): chịu sự LÃNH ĐẠO của cơ quan có thẩm quyền của Đảng; sự CHỈ ĐẠO của người đứng đầu cơ quan, tổ chức sử dụng cơ yếu; sự QUẢN LÝ VỀ CHUYÊN MÔN, NGHIỆP VỤ của tổ chức cơ yếu cấp trên. Khi phân tích, soạn thảo phải xác định đúng kênh: nội dung chuyên môn, nghiệp vụ, kỹ thuật mật mã đi theo kênh tổ chức cơ yếu cấp trên (đến Ban Cơ yếu Chính phủ); nội dung tổ chức, nhân lực, bảo đảm điều kiện đi theo kênh người đứng đầu cơ quan sử dụng cơ yếu. Hệ thống tổ chức cơ yếu Quân đội nhân dân là một hệ thống trong cơ yếu các bộ, ngành (khoản 2 Điều 22).

3. Phân định thẩm quyền:
- Ban Cơ yếu Chính phủ: cơ quan mật mã quốc gia, giúp Bộ trưởng Bộ Quốc phòng quản lý nhà nước về cơ yếu (Điều 6 Luật Cơ yếu), về mật mã dân sự và an ninh mạng thuộc phạm vi quản lý (khoản 4 Điều 39 Luật An ninh mạng); chủ trì bảo vệ an ninh mạng hệ thống thông tin cơ yếu thuộc Ban.
- Bộ Quốc phòng: chủ trì đối với hệ thống thông tin quân sự (thẩm định, kiểm tra, giám sát, ứng phó sự cố).
- Bộ Công an: đầu mối quản lý nhà nước về an ninh mạng, trừ phạm vi của Bộ Quốc phòng, Ban Cơ yếu Chính phủ.
- Mật mã cơ yếu bảo vệ thông tin bí mật nhà nước; mật mã dân sự bảo vệ thông tin KHÔNG thuộc bí mật nhà nước. Không dùng lẫn hai khái niệm.

4. Yêu cầu bắt buộc thường gặp: thông tin bí mật nhà nước truyền, lưu giữ trên phương tiện điện tử phải mã hóa bằng mật mã cơ yếu (Điều 9); chỉ dùng sản phẩm mật mã do Ban Cơ yếu Chính phủ cung cấp để bảo vệ bí mật nhà nước (khoản 2 Điều 11); sản phẩm mật mã phải kiểm định, đánh giá trước khi sử dụng (Điều 15); triển khai, giải thể mạng liên lạc cơ yếu cần thống nhất chuyên môn bằng văn bản của Ban Cơ yếu Chính phủ (Điều 17); sản phẩm mật mã, thông tin về tổ chức, mạng liên lạc cơ yếu, nơi làm việc, kho cất giữ là bí mật nhà nước (Điều 8); hệ thống thông tin cơ yếu, quân sự thuộc hệ thống thông tin quan trọng về an ninh quốc gia (Điều 9 Luật An ninh mạng).

5. Hiệu lực: Luật An ninh mạng số 116/2025/QH15 có hiệu lực từ 01/7/2026, thay thế Luật An toàn thông tin mạng 2015 và Luật An ninh mạng 2018; hệ thống thông tin đã xác định cấp độ có 12 tháng để đáp ứng yêu cầu mới (Điều 44, 45). Văn bản mới phải viện dẫn căn cứ còn hiệu lực.

6. Giới hạn: không suy đoán, không tự tổng hợp thông tin về tổ chức, mạng liên lạc cơ yếu, sản phẩm mật mã cụ thể; nội dung chữ ký số, chứng thực số chỉ viện dẫn văn bản chuyên ngành có trong nguồn, không tự nêu số hiệu văn bản không có trong nguồn.
