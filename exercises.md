# Phiếu Phản Ánh — K4 Level 3A, Ngày 12

> **Bài làm cá nhân.** Trả lời bằng lời của chính bạn, dựa trên những gì bạn
> quan sát được khi chạy code — không sao chép đáp án của người khác.
>
> Cách trả lời: thay dòng `> *Câu trả lời của bạn*` bằng câu trả lời.
> `grade.py` đếm số câu đã trả lời (15 điểm cho 10 câu).
>
> Họ và tên: ....Nguyễn Mạnh Hải....  Mã học viên: ...2A202602988......

---

### Câu 1 — Fail fast (CP1)

Trong `Settings`, `agent_api_key` không có giá trị mặc định nên app chết ngay
khi khởi động nếu thiếu biến môi trường. Hãy mô tả một tình huống cụ thể mà
việc "chết sớm" này cứu bạn, so với việc để mặc định `"changeme"`.

> Tình huống: mình deploy lên Render nhưng quên đặt `AGENT_API_KEY` trong
> dashboard. Nếu để mặc định `"changeme"` thì service vẫn lên, `/health` vẫn
> xanh, mình tưởng deploy thành công, trong khi ai đoán được `"changeme"` đều
> gọi `/ask` miễn phí và đốt ngân sách LLM của mình mà mình không hề biết.
>
> Khi thử thật: chạy container **không có** `AGENT_API_KEY` thì app thoát ngay
> (exit code 3, log `agent_api_key — Field required` rồi `Application startup
> failed`), còn có key thì chạy bình thường. Lỗi hiện ra ngay ở bước deploy
> chứ không nằm chờ đến khi có người gọi API.
>
> Mình cũng phát hiện ra một chỗ hở: ban đầu `get_settings()` chỉ được gọi khi
> có request đầu tiên, nên thiếu key thì container vẫn `running`, `/health`
> trả 200 và `/ask` trả 500 — đúng kiểu lỗi khó thấy nhất. Mình sửa bằng cách
> gọi `get_settings()` ngay trong `lifespan` lúc khởi động. Vậy fail fast chỉ
> có tác dụng khi cấu hình thật sự được đọc ở lúc khởi động.

---

### Câu 2 — Log cho máy đọc (CP1)

Chạy service và gọi `/ask` vài lần. Dán một dòng log JSON bạn thu được, rồi
nêu **hai** việc bạn làm được với dòng log đó mà `print("đã trả lời xong")`
không làm được.

> Một dòng log thật lấy từ `docker compose logs agent` sau khi gọi `/ask`:
>
> ```
> {"event": "ask_completed", "level": "info", "timestamp": "2026-09-28T09:02:03.056944+00:00", "user_id": "cp4b", "tokens_in": 43, "tokens_out": 44, "cost_usd": 3.285e-05}
> ```
>
> Hai việc làm được nhờ log JSON:
> 1. **Lọc và tổng hợp theo trường**: ví dụ lọc `event = "ask_completed"` rồi
>    cộng `cost_usd` theo từng `user_id` để biết ai tiêu bao nhiêu tiền.
>    `print("đã trả lời xong")` chỉ là một câu chữ, không có `user_id` hay
>    `cost_usd` để cộng.
> 2. **Cảnh báo và sắp xếp theo thời gian tự động**: cloud đọc được `level`
>    và `timestamp` nên đặt được luật "báo khi `level = error`" hoặc vẽ biểu
>    đồ số request theo thời gian. Với `print` phải tự viết regex để cắt chuỗi,
>    và chỉ cần đổi câu chữ là hỏng.

---

### Câu 3 — Kích thước image (CP2)

Build cả hai phiên bản và ghi lại số đo thật:

```bash
docker build -f <Dockerfile-1-stage> -t agent:single .
docker build -t agent:multi .
docker images | grep agent
```

| Bản | Dung lượng |
|-----|-----------|
| 1 stage (bản đầu) | 1.73 GB |
| Multi-stage | 271 MB |

Giải thích: phần dung lượng chênh lệch đó là những gì?

> Số đo lấy từ `docker images` (image multi-stage tag là `day12-agent:prod`).
> Chênh lệch khoảng 1.46 GB, chủ yếu đến từ **base image**: bản 1 stage dùng
> `python:3.11` đầy đủ nặng 1.61 GB, còn `python:3.11-slim` chỉ 189 MB. Bản
> đầy đủ mang theo trình biên dịch và bộ công cụ build; `docker history` cho
> thấy hai layer cài apt lớn nhất là 694 MB và 202 MB. Ngoài ra bản 1 stage
> còn `COPY . .` và `pip install` (95 MB) ngay trong image cuối.
>
> Bản multi-stage cài thư viện ở stage `builder`, rồi chỉ `COPY --from=builder
> /install /usr/local` (65.5 MB) sang stage `runtime` dựa trên slim. Compiler,
> cache của pip và mọi thứ chỉ cần lúc build đều bị bỏ lại ở stage builder.

