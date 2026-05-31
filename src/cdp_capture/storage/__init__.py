"""Storage backend interface and registry."""

from .base import StorageBackend
from .postgres import PostgresBackend
from .json_file import JsonFileBackend

__all__ = ["StorageBackend", "PostgresBackend", "JsonFileBackend"]


def create_backends(
    *,
    postgres: bool = True,
    json_file: bool = True,
    postgres_config: dict | None = None,
    json_file_dir: str = "./captures",
) -> list[StorageBackend]:
    """Create a list of configured storage backends.

    By default both PostgreSQL and JSON file backends are created.
    The caller can disable either one.

    Args:
        postgres: Enable PostgreSQL backend (default True).
        json_file: Enable JSON file backend (default True).
        postgres_config: Dict of PG connection params (dbname, user, password, host, port).
        json_file_dir: Output directory for JSON files.

    Returns:
        List of initialized StorageBackend instances.
    """
    backends: list[StorageBackend] = []

    if json_file:
        backends.append(JsonFileBackend(output_dir=json_file_dir))

    if postgres:
        backends.append(PostgresBackend(**(postgres_config or {})))

    return backends
