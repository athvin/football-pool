"""Plain-English definitions for the pool's private vocabulary.

Every page on this site is full of words that mean something specific here and
something vaguer everywhere else. "On the table" is not "points available",
"locked in" is not "guaranteed to you", and "expected $" is emphatically not
what anybody is going to be paid. A reader who guesses at those is reading a
different scoreboard from the one that was built.

The definitions live here, in one place, and the templates reference them by
key — so a term cannot be explained one way on the schedule page and another
way on the forecast. They are built from a ``Season`` rather than written as
fixed prose because the numbers that make them concrete are configurable: how
many places pay, what the entry costs, how big the pot is. A definition that
says "the top three" when the rules file says two is worse than no definition.
"""

from __future__ import annotations

from dataclasses import dataclass

from .season import Season


@dataclass(frozen=True)
class Term:
    """One entry: the words as they appear on the page, and what they mean."""

    term: str
    definition: str


def _places(season: Season) -> str:
    """"first and second" / "the top three" — however many places pay."""
    n = len(season.payout_split)
    if n == 1:
        return "first place"
    if n == 2:
        return "first or second"
    return f"the top {n}"


def terms(season: Season) -> dict[str, Term]:
    """The whole glossary, with this season's actual numbers written into it."""
    fee = f"${season.entry_fee:,.0f}"
    pot = f"${season.pot:,.0f}"
    paying = _places(season)

    return {
        "lf": Term(
            "Leveling factor",
            "A team's handicap, set from last year's record. A regular-season "
            "win pays the winning team's own leveling factor — so a win by a "
            "bad team is worth more to you than a win by a good one, and the "
            "loser's factor never enters into it.",
        ),
        "banked": Term(
            "Banked",
            "Points already scored, from games that have finished. Nothing "
            "here is projected, and nothing here can be taken away.",
        ),
        "team_points": Term(
            "Points generated",
            "Everything this team has scored for each entry holding it: "
            "leveling-factor points from wins, a division or wild-card berth "
            "bonus, and any playoff-win points already earned.",
        ),
        "floor": Term(
            "Floor",
            "The lowest this entry can still finish on: everything banked, "
            "plus anything left that they cannot avoid scoring.",
        ),
        "ceiling": Term(
            "Ceiling",
            "The highest this entry could still finish on — every remaining "
            "game won by the team you want, and the best possible January. It "
            "is a limit, not a forecast; nobody finishes on their ceiling.",
        ),
        "upside": Term(
            "Still on the table",
            "Ceiling minus floor: how much of this entry's finish is still "
            "genuinely undecided.",
        ),
        "on_the_table": Term(
            "On the table",
            "The most the whole pool could bank in this week. Only sides "
            "somebody actually holds are counted, so a game nobody in the pool "
            "is on adds nothing — it cannot pay anyone.",
        ),
        "locked_in": Term(
            "Locked in",
            "Points the field cannot avoid banking this week. When one entry "
            "holds both sides of a game, a team they own has to win it, so "
            "those points are already spoken for whatever happens.",
        ),
        "pool_side": Term(
            "Pool has a side",
            "Games where somebody in the pool holds at least one of the two "
            "teams. The rest cannot move the standings by a single point.",
        ),
        "swing": Term(
            "Swing",
            "How much a game actually moves the standings. When a team half "
            "the pool owns wins, half the pool rises together and the order "
            "barely changes — so swing measures only the part that separates "
            "people. A game the whole field is on one side of scores zero.",
        ),
        "drama": Term(
            "Drama",
            "Pool swing multiplied by how uncertain the NFL result is, then "
            "scaled so the slate's biggest game is 100. A close game matters "
            "only when its result can separate the pool.",
        ),
        "leverage": Term(
            "Leverage",
            "The leveling factor this entry holds that nobody else does. "
            "Shared teams lift everyone at once; you only gain ground on the "
            "field with teams nobody else has.",
        ),
        "share": Term(
            "Share",
            "How much of an entry's banked total came from the team shown. It "
            "is that team's points divided by all the points the entry has "
            "banked so far.",
        ),
        "bye": Term(
            "Bye",
            "A week a team does not play. Every NFL team takes one during the "
            "regular season, and a team on its bye cannot score you anything — "
            "so a week with two of your four teams off is a quiet one.",
        ),
        "eliminated": Term(
            "Eliminated",
            "Cannot finish first any more: even this entry's ceiling is below "
            "somebody else's floor.",
        ),
        "pot": Term(
            "The pot",
            f"Every {fee} entry added together — {pot} this season, and the "
            f"whole of it is paid out to {paying}.",
        ),
        "p_first": Term(
            "Chance of winning",
            "How often this entry finishes first across every simulated "
            "season. This is the chance of winning the pool outright — it is "
            "not the chance of making money, which is a much easier bar.",
        ),
        "p_cash": Term(
            "Chance of cashing",
            f"How often this entry finishes somewhere that pays — {paying}. "
            "An entry can be very likely to cash and still unlikely to win, "
            "which is why both numbers are on the page.",
        ),
        "expected_payout": Term(
            "Expected payout",
            "The average of what this entry gets paid across every simulated "
            "season — each prize weighted by how often they finish in that "
            "place. It is a long-run average and not a cheque anybody will "
            "ever be handed: the real outcome is one of the actual prizes, or "
            "nothing at all.",
        ),
        "expected_net": Term(
            "Expected profit",
            f"Expected payout minus the {fee} entry. Positive means the entry "
            "is worth more than it cost. Across the whole pool these add up to "
            "zero, because the pot is exactly what everyone paid in — one "
            "entry only shows a profit at another's expense.",
        ),
        "projected_score": Term(
            "Projected final score",
            "Where this entry's final total landed across every simulated "
            "season: the middle of the range, and the band that eight seasons "
            "out of ten fell inside.",
        ),
        "head_to_head": Term(
            "Head to head",
            "How often one entry finishes above another with everybody else "
            "ignored. It is a straight two-horse race, so a pair of opposite "
            "cells always adds to 100%.",
        ),
        "simulations": Term(
            "Simulated seasons",
            "The model plays the rest of the season out thousands of times, "
            "holding every completed game fixed, and counts how often each "
            "thing happens. Anything drawn from it is cyan, so a forecast is "
            "never mistaken for something that already happened.",
        ),
        "game_win_chance": Term(
            "Game win chance",
            "How often this team wins this game in the model's simulated "
            "seasons. It is an NFL outcome forecast, not the chance that an "
            "entry wins the pool.",
        ),
    }
