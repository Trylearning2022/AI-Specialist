# Tác vụ AI, hỏi lại, bảo vệ ATTT, giám định dữ liệu và giám sát (bản 1.3.0)

Tài liệu này hướng dẫn sử dụng, tinh chỉnh các chức năng bổ sung ở bản 1.3.0. Tham số cấu hình nằm trong
`backend/aicommon/config.py` (biến môi trường cùng tên viết HOA); các chỗ có thể điều chỉnh được đánh dấu
`[TINH CHỈNH]` trong mã nguồn (`grep -rn "TINH CHỈNH" backend/`).

## 1. Tổng quan

```
                         ┌──────────────────────── orchestrator (hỏi đáp trực tiếp) ────────────────────────┐
 câu hỏi ─► bảo vệ ATTT ─► định tuyến ─► hỏi lại? ─► luồng xử lý (kế hoạch từng bước, SSE plan/step) ─► kiểm chứng
            (guard.py)                 (clarify.py)        │
                                                           │ phân tích / soạn thảo / tổng hợp
                                                           ▼
                                agent-svc ──► hàng đợi "agent" ──► agent-worker (01 tiến trình trên CPU)
                                  │   tác vụ dài theo kế hoạch cố định, tiến trình lưu CSDL, giao diện thăm dò 1,5 giây
                                  │   nhường máy chủ mô hình cho hỏi đáp trực tiếp (priority.py)
                                  └── lịch chạy nền ──► tác tử giám định dữ liệu (quality.py)
 mọi dịch vụ ──► telemetry (Redis Stream) ──► audit-svc /monitor/* ──► màn hình Giám sát hệ thống
```

| Chức năng | Ở đâu trên giao diện | Mã nguồn chính |
|---|---|---|
| Tiến trình từng bước của câu trả lời | Mọi câu trả lời trong trò chuyện | `orchestrator/pipelines.py` (lớp `Steps`), `StepTimeline.vue` |
| Hỏi lại khi câu hỏi chưa rõ | Thẻ lựa chọn trong trò chuyện | `orchestrator/clarify.py`, `ClarifyCard.vue` |
| Hỗ trợ kỹ thuật gộp vào hỏi đáp | Trò chuyện (chế độ Tự động/Kỹ thuật) | `pipelines.ho_tro`, `prompts/vai-tro/ho-tro.md` |
| Bảo vệ an toàn thông tin | Tự động, trước mọi xử lý | `aicommon/guard.py` |
| Phân tích văn bản mới | Đính kèm tệp trong trò chuyện; tiện ích *Phân tích văn bản* | `agent/analyze.py`, `skills/phan-tich-*` |
| Soạn văn bản tham mưu | "Soạn tờ trình…" trong trò chuyện; tiện ích *Soạn văn bản tham mưu* | `agent/draft.py`, `skills/soan-*` |
| Tổng hợp báo cáo chung | Đính kèm nhiều báo cáo + "tổng hợp"; tiện ích *Tổng hợp báo cáo* | `agent/synth.py`, `summary/core.py` |
| Giám định dữ liệu | Tiện ích *Giám định dữ liệu* (kiểm duyệt viên, quản trị) | `agent/quality.py` |
| Giám sát, nhật ký | Tiện ích *Giám sát hệ thống* | `aicommon/telemetry.py`, `audit/monitor.py` |

## 2. Câu trả lời theo từng bước

Mỗi luồng phát sự kiện `plan` (danh sách bước) và `step` (cập nhật từng bước: đang chạy, xong, bỏ qua, lỗi,
thời gian, chi tiết). Giao diện vẽ thành dòng thời gian khi đang xử lý, thu gọn thành "Đã xử lý qua N bước"
khi xong; vết các bước được lưu cùng câu trả lời (`data.trace`) để xem lại.

| Luồng | Các bước |
|---|---|
| Tra cứu tài liệu | Phân tích câu hỏi → Tìm kiếm → Chọn nguồn → Soạn câu trả lời → Kiểm chứng |
| Hỗ trợ kỹ thuật | Xác định thiết bị, triệu chứng → Tìm hướng dẫn trong tài liệu kỹ thuật → Chọn hướng dẫn → Lập các bước xử lý → Kiểm chứng |
| Nguyên văn | Phân tích câu hỏi → Định vị điều, khoản → Trích nguyên văn → Kiểm tra hiệu lực |
| Phân tích, soạn thảo, tổng hợp | Tạo tác vụ → thẻ tác vụ hiển thị tiến trình trực tiếp trong trò chuyện |

