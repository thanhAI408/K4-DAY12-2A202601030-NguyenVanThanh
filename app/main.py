"""Chat service — điểm ráp nối của cả lab (CP1, CP3, CP4).

Luồng một request tới /chat:

    client ──► verify_bearer_token ──► token bucket ──► cost guard
                                                            │
                                    store.history ◄─────────┘
                                          │
                                   generate_reply
                                          │
                              store.add_turn × 2 ──► guard.record ──► emit
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from utils.mock_llm import generate_reply

from .auth import verify_bearer_token
from .config import get_settings
from .cost_guard import CostGuard
from .lifecycle import shutdown_guard
from .logging_utils import emit
from .rate_limiter import TokenBucket
from .store import ChatStore, get_redis_client

SERVICE_NAME = "day12-chat-service"
SERVICE_VERSION = "1.0.0"


# ─────────────────────────────────────────────────────────────
# Providers
# ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_store() -> ChatStore:
    return ChatStore(get_redis_client())


@lru_cache(maxsize=1)
def get_bucket() -> TokenBucket:
    settings = get_settings()

    return TokenBucket(
        get_redis_client(),
        capacity=settings.bucket_capacity,
        refill_per_minute=settings.refill_per_minute,
    )


@lru_cache(maxsize=1)
def get_cost_guard() -> CostGuard:
    return CostGuard(
        get_redis_client(),
        get_settings().daily_budget_usd,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Chạy lúc app khởi động và lúc tắt."""
    shutdown_guard.arm()

    emit(
        "service_started",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
    )

    yield

    emit(
        "service_stopped",
        service=SERVICE_NAME,
    )


app = FastAPI(
    title="Day 12 Chat Service",
    version=SERVICE_VERSION,
    lifespan=lifespan,
)


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=2000,
    )


# ─────────────────────────────────────────────────────────────
# Health & readiness
# ─────────────────────────────────────────────────────────────

@app.get("/")
def root():
    """Root endpoint — service info, easy to verify from browser."""
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "endpoints": {
            "healthz": "/healthz",
            "readyz": "/readyz",
            "chat": "/chat (POST, requires Bearer token)",
            "docs": "/docs",
        },
    }


@app.get("/healthz")
def healthz():
    """Liveness probe — process còn sống không?"""

    if shutdown_guard.draining:
        return JSONResponse(
            status_code=503,
            content={
                "status": "draining",
            },
        )

    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
    }


@app.get("/readyz")
def readyz(store: ChatStore = Depends(get_store)):
    """Readiness probe — service có sẵn sàng nhận traffic không?"""

    # Đang graceful shutdown thì không nhận traffic mới
    if shutdown_guard.draining:
        return JSONResponse(
            status_code=503,
            content={
                "status": "draining",
            },
        )

    # Redis chết hoặc không truy cập được
    if not store.ping():
        return JSONResponse(
            status_code=503,
            content={
                "status": "not ready",
                "redis": False,
            },
        )

    # Service và Redis đều sẵn sàng
    return {
        "status": "ready",
        "redis": True,
    }


# ─────────────────────────────────────────────────────────────
# Endpoint chính
# ─────────────────────────────────────────────────────────────

@app.post("/chat")
def chat(
    payload: ChatRequest,
    client_id: str = Depends(verify_bearer_token),
    store: ChatStore = Depends(get_store),
    bucket: TokenBucket = Depends(get_bucket),
    guard: CostGuard = Depends(get_cost_guard),
):
    """Gửi một tin nhắn tới service."""

    # 1. Rate limit
    bucket.consume(client_id)

    # 2. Kiểm tra ngân sách
    guard.check(client_id)

    # 3. Lấy lịch sử hội thoại
    history = store.history(client_id)

    # 4. Gọi mock LLM
    result = generate_reply(
        payload.message,
        history,
    )

    # 5. Lưu user message
    store.add_turn(
        client_id,
        "user",
        payload.message,
    )

    # 5. Lưu assistant reply
    store.add_turn(
        client_id,
        "assistant",
        result["text"],
    )

    # 6. Ghi nhận chi phí
    guard.record(
        client_id,
        result["usd_cost"],
    )

    # 7. Structured log
    emit(
        "chat_completed",
        client_id=client_id,
        prompt_tokens=result["prompt_tokens"],
        completion_tokens=result["completion_tokens"],
        usd_cost=result["usd_cost"],
    )

    # 8. Trả response
    return {
        "reply": result["text"],
        "client_id": client_id,
        "turns_before": len(history),
        "usd_cost": result["usd_cost"],
        "usage": {
            "prompt": result["prompt_tokens"],
            "completion": result["completion_tokens"],
        },
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.port,
    )