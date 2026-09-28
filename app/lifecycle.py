"""CP4 — Graceful shutdown.

Khi bạn deploy phiên bản mới, orchestrator (Docker, Railway, Cloud Run, K8s)
gửi **SIGTERM** rồi đợi vài chục giây trước khi SIGKILL. Nếu app bỏ qua tín
hiệu đó, mọi request đang xử lý dở bị cắt giữa chừng — user thấy lỗi 502 mỗi
lần bạn deploy.

Ứng xử đúng: nhận SIGTERM → báo "tôi sắp tắt" qua health check để load
balancer ngừng đẩy traffic mới vào → xử lý nốt request đang chạy → thoát.
"""

from __future__ import annotations

import signal


class Lifecycle:
    """Giữ trạng thái vòng đời của process."""

    def __init__(self) -> None:
        self.shutting_down = False
        # Handler đã được đăng ký trước ta (của uvicorn) — xem install()
        self._previous: dict = {}

    def request_shutdown(self, signum=None, frame=None) -> None:
        """Signal handler: đánh dấu process đang tắt dần.

        Cách làm (CP4):
          1. ``self.shutting_down = True``
          2. Gọi lại handler cũ nếu có::

                previous = self._previous.get(signum)
                if callable(previous):
                    previous(signum, frame)

        Bước 2 quan trọng hơn vẻ ngoài của nó. Mỗi tín hiệu chỉ có **một**
        handler: đăng ký handler của mình là ghi đè handler của uvicorn — thứ
        chịu trách nhiệm thật sự cho việc dừng server. Không gọi lại nó thì
        app bật cờ "đang tắt" rồi... chạy tiếp mãi mãi, cho tới khi
        orchestrator hết kiên nhẫn và SIGKILL. Đúng cái mà graceful shutdown
        định tránh.

        Chữ ký ``(signum, frame)`` là bắt buộc vì Python gọi handler với 2
        tham số này. Không làm gì nặng ở đây (không gọi mạng, không ghi file)
        — handler chạy xen giữa bytecode.
        """
        # Việc DUY NHẤT phải làm trong handler: bật cờ. /health và /ready đọc
        # cờ này để trả 503, load balancer rút instance khỏi vòng xoay. Handler
        # chạy xen giữa bytecode nên không được gọi mạng hay ghi file ở đây.
        self.shutting_down = True

        # Nhường lại cho handler cũ (của uvicorn). Mỗi tín hiệu chỉ có MỘT
        # handler; đăng ký handler của ta là ghi đè handler của uvicorn — thứ
        # thật sự dừng server. Quên bước này thì app bật cờ "đang tắt" rồi chạy
        # mãi cho tới khi bị SIGKILL, đúng cái graceful shutdown muốn tránh.
        # callable(): handler cũ có thể là signal.SIG_DFL / SIG_IGN (không gọi
        # được) hoặc None, khi đó bỏ qua.
        previous = self._previous.get(signum)
        if callable(previous):
            previous(signum, frame)

    def install(self) -> None:
        """Đăng ký handler cho SIGTERM và SIGINT, nhớ lại handler cũ.

        Cách làm (CP4): với mỗi tín hiệu trong ``(signal.SIGTERM, signal.SIGINT)``:

            self._previous[sig] = signal.getsignal(sig)   # nhớ handler cũ
            signal.signal(sig, self.request_shutdown)     # rồi mới ghi đè

        SIGTERM: orchestrator yêu cầu tắt. SIGINT: bạn bấm Ctrl+C.
        """
        for sig in (signal.SIGTERM, signal.SIGINT):
            current = signal.getsignal(sig)

            # Phòng gọi install() hai lần: lần hai sẽ "nhớ" chính
            # request_shutdown làm handler cũ, rồi request_shutdown gọi lại
            # chính nó → đệ quy vô hạn. Đã đăng ký rồi thì bỏ qua.
            if current == self.request_shutdown:
                continue

            # Nhớ handler cũ TRƯỚC, rồi mới ghi đè — thứ tự này quan trọng
            # vì sau khi ghi đè thì không còn cách nào lấy lại handler cũ.
            self._previous[sig] = current

            # Truyền THAM CHIẾU hàm (không có dấu ngoặc). Viết
            # `self.request_shutdown()` sẽ gọi hàm ngay và đăng ký kết quả None.
            signal.signal(sig, self.request_shutdown)


# Một instance dùng chung cho cả app
lifecycle = Lifecycle()
