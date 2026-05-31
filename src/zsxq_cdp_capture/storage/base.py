"""Abstract base class for storage backends."""

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Abstract interface for persisting captured data records.

    Subclass this to add new storage targets (e.g. SQLite, S3, Elasticsearch).
    """

    @abstractmethod
    def init(self) -> None:
        """Initialize the backend — create tables, open files, etc.

        Called once before any save() calls. Must be idempotent.
        """
        ...

    @abstractmethod
    def save(self, records: list[dict]) -> int:
        """Persist a batch of records.

        Args:
            records: List of dicts with a unique `id` key for dedup.

        Returns:
            Number of records actually inserted (new ones only).
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Close connections, flush files, release resources.

        No further save() calls will be made after close().
        """
        ...
