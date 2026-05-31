# cdp-capture

Passive CDP-based data capture — intercept browser network responses
**without sending any HTTP requests**, making your scraper invisible to
anti-bot detection.

Built on top of [browser-harness] for CDP transport.  Your script rides
inside a real, non-headless Chrome browser.  As the page loads and you
scroll naturally, `cdp-capture` intercepts the API responses the browser
receives, extracts structured data from them, and persists the results to
**PostgreSQL**, **JSON files**, or **both**.

[browser-harness]: https://github.com/browser-use/browser-harness

## Why passive?

| Approach | HTTP requests | Visible to WAF? | Fingerprint |
|---|---|---|---|
| `requests` / `httpx` | Yes, from Python | Yes | Python TLS |
| Playwright / Puppeteer | Yes, via CDP `fetch` | Sometimes | Headless hints |
| **cdp-capture** | **No** — intercepts real Chrome traffic | **No** | Real Chrome |

The browser makes the requests.  You just listen.

## Installation

```bash
pip install cdp-capture
```

You also need `browser-harness` installed and a Chrome instance with CDP
enabled:

```bash
pip install browser-harness
```

## Quick start

```python
"""my_capture.py — run with:  browser-harness < my_capture.py"""
import json
from cdp_capture import run

def my_extractor(url, body):
    """Parse each intercepted API response into records."""
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
    json_file=True,
    postgres=True,
)
print(f"Captured {result['total_records']} records")
```

```bash
BU_CDP_URL=http://127.0.0.1:9223 browser-harness < my_capture.py
```

## Storage backends

### Both enabled by default — you pick

| Backend | Best for | Class |
|---|---|---|
| PostgreSQL | Production, querying, large datasets | `PostgresBackend` |
| JSON file | Debugging, portability, small datasets | `JsonFileBackend` |

### Use only PostgreSQL

```python
from cdp_capture import run, PostgresBackend

run(
    ...,
    backends=[PostgresBackend()],
    # or: postgres=True, json_file=False
)
```

### Use only JSON file

```python
from cdp_capture import run, JsonFileBackend

run(
    ...,
    backends=[JsonFileBackend(output_dir="./my_captures")],
    # or: postgres=False, json_file=True
)
```

### Use both (default)

```python
from cdp_capture import run

run(...)  # both enabled by default
```

### Custom PostgreSQL config

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

Or via environment variables:

```bash
export CDP_CAPTURE_DB_NAME=my_capture_db
export CDP_CAPTURE_DB_USER=capture_user
export CDP_CAPTURE_DB_PASSWORD=secret
export CDP_CAPTURE_DB_HOST=10.0.0.5
```

### JSON file output

Files land in `./captures/` by default, named `capture_<timestamp>.json`:

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

Set `json_file_dir="./output"` to change the directory.

## Writing an extractor

The extractor is the only piece you **must** write.  Everything else is
handled by the engine.

```python
def extractor(url: str, body: str) -> list[dict]:
    """Parse a response body into zero or more record dicts.

    Each dict MUST contain a ``record_id`` key — this is used for
    deduplication across scroll rounds.
    """
    ...
```

### Record dict fields

| Key | Type | Required | Notes |
|---|---|---|---|
| `record_id` | `str` | Yes | Unique ID for dedup |
| `title` | `str` | No | |
| `body_text` | `str` | No | |
| `author` | `str` | No | |
| `author_id` | `str` | No | |
| `source_url` | `str` | No | |
| `record_type` | `str` | No | e.g. `"talk"`, `"question"` |
| `create_time` | `str` | No | ISO-8601 timestamp |
| `extra` | `dict` | No | Arbitrary JSON-serialisable data |

## How it works

```
┌──────────┐   CDP events    ┌───────────────┐   records   ┌──────────────┐
│  Chrome  │ ───────────────> │ CaptureEngine │ ──────────> │ Storage      │
│  (real)  │  Network.*       │               │            │ Postgres +   │
│          │ <─────────────── │  • drain      │            │ JSON file    │
│  scroll  │  Input.*         │  • getBody    │            └──────────────┘
│  navigate│  Page.*          │  • extract    │
└──────────┘                  │  • dedup      │
                              └───────────────┘
```

1. **Navigate** — `goto_url()` opens the target page.  The browser
   naturally fires API requests as the page loads.
2. **Intercept** — CDP `Network.requestWillBeSent` and
   `Network.loadingFinished` events tell us which URLs were fetched.
