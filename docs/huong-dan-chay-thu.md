# Hướng dẫn chạy thử AI Local 1.1.2 trong VS Code

Ngày 15/11/2026

## 1. Mục đích và tổng quan

Tài liệu hướng dẫn chạy thử mã nguồn AI Local 1.1.2 trên máy phát triển bằng VS Code, không cần mô hình LLM thật. Kết quả cần đạt: 22/22 bài kiểm thử tự động đạt và đăng nhập, thao tác được trên giao diện web.

Ở chế độ chạy thử, một máy chủ mô hình giả lập (`mock_llm.py`) thay cho LLM, embedding và reranker. Câu trả lời của mô hình giả lập không có giá trị nội dung. Mục đích của bước chạy thử là kiểm tra luồng xử lý, phân quyền, cơ sở dữ liệu, hàng đợi và giao diện, không phải chất lượng câu trả lời.

**Danh mục viết tắt**

| Viết tắt | Nghĩa |
| --- | --- |
| API | Giao diện lập trình ứng dụng |
| CSDL | Cơ sở dữ liệu |
| FTS | Tìm kiếm toàn văn (Full-Text Search) |
| LLM | Mô hình ngôn ngữ lớn |
| KB | Kho văn bản chuẩn (Markdown, quản lý bằng Git) |
| venv | Môi trường Python riêng của dự án (thư mục `.venv`) |
| Task | Tác vụ VS Code, chạy qua *Terminal › Run Task…* |

**Trình tự chung:** chuẩn bị máy (mục 2), sau đó thực hiện 5 tác vụ theo thứ tự (mục 3), kiểm tra thủ công trên giao diện (mục 4), và dừng hoặc xử lý sự cố (mục 5). Sơ đồ dưới đây thể hiện các thành phần được bật khi chạy thử.

![Môi trường chạy thử](images/moi-truong-chay-thu.png)

Hình 1. Thành phần do từng bước bật lên. Bước 1 và 2 là nền; bước 3 phải đang chạy thì bước 4 và 5 mới hoạt động.

## 2. Chuẩn bị máy

Cài đủ các phần mềm dưới đây trước khi mở dự án. Kiểm tra bằng cách mở terminal mới (sau khi cài) và gõ lệnh ở cột thứ ba.

| Phần mềm | Mục đích | Lệnh kiểm tra | Yêu cầu |
| --- | --- | --- | --- |
| Python 3.12 trở lên | Chạy 8 dịch vụ backend, hàng đợi Celery và bộ kiểm thử | `python --version` | Bắt buộc |
| Git | Dịch vụ tra cứu chính xác (exact) lưu kho văn bản chuẩn bằng Git để có lịch sử phiên bản | `git --version` | Bắt buộc |
| Docker Desktop | Chạy PostgreSQL và Redis dành riêng cho kiểm thử, không phải cài hai phần mềm này vào máy | `docker compose version` | Bắt buộc (hoặc có sẵn PostgreSQL 17, Redis 7) |
| Node.js 20 trở lên | Chạy giao diện web (Vue + Vite) | `node --version` | Cần cho bước 5 |
| pandoc | Xuất báo cáo tổng hợp ra DOCX | `pandoc --version` | Tùy chọn |
| VS Code + tiện ích Python (Microsoft) | Chạy tác vụ, bảng Testing, gỡ lỗi | — | Bắt buộc |

**Lưu ý trên Windows:**

- Khi cài Python, chọn *Add python.exe to PATH*. Nếu gõ `python` mà mở Microsoft Store, hãy tắt bí danh trong *Settings › Apps › Advanced app settings › App execution aliases*.
- Docker Desktop phải đang chạy (biểu tượng cá voi ở khay hệ thống chuyển sang trạng thái *running*) trước bước 2.
- Sau khi cài phần mềm, đóng và mở lại VS Code để terminal nhận PATH mới.

**Các cổng sẽ sử dụng** (phải còn trống): 5173 (giao diện), 8100–8107 (8 dịch vụ), 9000 (mô hình giả lập), 55432 (PostgreSQL), 56379 (Redis). Hai cổng cuối được chọn khác cổng mặc định để không đụng PostgreSQL hoặc Redis đã có trên máy.

**Mở dự án:** giải nén `ai-local-1.1.2.zip`, vào VS Code chọn *File › Open Folder* và chọn thư mục `ai-local` (thư mục chứa `backend`, `frontend`, `.vscode`). Phải mở đúng thư mục này vì các tác vụ trong `.vscode/tasks.json` tính đường dẫn từ đó. Nếu VS Code hỏi *Do you trust the authors*, chọn *Yes* để cho phép chạy tác vụ.

## 3. Các bước chạy thử

Mọi tác vụ mở bằng **Terminal › Run Task…** (hoặc Ctrl+Shift+P, gõ *Tasks: Run Task*), rồi chọn tên tác vụ. Mỗi tác vụ mở một ô terminal riêng ở bảng dưới. Bước 1 và 2 chỉ làm lần đầu; các lần sau bắt đầu từ bước 3 (Docker Desktop vẫn phải đang chạy).

### Bước 1. Tạo môi trường Python

**Thao tác:**

1. Chạy tác vụ **"1. Tạo môi trường Python (.venv)"**. Chờ đến khi terminal báo `Successfully installed …` (khoảng 3–10 phút, tùy tốc độ mạng).
2. Nhấn Ctrl+Shift+P, gõ *Python: Select Interpreter*, chọn mục có đường dẫn `.venv` (Windows: `.venv\Scripts\python.exe`).

**Lệnh tương đương trong terminal** (mở bằng *Terminal › New Terminal*, thư mục hiện hành là gốc dự án):

