#!/usr/bin/env bash
# =====================================================================
# CHẠY TRÊN MÁY TẢI (vùng Internet). Tải mô hình từ Hugging Face, ghim phiên bản, xuất GGUF + SHA256SUMS.
#   pip install -U "huggingface_hub[cli]"      # công cụ hf
#   git clone https://github.com/ggml-org/llama.cpp && (cd llama.cpp && cmake -B build && cmake --build build -j)
#   pip install -r llama.cpp/requirements/requirements-convert_hf_to_gguf.txt
#   CAP=2 MODE=quantize scripts/download-models.sh ./out-models
#   CAP=2 MODE=gguf WITH_SMALL=0 scripts/download-models.sh ./out-models   # máy chủ CPU 20 nhân (tài liệu triển khai)
# CAP=1: Qwen3.5-9B làm mô hình chính | CAP=2: Qwen3.6-35B-A3B + Qwen3.5-9B
# MODE=quantize (khuyến nghị – tự lượng tử hóa từ bản gốc, kiểm soát nguồn gốc trọng số)
# MODE=gguf     (tải bản GGUF đã lượng tử hóa sẵn của bên thứ ba – nhanh hơn, cần đánh giá nguồn;
#                riêng embedding tiếng Việt không có bản GGUF chính thức → vẫn chuyển đổi f16 từ bản gốc,
#                chỉ cần mã nguồn llama.cpp + gói Python chuyển đổi, KHÔNG cần biên dịch)
# WITH_SMALL=0  (không tải mô hình nhỏ – máy chủ CPU dùng mô hình MoE 35B-A3B làm mô hình duy nhất)
# =====================================================================
set -euo pipefail
OUT=${1:-./out-models}; CAP=${CAP:-2}; MODE=${MODE:-quantize}; LLAMA=${LLAMA:-./llama.cpp}
QUANT=${QUANT:-Q4_K_M}; WITH_SMALL=${WITH_SMALL:-1}
mkdir -p "$OUT/src" "$OUT/gguf"
log() { echo "[$(date +%H:%M:%S)] $*"; }

# Tên kho chính thức (kiểm tra lại trên Hugging Face tại thời điểm tải)
MAIN_REPO=${MAIN_REPO:-$([ "$CAP" = "1" ] && echo Qwen/Qwen3.5-9B || echo Qwen/Qwen3.6-35B-A3B)}
SMALL_REPO=${SMALL_REPO:-$([ "$CAP" = "1" ] && echo Qwen/Qwen3.5-2B || echo Qwen/Qwen3.5-9B)}
EMBED_REPO=${EMBED_REPO:-AITeamVN/Vietnamese_Embedding}
RERANK_REPO=${RERANK_REPO:-BAAI/bge-reranker-v2-m3}
# Bản GGUF dựng sẵn (MODE=gguf)
MAIN_GGUF_REPO=${MAIN_GGUF_REPO:-unsloth/$(basename "$MAIN_REPO")-GGUF}
SMALL_GGUF_REPO=${SMALL_GGUF_REPO:-unsloth/$(basename "$SMALL_REPO")-GGUF}
RERANK_GGUF_REPO=${RERANK_GGUF_REPO:-gpustack/bge-reranker-v2-m3-GGUF}

rev() { hf api "models/$1" 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin).get('sha',''))" 2>/dev/null || true; }

