# Đánh giá SQLite FTS5 và PostgreSQL cho tìm kiếm toàn văn Luồng B

*Cập nhật: 13/11/2026 – áp dụng từ phiên bản 1.1.0*

## 1. Kết luận

Luồng B chuyển sang **tìm kiếm toàn văn có sẵn của PostgreSQL** (`tsvector` + chỉ mục GIN, cấu hình `simple`), bổ sung **pg_trgm** để tìm gần đúng khi gõ sai. Kho Git Markdown vẫn là nguồn duy nhất; bảng PostgreSQL chỉ là chỉ mục dựng lại được; nguyên văn luôn đọc từ tệp. Không dùng vector.

Lý do chính: hệ thống đã vận hành PostgreSQL; chỉ mục dùng chung cho nhiều tiến trình/container (trước đây mỗi tiến trình tự dựng chỉ mục SQLite trong bộ nhớ); khởi động lại không phải dựng lại chỉ mục; sao lưu, phân quyền, giám sát theo một quy trình chung.

## 2. So sánh

| Tiêu chí | SQLite FTS5 (bản 1.0.0) | PostgreSQL FTS (bản 1.1.0) |
|---|---|---|
| Xếp hạng | `bm25()` sẵn có (có IDF) | `ts_rank_cd`: không có IDF, không bão hòa tần suất từ |
| Bỏ dấu tiếng Việt | `unicode61 remove_diacritics` | `unaccent` không IMMUTABLE nên không dùng trực tiếp trong cột sinh/chỉ mục → hệ thống chuẩn hóa ở ứng dụng (dùng chung cho lập chỉ mục và truy vấn) |
| Tách từ tiếng Việt | Theo âm tiết; không có từ điển tiếng Việt | Như nhau (cấu hình `simple`, không stemming – phù hợp ngôn ngữ đơn lập) |
| Cụm từ chính xác | `"..."` | Toán tử `<->` |
| Gõ sai chính tả | Không (cần tokenizer trigram riêng) | Có – `pg_trgm` (`word_similarity`) |
| Dùng chung giữa tiến trình, container | Không (bản 1.0 dựng trong bộ nhớ từng tiến trình, buộc chạy 01 tiến trình) | Có; ghi Git và cập nhật chỉ mục được khóa bằng advisory lock của PostgreSQL |
| Khởi động lại | Dựng lại toàn bộ chỉ mục | Bỏ qua nếu commit đã lập chỉ mục trùng HEAD; cập nhật tăng dần theo văn bản |
| Sao lưu, sẵn sàng cao | Không áp dụng (dữ liệu tạm) | Theo CSDL (pg_dump, sao chép vật lý) |
| Thành phần phải vận hành thêm | Không | Không (PostgreSQL đã có trong hệ thống); `pg_trgm` thuộc gói contrib chính thức |

Hạn chế xếp hạng của PostgreSQL là đã biết: hàm xếp hạng sẵn có chỉ tính tần suất từ và độ dài văn bản, không tính IDF ([ParadeDB](https://www.paradedb.com/learn/search-in-postgresql/bm25)); hiệu năng xếp hạng cũng giảm khi bảng lên tới hàng trăm nghìn – triệu dòng ([Tiger Data](https://www.tigerdata.com/blog/introducing-pg_textsearch-true-bm25-ranking-hybrid-retrieval-postgres)). Với Luồng B, ảnh hưởng thấp vì: (1) tham chiếu trực tiếp (số hiệu, Điều, Khoản, mã mục) được phân giải trước, không qua xếp hạng; (2) kết quả FTS chỉ là danh sách ứng viên (tối đa 8) để mô hình chọn trong phạm vi ứng viên; (3) kho văn bản chuẩn thường ở mức hàng nghìn – vài chục nghìn mục.

## 3. Đo kiểm

`backend/tests/bench_fts.py` – kho mục tổng hợp (phân bố từ Zipf), 200 truy vấn AND 2–4 từ, lấy top-10; máy kiểm thử 2 vCPU, PostgreSQL 16:

| Số mục | Công cụ | Dựng chỉ mục | p50 | p95 | Số truy vấn có kết quả |
|---|---|---|---|---|---|
| 5.000 | SQLite FTS5 | 0,0 s | 0,13 ms | 0,35 ms | 172/200 |
| 5.000 | PostgreSQL | 0,5 s | 0,29 ms | 1,55 ms | 172/200 |
| 50.000 | SQLite FTS5 | 0,6 s | 0,98 ms | 2,31 ms | 196/200 |
| 50.000 | PostgreSQL (89 MB bảng + chỉ mục) | 4,9 s | 1,14 ms | 9,10 ms | 196/200 |

Hai công cụ trả về cùng tập kết quả khớp; độ trễ đều ở mức mili giây, không đáng kể so với thời gian sinh câu trả lời của mô hình (giây). Dựng chỉ mục PostgreSQL chậm hơn nhưng chỉ chạy khi kho thay đổi và theo từng văn bản.

## 4. Phương án nâng cấp xếp hạng (khi cần)

| Tiện ích | Giấy phép | Ghi chú |
|---|---|---|
| pg_textsearch (Tiger Data) | PostgreSQL License | BM25 trong PostgreSQL; theo nhà phát triển yêu cầu PostgreSQL 17+ ([so sánh](https://particula.tech/blog/pg-search-vs-pg-textsearch-bm25-postgres)) |
| pg_search (ParadeDB) | AGPL-3.0 ([PGXN](https://pgxn.org/dist/pg_search/0.18.6/)) | Không chọn do điều khoản copyleft |

Có thể thay câu truy vấn trong `services/exact/pgindex.py` (hàm `search`) mà không ảnh hưởng phần còn lại.

## 5. Thay đổi trong mã nguồn

- `services/exact/pgindex.py` (mới): bảng `exact_section` (cột `tsv` sinh tự động, trọng số A = số hiệu/tên/đường dẫn tiêu đề, B = nội dung), chỉ mục GIN, chỉ mục trigram; bảng `exact_index_state` lưu commit đã lập chỉ mục; truy vấn theo thứ tự cụm từ → đủ mọi từ → một trong các từ → gần đúng.
- `services/exact/kb.py`: bỏ SQLite; đồng bộ chỉ mục khi khởi động (bỏ qua nếu commit không đổi) và sau mỗi commit (chỉ văn bản thay đổi); khóa advisory PostgreSQL cho thao tác Git; tự nạp lại bộ nhớ khi tiến trình khác ghi commit mới.
- `aicommon/db.py`: tạo bảng có khóa advisory, tránh xung đột khi nhiều tiến trình khởi động cùng lúc.
- `docker-compose.yml`: exact-svc chạy 2 tiến trình.
- `POST /api/exact/reload?force=true`: dựng lại toàn bộ chỉ mục.
- Kiểm thử: `tests/test_exact_pg.py` (5 bài: bỏ dấu, cụm từ, số hiệu, gõ sai, lọc văn bản, khởi động lại, cập nhật tăng dần, thu hồi).