```powershell
# Windows PowerShell
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
.venv\Scripts\python --version

# (Tùy chọn) kích hoạt .venv để gõ "python" thay cho ".venv\Scripts\python".
# Nếu báo "running scripts is disabled", chạy một lần lệnh Set-ExecutionPolicy bên dưới.
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.venv\Scripts\Activate.ps1
```

```bash
# Linux / macOS
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
source .venv/bin/activate        # (tùy chọn) kích hoạt
```

Khi đã kích hoạt, dấu nhắc lệnh có tiền tố `(.venv)`. Các lệnh `python` ở những bước sau trong tài liệu này đều hiểu là Python của `.venv`.

**Mục đích:** tạo thư mục `.venv` chứa bản Python riêng của dự án và cài đúng phiên bản các thư viện đã ghim trong `backend/requirements-dev.txt` (FastAPI, SQLAlchemy, Celery, Qdrant client, pytest…). Thư viện cài vào `.venv` nên không ảnh hưởng các dự án Python khác trên máy. Chọn interpreter ở thao tác 2 để VS Code hiểu mã nguồn (gợi ý, báo lỗi) và để bảng Testing dùng đúng môi trường này.

**Kết quả đúng:** có thư mục `.venv` ở gốc dự án; thanh trạng thái dưới cùng VS Code hiển `3.12.x ('.venv')` hoặc tương tự.

**Lỗi thường gặp:** `python: command not found` → Python chưa có trong PATH (xem mục 2). Lỗi tải thư viện → máy không ra được Internet hoặc cần khai báo proxy cho pip (`pip config set global.proxy http://…`).

### Bước 2. Bật PostgreSQL và Redis thử nghiệm

**Thao tác:** chạy tác vụ **"2. Bật PostgreSQL + Redis thử nghiệm (Docker)"**. Tác vụ chạy lệnh dưới đây tại thư mục gốc dự án; có thể gõ trực tiếp trong terminal (PowerShell và bash giống nhau). Tham số `--wait` giữ lệnh chờ đến khi cả hai container báo *healthy*.

```bash
cd ai-local
docker compose -f docker-compose.test.yml up -d --wait
```

**Cấu hình Docker Desktop (làm một lần):**

1. *Settings › General*: trên Windows giữ chọn *Use the WSL 2 based engine* (mặc định). *Settings › Resources*: không cần điều chỉnh, mức mặc định đủ cho hai container này.
2. Máy ra Internet qua proxy: khai báo tại *Settings › Resources › Proxies*, bấm *Apply & restart*.
3. Máy trong mạng nội bộ, không ra Internet: tải image trên máy có Internet, chép tệp `.tar` sang rồi nạp vào Docker Desktop:

```bash
# Trên máy có Internet
docker pull postgres:17-bookworm
docker pull redis:7.4-bookworm
docker save -o ai-test-images.tar postgres:17-bookworm redis:7.4-bookworm

# Trên máy nội bộ (sau khi chép tệp sang)
docker load -i ai-test-images.tar
docker images        # phải thấy postgres 17-bookworm và redis 7.4-bookworm
```

**Nội dung tệp cấu hình `docker-compose.test.yml`** (ở gốc dự án, bản 1.1.2):

```yaml
name: ai-local-test
services:
  postgres:
    image: postgres:17-bookworm
    container_name: ai-test-postgres
    environment:
      POSTGRES_USER: ai          # tài khoản quản trị CSDL thử nghiệm
      POSTGRES_PASSWORD: ai      # mật khẩu thử nghiệm – không dùng cho vận hành
      POSTGRES_DB: ai            # CSDL mặc định; ai_exact_test do bộ kiểm thử tự tạo
      TZ: Asia/Ho_Chi_Minh
    ports: ["127.0.0.1:55432:5432"]
    volumes: ["pgtest:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ai -d ai"]
      interval: 3s
      timeout: 3s
      retries: 20
    restart: unless-stopped
  redis:
    image: redis:7.4-bookworm
    container_name: ai-test-redis
    command: ["redis-server", "--save", "", "--appendonly", "no"]
    ports: ["127.0.0.1:56379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 3s
      timeout: 3s
      retries: 20
    restart: unless-stopped
volumes:
  pgtest: {}
```

| Khóa cấu hình | Ý nghĩa |
| --- | --- |
| `container_name` | Tên cố định `ai-test-postgres`, `ai-test-redis`, dùng trong các lệnh `docker exec` bên dưới và hiển trong Docker Desktop |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Chỉ có tác dụng ở lần tạo volume đầu tiên. Đổi giá trị thì phải xóa volume (`down -v`) và khai báo lại `TEST_DATABASE_URL` |
| `ports: "127.0.0.1:55432:5432"` | Cổng 5432 trong container được mở ra cổng 55432 của máy, chỉ trên địa chỉ nội bộ 127.0.0.1 |
| `volumes: pgtest` | Dữ liệu PostgreSQL lưu trong volume `ai-local-test_pgtest`, còn nguyên khi dừng hoặc xóa container |
| `healthcheck` | Docker tự kiểm tra 3 giây một lần; trạng thái *healthy* nghĩa là đã nhận kết nối |
| `command` của Redis | Tắt ghi dữ liệu Redis xuống đĩa; dữ liệu hàng đợi là tạm thời, không cần giữ |
| `restart: unless-stopped` | Container tự chạy lại khi mở Docker Desktop, trừ khi đã dừng bằng tay |

Ứng dụng kết nối bằng hai chuỗi sau (mặc định trong `run_stack.py`): `postgresql+psycopg://ai:ai@127.0.0.1:55432/ai` và `redis://127.0.0.1:56379/0`.

**Mục đích:**

