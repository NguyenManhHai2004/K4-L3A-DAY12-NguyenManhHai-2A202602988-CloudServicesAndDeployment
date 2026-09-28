"""CP1 — Structured logging.

`print("user abc hỏi gì đó")` là log cho người đọc. Cloud (Railway, Render,
Cloud Run, Datadog...) đọc log bằng máy: một dòng = một JSON object thì mới
lọc/đếm/cảnh báo được. Đây là khác biệt lớn giữa localhost và production.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """CHO SẴN — thời điểm hiện tại theo ISO-8601, múi giờ UTC."""
    return datetime.now(timezone.utc).isoformat()


def log_event(event: str, level: str = "info", **fields) -> str:
    """Ghi một dòng log JSON ra stdout.

    TODO (CP1): tạo dict gồm tối thiểu 3 khóa
        - "event"     : tên sự kiện, lấy từ tham số ``event``
        - "level"     : mức log, VIẾT THƯỜNG (dùng ``level.lower()``)
        - "timestamp" : ``utc_now_iso()``
    rồi gộp thêm mọi cặp key/value trong ``**fields``.

    In chuỗi JSON đó ra stdout **trên một dòng duy nhất**
    (``json.dumps(..., ensure_ascii=False)``, đừng dùng ``indent``) và
    trả về chính chuỗi đó.

    Ví dụ:
        >>> log_event("ask_completed", user_id="sv01", cost_usd=0.0001)
        '{"event": "ask_completed", "level": "info", "timestamp": "...", ...}'
    """
    # Ba khóa bắt buộc để mọi log đều lọc/sắp xếp được trên dashboard cloud.
    # level.lower(): người gọi có thể truyền "ERROR" hay "Error", nhưng log
    # luôn ra "error" để query `level = "error"` không bỏ sót dòng nào.
    record = {
        "event": event,
        "level": level.lower(),
        "timestamp": utc_now_iso(),
        # Gộp các trường tùy ý (user_id, cost_usd, ...) vào cùng một object
        # phẳng, mỗi trường thành một cột có thể lọc được.
        **fields,
    }

    # - ensure_ascii=False: giữ nguyên tiếng Việt thay vì \uXXXX cho dễ đọc.
    # - KHÔNG dùng indent: JSON nhiều dòng sẽ bị hệ thống thu log tách thành
    #   nhiều bản ghi rời rạc (cloud thu log theo từng dòng).
    # - default=str: nếu lỡ truyền vào giá trị không serialize được (datetime,
    #   Path, ...) thì đổi sang chuỗi, để việc ghi log không bao giờ làm sập
    #   request đang xử lý.
    line = json.dumps(record, ensure_ascii=False, default=str)

    # flush=True: đẩy ngay ra stdout, tránh mất log nếu container bị kill
    # trước khi buffer được xả (stdout khi không phải terminal thường bị đệm).
    print(line, file=sys.stdout, flush=True)
    return line
