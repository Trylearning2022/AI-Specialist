# Hướng dẫn tinh chỉnh tìm kiếm, truy xuất và chất lượng câu trả lời (Luồng A)

Áp dụng từ bản 1.2.0. Tài liệu dành cho cán bộ kỹ thuật vận hành hệ thống: giải thích quy trình truy xuất,
các tham số có thể điều chỉnh, cách chẩn đoán khi câu trả lời thiếu, sai, lệch trích dẫn.

Trong mã nguồn, mọi điểm có thể tinh chỉnh được đánh dấu `[TINH CHỈNH]`:

```bash
grep -rn "TINH CHỈNH" backend/
```

## 1. Quy trình trả lời một câu hỏi tra cứu

```
Câu hỏi
  │ (1) Viết lại câu hỏi nối tiếp thành câu độc lập (chỉ khi có lịch sử hội thoại, mô hình nhỏ)
  │ (2) Mở rộng thuật ngữ viết tắt theo glossary/thuat-ngu.md (PKT → Phòng Kỹ thuật)
  ▼
search-svc ── nhánh vector (bge-m3) ──┐  mỗi nhánh SEARCH_CANDIDATES đoạn, đã lọc quyền
          └── nhánh BM25 (âm tiết,    ├─► hợp nhất RRF
              cặp âm tiết, không dấu) ┘
  │ (3) Xếp hạng lại (bge-reranker): loại đoạn dưới RERANK_THRESHOLD hoặc kém đoạn tốt nhất quá RERANK_MARGIN
  │ (4) Gộp các đoạn cùng mục; mục ≤ SEARCH_SECTION_MAX_TOKENS lấy NGUYÊN mục,
  │     mục dài hơn lấy đoạn trúng ± SEARCH_NEIGHBORS đoạn; tối đa SEARCH_MAX_PER_DOC mục/tài liệu
  │ (5) Giữ SEARCH_TOP_K mục
  ▼
orchestrator
  │ (6) Chọn nguồn theo ngân sách CTX_BUDGET_SOURCES (mục cuối không vừa thì cắt bớt, không bỏ)
  │ (7) Lắp ngữ cảnh: chính sách → vai trò → thuật ngữ → CÂU HỎI → NGUỒN [1..n] → NHẮC LẠI CÂU HỎI
  │ (8) Mô hình chính sinh câu trả lời (ANSWER_TEMPERATURE, tối đa ANSWER_MAX_TOKENS)
  │     Bị cắt vì hết token → rút về ý trọn vẹn cuối, ghi chú cho người dùng
  │ (9) Verifier: trích dẫn hợp lệ → bám nguồn từng câu (sửa [n] lệch, bổ sung [n] thiếu,
  │     đánh dấu câu không có trong nguồn) → trích nguyên văn → số liệu
  ▼
Câu trả lời + nguồn + cảnh báo
```

## 2. Bảng tham số

Đặt trong `.env` (triển khai Docker Compose) hoặc biến môi trường trước khi chạy `run_stack.py`
(PowerShell: `$env:TEN_BIEN="giá trị"`). Cột "Lập chỉ mục lại" = phải chạy lại lập chỉ mục sau khi đổi.

| Tham số | Mặc định | Máy dev CPU (`--real`) | Tác dụng | Lập chỉ mục lại |
|---|---|---|---|---|
| `CHUNK_MAX_TOKENS` | 500 | 500 | Kích thước đoạn khi lập chỉ mục. Nhỏ: khớp chính xác hơn, dễ mất ngữ cảnh. Lớn: đủ ý hơn, vector "loãng" | Có |
| `CHUNK_MIN_TOKENS` | 60 | 60 | Đoạn ngắn hơn được gộp với đoạn kế tiếp cùng mục cha | Có |
| `SEARCH_CANDIDATES` | 30 | 20 | Số ứng viên mỗi nhánh tìm kiếm trước khi xếp hạng lại. Tăng: ít bỏ sót; reranker chậm hơn | Không |
| `SEARCH_TOP_K` | 6 | 5 | Số mục đưa cho mô hình | Không |
| `SEARCH_SECTION_MAX_TOKENS` | 1200 | 900 | Mục ngắn hơn được đưa nguyên mục (khắc phục thiếu bước, thiếu dòng bảng) | Không |
| `SEARCH_NEIGHBORS` | 1 | 1 | Mục dài: số đoạn lân cận lấy thêm mỗi phía đoạn trúng | Không |
| `SEARCH_MAX_PER_DOC` | 3 | 3 | Số mục tối đa từ một tài liệu (đa dạng nguồn); 0 = không giới hạn | Không |
| `SEARCH_EXPAND_GLOSSARY` | true | true | Mở rộng chữ viết tắt theo từ điển thuật ngữ | Không |
| `RERANK_THRESHOLD` | −2.0 | −2.0 | Ngưỡng tuyệt đối điểm reranker (logit). Tăng: ít nguồn rác; giảm: ít "không tìm thấy căn cứ" | Không |
| `RERANK_MARGIN` | 7.0 | 7.0 | Loại nguồn kém nguồn tốt nhất quá N điểm; 0 = tắt | Không |
| `CTX_BUDGET_SOURCES` | 8000 | 4000 | Token dành cho nguồn. Thời gian xử lý trên CPU tăng gần tuyến tính theo giá trị này | Không |
| `ANSWER_MAX_TOKENS` | 1024 | 800 | Độ dài tối đa câu trả lời. Quá thấp → bị cắt (có cảnh báo) | Không |
| `ANSWER_TEMPERATURE` | 0.1 | 0.1 | Nhiệt độ sinh câu trả lời; thấp = bám nguồn | Không |
| `VERIFY_GROUNDING` | true | true | Kiểm tra bám nguồn theo từng câu | Không |
| `VERIFY_SUPPORT_MIN` | 0.30 | 0.30 | Câu có độ phủ với mọi nguồn dưới ngưỡng → đánh dấu "chưa tìm thấy trong nguồn" | Không |
| `VERIFY_SUPPORT_LOW` / `_FIX` | 0.35 / 0.60 | như mặc định | Câu trích [n] phủ < LOW nhưng nguồn khác phủ ≥ FIX → tự sửa chỉ số trích dẫn | Không |
| `VERIFY_STRICT_A` | true | true | Câu trả lời không có trích dẫn hợp lệ nào → thay bằng câu từ chối | Không |

