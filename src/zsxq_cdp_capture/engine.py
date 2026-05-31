"""Capture engine — passive CDP network interception with human-like scrolling.

The engine navigates to a target URL, intercepts API responses via CDP
Network events, extracts data through a user-provided extractor function,
and persists results to one or more storage backends.

Usage is normally through the higher-level :func:`zsxq_cdp_capture.run` entry
point.  Use :class:`CaptureEngine` directly only when you need to
customise the default lifecycle.
"""

from __future__ import annotations

import base64
import json
import random
import time
from collections.abc import Callable
from typing import Any

from .storage.base import StorageBackend

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Extractor = Callable[[str, str], list[dict[str, Any]]]
"""An extractor receives a URL and a response body string, and returns a
(possibly empty) list of record dicts.  Each dict **must** contain a
``record_id`` key that is unique within the capture session."""

# ---------------------------------------------------------------------------
# Default extractor helpers
# ---------------------------------------------------------------------------

RE_HTML_TAG = None  # compiled lazily


def _get_html_re():
    global RE_HTML_TAG
    if RE_HTML_TAG is None:
        import re

        RE_HTML_TAG = re.compile(r"<[^>]+>")
    return RE_HTML_TAG


def strip_html(text: str) -> str:
    """Strip HTML tags, collapse whitespace."""
    if not text:
        return ""
    text = _get_html_re().sub(" ", text)
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CaptureEngine:
    """Passive CDP network capture with human-like scroll behaviour.

    Parameters
    ----------
    backends:
        One or more :class:`~zsxq_cdp_capture.storage.StorageBackend` instances.
        All backends receive the same records.
    url_patterns:
        Substrings to match against intercepted request URLs.  Only
        responses whose URL contains *any* of these patterns will be
        parsed and fed to the extractor.
    extractor:
        A callable ``(url: str, body: str) -> list[dict]`` that parses a
        response body into a list of record dicts.  Every dict **must**
        have a ``record_id`` key that is unique in the session.
    """

    def __init__(
        self,
        backends: list[StorageBackend] | None = None,
        *,
        url_patterns: list[str] | None = None,
        extractor: Extractor | None = None,
    ):
        self._backends = backends or []
        self._url_patterns = url_patterns or []
        self._extractor = extractor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_extractor(self, fn: Extractor) -> None:
        """Set or replace the response-body extractor."""
        self._extractor = fn

    def capture(
        self,
        url: str,
        *,
        max_scrolls: int = 100,
        stale_threshold: int = 50,
    ) -> dict[str, Any]:
        """Run the full capture loop.

        Parameters
        ----------
        url:
            The page URL to navigate to.  The browser will naturally
            issue API calls as the page loads and as we scroll.
        max_scrolls:
            Hard safety cap on the number of scroll rounds.
        stale_threshold:
            Consecutive rounds with zero new records before auto-stop
            (adaptive exit).

        Returns
        -------
        dict with keys ``total_records``, ``fetched_bodies``,
        ``scroll_rounds``, ``started_at``, ``finished_at``.
        """
        if self._extractor is None:
            raise RuntimeError("No extractor set — call set_extractor() first")

        self._init_backends()

        started_at = time.time()
        req_url_map: dict[str, str] = {}
        fetched_ids: set[str] = set()
        records: dict[str, dict] = {}
        saved_ids: set[str] = set()
        bodies_count = 0

        def _flush():
            new = [r for rid, r in records.items() if rid not in saved_ids]
            if not new:
                return
            for be in self._backends:
                be.save(new)
            saved_ids.update(r["record_id"] for r in new)

        def _process_events(events, label):
            nonlocal bodies_count

            for e in events:
                if e.get("method") == "Network.requestWillBeSent":
                    rid = e["params"]["requestId"]
                    url_str = e["params"]["request"]["url"]
                    if rid not in req_url_map:
                        req_url_map[rid] = url_str

            new_bodies = 0
            for e in events:
                if e.get("method") != "Network.loadingFinished":
                    continue
                rid = e["params"]["requestId"]
                if rid in fetched_ids:
                    continue
                fetched_ids.add(rid)

                u = req_url_map.get(rid, "")
                if not u or not any(p in u for p in self._url_patterns):
                    continue

                try:
                    result = _cdp("Network.getResponseBody", requestId=rid)
                except Exception:
                    continue

                body = result.get("body", "")
                if result.get("base64Encoded"):
                    body = base64.b64decode(body).decode("utf-8", errors="replace")
                bodies_count += 1
                new_bodies += 1

                try:
                    for rec in self._extractor(u, body):
                        rid_key = rec.get("record_id")
                        if rid_key and rid_key not in records:
                            records[rid_key] = rec
                except Exception:
                    pass

            _flush()

            topic_count = len(records)
            info = f"{len(events)} events"
            if new_bodies:
                info += f", {new_bodies} bodies, {topic_count} records"
            print(f"  [{label}] {info}")

        # --- navigate -------------------------------------------------------
        print(f"[*] Navigating to {url}")
        try:
            _ensure_real_tab()
        except Exception:
            _new_tab(url)

        _goto_url(url)
        _wait_for_load()
        time.sleep(3)

        # drain before idle (avoid the drain_events / wait_for_network_idle
        # ordering pitfall — idle drains internally and discards events)
        events = _drain_events()
        _process_events(events, "initial")

        _wait_for_network_idle(timeout=15)
        events = _drain_events()
        _process_events(events, "late")

        print(
            f"[*] Phase 1 done: {len(records)} records so far "
            f"({bodies_count} bodies fetched)"
        )

        # --- scroll loop ----------------------------------------------------
        stale = 0
        for i in range(max_scrolls):
            before = len(records)

            _human_scroll()
            events = _drain_events()
            _process_events(events, f"scroll{i + 1}")

            _wait_for_network_idle(timeout=8)
            events = _drain_events()
            _process_events(events, f"scroll{i + 1}b")

            if len(records) > before:
                stale = 0
            else:
                stale += 1
                if stale >= stale_threshold:
                    print(f"[*] Stopping — {stale} stale rounds")
                    break

        # --- finalise -------------------------------------------------------
        _flush()
        self._close_backends()

        finished_at = time.time()
        result = {
            "total_records": len(records),
            "fetched_bodies": bodies_count,
            "scroll_rounds": i + 1,
            "started_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)
            ),
            "finished_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(finished_at)
            ),
        }
        print(
            f"[+] Done: {result['total_records']} records, "
            f"{result['fetched_bodies']} bodies, "
            f"{result['scroll_rounds']} scrolls"
        )
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _init_backends(self) -> None:
        for be in self._backends:
            be.init()

    def _close_backends(self) -> None:
        for be in self._backends:
            be.close()


