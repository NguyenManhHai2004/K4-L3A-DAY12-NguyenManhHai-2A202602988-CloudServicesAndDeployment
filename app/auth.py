"""CP3 — Xác thực bằng API key.

Public URL = ai cũng gọi được. Không có lớp này, hóa đơn LLM của bạn do
người lạ quyết định.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from .config import get_settings

ANONYMOUS_USER = "anonymous"


def verify_api_key(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> str:
    """Kiểm tra header ``X-API-Key``; trả về user_id nếu hợp lệ.

    TODO (CP3):
      1. Lấy khóa đúng từ ``get_settings().agent_api_key``.
      2. Nếu ``x_api_key`` là None hoặc không khớp → raise
         ``HTTPException(status_code=401, detail="invalid or missing API key")``.
      3. So sánh bằng ``secrets.compare_digest(a, b)``, **không dùng** ``==``.
         Toán tử ``==`` dừng ngay tại ký tự đầu khác nhau, nên thời gian trả
         lời rò rỉ thông tin về khóa (timing attack). ``compare_digest`` luôn
         chạy hết chuỗi.
      4. Hợp lệ → trả về ``x_user_id`` nếu client có gửi, ngược lại trả
         ``ANONYMOUS_USER``. user_id này là đơn vị để rate limit và tính chi phí.

    Gợi ý: dùng ``status.HTTP_401_UNAUTHORIZED`` cho dễ đọc.
    """
    # Khóa đúng lấy từ cấu hình (biến môi trường AGENT_API_KEY), không hardcode.
    expected_key = get_settings().agent_api_key

    # Thiếu header X-API-Key → 401 ngay. Kiểm tra `is None` riêng vì
    # compare_digest không nhận None.
    #
    # compare_digest (không dùng ==): `==` dừng ở ký tự đầu tiên khác nhau nên
    # thời gian phản hồi lộ ra "đoán đúng bao nhiêu ký tự đầu"; kẻ tấn công đo
    # thời gian rồi dò khóa từng ký tự (timing attack). compare_digest luôn
    # chạy hết độ dài chuỗi nên không rò rỉ thông tin đó.
    #
    # .encode("utf-8"): compare_digest với str chỉ chấp nhận ASCII, nếu client
    # gửi header có ký tự non-ASCII (ví dụ tiếng Việt) sẽ ném TypeError → 500.
    # So sánh trên bytes thì luôn an toàn và vẫn trả về 401 đúng như mong đợi.
    if x_api_key is None or not secrets.compare_digest(
        x_api_key.encode("utf-8"), expected_key.encode("utf-8")
    ):
        # Cùng một thông báo cho cả "thiếu khóa" và "sai khóa" để không tiết
        # lộ cho người lạ biết họ sai ở đâu.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )

    # Khóa hợp lệ → trả user_id. Đây là đơn vị để rate limit và tính chi phí.
    # Client không gửi X-User-Id thì gộp chung vào một user "anonymous".
    return x_user_id or ANONYMOUS_USER
