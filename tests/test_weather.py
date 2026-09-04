from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from football_pool.weather import FORECAST_URL, fetch_weather


def game(**overrides):
    row = {
        "game_id": "2026_01_DAL_SEA",
        "gameday": "2026-09-10",
        "gametime": "20:20",
        "played": False,
        "roof": "outdoors",
        "stadium": "Lumen Field",
    }
    row.update(overrides)
    return row


class Response:
    def __init__(self, payload, *, broken=False):
        self.payload = payload
        self.broken = broken

    def raise_for_status(self):
        if self.broken:
            raise RuntimeError("weather is down")

    def json(self):
        return self.payload


class Client:
    def __init__(self, payload, *, broken=False):
        self.response = Response(payload, broken=broken)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def hourly(temp=61.2, code=61):
    return {
        "hourly": {
            "time": ["2026-09-10T23:00", "2026-09-11T00:00", "2026-09-11T01:00"],
            "temperature_2m": [70, temp, 59],
            "apparent_temperature": [70, 58.7, 56],
            "precipitation_probability": [5, 72, 80],
            "weather_code": [0, code, 63],
            "wind_speed_10m": [2, 11.4, 13],
            "wind_gusts_10m": [5, 22.6, 25],
        }
    }


NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def test_fetches_the_nearest_kickoff_hour_in_one_keyless_request():
    client = Client(hourly())
    result = fetch_weather(pd.DataFrame([game()]), NOW, client=client)

    assert len(client.calls) == 1
    url, options = client.calls[0]
    assert url == FORECAST_URL
    assert options["params"]["temperature_unit"] == "fahrenheit"
    assert options["params"]["wind_speed_unit"] == "mph"
    weather = result["2026_01_DAL_SEA"]
    assert weather.temperature == 61
    assert weather.feels_like == 59
    assert weather.precipitation == 72
    assert weather.wind == 11 and weather.gust == 23
    assert weather.label == "Light rain"
    assert weather.to_dict()["code"] == 61


def test_batches_distinct_venues_and_reuses_one_forecast_per_coordinate():
    games = pd.DataFrame(
        [
            game(game_id="one"),
            game(game_id="two", gametime="21:00"),
            game(game_id="three", stadium="Gillette Stadium"),
        ]
    )
    client = Client([hourly(60), hourly(40, 71)])
    result = fetch_weather(games, NOW, client=client)

    assert set(result) == {"one", "two", "three"}
    params = client.calls[0][1]["params"]
    assert params["latitude"].count(",") == 1
    # Same venue reuses the same hourly forecast object, then each kickoff
    # independently selects its nearest hour.
    assert result["one"].temperature == 60
    assert result["two"].temperature == 59
    assert result["three"].label == "Light snow"


@pytest.mark.parametrize(
    "row",
    [
        game(played=True),
        game(roof="dome"),
        game(stadium="A future mystery stadium"),
        game(gameday="2026-12-01"),
        game(gameday="2026-08-01"),
    ],
)
def test_ineligible_games_never_trigger_a_request(row):
    client = Client(hourly())
    assert fetch_weather(pd.DataFrame([row]), NOW, client=client) == {}
    assert client.calls == []


def test_offline_and_old_snapshots_need_no_weather_schema():
    client = Client(hourly())
    assert fetch_weather(pd.DataFrame([game()]), NOW, offline=True, client=client) == {}
    assert fetch_weather(pd.DataFrame([{"game_id": "old"}]), NOW, client=client) == {}
    assert fetch_weather(pd.DataFrame(), NOW, client=client) == {}
    assert client.calls == []


def test_a_failed_or_malformed_forecast_never_stops_the_build():
    frame = pd.DataFrame([game()])
    with pytest.warns(RuntimeWarning, match="kickoff weather unavailable"):
        assert fetch_weather(frame, NOW, client=Client({}, broken=True)) == {}
    with pytest.warns(RuntimeWarning, match="kickoff weather unavailable"):
        assert fetch_weather(frame, NOW, client=Client({"not_hourly": True})) == {}
