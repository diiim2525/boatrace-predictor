"""Append-only local fallback and repository selection."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from .config import AppConfig
from .models import RunResult


class HistoryRepository(Protocol):
    def append(self, result: RunResult, raw_payload: bytes | None) -> str:
        """Append one complete run and return a truthful persistence label."""


class JsonlHistoryRepository:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def append(self, result: RunResult, raw_payload: bytes | None) -> str:
        _assert_outside_repository(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        return "local_ndjson_only"


def repository_for(config: AppConfig) -> HistoryRepository:
    if config.db_write_enabled and config.database_url:
        from .postgres import PostgresHistoryRepository

        # The repository constructor independently checks the live process environment.
        return PostgresHistoryRepository(config.database_url)
    return JsonlHistoryRepository(config.history_path)


def _assert_outside_repository(path: Path) -> None:
    from .config import REPOSITORY_ROOT

    try:
        path.resolve().relative_to(REPOSITORY_ROOT)
    except ValueError:
        return
    raise ValueError("Local NDJSON must be stored outside the repository")
