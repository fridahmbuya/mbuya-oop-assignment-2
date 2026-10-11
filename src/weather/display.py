"""Displaying a forecast: a formatted table, a chart, and the data-flow diagram."""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch

from src.weather.parsing import COL_RAIN, COL_TMAX, COL_TMIN, COL_WEATHER, COL_WIND

ATTRIBUTION = {
    "Open-Meteo": "Weather data by Open-Meteo.com (CC BY 4.0)",
    "MET Norway": "Data from MET Norway (CC BY 4.0 / NLOD)",
}


def format_table(df: pd.DataFrame) -> str:
    """Fixed-width text table with weekday names and one decimal place."""
    shown = df[[COL_WEATHER, COL_TMAX, COL_TMIN, COL_RAIN, COL_WIND]].copy()
    shown.index = [d.strftime("%a %d %b") for d in df.index]
    shown.index.name = "Date"
    return shown.to_string(float_format=lambda v: f"{v:.1f}")


def plot_forecast(df: pd.DataFrame, place: str, source: Optional[str] = None) -> Figure:
    """Temperature range (floating bars from min to max) with precipitation on a second axis."""
    source = source or df.attrs.get("source", "Open-Meteo")
    labels = [d.strftime("%a\n%d %b") for d in df.index]
    x = range(len(df))

    fig, ax = plt.subplots(figsize=(11, 5.2))
    rain_ax = ax.twinx()
    rain_ax.bar(x, df[COL_RAIN], width=0.75, color="#9ecae1", alpha=0.6, label="Precipitation (mm)", zorder=1)
    rain_ax.set_ylabel("Precipitation (mm per day)")
    rain_ax.set_ylim(0, max(5.0, float(df[COL_RAIN].max()) * 2.2))

    ax.bar(x, df[COL_TMAX] - df[COL_TMIN], bottom=df[COL_TMIN], width=0.35, color="#f28e2b",
           label="Temperature range (min to max)", zorder=3)
    for i, (low, high) in enumerate(zip(df[COL_TMIN], df[COL_TMAX])):
        ax.text(i, high + 0.3, f"{high:.0f}°", ha="center", va="bottom", fontsize=9)
        ax.text(i, low - 0.3, f"{low:.0f}°", ha="center", va="top", fontsize=9)
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("Temperature (°C)")
    ax.set_xlabel("Date (local time at the location)")
    span = float(df[COL_TMAX].max() - df[COL_TMIN].min()) or 1.0
    ax.set_ylim(float(df[COL_TMIN].min()) - 0.25 * span - 1, float(df[COL_TMAX].max()) + 0.25 * span + 1)
    ax.set_zorder(rain_ax.get_zorder() + 1)
    ax.patch.set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    ax.set_title(f"{place}: daily temperature range and precipitation")

    handles = ax.get_legend_handles_labels()[0] + rain_ax.get_legend_handles_labels()[0]
    ax.legend(handles, [h.get_label() for h in handles], loc="upper left", fontsize=9)
    fig.text(0.99, 0.01, ATTRIBUTION.get(source, source), ha="right", va="bottom", fontsize=8, color="grey")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def draw_data_flow() -> Figure:
    """The data-flow diagram for the report: from user input to displayed forecast."""
    fig, ax = plt.subplots(figsize=(13, 5.4))
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 5.4)
    ax.axis("off")

    def box(x: float, y: float, text: str, colour: str, w: float = 2.1, h: float = 0.9) -> None:
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05", fc=colour, ec="#333333"))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=9)

    def arrow(x1: float, y1: float, x2: float, y2: float, text: str = "", both: bool = False) -> None:
        style = "<->" if both else "->"
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle=style, color="#333333"))
        if text:
            ax.text((x1 + x2) / 2 + 0.08, (y1 + y2) / 2, text, ha="left", va="center", fontsize=8, color="#444444")

    mine, theirs, shared = "#dbeafe", "#fde2c4", "#e2f0d9"
    # Row 1: our functions, left to right
    box(0.1, 3.8, "1. Config cell\nplace name + email", mine)
    box(2.9, 3.8, "2. geocode(name)", mine)
    box(5.7, 3.8, "choose_location()\none latitude / longitude", mine)
    box(8.5, 3.8, "3. get_forecast(lat, lon, days)", mine, w=2.4)
    box(11.2, 3.8, "4. parse JSON\nto DataFrame", mine, w=1.7)
    for x1, x2 in [(2.2, 2.9), (5.0, 5.7), (7.8, 8.5), (10.9, 11.2)]:
        arrow(x1, 4.25, x2, 4.25)
    # Row 2: the wrapper every request passes through
    box(2.9, 2.2, "request_with_retries():   timeout   ·   raise_for_status()   ·   retries with backoff   ·   WeatherAPIError",
        shared, w=8.0, h=0.7)
    arrow(3.95, 3.8, 3.95, 2.95, both=True)
    arrow(9.7, 3.8, 9.7, 2.95, both=True)
    # Row 3: third-party services and the output
    box(2.9, 0.6, "Open-Meteo\nGeocoding API", theirs)
    box(8.5, 0.6, "Open-Meteo Forecast API\nMET Norway (second source)", theirs, w=2.4)
    box(11.2, 0.6, "5. Table, chart,\ntext summary", shared, w=1.7)
    arrow(3.95, 2.2, 3.95, 1.55, "HTTPS GET / JSON", both=True)
    arrow(9.7, 2.2, 9.7, 1.55, "HTTPS GET / JSON", both=True)
    arrow(12.05, 3.8, 12.05, 1.55)
    ax.text(0.1, 5.05, "Data flow: from user input to displayed forecast", fontsize=11, weight="bold")
    ax.text(0.1, 0.1, "blue = our functions      green = shared wrapper and output      "
            "orange = third-party services (the only point where location data leaves the machine)",
            fontsize=8, color="#444444")
    return fig
