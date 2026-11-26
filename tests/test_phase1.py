from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from boatrace_analyst.config import AppConfig, require_database_write_permission
from boatrace_analyst.models import (
    CalendarStatus, DataStatus, FetchResponse, FetchStatus, JsonPresence, RunResult,
    ValidationStatus,
)
from boatrace_analyst.postgres import PostgresHistoryRepository
from boatrace_analyst.repository import JsonlHistoryRepository, repository_for
from boatrace_analyst.service import run_ingestion
from boatrace_analyst.sources import DateJsonSource, UnconfirmedCalendarProvider, dated_url
from boatrace_analyst.validation import validate_payload
from boatrace_analyst.venues import VENUES


TARGET = date(2026, 11, 27)
FAKE_DATABASE_URL = "postgresql://phase1-test.invalid/unused"


def valid_payload(venue_code: int = 3, target: date = TARGET) -> bytes:
    race = {
        "date": target.isoformat(),
        "stadium_number": venue_code,
        "race_number": 1,
        "racers": {},
        "preview": {"date": target.isoformat(), "racers": {}},
        "result": {"date": target.isoformat(), "racers": {}, "payouts": {}},
    }
    document = {"programs": {"stadiums": {str(venue_code): {"races": {"1": race}}}}}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class FakeSource:
    def __init__(self, body: bytes | None = None, error_code: str | None = None) -> None:
        self.body = body
        self.error_code = error_code

    def fetch(self, target_date: date) -> FetchResponse:
        return FetchResponse(
            source_url=dated_url(target_date),
            requested_at="2026-11-27T00:00:00+00:00",
            retrieved_at="2026-11-27T00:00:01+00:00",
            http_status=200 if self.body is not None else None,
            body=self.body,
            error_code=self.error_code,
            error_message="mock failure" if self.error_code else None,
        )


class NoEventCalendar:
    def status_for(self, venue_code: int, target_date: date):
        if venue_code == 5:
            return CalendarStatus.NO_EVENT, "test-calendar", "explicit test evidence"
        return CalendarStatus.UNCONFIRMED, None, "no verified schedule"


