# Hệ thống AI Local nội bộ

Mã nguồn hoàn chỉnh của hệ thống AI cục bộ theo *Phương án tổng thể xây dựng hệ thống AI Local*: tra cứu tài liệu nội bộ có trích dẫn, tra cứu chính xác văn bản chuẩn (trích nguyên văn), tổng hợp báo cáo theo mẫu, hỗ trợ kỹ thuật. Hệ thống chạy hoàn toàn trên mạng nội bộ, trên máy chủ chỉ có CPU, và nâng cấp lên GPU mà không phải sửa mã ứng dụng.

**Đơn vị chỉ cần bổ sung tệp mô hình** (GGUF) vào thư mục `models/` – xem [models/README.md](models/README.md).

---

## 1. Kiến trúc

```
Trình duyệt ──HTTPS──> Nginx (biên, TLS) ──> portal (Vue 3)
                                         ├──> Keycloak (SSO, RBAC, đơn vị, cấp độ mật)
                                         └──> gateway (xác thực JWT, giới hạn tần suất, ký ngữ cảnh người dùng, kiểm toán)
                                                 │
     ┌────────────── orchestrator (HARNESS: định tuyến · Context Builder · Verifier · vòng lặp tác tử · MCP) ─┐
     │                  │                     │                      │                    │                 │
 search-svc        exact-svc            summary-svc + worker    support-svc        ingest-svc + worker   audit-svc
 Luồng A           Luồng B              Map → tính bằng mã      cây xử lý sự cố,   chuyển đổi, làm     nhật ký chuỗi
 vector+BM25,RRF   Markdown nguyên văn  → Reduce → Verifier     phiếu yêu cầu      sạch, kiểm duyệt   băm (Redis Stream)
 rerank            Git + PostgreSQL FTS → DOCX (pandoc)                            2 cấp cho Luồng B
     │                  │                     │                                         │
  Qdrant           kho Git /kb           PostgreSQL · Redis (hàng đợi Celery)       docling-serve (PDF/OCR)
     │
  embed / rerank (llama.cpp)      LiteLLM ──> llm-main (llama.cpp, CPU) │ vLLM (GPU, giai đoạn 4)
```

| Thành phần | Nguồn | Vai trò |
|---|---|---|
| llama.cpp `llama-server` | Mã nguồn mở (MIT), ảnh chính thức | Suy luận LLM, embedding, rerank trên CPU |
| LiteLLM | Mã nguồn mở (MIT), ảnh chính thức | Cổng mô hình: tên logic `chinh`/`nho`, dự phòng, hạn mức |
| vLLM | Mã nguồn mở (Apache 2.0) | Suy luận GPU (giai đoạn 4) |
| Qdrant | Mã nguồn mở (Apache 2.0) | CSDL vector, tìm kiếm lai, lọc theo quyền |
| docling-serve | Mã nguồn mở (MIT, IBM) | Chuyển PDF/ảnh scan sang Markdown, OCR |
| MarkItDown | Mã nguồn mở (MIT, Microsoft) | Chuyển DOCX/XLSX/PPTX/HTML sang Markdown |
| Keycloak | Mã nguồn mở (Apache 2.0) | SSO, vai trò, nhóm đơn vị, MFA |
| PostgreSQL, Redis, Nginx, Gitea, Prometheus | Mã nguồn mở | Dữ liệu, hàng đợi, biên, kho Git, giám sát |
| `backend/` (Python, FastAPI) | Viết mới | 8 dịch vụ nghiệp vụ, harness, verifier |
| `frontend/` (Vue 3) | Viết mới | Cổng nghiệp vụ và quản trị |

### Hai luồng tri thức

| | Luồng A – tra cứu tham khảo | Luồng B – tra cứu chính xác |
|---|---|---|
| Dữ liệu | Tài liệu đã chuẩn hóa Markdown | Kho Markdown chuẩn (Git), mỗi mục có mã định danh `<!-- id: ... -->` |
| Truy xuất | Vector dày + BM25 → RRF → rerank (Qdrant) | Mã định danh, tham chiếu “Điều/Khoản/số hiệu”, tìm kiếm toàn văn PostgreSQL (tsvector/GIN, pg_trgm khi gõ sai), mô hình chọn mục **trong danh sách ứng viên** – **không dùng vector** |
| Vai trò mô hình | Viết câu trả lời có trích dẫn `[n]` | Chỉ viết câu dẫn và diễn giải; **khối nguyên văn do chương trình chèn** từ tệp |
| Verifier | Loại trích dẫn không tồn tại; kiểm tra trích dẫn nguyên văn, số liệu; không có trích dẫn hợp lệ → “Không tìm thấy căn cứ” | Mọi số, trích dẫn trong diễn giải phải có trong nguyên văn, nếu không → loại diễn giải; cảnh báo văn bản hết hiệu lực |
| Cập nhật | Duyệt 1 cấp | Duyệt **2 cấp bởi 2 cán bộ khác nhau**, commit Git có tác giả là người duyệt, sinh `INDEX.md` |