- **PostgreSQL** lưu toàn bộ dữ liệu nghiệp vụ: tài khoản phiên hội thoại, hồ sơ nạp tài liệu, phiếu kiểm duyệt, nhật ký kiểm toán và chỉ mục tìm kiếm toàn văn của kho văn bản chuẩn.
- **Redis** làm hàng đợi công việc cho Celery (chuyển đổi tài liệu, tổng hợp báo cáo), luồng nhật ký kiểm toán và bộ đếm giới hạn tần suất truy cập.
- Hai dịch vụ chạy trong container, chỉ mở cổng trên `127.0.0.1` (máy khác trong mạng không truy cập được), tài khoản CSDL `ai`/`ai` chỉ dùng cho thử nghiệm.

**Kết quả đúng:** lệnh `up -d --wait` kết thúc với hai dòng `Container ai-test-postgres Healthy` và `Container ai-test-redis Healthy`. Trong Docker Desktop, tab *Containers* có nhóm `ai-local-test` gồm hai container trạng thái *Running*; bấm vào từng container, tab *Logs* có dòng `database system is ready to accept connections` (PostgreSQL) và `Ready to accept connections` (Redis). Tab *Exec* của container cho phép gõ lệnh trực tiếp bên trong.

**Kiểm tra bằng lệnh** (PowerShell hoặc bash):

```bash
# 1. Trạng thái hai container – cột STATUS phải có "(healthy)"
docker compose -f docker-compose.test.yml ps

# 2. PostgreSQL trả lời được truy vấn – kết quả: PostgreSQL 17.x ...
docker exec ai-test-postgres psql -U ai -d ai -c "SELECT version();"

# 3. Extension pg_trgm (tìm gần đúng) có sẵn – kết quả: pg_trgm | 1.6
docker exec ai-test-postgres psql -U ai -d ai -c "SELECT name, default_version FROM pg_available_extensions WHERE name='pg_trgm';"

# 4. Redis trả lời – kết quả: PONG
docker exec ai-test-redis redis-cli ping
```

**Kiểm tra tổng hợp bằng tác vụ "0. Kiểm tra môi trường"** (sau bước 1 và 2). Tác vụ chạy `backend/tests/check_env.py`, kiểm tra phần mềm, container, kết nối CSDL từ Python và các cổng. Kết quả đúng có dạng:

```text
== Phần mềm ==
[ĐẠT ] Python >= 3.12                     3.12.8
[ĐẠT ] Git                                git version 2.47.1.windows.1
[ĐẠT ] Docker Compose                     Docker Compose version v2.31.0
[ĐẠT ] Node.js >= 20 (giao diện)          v22.12.0
[ĐẠT ] npm (giao diện)                    10.9.0
[THIẾU] pandoc (xuất DOCX)                 không tìm thấy trong PATH
== Docker ==
[ĐẠT ] Docker Engine đang chạy
[ĐẠT ] Container ai-test-postgres         Up 2 minutes (healthy)
[ĐẠT ] Container ai-test-redis            Up 2 minutes (healthy)
== PostgreSQL / Redis ==
[ĐẠT ] PostgreSQL                         17.x (127.0.0.1:55432/ai)
[ĐẠT ] Extension pg_trgm có sẵn
[ĐẠT ] Redis                              redis://127.0.0.1:56379/0
== Cổng của hệ thống thử nghiệm ==
[ĐẠT ] Cổng 5173, 8100-8107, 9000         còn trống

Kết luận: ĐẠT – có thể chạy bước 3.
```

Phiên bản trên máy có thể khác ví dụ. Mục *THIẾU* là tùy chọn; mục *LỖI* phải xử lý trước khi sang bước 3.

**Lỗi thường gặp:** `error during connect` hoặc `Cannot connect to the Docker daemon` → Docker Desktop chưa chạy. `port is already allocated` → cổng 55432 hoặc 56379 đang bị chương trình khác dùng.

**Không dùng Docker:** nếu máy đã có PostgreSQL 17 và Redis 7, bỏ qua bước này và đặt hai biến môi trường trước bước 3, ví dụ `TEST_DATABASE_URL=postgresql+psycopg://user:matkhau@localhost:5432/ai` và `TEST_REDIS_URL=redis://localhost:6379/0`. Tài khoản PostgreSQL cần quyền tạo CSDL và tạo extension `pg_trgm`.

**Kết nối bằng công cụ quản trị CSDL (tùy chọn):** khai báo trong pgAdmin, DBeaver hoặc tiện ích PostgreSQL của VS Code.

| Tham số | PostgreSQL | Redis |
| --- | --- | --- |
| Host | localhost | localhost |
| Port | 55432 | 56379 |
| CSDL | ai (và ai\_exact\_test do kiểm thử tạo) | 0 |
| Tài khoản / mật khẩu | ai / ai | không có |
| SSL | tắt | tắt |

**Xem dữ liệu sau khi chạy kiểm thử** (kết quả mẫu lấy từ lần chạy 22/22 đạt):

```bash
# Mở phiên psql tương tác bên trong container (gõ \q để thoát)
docker exec -it ai-test-postgres psql -U ai -d ai
```

```sql
\dt
-- 11 bảng: audit_log, exact_index_state, exact_section, ing_document, ing_job,
--           orc_conversation, orc_feedback, orc_message, sum_job, sup_session, sup_ticket

SELECT doc_id, count(*) AS so_muc FROM exact_section GROUP BY doc_id ORDER BY 1;
--   doc_id   | so_muc
-- HD-03-2026 |      3
-- QD-15-2026 |     15
-- QD-20-2026 |      5      (văn bản do bài kiểm thử nạp và duyệt 2 cấp)

SELECT status, count(*) FROM ing_job GROUP BY 1;   -- cho_duyet / da_duyet
SELECT count(*) FROM audit_log;                    -- số bản ghi nhật ký kiểm toán
```

