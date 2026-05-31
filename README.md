# cdp-capture

> 基于 CDP 的被动式数据抓取库 — 不主动发 HTTP 请求，反爬系统看不到你。

Passive CDP-based data capture — intercept browser network responses
**without sending any HTTP requests**, making your scraper invisible to
anti-bot detection.

Built on top of [browser-harness] for CDP transport.  Your script rides
inside a real, non-headless Chrome browser.  As the page loads and you
scroll naturally, `cdp-capture` intercepts the API responses the browser
receives, extracts structured data from them, and persists the results to
**PostgreSQL**, **JSON files**, or **both**.

基于 [browser-harness] 做 CDP 传输层。你的脚本跑在一个真实的、非 headless
的 Chrome 浏览器里。页面加载、自然滚动的过程中，`cdp-capture` 在背后偷听浏览器
收到的 API 响应，把数据摘出来，存到 **PostgreSQL**、**JSON 文件**，或者**两者同时**。

[browser-harness]: https://github.com/browser-use/browser-harness

## 为什么用被动模式？ / Why passive?

| 方案 | HTTP 请求 | WAF 可见？ | 指纹 |
|---|---|---|---|
| `requests` / `httpx` | 有，Python 发出 | 是 | Python TLS |
| Playwright / Puppeteer | 有，CDP `fetch` | 有时 | Headless 痕迹 |
| **cdp-capture** | **无** — 偷听真实 Chrome 流量 | **否** | 真实 Chrome |

浏览器自己发请求，你只负责听。 / The browser makes the requests.  You just listen.

## 安装 / Installation

```bash
pip install cdp-capture
```

还需要装 `browser-harness` 并准备一个开了 CDP 的 Chrome：

```bash
pip install browser-harness
```

## 快速开始 / Quick start

```python
"""my_capture.py — 用法:  browser-harness < my_capture.py"""
import json
from cdp_capture import run

def my_extractor(url, body):
    """解析每个拦截到的 API 响应，返回 record 列表"""
    data = json.loads(body)
    results = []
    for item in data.get("items", []):
        results.append({
            "record_id": str(item["id"]),
            "title": item.get("title", ""),
            "body_text": item.get("content", ""),
            "author": item.get("author", {}).get("name", ""),
            "source_url": url,
            "create_time": item.get("created_at"),
        })
    return results

result = run(
    url="https://example.com/data-page",
    extractor=my_extractor,
    url_patterns=["api.example.com/v1/items"],
    json_file=True,   # 同时写 JSON 文件
    postgres=True,    # 同时写 PostgreSQL
)
print(f"抓到 {result['total_records']} 条记录")
```

```bash
BU_CDP_URL=http://127.0.0.1:9223 browser-harness < my_capture.py
```

## 存储后端 / Storage backends

### 默认两个都开，你自己选 / Both enabled by default — you pick

| 后端 | 适合场景 | 类 |
|---|---|---|
| PostgreSQL | 生产环境、大数据量、需要 SQL 查询 | `PostgresBackend` |
| JSON 文件 | 调试、小数据、方便拷走归档 | `JsonFileBackend` |

### 只要 PostgreSQL

```python
from cdp_capture import run

run(..., postgres=True, json_file=False)
```

### 只要 JSON 文件

```python
from cdp_capture import run

run(..., postgres=False, json_file=True)
```

### 两个都要（默认行为）

```python
from cdp_capture import run

run(...)  # 啥都不设，两个都开
```

### 自定义 PostgreSQL 连接

```python
from cdp_capture import run

run(
    ...,
    postgres_config={
        "dbname": "my_capture_db",
        "user": "capture_user",
        "password": "secret",
        "host": "10.0.0.5",
        "port": "5432",
    },
)
```

或者用环境变量：

```bash
export CDP_CAPTURE_DB_NAME=my_capture_db
export CDP_CAPTURE_DB_USER=capture_user
export CDP_CAPTURE_DB_PASSWORD=secret
export CDP_CAPTURE_DB_HOST=10.0.0.5
```