### Context engineering và harness engineering (trong `services/orchestrator`)

- **Context Builder** (`context.py`): chỉ thị phân tầng (chính sách cố định đặt đầu để tận dụng cache tiền tố `--cache-reuse`), vai trò theo phân hệ, kỹ năng Markdown, thuật ngữ đơn vị (chỉ chèn thuật ngữ xuất hiện), tóm tắt hội thoại, nguồn theo ngân sách token.
- **Bộ định tuyến** (`pipelines.py`): quy tắc trước, mô hình nhỏ sau (JSON có schema).
- **Verifier** (`verifier.py`): kiểm tra bằng mã chương trình, không dùng LLM cho kiểm tra cứng.
- **Vòng lặp tác tử có giới hạn** (chế độ “Trợ lý nhiều bước”): tối đa `AGENT_MAX_STEPS` bước, `AGENT_TIMEOUT_S` giây; công cụ theo vai trò, mặc định chỉ đọc; công cụ có ghi bắt buộc xác nhận.
- **Tool Registry** (`tools.py`): cùng một danh mục công bố qua API `/api/chat/tools`, máy chủ **MCP** `/api/chat/mcp/` và định dạng tools của OpenAI.
- **Vòng “bánh cóc”**: phản hồi Đúng/Sai của người dùng → màn hình Quản trị › Phản hồi → sửa ở tầng tương ứng (dữ liệu, kỹ năng, thuật ngữ, ngưỡng) → bổ sung ca kiểm thử.
- **Tùy biến không cần lập trình**: `prompts/*.md` (chỉ thị), `skills/*/SKILL.md` (kỹ năng + mẫu báo cáo), `glossary/thuat-ngu.md`, `support/trees/*.yaml` (cây xử lý sự cố).

---

## 2. Cấu trúc thư mục

```
backend/
  aicommon/            thư viện dùng chung: cấu hình, bảo mật, LLM client, Markdown, văn bản tiếng Việt, CSDL, kiểm toán
  services/
    gateway/           API Gateway (OIDC/JWT, chế độ dev, giới hạn tần suất, proxy SSE)
    orchestrator/      harness: định tuyến, Context Builder, Verifier, luồng xử lý, tác tử, MCP, hội thoại, phản hồi
    search/            Luồng A: lập chỉ mục, tìm kiếm lai, rerank, lọc quyền
    exact/             Luồng B: kho Git văn bản chuẩn, chỉ mục toàn văn PostgreSQL, phân giải tham chiếu, lịch sử, so sánh phiên bản
    ingest/            nạp: nhận dạng định dạng, chuyển đổi, làm sạch (Unicode NFC, TCVN3, đầu/chân trang), metadata,
                       chấm điểm chất lượng, phát hiện trùng lặp (MinHash), kiểm duyệt, sổ đăng ký tài liệu, thu hồi
    summary/           tổng hợp Map → tính bằng mã → Reduce → Verifier → DOCX
    support/           cây xử lý sự cố, phiếu yêu cầu, đề xuất bổ sung tri thức
    audit/             nhật ký kiểm toán chuỗi băm, kiểm tra toàn vẹn
  tools/               seed.py (nạp dữ liệu ban đầu), reindex.py (lập chỉ mục lại)
  tests/               kiểm thử đơn vị, tích hợp end-to-end, máy chủ mô hình giả lập
frontend/              Vue 3: Hỏi đáp, Tra cứu chính xác, Tổng hợp, Hỗ trợ kỹ thuật, Danh mục, Nạp dữ liệu, Kiểm duyệt, Quản trị
prompts/ skills/ glossary/ support/   tài nguyên Markdown/YAML tùy biến
docs/                  đánh giá kỹ thuật (docs/danh-gia-fts.md: SQLite FTS5 – PostgreSQL)
kb-seed/               dữ liệu mẫu (van-ban/ → Luồng B, tai-lieu/ → Luồng A)
config/                nginx, keycloak (realm), litellm, postgres, prometheus, tài khoản thử nghiệm
scripts/               init, gen-certs, download-models, export-bundle, import-bundle, backup, smoke-test
docker-compose.yml     triển khai Giai đoạn 1 (CPU) · docker-compose.gpu.yml: bổ sung vLLM
```

