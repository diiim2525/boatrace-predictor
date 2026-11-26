"""Command-line entry point for local and manual workflow runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import AppConfig
from .models import DataStatus, FetchStatus, ValidationStatus
from .postgres import PostgresHistoryRepository
from .repository import repository_for
from .service import run_ingestion


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="boatrace-phase1")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Fetch, validate, and append one target-date run")
    run.add_argument("--target-date", default=None, help="Target date YYYY-MM-DD; defaults to Japan local date")
    commands.add_parser("migrate", help="Apply the Phase 1 schema using an explicitly enabled DB")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = AppConfig.from_environment(getattr(args, "target_date", None))
    if args.command == "migrate":
        if not config.db_write_enabled or not config.database_url:
            print("DB migration refused: DATABASE_URL and PHASE1_DB_WRITE_ENABLED=true are required", file=sys.stderr)
            return 2
        PostgresHistoryRepository(config.database_url).migrate()
        print("Phase 1 schema applied")
        return 0

    try:
        result = run_ingestion(config)
    except Exception as exc:
        print(f"Phase 1 run failed before persistence: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if result.persistence_status == "local_ndjson_only":
        print(
            "DB未接続: ローカルNDJSONに追記しました。DB保存・永続保存完了を意味しません。",
            file=sys.stderr,
        )
    elif result.persistence_status == "local_fallback_db_commit_unconfirmed":
        print(
            "DB書き込み結果未確認: ローカルNDJSONに追記しました。DB保存完了とは表示しません。",
            file=sys.stderr,
        )
    if result.fetch_status is FetchStatus.FAILED or result.validation_status is ValidationStatus.INVALID:
        return 1
    if any(outcome.data_status is DataStatus.INVALID for outcome in result.outcomes):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
