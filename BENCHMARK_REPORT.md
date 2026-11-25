# Benchmark & Observability Report — Day 14

> Copy file này thành `BENCHMARK_REPORT.md` trong repo của bạn và điền đầy đủ.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Võ Lê Hải Đăng (2A202603577)
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows + WSL2, Docker Desktop, Python 3.11

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Đảm bảo 95% người dùng nhận phản hồi dưới 0.5 giây, giữ trải nghiệm tương tác mượt |
| Error rate `/ask` | < 2.0 % | Cho phép error budget 2% để chịu được lỗi upstream thoáng qua mà không gây alert giả |
| Accuracy trên golden dataset | ≥ 80 % | Đảm bảo chất lượng câu trả lời RAG không tụt dưới ngưỡng chấp nhận khi deploy |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.64 | 201.8 | 395.9 | 1724.6 | 0.33% | PASS |
| 10 | 35.68 | 189.3 | 482.4 | 1695.6 | 1.33% | PASS |
| 50 | 85.07 | 216.6 | 698.2 | 1723.9 | 0.67% | FAIL (p95 > 500ms) |
| 100 | 41.09 | 885.1 | 4925.4 | 5131.2 | 1.00% | FAIL (p95 > 500ms) |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

Không. Từ concurrency 1 → 10 → 50, RPS tăng từ 3.64 → 35.68 → 85.07 req/s, nhưng khi lên 100 thì **RPS tụt xuống 41.09 req/s** và p95 vọt lên **4925.4 ms**. Nguyên nhân là quá tải trên 1 process uvicorn (event loop / CPU / context switching và hàng đợi request bị dồn), khiến thời gian chờ tăng vọt thay vì tăng thông lượng.

### 2.2 Tail latency

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 204.7 | 434.1 | 452.2 |
| 0.03 (mặc định) | 247.1 | 472.5 | 1698.6 |
| 0.1 | 356.1 | 1699.7 | 1964.3 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

