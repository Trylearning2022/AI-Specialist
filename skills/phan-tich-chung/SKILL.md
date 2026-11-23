---
name: phan-tich-chung
loai: phan_tich
description: Bộ tiêu chí rút gọn – văn bản ngoài chuyên ngành (hành chính, kế hoạch chung) gửi đến tổ chức cơ yếu; xác định tác động tới công tác cơ yếu, bảo vệ BMNN
# Dùng khi văn bản không thuộc chuyên môn mật mã (bộ đầy đủ: phan-tich-co-yeu). Ít tiêu chí → nhanh trên CPU.
tieu_chi:
  - {id: c01, nhom: "Thẩm quyền, quan hệ công tác", muc_do_mac_dinh: cao,
     can_cu: "Khoản 3 Điều 22 Luật Cơ yếu",
     hoi: "Văn bản do cơ quan nào ban hành, theo kênh nào đối với tổ chức cơ yếu (chỉ đạo của người đứng đầu cơ quan sử dụng cơ yếu, hay chuyên môn của tổ chức cơ yếu cấp trên); mục đích, phạm vi, đối tượng áp dụng?",
     tu_khoa: [thẩm quyền, người đứng đầu, tổ chức cơ yếu, phạm vi điều chỉnh, đối tượng áp dụng, mục đích]}
  - {id: c02, nhom: "Nhiệm vụ, thời hạn", muc_do_mac_dinh: cao,
     can_cu: "Điều 21 Luật Cơ yếu (nhiệm vụ của tổ chức cơ yếu)",
     hoi: "Văn bản giao nhiệm vụ gì cho tổ chức cơ yếu hoặc bộ phận an ninh mạng, chứng thực số của đơn vị; ai chủ trì, phối hợp; thời hạn thực hiện, báo cáo? Nhiệm vụ có thuộc chức năng của tổ chức cơ yếu không?",
     tu_khoa: [chủ trì, phối hợp, giao nhiệm vụ, thời hạn, trước ngày, chậm nhất, báo cáo kết quả]}
  - {id: c03, nhom: "Bảo vệ bí mật nhà nước", muc_do_mac_dinh: cao,
     can_cu: "Điều 8, 9 Luật Cơ yếu; Điều 15 Luật An ninh mạng",
     hoi: "Triển khai văn bản có phát sinh soạn thảo, lưu giữ, truyền đưa thông tin bí mật nhà nước trên phương tiện điện tử, hoặc cung cấp thông tin về tổ chức, mạng liên lạc cơ yếu không? Có cần mã hóa bằng mật mã cơ yếu không?",
     tu_khoa: [bí mật nhà nước, độ mật, mã hóa, truyền đưa, lưu giữ, thông tin mật, cung cấp thông tin]}
  - {id: c04, nhom: "An ninh mạng hệ thống thông tin",
     can_cu: "Điều 8, 9, 11, 40 Luật An ninh mạng",
     hoi: "Văn bản có triển khai, kết nối, nâng cấp hệ thống thông tin, phần mềm, dữ liệu không; có yêu cầu xác định cấp độ, phương án bảo đảm an ninh mạng, người phụ trách an ninh mạng không?",
     tu_khoa: [hệ thống thông tin, phần mềm, cơ sở dữ liệu, chuyển đổi số, kết nối, cấp độ, an ninh mạng]}
  - {id: c05, nhom: "Căn cứ, hiệu lực",
     can_cu: "Điều 44, 45 Luật An ninh mạng 2025",
     hoi: "Văn bản viện dẫn căn cứ nào, có căn cứ đã hết hiệu lực không; thay thế, sửa đổi văn bản nào; hiệu lực từ khi nào?",
     tu_khoa: [căn cứ, thay thế, sửa đổi, bãi bỏ, hiệu lực, kể từ ngày]}
  - {id: c06, nhom: "Bảo đảm",
     can_cu: "Điều 16 Luật Cơ yếu",
     hoi: "Văn bản có nội dung về kinh phí, nhân lực, trang thiết bị mà tổ chức cơ yếu cần bảo đảm hoặc đề nghị không?",
     tu_khoa: [kinh phí, ngân sách, nhân lực, trang thiết bị, mua sắm, bảo đảm]}
  - {id: c07, nhom: "Rủi ro", muc_do_mac_dinh: cao,
     can_cu: "Điều 5 Luật Cơ yếu",
     hoi: "Nội dung nào có thể gây khó khăn hoặc rủi ro cho công tác cơ yếu khi triển khai (thời hạn gấp, chưa rõ chủ trì, nguy cơ lộ bí mật nhà nước)?",
     tu_khoa: [khó khăn, vướng mắc, chưa có hướng dẫn, khẩn, gấp, rủi ro, nguy cơ]}
---

Phân tích ngắn gọn, khách quan; chỉ nêu nội dung có trong văn bản; nêu rõ tác động tới công tác cơ yếu và kênh xử lý (báo cáo người đứng đầu hay xin ý kiến tổ chức cơ yếu cấp trên); đề xuất ghi rõ là ý kiến tham khảo.