---

### Câu 4 — Thứ tự lệnh trong Dockerfile (CP2)

Sửa một ký tự trong `app/main.py` rồi build lại. Với Dockerfile của bạn, những
layer nào được dùng lại từ cache, layer nào phải chạy lại? Nếu bạn đặt
`COPY . .` lên trước `RUN pip install` thì kết quả khác thế nào?

> Mình sửa 1 ký tự trong `app/main.py` rồi build lại (làm trên bản sao thư mục
> để không đụng vào repo). Kết quả với Dockerfile của mình:
>
> | Layer | Trạng thái |
> |---|---|
> | builder: `WORKDIR /build`, `COPY requirements.txt .`, `RUN pip install ...` | **CACHED** |
> | runtime: `useradd`, `COPY --from=builder /install /usr/local`, `WORKDIR /app` | **CACHED** |
> | runtime: `COPY app ./app` | chạy lại (vì `main.py` đổi) |
> | runtime: `COPY utils ./utils` | chạy lại |
>
> `COPY utils` chạy lại dù `utils/` không đổi, vì Docker hủy cache **từ layer
> đầu tiên bị thay đổi trở đi**. Quan trọng là bước `pip install` nằm trước
> nên vẫn được dùng lại từ cache.
>
> Khi thử đặt `COPY . .` lên trước `RUN pip install` (Dockerfile 1 stage đơn
> giản), sửa đúng 1 ký tự thì `COPY . .` chạy lại và kéo theo `pip install`
> chạy lại, mất khoảng **34 giây** để cài lại toàn bộ thư viện. Do đó mỗi lần
> sửa một dấu phẩy trong code là phải chờ cài thư viện lại.

---

### Câu 5 — Vì sao không chạy bằng root (CP2)

Container mặc định chạy bằng root. Mô tả chuỗi sự kiện dẫn từ "một lỗ hổng
trong code Python của bạn" tới "kẻ tấn công có quyền cao trên máy host", và
lệnh `USER` cắt đứt chuỗi đó ở chỗ nào.

> Chuỗi sự kiện: (1) code của mình có lỗ hổng, ví dụ cho phép chạy lệnh tùy ý
> hoặc đọc/ghi file tùy ý; (2) kẻ tấn công khai thác và chạy được lệnh bên
> trong container; (3) vì process chạy bằng root nên họ có quyền root trong
> container: đọc mọi file, sửa file hệ thống, cài công cụ, đọc mọi secret;
> (4) nếu container còn cấu hình lỏng (mount thư mục host, cờ đặc quyền, hoặc
> một lỗ hổng kernel/runtime) thì root trong container dễ trở thành quyền cao
> trên máy host.
>
> Lệnh `USER appuser` (UID 10001) cắt chuỗi ở bước (3): kẻ tấn công vào được
> container thì cũng chỉ có quyền của một user thường, không ghi được vào
> thư mục hệ thống và khó tiến thêm bước (4). Mình đã kiểm tra bằng
> `docker run --rm day12-agent:prod id` cho ra `uid=10001(appuser)`.

---

### Câu 6 — Cửa sổ trượt (CP3)

Rate limit của bạn dùng sliding window 60 giây. Nếu thay bằng cách đếm theo
phút đồng hồ (reset lúc giây 00), một người dùng có thể gửi tối đa bao nhiêu
request trong 2 giây liên tiếp khi hạn mức là 10/phút? Giải thích cách đạt được
con số đó.

> Tối đa **20 request** trong 2 giây. Đếm theo phút đồng hồ thì bộ đếm reset
> về 0 đúng lúc giây 00. Người dùng gửi 10 request ở giây :59 (đủ hạn mức của
> phút đó), rồi chỉ 1–2 giây sau, sang phút mới bộ đếm về 0 nên gửi thêm 10
> request nữa ở giây :00. Tổng 20 request trong khoảng 2 giây mà không phút
> nào bị chặn.
>
> Cửa sổ trượt không có kẽ hở này vì luôn đếm số request trong **60 giây gần
> nhất** tính từ thời điểm hiện tại: 10 request lúc :59 vẫn còn nằm trong cửa
> sổ ở giây :00 nên request thứ 11 bị chặn (429).

---

### Câu 7 — Rate limit và cost guard (CP3)

Hai cơ chế này khác nhau ở điểm nào? Cho một tình huống mà rate limit cho qua
nhưng cost guard phải chặn, và một tình huống ngược lại.

