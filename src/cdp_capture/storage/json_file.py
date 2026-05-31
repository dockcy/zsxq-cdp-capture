"""JSON file storage backend — writes captured records to timestamped files."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .base import StorageBackend


class JsonFileBackend(StorageBackend):
    """Appends records to a timestamped JSON file in the output directory.

    Provides a plain-text, git-diffable alternative to the PostgreSQL backend.
    Suitable for small-to-medium datasets, debugging, and portable archives.

    Output files are named: ``capture_<timestamp>.json``.
    """

    def __init__(self, output_dir: str = "./captures"):
        self._output_dir = Path(output_dir)
        self._records: dict[str, dict] = {}  # record_id -> record (dedup)
        self._file_path: Path | None = None

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Ensure the output directory exists."""
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def save(self, records: list[dict]) -> int:
        """Add records to the in-memory buffer (dedup by record_id).

        Returns count of *new* records added (not already seen).
        """
        before = len(self._records)
        for r in records:
            rid = r.get("record_id")
            if rid and rid not in self._records:
                self._records[rid] = r
        return len(self._records) - before

    def close(self) -> None:
        """Flush all buffered records to a timestamped JSON file."""
        if not self._records:
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._file_path = self._output_dir / f"capture_{ts}.json"

        records_list = sorted(
            self._records.values(),
            key=lambda r: r.get("create_time", ""),
            reverse=True,
        )

        payload = {
            "captured_at": datetime.now().isoformat(),
            "total": len(records_list),
            "records": records_list,
        }

        self._file_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        )

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Number of records currently buffered in memory."""
        return len(self._records)

    @property
    def file_path(self) -> Path | None:
        """Path to the written JSON file (available after close())."""
        return self._file_path
