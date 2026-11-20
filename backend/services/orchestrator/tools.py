"""Tool Registry – danh mục công cụ cho tác tử, cấp theo vai trò, mặc định chỉ đọc.

Cùng một danh mục được công bố qua: (1) API /tools nội bộ, (2) máy chủ MCP (/mcp),
(3) định dạng "tools" của API OpenAI cho vòng lặp tác tử.
"""
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from aicommon.config import get_settings
from aicommon.internal import AsyncSvc
from aicommon.security import UserCtx

S = get_settings()
search_svc = AsyncSvc(S.search_url)
exact_svc = AsyncSvc(S.exact_url)
support_svc = AsyncSvc(S.support_url)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., Awaitable[Any]]
    roles: tuple[str, ...] = ("user", "reviewer", "admin")
    writes: bool = False  # công cụ có ghi dữ liệu → bắt buộc người dùng xác nhận
    tags: list[str] = field(default_factory=list)

    def openai(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


async def _search_docs(user: UserCtx, query: str, loai: str | None = None, top_k: int = 5):
    f = {"loai": loai} if loai else {}
    r = await search_svc.call("POST", "/search", user, json={"query": query, "top_k": top_k, "filters": f})
    return [{"doc_id": h["doc_id"], "section_id": h["section_id"], "title": h["title"], "breadcrumb": h["breadcrumb"],
             "text": h["text"], "nguon": h.get("nguon"), "so_hieu": h.get("so_hieu")} for h in r["results"]]


async def _find_exact(user: UserCtx, query: str, limit: int = 5):
    r = await exact_svc.call("POST", "/resolve", user, json={"query": query})
    if r["section_ids"]:
        return [{"section_id": s} for s in r["section_ids"]]
    r = await exact_svc.call("POST", "/search", user, json={"query": query, "limit": limit})
    return [{"section_id": h["section_id"], "path": " › ".join(h["path"]), "snippet": h["snippet"]} for h in r["results"]]


async def _get_section(user: UserCtx, section_id: str):
    s = await exact_svc.call("GET", f"/sections/{section_id}", user)
    return {k: s[k] for k in ("section_id", "doc_id", "so_hieu", "ten", "heading", "text", "trang_thai", "commit")}


async def _list_catalog(user: UserCtx):
    r = await exact_svc.call("GET", "/catalog", user)
    return [{k: d[k] for k in ("doc_id", "so_hieu", "ten", "loai", "trang_thai")} for d in r["docs"]]


async def _suggest_trees(user: UserCtx, query: str):
    return await support_svc.call("GET", "/trees/suggest", user, params={"q": query})


REGISTRY: dict[str, Tool] = {t.name: t for t in [
    Tool("search_docs", "Tìm kiếm ngữ nghĩa trong tài liệu tham khảo nội bộ (Luồng A). Trả các đoạn văn kèm nguồn.",
         {"type": "object", "properties": {"query": {"type": "string", "description": "Nội dung cần tìm"},
                                           "loai": {"type": "string", "description": "Loại văn bản (tùy chọn)"},
                                           "top_k": {"type": "integer", "minimum": 1, "maximum": 10}},
          "required": ["query"]}, _search_docs, tags=["luong_a"]),
    Tool("find_exact", "Định vị mục trong kho văn bản chuẩn theo số hiệu, Điều, Khoản hoặc từ khóa (Luồng B, không dùng vector).",
         {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
          "required": ["query"]}, _find_exact, tags=["luong_b"]),
    Tool("get_section", "Lấy NGUYÊN VĂN một mục của kho văn bản chuẩn theo mã mục.",
         {"type": "object", "properties": {"section_id": {"type": "string"}}, "required": ["section_id"]},
         _get_section, tags=["luong_b"]),
    Tool("list_catalog", "Liệt kê danh mục văn bản chuẩn người dùng được phép truy cập.",
         {"type": "object", "properties": {}}, _list_catalog, tags=["luong_b"]),
    Tool("suggest_trees", "Gợi ý cây xử lý sự cố kỹ thuật phù hợp với mô tả sự cố.",
         {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
         _suggest_trees, tags=["ho_tro"]),
]}


def tools_for(user: UserCtx) -> list[Tool]:
    return [t for t in REGISTRY.values() if user.has(*t.roles)]


async def run_tool(user: UserCtx, name: str, args: dict) -> Any:
    t = REGISTRY.get(name)
    if not t or not user.has(*t.roles):
        raise PermissionError(f"Công cụ '{name}' không tồn tại hoặc không được cấp cho người dùng")
    if t.writes and not args.pop("_xac_nhan", False):
        raise PermissionError(f"Công cụ '{name}' có ghi dữ liệu, cần người dùng xác nhận")
    props = t.parameters.get("properties", {})
    clean = {k: v for k, v in args.items() if k in props}
    return await t.fn(user, **clean)