## 3. Hỏi lại làm rõ

Thuật toán quy tắc (không gọi mô hình, vài mili giây), mỗi câu hỏi chỉ hỏi lại tối đa 01 lần:

| Quy tắc | Điều kiện | Câu hỏi lại |
|---|---|---|
| Quá ngắn | Ít hơn `CLARIFY_MIN_TOKENS` âm tiết nội dung, không nêu thiết bị | Nhóm nội dung cần hỗ trợ |
| Thiếu thiết bị | Sự cố kỹ thuật chưa nêu thiết bị/hệ thống | USB Token, chứng thư số, phần mềm ký số, máy tính, mạng, tài khoản |
| Thiếu triệu chứng | Nêu thiết bị nhưng mô tả mơ hồ ("bị lỗi", "không dùng được") | Triệu chứng điển hình của thiết bị đó |
| Kết quả phân tán | Điểm rerank cao nhất < `CLARIFY_MAX_SCORE` và ≥ 3 tài liệu có điểm chênh ≤ `CLARIFY_SPREAD` | Chọn tài liệu muốn hỏi |

Danh mục thiết bị và triệu chứng: biến `OBJECTS` trong `clarify.py` – bổ sung theo thực tế đơn vị.
Tắt: `CLARIFY_ENABLED=false`. Hỏi lại xảy ra quá nhiều với câu hỏi đã rõ: giảm `CLARIFY_MAX_SCORE` (ví dụ −2).

## 4. Hỗ trợ kỹ thuật (thay cho cây xử lý sự cố)

Không còn phải soạn tay cây xử lý cho từng lĩnh vực. Các bước xử lý được trích từ tài liệu đã nạp loại
`su_co`, `huong_dan`, `tai_lieu_ky_thuat`; không có tài liệu phù hợp thì đề nghị tạo phiếu yêu cầu ngay từ
câu trả lời. Muốn trợ lý hướng dẫn tốt một sự cố: nạp một tài liệu Markdown/DOCX ngắn có các mục *Triệu chứng*,
*Nguyên nhân thường gặp*, *Các bước xử lý* (đánh số), *Lưu ý an toàn* – mẫu: `kb-seed/tai-lieu/huong-dan-xu-ly-usb-token.md`.
Phiếu đã xử lý xong có thể "Đề xuất bổ sung tri thức" để thành tài liệu hướng dẫn mới (qua kiểm duyệt).
API cây xử lý cũ (`/support/trees`, `/support/sessions`) vẫn giữ để tương thích, giao diện không dùng nữa.

## 5. Bảo vệ an toàn thông tin

| Loại | Nhận diện | Xử lý |
|---|---|---|
| Bí mật xác thực | Khóa bí mật PEM, cụm khôi phục, "mã PIN/mật khẩu là/: <giá trị>" | Từ chối; **không lưu** nội dung (CSDL chỉ ghi "[Nội dung đã được ẩn]"); nhắc đổi PIN, báo cáo thu hồi chứng thư |
| Vượt bảo mật | "bẻ khóa/vượt qua/vô hiệu hóa … xác thực/mã PIN/chứng thư…", "trích xuất khóa bí mật từ token/HSM" | Từ chối, chỉ dẫn quy trình chính thức. Câu hỏi về quy định, biện pháp phòng ngừa vẫn được trả lời |
| Dấu độ mật | Dòng riêng "MẬT/TỐI MẬT/TUYỆT MẬT" hoặc "Độ mật: …" vượt `SYSTEM_MAX_CLEARANCE` | Từ chối, không lưu |

Mỗi lần chặn ghi kiểm toán `guard.block` (chỉ ghi loại). Chỉ thị nghiệp vụ ngành ở `prompts/chinh-sach.md` (quy tắc 9–13).

## 6. Tác vụ dài (agent)