**p99** (và **p95** khi tỉ lệ chậm đạt 10%) nhạy nhất với request chậm: ở `MOCK_SLOW_RATE=0.03`, `avg` chỉ tăng nhẹ từ 204.7 lên 247.1 ms (vẫn rất đẹp), nhưng **p99 nhảy gần 4 lần** từ 452.2 lên **1698.6 ms**. Nếu đặt SLO theo `average`, các request chậm bất thường ảnh hưởng trực tiếp tới 1–5% người dùng cuối sẽ bị che khuất hoàn toàn.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.0 | 109.3 | 113.0 |
| Tổng cost (USD) | $0.000402 | $0.000764 | $0.000785 |
| Cost / câu đúng (USD) | $0.00040215 | $0.00003639 | $0.00003413 |
| Quality gate | FAIL | PASS (min 80%) | PASS (min 100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry `(["jwt", "xác thực"], ...)` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` giải thích JWT là token có thời gian hết hạn và chữ ký số |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry `(["hpa", "kubernetes", "autoscal"], ...)` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` mô tả HPA scale theo CPU, memory và custom metrics |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

Agent v2 thêm bước retrieval nên tốn gần gấp đôi token mỗi câu (109.3 vs 57.0) và p95 cao hơn v1 (246.1 ms vs 187.6 ms ở lần eval đầu), nhưng **accuracy tăng từ 4.35% lên 91.3% (và 100% sau khi bổ sung KB)**, kéo **cost / câu đúng giảm hơn 11 lần** (từ `$0.000402` xuống `$0.000034`). Trong CI, có thể chặn merge bằng exit code của `run_eval.py` (khi chạy v1 với `--baseline reports/eval_v2.json`, script trả `exit_code = 1` để CI fail job và chặn PR):
```yaml
- name: Run quality gate
  run: python eval/run_eval.py --url http://localhost:8002 --min-accuracy 0.8 --baseline reports/eval_v2.json
```

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals) — `screenshots/grafana-dashboard.png`
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian) — `screenshots/jaeger-error-trace.png`
- [x] Một trace lỗi trong Jaeger (có event `exception`) — `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing** — `screenshots/prometheus-alert-firing.png`

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | ~75s (`for: 1m` + scrape/eval interval) | Error Rate (5xx %) trên Grafana |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | ~135s (`for: 2m` + scrape/eval interval) | Latency (p50 / p95 / p99) trên Grafana |
| C | `LLM_MODEL=mock-llm-large` | *(tính chất: `LLMCostBurnRateHigh` nếu vượt $2/giờ)* | Chưa chạy riêng | LLM Cost & Tokens/s |
| D | `docker pause` 1 instance | *(tính chất: `AgentInstanceDown` sau `30s`)* | Chưa chạy riêng | Up instances / Scrape targets |
| E | `AGENT_VERSION=v1` | Không alert nào firing | N/A | Token usage / Latency giảm nhẹ nhưng chất lượng tụt |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Alert hạ tầng (error rate, p95, uptime) chỉ đo sức khoẻ kỹ thuật chứ không đo **chất lượng câu trả lời**. Để phát hiện tụt chất lượng như chuyển nhầm về `v1`, cần chạy **eval trên golden dataset (`eval/run_eval.py`) trong CI/CD trước khi deploy** (quality gate chặn merge khi accuracy giảm), kết hợp theo dõi feedback người dùng (thumbs up/down) hoặc online LLM-as-a-judge sampling trên production.

### 4.3 Debug bằng trace

Chọn 1 trace chậm / lỗi bạn tìm được:

- `trace_id`: `bd782aec687f590c4e2810b2a2d29a2d`
- Tổng thời gian: `858.4` ms (`859ms` trên Jaeger UI)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (`835 ms`, `97.2%` tổng thời gian; `agent.retrieve_context` mất `20.8 ms`)
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-25T15:10:31.677575+00:00", "level": "INFO", "service": "observable-agent", "instance": "ceba78bcb5bd", "event": "llm_error", "trace_id": "bd782aec687f590c4e2810b2a2d29a2d", "span_id": "a43676474b8aebae", "request_id": "f3d0d6d99582", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T15:10:31.678122+00:00", "level": "INFO", "service": "observable-agent", "instance": "ceba78bcb5bd", "event": "http_request", "trace_id": "bd782aec687f590c4e2810b2a2d29a2d", "span_id": "a43676474b8aebae", "request_id": "f3d0d6d99582", "method": "POST", "route": "/ask", "status": 503, "ms": 858.4}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 64.23 | 190 | 630 | 1700 | 66 / 7573 (0.87%) |
| 3 | 65.11 | 200 | 350 | 1700 | 77 / 7757 (0.99%) |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

Scale lên 3 instance **cải thiện rõ rệt p95** (giảm từ **630 ms** xuống **350 ms**) do giảm nghẽn hàng đợi trên mỗi container khi có 100 user đồng thời. Tuy nhiên **RPS chỉ tăng nhẹ** (64.23 → 65.11) vì các user Locust có `wait_time` cố định nên bị giới hạn bởi tốc độ sinh tải phía client, còn **p99 giữ nguyên 1700 ms** vì nút thắt tail latency nằm ở thời gian xử lý nội tại của LLM (`MOCK_SLOW_RATE=0.03`, `MOCK_SLOW_MS=1500`), không thể triệt tiêu bằng cách thêm instance.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. Không dùng `average` để đặt SLO: `p95`/`p99` phản ánh đúng tail latency mà người dùng thật gặp phải.
  2. Eval trên golden dataset + quality gate bằng exit code giúp phát hiện regression và đo hiệu quả chi phí (`cost / câu đúng`) trước khi merge/deploy.
  3. 3 trụ cột Metrics (Prometheus/Grafana) + Traces (OpenTelemetry/Jaeger) + Structured JSON Logs liên kết qua `trace_id` giúp khoanh vùng nhanh nguyên nhân chậm hoặc lỗi trên production.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

  Theo dõi thêm tỉ lệ cache hit (Redis), thời gian phản hồi riêng của vector DB / retrieval, và alert khi `cost_usd` tiệm cận ngưỡng 80% ngân sách ngày/tháng.
