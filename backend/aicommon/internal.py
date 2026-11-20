"""Gọi dịch vụ nội bộ kèm ngữ cảnh người dùng đã ký."""
import httpx
from fastapi import HTTPException

from .security import UserCtx, sign_service, sign_user


class ServiceError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _raise(r: httpx.Response):
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise ServiceError(r.status_code, str(detail)[:500])


class AsyncSvc:
    def __init__(self, base: str, timeout: float = 120):
        self.base = base.rstrip("/")
        self.client = httpx.AsyncClient(timeout=timeout)

    async def call(self, method: str, path: str, user: UserCtx, **kw):
        try:
            r = await self.client.request(method, self.base + path, headers={**sign_user(user), **sign_service()}, **kw)
        except httpx.HTTPError as e:
            raise ServiceError(503, f"Dịch vụ {self.base} không khả dụng: {e}") from e
        _raise(r)
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text


class SyncSvc:
    def __init__(self, base: str, timeout: float = 300):
        self.base = base.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def call(self, method: str, path: str, user: UserCtx, **kw):
        try:
            r = self.client.request(method, self.base + path, headers={**sign_user(user), **sign_service()}, **kw)
        except httpx.HTTPError as e:
            raise ServiceError(503, f"Dịch vụ {self.base} không khả dụng: {e}") from e
        _raise(r)
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text


def as_http(e: ServiceError) -> HTTPException:
    return HTTPException(e.status if e.status < 500 else 502, e.detail)
