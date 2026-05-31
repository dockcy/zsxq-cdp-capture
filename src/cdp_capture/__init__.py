"""Public API for cdp-capture.

Convenience entry points so callers don't need to wire up
:class:`CaptureEngine` manually.
"""

from __future__ import annotations

from typing import Any

from .engine import CaptureEngine, Extractor
from .storage import (
    JsonFileBackend,
    PostgresBackend,
    StorageBackend,
    create_backends,
)

__all__ = [
    "CaptureEngine",
    "Extractor",
    "JsonFileBackend",
    "PostgresBackend",
    "StorageBackend",
    "create_backends",
    "run",
]


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
) -> dict[str, Any]:
    """One-shot capture: navigate, intercept, save, return summary.

    This is the simplest way to use the library.  It wires together a
    :class:`CaptureEngine` and one or two storage backends, runs the
    capture loop, and returns a result dict.

    Parameters
    ----------
    url:
        The page URL whose API traffic you want to intercept.
    extractor:
        A function ``(url, body) -> list[dict]`` that parses each
        intercepted response body into records.  Every record dict
        **must** contain a ``record_id`` key.
    url_patterns:
        Substrings to match against intercepted request URLs.  Only
        responses matching at least one pattern are parsed.  If omitted,
        **all** URLs are passed to the extractor — usually you want to
        narrow this down to specific API hosts or paths.
    backends:
        Pre-configured list of storage backends.  When provided,
        ``postgres`` and ``json_file`` are ignored.
    postgres:
        Whether to auto-create a :class:`PostgresBackend`.  Default
        ``True``.
    json_file:
        Whether to auto-create a :class:`JsonFileBackend`.  Default
        ``True``.
    postgres_config:
        Dict of PG connection params (``dbname``, ``user``, ``password``,
        ``host``, ``port``).
    json_file_dir:
        Output directory for JSON files.  Default ``./captures``.
    max_scrolls:
        Hard safety cap on scroll rounds.
    stale_threshold:
        Consecutive idle rounds before auto-stop.

    Returns
    -------
    dict
        Summary with keys ``total_records``, ``fetched_bodies``,
        ``scroll_rounds``, ``started_at``, ``finished_at``.
    """
    if backends is None:
        backends = create_backends(
            postgres=postgres,
            json_file=json_file,
            postgres_config=postgres_config,
            json_file_dir=json_file_dir,
        )

    engine = CaptureEngine(
        backends=backends,
        url_patterns=url_patterns or [],
        extractor=extractor,
    )

    return engine.capture(
        url=url,
        max_scrolls=max_scrolls,
        stale_threshold=stale_threshold,
    )
