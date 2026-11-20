"""Máy chủ mô hình GIẢ LẬP (API tương thích OpenAI + /v1/embeddings + /v1/rerank) – CHỈ dùng kiểm thử.

Trả lời tất định theo loại tác vụ (header X-AI-Task) để kiểm thử toàn bộ luồng mà không cần mô hình thật.
Chạy: uvicorn tests.mock_llm:app --port 9000
"""
import hashlib
import json
import math
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
DIM = 64
CALLS: list[dict] = []


def _tok(t: str) -> list[str]:
    return re.findall(r"\w+", t.lower())


def _emb(t: str) -> list[float]:
    v = [0.0] * DIM
    for w in _tok(t):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1
    return [x / n for x in v]


def _answer(task: str, msgs: list[dict], body: dict) -> dict | str:
    user = msgs[-1]["content"] if msgs else ""
    if task == "router":
        return {"intent": "tra_cuu"}
    if task == "rewrite":
        return {"cau_hoi": user.split("CÂU HỎI CUỐI:")[-1].strip()}
    if task == "chon-muc":
        ids = re.findall(r"^\[([^\]]+)\]", user.split("ỨNG VIÊN:")[-1], re.M)
        return {"section_ids": ids[:1]}
    if task == "dien-giai":
        verb = user.split("NGUYÊN VĂN:")[-1].split("CÂU HỎI:")[0]
        nums = re.findall(r"\d+", verb)
        dg = f"Thời hạn là {nums[-1]} theo nguyên văn." if nums else ""
        if "BỊA SỐ" in user:
            dg = "Thời hạn là 999 ngày."
        return {"dien_giai": dg}
    if task == "cau-dan":
        verb = user.split("NGUYÊN VĂN:")[-1].split("CÂU HỎI:")[0]
        nums = re.findall(r"\d+", verb)
        dg = f"Thời hạn là {nums[-1]} theo nguyên văn." if nums else ""
        if "BỊA SỐ" in user:
            dg = "Thời hạn là 999 ngày."
        return {"cau_dan": "Nội dung này được quy định như sau:", "dien_giai": dg}
    if task.startswith("answer"):
        m = re.search(r"\[1\][^\n]*\n(.+)", user)
        first = m.group(1).strip().split(". ")[0] if m else ""
        if "KHÔNG TRÍCH" in user:
            return "Câu trả lời không có nguồn."
        if "CẮT CỤT" in user.split("NHẮC LẠI CÂU HỎI:")[-1]:
            return {"_length": f"Theo tài liệu, {first} [1].\n\nNgoài ra, đơn vị còn phải thực hiện các bước bổ sung gồm"}
        if "LỆCH NGUỒN" in user.split("NHẮC LẠI CÂU HỎI:")[-1]:
            # trích [1] nhưng nội dung nằm ở nguồn khác → Verifier phải sửa chỉ số
            m2 = re.search(r"\[2\][^\n]*\n(.+)", user)
            second = m2.group(1).strip().split(". ")[0] if m2 else first
            return f"Theo tài liệu, {first} [1]. {second} [1]. Hệ thống có sẵn tàu ngầm hạt nhân phục vụ diễn tập [1]."
        return f"Theo tài liệu, {first} [1]. Chi tiết xem nguồn [7]." if first else "Không tìm thấy căn cứ trong tài liệu được cung cấp."
    if task == "metadata":
        first = next((ln.strip("# ").strip() for ln in user.splitlines() if ln.strip()), "Tài liệu")
        return {"ten": first[:100], "loai": "khac", "tom_tat": "Tóm tắt thử nghiệm.", "so_hieu": "", "co_quan_ban_hanh": "",
                "ngay_ban_hanh": ""}
    if task == "tong-hop-map":
        text = user.split(":\n", 1)[-1]
        lines = [ln.strip("-# ").strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("|")]
        rows = []
        for m in re.finditer(r"(\d+)\s+(sự cố|máy|thiết bị|lượt)", text):
            rows.append({"chi_tieu": f"Số {m.group(2)}", "gia_tri": m.group(1), "don_vi_tinh": m.group(2), "doi_tuong": ""})
        rows.append({"chi_tieu": "Số bịa", "gia_tri": "123456", "don_vi_tinh": "", "doi_tuong": ""})
        return {"y_chinh": lines[1:3], "so_lieu": rows}
    if task == "tong-hop-reduce":
        tbl = re.search(r"BẢNG SỐ LIỆU:\n(.*)", user, re.S).group(1)
        tong = re.findall(r"\| [^|]+ \| [^|]* \| ([\d.,]+) \|", tbl)
        return (f"# Báo cáo tổng hợp\n\n## 1. Kết quả\n- Tổng số liệu: {tong[0] if tong else 0} [S1]\n"
                f"- Nội dung các đơn vị [S1] [S2]\n\n## 2. Kiến nghị\n- Không có kiến nghị mới [S1]")
    if task == "tac-tu":
        if not any(m["role"] == "tool" for m in msgs):
            return {"_tool": {"name": "search_docs", "arguments": json.dumps({"query": user})}}
        return "Theo kết quả tra cứu, nội dung có trong tài liệu [1]."
    if task == "tom-tat-hoi-thoai":
        return {"tom_tat": "Người dùng đã hỏi về thiết bị lưu khóa."}
    if task == "ho-tro-chon":
        return {"lua_chon": 0 if "có" in user.split("TRẢ LỜI:")[-1].lower() else 1}
    if task == "de-xuat-tri-thuc":
        return {"tieu_de": "Máy in không nhận lệnh in", "noi_dung": "## Triệu chứng\nKhông in được.\n\n## Cách xử lý\n1. Khởi động lại dịch vụ in."}
    if task == "chao-hoi":
        return "Xin chào, tôi là trợ lý AI nội bộ."
    return "OK"


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    task = req.headers.get("x-ai-task", "")
    CALLS.append({"task": task, "body": body})
    out = _answer(task, body["messages"], body)
    tool_calls, finish = None, "stop"
    if isinstance(out, dict) and "_length" in out:  # mô phỏng câu trả lời bị cắt vì hết max_tokens
        out, finish = out["_length"], "length"
    if isinstance(out, dict) and "_tool" in out:
        tool_calls = [{"id": "call_1", "type": "function", "function": out["_tool"]}]
        content = ""
    else:
        content = json.dumps(out, ensure_ascii=False) if isinstance(out, dict) else out
    if body.get("stream"):
        async def gen():
            for i in range(0, len(content), 12):
                yield "data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": content[i:i + 12]}}]}) + "\n\n"
            yield "data: " + json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"id": "x", "object": "chat.completion", "created": int(time.time()), "model": body.get("model"),
            "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}]}


@app.post("/v1/embeddings")
async def emb(req: Request):
    body = await req.json()
    inp = body["input"] if isinstance(body["input"], list) else [body["input"]]
    return {"data": [{"index": i, "embedding": _emb(t)} for i, t in enumerate(inp)]}


@app.post("/v1/rerank")
async def rerank(req: Request):
    body = await req.json()
    q = set(_tok(body["query"]))
    res = [{"index": i, "relevance_score": len(q & set(_tok(d))) - 1.0} for i, d in enumerate(body["documents"])]
    return {"results": sorted(res, key=lambda r: -r["relevance_score"])}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "chinh"}, {"id": "nho"}]}


@app.get("/calls")
async def calls():
    return JSONResponse(CALLS[-50:])