class Phase1Tests(unittest.TestCase):
    def config(self, path: Path, env: dict[str, str] | None = None) -> AppConfig:
        values = {"PHASE1_LOCAL_HISTORY_PATH": str(path)}
        if env:
            values.update(env)
        return AppConfig.from_environment(TARGET, values)

    def sample_run_result(self) -> RunResult:
        return RunResult(
            run_id="00000000-0000-0000-0000-000000000001",
            target_date=TARGET,
            source_url="mock://source",
            requested_at="2026-11-27T00:00:00+00:00",
            retrieved_at="2026-11-27T00:00:01+00:00",
            fetch_status=FetchStatus.SUCCESS,
            validation_status=ValidationStatus.VALID,
            http_status=200,
            payload_sha256=None,
            outcomes=[],
        )

    def test_venue_table_has_exactly_24_unique_codes(self) -> None:
        codes = [venue.code for venue in VENUES]
        self.assertEqual(len(VENUES), 24)
        self.assertEqual(len(set(codes)), 24)
        self.assertEqual(set(codes), set(range(1, 25)))

    def test_date_endpoint_uses_target_date(self) -> None:
        self.assertEqual(
            dated_url(TARGET),
            "https://boatraceopenapi.github.io/api/v1/2026/20261127.json",
        )

    def test_http_client_uses_mocked_opener(self) -> None:
        opener = Mock(return_value=FakeResponse(valid_payload()))
        response = DateJsonSource(opener=opener).fetch(TARGET)
        self.assertEqual(response.fetch_status, FetchStatus.SUCCESS)
        self.assertEqual(response.http_status, 200)
        opener.assert_called_once()
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, dated_url(TARGET))

    def test_transport_failure_is_not_json_absence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_ingestion(
                self.config(Path(directory) / "history.ndjson"),
                source=FakeSource(error_code="network_error"),
            )
        self.assertEqual(result.fetch_status, FetchStatus.FAILED)
        self.assertEqual({outcome.data_status for outcome in result.outcomes}, {DataStatus.FETCH_FAILED})
        self.assertEqual({outcome.json_presence for outcome in result.outcomes}, {JsonPresence.NOT_OBSERVED})

    def test_absent_json_key_is_distinct_from_confirmed_no_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_ingestion(
                self.config(Path(directory) / "history.ndjson"),
                source=FakeSource(valid_payload(3)),
                calendar_provider=NoEventCalendar(),
            )
        by_code = {outcome.venue_code: outcome for outcome in result.outcomes}
        self.assertEqual(len(by_code), 24)
        self.assertEqual(by_code[5].data_status, DataStatus.JSON_ABSENT)
        self.assertEqual(by_code[5].json_presence, JsonPresence.ABSENT)
        self.assertEqual(by_code[5].calendar_status, CalendarStatus.NO_EVENT)
        self.assertEqual(by_code[3].data_status, DataStatus.SUCCESS)
        self.assertEqual(by_code[4].calendar_status, CalendarStatus.UNCONFIRMED)

    def test_target_date_mismatch_is_invalid_and_not_rewritten(self) -> None:
        raw = valid_payload(target=date(2026, 11, 26))
        before = raw
        report = validate_payload(raw, TARGET)
        self.assertEqual(report.file_status, ValidationStatus.INVALID)
        self.assertIn(b"2026-11-26", raw)
        self.assertEqual(raw, before)

    def test_invalid_json_is_file_level_error(self) -> None:
        report = validate_payload(b"{broken", TARGET)
        self.assertEqual(report.file_status, ValidationStatus.INVALID)
        self.assertEqual(report.findings[0].scope.value, "file")

    def test_race_identity_mismatch_is_race_level_error(self) -> None:
        document = json.loads(valid_payload())
        document["programs"]["stadiums"]["3"]["races"]["1"]["race_number"] = 2
        report = validate_payload(json.dumps(document).encode(), TARGET)
        self.assertTrue(any(f.code == "key_value_mismatch" and f.scope.value == "race" for f in report.findings))

    def test_wrong_field_type_is_field_level_error(self) -> None:
        document = json.loads(valid_payload())
        document["programs"]["stadiums"]["3"]["races"]["1"]["distance"] = "1800"
        report = validate_payload(json.dumps(document).encode(), TARGET)
        self.assertTrue(any(f.code == "field_type_mismatch" and f.scope.value == "field" for f in report.findings))

    def test_ambiguous_null_is_unconfirmed_not_filled(self) -> None:
        document = json.loads(valid_payload())
        race = document["programs"]["stadiums"]["3"]["races"]["1"]
        race["preview"]["racers"] = {"1": {"entry_number": 1, "course_number": None}}
        raw = json.dumps(document).encode()
        report = validate_payload(raw, TARGET)
        self.assertTrue(any(f.code == "null_semantics_unconfirmed" for f in report.findings))
        self.assertIsNone(json.loads(raw)["programs"]["stadiums"]["3"]["races"]["1"]["preview"]["racers"]["1"]["course_number"])

    def test_database_url_absent_does_not_construct_postgres_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory) / "history.ndjson")
            with patch("boatrace_analyst.postgres.PostgresHistoryRepository._connect") as connect:
                result = run_ingestion(config, source=FakeSource(valid_payload()))
                connect.assert_not_called()
            self.assertTrue(config.history_path.exists())
        self.assertEqual(result.persistence_status, "local_ndjson_only")

    def test_database_write_permission_requires_both_settings(self) -> None:
        denied_environments = (
            {},
            {"DATABASE_URL": FAKE_DATABASE_URL},
            {"PHASE1_DB_WRITE_ENABLED": "true"},
            {"DATABASE_URL": FAKE_DATABASE_URL, "PHASE1_DB_WRITE_ENABLED": "false"},
        )
        for environment in denied_environments:
            with self.subTest(environment=environment):
                with self.assertRaises(PermissionError):
                    require_database_write_permission(environ=environment)

        authorized = {
            "DATABASE_URL": FAKE_DATABASE_URL,
            "PHASE1_DB_WRITE_ENABLED": "true",
        }
        self.assertEqual(
            require_database_write_permission(FAKE_DATABASE_URL, environ=authorized),
            FAKE_DATABASE_URL,
        )
        with self.assertRaises(PermissionError):
            require_database_write_permission("postgresql://different.invalid/db", environ=authorized)

    def test_postgres_repository_direct_construction_requires_both_settings(self) -> None:
        with patch.dict(os.environ, {"PHASE1_DB_WRITE_ENABLED": "true"}, clear=True):
            with patch.object(PostgresHistoryRepository, "_connect") as connect:
                with self.assertRaises(PermissionError):
                    PostgresHistoryRepository(FAKE_DATABASE_URL)
                connect.assert_not_called()

        with patch.dict(os.environ, {"DATABASE_URL": FAKE_DATABASE_URL}, clear=True):
            with patch.object(PostgresHistoryRepository, "_connect") as connect:
                with self.assertRaises(PermissionError):
                    PostgresHistoryRepository(FAKE_DATABASE_URL)
                connect.assert_not_called()

    def test_direct_postgres_append_and_migration_are_blocked_when_flag_is_false(self) -> None:
        enabled_environment = {
            "DATABASE_URL": FAKE_DATABASE_URL,
            "PHASE1_DB_WRITE_ENABLED": "true",
        }
        with patch.dict(os.environ, enabled_environment, clear=True):
            repository = PostgresHistoryRepository(FAKE_DATABASE_URL)

        disabled_environment = {
            "DATABASE_URL": FAKE_DATABASE_URL,
            "PHASE1_DB_WRITE_ENABLED": "false",
        }
        with patch.dict(os.environ, disabled_environment, clear=True):
            with patch.object(repository, "_connect") as connect:
                with self.assertRaises(PermissionError):
                    repository.append(self.sample_run_result(), b"{}")
                with self.assertRaises(PermissionError):
                    repository.migrate()
                connect.assert_not_called()

    def test_disabled_write_flag_keeps_repository_on_local_ndjson(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.ndjson"
            config = self.config(
                path,
                {"DATABASE_URL": FAKE_DATABASE_URL, "PHASE1_DB_WRITE_ENABLED": "false"},
            )
            with patch("boatrace_analyst.postgres.PostgresHistoryRepository") as postgres_repository:
                selected = repository_for(config)
                postgres_repository.assert_not_called()
            self.assertIsInstance(selected, JsonlHistoryRepository)

            result = run_ingestion(config, source=FakeSource(valid_payload()))
            self.assertEqual(result.persistence_status, "local_ndjson_only")
            self.assertTrue(path.exists())

    def test_run_ingestion_rejects_explicit_postgres_repository_before_fetch(self) -> None:
        enabled_environment = {
            "DATABASE_URL": FAKE_DATABASE_URL,
            "PHASE1_DB_WRITE_ENABLED": "true",
        }
        with patch.dict(os.environ, enabled_environment, clear=True):
            repository = PostgresHistoryRepository(FAKE_DATABASE_URL)

        with tempfile.TemporaryDirectory() as directory:
            config = self.config(
                Path(directory) / "history.ndjson",
                {"DATABASE_URL": FAKE_DATABASE_URL, "PHASE1_DB_WRITE_ENABLED": "false"},
            )
            source = Mock()
            with patch.dict(os.environ, enabled_environment, clear=True):
                with patch.object(repository, "_connect") as connect:
                    with self.assertRaises(PermissionError):
                        run_ingestion(config, source=source, repository=repository)
                    source.fetch.assert_not_called()
                    connect.assert_not_called()

    def test_run_ingestion_rechecks_live_write_permission_for_injected_repository(self) -> None:
        enabled_environment = {
            "DATABASE_URL": FAKE_DATABASE_URL,
            "PHASE1_DB_WRITE_ENABLED": "true",
        }
        with patch.dict(os.environ, enabled_environment, clear=True):
            repository = PostgresHistoryRepository(FAKE_DATABASE_URL)

        with tempfile.TemporaryDirectory() as directory:
            config = self.config(
                Path(directory) / "history.ndjson",
                {"DATABASE_URL": FAKE_DATABASE_URL, "PHASE1_DB_WRITE_ENABLED": "true"},
            )
            source = Mock()
            disabled_environment = {
                "DATABASE_URL": FAKE_DATABASE_URL,
                "PHASE1_DB_WRITE_ENABLED": "false",
            }
            with patch.dict(os.environ, disabled_environment, clear=True):
                with patch.object(repository, "_connect") as connect:
                    with self.assertRaises(PermissionError):
                        run_ingestion(config, source=source, repository=repository)
                    source.fetch.assert_not_called()
                    connect.assert_not_called()

    def test_ndjson_appends_each_run_without_replacing_previous_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.ndjson"
            repository = JsonlHistoryRepository(path)
            first = run_ingestion(self.config(path), source=FakeSource(valid_payload()), repository=repository)
            first_line = path.read_text(encoding="utf-8").splitlines()[0]
            second = run_ingestion(self.config(path), source=FakeSource(valid_payload()), repository=repository)
            lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], first_line)
        self.assertEqual(json.loads(lines[1])["run_id"], second.run_id)

    def test_workflow_is_manual_only_and_artifact_retention_is_30_days(self) -> None:
        workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "phase1-ingestion.yml"
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("retention-days: 30", text)
        self.assertNotIn("schedule:", text)
        self.assertNotIn("pull_request:", text)
        self.assertNotIn("push:", text)

    def test_sql_guards_history_tables_against_update_and_delete(self) -> None:
        schema = (Path(__file__).resolve().parents[1] / "sql" / "001_phase1.sql").read_text(encoding="utf-8")
        self.assertGreaterEqual(schema.count("BEFORE UPDATE OR DELETE"), 3)
        self.assertIn("Phase 1 history is append-only", schema)


if __name__ == "__main__":
    unittest.main()