```bash
# Redis: số sự kiện trong luồng kiểm toán, danh sách khóa hàng đợi Celery
docker exec ai-test-redis redis-cli XLEN audit
docker exec ai-test-redis redis-cli --scan --pattern "_kombu*"
```

**Dừng, xóa container và dữ liệu:**

```bash
docker compose -f docker-compose.test.yml stop       # dừng, giữ dữ liệu (tác vụ "2b")
docker compose -f docker-compose.test.yml start      # chạy lại
docker compose -f docker-compose.test.yml down       # xóa container, giữ volume dữ liệu
docker compose -f docker-compose.test.yml down -v    # xóa cả volume: CSDL trống hoàn toàn
docker compose -f docker-compose.test.yml logs -f postgres   # theo dõi nhật ký PostgreSQL
```

### Bước 3. Chạy hệ thống thử nghiệm

**Thao tác:** chạy tác vụ **"3. Chạy hệ thống thử nghiệm"**. Chờ đến khi terminal in dòng **"Hệ thống thử nghiệm đã sẵn sàng"** (thường 10–30 giây). Giữ nguyên ô terminal này trong suốt quá trình thử.

**Mục đích:** trình `backend/tests/run_stack.py` thay cho Docker Compose vận hành, bật toàn bộ phần backend ngay trên máy để có thể sửa mã và chạy lại nhanh. Trình này lần lượt:

1. Kiểm tra kết nối PostgreSQL, Redis và lệnh `git`; cảnh báo nếu thiếu `pandoc`.
2. Bật máy chủ mô hình giả lập (cổng 9000) thay cho llama-server.
3. Bật 8 dịch vụ: gateway 8100, orchestrator 8101, search 8102, exact 8103, ingest 8104, summary 8105, support 8106, audit 8107.
4. Bật Celery worker xử lý hàng đợi `ingest` và `summary` (Windows chạy chế độ `solo`).
5. Gọi `/api/health` của gateway cho đến khi mọi dịch vụ báo `ok` (tối đa 90 giây).

Các tham số chạy thử được đặt sẵn: đăng nhập chế độ `dev` (không cần Keycloak), Qdrant chạy nhúng trong tiến trình (không cần máy chủ Qdrant), docling tắt (dùng MarkItDown). Dữ liệu chạy thử nằm trong thư mục `.test-run` ở gốc dự án.

**Chọn "3" hay "3b":** tác vụ **"3b. … (xóa dữ liệu cũ)"** xóa và tạo lại CSDL, xóa thư mục `.test-run` rồi mới chạy. Dùng "3b" khi muốn chạy kiểm thử từ trạng thái sạch hoặc khi dữ liệu lần trước bị hỏng; dùng "3" để giữ lại dữ liệu đã nạp.

**Lệnh tương đương trong terminal:**

```powershell
# Windows PowerShell (đã kích hoạt .venv)
cd backend
python tests\run_stack.py            # giữ dữ liệu cũ
python tests\run_stack.py --reset    # xóa dữ liệu cũ rồi chạy (tương đương tác vụ 3b)

# Dùng PostgreSQL/Redis khác (không dùng Docker): khai báo trước khi chạy
$env:TEST_DATABASE_URL = "postgresql+psycopg://user:matkhau@localhost:5432/ai"
$env:TEST_REDIS_URL    = "redis://localhost:6379/0"
```

```bash
# Linux / macOS
cd backend
python tests/run_stack.py --reset
export TEST_DATABASE_URL=postgresql+psycopg://user:matkhau@localhost:5432/ai   # nếu không dùng Docker
```

Kết quả thực tế của lệnh `run_stack.py --reset` (đường dẫn nhật ký thay đổi theo máy):

```text
Khởi động dịch vụ… (nhật ký: C:\ai-local\.test-run\logs)
Hệ thống thử nghiệm đã sẵn sàng:
  API Gateway : http://localhost:8100/api/docs
  Giao diện   : cd frontend && npm run dev  → http://localhost:5173 (tài khoản thử nghiệm: canbo, kiemduyet1, kiemduyet2, quantri)
  Kiểm thử    : cd backend && python -m pytest
Nhấn Ctrl+C để dừng.
```

**Kiểm tra nhanh từ terminal thứ hai** (trên Windows dùng `curl.exe`, vì `curl` trong PowerShell là bí danh của lệnh khác):

```bash
curl.exe http://localhost:8100/api/health
```

```json
{"status":"ok","services":{"chat":"ok","search":"ok","exact":"ok","ingest":"ok","summary":"ok","support":"ok","audit":"ok"}}
```

Một dịch vụ báo khác `ok` thì xem tệp nhật ký cùng tên, ví dụ `Get-Content ..\.test-run\logs\exact.log -Tail 50` (PowerShell) hoặc `tail -n 50 ../.test-run/logs/exact.log` (bash).

**Kết quả đúng:** terminal in địa chỉ API Gateway `http://localhost:8100/api/docs`; mở địa chỉ này bằng trình duyệt thấy trang tài liệu API (Swagger).

**Lỗi thường gặp:**

