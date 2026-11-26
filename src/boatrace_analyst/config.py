"""Runtime configuration. Database writes require two explicit settings."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
JAPAN_TZ = ZoneInfo("Asia/Tokyo")


def database_write_enabled(environ: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environ is None else environ
    return bool(values.get("DATABASE_URL", "").strip()) and (
        values.get("PHASE1_DB_WRITE_ENABLED", "").strip().lower() == "true"
    )


def require_database_write_permission(
    database_url: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Return the configured DSN only when both database gates are enabled."""
    values = os.environ if environ is None else environ
    configured_url = values.get("DATABASE_URL", "").strip()
    if not configured_url:
        raise PermissionError("DATABASE_URL is not configured; PostgreSQL access is disabled")
    if values.get("PHASE1_DB_WRITE_ENABLED", "").strip().lower() != "true":
        raise PermissionError("PHASE1_DB_WRITE_ENABLED is not true; PostgreSQL writes are disabled")
    if database_url is not None and database_url.strip() != configured_url:
        raise PermissionError("Repository DATABASE_URL does not match the enabled configuration")
    return configured_url


def parse_target_date(value: str | date | None) -> date:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(value)
    return datetime.now(JAPAN_TZ).date()


@dataclass(frozen=True)
class AppConfig:
    target_date: date
    database_url: str | None
    db_write_enabled: bool
    history_path: Path

    @classmethod
    def from_environment(
        cls,
        target_date: str | date | None = None,
        environ: dict[str, str] | None = None,
    ) -> "AppConfig":
        values = os.environ if environ is None else environ
        database_url = values.get("DATABASE_URL", "").strip() or None
        configured_path = values.get("PHASE1_LOCAL_HISTORY_PATH", "").strip()
        if configured_path:
            history_path = Path(configured_path).expanduser().resolve()
        else:
            history_path = (
                Path.home() / ".local" / "state" / "boatrace-analyst" / "history.ndjson"
            ).resolve()
        _ensure_external_history_path(history_path)
        return cls(
            target_date=parse_target_date(target_date),
            database_url=database_url,
            db_write_enabled=database_write_enabled(values),
            history_path=history_path,
        )


def _ensure_external_history_path(path: Path) -> None:
    try:
        path.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return
    raise ValueError("PHASE1_LOCAL_HISTORY_PATH must be outside the repository")
