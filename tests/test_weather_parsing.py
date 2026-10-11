"""Offline checks on the weather parsing functions, using the saved sample JSON files."""
import json
from pathlib import Path

import pandas as pd
import pytest

from src.weather.api import build_geocoding_url, choose_location, validate_coordinates
from src.weather.http import LocationNotFoundError
from src.weather.parsing import (
    COL_RAIN,
    COL_TMAX,
    COL_TMIN,
    COL_WEATHER,
    COL_WIND,
    Location,
    compare_sources,
    decode_weather_code,
    parse_geocoding,
    parse_met_no_daily,
    parse_met_no_hourly,
    parse_open_meteo_daily,
    summarise_forecast,
)

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def load(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


# --- geocoding ---------------------------------------------------------------
def test_parse_geocoding_returns_candidates_best_first():
    places = parse_geocoding(load("geocoding_dresden.json"))
    assert len(places) == 3
    first = places[0]
    assert (first.name, first.country, first.admin1) == ("Dresden", "Germany", "Saxony")
    assert first.latitude == pytest.approx(51.05089) and first.longitude == pytest.approx(13.73832)
    assert first.timezone == "Europe/Berlin"
    assert {p.country for p in places} == {"Germany", "United States"}    # the name is ambiguous


def test_parse_geocoding_handles_missing_results_key():
    assert parse_geocoding(load("geocoding_no_results.json")) == []       # no KeyError
    assert parse_geocoding({"results": None}) == []
    assert parse_geocoding({"results": [{"name": "No coordinates"}]}) == []


def test_choose_location_zero_one_many():
    places = parse_geocoding(load("geocoding_dresden.json"))
    with pytest.raises(LocationNotFoundError):
        choose_location([], query="Qwxzzy")
    assert choose_location(places[:1]) == places[0]
    messages = []
    picked = choose_location(places, choice=2, query="Dresden", print_func=messages.append)
    assert picked.admin1 == "Tennessee"
    assert sum("Dresden" in m for m in messages) >= 3                     # all candidates were listed


def test_choose_location_interactive_reprompts():
    places = parse_geocoding(load("geocoding_dresden.json"))
    answers = iter(["", "nine", "7", "3"])
    picked = choose_location(places, query="Dresden", input_func=lambda _: next(answers), print_func=lambda _: None)
    assert picked.admin1 == "Ohio"


def test_geocoding_url_is_encoded():
    url = build_geocoding_url("São Paulo & more", count=2)
    assert "name=S%C3%A3o+Paulo+%26+more" in url and "count=2" in url


# --- Open-Meteo forecast ---------------------------------------------------------
def test_parse_forecast_shape_columns_and_units():
    df = parse_open_meteo_daily(load("forecast_dresden.json"))
    assert df.shape == (7, 6)
    assert list(df.columns[:5]) == [COL_WEATHER, COL_TMAX, COL_TMIN, COL_RAIN, COL_WIND]
    assert isinstance(df.index, pd.DatetimeIndex) and str(df.index[0].date()) == "2026-10-07"
    assert df.attrs["timezone"] == "Europe/Berlin"
    assert df.attrs["units"]["wind_speed_10m_max"] == "km/h"
    assert (df[COL_TMAX] >= df[COL_TMIN]).all()


def test_parse_forecast_values_match_the_json():
    raw = load("forecast_dresden.json")
    df = parse_open_meteo_daily(raw)
    assert df[COL_TMAX].tolist() == raw["daily"]["temperature_2m_max"]
    assert df[COL_RAIN].sum() == pytest.approx(sum(raw["daily"]["precipitation_sum"]))
    assert df[COL_WEATHER].iloc[1] == "Slight rain"                       # WMO code 61


def test_weather_code_decoding():
    assert decode_weather_code(0) == "Clear sky"
    assert decode_weather_code(95) == "Thunderstorm"
    assert decode_weather_code(1234) == "Unknown (code 1234)"
    assert decode_weather_code(None) == "No data"


def test_parse_forecast_rejects_incomplete_payloads():
    with pytest.raises(ValueError):
        parse_open_meteo_daily(load("forecast_error_latitude.json"))       # an error body, no 'daily'
    broken = load("forecast_dresden.json")
    del broken["daily"]["precipitation_sum"]
    with pytest.raises(ValueError):
        parse_open_meteo_daily(broken)
    ragged = load("forecast_dresden.json")
    ragged["daily"]["temperature_2m_min"].pop()
    with pytest.raises(ValueError):
        parse_open_meteo_daily(ragged)


def test_summary_mentions_key_facts():
    text = summarise_forecast(parse_open_meteo_daily(load("forecast_dresden.json")), "Dresden")
    assert "Dresden" in text and "16.4 °C" in text and "5.6 °C" in text and "16.8 mm" in text


# --- MET Norway --------------------------------------------------------------------
def test_met_no_times_are_converted_to_local_time():
    hourly = parse_met_no_hourly(load("met_no_dresden.json"), "Europe/Berlin")
    assert str(hourly.index.tz) == "Europe/Berlin"
    assert hourly.index[0].hour == 12                                     # 10:00 UTC is 12:00 in Berlin (CEST)


def test_met_no_wind_is_converted_to_kmh():
    raw = load("met_no_dresden.json")
    first_ms = raw["properties"]["timeseries"][0]["data"]["instant"]["details"]["wind_speed"]
    hourly = parse_met_no_hourly(raw, "Europe/Berlin")
    assert hourly["wind_kmh"].iloc[0] == pytest.approx(first_ms * 3.6)


def test_met_no_daily_has_same_columns_and_sane_values():
    daily = parse_met_no_daily(load("met_no_dresden.json"), "Europe/Berlin")
    assert {COL_TMAX, COL_TMIN, COL_RAIN, COL_WIND, "Steps"} <= set(daily.columns)
    assert (daily[COL_TMAX] >= daily[COL_TMIN]).all()
    assert daily.loc["2026-10-08", "Steps"] == 24                         # a full hourly day


def test_met_no_rejects_wrong_payload():
    with pytest.raises(ValueError):
        parse_met_no_hourly({"daily": {}})


def test_compare_sources_uses_only_common_dates():
    a = parse_open_meteo_daily(load("forecast_dresden.json"))
    b = parse_met_no_daily(load("met_no_dresden.json"), "Europe/Berlin")
    table = compare_sources(a, b)
    assert len(table) == 7
    assert f"{COL_TMAX} diff" in table.columns


# --- input validation -----------------------------------------------------------------
@pytest.mark.parametrize("lat, lon", [(123.0, 13.7), (-91, 0), (0, 181), ("51", 13), (True, 1)])
def test_invalid_coordinates_rejected(lat, lon):
    with pytest.raises(ValueError):
        validate_coordinates(lat, lon)


def test_location_label():
    assert Location("Jinja", 0.44, 33.2, country="Uganda", admin1="Eastern Region").label == "Jinja, Eastern Region, Uganda"
