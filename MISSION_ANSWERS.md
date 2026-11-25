# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found
Trong `01-localhost-vs-production/develop/app.py` có các anti-pattern sau:
1. **Hardcode secrets trong source code** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"`, `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên GitHub sẽ lộ ngay thông tin nhạy cảm.
2. **Không quản lý cấu hình tập trung qua biến môi trường** (dòng 21–22): gán cứng `DEBUG = True`, `MAX_TOKENS = 500`, không phân biệt môi trường dev/staging/production.
3. **Dùng `print()` thay cho structured logging và làm lộ secret ra log** (dòng 33–38): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` vừa khó tổng hợp log (không phải JSON), vừa ghi thẳng API key ra stdout.
4. **Thiếu health check / readiness endpoint** (dòng 42–43): không có `/health` hay `/ready`, nên nền tảng cloud/load balancer không biết khi nào app chết để restart hoặc chưa sẵn sàng để tránh route traffic.
5. **Hardcode `host="localhost"`, `port=8000`, `reload=True` và không xử lý graceful shutdown** (dòng 49–54): chỉ bind `localhost` nên không nhận kết nối từ ngoài container; cố định cổng `8000` thay vì đọc `PORT`; bật `reload=True` ở production; không bắt `SIGTERM` để hoàn thành request đang chạy trước khi tắt.

### Exercise 1.2: Test bản develop
```bash
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Kết quả kiểm tra thêm bản `production`:
```bash
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":10.7,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:59:20.232033+00:00"}

$ curl http://localhost:8000/ready
{"ready":true}

$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}
```

### Exercise 1.3: Comparison table
| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Why Important? |
|---------|----------------------------|------------------------------------------------|----------------|
| Config / Secrets | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG`, `MAX_TOKENS` trực tiếp trong code | Đọc từ biến môi trường qua `Settings` (`os.getenv(...)`) trong `config.py` và gọi `validate()` | Tránh lộ secret lên Git, đổi cấu hình linh hoạt giữa dev/staging/prod và fail-fast nếu thiếu key ở production |
| Health / Readiness | Không có | Có `GET /health` (liveness) và `GET /ready` (trả `503` khi `is_ready` là `False`) | Giúp cloud platform/load balancer biết app còn sống để restart và chỉ gửi traffic khi app sẵn sàng |
| Logging | Dùng `print()` dạng text tự do, in cả `OPENAI_API_KEY` | Dùng `logging` format JSON (`{"time":...,"level":...,"msg":...}`), chỉ log `question_length`, `client_ip`, `response_length` | Dễ parse/tìm kiếm trên hệ thống log tập trung (Loki, Datadog) và không làm rò rỉ dữ liệu nhạy cảm |
| Host / Port / Reload | Hardcode `host="localhost"`, `port=8000`, `reload=True` | Đọc `HOST` (mặc định `0.0.0.0`), `PORT` (mặc định `8000`), `reload=settings.debug` | `0.0.0.0` cho phép nhận request từ ngoài container; `PORT` động tương thích Railway/Render; tắt reload ở prod |
| Graceful Shutdown | Không xử lý signal, tắt đột ngột | Dùng `@asynccontextmanager lifespan` (đặt `is_ready = False` khi shutdown) và `signal.signal(signal.SIGTERM, handle_sigterm)` | Đảm bảo request đang xử lý được hoàn thành trước khi container/process dừng, tránh lỗi 5xx cho người dùng |

**Ví dụ anti-pattern đã được sửa (Develop vs Production):**
- **Hardcode secret & config:**
  - `develop/app.py` (dòng 17): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"`
  - `production/config.py` (dòng 27, 32): `openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))` và `api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))` (kèm `validate()` bắt buộc có `AGENT_API_KEY` khi `environment == "production"`).

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions
1. **Base image:** `python:3.11` (full Python distribution, dung lượng lớn ~1 GB vì chứa nhiều công cụ hệ thống và build tools).
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Copy order (`requirements.txt` trước `COPY app.py` / `COPY . .`):** Tận dụng **Docker layer cache**. `requirements.txt` ít thay đổi hơn source code, nên khi chỉ sửa code, Docker dùng lại layer đã `pip install` từ cache thay vì tải và cài lại toàn bộ thư viện.
4. **CMD vs ENTRYPOINT:**
   - `CMD ["python", "app.py"]` định nghĩa lệnh mặc định khi container khởi động và **có thể bị ghi đè** dễ dàng bằng tham số truyền thêm ở cuối `docker run`.
   - `ENTRYPOINT` định nghĩa tiến trình chính cố định của container; nếu kết hợp cả hai thì `CMD` đóng vai trò là tham số mặc định truyền cho `ENTRYPOINT`.

