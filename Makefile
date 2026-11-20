# Lệnh thường dùng (chạy tại thư mục gốc)
.PHONY: init up down logs build seed smoke backup test-local test-stop ui-dev

init:        ## Khởi tạo lần đầu (sinh khóa, chứng thư, khởi động)
	scripts/init.sh
up:
	docker compose up -d
down:
	docker compose down
logs:
	docker compose logs -f --tail=100
build:       ## Xây dựng ảnh backend và giao diện
	docker compose build gateway portal
seed:        ## Nạp dữ liệu mẫu trong kb-seed/
	docker compose --profile tools run --rm tools
smoke:
	scripts/smoke-test.sh
backup:
	scripts/backup.sh
test-local:  ## Kiểm thử tích hợp không cần Docker (PostgreSQL, Redis cục bộ; mô hình giả lập)
	cd backend && tests/run_stack.sh && python -m pytest -q tests
test-stop:
	cd backend && RESET=1 tests/stop_stack.sh
ui-dev:
	cd frontend && npm install && npm run dev
