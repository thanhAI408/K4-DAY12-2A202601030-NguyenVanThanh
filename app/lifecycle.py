"""CP4 — Graceful shutdown (draining).

Khi bạn deploy phiên bản mới, orchestrator (Docker, Railway, Cloud Run, K8s)
gửi **SIGTERM** rồi đợi vài chục giây trước khi SIGKILL. Nếu app bỏ qua tín
hiệu đó, mọi request đang xử lý dở bị cắt giữa chừng — user thấy lỗi 502 mỗi
lần bạn deploy.

Ứng xử đúng gọi là *draining*: nhận SIGTERM → báo "tôi sắp tắt" qua health
check để load balancer ngừng đẩy traffic mới vào → xử lý nốt request đang
chạy → thoát.
"""

from __future__ import annotations

import signal


class ShutdownGuard:
    """Giữ trạng thái vòng đời của process."""

    def __init__(self) -> None:
        self.draining = False

        # Handler đã được đăng ký trước ta (của uvicorn) — xem arm()
        self._previous: dict = {}

    def start_draining(self, signum=None, frame=None) -> None:
        """Signal handler: đánh dấu process đang tắt dần.

        CP4:
          1. Đánh dấu process đang draining.
          2. Gọi lại signal handler cũ nếu có.

        Gọi handler cũ rất quan trọng vì uvicorn vẫn cần nhận tín hiệu
        shutdown để thật sự dừng server một cách graceful.
        """
        self.draining = True

        previous = self._previous.get(signum)

        if callable(previous):
            previous(signum, frame)

    def arm(self) -> None:
        """Đăng ký handler cho SIGTERM và SIGINT, nhớ lại handler cũ."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._previous[sig] = signal.getsignal(sig)
            signal.signal(sig, self.start_draining)


# Một instance dùng chung cho cả app
shutdown_guard = ShutdownGuard()