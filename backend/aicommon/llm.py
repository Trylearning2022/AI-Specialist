"""Client gọi mô hình qua API tương thích OpenAI (LiteLLM → llama.cpp / vLLM).

Ứng dụng chỉ dùng tên logic của mô hình (chinh, nho); việc ánh xạ sang engine cụ thể
được cấu hình tại LiteLLM (config/litellm.yaml).
"""
import json
import re
import time
from typing import Any, AsyncIterator

import httpx

from .config import get_settings
from .telemetry import llm_usage, record_llm

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)


class LLMError(RuntimeError):
    pass


def strip_think(text: str) -> str:
    text = THINK_RE.sub("", text or "")
    if "</think>" in text:  # trường hợp thẻ mở bị cắt
        text = text.split("</think>", 1)[1]
    return text.strip()


def extract_json(text: str) -> Any:
    """Lấy đối tượng JSON từ đầu ra mô hình (chịu được ```json ... ``` và văn bản thừa)."""
    text = strip_think(text)
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    for opener, closer in (("{", "}"), ("[", "]")):
        s, e = text.find(opener), text.rfind(closer)
        if s != -1 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("Đầu ra mô hình không phải JSON hợp lệ")


def _body(messages, model, temperature, max_tokens, schema=None, tools=None, stream=False, **extra):
    s = get_settings()
    body: dict[str, Any] = {
        "model": model or s.model_main,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if schema is not None:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "ket_qua", "schema": schema, "strict": True}}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if s.llm_disable_thinking:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    body.update(extra)
    return body


def _chars(messages) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)


def _headers(task: str | None):
    h = {"Authorization": f"Bearer {get_settings().llm_api_key}"}
    if task:
        h["X-AI-Task"] = task  # phục vụ ghi vết, kiểm thử
    return h


class AsyncLLM:
    def __init__(self, base_url: str | None = None):
        s = get_settings()
        self.base = (base_url or s.llm_base_url).rstrip("/")
        self.client = httpx.AsyncClient(timeout=s.llm_timeout)

    async def chat_raw(self, messages, model=None, temperature=0.2, max_tokens=1024,
                       schema=None, tools=None, task=None, **extra) -> dict:
        body = _body(messages, model, temperature, max_tokens, schema, tools, **extra)
        t0 = time.perf_counter()
        try:
            r = await self.client.post(f"{self.base}/chat/completions", json=body, headers=_headers(task))
        except httpx.HTTPError as e:
            record_llm(task, body["model"], t0, False, error=str(e))
            raise LLMError(f"Không kết nối được máy chủ mô hình: {e}") from e
        if r.status_code >= 400:
            record_llm(task, body["model"], t0, False, error=f"HTTP {r.status_code}")
            raise LLMError(f"Máy chủ mô hình trả lỗi {r.status_code}: {r.text[:300]}")
        data = r.json()
        try:
            out = data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError):
            out = ""
        record_llm(task, body["model"], t0, True, *llm_usage(data, _chars(messages), out))
        return data

    async def chat(self, messages, **kw) -> str:
        data = await self.chat_raw(messages, **kw)
        return strip_think(data["choices"][0]["message"].get("content") or "")

    async def chat_json(self, messages, schema: dict, **kw) -> Any:
        kw.setdefault("temperature", 0.0)
        text = await self.chat(messages, schema=schema, **kw)
        return extract_json(text)

    async def stream(self, messages, model=None, temperature=0.2, max_tokens=1024,
                     task=None, info: dict | None = None, **extra) -> AsyncIterator[str]:
        """Sinh câu trả lời theo luồng. Nếu truyền dict `info`, sau khi kết thúc sẽ có
        info["finish_reason"]: "stop" (mô hình tự dừng) | "length" (hết max_tokens – câu trả lời bị cắt)."""
        body = _body(messages, model, temperature, max_tokens, stream=True, **extra)
        body["stream_options"] = {"include_usage": True}  # máy chủ hỗ trợ sẽ trả số token ở gói cuối
        in_think = False
        t0, first, out_chars, usage = time.perf_counter(), None, 0, {}
        try:
            async with self.client.stream("POST", f"{self.base}/chat/completions", json=body,
                                          headers=_headers(task)) as r:
                if r.status_code >= 400:
                    raise LLMError(f"Máy chủ mô hình trả lỗi {r.status_code}: {(await r.aread())[:300]!r}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        if obj.get("usage"):
                            usage = obj["usage"]
                        if not obj.get("choices"):
                            continue
                        choice = obj["choices"][0]
                        delta = choice.get("delta", {}).get("content") or ""
                        if choice.get("finish_reason") and info is not None:
                            info["finish_reason"] = choice["finish_reason"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    # bỏ phần suy luận <think>…</think> nếu mô hình phát ra trong nội dung
                    if "<think>" in delta:
                        in_think = True
                        delta = delta.split("<think>", 1)[0]
                    if in_think:
                        if "</think>" in delta:
                            in_think = False
                            delta = delta.split("</think>", 1)[1]
                        else:
                            continue
                    if delta:
                        if first is None:
                            first = time.perf_counter() - t0
                        out_chars += len(delta)
                        yield delta
        except httpx.HTTPError as e:
            record_llm(task, body["model"], t0, False, error=str(e))
            raise LLMError(f"Mất kết nối máy chủ mô hình: {e}") from e
        tin, tout = llm_usage({"usage": usage}, _chars(messages), "x" * out_chars)
        record_llm(task, body["model"], t0, True, tin, tout, first_token_s=first)

    async def models(self) -> list[str]:
        r = await self.client.get(f"{self.base}/models", headers=_headers(None))
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    async def aclose(self):
        await self.client.aclose()


class SyncLLM:
    """Dùng trong tác vụ nền (Celery)."""

    def __init__(self, base_url: str | None = None):
        s = get_settings()
        self.base = (base_url or s.llm_base_url).rstrip("/")
        self.client = httpx.Client(timeout=s.llm_timeout)

    def chat(self, messages, model=None, temperature=0.2, max_tokens=1024, schema=None, task=None, **extra) -> str:
        body = _body(messages, model, temperature, max_tokens, schema, **extra)
        t0 = time.perf_counter()
        try:
            r = self.client.post(f"{self.base}/chat/completions", json=body, headers=_headers(task))
        except httpx.HTTPError as e:
            record_llm(task, body["model"], t0, False, error=str(e))
            raise LLMError(f"Không kết nối được máy chủ mô hình: {e}") from e
        if r.status_code >= 400:
            record_llm(task, body["model"], t0, False, error=f"HTTP {r.status_code}")
            raise LLMError(f"Máy chủ mô hình trả lỗi {r.status_code}: {r.text[:300]}")
        data = r.json()
        out = data["choices"][0]["message"].get("content") or ""
        record_llm(task, body["model"], t0, True, *llm_usage(data, _chars(messages), out))
        return strip_think(out)

    def chat_json(self, messages, schema: dict, **kw) -> Any:
        kw.setdefault("temperature", 0.0)
        return extract_json(self.chat(messages, schema=schema, **kw))