| Thông báo | Nguyên nhân | Cách xử lý |
| --- | --- | --- |
| `[LỖI] Không kết nối được PostgreSQL` | Chưa làm bước 2 hoặc container đã dừng | Chạy lại bước 2 |
| `[LỖI] Không kết nối được Redis` | Như trên | Chạy lại bước 2 |
| `[LỖI] Chưa cài git` | Thiếu Git trong PATH | Cài Git, mở lại VS Code |
| `[LỖI] Hệ thống không sẵn sàng: {'status': 'dead', 'dead': ['exact']}` | Một dịch vụ dừng ngay khi khởi động | Mở `.test-run/logs/exact.log` (tên tệp theo dịch vụ bị báo) để xem lỗi |
| `{'status': 'timeout'}` | Dịch vụ khởi động quá 90 giây hoặc cổng bị chiếm | Xem nhật ký; kiểm tra cổng 8100–8107, 9000 còn trống |
| `[CẢNH BÁO] Chưa cài pandoc` | Thiếu pandoc | Không ảnh hưởng kiểm thử; cài pandoc nếu cần xuất DOCX |
| `[CẢNH BÁO] Chưa chạy dịch vụ OCR (docling-serve)` | Chưa bật container OCR | Chỉ cần khi nạp PDF scan, ảnh – xem mục 3.1 dưới |

#### 3.1. Bật OCR để nạp PDF scan, ảnh (tùy chọn)

**Mục đích:** PDF có lớp văn bản và DOCX, XLSX, PPTX được chuyển đổi ngay trong tiến trình. PDF scan và ảnh cần dịch vụ docling-serve (bố cục, bảng, OCR tiếng Việt bằng EasyOCR). Nếu không bật, khi nạp sẽ báo “PDF không có lớp văn bản, cần OCR”.

```powershell
# 1. Bật container OCR (lần đầu tải ảnh vài GB và mô hình OCR, mất 10–30 phút)
docker compose -f docker-compose.test.yml --profile ocr up -d

# 2. Kiểm tra: phải trả về {"status":"ok"}
curl.exe http://127.0.0.1:5001/health

# 3. Khởi động lại hệ thống thử nghiệm (không cần --reset)
python tests/run_stack.py --real
```

Khi khởi động, `run_stack.py` tự phát hiện docling-serve ở cổng 5001 và in dòng “OCR (docling-serve): đang chạy”. Đổi địa chỉ bằng biến `TEST_DOCLING_URL`; đặt `TEST_DOCLING_URL=off` để tắt.

Lưu ý trên laptop: OCR chạy bằng CPU, mỗi trang mất khoảng vài giây đến vài chục giây; container cần thêm khoảng 4 GB RAM. Khi đang chạy mô hình 9B, nên thử với tệp ít trang. Nếu docling-serve lỗi hoặc quá thời gian, thông báo lỗi của tác vụ nạp ghi rõ nguyên nhân (ví dụ `ReadTimeout`); mở `.test-run-that/logs/worker.log` để xem chi tiết.

### Bước 4. Chạy kiểm thử tự động

**Thao tác:** khi bước 3 đang chạy, chạy tác vụ **"4. Chạy toàn bộ kiểm thử"** (VS Code mở terminal thứ hai). Có thể thay bằng bảng **Testing** (biểu tượng bình thí nghiệm ở thanh bên trái), bấm nút chạy ở từng bài hoặc toàn bộ.

**Mục đích:** kiểm tra tự động các yêu cầu thiết kế thay cho thao tác tay. Lần đầu, bộ kiểm thử tự nạp dữ liệu mẫu từ thư mục `kb-seed`: 2 văn bản vào kho văn bản chuẩn (Luồng B, có duyệt hai cấp) và 4 tài liệu vào kho tra cứu (Luồng A). Các lần sau, nếu kho đã có dữ liệu thì không nạp lại.

| Tệp kiểm thử | Số bài | Nội dung kiểm tra | Cần bước 3 |
| --- | --- | --- | --- |
| `test_unit.py` | 5 | Tách điều khoản Markdown nguyên văn, gắn ID mục, chia đoạn, chuẩn hóa tiếng Việt, bộ kiểm tra (verifier) | Không |
| `test_exact_pg.py` | 5 | Tìm kiếm toàn văn trên PostgreSQL: không dấu, cụm từ, số hiệu văn bản, tìm gần đúng, cập nhật chỉ mục tăng dần. Dùng CSDL riêng `ai_exact_test` | Không (chỉ cần bước 2) |
| `test_e2e.py` | 12 | Toàn trình qua gateway: đăng nhập, Luồng A có trích dẫn, Luồng B trích nguyên văn và loại số liệu bịa, định tuyến, cây hỗ trợ kỹ thuật, tổng hợp báo cáo, nạp DOCX và TCVN3, phân quyền theo đơn vị, duyệt hai người khác nhau, chế độ tác tử, MCP, nhật ký kiểm toán | Có |

**Lệnh tương đương trong terminal** (terminal thứ hai, đã kích hoạt `.venv`, thư mục `backend`):

```bash
cd backend
python -m pytest                                   # toàn bộ 22 bài
python -m pytest -o addopts="" -v                  # liệt kê tên từng bài và kết quả
python -m pytest tests/test_unit.py                # một tệp (không cần bước 3)
python -m pytest tests/test_exact_pg.py            # một tệp (chỉ cần bước 2)
python -m pytest tests/test_e2e.py::test_auth      # một bài
python -m pytest -k "luong_b"                      # các bài có tên chứa "luong_b"
python -m pytest -x                                # dừng ở bài hỏng đầu tiên
python -m pytest --lf                              # chỉ chạy lại các bài hỏng lần trước
```

Kết quả thực tế của `python -m pytest -o addopts="" -v` (lược bỏ phần trăm tiến độ cuối dòng):