### JSON 文件输出

默认写到 `./captures/`，文件名 `capture_<时间戳>.json`：

```json
{
  "captured_at": "2026-05-31T12:00:00",
  "total": 245,
  "records": [
    {
      "record_id": "45544811818285188",
      "title": "...",
      "body_text": "...",
      "author": "...",
      "source_url": "...",
      "create_time": "2026-05-24T17:56:17+0800"
    }
  ]
}
```

改输出目录设 `json_file_dir="./output"`。

## 写 extractor / Writing an extractor

**extractor 是你唯一需要写的东西**，其他的引擎全包了。

The extractor is the only piece you **must** write.  Everything else is
handled by the engine.

```python
def extractor(url: str, body: str) -> list[dict]:
    """解析 API 响应，返回 record dict 列表。

    每个 dict 必须包含 ``record_id`` 字段 — 用于跨滚屏去重。
    """
    ...
```

### record dict 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `record_id` | `str` | 是 | 唯一 ID，用于去重 |
| `title` | `str` | 否 | 标题 |
| `body_text` | `str` | 否 | 正文 |
| `author` | `str` | 否 | 作者名 |
| `author_id` | `str` | 否 | 作者 ID |
| `source_url` | `str` | 否 | 来源链接 |
| `record_type` | `str` | 否 | 类型，如 `"talk"`、`"question"` |
| `create_time` | `str` | 否 | ISO-8601 时间戳 |
| `extra` | `dict` | 否 | 任意 JSON 可序列化的额外数据 |

## 工作原理 / How it works

```
┌──────────┐   CDP 事件      ┌───────────────┐   records   ┌──────────────┐
│  Chrome  │ ───────────────> │ CaptureEngine │ ──────────> │ Storage      │
│  (真浏览器) │  Network.*      │               │            │ Postgres +   │
│          │ <─────────────── │  • drain      │            │ JSON file    │
│  滚动    │  Input.*         │  • getBody    │            └──────────────┘
│  导航    │  Page.*          │  • extract    │
└──────────┘                  │  • dedup      │
                              └───────────────┘
```

1. **导航** — `goto_url()` 打开目标页面，浏览器自然发出 API 请求。
2. **拦截** — CDP `Network.requestWillBeSent` 和 `Network.loadingFinished` 事件告诉我们哪些 URL 被请求了。
3. **捞 body** — `Network.getResponseBody()` 在 Chrome 释放内存之前把响应体捞出来。
4. **提取** — 你的 `extractor(url, body)` 函数把 JSON 解析成结构化的 record dict。
5. **滚动** — 模拟真人的 `window.scrollBy()` 触发分页/无限滚动，滚动距离和时间随机化。
6. **自适应停止** — 连续 N 轮滚屏没新数据就自动停，`max_scrolls` 作为硬上限兜底。
7. **持久化** — 数据批量写入 PostgreSQL（upsert）和/或时间戳 JSON 文件。

## API 参考 / API reference

### `cdp_capture.run()` — 一键入口

```python
def run(
    url: str,                              # 目标页面 URL
    extractor: Extractor,                  # 你的解析函数
    *,
    url_patterns: list[str] | None = None, # 只拦截匹配这些字符串的 URL
    backends: list[StorageBackend] | None = None,  # 自定义后端列表
    postgres: bool = True,                 # 是否启用 PostgreSQL
    json_file: bool = True,                # 是否启用 JSON 文件
    postgres_config: dict | None = None,   # PG 连接参数
    json_file_dir: str = "./captures",     # JSON 输出目录
    max_scrolls: int = 100,                # 最大滚动次数
    stale_threshold: int = 50,             # 连续无新数据轮数阈值
) -> dict
```

### `CaptureEngine` — 引擎类

需要更细粒度的控制时直接用：

```python
from cdp_capture import CaptureEngine, PostgresBackend, JsonFileBackend

engine = CaptureEngine(
    backends=[PostgresBackend(), JsonFileBackend()],
    url_patterns=["api.example.com"],
    extractor=my_extractor,
)
result = engine.capture("https://example.com", max_scrolls=200)
```

