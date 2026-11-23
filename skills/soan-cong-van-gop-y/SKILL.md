---
name: soan-cong-van-gop-y
loai: soan_thao
ten_loai: Công văn
description: Công văn tham gia ý kiến dự thảo văn bản; công văn trả lời đề nghị của cơ quan, đơn vị
the_thuc: the-thuc.md
# Hình thức công văn (chọn trong phân hệ Soạn văn bản tham mưu). Hình thức đầu tiên là mặc định.
#   tra_loi : soạn theo dàn ý dưới đây (căn cứ → nội dung → đề xuất, kiến nghị)
#   gop_y   : tham gia ý kiến dự thảo – tải dự thảo lên, rà soát theo khía cạnh (cấu hình gop_y bên dưới)
che_do:
  - {id: tra_loi, ten: "Trả lời, đề nghị", mo_ta: "Soạn theo chủ đề; hệ thống tìm căn cứ, lập dàn ý để duyệt"}
  - {id: gop_y, ten: "Tham gia ý kiến dự thảo", mo_ta: "Tải dự thảo (và công văn đề nghị); rà soát thuật ngữ, căn cứ pháp lý, nhiệm vụ của ngành, kỹ thuật bảo mật – ký số – xác thực; duyệt từng ý kiến"}
trich_yeu_mau: "V/v tham gia ý kiến {chu_de}"
# Kết cấu: 1. Căn cứ (văn bản đề nghị tham gia ý kiến) → 2. Nội dung tham gia ý kiến → 3. Đề xuất, kiến nghị (nếu có)
dan_y:
  - {tieu_de: "1. Căn cứ", huong_dan: "Nêu văn bản đơn vị cần tham gia ý kiến hoặc trả lời: cơ quan đề nghị, số hiệu, ngày, trích yếu; tên dự thảo. Câu dẫn: \"… [đơn vị] đã nghiên cứu và tham gia ý kiến như sau:\"."}
  - {tieu_de: "2. Nội dung tham gia ý kiến", huong_dan: "Ý kiến chung (1–2 câu), sau đó ý kiến cụ thể theo thứ tự: thuật ngữ chuyên môn; căn cứ pháp lý; nhiệm vụ của ngành Cơ yếu; nội dung kỹ thuật (bảo mật, ký số, xác thực). Mỗi ý: vị trí (điều, khoản) → nhận xét → đề nghị sửa thành → căn cứ."}
  - {tieu_de: "3. Đề xuất, kiến nghị", huong_dan: "Chỉ khi có nội dung vượt phạm vi chỉnh sửa câu chữ (ví dụ đề nghị lấy ý kiến Ban Cơ yếu Chính phủ, bổ sung quy định). Không có thì bỏ phần này.", can_cu: false}