---

## 3. Triển khai trên mạng nội bộ

### 3.1. Yêu cầu

- Máy chủ Linux x86_64, Docker Engine 24+ và Docker Compose v2.
- Cấu hình tham chiếu: Cấp 1 – 16 nhân, RAM 64 GB; Cấp 2 – 64 nhân, RAM 192–256 GB (lắp đủ kênh nhớ). Ảnh docling-serve khoảng 4–5 GB.
- Tên miền nội bộ (ví dụ `ai.noibo.local`) trỏ về máy chủ.

### 3.2. Chuẩn bị tại máy tải (vùng Internet)

```bash
# 1) Mô hình (tự lượng tử hóa từ bản gốc – khuyến nghị; hoặc MODE=gguf để tải GGUF dựng sẵn)
CAP=2 MODE=quantize scripts/download-models.sh ./out-models
# 2) Ảnh container, gói Python, mã nguồn; ký số SHA256SUMS bằng chứng thư của cán bộ phụ trách
scripts/export-bundle.sh ./bundle canbo.crt canbo.key
```

Chuyển `bundle/` và `out-models/gguf/` vào mạng nội bộ qua phương tiện được cấp phép theo quy trình chuyển giao.

### 3.3. Tại máy chủ nội bộ

```bash
tar xzf bundle/source/ai-local.tar.gz -C /opt/ai-local && cd /opt/ai-local
scripts/import-bundle.sh /duong-dan/bundle ca-noibo.crt /duong-dan/out-models/gguf   # xác thực chữ ký, băm; nạp ảnh; chép mô hình
cp .env.example .env && vi .env      # AI_HOST, AI_PUBLIC_URL, tên tệp mô hình, số luồng CPU, SYSTEM_MAX_CLEARANCE
scripts/init.sh                      # sinh khóa bí mật, chứng thư (nếu chưa có), kiểm tra mô hình, khởi động, chờ sẵn sàng
scripts/smoke-test.sh                # kiểm tra mô hình, embedding
docker compose --profile tools run --rm tools   # (tùy chọn) nạp dữ liệu mẫu trong kb-seed/
```

- Đăng nhập lần đầu: tài khoản `quantri`, mật khẩu tạm `KC_INIT_ADMIN_PASSWORD` trong `.env` (bắt buộc đổi mật khẩu và cài OTP).
- Quản lý người dùng tại `https://<AI_HOST>/auth/admin/` (chỉ mở từ dải mạng quản trị – sửa trong `config/nginx/nginx.conf`):
  - vai trò `user`, `reviewer`, `admin`; cấp độ được xem `cap-do-0..3` (bị giới hạn thêm bởi `SYSTEM_MAX_CLEARANCE`);
  - đơn vị qua nhóm `/don-vi/<ma-don-vi>`; nhóm `/don-vi/tat-ca` được xem tài liệu mọi đơn vị.
- Dùng chứng thư do PKI của đơn vị cấp: đặt `server.crt`, `server.key` (và `ca.crt` nếu bật mTLS) vào `config/pki/`.
- Đăng nhập bằng chứng thư số (USB Token): cấu hình luồng xác thực X.509 trong Keycloak và bật `ssl_verify_client` tại Nginx.

### 3.4. Chế độ cấu hình mô hình

| Tình huống | Thiết lập trong `.env` |
|---|---|
| Chỉ có 01 mô hình | `LLM_SMALL_URL=http://llm-main:8080/v1` (mặc định) |
| Có mô hình nhỏ riêng | `LLM_SMALL_URL=http://llm-small:8080/v1`, `init.sh` tự bật profile `mo-hinh-nho` |
| Không dùng reranker | để trống `RERANK_URL` |
| Bật chế độ suy luận dài (thinking) | bỏ `--reasoning-budget 0` khỏi `LLM_MAIN_EXTRA` (chậm hơn đáng kể trên CPU) |
| Có GPU (Giai đoạn 4) | `LLM_MAIN_URL=http://vllm:8000/v1`, `VLLM_MODEL_DIR=...`, chạy `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d` |