# ---------------------------------------------------------------------------
# Thin wrappers around browser-harness globals
# ---------------------------------------------------------------------------
# These functions are injected as globals when browser-harness exec()s the
# user script.  In a non-browser-harness context they will raise NameError
# at call time, which is the correct behaviour — the library requires
# browser-harness as its CDP transport.


def _cdp(method: str, **params) -> dict:
    """Raw CDP call — delegated to browser-harness ``cdp()``."""
    return cdp(method, **params)  # noqa: F821


def _drain_events() -> list[dict]:
    """Drain buffered CDP events — delegated to browser-harness ``drain_events()``."""
    return drain_events()  # noqa: F821


def _goto_url(url: str) -> None:
    """Navigate to URL — delegated to browser-harness ``goto_url()``."""
    goto_url(url)  # noqa: F821


def _wait_for_load() -> None:
    """Wait for Page.loadEventFired — delegated to browser-harness ``wait_for_load()``."""
    wait_for_load()  # noqa: F821


def _wait_for_network_idle(timeout: int) -> None:
    """Wait for network idle — delegated to browser-harness ``wait_for_network_idle()``."""
    wait_for_network_idle(timeout)  # noqa: F821


def _ensure_real_tab() -> None:
    """Switch to a real page tab — delegated to browser-harness ``ensure_real_tab()``."""
    ensure_real_tab()  # noqa: F821


def _new_tab(url: str) -> None:
    """Open a new tab — delegated to browser-harness ``new_tab()``."""
    new_tab(url)  # noqa: F821


def _human_scroll() -> None:
    """Random scroll with randomised pause (300-700 px, 1.5-3 s)."""
    dy = random.randint(300, 700)
    js(f"window.scrollBy(0, {dy})")  # noqa: F821
    time.sleep(random.uniform(1.5, 3.0))
