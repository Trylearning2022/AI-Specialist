---
name: phan-tich-co-yeu
loai: phan_tich
mac_dinh: true
description: Phân tích văn bản theo chức năng, nhiệm vụ ngành Cơ yếu – mật mã bảo vệ BMNN, mật mã dân sự, chứng thực số, an ninh mạng (Luật Cơ yếu 2011, Luật An ninh mạng 2025)
# Mỗi tiêu chí là câu hỏi cán bộ tham mưu cơ yếu luôn đặt ra khi nhận một văn bản mới.
#   can_cu  : điều, khoản luật làm chuẩn đối chiếu – đưa vào chỉ thị và vào báo cáo để cán bộ kiểm tra lại
#   tu_khoa : cụm từ có dấu, ưu tiên cụm nhiều âm tiết (ít khớp nhầm); phải khớp ≥ 2 từ khóa hoặc 1 cụm nhiều âm tiết
#             thì đoạn văn mới được đưa cho mô hình – không khớp → "không đề cập", không tốn thời gian CPU.
# Thứ tự = thứ tự ưu tiên (chạy tối đa AGENT_MAX_CRITERIA tiêu chí). Nhóm 1–3 đặt trước vì là trọng tâm ngành.
tieu_chi:
  # ---- 1. Thẩm quyền, quan hệ công tác --------------------------------------------------------------
  - {id: cy01, nhom: "Thẩm quyền, quan hệ công tác", muc_do_mac_dinh: cao,
     can_cu: "Khoản 3 Điều 22, Điều 6 Luật Cơ yếu; Điều 39 Luật An ninh mạng",
     hoi: "Văn bản do cơ quan nào ban hành, theo kênh nào (lãnh đạo của Đảng, chỉ đạo của người đứng đầu cơ quan sử dụng cơ yếu, hay quản lý chuyên môn, nghiệp vụ của tổ chức cơ yếu cấp trên)? Nội dung có thuộc đúng thẩm quyền của cơ quan ban hành không; nội dung chuyên môn mật mã có được Ban Cơ yếu Chính phủ hoặc tổ chức cơ yếu cấp trên thống nhất không?",
     tu_khoa: [Ban Cơ yếu Chính phủ, tổ chức cơ yếu, cơ yếu cấp trên, người đứng đầu, thẩm quyền, chuyên môn nghiệp vụ, thống nhất, Bộ Quốc phòng, chỉ đạo]}
  - {id: cy02, nhom: "Thẩm quyền, quan hệ công tác", muc_do_mac_dinh: cao,
     can_cu: "Điều 21 Luật Cơ yếu; Điều 11, 15, 18, 40 Luật An ninh mạng",
     hoi: "Văn bản giao nhiệm vụ gì cho tổ chức cơ yếu, bộ phận an ninh mạng hoặc chứng thực số của đơn vị: ai chủ trì, ai phối hợp, thời hạn thực hiện và thời hạn báo cáo? Việc phân công chủ trì có phù hợp phân định giữa Ban Cơ yếu Chính phủ, Bộ Quốc phòng, Bộ Công an không?",
     tu_khoa: [chủ trì, phối hợp, giao nhiệm vụ, thời hạn, trước ngày, chậm nhất, báo cáo kết quả, tổ chức thực hiện]}

  # ---- 2. Mật mã bảo vệ bí mật nhà nước --------------------------------------------------------------
  - {id: cy03, nhom: "Mật mã bảo vệ BMNN", muc_do_mac_dinh: cao,
     can_cu: "Điều 9, khoản 2, 3 Điều 11 Luật Cơ yếu; Điều 15 Luật An ninh mạng",
     hoi: "Văn bản có nội dung soạn thảo, lưu giữ, truyền đưa thông tin bí mật nhà nước trên phương tiện điện tử, mạng máy tính không? Có yêu cầu mã hóa bằng mật mã cơ yếu không; có chỗ nào cho phép truyền, lưu thông tin bí mật mà chưa mã hóa hoặc dùng giải pháp không do Ban Cơ yếu Chính phủ cung cấp không?",
     tu_khoa: [bí mật nhà nước, mã hóa, mật mã cơ yếu, truyền đưa, lưu giữ, độ mật, thông tin mật, phương tiện điện tử]}
  - {id: cy04, nhom: "Mật mã bảo vệ BMNN", muc_do_mac_dinh: cao,
     can_cu: "Điều 13, 15, 16, 18 Luật Cơ yếu",
     hoi: "Văn bản quy định gì về sản phẩm mật mã: đề nghị trang bị, triển khai, cung cấp, kiểm định, đánh giá trước khi sử dụng, quản lý thống nhất? Văn bản yêu cầu triển khai có gửi đúng tổ chức cơ yếu có thẩm quyền không?",
     tu_khoa: [sản phẩm mật mã, kỹ thuật mật mã, triển khai, kiểm định, đánh giá, trang bị, cung cấp, quy chuẩn kỹ thuật]}
  - {id: cy05, nhom: "Mật mã bảo vệ BMNN", muc_do_mac_dinh: cao,
     can_cu: "Điều 17 Luật Cơ yếu",
     hoi: "Văn bản có liên quan đến triển khai mới, mở rộng, điều chỉnh hoặc giải thể mạng liên lạc cơ yếu không? Có văn bản thống nhất chuyên môn của Ban Cơ yếu Chính phủ chưa; trường hợp cấp thiết đã có thông báo bằng văn bản chưa?",
     tu_khoa: [mạng liên lạc cơ yếu, liên lạc cơ yếu, giải thể, triển khai mạng, thống nhất chuyên môn, cấp thiết]}
  - {id: cy06, nhom: "Mật mã bảo vệ BMNN", muc_do_mac_dinh: cao,
     can_cu: "Điều 19 Luật Cơ yếu",
     hoi: "Văn bản quy định gì về bảo quản, vận chuyển, thu hồi, tiêu hủy sản phẩm mật mã, tài liệu mật mã; xử lý khi mất, lộ, hư hỏng; tiêu hủy khẩn cấp và báo cáo sau tiêu hủy?",
     tu_khoa: [tiêu hủy, thu hồi, bảo quản, vận chuyển, tài liệu mật mã, khẩn cấp, mất, lộ, hư hỏng]}
  - {id: cy07, nhom: "Mật mã bảo vệ BMNN",
     can_cu: "Điều 8 Luật Cơ yếu",
     hoi: "Văn bản có chứa hoặc yêu cầu cung cấp thông tin về tổ chức cơ yếu, mạng liên lạc cơ yếu, nơi làm việc, kho cất giữ, cơ sở sản xuất sản phẩm mật mã không? Việc cung cấp, công bố, lưu trữ thông tin đó có được bảo vệ theo chế độ bí mật nhà nước không?",
     tu_khoa: [nơi làm việc, kho cất giữ, cơ sở sản xuất, tổ chức cơ yếu, mạng liên lạc, cung cấp thông tin, công khai]}

  # ---- 3. Mật mã dân sự, chữ ký số, chứng thực số -----------------------------------------------------
  - {id: cy08, nhom: "Mật mã dân sự, chứng thực số", muc_do_mac_dinh: cao,
     can_cu: "Khoản 20 Điều 2, khoản 6 Điều 27, khoản 2 Điều 26 Luật An ninh mạng",
     hoi: "Văn bản có sử dụng mật mã dân sự để bảo vệ thông tin không thuộc bí mật nhà nước không? Có yêu cầu về nguồn gốc, chứng nhận hợp quy, quản lý chất lượng sản phẩm, dịch vụ mật mã dân sự không; có chỗ nào lẫn giữa mật mã dân sự và mật mã cơ yếu không?",
     tu_khoa: [mật mã dân sự, sản phẩm mật mã dân sự, dịch vụ mật mã, hợp quy, chứng nhận, nguồn gốc]}
  - {id: cy09, nhom: "Mật mã dân sự, chứng thực số", muc_do_mac_dinh: cao,
     can_cu: "Quy định về chữ ký số, dịch vụ chứng thực chữ ký số chuyên dùng (cần nạp vào kho văn bản ngành để đối chiếu)",
     hoi: "Văn bản quy định gì về chứng thư số, chữ ký số chuyên dùng: đối tượng cấp, thẩm quyền đề nghị, cấp mới, gia hạn, thay đổi, tạm dừng, thu hồi; kiểm tra hiệu lực chữ ký (danh sách thu hồi, OCSP, dấu thời gian); giá trị pháp lý văn bản điện tử ký số?",
     tu_khoa: [chứng thư số, chữ ký số, ký số, chứng thực, thuê bao, thu hồi chứng thư, dấu thời gian, văn bản điện tử]}
  - {id: cy10, nhom: "Mật mã dân sự, chứng thực số",
     can_cu: "Điều 15, 16 Luật Cơ yếu; quy định về chữ ký số chuyên dùng",
     hoi: "Văn bản yêu cầu gì về thiết bị lưu khóa bí mật (USB Token, thẻ ký số), thiết bị bảo mật phần cứng (HSM) và quản lý khóa: sinh khóa, lưu giữ, sao lưu, khôi phục, hủy khóa, mã PIN, bàn giao, thu hồi thiết bị?",
     tu_khoa: [USB Token, thiết bị lưu khóa, khóa bí mật, quản lý khóa, sinh khóa, mã PIN, HSM, bàn giao]}

  # ---- 4. An ninh mạng hệ thống thông tin --------------------------------------------------------------
  - {id: cy11, nhom: "An ninh mạng hệ thống thông tin", muc_do_mac_dinh: cao,
     can_cu: "Điều 8, 9, 10 Luật An ninh mạng",
     hoi: "Văn bản có xác định, đề xuất cấp độ hệ thống thông tin không? Hệ thống liên quan có thuộc hệ thống thông tin quân sự, cơ yếu, hệ thống lưu trữ, xử lý bí mật nhà nước (quan trọng về an ninh quốc gia) không; đã có thẩm định, chứng nhận đủ điều kiện trước khi vận hành chưa?",
     tu_khoa: [cấp độ, hệ thống thông tin, an ninh quốc gia, thẩm định, chứng nhận, đủ điều kiện, đưa vào vận hành, hồ sơ đề xuất]}
  - {id: cy12, nhom: "An ninh mạng hệ thống thông tin", muc_do_mac_dinh: cao,
     can_cu: "Điều 11, khoản 1 Điều 40 Luật An ninh mạng",
     hoi: "Văn bản yêu cầu gì về kiểm tra, đánh giá, giám sát an ninh mạng: chủ quản tự kiểm tra hằng năm và gửi kết quả bằng văn bản trước tháng 10; kết nối giám sát; kiểm tra đột xuất; cơ quan nào có thẩm quyền kiểm tra đối với hệ thống quân sự, cơ yếu?",
     tu_khoa: [tự kiểm tra, kiểm tra, đánh giá, giám sát, hằng năm, đột xuất, chủ quản, kết nối giám sát]}
  - {id: cy13, nhom: "An ninh mạng hệ thống thông tin", muc_do_mac_dinh: cao,
     can_cu: "Điều 18, 20, khoản 1 Điều 40 Luật An ninh mạng; Điều 19 Luật Cơ yếu",
     hoi: "Văn bản quy định gì về phòng ngừa, ứng phó, khắc phục sự cố, tấn công mạng: phương án ứng phó, đầu mối tiếp nhận, thời hạn và nơi báo cáo sự cố (cơ quan chuyên trách của Bộ Quốc phòng đối với hệ thống quân sự), thẩm quyền xử lý tình huống nguy hiểm?",
     tu_khoa: [sự cố, tấn công mạng, ứng phó, khắc phục, ứng cứu, tình huống nguy hiểm, báo cáo sự cố, lực lượng chuyên trách]}
  - {id: cy14, nhom: "An ninh mạng hệ thống thông tin",
     can_cu: "Điều 23, khoản 2, 3 Điều 40 Luật An ninh mạng",
     hoi: "Văn bản có yêu cầu chỉ định người, bộ phận phụ trách an ninh mạng; phương án bảo đảm an ninh mạng được thẩm định đối với dự án dùng ngân sách; trách nhiệm người đứng đầu không? Thiết bị, phần mềm, kết nối mạng được phép sử dụng quy định thế nào?",
     tu_khoa: [phụ trách an ninh mạng, bộ phận chuyên trách, phương án bảo đảm, người đứng đầu, thiết bị đầu cuối, phần mềm, kết nối Internet, mạng nội bộ]}

  # ---- 5. Nhân sự cơ yếu -------------------------------------------------------------------------------
  - {id: cy15, nhom: "Nhân sự cơ yếu",
     can_cu: "Điều 23–29 Luật Cơ yếu",
     hoi: "Văn bản quy định gì về tuyển chọn, tiêu chuẩn, đào tạo, bồi dưỡng, điều động, thôi việc người làm công tác cơ yếu; nghĩa vụ giữ bí mật kể cả khi thôi việc; hạn chế tham gia hoạt động mật mã ngoài ngành?",
     tu_khoa: [người làm công tác cơ yếu, tiêu chuẩn, tuyển chọn, đào tạo, bồi dưỡng, huấn luyện, điều động, thôi việc]}
  - {id: cy16, nhom: "Nhân sự cơ yếu",
     can_cu: "Điều 30–36 Luật Cơ yếu",
     hoi: "Văn bản có nội dung về chế độ, chính sách đối với người làm công tác cơ yếu (phụ cấp, cấp hàm, bảo hiểm, chế độ khi nghỉ hưu, thôi việc) không; có phù hợp quy định hiện hành không?",
     tu_khoa: [chế độ, chính sách, phụ cấp, cấp hàm, tiền lương, bảo hiểm, nghỉ hưu]}

  # ---- 6. Căn cứ, hiệu lực -----------------------------------------------------------------------------
  - {id: cy17, nhom: "Căn cứ, hiệu lực", muc_do_mac_dinh: cao,
     can_cu: "Điều 44, 45 Luật An ninh mạng 2025; Điều 37 Luật Cơ yếu",
     hoi: "Văn bản viện dẫn căn cứ pháp lý nào; có căn cứ đã hết hiệu lực không (Luật An toàn thông tin mạng 2015, Luật An ninh mạng 2018 hết hiệu lực từ 01/7/2026)? Văn bản thay thế, sửa đổi, bãi bỏ văn bản nào, hiệu lực từ ngày nào, có điều khoản chuyển tiếp không?",
     tu_khoa: [căn cứ, hiệu lực, thay thế, sửa đổi, bãi bỏ, chuyển tiếp, kể từ ngày, An toàn thông tin mạng]}

  # ---- 7. Bảo đảm ------------------------------------------------------------------------------------
  - {id: cy18, nhom: "Bảo đảm",
     can_cu: "Điều 10, Điều 16 Luật Cơ yếu",
     hoi: "Văn bản có nội dung về kinh phí, đầu tư, mua sắm, trang bị, hạ tầng, nhân lực bảo đảm cho hoạt động cơ yếu, an ninh mạng, chứng thực số không; nguồn kinh phí; đơn vị sử dụng có trách nhiệm bảo đảm điều kiện gì?",
     tu_khoa: [kinh phí, ngân sách, dự toán, đầu tư, mua sắm, trang bị, cơ sở vật chất, hạ tầng]}

  # ---- 8. Hành vi cấm, rủi ro ---------------------------------------------------------------------------
  - {id: cy19, nhom: "Hành vi bị nghiêm cấm, trách nhiệm",
     can_cu: "Điều 11 Luật Cơ yếu; Điều 7 Luật An ninh mạng",
     hoi: "Nội dung nào của văn bản liên quan đến hành vi bị nghiêm cấm (làm lộ bí mật nhà nước, sử dụng sản phẩm mật mã không do Ban Cơ yếu Chính phủ cung cấp, truyền bí mật nhà nước không mã hóa, sử dụng mật mã dân sự không rõ nguồn gốc)? Trách nhiệm và hình thức xử lý vi phạm quy định thế nào?",
     tu_khoa: [nghiêm cấm, vi phạm, xử lý vi phạm, kỷ luật, làm lộ, không được, trách nhiệm]}
  - {id: cy20, nhom: "Rủi ro, điểm cần lưu ý", muc_do_mac_dinh: cao,
     can_cu: "Điều 5 Luật Cơ yếu (bảo đảm tuyệt đối bí mật, an toàn, chính xác, kịp thời)",
     hoi: "Nội dung nào có thể gây rủi ro hoặc khó khăn khi đơn vị triển khai: thời hạn gấp, yêu cầu vượt khả năng bảo đảm, chưa rõ chủ trì, chưa có văn bản hướng dẫn, có thể ảnh hưởng an toàn bí mật nhà nước hoặc liên lạc cơ yếu?",
     tu_khoa: [khó khăn, vướng mắc, chưa có hướng dẫn, khẩn, gấp, rủi ro, nguy cơ, chưa bảo đảm]}
---

Hướng dẫn khi phân tích theo bộ tiêu chí này:
- Đứng ở vị trí cán bộ tham mưu của tổ chức cơ yếu: nêu rõ đơn vị PHẢI LÀM, ĐƯỢC LÀM, KHÔNG ĐƯỢC LÀM, theo kênh nào (chỉ đạo của người đứng đầu hay chuyên môn của cơ yếu cấp trên).
- Đối chiếu nội dung văn bản với căn cứ của tiêu chí; chỉ kết luận "trái", "thiếu" khi đoạn luật được cung cấp thể hiện rõ; nếu không có đoạn luật, ghi "cần đối chiếu".
- Thời hạn, số lượng, đối tượng giữ nguyên như văn bản; không suy đoán thông tin về tổ chức, mạng liên lạc, sản phẩm mật mã.
- Đề xuất viết ngắn: "Đề nghị … chủ trì …", "Cần báo cáo tổ chức cơ yếu cấp trên thống nhất chuyên môn …", "Cần rà soát căn cứ …".