Kế hoạch các bước do **chương trình** định nghĩa (không để mô hình tự lập kế hoạch), mỗi lượt gọi mô hình
chỉ làm một việc nhỏ với ngữ cảnh ngắn – phù hợp mô hình 9B trên CPU. Trạng thái lưu CSDL sau mỗi bước:
khởi động lại tiến trình nền, tác vụ chạy tiếp từ bước chưa xong; hủy được bất cứ lúc nào; tác vụ lỗi bấm
"Chạy lại" sẽ giữ các bước đã xong.

**Ưu tiên hỏi đáp trực tiếp:** trước mỗi lượt gọi mô hình, tác vụ nền chờ tới khi không còn ai đang hỏi đáp
(tối đa `AGENT_YIELD_MAX_S` giây); thẻ tác vụ hiển thị "Đang nhường máy chủ mô hình cho hỏi đáp trực tiếp".

### 6.1. Phân tích văn bản mới

| Bước | Thực hiện | Ghi chú |
|---|---|---|
| Tiếp nhận | Chương trình | Dùng lại bộ chuyển đổi của phân hệ nạp (OCR nếu có docling); kiểm tra dấu độ mật |
| Cấu trúc, trích xuất | Chương trình | Chia phần theo chương/mục/điều; trích thời hạn, nhiệm vụ ("… chủ trì/phối hợp/báo cáo …"), văn bản viện dẫn |
| Tóm tắt | Mô hình | Từng phần (≤ `AGENT_PART_TOKENS`), rồi toàn văn; ý có số liệu lạ bị loại |
| Đối chiếu cơ sở tri thức | Chương trình | Văn bản viện dẫn có trong kho chuẩn không, còn hiệu lực không; tài liệu nội bộ liên quan |
| Áp bộ tiêu chí | Mô hình | Tiêu chí không có từ khóa trong văn bản → "không đề cập", **không gọi mô hình**; trích dẫn của mô hình phải có thật trong văn bản |
| Lập báo cáo | Chương trình | Khung cố định: thông tin văn bản, tóm tắt, vấn đề theo mức độ, nhiệm vụ – thời hạn, đối chiếu, điểm lưu ý, đề xuất (tham khảo) |
| Kiểm chứng | Chương trình | Số liệu trong báo cáo phải có trong văn bản hoặc cơ sở tri thức |

**Bộ tiêu chí của ngành** là kỹ năng Markdown, cán bộ chuyên môn tự soạn, sửa không cần lập trình:
`skills/phan-tich-co-yeu/SKILL.md` (từ 1.3.2: 20 tiêu chí, 8 nhóm xây dựng từ Luật Cơ yếu 2011 và Luật An ninh mạng
2025 – xem `docs/bo-ky-nang-nganh-co-yeu.md`). Mỗi tiêu chí:

```yaml
- {id: cy05, nhom: "Mật mã bảo vệ BMNN", muc_do_mac_dinh: cao,
   can_cu: "Điều 17 Luật Cơ yếu",
   hoi: "Văn bản có liên quan đến triển khai, giải thể mạng liên lạc cơ yếu không? Đã có văn bản thống nhất chuyên môn …?",
   tu_khoa: [mạng liên lạc cơ yếu, liên lạc cơ yếu, giải thể, triển khai mạng, thống nhất chuyên môn]}
```

Câu hỏi càng cụ thể, kết quả càng tốt. `tu_khoa` dùng để lọc trước: văn bản phải chứa ≥ 2 từ khóa, hoặc
một cụm từ khóa nhiều âm tiết (so khớp có dấu, trọn từ). Bổ sung bộ tiêu chí lĩnh vực khác: sao chép thư mục,
đổi `name`, `description`, danh sách `tieu_chi`. Câu hỏi riêng của người dùng luôn là tiêu chí đầu tiên.

### 6.2. Soạn văn bản tham mưu

