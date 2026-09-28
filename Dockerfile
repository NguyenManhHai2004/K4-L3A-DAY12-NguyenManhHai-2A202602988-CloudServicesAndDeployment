# ═══════════════════════════════════════════════════════════════════
# CP2 — Containerization (bản production)
#
# So với bản 1-stage ban đầu, file này giải quyết 6 vấn đề:
#   [x] Multi-stage build: `builder` cài dependency, `runtime` chỉ nhận kết quả
#   [x] Base image slim, không dùng `python:3.11` bản đầy đủ (~1GB)
#   [x] COPY requirements.txt + cài thư viện TRƯỚC khi COPY source code
#   [x] Chạy bằng user thường (UID 10001), không phải root
#   [x] HEALTHCHECK gọi /health
#   [x] Đọc cổng từ biến môi trường PORT (cloud tự gán cổng)
#
# Build thử: docker build -t day12-agent:prod .
#            docker images day12-agent:prod     # xem dung lượng
# ═══════════════════════════════════════════════════════════════════


# ───────────────────────────────────────────────────────────────────
# Stage 1 — builder: nơi cài dependency. Stage này được phép "bẩn"
# (pip cache, công cụ build) vì nó bị vứt đi; chỉ /install được mang sang.
# ───────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Chỉ copy requirements.txt trước. Docker cache theo từng layer và hủy cache
# từ layer đầu tiên bị thay đổi trở đi. requirements.txt hiếm khi đổi, nên
# layer cài thư viện (chậm nhất) được dùng lại khi bạn chỉ sửa code.
COPY requirements.txt .

# --prefix=/install: cài vào một thư mục riêng để stage sau copy đúng thứ
# cần thiết. --no-cache-dir: không lưu cache tải về, image nhẹ hơn.
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ───────────────────────────────────────────────────────────────────
# Stage 2 — runtime: image thật sự được chạy/deploy. Chỉ chứa Python,
# thư viện đã cài, và source code. Không có pip cache hay công cụ build.
# ───────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# PYTHONUNBUFFERED: in log ra ngay, không đệm — nếu không, log JSON có thể
# đến muộn hoặc mất khi container bị dừng đột ngột.
# PYTHONDONTWRITEBYTECODE: không ghi file .pyc vào image.
# PORT: giá trị mặc định khi chạy local; cloud (Railway/Render/Cloud Run)
# sẽ ghi đè bằng cổng riêng của nó lúc chạy.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Tạo user thường trước khi chuyển sang nó. UID cố định (10001) để dễ phân
# quyền khi mount volume. Vì sao không dùng root: nếu kẻ tấn công khai thác
# được lỗ hổng trong app rồi thoát ra khỏi container, họ mang theo quyền root
# lên máy host. Chạy user thường thì quyền đó bị cắt ngay từ đầu.
RUN useradd --create-home --uid 10001 appuser

# Nhận thư viện đã cài từ stage builder vào /usr/local (nơi Python và
# lệnh `uvicorn` tự tìm thấy). Đây là bước "chỉ copy kết quả sang".
COPY --from=builder /install /usr/local

WORKDIR /app

# Source code copy SAU cùng: đây là thứ đổi thường xuyên nhất. Cần cả
# `utils/` (chứa mock_llm), thiếu nó thì app không import được.
COPY app ./app
COPY utils ./utils

# Từ dòng này trở đi mọi lệnh (và chính app) chạy bằng appuser.
USER appuser

# EXPOSE chỉ là tài liệu cho người đọc; cổng thật do biến PORT quyết định.
EXPOSE 8000

# Docker gọi /health định kỳ để biết container có còn phục vụ được không.
# Dùng Python có sẵn thay vì cài thêm curl (giữ image nhỏ). Đọc PORT để khớp
# với cổng mà cloud gán. `|| exit 1` báo lỗi rõ ràng khi gọi thất bại.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health').read()" || exit 1

# 0.0.0.0 (không phải 127.0.0.1): bind vào localhost thì bên ngoài container
# không gọi vào được. Dùng `sh -c` để shell mở rộng ${PORT:-8000}: dạng mảng
# thuần của CMD không đọc được biến môi trường.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
