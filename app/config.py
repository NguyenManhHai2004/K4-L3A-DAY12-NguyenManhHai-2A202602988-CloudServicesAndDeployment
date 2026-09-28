"""CP1 — Cấu hình theo 12-Factor.

Nguyên tắc: **không có giá trị cấu hình nào nằm trong code**. Tất cả đến từ
biến môi trường, để cùng một image chạy được ở laptop, staging và production
mà không phải sửa một dòng code nào.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Toàn bộ cấu hình của service.

    Cách làm (CP1): khai báo các trường dưới đây. pydantic-settings tự đọc biến
    môi trường theo tên trường (không phân biệt hoa thường), nên trường
    ``agent_api_key`` sẽ lấy giá trị từ biến ``AGENT_API_KEY``.

    | Trường                  | Kiểu  | Mặc định                   |
    |-------------------------|-------|----------------------------|
    | port                    | int   | 8000                       |
    | agent_api_key           | str   | KHÔNG có mặc định (bắt buộc)|
    | redis_url               | str   | "redis://localhost:6379/0" |
    | rate_limit_per_minute   | int   | 10                         |
    | monthly_budget_usd      | float | 10.0                       |
    | log_level               | str   | "INFO"                     |

    Vì sao ``agent_api_key`` không được có giá trị mặc định? Vì mặc định
    nghĩa là app vẫn khởi động khi bạn quên set secret trên cloud — và bạn
    chỉ phát hiện ra khi ai đó đã gọi API miễn phí bằng khóa mặc định đó.
    Không mặc định = fail fast ngay lúc khởi động.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Cổng HTTP mà uvicorn lắng nghe. Các platform như Railway/Render tự gán
    # biến PORT lúc chạy, nên KHÔNG được hardcode 8000 ở chỗ nào khác trong
    # code — 8000 chỉ là giá trị dự phòng khi chạy trên laptop.
    port: int = 8000

    # SECRET: cố ý KHÔNG có giá trị mặc định. Thiếu biến AGENT_API_KEY thì
    # Settings() ném ValidationError ngay lúc khởi động (fail fast) thay vì
    # âm thầm chạy với một khóa yếu. Giá trị thật chỉ nằm trong `.env` (đã bị
    # .gitignore) hoặc trong dashboard của cloud, không bao giờ nằm trong repo.
    agent_api_key: str

    # Địa chỉ Redis — nơi giữ mọi state (lịch sử chat, rate limit, chi phí)
    # để app stateless và scale ngang được. Mặc định trỏ tới Redis chạy local
    # bằng `docker compose up -d redis`. Trong docker-compose sẽ ghi đè thành
    # redis://redis:6379/0 (tên service, không phải localhost).
    redis_url: str = "redis://localhost:6379/0"

    # Số request tối đa mỗi user mỗi phút; vượt quá thì /ask trả 429.
    rate_limit_per_minute: int = 10

    # Ngân sách LLM mỗi user mỗi tháng (USD); vượt quá thì /ask trả 402.
    # Dùng float vì chi phí mỗi lượt gọi rất nhỏ (cỡ 0.0001 USD).
    monthly_budget_usd: float = 10.0

    # Mức log tối thiểu (DEBUG/INFO/WARNING/ERROR). Production để INFO,
    # khi cần điều tra sự cố chỉ cần đổi biến môi trường, không sửa code.
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Đọc cấu hình một lần rồi cache lại (đọc env mỗi request là lãng phí)."""
    return Settings()
