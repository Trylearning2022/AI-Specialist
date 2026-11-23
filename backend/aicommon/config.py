"""Cấu hình tập trung, đọc từ biến môi trường (xem .env.example).

Mỗi thuộc tính ứng với một biến môi trường cùng tên viết HOA (ví dụ ``search_top_k`` ↔ ``SEARCH_TOP_K``).
Các tham số đánh dấu ``[TINH CHỈNH]`` ảnh hưởng trực tiếp tới chất lượng hoặc tốc độ trả lời;
hướng dẫn chọn giá trị theo triệu chứng: docs/tinh-chinh-truy-xuat.md.
Tìm nhanh trong mã:  grep -rn "TINH CHỈNH" backend/
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    service_name: str = "ai-local"
    log_level: str = "INFO"

    # ------------------------------------------------------------------ Hạ tầng dữ liệu
    database_url: str = "postgresql+psycopg://ai:ai@postgres:5432/ai"
    redis_url: str = "redis://redis:6379/0"
    qdrant_url: str = "http://qdrant:6333"   # "path:<thư mục>" = Qdrant nhúng (máy dev), ":memory:" = kiểm thử
    qdrant_api_key: str | None = None
    qdrant_collection: str = "tai_lieu"

    # Bảo mật nội bộ: chữ ký HMAC cho ngữ cảnh người dùng truyền giữa các dịch vụ
    internal_secret: str = "doi-gia-tri-nay"
    system_max_clearance: int = 0  # độ mật tối đa hệ thống được phép xử lý (0 = thường)

    # ------------------------------------------------------------------ Mô hình (qua LiteLLM, API tương thích OpenAI)
    llm_base_url: str = "http://llm-gateway:4000/v1"
    llm_api_key: str = "sk-noibo"
    model_main: str = "chinh"   # tên logic mô hình chính (sinh câu trả lời, tổng hợp)
    model_small: str = "nho"    # tên logic mô hình nhỏ (định tuyến, viết lại câu hỏi, chọn mục)
    llm_timeout: float = 300.0
    llm_disable_thinking: bool = False  # True: gửi chat_template_kwargs.enable_thinking=false (Qwen3.x)
    # [TINH CHỈNH] Nhiệt độ khi sinh câu trả lời tra cứu. Thấp (0.0–0.2) = bám nguồn, ít "sáng tác".
    answer_temperature: float = 0.1

    embed_url: str = "http://embed:8080"
    embed_api_key: str | None = None
    embed_dim: int = 0  # 0 = tự dò từ máy chủ embedding
    embed_batch: int = 16
    rerank_url: str | None = "http://rerank:8080"
    # [TINH CHỈNH] Ngưỡng tuyệt đối điểm thô của bge-reranker (logit, khoảng −11…+11).
    # Đoạn dưới ngưỡng bị loại; tăng (−1, 0) nếu nguồn rác lọt vào, giảm (−4) nếu hay bị "không tìm thấy căn cứ".
    rerank_threshold: float = -2.0
    # [TINH CHỈNH] Ngưỡng tương đối: loại đoạn kém đoạn tốt nhất quá N điểm (0 = tắt).
    # Giữ câu trả lời tập trung khi có một nguồn rất khớp và nhiều nguồn khớp yếu.
    rerank_margin: float = 7.0

    # ------------------------------------------------------------------ Đường dẫn dữ liệu
    data_dir: str = "/data"
    kb_dir: str = "/kb"
    kb_git_remote: str | None = None
    skills_dir: str = "/app/skills"
    prompts_dir: str = "/app/prompts"
    glossary_file: str = "/app/glossary/thuat-ngu.md"

    # ------------------------------------------------------------------ Địa chỉ dịch vụ nội bộ
    orchestrator_url: str = "http://orchestrator:8000"
    search_url: str = "http://search:8000"
    exact_url: str = "http://exact:8000"
    ingest_url: str = "http://ingest:8000"
    summary_url: str = "http://summary:8000"
    support_url: str = "http://support:8000"
    audit_url: str = "http://audit:8000"
    docling_url: str | None = "http://docling:5001"
    docling_api_key: str | None = None
    docling_ocr_engine: str = "easyocr"
    docling_ocr_lang: str = "vi,en"
    docling_timeout: float = 900.0
    office_convert_timeout: int = 180   # giây – chuyển .doc/.xls bằng LibreOffice

    # ------------------------------------------------------------------ Tách đoạn (Luồng A) – thay đổi cần lập chỉ mục lại
    # [TINH CHỈNH] Kích thước đoạn tối đa (token ước lượng = số ký tự / 3). Nhỏ → khớp chính xác hơn nhưng
    # dễ mất ngữ cảnh; lớn → đủ ý hơn nhưng vector "loãng". 400–600 phù hợp văn bản hành chính.
    chunk_max_tokens: int = 500
    # Đoạn ngắn hơn ngưỡng này được gộp với đoạn kế tiếp cùng mục cha (tránh đoạn chỉ có tiêu đề).
    chunk_min_tokens: int = 60

    # ------------------------------------------------------------------ Truy xuất (Luồng A)
    # [TINH CHỈNH] Số ứng viên lấy từ mỗi nhánh (vector, BM25) trước khi hợp nhất RRF và xếp hạng lại.
    # Nhiều hơn → ít bỏ sót, nhưng reranker chậm hơn (CPU: 15–25; GPU: 30–50).
    search_candidates: int = 30
    # [TINH CHỈNH] Số MỤC (sau khi gộp các đoạn cùng mục) đưa cho mô hình. CPU: 4–5; GPU: 6–8.
    search_top_k: int = 6
    # [TINH CHỈNH] Mở rộng ngữ cảnh: mục có tổng độ dài ≤ ngưỡng này được đưa NGUYÊN mục (mọi đoạn),
    # mục dài hơn chỉ lấy đoạn trúng ± search_neighbors đoạn liền kề. Khắc phục câu trả lời thiếu bước, thiếu dòng bảng.
    search_section_max_tokens: int = 1200
    search_neighbors: int = 1
    # [TINH CHỈNH] Số mục tối đa lấy từ cùng một tài liệu (đa dạng nguồn); 0 = không giới hạn.
    search_max_per_doc: int = 3
    # Mở rộng truy vấn bằng từ điển thuật ngữ (viết tắt → nghĩa đầy đủ), ví dụ "PKT" → "Phòng Kỹ thuật".
    search_expand_glossary: bool = True

    # ------------------------------------------------------------------ Ngữ cảnh, harness
    ctx_window: int = 16384
    ctx_reserve_output: int = 2048
    # [TINH CHỈNH] Độ dài tối đa câu trả lời Luồng A (token). Quá thấp → câu trả lời bị cắt
    # (hệ thống sẽ cảnh báo); quá cao → chờ lâu trên CPU. CPU: 700–900; GPU: 1024–1500.
    answer_max_tokens: int = 1024
    exact_llm_interpret: bool = False  # Luồng B: sinh diễn giải ngay khi trả lời (mặc định: chỉ khi người dùng yêu cầu)
    # [TINH CHỈNH] Ngân sách token cho phần NGUỒN trong ngữ cảnh. Thời gian xử lý trên CPU tăng gần
    # tuyến tính theo giá trị này (≈ 30–60 token/giây với mô hình 9B). CPU: 3500–5000; GPU: 8000–12000.
    ctx_budget_sources: int = 8000
    ctx_budget_memory: int = 800      # ngân sách cho các lượt hội thoại gần nhất
    agent_max_steps: int = 6
    agent_timeout_s: int = 120

    # ------------------------------------------------------------------ Kiểm chứng (Verifier)
    # True: câu trả lời không có trích dẫn hợp lệ bị thay bằng câu từ chối.
    verify_strict_a: bool = True
    # [TINH CHỈNH] Kiểm tra bám nguồn theo từng câu (độ phủ từ ngữ giữa câu trả lời và nguồn được trích).
    verify_grounding: bool = True
    # Câu có độ phủ với nguồn TỐT NHẤT dưới ngưỡng này bị đánh dấu "không tìm thấy trong nguồn".
    verify_support_min: float = 0.30
    # Câu trích [n] nhưng nguồn n phủ dưới ngưỡng này, trong khi nguồn khác phủ cao hơn rõ rệt
    # (≥ verify_support_fix) → tự sửa chỉ số trích dẫn sang nguồn đúng.
    verify_support_low: float = 0.35
    verify_support_fix: float = 0.60

    # ------------------------------------------------------------------ Gateway
    auth_mode: str = "oidc"  # oidc | dev
    dev_auth_allowed: bool = False  # chế độ dev chỉ chạy khi bật rõ ràng (máy phát triển)
    oidc_issuer: str = "https://ai.noibo.local/auth/realms/ai"
    oidc_jwks_url: str = "http://keycloak:8080/auth/realms/ai/protocol/openid-connect/certs"
    oidc_allowed_azp: str = "portal"
    dev_users_file: str = "/app/config/users.dev.yaml"
    rate_limit_per_min: int = 60
    rate_limit_chat_per_min: int = 15
    max_upload_mb: int = 100

    # ------------------------------------------------------------------ Hỗ trợ kỹ thuật
    support_dir: str = "/app/support"
    ticket_webhook_url: str | None = None

    # ------------------------------------------------------------------ Hồ sơ phần cứng (1.3.0)
    # cpu | gpu. Ảnh hưởng tới mặc định của các chức năng nặng (kiểm tra chéo bằng mô hình, số bước tác tử).
    hardware_profile: str = "cpu"

    # ------------------------------------------------------------------ Hỏi lại làm rõ (1.3.0)
    # [TINH CHỈNH] Bật hỏi lại khi câu hỏi chưa đủ thông tin (thuật toán heuristic, không tốn mô hình).
    clarify_enabled: bool = True
    # Câu hỏi có ít hơn N âm tiết nội dung (sau khi bỏ từ dừng) được coi là quá ngắn để tìm kiếm.
    clarify_min_tokens: int = 3
    # [TINH CHỈNH] Hỏi lại khi kết quả tìm kiếm phân tán: điểm rerank cao nhất dưới ngưỡng này VÀ
    # ≥ 3 tài liệu khác nhau có điểm sát nhau (chênh ≤ clarify_spread). Đặt rất thấp (-99) để tắt.
    clarify_max_score: float = 0.0
    clarify_spread: float = 1.5
    # Dùng mô hình nhỏ đánh giá câu hỏi mơ hồ (tốn thêm 1 lượt gọi mô hình; mặc định chỉ bật trên GPU).
    clarify_llm: bool = False

    # ------------------------------------------------------------------ An toàn thông tin (1.3.0)
    # Chặn câu hỏi chứa bí mật (khóa bí mật PEM, mã PIN, mật khẩu) và yêu cầu vượt qua cơ chế bảo mật.
    guard_enabled: bool = True

    # ------------------------------------------------------------------ Tác vụ dài – agent (1.3.0)
    agent_url: str = "http://agent:8000"
    # [TINH CHỈNH] Tác vụ nền nhường mô hình cho hỏi đáp trực tiếp: trước mỗi lượt gọi mô hình, chờ tối đa
    # N giây khi đang có người hỏi đáp (0 = không nhường). CPU: 120–300; GPU: 0–30.
    agent_yield_max_s: int = 180
    # Ngân sách token mỗi phần tài liệu khi phân tích (map). CPU: 2500–3500; GPU: 5000–8000.
    agent_part_tokens: int = 3000
    # Số tiêu chí tối đa áp dụng trong một lượt phân tích (giới hạn thời gian chạy trên CPU).
    agent_max_criteria: int = 20
    agent_precedents: int = 2          # số văn bản đơn vị đã ban hành (tiền lệ) đưa vào khi soạn, góp ý
    agent_gopy_max_passages: int = 8   # tham gia ý kiến: số đoạn tối đa mỗi khía cạnh gửi mô hình (CPU)
    agent_gopy_def_similarity: float = 0.5  # định nghĩa dự thảo giống định nghĩa luật dưới ngưỡng này → đề nghị thống nhất
    # Ngân sách token căn cứ cho mỗi phần khi soạn thảo.
    agent_draft_ctx: int = 2500
    agent_upload_ttl_h: int = 72  # tệp đính kèm tạm (phân tích) tự xóa sau N giờ

    # ------------------------------------------------------------------ Tác tử giám định dữ liệu (1.3.0)
    # Chu kỳ tự chạy (phút); 0 = chỉ chạy khi quản trị viên bấm.
    qa_interval_min: int = 120
    # Chế độ dùng mô hình để kiểm tra chéo nghi vấn mâu thuẫn: off | auto | on.
    # auto = chỉ khi HARDWARE_PROFILE=gpu hoặc trong khung giờ rảnh qa_llm_hours (ví dụ "22-6").
    qa_llm_mode: str = "auto"
    qa_llm_hours: str = "22-6"
    qa_llm_max_checks: int = 10  # số nghi vấn tối đa kiểm tra bằng mô hình mỗi lượt
    qa_dup_threshold: float = 0.85  # ngưỡng Jaccard (MinHash) coi là gần trùng
    qa_stale_months: int = 18  # báo cáo, kế hoạch cũ hơn N tháng → đề nghị rà soát
    qa_gap_days: int = 30  # cửa sổ thống kê câu hỏi chưa trả lời được

    # ------------------------------------------------------------------ Giám sát (1.3.0)
    telemetry_enabled: bool = True
    telemetry_keep: int = 50000  # số bản ghi giữ lại cho mỗi luồng số liệu
    logs_keep: int = 20000       # số dòng nhật ký hệ thống giữ lại (mức WARNING trở lên + sự kiện nghiệp vụ)


@lru_cache
def get_settings() -> Settings:
    return Settings()
