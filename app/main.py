"""Agent service — điểm ráp nối của cả lab (CP1, CP3, CP4).

Luồng một request tới /ask:

    client ──► verify_api_key ──► rate_limiter ──► cost_guard
                                                       │
                              store.get_history ◄──────┘
                                       │
                                    ask_llm
                                       │
                              store.append × 2 ──► cost_guard.record ──► log_event
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from utils.mock_llm import ask_llm

from .auth import verify_api_key
from .config import get_settings
from .cost_guard import CostGuard
from .lifecycle import lifecycle
from .logging_utils import log_event
from .rate_limiter import RateLimiter
from .store import ConversationStore, get_redis_client

SERVICE_NAME = "day12-agent"
SERVICE_VERSION = "1.0.0"


# ─────────────────────────────────────────────────────────────
# Providers — CHO SẴN
# Tách ra thành hàm để test có thể thay bằng Redis giả qua
# app.dependency_overrides, và để kết nối Redis chỉ tạo khi thật sự cần.
# ─────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_store() -> ConversationStore:
    return ConversationStore(get_redis_client())


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(get_redis_client(), get_settings().rate_limit_per_minute)


@lru_cache(maxsize=1)
def get_cost_guard() -> CostGuard:
    return CostGuard(get_redis_client(), get_settings().monthly_budget_usd)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """CHO SẴN — chạy lúc app khởi động và lúc tắt."""
    lifecycle.install()
    log_event("service_started", service=SERVICE_NAME, version=SERVICE_VERSION)
    yield
    log_event("service_stopped", service=SERVICE_NAME)


app = FastAPI(title="Day 12 Production Agent", version=SERVICE_VERSION, lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


# ─────────────────────────────────────────────────────────────
# Health & readiness
# ─────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Liveness probe — process còn sống không?

    Cách làm (CP1 + CP4):
      - Đang tắt dần (``lifecycle.shutting_down``) → trả
        ``JSONResponse(status_code=503, content={"status": "shutting_down"})``
      - Bình thường → ``{"status": "ok", "service": SERVICE_NAME,
        "version": SERVICE_VERSION}`` (mặc định FastAPI trả 200).

    Endpoint này phải **nhẹ**: không gọi Redis, không query DB. Nó chỉ trả
    lời câu hỏi "có cần restart container này không?". Nếu nó phụ thuộc
    Redis, Redis chết một nhịp là cả cụm container bị restart theo.
    """
    # Hàm này CỐ Ý không có tham số nào (không Depends, không verify_api_key):
    #   - Không nhận Depends(get_store)... → không chạm Redis. Redis chết một
    #     nhịp mà /health cũng lỗi thì platform sẽ restart cả cụm container.
    #   - Không cần API key → probe của platform không gửi key, bắt buộc key
    #     là tự khóa mình ngoài cửa.
    # Bộ test kiểm tra điều này bằng inspect.signature(health).

    # Nhận SIGTERM (đang deploy/scale-down): báo 503 để load balancer ngừng
    # đẩy request mới vào instance này trong lúc nó xử lý nốt các request dở.
    if lifecycle.shutting_down:
        return JSONResponse(status_code=503, content={"status": "shutting_down"})

    # Bình thường: chỉ trả lời "process còn sống" — FastAPI mặc định trả 200.
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}


@app.get("/ready")
def ready(store: ConversationStore = Depends(get_store)):
    """Readiness probe — đã sẵn sàng nhận traffic chưa?

    Cách làm (CP4):
      - Đang tắt dần → 503 ``{"status": "shutting_down"}``
      - ``store.ping()`` False → 503 ``{"status": "not ready", "redis": False}``
      - Ngược lại → ``{"status": "ready", "redis": True}``

    Khác /health ở chỗ: endpoint này ĐƯỢC PHÉP kiểm tra dependency. Load
    balancer dùng nó để quyết định có đẩy request vào instance này không.
    """
    # Kiểm tra theo thứ tự: đang tắt thì khỏi cần hỏi Redis nữa.
    if lifecycle.shutting_down:
        return JSONResponse(status_code=503, content={"status": "shutting_down"})

    # Khác /health: ở đây ĐƯỢC PHÉP (và cần) hỏi dependency. Redis lỗi → 503
    # để load balancer ngừng gửi request vào instance này. Nhưng đây chỉ là
    # "tạm ngừng nhận khách", KHÔNG khiến container bị restart — chính vì vậy
    # việc kiểm tra Redis nằm ở /ready chứ không phải /health. ping() đã nuốt
    # exception nên không bao giờ làm endpoint này trả 500.
    if not store.ping():
        return JSONResponse(
            status_code=503, content={"status": "not ready", "redis": False}
        )

    return {"status": "ready", "redis": True}


