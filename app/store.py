"""CP4 — Stateless: state sống ngoài process.

Nếu lịch sử hội thoại nằm trong một dict trong RAM, thì khi scale lên 3
instance, user hỏi câu 1 vào instance A và câu 2 vào instance B sẽ thấy agent
"mất trí nhớ". Container còn bị restart bất cứ lúc nào. Vì vậy state phải
nằm ở nơi mọi instance cùng nhìn thấy: Redis.
"""

from __future__ import annotations

import json

import redis

from .config import get_settings

HISTORY_MAX_MESSAGES = 20
HISTORY_TTL_SECONDS = 7 * 24 * 3600


def get_redis_client(url: str | None = None):
    """CHO SẴN — tạo client Redis từ URL.

    ``fake://`` trả về Redis giả chạy trong RAM, dùng khi máy bạn chưa có
    Docker. Tiện cho lúc học, nhưng KHÔNG dùng khi deploy: nó vẫn là state
    trong process, đúng cái mà CP4 đang tìm cách loại bỏ.
    """
    url = url or get_settings().redis_url
    if url.startswith("fake://"):
        import fakeredis

        return fakeredis.FakeRedis(decode_responses=True)
    return redis.from_url(url, decode_responses=True)


class ConversationStore:
    """Lưu lịch sử hội thoại của từng user trong Redis List."""

    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def _key(user_id: str) -> str:
        """CHO SẴN."""
        return f"history:{user_id}"

    def ping(self) -> bool:
        """Redis có trả lời không? Dùng cho endpoint /ready.

        TODO (CP4): gọi ``self.client.ping()`` trong try/except.
        Trả ``True`` nếu thành công, ``False`` nếu có bất kỳ Exception nào
        (mất mạng, sai mật khẩu, Redis chưa khởi động...).
        """
        # Nuốt MỌI exception (mất mạng, sai mật khẩu, Redis chưa lên...) và
        # đổi thành False. Nếu để exception thoát ra, /ready sẽ trả 500 thay
        # vì 503, và load balancer hiểu sai tình trạng của instance.
        try:
            self.client.ping()
            return True
        except Exception:
            return False

    def append(self, user_id: str, role: str, content: str) -> None:
        """Ghi thêm một lượt vào lịch sử.

        TODO (CP4):
          1. ``self.client.rpush(key, json.dumps({"role": role, "content": content},
             ensure_ascii=False))``
          2. ``self.client.ltrim(key, -HISTORY_MAX_MESSAGES, -1)`` — chỉ giữ
             ``HISTORY_MAX_MESSAGES`` message gần nhất, nếu không prompt sẽ
             phình vô hạn và tiền token cũng vậy.
          3. ``self.client.expire(key, HISTORY_TTL_SECONDS)`` — hội thoại cũ
             tự hết hạn, khỏi phải dọn tay.
        """
        key = self._key(user_id)

        # Mỗi lượt là một phần tử của Redis List, lưu dạng chuỗi JSON.
        # RPUSH thêm vào CUỐI list → thứ tự cũ nhất trước, mới nhất sau.
        # ensure_ascii=False để tiếng Việt lưu nguyên dạng, dễ đọc khi debug.
        self.client.rpush(
            key, json.dumps({"role": role, "content": content}, ensure_ascii=False)
        )

        # Chỉ giữ HISTORY_MAX_MESSAGES message MỚI NHẤT. Chỉ số âm đếm từ cuối:
        # (-N, -1) = N phần tử cuối. Viết nhầm (0, N-1) sẽ giữ N phần tử CŨ
        # nhất và vứt tin mới. Không cắt thì prompt dài vô hạn = tiền token
        # vô hạn.
        self.client.ltrim(key, -HISTORY_MAX_MESSAGES, -1)

        # Gia hạn TTL mỗi lần có hội thoại mới: user còn dùng thì lịch sử còn
        # sống, bỏ đi 7 ngày thì tự biến mất — Redis không đầy dần.
        self.client.expire(key, HISTORY_TTL_SECONDS)

    def get_history(self, user_id: str) -> list[dict]:
        """Đọc lịch sử hội thoại, cũ nhất trước.

        TODO (CP4): ``self.client.lrange(key, 0, -1)`` rồi ``json.loads``
        từng phần tử. Chưa có gì → trả về list rỗng.
        """
        # LRANGE 0..-1 = toàn bộ list, cũ nhất trước. Key chưa tồn tại thì
        # Redis trả list rỗng nên không cần xử lý riêng trường hợp "chưa có gì".
        # State nằm ở Redis chứ không ở biến trong process, nên mọi container
        # (kể cả khi scale ra nhiều instance) đều thấy cùng một lịch sử.
        raw_turns = self.client.lrange(self._key(user_id), 0, -1)
        return [json.loads(turn) for turn in raw_turns]

    def clear(self, user_id: str) -> None:
        """CHO SẴN — xóa lịch sử của một user."""
        self.client.delete(self._key(user_id))
