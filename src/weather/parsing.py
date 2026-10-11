"""Pure parsing functions: JSON (already decoded to dicts) in, tidy Python objects out.

Nothing here touches the network, so every function can be tested offline with the saved
sample JSON files in ``samples/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd

# WMO weather interpretation codes, as documented by Open-Meteo
# (https://open-meteo.com/en/docs, section "WMO Weather interpretation codes").
WMO_CODES: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snowfall", 73: "Moderate snowfall", 75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

# Column names used everywhere after parsing: clear names WITH units.
COL_TMAX = "Max temp (°C)"
COL_TMIN = "Min temp (°C)"
COL_RAIN = "Precipitation (mm)"
COL_WIND = "Max wind (km/h)"
COL_WEATHER = "Weather"
COL_CODE = "WMO code"


def decode_weather_code(code: Optional[int]) -> str:
    """Turn a WMO weather code into words; unknown or missing codes are labelled, not hidden."""
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return "No data"
    return WMO_CODES.get(int(code), f"Unknown (code {int(code)})")


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Location:
    """One candidate place returned by the geocoder."""

    name: str
    latitude: float
    longitude: float
    country: str = ""
    admin1: str = ""          # state / region, used to tell same-named places apart
    timezone: str = "UTC"
    population: Optional[int] = None
    elevation: Optional[float] = None

    @property
    def label(self) -> str:
        """Readable one-line description, e.g. 'Dresden, Saxony, Germany'."""
        return ", ".join(part for part in (self.name, self.admin1, self.country) if part)

    def __str__(self) -> str:
        pop = f", pop. {self.population:,}" if self.population else ""
        return f"{self.label} ({self.latitude:.4f}, {self.longitude:.4f}{pop})"


def parse_geocoding(payload: Mapping[str, Any]) -> List[Location]:
    """Convert an Open-Meteo geocoding response into a list of Locations.

    When nothing matches, the API omits the ``results`` key altogether, so we use
    ``.get("results")`` and return an empty list instead of raising ``KeyError``.
    Entries without coordinates are skipped.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("Geocoding payload must be a JSON object (dict).")
    locations = []
    for item in payload.get("results") or []:
        if "latitude" not in item or "longitude" not in item:
            continue
        locations.append(
            Location(
                name=str(item.get("name", "")),
                latitude=float(item["latitude"]),
                longitude=float(item["longitude"]),
                country=str(item.get("country", "")),
                admin1=str(item.get("admin1", "")),
                timezone=str(item.get("timezone", "UTC")),
                population=item.get("population"),
                elevation=item.get("elevation"),
            )
        )
    return locations


# ---------------------------------------------------------------------------
# Open-Meteo daily forecast
# ---------------------------------------------------------------------------
_OPEN_METEO_COLUMNS = {
    "temperature_2m_max": COL_TMAX,
    "temperature_2m_min": COL_TMIN,
    "precipitation_sum": COL_RAIN,
    "wind_speed_10m_max": COL_WIND,
}


def parse_open_meteo_daily(payload: Mapping[str, Any]) -> pd.DataFrame:
    """Convert an Open-Meteo ``daily`` block into a DataFrame indexed by date.

    Columns: Weather (text), Max temp (°C), Min temp (°C), Precipitation (mm),
    Max wind (km/h), WMO code. The API's own unit strings are kept in ``df.attrs["units"]``
    and the timezone in ``df.attrs["timezone"]``.

    Raises:
        ValueError: if the ``daily`` block or a required variable is missing, or the
            arrays have different lengths.
    """
    daily = payload.get("daily") if isinstance(payload, Mapping) else None
    if not daily or "time" not in daily:
        raise ValueError("Response has no 'daily' block with 'time'; was daily=... requested?")
    missing = [key for key in _OPEN_METEO_COLUMNS if key not in daily]
    if missing:
        raise ValueError(f"Daily block is missing: {', '.join(missing)}.")
    n = len(daily["time"])
    if any(len(daily[key]) != n for key in _OPEN_METEO_COLUMNS):
        raise ValueError("Daily arrays have inconsistent lengths.")

    df = pd.DataFrame({new: daily[old] for old, new in _OPEN_METEO_COLUMNS.items()})
    codes = daily.get("weather_code", [None] * n)
    df.insert(0, COL_WEATHER, [decode_weather_code(c) for c in codes])
    df[COL_CODE] = codes
    df.index = pd.to_datetime(daily["time"]).rename("Date")
    df.attrs["units"] = dict(payload.get("daily_units", {}))
    df.attrs["timezone"] = payload.get("timezone", "UTC")
    df.attrs["source"] = "Open-Meteo"
    return df


# ---------------------------------------------------------------------------
# MET Norway Locationforecast 2.0 (second source)
# ---------------------------------------------------------------------------
MS_TO_KMH = 3.6