# ─────────────────────────────────────────────────────────────
# Endpoint chính
# ─────────────────────────────────────────────────────────────
@app.post("/ask")
def ask(
    payload: AskRequest,
    user_id: str = Depends(verify_api_key),
    store: ConversationStore = Depends(get_store),
    limiter: RateLimiter = Depends(get_rate_limiter),
    guard: CostGuard = Depends(get_cost_guard),
):
    """Hỏi agent một câu.

    Cách làm (CP3 + CP4) — làm ĐÚNG THỨ TỰ sau:
      1. ``limiter.check(user_id)``           → 429 nếu gọi quá nhanh
      2. ``guard.check(user_id)``             → 402 nếu hết ngân sách
      3. ``history = store.get_history(user_id)``
      4. ``result = ask_llm(payload.question, history)``
      5. ``store.append(user_id, "user", payload.question)`` và
         ``store.append(user_id, "assistant", result["answer"])``
      6. ``guard.record(user_id, result["cost_usd"])``
      7. ``log_event("ask_completed", user_id=user_id,
         tokens_in=result["tokens_in"], tokens_out=result["tokens_out"],
         cost_usd=result["cost_usd"])``
      8. trả về::

            {
                "answer": result["answer"],
                "user_id": user_id,
                "history_length": len(history),
                "cost_usd": result["cost_usd"],
                "tokens": {"in": result["tokens_in"], "out": result["tokens_out"]},
            }

    Vì sao check trước rồi mới gọi LLM? Vì tiền mất ở bước gọi LLM. Chặn sau
    khi đã gọi thì bạn vừa trả tiền vừa trả lỗi.

    ``user_id`` do ``verify_api_key`` trả về, nên request không có API key
    hợp lệ sẽ dừng ở 401 trước khi chạm vào bất cứ dòng nào ở đây.
    """
    # Bước 0 (đã xảy ra trước khi vào hàm): FastAPI chạy verify_api_key qua
    # Depends. Thiếu/sai khóa → 401 và dừng ở đó, nên request không hợp lệ
    # không bao giờ chạm tới limiter (không tiêu quota của ai) hay LLM.

    # 1. Rate limit: gọi quá nhanh → 429. Đặt TRƯỚC cost guard vì rẻ hơn và
    #    chặn được kẻ spam sớm nhất. Lưu ý check() cũng ghi nhận request này.
    limiter.check(user_id)

    # 2. Cost guard: đã hết ngân sách tháng → 402. Kiểm tra TRƯỚC khi gọi LLM
    #    vì tiền mất ở bước gọi LLM; chặn sau thì vừa trả tiền vừa trả lỗi.
    guard.check(user_id)

    # 3. Lấy lịch sử hội thoại TRƯỚC khi ghi lượt mới, để history_length trả
    #    về là số message đã có, không tính câu hỏi hiện tại.
    history = store.get_history(user_id)

    # 4. Gọi LLM (mock: tất định, không tốn tiền thật).
    result = ask_llm(payload.question, history)

    # 5. Lưu cả câu hỏi lẫn câu trả lời vào store (Redis ở bản thật) để request
    #    sau — kể cả rơi vào container khác — vẫn thấy được ngữ cảnh.
    store.append(user_id, "user", payload.question)
    store.append(user_id, "assistant", result["answer"])

    # 6. Ghi nhận chi phí SAU khi LLM đã trả kết quả (lúc này mới biết số
    #    token thật). Cộng dồn vào key cost:<user>:<YYYY-MM>.
    guard.record(user_id, result["cost_usd"])

    # 7. Log JSON một dòng để cloud lọc/đếm được (xem app/logging_utils.py).
    #    Chỉ log số liệu, không log nội dung câu hỏi (có thể chứa dữ liệu nhạy cảm).
    log_event(
        "ask_completed",
        user_id=user_id,
        tokens_in=result["tokens_in"],
        tokens_out=result["tokens_out"],
        cost_usd=result["cost_usd"],
    )

    # 8. Trả response.
    return {
        "answer": result["answer"],
        "user_id": user_id,
        "history_length": len(history),
        "cost_usd": result["cost_usd"],
        "tokens": {"in": result["tokens_in"], "out": result["tokens_out"]},
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