Ước lượng thời gian trên CPU (mô hình 9B, Q4_K_M): đọc ngữ cảnh khoảng 30–60 token/giây, sinh câu trả lời
khoảng 3–8 token/giây. Ví dụ ngữ cảnh 5.500 token và câu trả lời 400 token mất khoảng 2–3 phút cho phần đọc
và 1–2 phút cho phần sinh. Trên máy chủ GPU, cả hai nhanh hơn hàng chục lần, nên dùng giá trị mặc định.

## 3. Triệu chứng và cách xử lý

| Triệu chứng | Nguyên nhân thường gặp | Xử lý |
|---|---|---|
| Câu trả lời dừng giữa chừng, có ghi chú "đã được rút gọn" | Chạm `ANSWER_MAX_TOKENS` | Tăng `ANSWER_MAX_TOKENS` (CPU: 900–1000); hoặc hỏi hẹp hơn |
| Thiếu bước, thiếu dòng bảng so với tài liệu | Mục bị tách nhiều đoạn, mục quá dài so với `SEARCH_SECTION_MAX_TOKENS` | Tăng `SEARCH_SECTION_MAX_TOKENS` hoặc `SEARCH_NEIGHBORS`; kiểm tra tài liệu có tiêu đề mục rõ ràng |
| Thiếu ý ở câu hỏi nhiều ý (hai đơn vị, hai thời điểm) | Một tài liệu chiếm hết chỗ; `SEARCH_TOP_K` nhỏ | Giảm `SEARCH_MAX_PER_DOC` (2); tăng `SEARCH_TOP_K` và `CTX_BUDGET_SOURCES` |
| "Không tìm thấy căn cứ" dù tài liệu có nội dung | Đoạn đúng không vào ứng viên, hoặc bị reranker loại | Chạy `tools.search_debug` (mục 4): nếu đoạn đúng có trong nhánh nhưng bị ✗ → giảm `RERANK_THRESHOLD`; nếu không có trong nhánh nào → tăng `SEARCH_CANDIDATES`, bổ sung thuật ngữ vào từ điển |
| Trả lời lẫn nội dung của tài liệu không liên quan | Nguồn yếu lọt vào ngữ cảnh | Tăng `RERANK_THRESHOLD` (−1,0) hoặc giảm `RERANK_MARGIN` (5,0) |
| Câu có nhãn "chưa tìm thấy trong nguồn" | Mô hình thêm nội dung ngoài nguồn | Đối chiếu nguồn; nếu nhãn đặt nhầm cho câu diễn đạt lại đúng → giảm `VERIFY_SUPPORT_MIN` (0,25) |
| Cảnh báo "Đã điều chỉnh chỉ số trích dẫn" xuất hiện nhiều | Mô hình ghi [n] sai nguồn | Hệ thống đã tự sửa; nếu thường xuyên, cân nhắc mô hình lớn hơn hoặc giảm số nguồn (`SEARCH_TOP_K`) |
| Gõ không dấu tìm sai | Thiếu khớp từ khóa | Từ bản 1.2.0 BM25 đã khớp không dấu; cần lập chỉ mục lại dữ liệu cũ (mục 6) |
| Chữ viết tắt của đơn vị không được hiểu | Từ điển chưa có | Bổ sung vào `glossary/thuat-ngu.md` (dạng bảng: Thuật ngữ, Giải thích) |
| Trả lời rất chậm trên CPU | Ngữ cảnh lớn | Giảm `CTX_BUDGET_SOURCES`, `SEARCH_TOP_K`; dùng mô hình 4B; xem phần stream để đọc dần |