3. **Fetch body** — `Network.getResponseBody()` grabs the raw response
   before Chrome evicts it from memory.
4. **Extract** — Your `extractor(url, body)` function parses the JSON
   into structured record dicts.
5. **Scroll** — Human-like `window.scrollBy()` triggers pagination /
   infinite scroll APIs.  Scroll distance and timing are randomised.
6. **Adaptive stop** — When N consecutive scroll rounds yield zero new
   records, the engine stops.  A hard `max_scrolls` cap prevents
   infinite loops.
7. **Persist** — Records are flushed to PostgreSQL (upsert) and/or a
   timestamped JSON file.

## API reference

### `cdp_capture.run()`

The one-shot convenience entry point.

```python
def run(
    url: str,
    extractor: Extractor,
    *,
    url_patterns: list[str] | None = None,
    backends: list[StorageBackend] | None = None,
    postgres: bool = True,
    json_file: bool = True,
    postgres_config: dict | None = None,
    json_file_dir: str = "./captures",
    max_scrolls: int = 100,
    stale_threshold: int = 50,
) -> dict
```

### `CaptureEngine`

The class behind `run()`.  Use directly when you need fine-grained
control.

```python
from cdp_capture import CaptureEngine, PostgresBackend, JsonFileBackend

engine = CaptureEngine(
    backends=[PostgresBackend(), JsonFileBackend()],
    url_patterns=["api.example.com"],
    extractor=my_extractor,
)
result = engine.capture("https://example.com", max_scrolls=200)
```

### `PostgresBackend`

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

Table schema (auto-created on `init()`):

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGSERIAL PK` | Auto-increment |
| `record_id` | `VARCHAR(255) UNIQUE` | Dedup key |
| `source_url` | `TEXT` | |
| `title` | `TEXT` | |
| `body_text` | `TEXT` | |
| `author` | `VARCHAR(255)` | |
| `author_id` | `VARCHAR(255)` | |
| `record_type` | `VARCHAR(50)` | e.g. talk, question |
| `create_time` | `TIMESTAMPTZ` | Original timestamp |
| `extra` | `JSONB` | Arbitrary metadata |
| `captured_at` | `TIMESTAMPTZ` | When we saved it |
| `updated_at` | `TIMESTAMPTZ` | Last upsert time |

### `JsonFileBackend`

```python
JsonFileBackend(output_dir="./captures")
```

Records are buffered in memory during capture and flushed to a
timestamped JSON file on `close()`.

### `create_backends()`

```python
from cdp_capture import create_backends

backends = create_backends(
    postgres=True,
    json_file=True,
    postgres_config={"dbname": "mydb"},
    json_file_dir="./output",
)
```

## Running with browser-harness

`cdp-capture` uses `browser-harness` as its CDP transport.  Your script
runs inside the harness:

```bash
BU_CDP_URL=http://127.0.0.1:9223 browser-harness < your_script.py
```

The harness injects global functions (`goto_url`, `drain_events`, `cdp`,
`js`, `wait_for_network_idle`, etc.) that `cdp-capture` calls internally.

See [browser-harness] for setup instructions (Chrome with
`--remote-debugging-port`, Docker Compose, or cloud browsers).

## Pitfalls

These are extracted from real-world experience running CDP captures in
production.  Read them **before** you hit them.

1. **Drain before idle.**  `wait_for_network_idle()` calls
   `drain_events()` internally and discards the events.  Always drain
   BEFORE waiting for idle, then drain again after.

2. **`getResponseBody` is ephemeral.**  Chrome frees response body
   memory seconds after `loadingFinished`.  Fetch the body in the same
   drain cycle — don't defer it.

3. **Don't probe `scrollHeight`.**  Calling `page_info()` or
   `Runtime.evaluate` to check page height triggers anti-bot heuristics.
   Use the adaptive stale-round counter instead.

4. **Event buffer is finite.**  The browser-harness daemon caps its
   event buffer at 500 entries (FIFO).  On high-traffic pages, drain
   frequently (every 100–200 ms in tight loops).

5. **PostgreSQL autocommit.**  The `PostgresBackend` manages
   transactions internally.  Don't wrap it in your own transaction.

6. **`record_id` must be a string.**  The dedup dict uses string keys.
   Cast integer IDs with `str()`.

## License

MIT — see [LICENSE](./LICENSE).
