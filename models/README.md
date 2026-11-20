# Thư mục mô hình

Đặt các tệp mô hình vào thư mục này (được gắn chỉ đọc vào các container llama.cpp). Tên tệp khai báo trong `.env`.

| Biến trong .env | Vai trò | Khuyến nghị Cấp 1 (RAM 32–64 GB) | Khuyến nghị Cấp 2 (RAM 192–256 GB) |
|---|---|---|---|
| `LLM_MAIN_FILE` | Mô hình chính (bắt buộc) | `qwen3.5-9b-Q4_K_M.gguf` | `qwen3.6-35b-a3b-Q4_K_M.gguf` |
| `LLM_SMALL_FILE` | Mô hình nhỏ: định tuyến, metadata (tùy chọn) | không dùng (trỏ về mô hình chính) | `qwen3.5-9b-Q4_K_M.gguf` |
| `EMBED_FILE` | Embedding cho Luồng A (bắt buộc) | `vietnamese-embedding-f16.gguf` | như Cấp 1 |
| `RERANK_FILE` | Reranker (tùy chọn) | `bge-reranker-v2-m3-Q8_0.gguf` | như Cấp 1 |

- Chuẩn bị trên máy tải: `scripts/download-models.sh` (tự lượng tử hóa từ bản gốc hoặc tải GGUF dựng sẵn), kèm `SHA256SUMS`.
- Có thể dùng mô hình khác định dạng GGUF (ví dụ Gemma 4 26B-A4B) – chỉ cần đổi `LLM_MAIN_FILE`. Mô hình phải có chat template hỗ trợ gọi công cụ (llama.cpp `--jinja`) để dùng chế độ "Trợ lý nhiều bước".
- Đổi mô hình embedding (khác số chiều vector) phải lập chỉ mục lại Luồng A: xóa collection `tai_lieu` trong Qdrant rồi chạy lại nạp/duyệt hoặc công cụ lập chỉ mục lại.
- Giai đoạn GPU (vLLM): đặt thư mục safetensors (ví dụ `Qwen3.6-27B-FP8/`) và khai báo `VLLM_MODEL_DIR`.