### Exercise 2.2: Container test output
```bash
$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Image size comparison
- **Multi-stage build (`02-docker/production/Dockerfile`):**
  - Stage 1 (`builder`, từ `python:3.11-slim`): cài `gcc`, `libpq-dev` và `pip install --user` vào `/root/.local`.
  - Stage 2 (`runtime`, từ `python:3.11-slim`): chỉ copy `/root/.local` sang `/home/appuser/.local`, copy code cần chạy và chạy bằng non-root user `appuser`. Không mang theo `gcc`, `libpq-dev` hay apt cache nên image nhẹ hơn nhiều.
- Kết quả `docker images | grep my-agent`:
  ```text
  IMAGE               ID             DISK USAGE   CONTENT SIZE   EXTRA
  my-agent:advanced   8ff1faee2f07        240MB         57.4MB
  my-agent:develop    b7e5d1a11dce       1.67GB          426MB
  ```
- Develop (`my-agent:develop`): **1.67 GB (1670 MB)** disk usage (**426 MB** content size)
- Production (`my-agent:advanced`): **240 MB** disk usage (**57.4 MB** content size)
- Difference: giảm **85.6%** disk usage (tương đương giảm **86.5%** content size)

### Exercise 2.4: Docker Compose stack & Nginx test
- **Sơ đồ các service (`02-docker/production/docker-compose.yml`):**
  ```text
  Client ──(HTTP :80)──▶ nginx (reverse proxy / load balancer)
                              │
                              ▼ (mạng internal)
                            agent (:8000, depends_on redis & qdrant healthy)
                           /     \
                          ▼       ▼
                   redis (:6379)  qdrant (:6333)
  ```
  Các service cùng nằm trong network `internal`, giao tiếp qua service name (`redis://redis:6379/0`, `http://qdrant:6333`), `agent` không expose port trực tiếp ra host mà đi qua `nginx` ở cổng `80`.
- **Kết quả test qua Nginx:**
```bash
$ curl http://localhost/health
{"status":"ok","uptime_seconds":258.1,"version":"2.0.0","timestamp":"2026-11-25T09:24:36.202805"}

$ curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Railway hoặc Render deployment (Agent Part 6)
- Platform: <!-- Railway / Render -->
- Public URL: <!-- https://your-app.railway.app -->
- Screenshots: `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

### So sánh `railway.toml` và `render.yaml`
- **`railway.toml` (TOML, cấu hình cho 1 service):** Tập trung vào cách build (`builder = "DOCKERFILE"`, `dockerfilePath`) và chính sách chạy/restart (`healthcheckPath = "/health"`, `healthcheckTimeout`, `restartPolicyType`). Biến môi trường và secret thường được quản lý tách rời trên Railway Dashboard hoặc qua `railway variables set` vì một project Railway có thể gắn nhiều service (như Redis) qua UI/CLI.
- **`render.yaml` (YAML Blueprint, Infrastructure as Code cho nhiều resource):** Khai báo đầy đủ danh sách `services` (`type: web`, `runtime: docker`, `healthCheckPath: /health`) lẫn `envVars` ngay trong file; hỗ trợ `generateValue: true` (tự sinh secret ngẫu nhiên) và `sync: false` (nhắc người dùng nhập secret khi deploy, không lưu plain-text vào Git). Nhờ đó có thể dựng lại toàn bộ stack từ repo chỉ bằng một Blueprint.