```text
tests/test_e2e.py::test_auth PASSED
tests/test_e2e.py::test_catalog_and_versions PASSED
tests/test_e2e.py::test_luong_b_direct_reference PASSED
tests/test_e2e.py::test_luong_b_fts_and_verifier_drops_invented_numbers PASSED
tests/test_e2e.py::test_luong_a_stream_citations PASSED
tests/test_e2e.py::test_router_and_support_tree PASSED
tests/test_e2e.py::test_summary_job_numbers_computed_by_code PASSED
tests/test_e2e.py::test_ingest_docx_tcvn3_and_acl PASSED
tests/test_e2e.py::test_luong_b_requires_two_distinct_reviewers PASSED
tests/test_e2e.py::test_agent_mode_and_tools PASSED
tests/test_e2e.py::test_mcp_endpoint PASSED
tests/test_e2e.py::test_feedback_conversation_and_audit PASSED
tests/test_exact_pg.py::test_accent_insensitive_and_ranking PASSED
tests/test_exact_pg.py::test_phrase_and_identifier_tokens PASSED
tests/test_exact_pg.py::test_or_and_fuzzy_fallback PASSED
tests/test_exact_pg.py::test_doc_filter PASSED
tests/test_exact_pg.py::test_restart_skips_rebuild_and_incremental_commit PASSED
tests/test_unit.py::test_sections_verbatim PASSED
tests/test_unit.py::test_normalize_and_insert_ids PASSED
tests/test_unit.py::test_chunking_breadcrumb PASSED
tests/test_unit.py::test_text_utils PASSED
tests/test_unit.py::test_verifier PASSED
============================== 22 passed in 9.93s ==============================
```

Lần chạy đầu sau `--reset` mất lâu hơn (lần thử trên máy phát triển: 26 giây) vì phải nạp dữ liệu mẫu.

**Kết quả đúng:** dòng cuối terminal báo **`22 passed`** (khoảng 30–90 giây). Bài `test_exact_pg.py` báo *skipped* nghĩa là không kết nối được PostgreSQL.

**Lỗi thường gặp:** hàng loạt lỗi `ConnectError` trong `test_e2e.py` → bước 3 chưa sẵn sàng hoặc đã dừng. Một bài riêng lẻ báo *FAILED* → xem dòng `AssertionError` trong terminal và nhật ký dịch vụ liên quan trong `.test-run/logs`.

**Gỡ lỗi từng bước:** mở tệp kiểm thử, đặt điểm dừng (F9), vào *Run and Debug* chọn cấu hình chạy bài kiểm thử đang mở và bấm F5.

### Bước 5. Chạy giao diện web

**Thao tác:** khi bước 3 đang chạy, chạy tác vụ **"5. Chạy giao diện (Vite)"**. Khi terminal hiện `Local: http://localhost:5173/`, mở địa chỉ này bằng trình duyệt.

**Lệnh tương đương trong terminal** (terminal thứ ba):

```bash
cd frontend
npm install      # lần đầu, hoặc khi package.json thay đổi
npm run dev      # máy chủ phát triển tại http://localhost:5173, Ctrl+C để dừng
```

```text
  VITE v8.x  ready in ... ms

  ➜  Local:   http://localhost:5173/
```

**Mục đích:** lần đầu, `npm install` tải thư viện giao diện vào `frontend/node_modules`; sau đó `npm run dev` chạy máy chủ phát triển Vite. Vite chuyển mọi yêu cầu `/api` sang gateway ở cổng 8100, nên giao diện làm việc với đúng hệ thống đang chạy ở bước 3. Khi sửa tệp `.vue`, trang tự cập nhật.

**Kết quả đúng:** trang đăng nhập hiện danh sách tài khoản thử nghiệm. Chọn tài khoản để vào hệ thống, không cần mật khẩu (chỉ đúng ở chế độ `dev`).

| Tài khoản | Vai trò | Đơn vị | Dùng để thử |
| --- | --- | --- | --- |
| `canbo` | Người dùng | phong-ky-thuat | Hỏi đáp, tra cứu, tổng hợp, hỗ trợ kỹ thuật |
| `kiemduyet1` | Người dùng, kiểm duyệt | phong-ky-thuat | Nạp tài liệu, duyệt cấp 1 |
| `kiemduyet2` | Người dùng, kiểm duyệt | van-phong | Duyệt cấp 2 (phải khác người duyệt cấp 1) |
| `quantri` | Quản trị | tất cả đơn vị | Trang quản trị, nhật ký kiểm toán, thống kê |

**Lỗi thường gặp:** `npm: command not found` → chưa cài Node.js. Trang mở được nhưng báo lỗi kết nối hoặc 502 → bước 3 đã dừng.

## 4. Kiểm tra thủ công trên giao diện

Sau khi bước 4 đạt (dữ liệu mẫu đã được nạp), thực hiện các kịch bản dưới đây để kiểm tra từng phân hệ bằng mắt. Nội dung câu trả lời do mô hình giả lập sinh ra nên không đánh giá; chỉ kiểm tra luồng xử lý và hiển thị. Riêng phần trích nguyên văn của Luồng B do mã chèn vào, nên phải trùng từng chữ với văn bản gốc.

