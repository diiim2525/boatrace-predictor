"""HTTP retrieval and the deliberately disabled schedule-source adapter."""

from __future__ import annotations

import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Callable, Protocol

from .models import CalendarStatus, FetchResponse


V1_BASE_URL = "https://boatraceopenapi.github.io/api/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dated_url(target_date: date) -> str:
    return f"{V1_BASE_URL}/{target_date:%Y}/{target_date:%Y%m%d}.json"


class DateJsonSource:
    def __init__(
        self,
        opener: Callable[..., object] | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._opener = opener or urllib.request.urlopen
        self._timeout_seconds = timeout_seconds

    def fetch(self, target_date: date) -> FetchResponse:
        url = dated_url(target_date)
        requested_at = utc_now()
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "boatrace-analyst-phase1/0.1",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                body = response.read()
                status = int(getattr(response, "status", getattr(response, "code", 200)))
            retrieved_at = utc_now()
            if status < 200 or status >= 300:
                return FetchResponse(
                    url, requested_at, retrieved_at, status, None,
                    error_code=f"http_{status}",
                    error_message=f"Source returned HTTP {status}",
                )
            return FetchResponse(url, requested_at, retrieved_at, status, body)
        except urllib.error.HTTPError as exc:
            return FetchResponse(
                url, requested_at, utc_now(), exc.code, None,
                error_code=f"http_{exc.code}",
                error_message=f"Source returned HTTP {exc.code}",
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", None)
            detail = str(reason if reason is not None else exc)[:240]
            return FetchResponse(
                url, requested_at, utc_now(), None, None,
                error_code="network_error",
                error_message=detail or "Network request failed",
            )


class CalendarEvidenceProvider(Protocol):
    def status_for(self, venue_code: int, target_date: date) -> tuple[CalendarStatus, str | None, str | None]:
        """Return status, source URL, and evidence note."""


class UnconfirmedCalendarProvider:
    """No automated monthly-schedule parser is enabled until its contract is verified."""

    def status_for(self, venue_code: int, target_date: date) -> tuple[CalendarStatus, str | None, str | None]:
        return CalendarStatus.UNCONFIRMED, None, "schedule_source_not_verified"
