# Bước 1: xây dựng giao diện (cần kho npm nội bộ hoặc thư mục node_modules đã chuẩn bị – xem scripts/)
FROM node:22-bookworm-slim AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json* ./
ARG NPM_REGISTRY=""
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi && npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Bước 2: phục vụ tệp tĩnh (Nginx biên chuyển tiếp tới container này)
FROM nginx:1.27-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY config/nginx/portal.conf /etc/nginx/conf.d/default.conf