| TT | Trang (tài khoản) | Thao tác | Kết quả cần thấy |
| --- | --- | --- | --- |
| 1 | Danh mục tài liệu (`canbo`) | Mở trang | Có 2 văn bản chuẩn (QD-15-2026, HD-03-2026) và các tài liệu tra cứu thuộc đơn vị được xem |
| 2 | Tra cứu chính xác (`canbo`) | Gõ `QD-15-2026.D5` hoặc `thoi han su dung` (không dấu) | Hiện Điều 5 "Thời hạn sử dụng" kèm mã mục; nội dung trùng văn bản gốc trong `kb-seed/van-ban` |
| 3 | Hỏi đáp (`canbo`) | Hỏi: "Theo QD-15-2026, thời hạn sử dụng USB Token là bao lâu?" | Câu trả lời hiện dần từng đoạn, có trích dẫn mã mục; bấm trích dẫn xem được nguyên văn |
| 4 | Hỏi đáp (`canbo`) | Hỏi một câu về nội dung báo cáo tuần hoặc sự cố mất mạng | Câu trả lời theo Luồng A, có danh sách nguồn tài liệu |
| 5 | Hỗ trợ kỹ thuật (`canbo`) | Hỏi "USB Token cắm vào máy tính không nhận, đèn không sáng"; sau đó hỏi "bị lỗi rồi" | Câu thứ nhất: kế hoạch 5 bước hiện trực tiếp, các bước xử lý lấy từ tài liệu hướng dẫn, có nút tạo phiếu hỗ trợ. Câu thứ hai: thẻ hỏi lại thiết bị, bấm một lựa chọn thì trả lời tiếp |
| 6 | Tổng hợp (`canbo`) | Kéo 2 tệp báo cáo vào ô trò chuyện, gõ "tổng hợp báo cáo chung", gửi | Thẻ tác vụ hiện tiến trình từng bước; xong mở "Xem kết quả": báo cáo, bảng số liệu do chương trình tính, xuất DOCX |
| 6a | Phân tích văn bản (`canbo`) | Đính kèm một văn bản (kế hoạch, công văn) vào ô trò chuyện, gửi | Thẻ tác vụ phân tích 7 bước; kết quả có tóm tắt, vấn đề theo tiêu chí ngành, nhiệm vụ – thời hạn, đối chiếu văn bản viện dẫn |
| 6b | Soạn thảo (`canbo`) | Gõ "Soạn tờ trình về việc cấp bổ sung thiết bị lưu khóa bí mật" | Tác vụ dừng ở "Chờ xác nhận": sửa dàn ý, gắn căn cứ, xác nhận; nhận bản sạch và bản kèm căn cứ |
| 6c | Bảo vệ ATTT (`canbo`) | Gõ "mã PIN của tôi là 12345678" | Bị chặn, hiện hướng dẫn; mở lại hội thoại không thấy giá trị PIN |
| 6d | Giám định dữ liệu, Giám sát (`kiemduyet1`, `quantri`) | Bấm "Giám định ngay"; mở Giám sát hệ thống | Lượt giám định chạy từng bước, danh sách phát hiện; trang giám sát có chỉ số, biểu đồ, nhật ký hệ thống |
| 7 | Nạp dữ liệu (`kiemduyet1`) | Tải lên một tệp DOCX hoặc Markdown, chọn Luồng B | Tệp được chuyển sang Markdown, có điểm chất lượng; chờ duyệt |
| 8 | Kiểm duyệt (`kiemduyet1`, rồi `kiemduyet2`) | Duyệt cấp 1 bằng `kiemduyet1`, đăng xuất, duyệt cấp 2 bằng `kiemduyet2` | Chỉ sau khi hai người khác nhau duyệt, văn bản mới vào kho văn bản chuẩn; một người duyệt cả hai cấp bị từ chối |
| 9 | Giám sát hệ thống › Kiểm toán (`quantri`) | Xem nhật ký kiểm toán và bấm kiểm tra chuỗi băm | Các thao tác ở kịch bản 1–8 có trong nhật ký; chuỗi băm báo toàn vẹn |
| 10 | Trang quản trị (`canbo`) | Gõ trực tiếp `/quan-tri` trên thanh địa chỉ | Bị chuyển về trang Hỏi đáp (không có quyền) |

**Kiểm tra qua API bằng dòng lệnh.** Danh sách API xem tại `http://localhost:8100/api/docs`. Mọi yêu cầu gửi kèm token thử nghiệm dạng `dev-<tên tài khoản>`. Kết quả dưới đây lấy từ lần chạy thử thực tế.

```powershell
# Windows PowerShell
$H = @{ Authorization = "Bearer dev-canbo" }

# 1. Thông tin tài khoản đang đăng nhập
Invoke-RestMethod http://localhost:8100/api/me -Headers $H

# 2. Tra cứu chính xác (tìm không dấu)
Invoke-RestMethod http://localhost:8100/api/exact/search -Method Post -Headers $H `
  -ContentType "application/json" -Body '{"query":"thoi han su dung"}' |
  Select-Object -ExpandProperty results | Select-Object section_id, heading, match

