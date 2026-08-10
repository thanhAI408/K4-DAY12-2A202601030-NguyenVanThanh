"""CP3 — Rate limiting bằng thuật toán token bucket.

Hình dung mỗi client có một cái xô đựng token:

    - Xô chứa tối đa ``capacity`` token, ban đầu đầy.
    - Token tự nhỏ vào xô đều đặn với tốc độ ``refill_per_minute`` mỗi phút.
    - Mỗi request lấy ra 1 token. Xô cạn → 429.

Cấu trúc dữ liệu: một Redis HASH cho mỗi client, gồm 2 trường:
``tokens`` (số token còn lại) và ``ts`` (lần cập nhật gần nhất).
"""

from __future__ import annotations

import time

from fastapi import HTTPException, status


BUCKET_TTL_SECONDS = 3600


class TokenBucket:
    def __init__(self, client, capacity: int, refill_per_minute: int) -> None:
        self.client = client
        self.capacity = capacity
        self.refill_per_minute = refill_per_minute

    @staticmethod
    def _key(client_id: str) -> str:
        """Mỗi client một bucket riêng."""
        return f"bucket:{client_id}"

    @property
    def refill_per_second(self) -> float:
        """Tốc độ nạp token tính theo giây."""
        return self.refill_per_minute / 60.0

    def available(self, client_id: str, now: float | None = None) -> float:
        """Trả về số token còn lại tại thời điểm hiện tại."""
        now = now if now is not None else time.time()

        state = self.client.hgetall(self._key(client_id))

        if not state:
            return float(self.capacity)

        tokens = float(state["tokens"])
        last = float(state["ts"])

        tokens += (now - last) * self.refill_per_second

        return min(float(self.capacity), tokens)

    def consume(self, client_id: str, now: float | None = None) -> None:
        """Tiêu thụ 1 token; hết token thì trả lỗi 429."""
        now = now if now is not None else time.time()

        tokens = self.available(client_id, now)

        if tokens < 1:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(self.retry_after(tokens))},
            )

        key = self._key(client_id)

        self.client.hset(
            key,
            mapping={
                "tokens": tokens - 1,
                "ts": now,
            },
        )

        self.client.expire(key, BUCKET_TTL_SECONDS)

    def retry_after(self, tokens: float) -> int:
        """Còn bao nhiêu giây nữa thì có token tiếp theo."""
        if self.refill_per_second <= 0:
            return BUCKET_TTL_SECONDS

        return max(
            1,
            int((1 - tokens) / self.refill_per_second) + 1,
        )