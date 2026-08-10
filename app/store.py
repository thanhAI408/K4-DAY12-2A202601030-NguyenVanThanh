"""CP4 — Stateless: state sống ngoài process.

Nếu lịch sử hội thoại nằm trong một dict trong RAM, thì khi scale lên 3
instance, client gửi tin 1 vào instance A và tin 2 vào instance B sẽ thấy
service "mất trí nhớ". Container còn bị restart bất cứ lúc nào. Vì vậy state
phải nằm ở nơi mọi instance cùng nhìn thấy: Redis.
"""

from __future__ import annotations

import json

import redis

from .config import get_settings


HISTORY_MAX_MESSAGES = 12
HISTORY_TTL_SECONDS = 3 * 24 * 3600


def get_redis_client(url: str | None = None):
    """Tạo client Redis từ URL."""
    url = url or get_settings().redis_url

    if url.startswith("fake://"):
        import fakeredis

        return fakeredis.FakeRedis(decode_responses=True)

    return redis.from_url(
        url,
        decode_responses=True,
    )


class ChatStore:
    """Lưu lịch sử hội thoại của từng client trong Redis List."""

    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def _key(client_id: str) -> str:
        """Mỗi client có một Redis key riêng."""
        return f"chat:{client_id}"

    def ping(self) -> bool:
        """Kiểm tra Redis còn hoạt động hay không."""
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def add_turn(
        self,
        client_id: str,
        role: str,
        content: str,
    ) -> None:
        """Thêm một message vào lịch sử hội thoại."""
        key = self._key(client_id)

        message = json.dumps(
            {
                "role": role,
                "content": content,
            },
            ensure_ascii=False,
        )

        self.client.rpush(
            key,
            message,
        )

        self.client.ltrim(
            key,
            -HISTORY_MAX_MESSAGES,
            -1,
        )

        self.client.expire(
            key,
            HISTORY_TTL_SECONDS,
        )

    def history(self, client_id: str) -> list[dict]:
        """Đọc lịch sử hội thoại từ cũ nhất đến mới nhất."""
        key = self._key(client_id)

        items = self.client.lrange(
            key,
            0,
            -1,
        )

        return [
            json.loads(item)
            for item in items
        ]

    def reset(self, client_id: str) -> None:
        """Xóa lịch sử của một client."""
        self.client.delete(
            self._key(client_id)
        )