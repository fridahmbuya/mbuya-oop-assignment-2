"""Offline tests of the retry wrapper, using a fake session instead of the network."""
import pytest
import requests

from src.weather.api import get_forecast, get_forecast_met_no
from src.weather.http import (
    PLACEHOLDER_EMAIL,
    ConfigError,
    WeatherAPIError,
    build_user_agent,
    fetch_json,
    is_placeholder,
    request_with_retries,
)


class FakeResponse:
    """Just enough of requests.Response for the wrapper."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code, self._payload, self.text = status_code, payload, text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    """Returns (or raises) a scripted sequence of outcomes, one per call."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def no_sleep_recorder():
    waits = []
    return waits, waits.append


def test_success_first_time_makes_one_call_with_timeout():
    session = FakeSession(FakeResponse(200, {"ok": True}))
    assert fetch_json("https://example.org", {"a": 1}, session=session, timeout=3) == {"ok": True}
    assert len(session.calls) == 1 and session.calls[0]["timeout"] == 3


def test_retries_5xx_then_succeeds_with_exponential_backoff():
    waits, sleep = no_sleep_recorder()
    session = FakeSession(FakeResponse(503), FakeResponse(500), FakeResponse(200, {"ok": True}))
    assert fetch_json("https://example.org", session=session, backoff=0.5, sleep=sleep) == {"ok": True}
    assert len(session.calls) == 3
    assert waits == [0.5, 1.0]                      # 0.5 * 2**0, 0.5 * 2**1


def test_connection_errors_hit_the_retry_cap_and_raise_custom_error():
    waits, sleep = no_sleep_recorder()
    session = FakeSession(*[requests.ConnectionError("no network")] * 4)
    with pytest.raises(WeatherAPIError) as info:
        request_with_retries("https://example.org", session=session, max_retries=3, sleep=sleep)
    assert info.value.attempts == 4 and len(session.calls) == 4
    assert waits == [0.5, 1.0, 2.0]                 # no pointless wait after the last attempt
    assert "after 4 attempt" in str(info.value)


def test_timeouts_are_retried():
    session = FakeSession(requests.Timeout("slow"), FakeResponse(200, {"ok": 1}))
    assert fetch_json("https://example.org", session=session, sleep=lambda _: None) == {"ok": 1}


def test_4xx_is_not_retried_and_reports_the_api_reason():
    body = {"error": True, "reason": "Latitude must be in range of -90 to 90°. Given: 123.0."}
    session = FakeSession(FakeResponse(400, body))
    with pytest.raises(WeatherAPIError) as info:
        fetch_json("https://example.org", session=session, sleep=lambda _: None)
    assert len(session.calls) == 1 and info.value.status == 400
    assert "Latitude must be in range" in str(info.value)


def test_invalid_json_raises_custom_error():
    with pytest.raises(WeatherAPIError):
        fetch_json("https://example.org", session=FakeSession(FakeResponse(200, None, "<html>")))


def test_bad_arguments_rejected():
    with pytest.raises(ValueError):
        request_with_retries("https://example.org", timeout=0)
    with pytest.raises(ValueError):
        request_with_retries("https://example.org", max_retries=-1)


# --- identification -----------------------------------------------------------
def test_placeholder_detection_and_user_agent():
    assert is_placeholder(PLACEHOLDER_EMAIL) and is_placeholder("") and is_placeholder("not-an-email")
    assert not is_placeholder("student@university.ac.ug")
    assert "contact" not in build_user_agent(PLACEHOLDER_EMAIL)          # never invent contact details
    assert "student@university.ac.ug" in build_user_agent("student@university.ac.ug")


def test_met_norway_refuses_to_call_without_a_real_email():
    session = FakeSession()                                               # would fail if a call were made
    with pytest.raises(ConfigError):
        get_forecast_met_no(51.05, 13.74, PLACEHOLDER_EMAIL, session=session)
    assert session.calls == []


def test_met_norway_truncates_coordinates_and_identifies_itself():
    session = FakeSession(FakeResponse(200, {"properties": {"timeseries": []}}))
    get_forecast_met_no(51.050891234, 13.738329876, "student@university.ac.ug", session=session)
    call = session.calls[0]
    assert call["params"] == {"lat": 51.0509, "lon": 13.7383}
    assert "student@university.ac.ug" in call["headers"]["User-Agent"]


def test_get_forecast_validates_before_calling():
    session = FakeSession()
    with pytest.raises(ValueError):
        get_forecast(123.0, 13.7, session=session)
    with pytest.raises(ValueError):
        get_forecast(51.0, 13.7, days=0, session=session)
    assert session.calls == []


def test_get_forecast_sends_documented_parameters():
    session = FakeSession(FakeResponse(200, {"daily": {}}))
    get_forecast(51.05, 13.74, days=5, session=session)
    params = session.calls[0]["params"]
    assert params["timezone"] == "auto" and params["forecast_days"] == 5
    assert "temperature_2m_max" in params["daily"] and "wind_speed_10m_max" in params["daily"]
