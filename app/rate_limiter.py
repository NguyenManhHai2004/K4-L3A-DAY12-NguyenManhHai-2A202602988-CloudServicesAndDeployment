"""CP3 — Rate limiting bằng thuật toán sliding window.

Đếm số request trong 60 giây **gần nhất** (cửa sổ trượt), thay vì đếm theo
phút đồng hồ. Đếm theo phút đồng hồ có lỗ hổng: 10 request lúc 10:00:59 và
10 request lúc 10:01:01 = 20 request trong 2 giây mà vẫn "đúng luật".

Cấu trúc dữ liệu: Redis Sorted Set (ZSET), score = timestamp của request.
"""

from __future__ import annotations

import time
import uuid

from fastapi import HTTPException, status

WINDOW_SECONDS = 60


class RateLimiter:
    def __init__(self, client, limit_per_minute: int) -> None:
        self.client = client
        self.limit = limit_per_minute

    @staticmethod
    def _key(user_id: str) -> str:
        """CHO SẴN — mỗi user một key riêng."""
        return f"ratelimit:{user_id}"

    def hit_count(self, user_id: str, now: float | None = None) -> int:
        """Số request của user trong ``WINDOW_SECONDS`` giây gần nhất.

        TODO (CP3):
          1. ``now = now if now is not None else time.time()``
          2. Xóa các entry cũ hơn cửa sổ:
             ``self.client.zremrangebyscore(key, 0, now - WINDOW_SECONDS)``
          3. Trả về ``self.client.zcard(key)``
        """
        # Cho phép test "tiêm" thời gian giả (now=1000.0...) để kiểm tra cửa sổ
        # trượt mà không phải chờ 60 giây thật. Không dùng `now or time.time()`
        # vì now=0.0 là giá trị hợp lệ nhưng bị coi là falsy.
        now = now if now is not None else time.time()
        key = self._key(user_id)

        # Vứt các request đã trượt ra khỏi cửa sổ: score (timestamp) từ 0 tới
        # now-60 là quá cũ. Đây chính là chỗ làm nên "cửa sổ trượt".
        self.client.zremrangebyscore(key, 0, now - WINDOW_SECONDS)

        # Số phần tử còn lại trong ZSET = số request trong 60 giây gần nhất.
        return self.client.zcard(key)

    def check(self, user_id: str, now: float | None = None) -> None:
        """Cho qua nếu còn quota, ngược lại raise 429.

        TODO (CP3):
          1. ``now = now if now is not None else time.time()``
          2. Gọi ``self.hit_count(user_id, now)``.
          3. Nếu số đó ``>= self.limit`` → raise
             ``HTTPException(status_code=429, detail="rate limit exceeded",
                             headers={"Retry-After": str(WINDOW_SECONDS)})``
          4. Chưa vượt → ghi nhận request này:
             ``self.client.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})``
             (member phải là chuỗi DUY NHẤT, nếu không hai request cùng
             timestamp sẽ ghi đè nhau và bạn đếm thiếu)
             rồi ``self.client.expire(key, WINDOW_SECONDS)`` để key tự dọn.

        Lưu ý thứ tự: **kiểm tra trước, ghi nhận sau**. Ghi trước rồi mới đếm
        sẽ chặn nhầm ngay ở request thứ ``limit``.
        """
        now = now if now is not None else time.time()

        # ĐẾM TRƯỚC, GHI SAU. Nếu ghi request này rồi mới đếm thì request thứ
        # `limit` đã tự đếm chính nó và bị chặn nhầm (limit=3 mà chỉ cho 2).
        # hit_count cũng dọn luôn các entry đã ra khỏi cửa sổ.
        if self.hit_count(user_id, now) >= self.limit:
            # 429 Too Many Requests. Retry-After báo cho client biết chờ tối
            # đa bao lâu (một cửa sổ) trước khi thử lại.
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )

        key = self._key(user_id)
        # Ghi nhận request này. Member PHẢI duy nhất: ZSET là tập hợp nên hai
        # request cùng timestamp mà trùng member chỉ được giữ một → đếm thiếu
        # và kẻ gọi nhanh lách được giới hạn. uuid4 đảm bảo không trùng.
        # Score = now để lần sau zremrangebyscore biết request nào đã cũ.
        self.client.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})

        # Key tự hết hạn sau một cửa sổ nếu user ngừng gọi, khỏi phải dọn tay.
        self.client.expire(key, WINDOW_SECONDS)
