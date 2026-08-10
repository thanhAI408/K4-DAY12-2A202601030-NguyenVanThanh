"""CP3 — Cost guard: chặn chi phí trước khi hóa đơn chặn bạn.

Rate limit giới hạn *số lượng* request. Cost guard giới hạn *số tiền*: một
client gửi đúng hạn mức request nhưng mỗi request 50k token vẫn đốt sạch
ngân sách.

Lab này chốt ngân sách theo **ngày**, không phải theo tháng.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status


KEY_TTL_SECONDS = 3 * 24 * 3600


class CostGuard:
    def __init__(self, client, daily_budget_usd: float) -> None:
        self.client = client
        self.budget = daily_budget_usd

    @staticmethod
    def today() -> str:
        """Nhãn ngày hiện tại theo UTC."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @classmethod
    def _key(cls, client_id: str, day: str | None = None) -> str:
        """Khóa Redis theo từng client và từng ngày."""
        return f"spend:{client_id}:{day or cls.today()}"

    def spent(self, client_id: str, day: str | None = None) -> float:
        """Trả về tổng chi phí đã dùng trong ngày."""
        value = self.client.get(self._key(client_id, day))

        if value is None:
            return 0.0

        return float(value)

    def check(
        self,
        client_id: str,
        estimated_cost: float = 0.0,
        day: str | None = None,
    ) -> None:
        """Kiểm tra client còn nằm trong ngân sách hay không."""
        if self.spent(client_id, day) + estimated_cost > self.budget:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="daily budget exceeded",
            )

    def record(
        self,
        client_id: str,
        cost: float,
        day: str | None = None,
    ) -> float:
        """Cộng dồn chi phí vừa phát sinh."""
        key = self._key(client_id, day)

        total = self.client.incrbyfloat(key, cost)
        self.client.expire(key, KEY_TTL_SECONDS)

        return float(total)

    def remaining(
        self,
        client_id: str,
        day: str | None = None,
    ) -> float:
        """Trả về ngân sách còn lại."""
        return max(
            0.0,
            self.budget - self.spent(client_id, day),
        )