### `PostgresBackend` — PostgreSQL 后端

```python
PostgresBackend(
    dbname="cdp_capture",
    user="postgres",
    password="",
    host="127.0.0.1",
    port="5432",
    table_name="records",
)
```

表结构（`init()` 时自动创建）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | `BIGSERIAL PK` | 自增主键 |
| `record_id` | `VARCHAR(255) UNIQUE` | 去重键 |
| `source_url` | `TEXT` | 来源 URL |
| `title` | `TEXT` | 标题 |
| `body_text` | `TEXT` | 正文 |
| `author` | `VARCHAR(255)` | 作者 |
| `author_id` | `VARCHAR(255)` | 作者 ID |
| `record_type` | `VARCHAR(50)` | 类型 |
| `create_time` | `TIMESTAMPTZ` | 原始时间戳 |
| `extra` | `JSONB` | 任意附加数据 |
| `captured_at` | `TIMESTAMPTZ` | 抓取时间 |
| `updated_at` | `TIMESTAMPTZ` | 最后 upsert 时间 |

### `JsonFileBackend` — JSON 文件后端

```python
JsonFileBackend(output_dir="./captures")
```

抓取期间数据在内存缓存，`close()` 时一次性写入时间戳命名的 JSON 文件。

### `create_backends()` — 后端工厂

```python
from cdp_capture import create_backends

backends = create_backends(
    postgres=True,
    json_file=True,
    postgres_config={"dbname": "mydb"},
    json_file_dir="./output",
)
```

## 配合 browser-harness 运行

`cdp-capture` 用 `browser-harness` 做 CDP 传输层，你的脚本跑在 harness 里面：

```bash
BU_CDP_URL=http://127.0.0.1:9223 browser-harness < your_script.py
```

harness 会注入全局函数（`goto_url`、`drain_events`、`cdp`、`js`、
`wait_for_network_idle` 等），`cdp-capture` 内部直接调用它们。

## 踩坑记录 / Pitfalls

这些是从生产环境实战中踩出来的坑，**用之前先读一遍**。

> These are extracted from real-world production experience.  Read them
> **before** you hit them.

1. **先 drain 再 idle。** `wait_for_network_idle()` 内部会调 `drain_events()`
   并把事件丢掉。一定要在等 idle **之前**先 drain，idle 之后再 drain 一次。

2. **`getResponseBody` 是过时不候的。** Chrome 在 `loadingFinished` 后几秒
   就会释放响应体内存。必须在同一轮 drain 里把 body 捞出来，不要攒到后面。

3. **别探 `scrollHeight`。** 调 `page_info()` 或 `Runtime.evaluate` 去查
   页面高度会触发反爬检测。用自适应 stale 计数器来判断翻完了没有。

4. **事件缓冲区有上限。** browser-harness daemon 的事件缓冲区只有 500 条
   （FIFO）。高流量页面要高频 drain（紧循环里每 100-200ms 一次）。

5. **PostgreSQL 自动提交。** `PostgresBackend` 内部管理事务，外面不要再包
   事务。

6. **`record_id` 必须是字符串。** 去重字典用字符串 key，数字 ID 要
   `str()` 转换。

## 目录结构 / Project structure

```
cdp-capture/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/cdp_capture/
│   ├── __init__.py          # 公共 API: run(), CaptureEngine, create_backends()
│   ├── engine.py            # 引擎核心: CDP 拦截 + 滚动循环
│   ├── __main__.py          # CLI 入口
│   └── storage/
│       ├── __init__.py      # create_backends() 工厂函数
│       ├── base.py          # StorageBackend 抽象基类
│       ├── postgres.py      # PostgreSQL 后端（连接池 + upsert）
│       └── json_file.py     # JSON 文件后端（内存缓存 + 时间戳文件）
└── examples/
    └── zsxq_capture.py      # 真实案例：知识星球抓取
```

## License

MIT — see [LICENSE](./LICENSE).
