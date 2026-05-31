#!/usr/bin/env python3
"""Example: capture topics from a 知识星球 (zsxq) group.

Usage:
    BU_CDP_URL=http://127.0.0.1:9223 browser-harness < examples/zsxq_capture.py

Environment variables:
    ZSXQ_GROUP_ID   — zsxq group ID (default: 48885521585418)
    ZSXQ_MAX_SCROLL — max scroll rounds (default: 100)
"""

import json
import os

from cdp_capture import run

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GROUP_ID = os.environ.get("ZSXQ_GROUP_ID", "48885521585418")
GROUP_URL = f"https://wx.zsxq.com/group/{GROUP_ID}"
API_HOST = "api.zsxq.com"
TOPICS_PATH = f"/v2/groups/{GROUP_ID}/topics"
MAX_SCROLL = int(os.environ.get("ZSXQ_MAX_SCROLL", "100"))

# ---------------------------------------------------------------------------
# Extractor — parses zsxq API responses into record dicts
# ---------------------------------------------------------------------------


def extract_zsxq_topics(url: str, body: str) -> list[dict]:
    """Extract topics from a zsxq /v2/groups/{id}/topics response."""
    if TOPICS_PATH not in url:
        return []

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return []

    if not data.get("succeeded"):
        return []

    records = []
    for t in data.get("resp_data", {}).get("topics", []):
        tid = t.get("topic_id")
        if not tid:
            continue

        tp = t.get("type", "talk")
        content = t.get(tp, {})
        body_text = content.get("text", "") or ""

        records.append(
            {
                "record_id": str(tid),
                "record_type": tp,
                "title": (t.get("title") or "")[:200],
                "body_text": body_text,
                "author": content.get("owner", {}).get("name", ""),
                "author_id": str(content.get("owner", {}).get("user_id", "")),
                "source_url": f"https://wx.zsxq.com/topic/{tid}",
                "create_time": t.get("create_time"),
            }
        )

    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__builtins__" or __name__ == "__main__":
    # The `__builtins__` check handles the browser-harness exec()
    # environment where __name__ is not "__main__".

    result = run(
        url=GROUP_URL,
        extractor=extract_zsxq_topics,
        url_patterns=[TOPICS_PATH],
        postgres=True,   # set False to skip PostgreSQL
        json_file=True,  # set False to skip JSON file output
        json_file_dir="./captures",
        max_scrolls=MAX_SCROLL,
        stale_threshold=50,
    )

    print(f"\nDone: {result['total_records']} records in {result['scroll_rounds']} scrolls")
