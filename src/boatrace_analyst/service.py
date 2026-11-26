"""Coordinate one date-specific retrieval and append its outcomes."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date

from .config import AppConfig
from .models import (
    FetchStatus, FindingScope, FindingSeverity, RunResult, ValidationFinding, ValidationStatus,
)
from .postgres import PostgresHistoryRepository
from .repository import JsonlHistoryRepository, HistoryRepository, repository_for
from .sources import CalendarEvidenceProvider, DateJsonSource, UnconfirmedCalendarProvider
from .status import build_venue_outcomes
from .validation import ValidationReport, validate_payload


def run_ingestion(
    config: AppConfig,
    source: DateJsonSource | None = None,
    calendar_provider: CalendarEvidenceProvider | None = None,
    repository: HistoryRepository | None = None,
) -> RunResult:
    selected_repository = repository if repository is not None else repository_for(config)
    if isinstance(selected_repository, PostgresHistoryRepository):
        if not config.db_write_enabled or not config.database_url:
            raise PermissionError("AppConfig does not enable PostgreSQL writes")
        selected_repository.ensure_write_enabled(config.database_url)

    source = source or DateJsonSource()
    calendar_provider = calendar_provider or UnconfirmedCalendarProvider()
    response = source.fetch(config.target_date)
    report: ValidationReport | None = None
    if response.body is not None:
        report = validate_payload(response.body, config.target_date)

    outcomes = build_venue_outcomes(response, report, config.target_date, calendar_provider)
    findings = [finding for finding in report.findings if finding.venue_code is None] if report else []
    if response.error_code:
        findings.append(ValidationFinding(
            FindingScope.FILE, FindingSeverity.ERROR, response.error_code, "$",
            response.error_message or "Source request failed",
        ))

    if response.fetch_status is FetchStatus.FAILED:
        validation_status = ValidationStatus.UNCONFIRMED
    elif report is None:
        validation_status = ValidationStatus.INVALID
    elif report.file_status is ValidationStatus.INVALID or any(
        outcome.validation_status is ValidationStatus.INVALID for outcome in outcomes
    ):
        validation_status = ValidationStatus.INVALID
    elif report.file_status is ValidationStatus.UNCONFIRMED or any(
        outcome.validation_status is ValidationStatus.UNCONFIRMED for outcome in outcomes
    ):
        validation_status = ValidationStatus.UNCONFIRMED
    else:
        validation_status = ValidationStatus.VALID

    result = RunResult(
        run_id=str(uuid.uuid4()),
        target_date=config.target_date,
        source_url=response.source_url,
        requested_at=response.requested_at,
        retrieved_at=response.retrieved_at,
        fetch_status=response.fetch_status,
        validation_status=validation_status,
        http_status=response.http_status,
        payload_sha256=hashlib.sha256(response.body).hexdigest() if response.body is not None else None,
        outcomes=outcomes,
        findings=findings,
    )

    if isinstance(selected_repository, JsonlHistoryRepository):
        result.persistence_status = "local_ndjson_only"
    try:
        result.persistence_status = selected_repository.append(result, response.body)
    except Exception as exc:
        if isinstance(selected_repository, JsonlHistoryRepository):
            raise
        result.persistence_status = "local_fallback_db_commit_unconfirmed"
        fallback = JsonlHistoryRepository(config.history_path)
        fallback.append(result, response.body)
        # The fallback is not proof that PostgreSQL did not commit if its reply was lost.
        result.findings.append(ValidationFinding(
            FindingScope.FILE, FindingSeverity.UNCONFIRMED, "db_write_unconfirmed", "$",
            f"PostgreSQL write was not confirmed; local NDJSON was appended ({type(exc).__name__})",
        ))
    return result