Đổi mô hình embedding (khác số chiều): xóa collection `tai_lieu` trong Qdrant, sau đó `docker compose --profile tools run --rm tools python -m tools.reindex`.

### 3.5. Vận hành

- `make logs`, `docker compose ps`; giám sát: `docker compose --profile giam-sat up -d` (Prometheus tại `127.0.0.1:9090`, mọi dịch vụ có `/metrics`).
- Sao lưu: `scripts/backup.sh` (PostgreSQL, snapshot Qdrant, bundle Git kho văn bản chuẩn, dữ liệu tài liệu) – đặt lịch cron, mã hóa bản sao lưu theo quy định.
- Kho Git văn bản chuẩn đồng bộ lên Gitea: chạy `--profile gitea`, tạo kho, đặt `KB_GIT_REMOTE`.
- Kiểm tra toàn vẹn nhật ký kiểm toán: Quản trị › Nhật ký kiểm toán › “Kiểm tra toàn vẹn chuỗi băm”.

---

## 4. Chạy thử trên máy phát triển (VS Code, Windows/Linux/macOS)

Không cần mô hình thật: `tests/mock_llm.py` giả lập máy chủ LLM, embedding, reranker. Cần: Python 3.12+, Git, Docker Desktop (chỉ để chạy PostgreSQL và Redis), Node.js 20+ (giao diện); pandoc (tùy chọn, để xuất DOCX).

Trong VS Code: **Terminal › Run Task…** chạy lần lượt:

| Tác vụ | Lệnh tương đương |
|---|---|
| 0. Kiểm tra môi trường | `python backend/tests/check_env.py` |
| 1. Tạo môi trường Python (.venv) | `python -m venv .venv` rồi `pip install -r backend/requirements-dev.txt` |
| 2. Bật PostgreSQL + Redis thử nghiệm (Docker) | `docker compose -f docker-compose.test.yml up -d --wait` |
| 2b. Dừng PostgreSQL + Redis thử nghiệm | `docker compose -f docker-compose.test.yml stop` |
| 3. Chạy hệ thống thử nghiệm (3b: xóa dữ liệu cũ) | `cd backend && python tests/run_stack.py [--reset]` |
| 4. Chạy toàn bộ kiểm thử | `cd backend && python -m pytest` |
| 5. Chạy giao diện (Vite) | `cd frontend && npm install && npm run dev` → http://localhost:5173 |

- Sau bước 1, chọn trình thông dịch `.venv` (Ctrl+Shift+P › *Python: Select Interpreter*); bảng **Testing** của VS Code sẽ liệt kê các bài kiểm thử trong `backend/tests`.
- Đăng nhập giao diện bằng tài khoản thử nghiệm `canbo`, `kiemduyet1`, `kiemduyet2`, `quantri`. Dữ liệu mẫu được nạp tự động khi chạy kiểm thử lần đầu (hoặc `python -m tools.seed ../kb-seed` với biến môi trường như `run_stack.py`).
- Hướng dẫn chi tiết từng bước (cấu hình Docker Desktop, lệnh, kết quả mẫu): `docs/huong-dan-chay-thu.md`.
- Nhật ký từng dịch vụ: thư mục `.test-run/logs`. Gỡ lỗi bằng cấu hình trong `.vscode/launch.json`.
- Trên Linux có sẵn PostgreSQL 16 và Redis có thể dùng `tests/run_stack.sh` thay cho Docker.
- Đo so sánh SQLite FTS5 – PostgreSQL: `cd backend && python tests/bench_fts.py --sections 50000`.

Bộ kiểm thử (22 bài) kiểm tra: xác thực, phân quyền vai trò; tra cứu chính xác bằng tham chiếu trực tiếp và bằng FTS; Verifier loại diễn giải chứa số bịa; Luồng A dạng luồng (SSE) với loại trích dẫn không tồn tại; định tuyến tự động; cây xử lý sự cố → phiếu → đề xuất tri thức; tổng hợp với số liệu do chương trình tính, loại số bịa, xuất DOCX; nạp DOCX, chuyển mã TCVN3, chặn độ mật vượt quyền; lọc theo đơn vị; duyệt 2 cấp bắt buộc khác người; vòng lặp tác tử; máy chủ MCP; phản hồi, hội thoại riêng tư; chuỗi băm kiểm toán.