Nguyên tắc: mỗi lần chỉ đổi MỘT tham số, chạy lại `python tests/eval_real.py`, so sánh tệp
`.test-run-that/eval-*.json` với lần trước.

## 4. Công cụ chẩn đoán tìm kiếm

```powershell
cd backend
python -m tools.search_debug "Máy trạm mất kết nối mạng thì xử lý thế nào?"
python -m tools.search_debug "PKT kiến nghị gì" --no-rerank     # xem thứ tự khi chưa xếp hạng lại
```

Kết quả gồm bốn phần:

1. **Sau mở rộng**: truy vấn sau khi thêm nghĩa chữ viết tắt.
2. **Nhánh vector / nhánh BM25**: 10 đoạn đứng đầu mỗi nhánh (mã mục, số đoạn, điểm). Đoạn đúng chỉ có ở
   BM25 → câu hỏi dùng từ đặc thù, mô hình embedding chưa hiểu; chỉ có ở vector → câu hỏi diễn đạt khác tài liệu.
3. **Xếp hạng lại**: điểm reranker của mọi ứng viên; ✓ = được chọn, ✗ = bị loại (dưới ngưỡng, trùng mục,
   vượt `SEARCH_TOP_K` hoặc `SEARCH_MAX_PER_DOC`).
4. **Nguồn đưa cho mô hình**: các mục cuối cùng, các đoạn được ghép, có mở rộng hay không, độ dài ước lượng.

Nếu phần 4 đã có đủ nội dung mà câu trả lời vẫn thiếu, sai: vấn đề nằm ở mô hình hoặc chỉ thị
(`prompts/README.md`), không ở tìm kiếm.

## 5. Kiểm chứng bám nguồn theo từng câu

Verifier (`services/orchestrator/verifier.py`) tách câu trả lời thành từng câu, đo **độ phủ** giữa câu và từng nguồn:

```
độ phủ = ½ × (tỷ lệ âm tiết nội dung của câu có trong nguồn) + ½ × (tỷ lệ cặp âm tiết liền kề có trong nguồn)
```

Âm tiết giữ dấu, đã bỏ hư từ ("và", "của", "các"…). Câu diễn đạt sát nguồn thường đạt ≥ 0,5; câu bịa thường < 0,25.
Câu có dưới 6 âm tiết nội dung (câu nối, tiêu đề) không bị đối chiếu.

| Kết quả đối chiếu | Hành động |
|---|---|
| Câu ghi [n], nguồn n phủ thấp, nguồn m phủ cao | Sửa thành [m], cảnh báo "Đã điều chỉnh chỉ số trích dẫn" |
| Câu không ghi trích dẫn, khớp rõ một nguồn | Bổ sung [m] |
| Câu không khớp nguồn nào | Gắn nhãn *(chưa tìm thấy trong nguồn)*, câu trả lời mang nhãn "Cần đối chiếu" |

Đây là phép đo từ vựng: không hiểu nghĩa, có thể đánh dấu nhầm câu diễn đạt lại quá xa nguồn. Nhãn là
cảnh báo để người dùng đối chiếu, không xóa nội dung.

## 6. Nâng cấp lên 1.2.0: lập chỉ mục lại

Bản 1.2.0 thay đổi cách tách đoạn (bỏ đoạn chỉ có tiêu đề, cắt bảng giữ dòng tiêu đề) và vector thưa
(thêm thuật ngữ không dấu). Dữ liệu đã nạp trước đó vẫn tìm được nhưng không hưởng các cải tiến này.

- Máy dev: `python tests/run_stack.py --real --reindex` (giữ nguyên dữ liệu, chỉ lập chỉ mục lại Luồng A),
  hoặc làm lại từ đầu `--reset --seed`.
- Máy chủ: `docker compose --profile tools run --rm tools python -m tools.reindex`.

## 7. Soạn tài liệu để truy xuất tốt

1. Mỗi mục một chủ đề, có tiêu đề rõ (`## Cách xử lý`, `### Điều 5. Thời hạn sử dụng`): tiêu đề trở thành
   đường dẫn ngữ cảnh của đoạn, giúp tìm đúng và trích dẫn đúng.
2. Quy trình viết dạng danh sách đánh số trong một mục; không trải một quy trình qua nhiều mục.
3. Bảng có dòng tiêu đề; tránh bảng gộp ô phức tạp (sau chuyển đổi dễ vỡ cấu trúc).
4. Ghi đủ đơn vị, thời gian trong nội dung ("Phòng Kỹ thuật, tuần 45"), không chỉ ở tên tệp.
5. Bổ sung chữ viết tắt, tên gọi khác của đơn vị vào `glossary/thuat-ngu.md`.
