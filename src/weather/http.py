"""Robust HTTP for the weather project: one function every request goes through.

``request_with_retries`` adds, in one place, the four behaviours Part C asks for:

    1. a timeout on every request (never wait forever);
    2. ``raise_for_status()`` so HTTP errors are not mistaken for data;
    3. retries with exponential backoff for TEMPORARY failures (connection errors,
       timeouts, HTTP 5xx, HTTP 429), up to a retry cap;
    4. a clear custom exception (:class:`WeatherAPIError`) when it finally gives up.

Permanent failures (HTTP 4xx such as 400 "invalid latitude") are NOT retried: asking the
same wrong question again cannot help and only adds traffic.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, Mapping, Optional

import requests

PLACEHOLDER_EMAIL = "your.name@university.example"
APP_NAME = "oop-assignment2-weather/1.0"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class WeatherError(Exception):
    """Base class for every error raised by the weather code."""


class WeatherAPIError(WeatherError):
    """A request failed for good (after retries, or immediately for a 4xx response).

    Attributes:
        url: The URL requested.
        attempts: How many attempts were made.
        status: Last HTTP status code, or None if no response was received.
    """

    def __init__(self, message: str, url: str = "", attempts: int = 0, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.url, self.attempts, self.status = url, attempts, status


class LocationNotFoundError(WeatherError):
    """The geocoder returned no match for the place name."""


class ConfigError(WeatherError):
    """The configuration is unusable, e.g. the contact email is still the placeholder."""


# ---------------------------------------------------------------------------
# Identification
# ---------------------------------------------------------------------------
def contact_email(config_value: str = PLACEHOLDER_EMAIL) -> str:
    """Contact email from the WEATHER_CONTACT_EMAIL environment variable, else the config cell."""
    return os.environ.get("WEATHER_CONTACT_EMAIL", config_value).strip()


def is_placeholder(email: str) -> bool:
    """True if ``email`` is missing, malformed, or still the placeholder."""
    email = (email or "").strip().lower()
    return (not email) or email == PLACEHOLDER_EMAIL or "@" not in email or email.endswith(".example")


def build_user_agent(email: str, require_contact: bool = False) -> str:
    """User-Agent header identifying this program.

    With a real email: ``oop-assignment2-weather/1.0 (student project; contact: a@b.ac.ug)``.
    With the placeholder: the app name only, because we must never invent contact details.
    MET Norway requires a contact, so pass ``require_contact=True`` for it.
    """
    if is_placeholder(email):
        if require_contact:
            raise ConfigError(
                "This API requires a real contact email in the User-Agent. Set CONTACT_EMAIL in the "
                "configuration cell (or the WEATHER_CONTACT_EMAIL environment variable) to your own "
                "university email."
            )
        return f"{APP_NAME} (student project)"
    return f"{APP_NAME} (student project; contact: {email})"


# ---------------------------------------------------------------------------
# The request wrapper
# ---------------------------------------------------------------------------
def _api_reason(response: requests.Response) -> str:
    """Pull the API's own explanation out of an error body, if it sent one."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200].strip()
    if isinstance(body, dict):
        return str(body.get("reason") or body.get("error") or body)
    return str(body)[:200]


def request_with_retries(
    url: str,
    params: Optional[Mapping[str, Any]] = None,
    *,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = 10.0,
    max_retries: int = 3,
    backoff: float = 0.5,
    session: Optional[Any] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> requests.Response:
    """GET ``url`` and return the successful Response.

    Args:
        url: Endpoint to call.
        params: Query parameters; ``requests`` encodes them safely.
        headers: Extra headers such as User-Agent.
        timeout: Seconds to wait for a connection and for data before giving up.
        max_retries: Extra attempts after the first one (retry cap).
        backoff: Base delay; waits ``backoff * 2**n`` seconds before retry n (0.5, 1, 2, ...).
        session: Object with a ``get`` method (a ``requests.Session``, or a fake in tests).
        sleep: Function used to wait; replaced in tests so they run instantly.

    Raises:
        WeatherAPIError: on a 4xx response (immediately) or when every attempt failed.
    """
    if max_retries < 0 or timeout <= 0 or backoff < 0:
        raise ValueError("max_retries and backoff must be >= 0 and timeout > 0.")
    http = session or requests
    attempts = max_retries + 1
    last_problem = "unknown error"
    last_status: Optional[int] = None

    for attempt in range(attempts):
        try:
            response = http.get(url, params=params, headers=headers, timeout=timeout)
            last_status = response.status_code
            if response.status_code in RETRY_STATUS:
                last_problem = f"HTTP {response.status_code} (temporary server problem)"
            else:
                try:
                    response.raise_for_status()
                except requests.HTTPError:
                    # 4xx: our request is wrong. Do not retry.
                    raise WeatherAPIError(
                        f"HTTP {response.status_code} from {url}: {_api_reason(response)}",
                        url, attempt + 1, response.status_code,
                    ) from None
                return response
        except requests.Timeout:
            last_problem = f"timed out after {timeout} s"
        except requests.ConnectionError as err:
            last_problem = f"connection failed ({type(err).__name__})"
        if attempt < attempts - 1:
            sleep(backoff * (2 ** attempt))

    raise WeatherAPIError(
        f"Giving up on {url} after {attempts} attempt(s): {last_problem}.", url, attempts, last_status
    )


def fetch_json(url: str, params: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    """Like :func:`request_with_retries` but returns the decoded JSON body."""
    response = request_with_retries(url, params, **kwargs)
    try:
        return response.json()
    except ValueError:
        raise WeatherAPIError(f"{url} did not return valid JSON.", url, 1, response.status_code) from None