quantize() { # repo đích tên-tệp kiểu-lượng-tử
  local repo=$1 name=$2 q=$3 dir="$OUT/src/$(basename "$1")"
  log "Tải $repo"; hf download "$repo" --local-dir "$dir" ${REV:+--revision "$REV"}
  log "Chuyển đổi $repo sang GGUF"
  python3 "$LLAMA/convert_hf_to_gguf.py" "$dir" --outtype f16 --outfile "$OUT/src/$name-f16.gguf"
  if [ "$q" = "f16" ]; then mv "$OUT/src/$name-f16.gguf" "$OUT/gguf/$name-f16.gguf"; return; fi
  if [ -f calib/vi_calib.txt ]; then
    log "Tạo ma trận quan trọng (imatrix) bằng dữ liệu tiếng Việt"
    "$LLAMA/build/bin/llama-imatrix" -m "$OUT/src/$name-f16.gguf" -f calib/vi_calib.txt -o "$OUT/src/$name.imatrix"
    "$LLAMA/build/bin/llama-quantize" --imatrix "$OUT/src/$name.imatrix" "$OUT/src/$name-f16.gguf" "$OUT/gguf/$name-$q.gguf" "$q"
  else
    "$LLAMA/build/bin/llama-quantize" "$OUT/src/$name-f16.gguf" "$OUT/gguf/$name-$q.gguf" "$q"
  fi
  rm -f "$OUT/src/$name-f16.gguf"
}

fetch_gguf() { # repo mẫu-tên tên-đích
  local repo=$1 pat=$2 dst=$3 tmp="$OUT/src/dl-$(basename "$1")"
  log "Tải $repo ($pat)"; hf download "$repo" --include "$pat" --local-dir "$tmp"
  local f; f=$(find "$tmp" -name "*.gguf" | grep -v -i mmproj | sort | head -1)
  [ -n "$f" ] || { echo "Không tìm thấy tệp khớp $pat trong $repo"; exit 1; }
  cp "$f" "$OUT/gguf/$dst"
}

MAIN_NAME=$(basename "$MAIN_REPO" | tr 'A-Z' 'a-z'); SMALL_NAME=$(basename "$SMALL_REPO" | tr 'A-Z' 'a-z')
if [ "$MODE" = "quantize" ]; then
  quantize "$MAIN_REPO" "$MAIN_NAME" "$QUANT"
  [ "$WITH_SMALL" = 1 ] && quantize "$SMALL_REPO" "$SMALL_NAME" "$([ "$CAP" = "1" ] && echo Q8_0 || echo "$QUANT")"
  quantize "$EMBED_REPO" vietnamese-embedding f16
  quantize "$RERANK_REPO" bge-reranker-v2-m3 Q8_0
else
  fetch_gguf "$MAIN_GGUF_REPO" "*${QUANT}*.gguf" "$MAIN_NAME-$QUANT.gguf"
  [ "$WITH_SMALL" = 1 ] && fetch_gguf "$SMALL_GGUF_REPO" "*${QUANT}*.gguf" "$SMALL_NAME-$QUANT.gguf"
  # Embedding: hệ thống dùng Vietnamese_Embedding (tinh chỉnh tiếng Việt của bge-m3), tên tệp phải khớp EMBED_FILE
  # trong .env (vietnamese-embedding-f16.gguf). Không thay bằng bge-m3 gốc: kém chính xác với tiếng Việt.
  [ -f "$LLAMA/convert_hf_to_gguf.py" ] || { echo "Thiếu $LLAMA/convert_hf_to_gguf.py – chạy: git clone --depth 1 https://github.com/ggml-org/llama.cpp && pip install -r llama.cpp/requirements/requirements-convert_hf_to_gguf.txt"; exit 1; }
  quantize "$EMBED_REPO" vietnamese-embedding f16
  fetch_gguf "$RERANK_GGUF_REPO" "*Q8_0*.gguf" "bge-reranker-v2-m3-Q8_0.gguf"
fi

log "Lập manifest, SHA-256"
{
  echo "ngay_tai: $(date -I)"; echo "che_do: $MODE"; echo "tai_nguyen:"
  for r in "$MAIN_REPO" $([ "$WITH_SMALL" = 1 ] && echo "$SMALL_REPO") "$EMBED_REPO" "$RERANK_REPO"; do
    echo "  - {nguon: https://huggingface.co/$r, phien_ban: '$(rev "$r")'}"
  done
} > "$OUT/gguf/MODELS-MANIFEST.yaml"
(cd "$OUT/gguf" && sha256sum *.gguf > SHA256SUMS)
log "Hoàn thành. Thư mục cần chuyển giao: $OUT/gguf"
ls -lh "$OUT/gguf"