# 3. Lấy nguyên văn một mục theo mã
(Invoke-RestMethod http://localhost:8100/api/exact/sections/QD-15-2026.D5 -Headers $H).text

# 4. Tài khoản không có quyền quản trị bị từ chối (kỳ vọng lỗi 403)
Invoke-RestMethod http://localhost:8100/api/audit/verify -Headers $H
```

```bash
# Linux / macOS (Windows: thay curl bằng curl.exe)
curl -H "Authorization: Bearer dev-canbo" http://localhost:8100/api/me
curl -X POST http://localhost:8100/api/exact/search \
  -H "Authorization: Bearer dev-canbo" -H "Content-Type: application/json" \
  -d '{"query":"thoi han su dung"}'
curl -H "Authorization: Bearer dev-canbo" http://localhost:8100/api/exact/sections/QD-15-2026.D5
curl -i -H "Authorization: Bearer dev-canbo" http://localhost:8100/api/audit/verify   # HTTP 403
curl -H "Authorization: Bearer dev-quantri" http://localhost:8100/api/audit/verify    # quản trị: được phép
```

Kết quả của lệnh 1 (tài khoản `canbo`):

```json
{"sub":"dev:dev-canbo","username":"canbo","name":"Nguyễn Văn Cán Bộ","roles":["user"],
 "units":["phong-ky-thuat"],"clearance":0,"effective_clearance":0,"system_max_clearance":1}
```

Kết quả của lệnh 2, kết quả đầu tiên (rút gọn): từ khóa không dấu vẫn tìm đúng Điều 5; `match: "and"` cho biết tìm theo kế hoạch "đủ mọi từ".

```json
{"section_id": "QD-15-2026.D5", "doc_id": "QD-15-2026", "heading": "Điều 5. Thời hạn sử dụng",
 "snippet": "### Điều 5. Thời hạn sử dụng 1. Thiết bị được sử dụng tối đa 05 năm kể từ ngày cấp phát. ...",
 "match": "and"}
```

Kết quả của lệnh kiểm tra chuỗi băm bằng tài khoản `quantri`: `{"ok":true,"checked":163}` (số bản ghi thay đổi theo số thao tác đã làm). Cùng lệnh đó với tài khoản `canbo` trả mã HTTP 403.

## 5. Dừng, chạy lại và xử lý sự cố

**Dừng hệ thống:**

1. Trong terminal của bước 5, nhấn Ctrl+C để dừng giao diện.
2. Trong terminal của bước 3, nhấn Ctrl+C. Trình chạy in "Đang dừng các dịch vụ…" và tắt cả 10 tiến trình. Không đóng ô terminal bằng nút thùng rác trước khi dừng, vì có thể để lại tiến trình chạy ngầm chiếm cổng.
3. Nếu không cần thử tiếp, dừng CSDL thử nghiệm: `docker compose -f docker-compose.test.yml stop`. Dữ liệu vẫn giữ trong volume `pgtest`.

**Chạy lại lần sau:** mở Docker Desktop, chạy bước 2 (để khởi động lại container), bước 3, rồi bước 4 hoặc 5. Không cần làm lại bước 1, trừ khi `requirements-dev.txt` thay đổi.

**Xóa sạch toàn bộ dữ liệu thử nghiệm:** chạy tác vụ "3b" (xóa CSDL và `.test-run`), hoặc xóa hẳn container kèm volume bằng `docker compose -f docker-compose.test.yml down -v`.

**Xử lý sự cố chung:**

| Hiện tượng | Cách xử lý |
| --- | --- |
| Không thấy tác vụ "1. …" đến "5. …" trong Run Task | Mở sai thư mục; mở lại đúng thư mục `ai-local` |
| Bước 3 báo cổng đang dùng sau lần chạy trước | Còn tiến trình cũ. Windows: `netstat -ano \| findstr :8100` rồi `taskkill /PID <số> /F`. Linux: `lsof -i :8100` rồi `kill <số>` |
| Bảng Testing không hiện bài kiểm thử | Chưa chọn interpreter `.venv` (bước 1, thao tác 2); bấm nút *Refresh Tests* |
| Kết quả kiểm thử khác nhau giữa các lần chạy | Dữ liệu cũ ảnh hưởng; chạy "3b" rồi chạy lại bước 4 |
| Tiếng Việt trong terminal Windows bị lỗi hiển thị | Chạy `chcp 65001` trong terminal, hoặc xem nhật ký trong VS Code (tệp ghi UTF-8) |

**Khi cần hỗ trợ:** gửi kèm (1) nội dung terminal của bước báo lỗi, (2) tệp nhật ký tương ứng trong `.test-run/logs` (mỗi dịch vụ một tệp, ví dụ `gateway.log`, `exact.log`, `worker.log`), (3) hệ điều hành và kết quả `python --version`.

## 6. Phụ lục: trình tự lệnh đầy đủ

Trình tự dưới đây tương đương các tác vụ 0–5, dùng khi không chạy qua VS Code. Cần 3 cửa sổ terminal, đều mở tại thư mục gốc `ai-local`.

```powershell
# ===== Terminal 1: chuẩn bị và chạy hệ thống (Windows PowerShell) =====
python -m venv .venv                                              # Bước 1 (lần đầu)
.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
.venv\Scripts\Activate.ps1
docker compose -f docker-compose.test.yml up -d --wait            # Bước 2
python backend\tests\check_env.py                                  # Tác vụ 0: phải "ĐẠT"
cd backend
python tests\run_stack.py --reset                                 # Bước 3: chờ "đã sẵn sàng", giữ cửa sổ

# ===== Terminal 2: kiểm thử =====
.venv\Scripts\Activate.ps1
cd backend
python -m pytest                                                  # Bước 4: "22 passed"

# ===== Terminal 3: giao diện =====
cd frontend
npm install
npm run dev                                                       # Bước 5: http://localhost:5173

# ===== Kết thúc =====
# Ctrl+C ở Terminal 3 và Terminal 1, sau đó:
docker compose -f docker-compose.test.yml stop
```

```bash
# ===== Linux / macOS: cùng trình tự =====
python3 -m venv .venv && .venv/bin/python -m pip install -r backend/requirements-dev.txt
source .venv/bin/activate
docker compose -f docker-compose.test.yml up -d --wait
python backend/tests/check_env.py
cd backend && python tests/run_stack.py --reset          # Terminal 1
cd backend && python -m pytest                           # Terminal 2 (đã source .venv)
cd frontend && npm install && npm run dev                # Terminal 3
```

**Thay đổi trong bản 1.1.2 so với 1.1.1:** `docker-compose.test.yml` có tên container cố định và kiểm tra sức khỏe (dùng được `--wait`); thêm `backend/tests/check_env.py` cùng tác vụ "0. Kiểm tra môi trường" và "2b. Dừng PostgreSQL + Redis"; đầu ra tiếng Việt của `run_stack.py` ép về UTF-8 để không lỗi trên terminal Windows; tài liệu này kèm trong mã nguồn tại `docs/huong-dan-chay-thu.md`.