> Khác nhau: rate limit giới hạn **số lượng** request theo thời gian (10/phút,
> trả 429), còn cost guard giới hạn **số tiền** đã tiêu trong tháng (trả 402).
>
> - Rate limit cho qua nhưng cost guard phải chặn: một user chỉ gửi 5
>   request/phút, dưới hạn mức, nhưng mỗi request kèm lịch sử rất dài nên tốn
>   hàng chục nghìn token. Số lượng thì ít, nhưng ngân sách tháng vẫn cạn.
> - Ngược lại, cost guard cho qua nhưng rate limit phải chặn: một script gửi
>   liên tục hàng trăm câu hỏi rất ngắn trong một phút. Mỗi câu chỉ tốn vài
>   phần nghìn xu nên tổng tiền vẫn còn xa ngân sách, nhưng số request vượt
>   xa 10/phút nên bị 429 (bảo vệ server khỏi bị dồn dập).

---

### Câu 8 — /health khác /ready (CP4)

Nếu gộp hai endpoint làm một và cho nó kiểm tra Redis, chuyện gì xảy ra với cụm
3 container khi Redis mất kết nối 30 giây? Trả lời theo đúng thứ tự sự kiện.

> Theo thứ tự:
> 1. Redis mất kết nối.
> 2. Endpoint gộp kiểm tra Redis nên cả 3 container đều trả 503 (unhealthy),
>    dù process của chúng vẫn sống bình thường.
> 3. Orchestrator hiểu là container hỏng nên **restart cả 3 cùng lúc**.
> 4. Trong lúc restart không còn container nào phục vụ, người dùng nhận lỗi
>    kể cả với những việc không cần Redis.
> 5. Redis quay lại sau 30 giây nhưng các container vẫn đang khởi động lại,
>    nên hệ thống còn gián đoạn thêm một lúc. Sự cố nhỏ ở Redis biến thành
>    sự cố toàn hệ thống.
>
> Tách ra thì `/health` (liveness) không chạm Redis nên luôn 200, container
> không bị restart; còn `/ready` trả 503 nên load balancer chỉ tạm ngừng gửi
> request, chờ Redis quay lại thì nhận traffic trở lại.

---

### Câu 9 — Stateless (CP4)

Chạy `docker compose up --scale agent=3` rồi gọi `/ask` nhiều lần với cùng một
`X-User-Id`. Quan sát `history_length` trong response. Nếu lịch sử được lưu
trong một dict Python thay vì Redis, bạn sẽ thấy con số đó thay đổi thế nào?

> Mình chạy 3 container `agent` sau nginx (cổng 8000) rồi gọi `/ask` 6 lần với
> cùng một `X-User-Id`. Dãy `history_length` thu được: **0, 2, 4, 6, 8, 10**,
> tăng đều 2 mỗi lượt (1 câu hỏi + 1 câu trả lời). Log cho thấy mỗi container
> xử lý đúng 2 trong 6 request, tức là request thật sự rơi vào các container
> khác nhau mà lịch sử vẫn liền mạch, vì mọi container cùng đọc một Redis.
>
> Nếu lưu trong dict Python thì mỗi container có dict riêng trong RAM. Nginx
> chia vòng tròn A → B → C → A... nên ba request đầu mỗi container đều thấy
> lịch sử rỗng, dự đoán dãy sẽ là **0, 0, 0, 2, 2, 2** thay vì tăng đều: agent
> "mất trí nhớ" một cách ngẫu nhiên tùy request rơi vào container nào (đây là
> suy luận từ cách round-robin hoạt động, mình chưa chạy thử bản dict).

---

### Câu 10 — Deploy thật (CP5)

Ghi lại **một** lỗi bạn gặp khi deploy lên cloud (build fail, health check
timeout, sai REDIS_URL, app không đọc `$PORT`...): thông báo lỗi là gì, bạn
tìm ra nguyên nhân bằng cách nào, và sửa ra sao?

> Lỗi: lúc đầu mình thử deploy lên **Railway** bằng CLI. Chạy `railway init
> --name day12-agent` (đã đăng nhập và chọn đúng workspace của mình) thì CLI
> dừng với thông báo: `Your trial has expired. Please select a plan to
> continue using Railway.` và project không được tạo.
>
> Cách tìm nguyên nhân: đăng nhập thì thành công (`railway whoami` hiện đúng
> email), nên không phải lỗi token hay cấu hình. Thông báo lỗi nói thẳng là
> gói dùng thử của tài khoản đã hết hạn, và `railway status` sau đó báo
> chưa có project nào được liên kết.
>
> Cách sửa: chuyển sang **Render**, vì repo đã có sẵn `render.yaml`. Mình tạo
> Blueprint từ repo GitHub, Render tự tạo web service `day12-agent` và Redis
> (Key Value) `day12-redis`, nối `REDIS_URL` bằng `fromService`. Sau đó gọi
> `/health` → 200, `/ready` → 200 với `redis: true`, `/ask` không key → 401.
>
> Một lỗi nhỏ khác gặp sau đó: gọi `/ask` bằng khóa mới thì bị 401. Mình thử
> cả hai khóa và thấy Render đang dùng khóa local (`AGENT_API_KEY` trong
> `.env`) chứ không phải khóa mới, vì lúc tạo Blueprint đã dán nhầm khóa cũ.
