"""Test helpers shared across modules."""

from __future__ import annotations

import pandas as pd


def mkgames(rows: list[dict]) -> pd.DataFrame:
    """Build a games frame shaped like ``nflverse.parse_games`` output.

    Each row takes ``home``, ``away``, and either ``hs``/``as_`` scores for a
    completed game, or neither for one still to be played. Optional ``type``
    (default ``REG``), ``week`` (default 1), ``gameday``, ``gametime``,
    ``location`` and ``overtime``.

    The last four are rarely interesting to a scoring test, but they are part of
    the real frame — the schedule page reads all of them — so they are always
    present rather than only when a caller thinks to ask.
    """
    out = []
    for i, r in enumerate(rows):
        hs, as_ = r.get("hs"), r.get("as_")
        played = hs is not None and as_ is not None
        result = (hs - as_) if played else None
        out.append(
            {
                "game_id": f"g{i}",
                "season": 2026,
                "game_type": r.get("type", "REG"),
                "week": r.get("week", 1),
                "gameday": r.get("gameday", "2026-09-13"),
                "gametime": r.get("gametime", "13:00"),
                "home_team": r["home"],
                "away_team": r["away"],
                "home_score": hs,
                "away_score": as_,
                "result": result,
                "overtime": r.get("overtime", 0),
                "location": r.get("location", "Home"),
                "played": played,
                "is_tie": played and result == 0,
                "home_won": played and result > 0,
                "away_won": played and result < 0,
            }
        )
    return pd.DataFrame(out)