# ---------------- Cấu hình tác vụ "Tham gia ý kiến dự thảo" (agent/gopy.py) ----------------
gop_y:
  cau_dan: "Thực hiện đề nghị của {co_quan_de_nghi} tại {van_ban_de_nghi} về việc lấy ý kiến đối với {ten_du_thao}, {don_vi} đã nghiên cứu và tham gia ý kiến như sau:"
  cau_dan_khong_cv: "{don_vi} đã nghiên cứu {ten_du_thao} và tham gia ý kiến như sau:"
  y_kien_chung_co_gop_y: "{don_vi} cơ bản nhất trí với nội dung dự thảo; đề nghị cơ quan chủ trì soạn thảo nghiên cứu, chỉnh sửa, bổ sung một số nội dung sau:"
  y_kien_chung_nhat_tri: "{don_vi} nhất trí với nội dung dự thảo."
  # Thứ tự khía cạnh = thứ tự trình bày trong mục 2. Có thể tắt khía cạnh bằng bat: false.
  khia_canh:
    - {id: thuat_ngu, ten: "Về thuật ngữ chuyên môn", bat: true}
    - {id: can_cu, ten: "Về căn cứ pháp lý", bat: true}
    - {id: nhiem_vu, ten: "Về nhiệm vụ của ngành Cơ yếu", bat: true,
       # câu có các cụm này được rà soát (chương trình tìm, mô hình nhận xét theo điều luật tra được)
       tu_khoa: [Ban Cơ yếu Chính phủ, tổ chức cơ yếu, lực lượng cơ yếu, Cục Cơ yếu, người làm công tác cơ yếu,
                 mạng liên lạc cơ yếu, sản phẩm mật mã, mật mã cơ yếu, hệ thống thông tin cơ yếu, mật mã dân sự,
                 Bộ Quốc phòng, Bộ Công an]}
    - {id: ky_thuat, ten: "Về nội dung kỹ thuật (bảo mật, ký số, xác thực)", bat: true,
       tu_khoa: [mã hóa, giải mã, khóa bí mật, khóa công khai, quản lý khóa, chữ ký số, ký số, chứng thư số,
                 chứng thực, xác thực, dấu thời gian, thiết bị lưu khóa, USB Token, HSM, OCSP, danh sách thu hồi,
                 bí mật nhà nước, an ninh mạng, cấp độ, mật khẩu, đăng nhập, nhật ký hệ thống, sao lưu]}
  # Thuật ngữ: cách dùng đúng theo luật ← cách viết cần tránh. Chương trình dò trong dự thảo, không cần mô hình.
  # [TINH CHỈNH] Cán bộ bổ sung theo văn bản của ngành; chỉ đưa cặp có căn cứ rõ.
  thuat_ngu:
    - {dung: "mật mã dân sự", tranh: ["mật mã dân dụng", "mật mã thương mại"], can_cu: "khoản 20 Điều 2 Luật An ninh mạng 2025"}
    - {dung: "sản phẩm mật mã", tranh: ["sản phẩm mã hóa", "thiết bị mã hóa cơ yếu"], can_cu: "khoản 6 Điều 3 Luật Cơ yếu"}
    - {dung: "mạng liên lạc cơ yếu", tranh: ["mạng thông tin cơ yếu", "mạng cơ yếu"], can_cu: "khoản 7 Điều 3 Luật Cơ yếu"}
    - {dung: "Ban Cơ yếu Chính phủ", tranh_regex: "Ban Cơ yếu(?!\\s+Chính\\s+phủ)", can_cu: "Điều 6 Luật Cơ yếu",
       ghi_chu: "ghi đầy đủ tên cơ quan"}
    - {dung: "an ninh mạng / an ninh thông tin mạng", tranh: ["an toàn thông tin mạng"],
       can_cu: "khoản 1, 2 Điều 2 Luật An ninh mạng 2025 (Luật An toàn thông tin mạng 2015 hết hiệu lực từ 01/7/2026)",
       ghi_chu: "xem xét theo ngữ cảnh; giữ nguyên nếu là tên riêng của đơn vị, tiêu chuẩn"}
    - {dung: "hệ thống thông tin cơ yếu", tranh: ["hệ thống cơ yếu"], can_cu: "khoản 23 Điều 2 Luật An ninh mạng 2025",
       ghi_chu: "khi chỉ hệ thống thông tin dùng mật mã cơ yếu bảo vệ bí mật nhà nước"}
  # Căn cứ bắt buộc: dự thảo có nội dung thuộc lĩnh vực mà không viện dẫn luật tương ứng → đề nghị bổ sung.
  can_cu_bat_buoc:
    - {khi: [mật mã, cơ yếu, bí mật nhà nước, mã hóa], so_hieu: "05/2011/QH13", ten: "Luật Cơ yếu"}
    - {khi: [an ninh mạng, hệ thống thông tin, không gian mạng, sự cố an ninh mạng], so_hieu: "116/2025/QH15", ten: "Luật An ninh mạng"}
    - {khi: [chữ ký số, chứng thư số, giao dịch điện tử, văn bản điện tử], so_hieu: "20/2023/QH15", ten: "Luật Giao dịch điện tử"}
---

Công văn tham gia ý kiến:
- Đúng kết cấu: 1. Căn cứ → 2. Nội dung tham gia ý kiến → 3. Đề xuất, kiến nghị (nếu có).
- Mỗi ý cụ thể: vị trí trong dự thảo (điều, khoản, điểm) → nhận xét ngắn → "Đề nghị sửa thành: …" hoặc "Đề nghị bổ sung: …" → căn cứ (điều, khoản).
- Chỉ góp ý trong phạm vi chức năng của đơn vị; không góp ý câu chữ thuần túy ngoài chuyên môn.
- Nội dung chuyên môn mật mã chưa được Ban Cơ yếu Chính phủ thống nhất: kiến nghị cơ quan chủ trì lấy ý kiến Ban Cơ yếu Chính phủ.
- Lời văn lịch sự, ngắn gọn: "đề nghị nghiên cứu, chỉnh sửa", "đề nghị bổ sung", "đề nghị làm rõ".