def parse_met_no_hourly(payload: Mapping[str, Any], timezone: str = "UTC") -> pd.DataFrame:
    """Flatten MET Norway's ``timeseries`` into one row per time step, in local time.

    MET Norway timestamps are UTC, so they are converted to ``timezone`` first; otherwise
    "today's maximum" would be computed over the wrong 24 hours. Wind is converted from
    m/s to km/h to match Open-Meteo. Precipitation is taken from ``next_1_hours`` where
    present (near term) and from ``next_6_hours`` further out, never both for one step.
    """
    try:
        series = payload["properties"]["timeseries"]
    except (KeyError, TypeError):
        raise ValueError("Response has no properties.timeseries; is this a Locationforecast reply?") from None
    rows = []
    for step in series:
        data = step.get("data", {})
        details = data.get("instant", {}).get("details", {})
        block = data.get("next_1_hours") or data.get("next_6_hours") or {}
        rows.append(
            {
                "time": step["time"],
                "temp_c": details.get("air_temperature"),
                "wind_kmh": None if details.get("wind_speed") is None else details["wind_speed"] * MS_TO_KMH,
                "precip_mm": block.get("details", {}).get("precipitation_amount"),
                "symbol": block.get("summary", {}).get("symbol_code"),
            }
        )
    df = pd.DataFrame(rows, columns=["time", "temp_c", "wind_kmh", "precip_mm", "symbol"])
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(timezone)
    return df.set_index("time")


def parse_met_no_daily(payload: Mapping[str, Any], timezone: str = "UTC") -> pd.DataFrame:
    """Aggregate MET Norway data to one row per local calendar day.

    Same column names as :func:`parse_open_meteo_daily` so the two sources can be compared,
    plus ``Steps`` (how many time steps the day is built from: 24 means a full hourly day).
    """
    hourly = parse_met_no_hourly(payload, timezone)
    if hourly.empty:
        raise ValueError("MET Norway response contains no time steps.")
    by_day = hourly.groupby(hourly.index.date)
    daily = pd.DataFrame(
        {
            COL_TMAX: by_day["temp_c"].max(),
            COL_TMIN: by_day["temp_c"].min(),
            COL_RAIN: by_day["precip_mm"].sum(min_count=1),
            COL_WIND: by_day["wind_kmh"].max(),
            "Steps": by_day["temp_c"].count(),
        }
    ).round(1)
    daily.index = pd.to_datetime(daily.index).rename("Date")
    daily.attrs["timezone"] = timezone
    daily.attrs["source"] = "MET Norway"
    return daily


# ---------------------------------------------------------------------------
# Words and comparison
# ---------------------------------------------------------------------------
def summarise_forecast(df: pd.DataFrame, place: str) -> str:
    """A short plain-language summary of a daily forecast table."""
    if df.empty:
        return f"No forecast data for {place}."
    hottest, coldest = df[COL_TMAX].idxmax(), df[COL_TMIN].idxmin()
    wet = df[df[COL_RAIN] > 0]
    windiest = df[COL_WIND].idxmax()
    fmt = "%a %d %b"
    lines = [
        f"{place}: {len(df)}-day forecast, {df.index[0]:{fmt}} to {df.index[-1]:{fmt}}.",
        f"Warmest day: {hottest:{fmt}} ({df.loc[hottest, COL_TMAX]:.1f} °C). "
        f"Coldest night: {coldest:{fmt}} ({df.loc[coldest, COL_TMIN]:.1f} °C).",
    ]
    if wet.empty:
        lines.append("No precipitation is expected.")
    else:
        wettest = df[COL_RAIN].idxmax()
        lines.append(
            f"Precipitation on {len(wet)} of {len(df)} days, {df[COL_RAIN].sum():.1f} mm in total; "
            f"wettest: {wettest:{fmt}} ({df.loc[wettest, COL_RAIN]:.1f} mm)."
        )
    lines.append(f"Strongest wind: {df.loc[windiest, COL_WIND]:.1f} km/h on {windiest:{fmt}}.")
    return "\n".join(lines)


def compare_sources(first: pd.DataFrame, second: pd.DataFrame) -> pd.DataFrame:
    """Day-by-day differences (first minus second) for the days both sources cover."""
    columns = [COL_TMAX, COL_TMIN, COL_RAIN, COL_WIND]
    common = first.index.intersection(second.index)
    if common.empty:
        raise ValueError("The two forecasts have no dates in common.")
    a_name = first.attrs.get("source", "A")
    b_name = second.attrs.get("source", "B")
    out = pd.DataFrame(index=common)
    for col in columns:
        out[f"{col} {a_name}"] = first.loc[common, col]
        out[f"{col} {b_name}"] = second.loc[common, col]
        out[f"{col} diff"] = (first.loc[common, col] - second.loc[common, col]).round(1)
    return out
