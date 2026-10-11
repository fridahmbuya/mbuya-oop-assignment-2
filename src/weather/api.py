"""Calls to the three approved web APIs. The HTTP requests are made directly (no wrapper
library): once with the standard library's urllib (Part A) and otherwise with requests.

    Open-Meteo Geocoding   https://geocoding-api.open-meteo.com/v1/search
    Open-Meteo Forecast    https://api.open-meteo.com/v1/forecast
    MET Norway             https://api.met.no/weatherapi/locationforecast/2.0/compact
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence

from src.weather.http import (
    LocationNotFoundError,
    WeatherAPIError,
    build_user_agent,
    fetch_json,
)
from src.weather.parsing import Location, parse_geocoding

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MET_NO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"

DAILY_VARIABLES = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
)
MAX_FORECAST_DAYS = 16


# ---------------------------------------------------------------------------
# Part A: the same geocoding call with the standard library only
# ---------------------------------------------------------------------------
def build_geocoding_url(name: str, count: int = 5) -> str:
    """Geocoding URL with a safely encoded query string (``urllib.parse.urlencode``)."""
    query = urllib.parse.urlencode({"name": name, "count": count, "language": "en", "format": "json"})
    return f"{GEOCODING_URL}?{query}"


def geocode_urllib(name: str, count: int = 5, user_agent: str = "", timeout: float = 10.0) -> Dict[str, Any]:
    """Geocode ``name`` using only urllib.request, urllib.parse and json. Returns raw JSON."""
    request = urllib.request.Request(build_geocoding_url(name, count), headers={"User-Agent": user_agent or "python-urllib"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:   # noqa: S310 (fixed https URL)
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except urllib.error.HTTPError as err:          # the server answered with 4xx/5xx
        raise WeatherAPIError(f"HTTP {err.code} from geocoding API: {err.reason}", GEOCODING_URL, 1, err.code) from None
    except (urllib.error.URLError, TimeoutError) as err:   # no connection, DNS failure, timeout
        raise WeatherAPIError(f"Could not reach the geocoding API: {err}", GEOCODING_URL, 1) from None


# ---------------------------------------------------------------------------
# Part B: geocode and forecast
# ---------------------------------------------------------------------------
def geocode(name: str, count: int = 5, email: str = "", **request_options: Any) -> List[Location]:
    """Find candidate locations for a place name.

    Returns a list, best match first. The list is EMPTY when nothing matches (the API then
    sends no ``results`` key). Use :func:`choose_location` to pick one.

    Raises:
        ValueError: if the name is shorter than 2 characters (the API needs at least 2).
        WeatherAPIError: if the request fails.
    """
    name = (name or "").strip()
    if len(name) < 2:
        raise ValueError("Location name must have at least 2 characters.")
    if not 1 <= count <= 100:
        raise ValueError("count must be between 1 and 100.")
    payload = fetch_json(
        GEOCODING_URL,
        {"name": name, "count": count, "language": "en", "format": "json"},
        headers={"User-Agent": build_user_agent(email)},
        **request_options,
    )
    return parse_geocoding(payload)


def choose_location(
    candidates: Sequence[Location],
    choice: Optional[int] = None,
    query: str = "",
    input_func: Callable[[str], str] = input,
    print_func: Callable[[str], None] = print,
) -> Location:
    """Pick one location from the geocoder's candidates.

    * no candidates  -> :class:`LocationNotFoundError`
    * one candidate  -> returned directly
    * several        -> the candidates are listed; ``choice`` (1-based, from the config cell)
      selects one, or, if ``choice`` is None, the user is asked to type a number.
    """
    if not candidates:
        raise LocationNotFoundError(f"No place called '{query}' was found. Check the spelling.")
    if len(candidates) == 1:
        return candidates[0]
    print_func(f"'{query}' is ambiguous. {len(candidates)} candidates:")
    for i, loc in enumerate(candidates, start=1):
        print_func(f"  {i}. {loc}")
    if choice is None:
        for _ in range(5):
            answer = input_func(f"Pick a number 1-{len(candidates)}: ").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(candidates):
                choice = int(answer)
                break
            print_func("  Not a valid choice, try again.")
        else:
            raise ValueError("No valid choice was made.")
    if not 1 <= choice <= len(candidates):
        raise ValueError(f"choice must be between 1 and {len(candidates)}, got {choice}.")
    print_func(f"-> using {choice}. {candidates[choice - 1].label}")
    return candidates[choice - 1]


def validate_coordinates(lat: float, lon: float) -> None:
    """Reject impossible coordinates before spending a network request on them."""
    if isinstance(lat, bool) or isinstance(lon, bool) or not all(isinstance(v, (int, float)) for v in (lat, lon)):
        raise ValueError("Latitude and longitude must be numbers.")
    if not -90 <= lat <= 90:
        raise ValueError(f"Latitude must be between -90 and 90, got {lat}.")
    if not -180 <= lon <= 180:
        raise ValueError(f"Longitude must be between -180 and 180, got {lon}.")


def get_forecast(
    lat: float, lon: float, days: int = 7, email: str = "", validate: bool = True, **request_options: Any
) -> Dict[str, Any]:
    """Daily forecast from Open-Meteo as raw JSON.

    Requests weather code, max/min temperature, precipitation sum and max wind speed, with
    ``timezone=auto`` so each "day" is a local calendar day at the location.

    Args:
        lat, lon: Coordinates in decimal degrees.
        days: Number of forecast days, 1 to 16.
        email: Contact email for the User-Agent (optional for Open-Meteo).
        validate: Check the inputs locally first. Set False only to demonstrate the API's
            own error message.
    """
    if validate:
        validate_coordinates(lat, lon)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_FORECAST_DAYS:
            raise ValueError(f"days must be a whole number from 1 to {MAX_FORECAST_DAYS}.")
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(DAILY_VARIABLES),
        "timezone": "auto",
        "forecast_days": days,
    }
    return fetch_json(FORECAST_URL, params, headers={"User-Agent": build_user_agent(email)}, **request_options)


# ---------------------------------------------------------------------------
# Part C: second source
# ---------------------------------------------------------------------------
def get_forecast_met_no(lat: float, lon: float, email: str, **request_options: Any) -> Dict[str, Any]:
    """Forecast from MET Norway Locationforecast 2.0 (compact) as raw JSON.

    MET Norway's terms require (a) a User-Agent that identifies the application with real
    contact details and (b) coordinates with at most 4 decimals. Both are enforced here;
    a placeholder email raises :class:`~src.weather.http.ConfigError` before any request.
    """
    validate_coordinates(lat, lon)
    headers = {"User-Agent": build_user_agent(email, require_contact=True)}
    params = {"lat": round(lat, 4), "lon": round(lon, 4)}
    return fetch_json(MET_NO_URL, params, headers=headers, **request_options)
