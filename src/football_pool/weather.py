"""Optional kickoff weather for the Gameday page.

Open-Meteo needs no key and accepts several coordinates in one request. Weather
is context, never a scoring input: an unknown venue, a roof, a distant kickoff,
or a failed request simply produces no weather badge for that game.
"""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from .schedule import kickoff

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ATTRIBUTION_URL = "https://open-meteo.com/"
ATTRIBUTION_TEXT = "Weather by Open-Meteo"
FORECAST_HORIZON = timedelta(days=16)

# Stadium names are used instead of team codes because international and
# neutral-site games move. Coordinates only select the forecast grid point;
# they are not displayed as venue facts. New/renamed venues fail closed.
VENUES: dict[str, tuple[float, float]] = {
    "M&T Bank Stadium": (39.2780, -76.6227),
    "Gillette Stadium": (42.0909, -71.2643),
    "Highmark Stadium": (42.7738, -78.7868),
    "Bank of America Stadium": (35.2258, -80.8528),
    "Soldier Field": (41.8623, -87.6167),
    "Paycor Stadium": (39.0954, -84.5160),
    "Huntington Bank Field": (41.5061, -81.6995),
    "Empower Field at Mile High": (39.7439, -105.0201),
    "Lambeau Field": (44.5013, -88.0622),
    "EverBank Stadium": (30.3239, -81.6373),
    "GEHA Field at Arrowhead Stadium": (39.0489, -94.4839),
    "Wembley Stadium": (51.5560, -0.2796),
    "Tottenham Hotspur Stadium": (51.6043, -0.0665),
    "Estadio Banorte": (19.3029, -99.1505),
    "Hard Rock Stadium": (25.9580, -80.2389),
    "Nissan Stadium": (36.1665, -86.7713),
    "MetLife Stadium": (40.8135, -74.0745),
    "Lincoln Financial Field": (39.9008, -75.1675),
    "Acrisure Stadium": (40.4468, -80.0158),
    "Lumen Field": (47.5952, -122.3316),
    "Levi's Stadium": (37.4030, -121.9700),
    "Raymond James Stadium": (27.9759, -82.5033),
    "Northwest Stadium": (38.9076, -76.8645),
}

WEATHER_LABELS = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Cloudy",
    45: "Fog",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Rain showers",
    82: "Heavy showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorms",
    96: "Storms with hail",
    99: "Storms with hail",
}


@dataclass(frozen=True)
class KickoffWeather:
    temperature: int
    feels_like: int
    precipitation: int
    wind: int
    gust: int
    code: int
    label: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(values: list[Any], index: int, default: float = 0.0) -> float:
    try:
        value = values[index]
        return default if value is None else float(value)
    except (IndexError, TypeError, ValueError):
        return default


def _eligible_games(games: pd.DataFrame, instant: datetime) -> list[tuple[Any, datetime, tuple[float, float]]]:
    rows = []
    for row in games.itertuples():
        if bool(row.played) or str(getattr(row, "roof", "")).lower() not in {"outdoors", "open"}:
            continue
        venue = getattr(row, "stadium", None)
        if venue is None or pd.isna(venue) or str(venue) not in VENUES:
            continue
        when = kickoff(row.gameday, row.gametime)
        distance = when - instant
        if distance < timedelta(0) or distance > FORECAST_HORIZON:
            continue
        rows.append((row, when, VENUES[str(venue)]))
    return rows


def fetch_weather(
    games: pd.DataFrame,
    instant: datetime,
    *,
    offline: bool = False,
    client: Any = httpx,
) -> dict[str, KickoffWeather]:
    """Fetch one batched forecast and align its nearest hour to each kickoff."""
    if offline or games.empty or "roof" not in games or "stadium" not in games:
        return {}
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    instant = instant.astimezone(timezone.utc)
    eligible = _eligible_games(games, instant)
    if not eligible:
        return {}

    coordinates = list(dict.fromkeys(item[2] for item in eligible))
    params = {
        "latitude": ",".join(str(c[0]) for c in coordinates),
        "longitude": ",".join(str(c[1]) for c in coordinates),
        "hourly": (
            "temperature_2m,apparent_temperature,precipitation_probability,"
            "weather_code,wind_speed_10m,wind_gusts_10m"
        ),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "UTC",
        "forecast_days": 16,
    }
    try:
        response = client.get(FORECAST_URL, params=params, timeout=12.0)
        response.raise_for_status()
        payload = response.json()
        forecasts = payload if isinstance(payload, list) else [payload]
        by_coord = dict(zip(coordinates, forecasts))

        out: dict[str, KickoffWeather] = {}
        for row, when, coordinate in eligible:
            hourly = by_coord[coordinate]["hourly"]
            times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in hourly["time"]]
            i = min(range(len(times)), key=lambda j: abs(times[j] - when))
            code = int(round(_number(hourly.get("weather_code", []), i)))
            out[str(row.game_id)] = KickoffWeather(
                temperature=round(_number(hourly.get("temperature_2m", []), i)),
                feels_like=round(_number(hourly.get("apparent_temperature", []), i)),
                precipitation=round(_number(hourly.get("precipitation_probability", []), i)),
                wind=round(_number(hourly.get("wind_speed_10m", []), i)),
                gust=round(_number(hourly.get("wind_gusts_10m", []), i)),
                code=code,
                label=WEATHER_LABELS.get(code, "Mixed conditions"),
            )
        return out
    except Exception as exc:  # noqa: BLE001 - weather can never stop a publish
        warnings.warn(f"kickoff weather unavailable: {exc}", RuntimeWarning, stacklevel=2)
        return {}
