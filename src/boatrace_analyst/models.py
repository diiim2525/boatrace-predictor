"""Shared records and explicit state values for Phase 1."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class TextEnum(str, Enum):
    """An enum that serializes to its stable string value."""


class FetchStatus(TextEnum):
    NOT_ATTEMPTED = "not_attempted"
    SUCCESS = "success"
    FAILED = "failed"


class JsonPresence(TextEnum):
    PRESENT = "present"
    ABSENT = "absent"
    NOT_OBSERVED = "not_observed"


class DataStatus(TextEnum):
    NOT_ATTEMPTED = "not_attempted"
    FETCH_FAILED = "fetch_failed"
    JSON_ABSENT = "json_absent"
    SUCCESS = "success"
    INVALID = "invalid"


class ValidationStatus(TextEnum):
    VALID = "valid"
    INVALID = "invalid"
    UNCONFIRMED = "unconfirmed"


class CalendarStatus(TextEnum):
    SCHEDULED = "scheduled"
    NO_EVENT = "no_event"
    UNCONFIRMED = "unconfirmed"


class FindingScope(TextEnum):
    FILE = "file"
    RACE = "race"
    FIELD = "field"


class FindingSeverity(TextEnum):
    ERROR = "error"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True)
class FetchResponse:
    source_url: str
    requested_at: str
    retrieved_at: str
    http_status: int | None
    body: bytes | None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def fetch_status(self) -> FetchStatus:
        return FetchStatus.SUCCESS if self.body is not None and self.error_code is None else FetchStatus.FAILED


@dataclass(frozen=True)
class ValidationFinding:
    scope: FindingScope
    severity: FindingSeverity
    code: str
    field_path: str
    message: str
    venue_code: int | None = None
    race_number: int | None = None
    expected_type: str | None = None
    actual_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: _enum_value(value) for key, value in asdict(self).items()}


@dataclass
class VenueOutcome:
    venue_code: int
    venue_name: str
    fetch_status: FetchStatus
    json_presence: JsonPresence
    validation_status: ValidationStatus
    calendar_status: CalendarStatus = CalendarStatus.UNCONFIRMED
    race_count: int | None = None
    calendar_source: str | None = None
    calendar_evidence: str | None = None
    findings: list[ValidationFinding] = field(default_factory=list)

    @property
    def data_status(self) -> DataStatus:
        if self.fetch_status is FetchStatus.NOT_ATTEMPTED:
            return DataStatus.NOT_ATTEMPTED
        if self.fetch_status is FetchStatus.FAILED:
            return DataStatus.FETCH_FAILED
        if self.validation_status is ValidationStatus.INVALID:
            return DataStatus.INVALID
        if self.json_presence is JsonPresence.ABSENT:
            return DataStatus.JSON_ABSENT
        if self.json_presence is JsonPresence.PRESENT:
            return DataStatus.SUCCESS
        return DataStatus.INVALID

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue_code": self.venue_code,
            "venue_name": self.venue_name,
            "fetch_status": self.fetch_status.value,
            "json_presence": self.json_presence.value,
            "data_status": self.data_status.value,
            "validation_status": self.validation_status.value,
            "calendar_status": self.calendar_status.value,
            "race_count": self.race_count,
            "calendar_source": self.calendar_source,
            "calendar_evidence": self.calendar_evidence,
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass
class RunResult:
    run_id: str
    target_date: date
    source_url: str
    requested_at: str
    retrieved_at: str
    fetch_status: FetchStatus
    validation_status: ValidationStatus
    http_status: int | None
    payload_sha256: str | None
    outcomes: list[VenueOutcome]
    findings: list[ValidationFinding] = field(default_factory=list)
    persistence_status: str = "not_saved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "target_date": self.target_date.isoformat(),
            "source_url": self.source_url,
            "requested_at": self.requested_at,
            "retrieved_at": self.retrieved_at,
            "fetch_status": self.fetch_status.value,
            "validation_status": self.validation_status.value,
            "http_status": self.http_status,
            "payload_sha256": self.payload_sha256,
            "persistence_status": self.persistence_status,
            "venue_count": len(self.outcomes),
            "venues": [outcome.to_dict() for outcome in self.outcomes],
            "findings": [finding.to_dict() for finding in self.findings],
        }


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value
