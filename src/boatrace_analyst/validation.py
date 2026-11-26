"""Three-level validation for the documented v1 response shape."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .models import FindingScope, FindingSeverity, ValidationFinding, ValidationStatus
from .venues import VENUE_BY_CODE


RACE_SCHEMA = {
    "date": "string", "stadium_number": "integer", "race_number": "integer",
    "closed_at": "string", "grade_number": "integer", "grade_number_source": "string",
    "title": "string", "subtitle": "string", "distance": "integer",
    "distance_source": "string", "day_number": "integer", "day_number_source": "string",
    "racers": "object", "preview": "object", "result": "object",
}
ENTRY_SCHEMA = {
    "entry_number": "integer", "name": "string", "number": "integer",
    "rank_number": "integer", "rank_number_source": "string",
    "branch_number": "integer", "branch_number_source": "string",
    "birthplace_number": "integer", "birthplace_number_source": "string",
    "age": "integer", "age_source": "string", "weight": "number", "weight_source": "string",
    "flying_count": "integer", "flying_count_source": "string",
    "late_count": "integer", "late_count_source": "string",
    "average_start_timing": "number", "national_win_rate": "number",
    "national_top_2_percent": "number", "national_top_3_percent": "number",
    "local_win_rate": "number", "local_top_2_percent": "number", "local_top_3_percent": "number",
    "motor_number": "integer", "motor_top_2_percent": "number", "motor_top_3_percent": "number",
    "boat_number": "integer", "boat_top_2_percent": "number", "boat_top_3_percent": "number",
}
PREVIEW_SCHEMA = {
    "date": "string", "stadium_number": "integer", "race_number": "integer",
    "wind_speed": "integer", "wind_speed_source": "string",
    "wind_direction_number": "integer", "wind_direction_number_source": "string",
    "wave_height": "integer", "wave_height_source": "string",
    "weather_number": "integer", "weather_number_source": "string",
    "air_temperature": "number", "air_temperature_source": "string",
    "water_temperature": "number", "water_temperature_source": "string", "racers": "object",
}
PREVIEW_RACER_SCHEMA = {
    "entry_number": "integer", "course_number": "integer", "start_timing": "number",
    "start_timing_source": "string", "weight": "number", "weight_source": "string",
    "weight_adjustment": "number", "weight_adjustment_source": "string",
    "exhibition_time": "number", "exhibition_time_source": "string",
    "tilt_adjustment": "number", "tilt_adjustment_source": "string",
    "propeller": "string", "parts": "array",
}
PART_SCHEMA = {"number": "integer", "number_source": "string", "quantity": "integer"}
RESULT_SCHEMA = {
    "date": "string", "stadium_number": "integer", "race_number": "integer",
    "wind_speed": "integer", "wind_speed_source": "string",
    "wind_direction_number": "integer", "wind_direction_number_source": "string",
    "wave_height": "integer", "wave_height_source": "string",
    "weather_number": "integer", "weather_number_source": "string",
    "air_temperature": "number", "air_temperature_source": "string",
    "water_temperature": "number", "water_temperature_source": "string",
    "technique_number": "integer", "technique_number_source": "string",
    "remarks": "string", "refunds": "array", "racers": "object", "payouts": "object",
}
RESULT_RACER_SCHEMA = {
    "entry_number": "integer", "course_number": "integer", "start_timing": "number",
    "start_timing_source": "string", "place_number": "integer",
    "place_number_source": "string", "number": "integer", "number_source": "string", "name": "string",
}
PAYOUT_SCHEMA = {"combination": "string", "amount": "integer", "label": "string"}


@dataclass
class ValidationReport:
    document: dict[str, Any] | None
    file_status: ValidationStatus
    findings: list[ValidationFinding] = field(default_factory=list)
    venue_findings: dict[int, list[ValidationFinding]] = field(default_factory=dict)
    race_counts: dict[int, int] = field(default_factory=dict)


def validate_payload(raw: bytes, target_date: date) -> ValidationReport:
    try:
        text = raw.decode("utf-8")
        document = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        finding = _finding(
            FindingScope.FILE, FindingSeverity.ERROR, "invalid_json", "$",
            f"Payload is not valid UTF-8 JSON: {exc}", expected="JSON object", actual="invalid",
        )
        return ValidationReport(None, ValidationStatus.INVALID, [finding])

    if not isinstance(document, dict):
        finding = _finding(
            FindingScope.FILE, FindingSeverity.ERROR, "invalid_root_type", "$",
            "The v1 root must be an object", expected="object", actual=_json_type(document),
        )
        return ValidationReport(None, ValidationStatus.INVALID, [finding])

    programs = document.get("programs")
    if not isinstance(programs, dict):
        finding = _finding(
            FindingScope.FILE, FindingSeverity.ERROR, "invalid_programs", "programs",
            "programs must be an object", expected="object", actual=_json_type(programs),
        )
        return ValidationReport(document, ValidationStatus.INVALID, [finding])

    stadiums = programs.get("stadiums")
    if not isinstance(stadiums, dict):
        finding = _finding(
            FindingScope.FILE, FindingSeverity.ERROR, "invalid_stadiums", "programs.stadiums",
            "programs.stadiums must be an object", expected="object", actual=_json_type(stadiums),
        )
        return ValidationReport(document, ValidationStatus.INVALID, [finding])

    file_findings: list[ValidationFinding] = []
    venue_findings: dict[int, list[ValidationFinding]] = {}
    race_counts: dict[int, int] = {}
    any_dates = False

    for stadium_key, stadium_value in stadiums.items():
        try:
            venue_code = int(stadium_key)
        except (TypeError, ValueError):
            file_findings.append(_finding(
                FindingScope.FILE, FindingSeverity.ERROR, "invalid_stadium_key",
                f"programs.stadiums.{stadium_key}", "Venue key is not an integer string",
                expected="integer string", actual=_json_type(stadium_key),
            ))
            continue
        if str(venue_code) != str(stadium_key) or venue_code not in VENUE_BY_CODE:
            file_findings.append(_finding(
                FindingScope.FILE, FindingSeverity.ERROR, "unknown_stadium_code",
                f"programs.stadiums.{stadium_key}", "Venue key is not in the v1 venue table",
                venue_code=venue_code, expected="1..24 v1 venue code", actual=str(stadium_key),
            ))
            continue

        local: list[ValidationFinding] = []
        venue_findings[venue_code] = local
        stadium_path = f"programs.stadiums.{stadium_key}"
        if not isinstance(stadium_value, dict):
            local.append(_finding(
                FindingScope.RACE, FindingSeverity.ERROR, "invalid_stadium_record", stadium_path,
                "Venue record must be an object", venue_code=venue_code,
                expected="object", actual=_json_type(stadium_value),
            ))
            race_counts[venue_code] = 0
            continue
        races = stadium_value.get("races")
        if not isinstance(races, dict):
            local.append(_finding(
                FindingScope.RACE, FindingSeverity.ERROR, "invalid_races_map", f"{stadium_path}.races",
                "races must be an object", venue_code=venue_code,
                expected="object", actual=_json_type(races),
            ))
            race_counts[venue_code] = 0
            continue

        race_counts[venue_code] = len(races)
        if not races:
            local.append(_finding(
                FindingScope.RACE, FindingSeverity.UNCONFIRMED, "empty_races_map", f"{stadium_path}.races",
                "No race records are present; completeness is not defined by the available contract",
                venue_code=venue_code, expected_type="non-empty object", actual_type="empty object",
            ))

        for race_key, race in races.items():
            race_path = f"{stadium_path}.races.{race_key}"
            try:
                race_number_key = int(race_key)
            except (TypeError, ValueError):
                local.append(_finding(
                    FindingScope.RACE, FindingSeverity.ERROR, "invalid_race_key", race_path,
                    "Race key is not an integer string", venue_code=venue_code,
                    expected="integer string", actual=_json_type(race_key),
                ))
                continue
            if not isinstance(race, dict):
                local.append(_finding(
                    FindingScope.RACE, FindingSeverity.ERROR, "invalid_race_record", race_path,
                    "Race record must be an object", venue_code=venue_code, race_number=race_number_key,
                    expected="object", actual=_json_type(race),
                ))
                continue

            _validate_fields(race, RACE_SCHEMA, race_path, local, venue_code, race_number_key)
            _check_identity(race, "stadium_number", venue_code, race_path, local, venue_code, race_number_key)
            _check_identity(race, "race_number", race_number_key, race_path, local, venue_code, race_number_key)
            any_dates |= _check_date(race, race_path, target_date, local, venue_code, race_number_key)

            _validate_racer_map(race.get("racers"), ENTRY_SCHEMA, f"{race_path}.racers", local, venue_code, race_number_key)
            preview = race.get("preview")
            if isinstance(preview, dict):
                _validate_fields(preview, PREVIEW_SCHEMA, f"{race_path}.preview", local, venue_code, race_number_key)
                _check_identity(preview, "stadium_number", venue_code, f"{race_path}.preview", local, venue_code, race_number_key)
                _check_identity(preview, "race_number", race_number_key, f"{race_path}.preview", local, venue_code, race_number_key)
                any_dates |= _check_date(preview, f"{race_path}.preview", target_date, local, venue_code, race_number_key)
                _validate_preview_racers(preview.get("racers"), f"{race_path}.preview.racers", local, venue_code, race_number_key)

            result = race.get("result")
            if isinstance(result, dict):
                _validate_fields(result, RESULT_SCHEMA, f"{race_path}.result", local, venue_code, race_number_key)
                _check_identity(result, "stadium_number", venue_code, f"{race_path}.result", local, venue_code, race_number_key)
                _check_identity(result, "race_number", race_number_key, f"{race_path}.result", local, venue_code, race_number_key)
                any_dates |= _check_date(result, f"{race_path}.result", target_date, local, venue_code, race_number_key)
                _validate_racer_map(result.get("racers"), RESULT_RACER_SCHEMA, f"{race_path}.result.racers", local, venue_code, race_number_key)
                _validate_payouts(result.get("payouts"), f"{race_path}.result.payouts", local, venue_code, race_number_key)
                _validate_integer_array(result.get("refunds"), f"{race_path}.result.refunds", local, venue_code, race_number_key)

    if not any_dates:
        file_findings.append(_finding(
            FindingScope.FILE, FindingSeverity.UNCONFIRMED, "target_date_unverifiable", "programs.stadiums",
            "No race date was available to compare with the requested target date",
            expected_type="date string", actual_type="missing",
        ))

    if any(
        finding.code == "target_date_mismatch" and finding.severity is FindingSeverity.ERROR
        for group in venue_findings.values() for finding in group
    ):
        file_findings.append(_finding(
            FindingScope.FILE, FindingSeverity.ERROR, "target_date_mismatch", "programs.stadiums",
            "At least one race date differs from the requested target date",
            expected=target_date.isoformat(), actual="one or more mismatched race dates",
        ))

    all_findings = file_findings + [finding for group in venue_findings.values() for finding in group]
    if any(f.severity is FindingSeverity.ERROR for f in file_findings):
        file_status = ValidationStatus.INVALID
    elif any(f.severity is FindingSeverity.UNCONFIRMED for f in file_findings):
        file_status = ValidationStatus.UNCONFIRMED
    else:
        file_status = ValidationStatus.VALID
    return ValidationReport(document, file_status, all_findings, venue_findings, race_counts)


def _validate_fields(
    record: dict[str, Any], schema: dict[str, str], path: str,
    findings: list[ValidationFinding], venue_code: int, race_number: int,
) -> None:
    for field_name, expected in schema.items():
        field_path = f"{path}.{field_name}"
        if field_name not in record:
            findings.append(_finding(
                FindingScope.FIELD, FindingSeverity.UNCONFIRMED, "field_presence_unconfirmed", field_path,
                "The published field list does not define requiredness for every field",
                venue_code=venue_code, race_number=race_number,
                expected=expected, actual="missing",
            ))
            continue
        value = record[field_name]
        if value is None:
            if _null_is_documented(field_name, path):
                continue
            findings.append(_finding(
                FindingScope.FIELD, FindingSeverity.UNCONFIRMED, "null_semantics_unconfirmed", field_path,
                "This field is null, but the available specification does not define that null case",
                venue_code=venue_code, race_number=race_number,
                expected=expected, actual="null",
            ))
            continue
        if not _matches_type(value, expected):
            findings.append(_finding(
                FindingScope.FIELD, FindingSeverity.ERROR, "field_type_mismatch", field_path,
                "Field value does not match the v1 type", venue_code=venue_code,
                race_number=race_number, expected=expected, actual=_json_type(value),
            ))


def _null_is_documented(field_name: str, path: str) -> bool:
    if field_name in {"propeller", "quantity", "remarks", "amount", "label"}:
        return True
    if field_name == "start_timing":
        return True
    if field_name == "day_number":
        return True
    return False


def _validate_racer_map(
    value: Any, schema: dict[str, str], path: str,
    findings: list[ValidationFinding], venue_code: int, race_number: int,
) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        findings.append(_finding(
            FindingScope.RACE, FindingSeverity.ERROR, "invalid_racer_map", path,
            "Racer collection must be an object", venue_code=venue_code,
            race_number=race_number, expected="object", actual=_json_type(value),
        ))
        return
    for entry_key, racer in value.items():
        racer_path = f"{path}.{entry_key}"
        try:
            entry_number = int(entry_key)
        except (TypeError, ValueError):
            findings.append(_finding(
                FindingScope.RACE, FindingSeverity.ERROR, "invalid_entry_key", racer_path,
                "Entry key must be an integer string", venue_code=venue_code,
                race_number=race_number, expected="integer string", actual=_json_type(entry_key),
            ))
            continue
        if not isinstance(racer, dict):
            findings.append(_finding(
                FindingScope.RACE, FindingSeverity.ERROR, "invalid_racer_record", racer_path,
                "Racer record must be an object", venue_code=venue_code,
                race_number=race_number, expected="object", actual=_json_type(racer),
            ))
            continue
        _validate_fields(racer, schema, racer_path, findings, venue_code, race_number)
        _check_identity(racer, "entry_number", entry_number, racer_path, findings, venue_code, race_number)


def _validate_preview_racers(
    value: Any, path: str, findings: list[ValidationFinding], venue_code: int, race_number: int,
) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        findings.append(_finding(
            FindingScope.RACE, FindingSeverity.ERROR, "invalid_preview_racers", path,
            "preview.racers must be an object", venue_code=venue_code,
            race_number=race_number, expected="object", actual=_json_type(value),
        ))
        return
    for entry_key, racer in value.items():
        racer_path = f"{path}.{entry_key}"
        try:
            entry_number = int(entry_key)
        except (TypeError, ValueError):
            findings.append(_finding(
                FindingScope.RACE, FindingSeverity.ERROR, "invalid_entry_key", racer_path,
                "Entry key must be an integer string", venue_code=venue_code,
                race_number=race_number, expected="integer string", actual=_json_type(entry_key),
            ))
            continue
        if not isinstance(racer, dict):
            findings.append(_finding(
                FindingScope.RACE, FindingSeverity.ERROR, "invalid_preview_racer", racer_path,
                "Preview racer record must be an object", venue_code=venue_code,
                race_number=race_number, expected="object", actual=_json_type(racer),
            ))
            continue
        _validate_fields(racer, PREVIEW_RACER_SCHEMA, racer_path, findings, venue_code, race_number)
        _check_identity(racer, "entry_number", entry_number, racer_path, findings, venue_code, race_number)
        parts = racer.get("parts")
        if isinstance(parts, list):
            for index, part in enumerate(parts):
                part_path = f"{racer_path}.parts.{index}"
                if not isinstance(part, dict):
                    findings.append(_finding(
                        FindingScope.FIELD, FindingSeverity.ERROR, "invalid_part_record", part_path,
                        "Part record must be an object", venue_code=venue_code,
                        race_number=race_number, expected="object", actual=_json_type(part),
                    ))
                else:
                    _validate_fields(part, PART_SCHEMA, part_path, findings, venue_code, race_number)


def _validate_payouts(
    value: Any, path: str, findings: list[ValidationFinding], venue_code: int, race_number: int,
) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        findings.append(_finding(
            FindingScope.RACE, FindingSeverity.ERROR, "invalid_payouts", path,
            "payouts must be an object", venue_code=venue_code,
            race_number=race_number, expected="object", actual=_json_type(value),
        ))
        return
    for bet_type, payouts in value.items():
        bet_path = f"{path}.{bet_type}"
        if not isinstance(payouts, list):
            findings.append(_finding(
                FindingScope.RACE, FindingSeverity.ERROR, "invalid_payout_array", bet_path,
                "Each payout type must contain an array", venue_code=venue_code,
                race_number=race_number, expected="array", actual=_json_type(payouts),
            ))
            continue
        for index, payout in enumerate(payouts):
            payout_path = f"{bet_path}.{index}"
            if not isinstance(payout, dict):
                findings.append(_finding(
                    FindingScope.FIELD, FindingSeverity.ERROR, "invalid_payout_record", payout_path,
                    "Payout entry must be an object", venue_code=venue_code,
                    race_number=race_number, expected="object", actual=_json_type(payout),
                ))
            else:
                _validate_fields(payout, PAYOUT_SCHEMA, payout_path, findings, venue_code, race_number)


def _validate_integer_array(
    value: Any, path: str, findings: list[ValidationFinding], venue_code: int, race_number: int,
) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        findings.append(_finding(
            FindingScope.FIELD, FindingSeverity.ERROR, "invalid_integer_array", path,
            "Expected an array of integers", venue_code=venue_code,
            race_number=race_number, expected="integer[]", actual=_json_type(value),
        ))
        return
    for index, item in enumerate(value):
        if not _matches_type(item, "integer"):
            findings.append(_finding(
                FindingScope.FIELD, FindingSeverity.ERROR, "array_item_type_mismatch", f"{path}.{index}",
                "Array item does not match integer type", venue_code=venue_code,
                race_number=race_number, expected="integer", actual=_json_type(item),
            ))


def _check_identity(
    record: dict[str, Any], field_name: str, expected_value: int, path: str,
    findings: list[ValidationFinding], venue_code: int, race_number: int,
) -> None:
    if field_name not in record:
        return
    value = record[field_name]
    if isinstance(value, bool) or not isinstance(value, int):
        return
    if value != expected_value:
        findings.append(_finding(
            FindingScope.RACE, FindingSeverity.ERROR, "key_value_mismatch", f"{path}.{field_name}",
            "Object key and numeric identity field do not match", venue_code=venue_code,
            race_number=race_number, expected=str(expected_value), actual=str(value),
        ))


def _check_date(
    record: dict[str, Any], path: str, target_date: date,
    findings: list[ValidationFinding], venue_code: int, race_number: int,
) -> bool:
    if "date" not in record:
        findings.append(_finding(
            FindingScope.FIELD, FindingSeverity.UNCONFIRMED, "date_missing", f"{path}.date",
            "Target date cannot be checked because the date key is absent",
            venue_code=venue_code, race_number=race_number, expected="YYYY-MM-DD", actual="missing",
        ))
        return False
    value = record["date"]
    if not isinstance(value, str):
        return False
    try:
        observed = date.fromisoformat(value)
    except ValueError:
        findings.append(_finding(
            FindingScope.FIELD, FindingSeverity.ERROR, "invalid_date", f"{path}.date",
            "Date is not a valid ISO calendar date", venue_code=venue_code,
            race_number=race_number, expected="YYYY-MM-DD", actual=value,
        ))
        return False
    if observed != target_date:
        findings.append(_finding(
            FindingScope.FIELD, FindingSeverity.ERROR, "target_date_mismatch", f"{path}.date",
            "JSON date does not match the requested target date", venue_code=venue_code,
            race_number=race_number, expected=target_date.isoformat(), actual=value,
        ))
        return True
    return True


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _finding(
    scope: FindingScope, severity: FindingSeverity, code: str, field_path: str,
    message: str, venue_code: int | None = None, race_number: int | None = None,
    expected: str | None = None, actual: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        scope=scope, severity=severity, code=code, field_path=field_path,
        message=message, venue_code=venue_code, race_number=race_number,
        expected_type=expected, actual_type=actual,
    )