Thu thập căn cứ (văn bản chuẩn – nguyên văn; tài liệu nội bộ; tài liệu chỉ định) → lập dàn ý → **dừng chờ
người dùng duyệt dàn ý** (sửa tên phần, ý chính, gắn/bỏ căn cứ) → viết từng phần CHỈ từ căn cứ đã gắn →
kiểm chứng (câu không có căn cứ được đánh dấu ở bản kèm căn cứ) → ghép thể thức. Kết quả có **bản sạch** (không
chỉ số căn cứ, để trình ký) và **bản kèm căn cứ** [S#] cùng phụ lục căn cứ (để rà soát); cả hai xuất được DOCX.

Mẫu văn bản: `skills/soan-to-trinh`, `soan-bao-cao-de-xuat`, `soan-ke-hoach`, `soan-cong-van-gop-y` – mỗi mẫu có
`dan_y` (các phần, hướng dẫn viết, có cần căn cứ không) và `the-thuc.md` (khối thể thức với các ô `{don_vi}`,
`{ky_hieu}`, `{trich_yeu}`, `{noi_nhan}`…). Thêm loại văn bản mới: sao chép một thư mục mẫu và sửa.
Định dạng DOCX theo thể thức đơn vị: đặt tệp `skills/reference.docx` (kiểu chữ, lề, cỡ chữ) – pandoc dùng làm mẫu.

### 6.3. Tổng hợp báo cáo chung

Đầu vào là báo cáo trong kho và/hoặc tệp tải lên (không cần nạp vào kho). Thuật toán dùng chung với summary-svc
(`services/summary/core.py`): tóm tắt, trích số liệu từng báo cáo → loại số liệu không có trong văn bản → chương
trình cộng tổng theo chỉ tiêu → viết báo cáo theo mẫu (mỗi ý ghi [S#]) → kiểm chứng, phụ lục bảng số liệu và nguồn.
Mẫu mặc định: `skills/tong-hop-bao-cao-chung`.

## 7. Tác tử giám định dữ liệu

Chạy theo lịch (`QA_INTERVAL_MIN`, mặc định 120 phút) **khi hệ thống rảnh** (không ai đang hỏi đáp, không có tác
vụ dài đang chạy), hoặc khi kiểm duyệt viên bấm "Giám định ngay". Hai tầng:

| Tầng | Khi nào chạy | Kiểm tra |
|---|---|---|
| 1 – Thuật toán | Luôn chạy, không cần mô hình | Gần trùng (MinHash LSH), hiệu lực chưa cập nhật, nghi vấn mâu thuẫn số liệu, văn bản viện dẫn thiếu, thiếu thông tin mô tả, tài liệu cũ, nội dung kém (OCR lỗi), lỗ hổng tri thức (câu hỏi không có căn cứ, bị đánh giá sai – gom nhóm), tài liệu hay bị trả lời bám nguồn kém |
| 2 – Kiểm tra chéo bằng mô hình | `QA_LLM_MODE`: `on`; `auto` = khi `HARDWARE_PROFILE=gpu` hoặc trong giờ rảnh `QA_LLM_HOURS` và không ai đang hỏi; `off` | Xác nhận/bác bỏ nghi vấn mâu thuẫn (tối đa `QA_LLM_MAX_CHECKS` mỗi lượt); có người hỏi đáp thì dừng, lượt sau làm tiếp |

Nghi vấn mâu thuẫn: chương trình trích cặp (cụm nội dung, giá trị, đơn vị) như "thu hồi trong thời hạn 07 ngày
làm việc" và so giữa văn bản chuẩn với các tài liệu khác (mẫu `_FACT` trong `quality.py`).

Mỗi phát hiện có mã vân tay ổn định: không tạo trùng giữa các lượt; phát hiện chưa xử lý mà lượt sau không còn
thì **tự đóng**; đã "Bỏ qua" không mở lại; đã "Xử lý" mà vẫn còn thì mở lại. Thay đổi dữ liệu thật chỉ khi có người
bấm: "Áp dụng đề xuất" sửa thông tin mô tả của tài liệu tham khảo (Luồng A); văn bản chuẩn (Luồng B) phải sửa qua
quy trình nạp – duyệt hai cấp.

## 8. Giám sát hệ thống

Mọi dịch vụ ghi bản ghi nhỏ vào Redis Stream (`tel:http`, `tel:llm`, `tel:chat`, `tel:task`, `tel:logs`, giới hạn
`TELEMETRY_KEEP`/`LOGS_KEEP` bản ghi, tự xoay vòng); audit-svc tổng hợp theo khung thời gian. Không cần thêm
Prometheus/ELK (Prometheus vẫn dùng được qua `/metrics` nếu bật profile `giam-sat`).

| Thẻ | Nội dung |
|---|---|
| Tổng quan | Số câu hỏi, người dùng, thời gian trả lời TB/P95, thời gian ra chữ đầu, tốc độ sinh (token/giây), tỷ lệ đạt kiểm chứng, không có căn cứ, chặn ATTT, lỗi; biểu đồ theo thời gian; theo luồng; tình trạng dịch vụ và máy chủ mô hình; CPU/RAM/ổ đĩa; hàng đợi tác vụ dài |
| Người dùng | Số câu hỏi, thời gian TB, câu không có căn cứ, luồng hay dùng, lần cuối hoạt động |
| Hiệu năng | Theo loại lượt gọi mô hình: số lượt, thời gian TB, token vào/ra TB, token/giây; theo dịch vụ: P95, lỗi 4xx/5xx |
| Nhật ký hệ thống (quản trị) | Nhật ký WARNING/ERROR và sự kiện nghiệp vụ của mọi dịch vụ, lọc mức, dịch vụ, từ khóa, xem trực tiếp; bấm dòng để xem chi tiết lỗi |
| Kiểm toán (quản trị) | Nhật ký kiểm toán chuỗi băm, thống kê hành động, người thực hiện, kiểm tra toàn vẹn |

Đọc số liệu để tinh chỉnh: lượt gọi có *token vào TB* lớn và thời gian dài → giảm `CTX_BUDGET_SOURCES`
(hỏi đáp) hoặc `AGENT_PART_TOKENS` (phân tích); *token/giây* thấp bất thường → kiểm tra số luồng llama-server, RAM.

## 9. Bảng tham số bổ sung

| Tham số | Mặc định | CPU khuyến nghị | GPU | Ý nghĩa |
|---|---|---|---|---|
| `HARDWARE_PROFILE` | cpu | cpu | gpu | Hồ sơ phần cứng |
| `CLARIFY_ENABLED` | true | true | true | Hỏi lại khi chưa rõ |
| `CLARIFY_MAX_SCORE` | 0.0 | 0.0 | 0.0 | Ngưỡng điểm rerank coi là kết quả phân tán |
| `GUARD_ENABLED` | true | true | true | Bảo vệ ATTT đầu vào |
| `AGENT_YIELD_MAX_S` | 180 | 120–300 | 0–30 | Tác vụ nền nhường mô hình tối đa (giây) mỗi lượt gọi |
| `AGENT_PART_TOKENS` | 3000 | 2500–3000 | 5000–8000 | Kích thước phần khi phân tích |
| `AGENT_MAX_CRITERIA` | 20 | 12–16 | 20–30 | Số tiêu chí tối đa mỗi lượt phân tích |
| `AGENT_DRAFT_CTX` | 2500 | 2000–2500 | 4000–6000 | Ngân sách căn cứ mỗi phần khi soạn thảo |
| `AGENT_WORKERS` (compose) | 1 | 1 | 2–4 | Số tác vụ dài chạy song song |
| `QA_INTERVAL_MIN` | 120 | 120–360 | 60 | Chu kỳ giám định dữ liệu (0 = chỉ chạy tay) |
| `QA_LLM_MODE` / `QA_LLM_HOURS` | auto / 22-6 | auto | on | Kiểm tra chéo bằng mô hình |
| `QA_DUP_THRESHOLD` | 0.85 | | | Ngưỡng gần trùng |
| `QA_STALE_MONTHS` | 18 | | | Báo cáo, kế hoạch cũ hơn N tháng → đề nghị rà soát |

## 10. Kiểm thử

```bash
python tests/run_stack.py --reset          # chạy hệ thống với mô hình giả lập (9 dịch vụ + 2 tiến trình nền)
python -m pytest -q tests/                 # 49 ca: đơn vị + tích hợp (tests/test_agent_e2e.py cho 1.3.0)
python tests/run_stack.py --real --seed    # mô hình thật; --seed chỉ bổ sung tài liệu mẫu còn thiếu
python tests/eval_real.py                  # bộ câu hỏi mẫu (có thêm R3 USB Token, C1 hỏi lại, G1 chặn bí mật)
```