### Exercise 3.3: Cloud Run CI/CD Pipeline (`cloudbuild.yaml` & `service.yaml`)
Pipeline trong `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` tự động chạy 4 bước tuần tự khi push lên nhánh `main`: (1) **Test** — dùng `python:3.11-slim` cài dependencies và chạy `pytest tests/ -v`; (2) **Build** — build Docker image gắn tag `$COMMIT_SHA` và `latest` (tận dụng `--cache-from`); (3) **Push** — đẩy image lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`); (4) **Deploy** — dùng `gcloud run deploy` triển khai lên Cloud Run (`asia-southeast1`), cấu hình autoscale `min-instances=1`, `max-instances=10`, và nạp secret từ Secret Manager. File `service.yaml` mô tả cấu hình dịch vụ Cloud Run dạng IaC (tài nguyên CPU/RAM, `containerConcurrency: 80`, `livenessProbe` ở `/health`, `startupProbe` ở `/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`develop`)
```text
[No Key] HTTP 401: {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
[With Key] HTTP 200: {"question":"hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2 - 4.3: JWT & Rate Limiting (`production`, đã che token)
```text
[No Token] HTTP 401: {"detail":"Authentication required. Include: Authorization: Bearer <token>"}
[Auth Token] HTTP 200: token_len=168 (masked: eyJhbGciOiJI...)
[Req 01] HTTP 200: {"question":"hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}
[Req 02] HTTP 200
...
[Req 09] HTTP 200
[Req 10] HTTP 200: {"question":"hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":0,"budget_remaining_usd":0.000188}}
[Req 11] HTTP 429: {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
[Req 12] HTTP 429: {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost guard implementation
- **Cách hoạt động (`04-api-gateway/production/cost_guard.py`):**
  1. Trước khi gọi LLM, `check_budget(user_id)` kiểm tra cả **global daily budget** (`global_daily_budget_usd`, vượt → trả `503`) và **per-user daily budget** (`daily_budget_usd`, vượt → trả `402 Payment Required`), đồng thời ghi log cảnh báo khi dùng tới ngưỡng `warn_at_pct` (80%).
  2. Sau khi LLM trả lời, `record_usage(user_id, input_tokens, output_tokens)` tính chi phí dựa trên đơn giá input/output token và cộng dồn vào usage trong ngày của user cũng như tổng chi phí toàn hệ thống.
  3. Trong production thực tế (như Part 6), state chi phí phải lưu trong **Redis/DB** thay vì in-memory dict để không bị mất khi restart hoặc sai lệch khi chạy nhiều instance.
- **Vì sao cần cả Rate Limit lẫn Cost Guard?**
  - **Rate limit** bảo vệ **tốc độ/tài nguyên hệ thống** (chống spam/DDoS theo số request/phút, trả `429`), nhưng không kiểm soát độ dài prompt/token (một vài request hợp lệ với prompt rất dài vẫn có thể đốt hết ngân sách).
  - **Cost guard** bảo vệ **tiền/ngân sách API LLM** (tính theo token thực tế tiêu thụ, trả `402`), đảm bảo không bị vượt chi phí dù request đi ở tốc độ chậm. Hai lớp này bổ trợ cho nhau.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 - 5.3: Health vs Readiness & Graceful Shutdown
- **Khác biệt giữa `/health` (Liveness) và `/ready` (Readiness):**
  - `GET /health` (**Liveness probe**): kiểm tra process của agent có còn sống hay không (trả `200` khi process chạy, kể cả khi Redis/dependency tạm mất kết nối). Nếu `/health` fail, orchestrator (Docker/Kubernetes/cloud) sẽ **restart** container.
  - `GET /ready` (**Readiness probe**): kiểm tra agent có **sẵn sàng nhận traffic** hay chưa (ví dụ kết nối Redis thành công, không đang shutdown). Nếu mất Redis hoặc đang tắt → trả `503` để load balancer ngừng đẩy request mới vào instance đó mà không cần restart container.
- **Vì sao state lưu trong RAM hỏng khi chạy nhiều instance?**
  - Khi scale lên 3 instance (`--scale agent=3`), load balancer (Nginx) phân phối request luân phiên giữa các container. Nếu session history / rate limit / budget lưu trong RAM riêng của từng instance, request 1 vào instance A nhưng request 2 vào instance B sẽ không thấy state của request 1 → mất lịch sử hội thoại, đếm sai rate limit. Giải pháp là chuyển toàn bộ state ra **Redis** dùng chung (stateless agent).

### Exercise 5.4 - 5.5: Stateless + Redis + Nginx Load Balancer
- **Kết quả chạy `python test_stateless.py` với `--scale agent=3`:**
```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: ca53f8fe-4ee2-4b6f-bb3a-eec967187eb0

Request 1: [instance-20425e]
Request 2: [instance-4c21b3]
Request 3: [instance-625125]
Request 4: [instance-20425e]
Request 5: [instance-4c21b3]

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-20425e', 'instance-4c21b3', 'instance-625125'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```
- **Giải thích:** Nginx phân phối 5 request thuộc cùng `session_id` qua 3 container khác nhau (`instance-20425e`, `instance-4c21b3`, `instance-625125`). Vì lịch sử hội thoại được lưu tập trung trong **Redis** thay vì RAM cục bộ của từng container, khi gọi `/chat/{session_id}/history` vẫn đọc lại đủ cả 10 message (5 user + 5 assistant) không bị mất state.

---

## Part 6: Final Project (`06-lab-complete/`)

### Output `python check_production_ready.py` (Checklist Deliverable)
```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

---

## AI Log

| Lần | Dùng cho phần nào | Hỏi gì | Nhận gì | Tự sửa & tự kiểm tra thế nào |
|-----|-------------------|--------|---------|-------------------------------|
| 1 | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
