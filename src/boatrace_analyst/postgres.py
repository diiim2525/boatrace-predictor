"""PostgreSQL append-only persistence. psycopg is imported only on use."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import require_database_write_permission
from .models import RunResult


class PostgresHistoryRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = require_database_write_permission(database_url)

    def ensure_write_enabled(self, expected_database_url: str | None = None) -> None:
        configured_url = require_database_write_permission(self._database_url)
        if expected_database_url is not None and configured_url != expected_database_url.strip():
            raise PermissionError("AppConfig DATABASE_URL does not match the enabled configuration")

    def _connect(self) -> Any:
        self.ensure_write_enabled()
        import psycopg  # Optional dependency; never imported in DB-disconnected mode.

        return psycopg.connect(self._database_url)

    def migrate(self) -> None:
        self.ensure_write_enabled()
        schema_path = Path(__file__).resolve().parents[2] / "sql" / "001_phase1.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(schema_sql)

    def append(self, result: RunResult, raw_payload: bytes | None) -> str:
        self.ensure_write_enabled()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO ingestion_runs
                    (run_id, target_date, requested_at, retrieved_at, source_url,
                     fetch_status, validation_status, http_status, payload_sha256, raw_payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        result.run_id, result.target_date, result.requested_at,
                        result.retrieved_at, result.source_url, result.fetch_status.value,
                        result.validation_status.value, result.http_status,
                        result.payload_sha256, raw_payload,
                    ),
                )
                for outcome in result.outcomes:
                    cursor.execute(
                        """INSERT INTO venue_acquisition_history
                        (run_id, venue_code, target_date, observed_at, fetch_status,
                         json_presence, data_status, validation_status, calendar_status,
                         race_count, calendar_source, calendar_evidence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            result.run_id, outcome.venue_code, result.target_date,
                            result.retrieved_at, outcome.fetch_status.value,
                            outcome.json_presence.value, outcome.data_status.value,
                            outcome.validation_status.value, outcome.calendar_status.value,
                            outcome.race_count, outcome.calendar_source, outcome.calendar_evidence,
                        ),
                    )
                for finding in result.findings:
                    cursor.execute(
                        """INSERT INTO validation_findings
                        (run_id, scope, severity, code, field_path, message,
                         venue_code, race_number, expected_type, actual_type)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            result.run_id, finding.scope.value, finding.severity.value,
                            finding.code, finding.field_path, finding.message,
                            finding.venue_code, finding.race_number,
                            finding.expected_type, finding.actual_type,
                        ),
                    )
                for outcome in result.outcomes:
                    for finding in outcome.findings:
                        cursor.execute(
                            """INSERT INTO validation_findings
                            (run_id, scope, severity, code, field_path, message,
                             venue_code, race_number, expected_type, actual_type)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (
                                result.run_id, finding.scope.value, finding.severity.value,
                                finding.code, finding.field_path, finding.message,
                                finding.venue_code, finding.race_number,
                                finding.expected_type, finding.actual_type,
                            ),
                        )
        return "postgres_committed"