> Máy chủ mô hình giả lập (`tests/mock_llm.py`) chỉ phục vụ kiểm thử luồng xử lý. Chất lượng câu trả lời thực tế phụ thuộc mô hình, cần đánh giá trên bộ câu hỏi (golden set) của đơn vị theo mục 4.5 của phương án.

---

### 4.1. Chạy với mô hình thật trên máy phát triển (32 GB RAM, CPU)

Cấu hình đề xuất: Qwen3.5-9B Q4_K_M (mô hình chính), bge-m3 Q8_0 (embedding), bge-reranker-v2-m3 Q8_0 (reranker), khoảng 7 GB tệp; phương án nhẹ hơn: Qwen3.5-4B.

| Tác vụ VS Code | Lệnh tương đương (thư mục `backend`) |
|---|---|
| (tải mô hình, máy có Internet) | `pip install huggingface_hub` rồi `python -m tools.download_dev_models [--chat 4b]` |
| 6. Chạy mô hình thật (llama-server) | `python tests/run_models.py --llama-dir C:\llama.cpp [--check] [--no-rerank]` |
| 7. Chạy hệ thống với mô hình thật | `python tests/run_stack.py --real --reset --seed [--no-rerank]` |
| 8. Đánh giá với mô hình thật | `python tests/eval_real.py [--show] [--only B1,A1]` |

- Chế độ `--real` dùng CSDL riêng (`<tên>_that`), Redis số 1, thư mục `.test-run-that`; không lẫn dữ liệu với chế độ mô hình giả lập.
- `run_models.py` đặt `-c` = ngữ cảnh mỗi luồng × số luồng (llama-server chia `-c` cho `--parallel`), tắt chế độ suy luận (`--reasoning off` hoặc `--reasoning-budget 0` tùy bản llama.cpp), chỉ mở cổng trên 127.0.0.1.
- Hướng dẫn chi tiết từng bước: tài liệu "Hướng dẫn chạy AI Local với mô hình thật trên máy 32 GB RAM".

## 5. API chính (qua Gateway, tiền tố `/api`)

| Nhóm | Đường dẫn |
|---|---|
| Hỏi đáp | `POST /chat/chat` (SSE: `start`, `status`, `meta`, `delta`, `step`, `final`), `GET/PATCH/DELETE /chat/conversations[/{id}]`, `POST /chat/messages/{id}/interpret` (diễn giải nguyên văn theo yêu cầu), `POST /chat/feedback`, `GET /chat/tools`, `POST /chat/tools/{ten}`, MCP `POST /chat/mcp/` |
| Luồng A | `POST /search/search`, `POST /search/documents` |
| Luồng B | `GET /exact/catalog`, `GET /exact/docs/{id}`, `GET /exact/sections/{ma_muc}`, `POST /exact/search`, `POST /exact/resolve`, `GET /exact/docs/{id}/versions`, `GET /exact/docs/{id}/diff` |
| Nạp dữ liệu | `POST /ingest/jobs`, `GET /ingest/jobs/{id}`, `PUT /ingest/jobs/{id}`, `POST /ingest/jobs/{id}/approve` (`track` A/B), `/reject`, `/retry`, `GET /ingest/documents`, `DELETE /ingest/documents/{id}` (thu hồi), `GET /ingest/reports/quality` |
| Tổng hợp | `GET /summary/templates`, `POST /summary/jobs`, `GET /summary/jobs/{id}`, `GET /summary/jobs/{id}/docx` |
| Hỗ trợ | `GET /support/trees`, `POST /support/sessions`, `POST /support/sessions/{id}/answer`, `GET/POST/PATCH /support/tickets` |
| Kiểm toán | `GET /audit/logs`, `GET /audit/verify` |

Tài liệu OpenAPI: `https://<AI_HOST>/api/docs` (gateway); mỗi dịch vụ có `/docs` nội bộ.

---

## 6. Điểm khác so với văn bản phương án

