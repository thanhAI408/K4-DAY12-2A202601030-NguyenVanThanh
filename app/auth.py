"""CP3 — Xác thực bằng Bearer token.

Public URL = ai cũng gọi được. Không có lớp này, hóa đơn LLM của bạn do
người lạ quyết định.

Chuẩn dùng ở đây là RFC 6750 — token đi trong header Authorization:

    Authorization: Bearer <token>
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from .config import get_settings

ANONYMOUS_CLIENT = "anonymous"
SCHEME = "Bearer"


def verify_bearer_token(
    authorization: str | None = Header(default=None),
    x_client_id: str | None = Header(default=None),
) -> str:
    """Kiểm tra Bearer token và trả về client_id."""

    def unauthorized() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not authorization:
        unauthorized()

    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != SCHEME.lower() or not token:
        unauthorized()

    expected_token = get_settings().api_token

    if not secrets.compare_digest(token, expected_token):
        unauthorized()

    return x_client_id or ANONYMOUS_CLIENT