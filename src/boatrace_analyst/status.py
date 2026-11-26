"""Construct one independent result row for each of the 24 venues."""

from __future__ import annotations

from datetime import date

from .models import (
    CalendarStatus, DataStatus, FetchResponse, FetchStatus, JsonPresence,
    ValidationFinding, ValidationStatus, VenueOutcome,
)
from .sources import CalendarEvidenceProvider
from .validation import ValidationReport
from .venues import VENUES


def build_venue_outcomes(
    response: FetchResponse,
    report: ValidationReport | None,
    target_date: date,
    calendar_provider: CalendarEvidenceProvider,
) -> list[VenueOutcome]:
    outcomes: list[VenueOutcome] = []
    stadiums = None
    if report is not None and isinstance(report.document, dict):
        programs = report.document.get("programs")
        if isinstance(programs, dict) and isinstance(programs.get("stadiums"), dict):
            stadiums = programs["stadiums"]

    for venue in VENUES:
        calendar_status, calendar_source, calendar_evidence = calendar_provider.status_for(
            venue.code, target_date
        )
        findings: list[ValidationFinding] = []
        if response.fetch_status is FetchStatus.FAILED:
            findings = []
            outcomes.append(VenueOutcome(
                venue.code, venue.name, FetchStatus.FAILED, JsonPresence.NOT_OBSERVED,
                ValidationStatus.UNCONFIRMED, CalendarStatus(calendar_status),
                calendar_source=calendar_source, calendar_evidence=calendar_evidence,
                findings=findings,
            ))
            continue

        if stadiums is None:
            outcomes.append(VenueOutcome(
                venue.code, venue.name, FetchStatus.SUCCESS, JsonPresence.NOT_OBSERVED,
                ValidationStatus.INVALID, CalendarStatus(calendar_status),
                calendar_source=calendar_source, calendar_evidence=calendar_evidence,
                findings=[],
            ))
            continue

        key = str(venue.code)
        presence = JsonPresence.PRESENT if key in stadiums else JsonPresence.ABSENT
        findings.extend(report.venue_findings.get(venue.code, []))

        if report.file_status is ValidationStatus.INVALID:
            validation_status = ValidationStatus.INVALID
        elif any(item.severity.value == "error" for item in findings):
            validation_status = ValidationStatus.INVALID
        elif report.file_status is ValidationStatus.UNCONFIRMED or any(
            item.severity.value == "unconfirmed" for item in findings
        ):
            validation_status = ValidationStatus.UNCONFIRMED
        else:
            validation_status = ValidationStatus.VALID

        outcomes.append(VenueOutcome(
            venue.code, venue.name, FetchStatus.SUCCESS, presence, validation_status,
            CalendarStatus(calendar_status),
            race_count=report.race_counts.get(venue.code),
            calendar_source=calendar_source, calendar_evidence=calendar_evidence,
            findings=findings,
        ))
    return outcomes