| Nội dung phương án | Hiện thực trong mã nguồn | Lý do |
|---|---|---|
| Kho tệp gốc SeaweedFS | Volume `appdata` | Giảm thành phần ở giai đoạn 1; có thể thay bằng lưu trữ S3 nội bộ |
| LangGraph cho vòng lặp tác tử | Vòng lặp tự viết có giới hạn bước, thời gian | Ít phụ thuộc, dễ kiểm soát, đủ cho các luồng hiện tại |
| Langfuse | Nhật ký kiểm toán chuỗi băm + Prometheus + vết hội thoại trong CSDL | Langfuse v3 cần thêm ClickHouse, nặng với hạ tầng CPU; có thể bổ sung sau |
| Harbor, Wazuh, OpenBao | Không nằm trong compose | Là hạ tầng dùng chung vùng quản trị; scripts hỗ trợ đẩy ảnh lên Harbor (`HARBOR=...`) |

## 7. Giới hạn đã biết

- Bản 1.2.0 – truy xuất, chất lượng câu trả lời (Luồng A): tìm kiếm khớp cả khi gõ không dấu, mở rộng chữ viết tắt theo từ điển thuật ngữ; gộp đoạn cùng mục và đưa nguyên mục (hoặc đoạn lân cận) cho mô hình; bảng dài giữ dòng tiêu đề ở mọi đoạn; giới hạn số mục mỗi tài liệu; ngưỡng reranker tương đối; câu hỏi nhắc lại sau nguồn; phát hiện câu trả lời bị cắt do hết token; Verifier kiểm tra bám nguồn từng câu (tự sửa trích dẫn lệch, bổ sung trích dẫn thiếu, đánh dấu câu không có trong nguồn). Tham số và cách tinh chỉnh: `docs/tinh-chinh-truy-xuat.md`; chẩn đoán: `python -m tools.search_debug "<câu hỏi>"`. Dữ liệu đã nạp trước 1.2.0 cần lập chỉ mục lại (`run_stack.py --real --reindex` hoặc `tools.reindex`).

- Bản 1.1.6 – giao diện: trò chuyện là màn hình chính; các phân hệ là tiện ích mở rộng (trang `/tien-ich`, người dùng tự ghim lên thanh bên; lệnh nhanh `/` trong ô nhập); cây xử lý sự cố chạy ngay trong trò chuyện; nguồn và toàn văn mở ở ngăn bên phải; chế độ sáng/tối; logo đơn vị tại `frontend/public/logo.png` (thay tệp để đổi logo). Danh mục tiện ích, chế độ trả lời và câu hỏi gợi ý khai báo tại `frontend/src/extensions.js`.
- Bản 1.1.6 – Luồng B: câu dẫn và vị trí trích dẫn (“Khoản 2 Điều 5 Quyết định số …”) do chương trình tạo từ cấu trúc văn bản, không gọi mô hình; phần diễn giải chỉ sinh khi người dùng bấm “Giải thích ngắn gọn” (đặt `EXACT_LLM_INTERPRET=true` để sinh ngay như trước). Luồng A giới hạn độ dài câu trả lời bằng `ANSWER_MAX_TOKENS` (chế độ `--real`: 450).

- Bản 1.1.4: các điểm cuối nội bộ (`exact/kb/*`, `search/index`, `search/docs/*`) chỉ nhận lời gọi có danh tính dịch vụ ký HMAC (`x-service`) và không được gateway chuyển tiếp; gateway từ chối khởi động với `AUTH_MODE=dev` nếu thiếu `DEV_AUTH_ALLOWED=true`. Khóa HMAC vẫn dùng chung cho mọi dịch vụ (đề xuất AT1 trong báo cáo rà soát).

- Văn bản bảng mã **VNI** được phát hiện và cảnh báo, chưa tự chuyển đổi; **TCVN3** được tự chuyển (chữ hoa có dấu dùng font `.VnTimeH` cần kiểm tra lại khi duyệt).
- Mã định danh mục tự sinh (với tiêu đề chưa gắn `<!-- id -->`) có thể thay đổi khi sửa văn bản – nên dùng “Xem trước mã định danh” khi duyệt Luồng B để chèn mã tường minh.
- Số người dùng đồng thời phụ thuộc phần cứng; cần đo tại Mốc 1 (`LLM_MAIN_PARALLEL`, `LLM_MAIN_CTX`, `LLM_MAIN_THREADS`).
- Các tên/phiên bản ảnh container trong `.env.example` cần được kiểm tra và ghim digest tại thời điểm đóng gói (`bundle/images.lock`).
- Ảnh docling-serve CPU đóng gói sẵn trọng số; cần xác nhận mô hình OCR tiếng Việt (EasyOCR `vi`) có sẵn trong ảnh, nếu không chuyển `DOCLING_OCR_ENGINE=tesseract` với gói `vie`.
