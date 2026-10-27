"""
data_loader.py

Loads and validates all input files for the fantasy basketball newsletter system.
Provides a centralized data access layer for all other modules.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional
from datetime import date, datetime

import pandas as pd


# =============================================================================
# LEAGUE CONFIG (loaded from config/league_config.json)
# =============================================================================

def _load_league_config():
    """Load league configuration from config/league_config.json."""
    config_path = Path(__file__).parent.parent / "config" / "league_config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"League config not found at {config_path}. "
            f"Copy config/league_config.json.example and fill in your league details."
        )
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

_LEAGUE_CONFIG = _load_league_config()

# --- League identity (from config) ---
MANAGERS = _LEAGUE_CONFIG["managers"]
MANAGER_TO_TEAM = _LEAGUE_CONFIG["manager_to_team"]
TEAM_TO_MANAGER = {v: k for k, v in MANAGER_TO_TEAM.items()}


class UnknownTeam(KeyError):
    """A Yahoo team name that config.manager_to_team does not know."""


_TEAM_KEY_MANAGERS: dict = {}


def team_key_managers(season: str = None, base_path="." ) -> dict:
    """{Yahoo team key: manager} for a season, from RECORDS.team_name_history.

    The TEAM KEY survives a rename and the display name does not, which is
    why the history is keyed on it. Cached by (file stamp, season).
    """
    season = season or CURRENT_SEASON
    path = Path(base_path) / DEFAULT_PATHS["records"]
    stamp = _file_stamp(path)
    hit = _TEAM_KEY_MANAGERS.get((stamp, season))
    if hit is None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                records = json.load(f)
        except (OSError, json.JSONDecodeError):
            records = {}
        history = (records.get("team_name_history") or {}).get(season) or {}
        hit = {str(k): v["manager"] for k, v in history.items()
               if isinstance(v, dict) and v.get("manager")}
        _TEAM_KEY_MANAGERS[(stamp, season)] = hit
    return hit


def manager_for_team(team_name: str, team_key: str = None, season: str = None,
                     base_path=".") -> str:
    """The manager behind a current-season Yahoo team. Raises if unknown.

    PREFER THE TEAM KEY. Pass it wherever Yahoo gives you one: a key survives
    a rename, a display name does not. Garrett renamed "Saboner" to
    "Blink-183" for 2026-27 (found 10-22, the same way Benton's rename was
    found 10-12: fetch_playerlist counted 15 of 60 rostered players as owned
    by nobody), and a key-keyed lookup would not have noticed. The keys come
    from RECORDS.team_name_history, which records them per season.

    The name is the fallback, and it RAISES when it misses. The ingest paths
    used to look it up with a blank-string default: a renamed team became
    manager "" on every lineup row, transaction and injury status, and
    nothing said so. Week 1 would have ingested a whole team under a blank
    manager.
    """
    if team_key:
        hit = team_key_managers(season, base_path).get(str(team_key))
        if hit:
            return hit
    try:
        return TEAM_TO_MANAGER[team_name]
    except KeyError:
        known = sorted(team_key_managers(season, base_path))
        raise UnknownTeam(
            f"Yahoo team {team_name!r}"
            + (f" (key {team_key})" if team_key else "")
            + f" is not in config manager_to_team {sorted(TEAM_TO_MANAGER)}"
            + (f", and that key is not in RECORDS.team_name_history for "
               f"{season or CURRENT_SEASON} {known}" if team_key else "")
            + ". A manager renamed his team: update manager_to_team in "
              "config/league_config.json (and add the season's team keys to "
              "RECORDS.team_name_history).") from None
MANAGER_COLORS = _LEAGUE_CONFIG.get("manager_colors", {})
MANAGER_ALIASES = _LEAGUE_CONFIG.get("manager_aliases", {})
LEAGUE_NAME = _LEAGUE_CONFIG.get("league_name", "Fantasy Basketball League")
LEAGUE_NAME_SHORT = _LEAGUE_CONFIG.get("league_name_short", "Fantasy League")
BRAND_COLORS = _LEAGUE_CONFIG.get("brand_colors", {})
NUM_TEAMS = len(MANAGERS)

# --- Yahoo config (from config) ---
YAHOO_GAME_CODE = _LEAGUE_CONFIG.get("yahoo", {}).get("game_code", "nba")
LEAGUE_KEY = _LEAGUE_CONFIG.get("yahoo", {}).get("current_league_key", "")
HISTORICAL_LEAGUE_KEYS = _LEAGUE_CONFIG.get("yahoo", {}).get("historical_league_keys", {})

# --- League structure (from config) ---
LEAGUE_STRUCTURE = _LEAGUE_CONFIG.get("league_structure", {})
KEEPER_ERA_START = LEAGUE_STRUCTURE.get("keeper_era_start", "2021-22")

# --- The durability prior (from config; no fallback -- a missing key raises) ---
DURABILITY_PRIOR = _LEAGUE_CONFIG["durability_prior"]
FLAT_GP_SHARE_MAX = float(DURABILITY_PRIOR["flat_gp_share_max"])

# --- Simulation counts (from config; no fallback -- a missing key raises) ---
SEASON_SIMS = int(_LEAGUE_CONFIG["simulations"]["season_sims"])
MARGINAL_VALUE_SIMS = int(_LEAGUE_CONFIG["simulations"]["marginal_value_sims"])
MARGINAL_VALUE_SHORTLIST_SIMS = int(_LEAGUE_CONFIG["simulations"]["marginal_value_shortlist_sims"])
PREMISE_TRADE_SAMPLE = int(_LEAGUE_CONFIG["simulations"]["premise_trade_sample"])
PREMISE_TRADE_SAMPLES = int(_LEAGUE_CONFIG["simulations"]["premise_trade_samples"])

# --- Season config (from config) ---
SEASON_CONFIG = _LEAGUE_CONFIG.get("season", {})
CURRENT_SEASON = SEASON_CONFIG.get("current", "")
CURRENT_SEASON_LONG = SEASON_CONFIG.get("current_long", "")
REGULAR_SEASON_WEEKS = SEASON_CONFIG.get("regular_season_weeks", 21)

# Per-season week layout. REGULAR_SEASON_WEEKS describes only the CURRENT
# season; historical seasons have had different shapes and anything walking
# history must not assume one boundary for all time. See league_config.json
# "season_structure" for the values and the derivation.
SEASON_STRUCTURE = _LEAGUE_CONFIG.get("season_structure", {})
PLAYOFF_START_WEEK = SEASON_CONFIG.get("playoff_start_week", 22)
TOTAL_WEEKS = SEASON_CONFIG.get("total_weeks", 23)
# Two scopes, named. No plain SEASON_NUMBER: a consumer must pick one, and a
# missing value raises at import rather than printing "Season 1".
DATA_ERA_SEASON_NUMBER = SEASON_CONFIG["data_era_season_number"]
LEAGUE_SEASON_NUMBER = SEASON_CONFIG["league_season_number"]
NBA_SCHEDULE_FILE = SEASON_CONFIG.get("nba_schedule_file", "")

# --- Pre-data-era history (from config) ---
PRE_DATA_ERA = _LEAGUE_CONFIG.get("pre_data_era", {})

# These keys are named after LEAGUEHISTORY.xlsx's columns on purpose, because
# the two are added together. They used to be "first_place_finishes" and
# "titles", where "titles" meant PLAYOFF championships -- the exact opposite
# of what titles_won means in the file it reconciles against. A reader who
# trusted the name would have credited the wrong managers.
#
# A .get() against a renamed key returns {} and silently contributes zero, so
# the old names are rejected outright rather than ignored.
_LEGACY_PRE_DATA_ERA_KEYS = {
    "first_place_finishes": "titles_won",
    "titles": "playoff_championships",
}
for _old, _new in _LEGACY_PRE_DATA_ERA_KEYS.items():
    if _old in PRE_DATA_ERA:
        raise ValueError(
            f"league_config.pre_data_era uses the old key {_old!r}; rename it "
            f"to {_new!r}. Leaving it would contribute zero silently.")

# --- Weekly add budget (from config) ---
# New for 2026-27. None for any season before it started, which is how a
# caller tells "no budget existed" from "the budget is zero".
WEEKLY_ADD_BUDGET = LEAGUE_STRUCTURE.get("weekly_add_budget")
WEEKLY_ADD_BUDGET_FROM = LEAGUE_STRUCTURE.get("weekly_add_budget_from", "")
COMMISSIONER = _LEAGUE_CONFIG.get("commissioner")
ADVICE_PUBLISH_FROM_WEEK = SEASON_CONFIG.get("advice_publish_from_week")


def add_budget_for(season=None):
    """Adds allowed per team per week, or None if the rule did not exist.

    The rule arrived in 2026-27. Counting an earlier season against it
    reports violations of a rule nobody was playing under.
    """
    season = season or CURRENT_SEASON
    if WEEKLY_ADD_BUDGET is None or not WEEKLY_ADD_BUDGET_FROM:
        return WEEKLY_ADD_BUDGET
    return WEEKLY_ADD_BUDGET if str(season) >= str(WEEKLY_ADD_BUDGET_FROM) else None


# --- Tiebreaker rules (from config) ---
TIEBREAKER_RULES = _LEAGUE_CONFIG.get("tiebreaker_rules", {})


class UnspecifiedRule(KeyError):
    """A league rule the config does not state. Raised, never defaulted:
    a silent default makes missing data look real (Nick, 10-07: "I'd
    rather a loud failure in week 22 than a quietly wrong bracket")."""


def league_rule(*path):
    """The value at `path` in league_config.json, or UnspecifiedRule."""
    node = _LEAGUE_CONFIG
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise UnspecifiedRule(
                f"league_config.json does not specify {'.'.join(path)}. "
                "Add the rule; the engine will not guess it.")
        node = node[key]
    return node

# --- Regular-season records: W-L-T and the standings (one implementation) ---
#
# A tied regular-season week is a T for both managers (tiebreaker_rules.
# regular_season_week = "tie"; Nick, 10-20, following Yahoo). A T counts as
# tie_win_value (0.5) of a win for standings position. Everything that ranks
# the regular season -- playoff seeding, title odds, the angles, season
# outcomes, the draft order -- goes through Record and standings_order below.


def regular_season_tie_value() -> Fraction:
    """What a T is worth in wins, from the config. Raises if the rule for a
    tied regular-season week is missing or is not "tie"."""
    rule = league_rule("tiebreaker_rules", "regular_season_week")
    if rule != "tie":
        raise UnspecifiedRule(f"tiebreaker_rules.regular_season_week = {rule!r}; only 'tie' is defined")
    return Fraction(str(league_rule("tiebreaker_rules", "tie_win_value")))


@dataclass(frozen=True)
class Record:
    """A regular-season record, W-L-T.

    Deliberately NOT a tuple: `w, l = record` and `record[0]` raise
    TypeError, so a caller still written for (wins, losses) breaks loudly
    instead of silently dropping the T.
    """
    wins: int = 0
    losses: int = 0
    ties: int = 0

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def standing(self) -> Fraction:
        """Wins for standings position: W + tie_win_value * T."""
        return self.wins + regular_season_tie_value() * self.ties if self.ties else Fraction(self.wins)

    @property
    def win_pct(self) -> Fraction:
        """(W + 0.5*T) / (W + L + T) -- Yahoo's winning percentage. 0 with no games."""
        return self.standing / self.games if self.games else Fraction(0)

    def add(self, outcome: str) -> "Record":
        if outcome == "win":
            return Record(self.wins + 1, self.losses, self.ties)
        if outcome == "loss":
            return Record(self.wins, self.losses + 1, self.ties)
        if outcome == "tie":
            return Record(self.wins, self.losses, self.ties + 1)
        raise ValueError(f"unknown outcome {outcome!r}")

    def __str__(self) -> str:
        """W-L, or W-L-T once there is a tie (how Yahoo shows it)."""
        return f"{self.wins}-{self.losses}" + (f"-{self.ties}" if self.ties else "")


def week_outcome(score_a: float, score_b: float) -> str:
    """"a", "b" or "tie" for a regular-season week. A tie is a T for both."""
    if score_a > score_b:
        return "a"
    if score_b > score_a:
        return "b"
    regular_season_tie_value()          # the rule must be configured
    return "tie"


def results_from(scores_by_week: dict, matchups_by_week: dict, last_week: int):
    """(records, h2h, points) over weeks 1..last_week.

    scores_by_week {week: {manager: score}}; matchups_by_week {week:
    [{manager_a, manager_b}]}. records {m: Record}; h2h {m: {opp: Record}};
    points {m: total over those weeks}. A pairing with a missing score, or
    with BOTH scores exactly 0, is skipped, as before: the week has not been
    played.
    """
    records: dict = {}
    h2h: dict = {}
    points: dict = {}
    for wk, scores in scores_by_week.items():
        if wk > last_week:
            continue
        for m, sc in scores.items():
            points[m] = points.get(m, 0.0) + sc
        for mu in matchups_by_week.get(wk, []):
            a, b = mu["manager_a"], mu["manager_b"]
            sa, sb = scores.get(a), scores.get(b)
            if sa is None or sb is None:
                continue
            if sa == 0 and sb == 0:
                # Both exactly zero: nothing has been played (a preview or a
                # preseason build writes zeros), not a 0-0 tie. Counted as no
                # result, as it always was.
                continue
            o = week_outcome(sa, sb)
            ra, rb = ("win", "loss") if o == "a" else (("loss", "win") if o == "b" else ("tie", "tie"))
            records[a] = records.get(a, Record()).add(ra)
            records[b] = records.get(b, Record()).add(rb)
            h2h.setdefault(a, {})[b] = h2h.get(a, {}).get(b, Record()).add(ra)
            h2h.setdefault(b, {})[a] = h2h.get(b, {}).get(a, Record()).add(rb)
    return records, h2h, points


def standings_order(records: dict, h2h: dict, points: dict, managers=None, notes=None) -> list:
    """The regular-season standings, best first. THE ranking rule.

      1. winning percentage, (W + 0.5*T) / (W + L + T)
      2. among the managers still level: head-to-head, each one's record
         against the others in that group, a T counting half a win
         (tiebreaker_rules.standings = h2h_regular_season). A split series
         -- 2-2-1 -- cannot separate them.
      3. total points (tiebreaker_rules.fallback = total_points)
    Still level after points, with games played: UnspecifiedRule -- the
    rules stop there. Before any game is played everyone is level by
    definition and the order is the MANAGERS order. `notes`, if a list, gets
    one plain-language line per tie the rules had to break.
    """
    standings_rule = league_rule("tiebreaker_rules", "standings")
    fallback_rule = league_rule("tiebreaker_rules", "fallback")
    if standings_rule != "h2h_regular_season" or fallback_rule != "total_points":
        raise ValueError(f"unknown tiebreak rule {standings_rule}/{fallback_rule}")
    managers = list(managers or MANAGERS)
    rec = {m: records.get(m, Record()) for m in managers}
    if all(r.games == 0 for r in rec.values()):
        return managers
    groups: dict = {}
    for m in managers:
        groups.setdefault(rec[m].win_pct, []).append(m)
    out = []
    for pct in sorted(groups, reverse=True):
        tied = groups[pct]
        if len(tied) > 1:
            within = {m: sum((h2h.get(m, {}).get(o, Record()).standing for o in tied if o != m),
                             Fraction(0)) for m in tied}
            tied = sorted(tied, key=lambda m: (within[m], points.get(m, 0.0)), reverse=True)
            keys = [(within[m], points.get(m, 0.0)) for m in tied]
            if len(set(keys)) < len(keys):
                raise UnspecifiedRule(
                    f"{', '.join(tied)} are level on record, head-to-head and total points; "
                    "the rules have no further tiebreak")
            if notes is not None:
                how = ("head-to-head" if len({within[m] for m in tied}) == len(tied)
                       else "total points (head-to-head could not separate them)")
                notes.append(f"{', '.join(tied)} level at {rec[tied[0]]}: ordered on {how}")
        out.extend(tied)
    return out


# --- Postseason format, keeper rules and payouts (from config) ---
# From 2026-27 the season is three stages, not two: a 15-week regular season,
# a six-week best-of-3 playoff bracket, then a two-week Cup. The old rule
# ("the bracket is the last two weeks") describes seasons through 2025-26 only.
POSTSEASON_FORMAT = _LEAGUE_CONFIG.get("postseason_format", {})
KEEPER_RULES = _LEAGUE_CONFIG.get("keeper_rules", {})
PAYOUTS = _LEAGUE_CONFIG.get("payouts", {})

# Total draft rounds is fixed by the roster: you draft into every non-IL spot.
# Unlike total_draft_rounds (live picks) this does not move when keeper counts
# change, so anything iterating rounds should use it.
TOTAL_ROUNDS = LEAGUE_STRUCTURE.get(
    "total_rounds",
    LEAGUE_STRUCTURE.get("roster_size", 17) - LEAGUE_STRUCTURE.get("il_slots", 2))


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_PATHS = {
    "playerlog": "data/PLAYERLOG.xlsx",
    "lineups": "data/LINEUPS.xlsx",
    "playerlist": "data/PLAYERLIST.xlsx",
    "leaguehistory": "data/LEAGUEHISTORY.xlsx",
    "schedule": "config/SCHEDULE.json",
    "injury_overrides": "config/INJURY_OVERRIDES.json",
    "records": "config/RECORDS.json",
    "nba_schedule": NBA_SCHEDULE_FILE or "data/nba_schedule.json",
    "league_history_detailed": "data/LEAGUE_HISTORY_DETAILED.json",
    "all_matchups": "data/historical/all_matchups.json",
    "historical_playerlog": "data/historical/HISTORICAL_PLAYERLOG.json",
}

STARTER_SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "UTIL"]
BENCH_SLOTS = ["BN"]
IL_SLOTS = ["IL", "IL+"]

SLOT_ELIGIBILITY = {
    "PG": ["PG"],
    "SG": ["SG"],
    "G": ["PG", "SG"],
    "SF": ["SF"],
    "PF": ["PF"],
    "F": ["SF", "PF"],
    "C": ["C"],
    "UTIL": ["PG", "SG", "SF", "PF", "C"],
    "BN": ["PG", "SG", "SF", "PF", "C"],
    "IL": ["PG", "SG", "SF", "PF", "C"],
    "IL+": ["PG", "SG", "SF", "PF", "C"],
}

# Current roster shape (2026-27): 10 starters + 5 bench + 2 IL = 17.
# Through Week 15 of 2025-26 it was 10 starters + 3 BN + 2 IL + 2 IL+; the
# league converted the two IL+ slots to bench slots effective Week 16
# (2026-02-02), which is also why the draft grew from 13 rounds to 15.
#
# IL+ is intentionally still handled elsewhere (IL_SLOTS, SLOT_ELIGIBILITY,
# the bench-slot filters in weekly_stats and consistency_score) because every
# season through 2025-26 Week 15 has IL+ rows in its lineup data.
ROSTER_SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "UTIL", "UTIL",
                "BN", "BN", "BN", "BN", "BN", "IL", "IL"]


@dataclass
class FantasyData:
    """Container for all loaded fantasy data."""

    playerlog: pd.DataFrame = field(default_factory=pd.DataFrame)
    lineups: pd.DataFrame = field(default_factory=pd.DataFrame)
    playerlist: pd.DataFrame = field(default_factory=pd.DataFrame)
    leaguehistory: pd.DataFrame = field(default_factory=pd.DataFrame)

    schedule: dict = field(default_factory=dict)
    injury_overrides: dict = field(default_factory=dict)
    records: dict = field(default_factory=dict)
    nba_schedule: dict = field(default_factory=dict)
    league_history_detailed: Optional[dict] = None
    all_matchups: list = field(default_factory=list)
    historical_playerlog: list = field(default_factory=list)

    season_year: str = ""
    current_week: int = 0
    base_path: Path = field(default_factory=lambda: Path("."))
    # The baseline hazard's durability input, frozen to a pre-season snapshot
    # (load_durability_prior). None -- the default, and what a synthetic world
    # or a retro-sim harness gets -- means the projections' OWN projected_gp
    # is the prior, which is right only for a file whose GP column is still
    # pre-season. load_all_data always sets it.
    durability_prior: Optional["DurabilityPrior"] = None

    def regular_season_results(self, include_playoffs: bool = False):
        """(records, h2h, points) for the current season so far -- see
        results_from. From RECORDS.json weekly_scores + SCHEDULE.json
        matchups, regular season only unless include_playoffs."""
        if include_playoffs:
            max_week = TOTAL_WEEKS
        else:
            # Deliberately NOT self.schedule["regular_season_weeks"]: the boundary comes from league_config, not SCHEDULE.json. That file is written per season and is the PREVIOUS season's for the whole preseason, so reading week counts out of it silently applies last year's shape -- 21 regular-season weeks where 2026-27 has 15.
            max_week = regular_season_weeks_for(CURRENT_SEASON)
        scores_by_week: dict = {}
        weekly_scores = self.records.get("weekly_scores", {})
        if isinstance(weekly_scores, dict):
            for mgr, entries in weekly_scores.items():
                if not isinstance(entries, list):
                    continue
                for e in entries:
                    wk = e.get("week")
                    if wk is None or wk > max_week:
                        continue
                    scores_by_week.setdefault(wk, {})[mgr] = e.get("score", 0.0)
        matchups = {wk: self.get_week_matchups(wk) for wk in scores_by_week}
        return results_from(scores_by_week, matchups, max_week)

    def get_manager_record(self, manager: str, include_playoffs: bool = False) -> "Record":
        """
        Current season record for a manager, as a Record (W-L-T).

        By default REGULAR-SEASON-ONLY (weeks 1 through the regular season's
        last): the league treats regular-season and playoff records as
        separate. A tied week is a T (tiebreaker_rules.regular_season_week).

        Computed from RECORDS.json weekly_scores + SCHEDULE.json matchups so
        the result is correct regardless of what LEAGUEHISTORY.xlsx contains
        (manually entered, may already include playoff games); that file is
        the fallback before any week is in RECORDS.
        """
        records, _h2h, _pts = self.regular_season_results(include_playoffs)
        rec = records.get(manager)
        if rec is not None and rec.games:
            return rec

        row = self.leaguehistory[self.leaguehistory["manager_name"] == manager]
        if row.empty:
            return Record()
        return parse_record_string(row.iloc[0]["record_current_season"])

    def get_week_dates(self, week: int) -> tuple[date, date]:
        """Get start and end dates for a fantasy week."""
        for w in self.schedule.get("weeks", []):
            if w["week"] == week:
                start = datetime.strptime(w["start_date"], "%Y-%m-%d").date()
                end = datetime.strptime(w["end_date"], "%Y-%m-%d").date()
                return (start, end)
        raise ValueError(f"Week {week} not found in schedule")

    def get_week_matchups(self, week: int) -> list[dict]:
        """Get matchups for a given week."""
        for w in self.schedule.get("weeks", []):
            if w["week"] == week:
                return w["matchups"]
        return []

    def get_player_projection(self, player_name: str) -> Optional[float]:
        """Get projected FPPG for a player from PLAYERLIST.

        Resolved through PlayerIndex, the one name resolver: exact, then
        accents and punctuation, then a generational suffix, then a first
        initial. This used to carry its own copy of that ladder, and the
        copies drifted -- the simulators' copy stopped at step two.
        """
        if self.playerlist.empty or "player_name" not in self.playerlist.columns:
            return None
        idx = getattr(self, "_projection_index", None)
        if idx is None or getattr(self, "_projection_index_src", None) is not self.playerlist:
            idx = PlayerIndex()
            for name, fppg in zip(self.playerlist["player_name"],
                                  self.playerlist["projectedFPPG"]):
                if not dict.__contains__(idx, name):   # first row wins, as before
                    idx[name] = fppg
            self._projection_index = idx
            self._projection_index_src = self.playerlist
        return idx.get(player_name)

    def _injury_entry(self, player_name: str):
        """The override entry for a player, matched through PlayerIndex.

        This was a lowercase comparison: "Nikola Jokic" in the overrides
        never matched the accented roster spelling, silently.
        """
        idx = PlayerIndex()
        for entry in self.injury_overrides.get("players", []):
            for name in (entry.get("player_name"), entry.get("_override_spelling")):
                if name and not dict.__contains__(idx, name):
                    idx[name] = entry
        return idx.get(player_name)

    def get_player_injury_weeks(self, player_name: str) -> list[int]:
        """Get weeks a player is out due to injury override."""
        entry = self._injury_entry(player_name)
        return entry.get("out_weeks", []) if entry else []

    def get_player_return_info(self, player_name: str) -> dict:
        """Get return info for a player if they have a confirmed return."""
        player = self._injury_entry(player_name)
        if not player or not player.get("return_week"):
            return {}
        return {
            "return_week": player.get("return_week"),
            "return_games": player.get("return_games"),
            "total_week_games": player.get("total_week_games"),
            "return_notes": player.get("return_notes", ""),
            "return_date": player.get("return_date"),
        }

    def get_player_out_from(self, player_name: str):
        """INJURY_OVERRIDES out_from (raw), or None: unavailable on and after
        that date, within its fantasy week. Parsed by absence.parse_out_from."""
        entry = self._injury_entry(player_name)
        return entry.get("out_from") if entry else None

    def is_player_available(self, player_name: str, week: int) -> bool:
        """Check if player is available for a given week."""
        out_weeks = self.get_player_injury_weeks(player_name)
        return week not in out_weeks

    def get_roster_for_date(self, manager: str, game_date: date) -> pd.DataFrame:
        """Get a manager's roster for a specific date from LINEUPS."""
        date_str = game_date.strftime("%Y-%m-%d")
        mask = (
            (self.lineups["manager"] == manager) &
            (self.lineups["date"].astype(str) == date_str)
        )
        return self.lineups[mask].copy()

    def get_nba_games_for_date(self, game_date: date) -> list[dict]:
        """Get all NBA games scheduled for a date."""
        date_str = game_date.strftime("%Y-%m-%d")
        games = []

        if "leagueSchedule" in self.nba_schedule:
            for game_date_obj in self.nba_schedule["leagueSchedule"].get("gameDates", []):
                for game in game_date_obj.get("games", []):
                    game_date_est = game.get("gameDateEst", "")
                    if game_date_est.startswith(date_str):
                        if game.get("gameLabel", "").lower() == "preseason":
                            continue
                        games.append({
                            "date": date_str,
                            "home_team": game.get("homeTeam", {}).get("teamTricode", ""),
                            "away_team": game.get("awayTeam", {}).get("teamTricode", ""),
                        })
        else:
            for game in self.nba_schedule.get("games", []):
                game_date_raw = game.get("date", "")
                if game_date_raw.startswith(date_str):
                    games.append({
                        "date": date_str,
                        "home_team": game.get("home", game.get("home_team", "")),
                        "away_team": game.get("away", game.get("away_team", "")),
                    })

        return games

    def get_teams_playing_on_date(self, game_date: date) -> set[str]:
        """Get set of NBA team abbreviations playing on a date."""
        teams = set()
        for game in self.get_nba_games_for_date(game_date):
            home = game.get("home_team", game.get("home", "")).upper()
            away = game.get("away_team", game.get("away", "")).upper()
            if home:
                teams.add(home)
            if away:
                teams.add(away)
        return teams

    def get_free_agents(self, rosters: Optional[dict] = None) -> pd.DataFrame:
        """PLAYERLIST players on no roster. See free_agents().

        `rosters` defaults to get_current_rosters() so the three existing
        callers are unchanged; anything that must not read config/ (C1, the
        retro-sim) passes rosters in.
        """
        if rosters is None:
            rosters = self.get_current_rosters()
        return free_agents(self.playerlist, rosters)

    def get_current_rosters(self) -> dict[str, list[str]]:
        """Get current rosters from ROSTERS.json."""
        rosters_file = Path(__file__).parent.parent / "config" / "ROSTERS.json"
        if rosters_file.exists():
            try:
                import json
                with open(rosters_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                config_rosters = config_data.get("rosters", config_data)
                return {
                    manager: players
                    for manager, players in config_rosters.items()
                    if isinstance(players, list)
                }
            except (json.JSONDecodeError, KeyError):
                pass

        most_recent_date = self.lineups["date"].max()
        current = self.lineups[self.lineups["date"] == most_recent_date]
        rosters = {}
        for manager in MANAGERS:
            players = current[current["manager"] == manager]["player_name"].tolist()
            rosters[manager] = players
        return rosters


# =============================================================================
# LOADING FUNCTIONS
# =============================================================================

def normalize_manager_name(name: str) -> str:
    """Normalize manager name to canonical form using MANAGER_ALIASES from config."""
    name = str(name).strip()
    return MANAGER_ALIASES.get(name.lower(), name)


def load_excel_file(path: Path, required_columns: list[str] = None) -> pd.DataFrame:
    """Load an Excel file and validate required columns."""
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    df = pd.read_excel(path)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]

    if required_columns:
        missing = set(required_columns) - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns in {path.name}: {missing}")

    return df


def load_json_file(path: Path) -> dict:
    """Load a JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_playerlog(path: Path) -> pd.DataFrame:
    """Load and validate PLAYERLOG.xlsx."""
    required = [
        "season_year", "week", "date", "manager", "fantasy_team",
        "player_name", "nba_team", "positions", "nba_opponent",
        "fantasy_points", "is_injured", "started"
    ]
    df = load_excel_file(path, required)
    df["manager"] = df["manager"].apply(normalize_manager_name)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["is_injured"] = df["is_injured"].fillna(False).astype(bool)
    df["started"] = df["started"].fillna(False).astype(bool)
    df["fantasy_points"] = pd.to_numeric(df["fantasy_points"], errors="coerce").fillna(0.0)
    return df


def load_lineups(path: Path) -> pd.DataFrame:
    """Load and validate LINEUPS.xlsx."""
    required = [
        "season_year", "week", "date", "manager", "fantasy_team",
        "player_name", "nba_team", "positions", "slot"
    ]
    df = load_excel_file(path, required)
    df["manager"] = df["manager"].apply(normalize_manager_name)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["slot"] = df["slot"].astype(str).str.upper()
    return df


_GENERATIONAL_SUFFIX = re.compile(r"\s+(?:jr|sr|ii|iii|iv|v)\.?\s*$", re.IGNORECASE)


def _without_suffix(name) -> str:
    """Normalised name with any trailing Jr/Sr/II/III/IV/V removed."""
    return normalize_player_name(_GENERATIONAL_SUFFIX.sub("", str(name or "").strip()))


def _last_name_with_initial(name) -> str:
    """"Shai Gilgeous-Alexander" and "S. Gilgeous-Alexander" -> "sgilgeousalexander".

    Returns "" for a single-word name, where there is no initial to take
    and the whole thing would collide with every other one-word entry.
    """
    cleaned = _GENERATIONAL_SUFFIX.sub("", str(name or "").strip())
    parts = [p for p in cleaned.split() if p]
    if len(parts) < 2:
        return ""
    first = normalize_player_name(parts[0])
    last = normalize_player_name(" ".join(parts[1:]))
    if not first or not last:
        return ""
    return first[0] + last


_INITIAL_TOKEN = re.compile(r"^[A-Za-z]\.?$")


def _is_abbreviated(name) -> bool:
    """True when the first name is written as an initial: "S. Gilgeous-Alexander"."""
    parts = _GENERATIONAL_SUFFIX.sub("", str(name or "").strip()).split()
    return len(parts) >= 2 and bool(_INITIAL_TOKEN.match(parts[0]))


def initial_match(a, b) -> bool:
    """Same player, one of the two spelled with a first initial.

    "Shai Gilgeous-Alexander" and "S. Gilgeous-Alexander" match. "Lonzo
    Ball" and "LaMelo Ball" do NOT: both reduce to "lball", but neither is
    abbreviated, so they are two people. Matching on the reduced form alone
    resolved Lonzo to LaMelo, Danny to Draymond Green, Justin to Jrue
    Holiday and Thaddeus to Trae Young (measured 2026-10-12 against the
    real PLAYERLIST) -- a real player's projection handed to someone else.
    """
    ka, kb = _last_name_with_initial(a), _last_name_with_initial(b)
    return bool(ka) and ka == kb and (_is_abbreviated(a) or _is_abbreviated(b))



def closest_player_name(name: str, pool, cutoff: float = 0.8):
    """The name in `pool` nearest to `name`, or None -- for SUGGESTING what a
    name that resolved to nobody was probably meant to be (a typo), never for
    resolving one: PlayerIndex resolves, this only advises. Compared on
    normalised names, so an accent or a suffix is not a near miss but an
    exact one, and it lives here so no other file grows its own matching."""
    import difflib
    by_norm = {normalize_player_name(n): n for n in pool}
    hit = difflib.get_close_matches(normalize_player_name(name), list(by_norm), n=1, cutoff=cutoff)
    return by_norm[hit[0]] if hit else None

class PlayerIndex(dict):
    """A {player name: value} mapping that matches across accent spellings.

    PLAYERLIST keeps Yahoo's spelling -- Jokic, Doncic, Sengun, Demin,
    Nurkic and Porzingis all carry diacritics. LINEUPS, PLAYERLOG and
    ROSTERS strip them on the way in (update_fantasy_logs and
    sync_transactions both call strip_accents). So every join FROM a
    roster INTO PLAYERLIST compares "Nikola Jokic" against "Nikola
    Jokic" with an acute accent, and misses.

    A miss is not an error. It falls through to a default -- 0.0 for a
    projection, 27 for an age -- and publishes it as though it were
    measured. Keepability scored the best player in the league at 0.0
    projected FPPG and guessed his age, three days before a keeper
    deadline, and nothing anywhere said so.

    This exists so no caller has to remember. Lookups normalise; keys,
    iteration and .values() are untouched, so anything that prints a key
    still prints the accented spelling Yahoo gave us.

    Strictly more permissive than dict: an exact match behaves exactly
    as before, and only a miss falls back to the normalised form.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._normalised = {}
        self._nosuffix = {}
        self._initial = {}
        for k in self:
            self._index(k)

    def _index(self, key):
        self._normalised[normalize_player_name(key)] = key
        self._nosuffix.setdefault(_without_suffix(key), []).append(key)
        initial = _last_name_with_initial(key)
        if initial:
            self._initial.setdefault(initial, []).append(key)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._index(key)

    def __delitem__(self, key):
        resolved = self._resolve(key)
        if resolved is None:
            raise KeyError(key)
        super().__delitem__(resolved)
        # All THREE indexes, or the deleted name keeps resolving through a
        # fallback. Removing it from _normalised alone left it findable by
        # suffix and by initial.
        self._normalised.pop(normalize_player_name(resolved), None)
        for index, probe in ((self._nosuffix, _without_suffix(resolved)),
                             (self._initial, _last_name_with_initial(resolved))):
            remaining = [k for k in index.get(probe, []) if k != resolved]
            if remaining:
                index[probe] = remaining
            else:
                index.pop(probe, None)

    def _resolve(self, key):
        """The stored key matching `key`, exactly or by spelling.

        Four steps, each only tried when the one before it misses, and the
        last two only accepted when they land on exactly one player:

            exact                "Nikola Jokic"
            accents/punctuation  "Nikola Jokic"   <- "Nikola Jokic" (acute)
            generational suffix  "Bobby Portis"   <- "Bobby Portis Jr."
            first initial        "S. Gilgeous-Alexander" <- "Shai ..."

        The last two are Yahoo's doing. On 2026-10-05 it rewrote Shai
        Gilgeous-Alexander as "S. Gilgeous-Alexander" and Bobby Portis as
        "Bobby Portis Jr." -- no projection changed, just the spelling --
        while every other file in the project still used the old form.
        Normalising only collapses accents and punctuation, so both came
        back as a missing projection on a keeper.

        Ambiguity is a miss, not a guess. Two players who reduce to the
        same last name and initial resolve to neither, and the initial step
        only fires when one side really is written as an initial -- "Lonzo
        Ball" is not "LaMelo Ball" (initial_match).
        """
        if super().__contains__(key):
            return key
        hit = self._normalised.get(normalize_player_name(key))
        if hit is not None:
            return hit
        candidates = set(self._nosuffix.get(_without_suffix(key)) or [])
        if len(candidates) == 1:
            return next(iter(candidates))
        probe = _last_name_with_initial(key)
        if probe:
            # Only an abbreviated spelling on one side makes two names the
            # same person; see initial_match.
            candidates = {k for k in self._initial.get(probe) or []
                          if initial_match(key, k)}
            if len(candidates) == 1:
                return next(iter(candidates))
        return None

    def canonical(self, key):
        """The stored key `key` resolves to, or None."""
        return self._resolve(key)

    def __getitem__(self, key):
        resolved = self._resolve(key)
        if resolved is None:
            raise KeyError(key)
        return super().__getitem__(resolved)

    def __contains__(self, key):
        return self._resolve(key) is not None

    def get(self, key, default=None):
        resolved = self._resolve(key)
        return super().__getitem__(resolved) if resolved is not None else default

    def setdefault(self, key, default=None):
        resolved = self._resolve(key)
        if resolved is not None:
            return super().__getitem__(resolved)
        self[key] = default
        return default

    def update(self, other=(), **kwargs):
        for k, v in (other.items() if hasattr(other, "items") else other):
            self[k] = v
        for k, v in kwargs.items():
            self[k] = v


def normalize_player_name(name) -> str:
    """Collapse case, accents and punctuation so spelling variants collide.

    Yahoo serves accented names -- Jokic, Doncic, Sengun, Demin, Nurkic all
    come back with diacritics, five of them in the top 150 alone. Every
    lookup into PLAYERLIST used exact string equality, so an accented name
    simply did not match the roster entry and the player fell through to a
    0.0 FPPG projection. Silently: no error, no warning, just a star player
    worth nothing in every simulation that week.

    The same function the history rollup uses, for the same reason.
    """
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = text.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def roster_index(rosters: dict) -> "PlayerIndex":
    """Every rostered player, as a PlayerIndex: {name: manager}."""
    idx = PlayerIndex()
    for manager, players in (rosters or {}).items():
        if isinstance(players, list):
            for name in players:
                idx[name] = manager
    return idx


def free_agents(playerlist: pd.DataFrame, rosters: dict) -> pd.DataFrame:
    """PLAYERLIST rows for players on no roster.

    Membership goes through PlayerIndex. The version this replaced compared
    normalised names, which collapses accents but not Yahoo's respellings:
    on 2026-10-05 Yahoo began writing "S. Gilgeous-Alexander" while every
    roster file kept "Shai Gilgeous-Alexander", and the rostered MVP came
    back as a free agent. It also read config/ROSTERS.json itself; rosters
    are now an argument.
    """
    rostered = roster_index(rosters)
    mask = [name not in rostered for name in playerlist["player_name"]]
    return playerlist[mask].copy()


# =============================================================================
# THE DURABILITY PRIOR -- projected GP, from a pre-season file, on purpose
# =============================================================================
#
# PLAYERLIST does two jobs and only one of them survives the season starting:
#
#   projectedFPPG, total projected FP   the scoring inputs. Taken LIVE; they
#                                       refresh correctly (FPPG correlates
#                                       0.97 across a mid-season refresh).
#   player_proj_GP                      the durability prior. Taken from a
#                                       PRE-SEASON SNAPSHOT, because the
#                                       column's MEANING changes in season:
#                                       projected games out of 82 with a
#                                       haircut on everyone becomes games out
#                                       of those remaining, marked down only
#                                       for a known current absence.
#
# Measured 2026-10-22: stored snapshots mean 69.1 GP, sd 4.9, 31% of players
# within one game of the median; a fresh fetch the same day mean 77.7, sd
# 2.74, 96% within one game. The hazard rate reads
# (82 - gp) / 82, so live-in-season turns 16% a game into 1.5% -- the injury
# model switches itself off and the level bias comes back
# (claude/HANDOFF_DURABILITY_PRIOR_2026-10-22.md).
#
# One seam: this object answers "how durable is he", and nothing else does.
# claude/DURABILITY_BLEND_DESIGN.md replaces its answer with a posterior
# later; the callers do not change when it does.


def gp_dispersion(values) -> dict:
    """How flat a projected-GP column is: {n, median, within_one, share}.

    `share` is the fraction of players within one game of the median. A
    pre-season column has a durability haircut spread across players (0.31 on
    every stored snapshot); an in-season one is nearly everyone's remaining
    games (0.96 on a fresh fetch), and is not a durability forecast at all.
    """
    gp = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    if gp.empty:
        return {"n": 0, "median": None, "within_one": 0, "share": None}
    median = float(gp.median())
    within = int((gp - median).abs().le(1).sum())
    return {"n": int(len(gp)), "median": median, "within_one": within,
            "share": within / len(gp)}


def gp_column_is_flat(values, limit: float = None) -> tuple:
    """(is it flat, the dispersion). Flat means in-season shaped: refuse it."""
    d = gp_dispersion(values)
    limit = FLAT_GP_SHARE_MAX if limit is None else limit
    return (d["share"] is not None and d["share"] > limit), d


class DurabilityPrior:
    """Each player's pre-season projected GP, and where it came from.

    gp_for(name) resolves through PlayerIndex and falls back to the league
    MEDIAN pre-season GP for a player the snapshot does not have -- a
    mid-season pickup. Never to "perfectly durable": that is the defect this
    class exists to prevent, one player at a time. Every fallback is recorded
    and reported.
    """

    def __init__(self, gp: dict, source: str, note: str = "", dispersion: dict = None):
        self.gp = gp if isinstance(gp, PlayerIndex) else PlayerIndex(gp or {})
        self.source = str(source)
        self.note = note
        self.dispersion = dispersion or gp_dispersion(dict.values(self.gp))
        self.median_gp = self.dispersion.get("median")
        self.fallbacks: dict = {}

    def gp_for(self, name: str, own: float = None):
        """(projected GP, fell back?). `own` is the player's GP in the live
        file: used only when there is no snapshot at all (source == "")."""
        hit = self.gp.get(name)
        if hit is not None:
            return float(hit), False
        if not self.source and own is not None:
            return float(own), False
        self.fallbacks[str(name)] = self.median_gp
        return self.median_gp, True

    def record(self) -> dict:
        return {
            "source": self.source or "the run's own projections (no snapshot)",
            "players": self.dispersion.get("n"),
            "median_gp": self.median_gp,
            "flat_gp_share": (None if self.dispersion.get("share") is None
                              else round(self.dispersion["share"], 3)),
            "note": self.note,
            "median_fallbacks": sorted(self.fallbacks),
        }

    def __repr__(self):
        return f"DurabilityPrior({self.source!r}, {self.dispersion.get('n')} players)"


class DurabilityPriorError(RuntimeError):
    """The configured durability prior cannot be used."""


# The snapshot is a few hundred rows of xlsx, 0.1 s a read, and every
# load_all_data wants it. Keyed by (path, mtime, size); a fresh
# DurabilityPrior is built per call, so one run's median fallbacks never
# show up in another's record.
_DURABILITY_PRIOR_CACHE: dict = {}


def load_durability_prior(base_path: Path = Path("."), config: dict = None) -> DurabilityPrior:
    """config durability_prior.snapshot -> DurabilityPrior. No silent fallback.

    A missing key, a missing file or a GP column with in-season dispersion all
    RAISE: running on the live file instead is exactly the bug
    (HANDOFF_DURABILITY_PRIOR_2026-10-22). The snapshot is NAMED in config, not
    picked from a directory listing, so nothing re-chooses it mid-season.
    """
    cfg = DURABILITY_PRIOR if config is None else config.get("durability_prior", {})
    rel = (cfg or {}).get("snapshot")
    if not rel:
        raise DurabilityPriorError(
            "config/league_config.json durability_prior.snapshot is not set. The "
            "baseline injury hazard needs a PRE-SEASON PLAYERLIST for its durability "
            "prior; the live file's GP column means something else in season.")
    path = Path(base_path) / rel
    if not path.is_file():
        raise DurabilityPriorError(
            f"the durability prior {rel} is missing. Point "
            "config/league_config.json durability_prior.snapshot at a pre-season "
            "PLAYERLIST snapshot (py scripts/check_playerlist.py --snapshot writes one).")
    stamp = _file_stamp(path)
    cached = _DURABILITY_PRIOR_CACHE.get(stamp)
    if cached is not None:
        gp, dispersion, flat = cached            # parsed once per process per file
    else:
        try:
            frame = pd.read_excel(path)
        except Exception as e:
            raise DurabilityPriorError(f"could not read the durability prior {rel}: {e}") from e
        for col in ("player_name", "player_proj_GP"):
            if col not in frame.columns:
                raise DurabilityPriorError(f"the durability prior {rel} has no {col} column")
        gp = {}
        for name, value in zip(frame["player_name"], frame["player_proj_GP"]):
            v = pd.to_numeric(value, errors="coerce")
            if pd.notna(name) and pd.notna(v) and float(v) > 0:
                gp[str(name)] = float(v)
        if not gp:
            raise DurabilityPriorError(f"the durability prior {rel} has no usable projected GP")
        flat, dispersion = gp_column_is_flat(gp.values())
        if stamp is not None:
            _DURABILITY_PRIOR_CACHE[stamp] = (gp, dispersion, flat)
    if flat:
        raise DurabilityPriorError(
            f"{rel} is not a pre-season file: {dispersion['within_one']} of "
            f"{dispersion['n']} players ({dispersion['share']:.0%}) are within one game "
            f"of the median {dispersion['median']:.0f}, above the "
            f"{FLAT_GP_SHARE_MAX:.0%} limit. In season Yahoo's GP column is games "
            "REMAINING, not a durability forecast, and using it would switch the "
            "injury hazard off. Point durability_prior.snapshot at a snapshot taken "
            "before week 1.")
    return DurabilityPrior(gp, rel, str((cfg or {}).get("_which", "")).split(".")[0], dispersion)


def load_playerlist(path: Path) -> pd.DataFrame:
    """Load and validate PLAYERLIST.xlsx."""
    required = [
        "player_name", "player_nba_team", "player_position(s)",
        "player_total_proj_FP", "player_proj_GP", "projectedFPPG"
    ]
    df = load_excel_file(path, required)
    df["projectedFPPG"] = pd.to_numeric(df["projectedFPPG"], errors="coerce").fillna(0.0)
    # Every lookup joins on this, never on the raw name.
    df["_name_key"] = df["player_name"].apply(normalize_player_name)
    # Yahoo rewrites names without warning: on 2026-10-05 it turned
    # "Shai Gilgeous-Alexander" into "S. Gilgeous-Alexander" and "Bobby
    # Portis" into "Bobby Portis Jr." without changing a single projection.
    # Every other file in the project still held the old spelling.
    df["_name_nosuffix"] = df["player_name"].apply(_without_suffix)
    df["_name_initial"] = df["player_name"].apply(_last_name_with_initial)
    return df


def load_leaguehistory(path: Path) -> pd.DataFrame:
    """Load and validate LEAGUEHISTORY.xlsx."""
    required = ["manager_name", "record_current_season", "total_points_current_season"]
    df = load_excel_file(path, required)
    df["manager_name"] = df["manager_name"].apply(normalize_manager_name)
    return df


def load_schedule(path: Path) -> dict:
    """Load and validate SCHEDULE.json."""
    data = load_json_file(path)
    required_keys = ["season_year", "total_weeks", "weeks"]
    for key in required_keys:
        if key not in data:
            raise ValueError(f"SCHEDULE.json missing required key: {key}")
    for week in data["weeks"]:
        if "week" not in week or "start_date" not in week or "end_date" not in week:
            raise ValueError(f"Invalid week entry in SCHEDULE.json: {week}")
    return data


def load_injury_overrides(path: Path) -> dict:
    """Load INJURY_OVERRIDES.json, names as written. Prefer the resolved form:
    load_resolved_injury_overrides(), or FantasyData.injury_overrides."""
    if not path.exists():
        return {"players": [], "last_updated": None}
    return load_json_file(path)


def resolve_injury_overrides(overrides: dict, rosters: dict,
                             playerlist_names) -> dict:
    """INJURY_OVERRIDES with every name in the spelling its consumers use.

    A dozen places read this file and every one matched names exactly (or
    lowercased): "player_name in roster", "isin(injured)". So "Nikola Jokic"
    typed into the overrides silently failed to match "Nikola Jokic" with
    the diacritic on a roster -- and this is the engine's only input for
    block absences, so the failure was a healthy player in every simulation
    (STATUS 10-12 sec.3 item 4).

    Resolving once, here, fixes all of them: a rostered player gets the
    ROSTERS.json spelling (what the roster-side code compares against), an
    unrostered one PLAYERLIST's (what the free-agent filters compare
    against). The name as typed is kept in "_override_spelling". A name
    that resolves to nobody stays as typed and is listed in "_unresolved";
    the loader warns and verify_project_integrity fails on it.
    """
    on_roster = PlayerIndex({p: p for ps in (rosters or {}).values()
                             if isinstance(ps, list) for p in ps})
    in_list = PlayerIndex({n: n for n in (list(playerlist_names)
                                          if playerlist_names is not None else [])})
    out = dict(overrides or {})
    players, unresolved = [], []
    for entry in (overrides or {}).get("players", []):
        entry = dict(entry)
        typed = str(entry.get("player_name", ""))
        hit = on_roster.get(typed) or in_list.get(typed)
        if hit is None:
            unresolved.append(typed)
        elif hit != typed:
            entry["_override_spelling"] = typed
            entry["player_name"] = hit
        players.append(entry)
    out["players"] = players
    out["_unresolved"] = unresolved
    return out


def _read_rosters_file(path: Path) -> dict:
    if not Path(path).is_file():
        return {}
    blob = json.loads(Path(path).read_text(encoding="utf-8"))
    rosters = blob.get("rosters", blob)
    return {m: p for m, p in rosters.items() if isinstance(p, list)}


def _warn_unresolved(resolved: dict) -> None:
    missing = resolved.get("_unresolved") or []
    if missing:
        print(f"  WARNING: INJURY_OVERRIDES names {missing} match no rostered "
              f"player and nothing in PLAYERLIST. They are IGNORED by every "
              f"simulation. Fix the spelling in config/INJURY_OVERRIDES.json.",
              file=sys.stderr)


def load_resolved_injury_overrides(base_path=".", playerlist_names=None) -> dict:
    """INJURY_OVERRIDES.json from base_path, resolved (resolve_injury_overrides)."""
    base = Path(base_path)
    raw = load_injury_overrides(base / DEFAULT_PATHS["injury_overrides"])
    if playerlist_names is None:
        pl = base / DEFAULT_PATHS["playerlist"]
        playerlist_names = (pd.read_excel(pl)["player_name"].dropna().tolist()
                            if pl.is_file() else [])
    resolved = resolve_injury_overrides(
        raw, _read_rosters_file(base / "config" / "ROSTERS.json"), playerlist_names)
    _warn_unresolved(resolved)
    return resolved


# =============================================================================
# TIE CONVENTIONS (project-wide)
# =============================================================================
# Fractional scoring (two decimal places) makes exact ties essentially
# impossible in real games, but the codebase still needs explicit rules
# for the rare edge case and -- more importantly -- for simulated weeks.
# Conventions:
#   * Simulations (title odds, playoff bracket, betting lines):
#         coin flip (random tiebreak). A simulated tie should resolve
#         either way with equal probability -- this is statistically
#         honest. See simulator_title_odds.py, simulator_playoff_odds.py,
#         simulator_betting.py.
#   * Actual completed games (playoff bracket resolution, historical
#         h2h reconstruction): "higher seed wins", implemented by
#         awarding the tie to manager_a (which is the higher-seeded
#         entry in SCHEDULE.json playoff matchups). Deterministic and
#         consistent. See simulator_playoff_odds.py:resolve_completed_week,
#         records_tracker.py.
#   * Luck index (all-play schedule-luck calc): split credit 0.5 wins
#         and 0.5 losses to each side. Mathematically correct for the
#         expected-wins comparison. See luck_index.py.
#   * W-L records (RECORDS.json, get_manager_record): tie counts as
#         neither a win nor a loss. Standard W-L bookkeeping convention.
# =============================================================================


def load_records(path: Path) -> dict:
    """Load RECORDS.json."""
    if not path.exists():
        return {
            "season_year": CURRENT_SEASON_LONG,
            "last_updated_week": 0,
            # Two watermarks: the week whose RESULTS are recorded, and the
            # week whose DERIVED history (bench points, blunders) is. They
            # are written at different points in the build and must be
            # guarded apart -- see records_tracker's phase comment.
            "last_history_week": 0,
            "title_odds_history": {},
            "season_records": {},
            "h2h_season": {},
            "cumulative_bench_points": {m: 0.0 for m in MANAGERS},
            "weekly_scores": []
        }
    return load_json_file(path)


def load_nba_schedule(path: Path) -> dict:
    """Load NBA schedule JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"NBA schedule file not found: {path}")
    return load_json_file(path)


def load_league_history_detailed(path: Path) -> Optional[dict]:
    """Load LEAGUE_HISTORY_DETAILED.json if it exists."""
    if not path.exists():
        return None
    return load_json_file(path)


def regular_season_weeks_for(season, default=None):
    """Last regular-season week for `season`.

    The regular/playoff boundary is not a fixed week number. The bracket is
    always the last two fantasy weeks, and how many fantasy weeks a season
    contains varies -- Yahoo stretches any week holding the All-Star break to
    14 days, so a season can cover the same calendar in fewer weeks. Known
    cases: 2019-20 ended at week 19 with no bracket, 2020-21 ran 18 weeks with
    the bracket at 17-18, and 2021-22 ran 22 weeks with the bracket at 21-22.

    Falls back to the current season's value when a season is not listed.
    """
    entry = SEASON_STRUCTURE.get(str(season))
    if isinstance(entry, dict):
        through = entry.get("regular_through")
        if through:
            return int(through)
    return int(REGULAR_SEASON_WEEKS if default is None else default)


def is_regular_season_week(season, week, default=None):
    """True if (season, week) falls in that season's regular season."""
    try:
        return int(week) <= regular_season_weeks_for(season, default)
    except (TypeError, ValueError):
        return False


def resolve_league_key(explicit=None):
    """(league_key, source) for a Yahoo call, or (None, reason) if there is none.

    yahoo.current_league_key is deliberately empty between the season reset
    and Yahoo provisioning the new league -- leaving last season's key there
    would make every script silently pull the wrong season. But an empty key
    still builds a URL: /fantasy/v2/league//settings, which Yahoo rejects.
    A diagnostic that makes that request reads the rejection as a permission
    problem and tells you to rebuild your app, which is what happened.

    So: resolve it explicitly, and say which key is being used and why.
    """
    if explicit:
        return explicit, "passed on the command line"
    if LEAGUE_KEY:
        return LEAGUE_KEY, f"yahoo.current_league_key ({CURRENT_SEASON})"
    if HISTORICAL_LEAGUE_KEYS:
        season = max(HISTORICAL_LEAGUE_KEYS)
        return HISTORICAL_LEAGUE_KEYS[season], (
            f"most recent historical league ({season}) -- "
            "yahoo.current_league_key is empty")
    return None, ("no league key: yahoo.current_league_key is empty and there "
                  "are no historical keys. Pass --league-key.")


def season_had_bracket(season):
    """True if `season` played a postseason bracket (2019-20 did not)."""
    entry = SEASON_STRUCTURE.get(str(season))
    if isinstance(entry, dict) and "bracket" in entry:
        return bool(entry["bracket"])
    return True


# =============================================================================
# SEASON FORMAT (2026-27 onward)
# =============================================================================
# Season keys are "YYYY-YY" and sort correctly as plain strings, which is what
# every _at_or_after comparison below relies on.

def _at_or_after(season, threshold):
    """True if `season` is `threshold` or a later season."""
    if not season or not threshold:
        return False
    return str(season) >= str(threshold)


def uses_three_stage_format(season=None):
    """True if `season` uses the regular / playoffs / cup format.

    Seasons before postseason_format.effective_from played the old shape: a
    single-game, two-week bracket in the final two weeks and nothing after it.
    """
    if season is None:
        season = CURRENT_SEASON
    entry = SEASON_STRUCTURE.get(str(season))
    if isinstance(entry, dict) and entry.get("format"):
        return entry["format"] == POSTSEASON_FORMAT.get("name", "three_stage")
    return _at_or_after(season, POSTSEASON_FORMAT.get("effective_from"))


def _stage(stage):
    return POSTSEASON_FORMAT.get("stages", {}).get(stage, {})


def stage_weeks(season, stage):
    """Inclusive (first_week, last_week) for a stage, or None.

    Stage is "regular_season", "playoffs" or "cup". Returns None when the
    season did not have that stage at all -- every season before 2026-27 has
    no cup, and 2019-20 has no playoffs either.
    """
    season = str(season) if season is not None else CURRENT_SEASON
    entry = SEASON_STRUCTURE.get(season)
    entry = entry if isinstance(entry, dict) else {}

    # A listed season with regular_through explicitly null has no week-level
    # data at all -- 2014-15 and 2015-16 predate Yahoo and survive only as
    # to-date totals in LEAGUEHISTORY.xlsx. Falling back to the current
    # season's week count here would invent a schedule for them.
    if "regular_through" in entry and entry["regular_through"] is None:
        return None

    if stage == "regular_season":
        return (1, regular_season_weeks_for(season))

    if not uses_three_stage_format(season):
        # Legacy shape: the bracket is the two weeks after the regular season,
        # and there is no cup.
        if stage == "cup" or not season_had_bracket(season):
            return None
        last = regular_season_weeks_for(season)
        return (last + 1, last + 2)

    if not season_had_bracket(season) and stage == "playoffs":
        return None
    key = "playoff_weeks" if stage == "playoffs" else "cup_weeks"
    weeks = entry.get(key) or _stage(stage).get("weeks")
    if not weeks:
        return None
    return (int(weeks[0]), int(weeks[-1]))


def phase_for_week(season, week):
    """Which stage (season, week) belongs to: regular_season / playoffs / cup.

    Returns None for a week outside the season entirely.
    """
    try:
        week = int(week)
    except (TypeError, ValueError):
        return None
    for stage in ("regular_season", "playoffs", "cup"):
        span = stage_weeks(season, stage)
        if span and span[0] <= week <= span[1]:
            return stage
    return None


def is_playoff_week(season, week):
    """True if (season, week) is part of the playoff bracket."""
    return phase_for_week(season, week) == "playoffs"


def is_cup_week(season, week):
    """True if (season, week) is part of the Cup."""
    return phase_for_week(season, week) == "cup"


def is_postseason_week(season, week):
    """True for any week after the regular season -- playoffs OR cup.

    Not the same as `not is_regular_season_week(...)`, which is also true for
    a week that falls outside the season altogether.
    """
    return phase_for_week(season, week) in ("playoffs", "cup")


def stage_rounds(season, stage):
    """Concrete rounds for a stage: [{name, weeks: (first, last), ...}].

    Empty when the season has no such stage. Used by the simulators so the
    bracket shape lives in config rather than in module constants.
    """
    span = stage_weeks(season, stage)
    if span is None:
        return []

    if not uses_three_stage_format(season):
        # Legacy shape: one semifinal week then one final week, and the
        # third-place game shares the final week. The new format's round
        # definitions describe six weeks and must not be applied to a season
        # that only ever played two.
        first, last = span
        return [
            {"name": "Semifinals", "weeks": (first, first), "seeds": [[1, 4], [2, 3]]},
            {"name": "Final", "weeks": (last, last), "field": "semifinal winners"},
            {"name": "Third Place", "weeks": (last, last), "field": "semifinal losers"},
        ]

    rounds = []
    for rnd in _stage(stage).get("rounds", []):
        weeks = rnd.get("weeks")
        if not weeks:
            continue
        out = dict(rnd)
        out["weeks"] = (int(weeks[0]), int(weeks[-1]))
        rounds.append(out)
    return rounds


def series_length(season, stage="playoffs"):
    """Weeks per playoff series: 3 under the new format, 1 under the old."""
    if stage == "cup" or not uses_three_stage_format(season):
        return 1
    fmt = _stage(stage).get("series_format", "best_of_1")
    match = re.search(r"(\d+)", str(fmt))
    return int(match.group(1)) if match else 1


# =============================================================================
# KEEPER COUNTS (per season, and NOT necessarily uniform across managers)
# =============================================================================
# Through 2026-27 every manager keeps the same number, so a single scalar
# (league_structure.keepers_per_team) is enough. From 2027-28 the previous
# season's Cup winner keeps one extra, so the count is per manager and the
# draft has a round with three picks in it instead of four. Anything that
# needs a keeper count must go through keepers_for(); the scalar is kept only
# for the current season and for reading old data.

def keeper_rules_for(season=None):
    """The {base, cup_winner_bonus} rule in force for `season`."""
    if season is None:
        season = CURRENT_SEASON
    season = str(season)
    listed = KEEPER_RULES.get("seasons", {})
    if season in listed and isinstance(listed[season], dict):
        rule = listed[season]
    else:
        rule = KEEPER_RULES.get("default", {})
        if not _at_or_after(season, rule.get("effective_from")):
            # Before the default takes effect and not listed: fall back to the
            # uniform scalar, which is how every pre-2027-28 season worked.
            return {"base": int(LEAGUE_STRUCTURE.get("keepers_per_team", 6)),
                    "cup_winner_bonus": 0}
    return {"base": int(rule.get("base", LEAGUE_STRUCTURE.get("keepers_per_team", 6))),
            "cup_winner_bonus": int(rule.get("cup_winner_bonus", 0))}


def cup_winner(season):
    """Who won `season`'s Cup, or None if unplayed/unrecorded."""
    return KEEPER_RULES.get("cup_winners", {}).get(str(season))


def _prior_season(season):
    """"2027-28" -> "2026-27". Returns None if unparseable."""
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(season))
    if not match:
        return None
    start = int(match.group(1)) - 1
    return f"{start}-{(start + 1) % 100:02d}"


def keepers_for(season=None, manager=None):
    """Keeper count for `season`.

    With a manager, returns that manager's count as an int. Without one,
    returns {manager: count} for every manager.

    The bonus goes to whoever won the PREVIOUS season's Cup. If that result is
    not recorded in keeper_rules.cup_winners this does not guess -- everyone
    gets the base count, which will be visibly one short rather than silently
    assigned to the wrong manager.
    """
    if season is None:
        season = CURRENT_SEASON
    rule = keeper_rules_for(season)
    counts = {m: rule["base"] for m in MANAGERS}
    if rule["cup_winner_bonus"]:
        holder = cup_winner(_prior_season(season))
        if holder in counts:
            counts[holder] += rule["cup_winner_bonus"]
    if manager is not None:
        return counts.get(manager, rule["base"])
    return counts


def live_picks_for(season=None, manager=None):
    """Drafted (non-keeper) picks for `season`: TOTAL_ROUNDS - keepers.

    With a manager, an int; without one, {manager: count}. In 2026-27 that is
    9 for everybody; in 2027-28 it is 9 for the Cup winner and 10 for the rest.
    """
    keepers = keepers_for(season, manager)
    if manager is not None:
        return TOTAL_ROUNDS - keepers
    return {m: TOTAL_ROUNDS - k for m, k in keepers.items()}


def first_keeper_round(season=None, manager=None):
    """The first round a manager's keepers occupy (keepers take the LAST rounds).

    2026-27: round 10 for everyone. 2027-28: round 10 for the Cup winner,
    round 11 for the other three.
    """
    picks = live_picks_for(season, manager)
    if manager is not None:
        return picks + 1
    return {m: p + 1 for m, p in picks.items()}


def load_all_matchups(path: Path) -> list:
    """Load historical matchup data from all_matchups.json."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _file_stamp(path: Path):
    """(resolved path, mtime_ns, size) -- the key a parse cache can trust.
    None when the file is not there."""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return (str(Path(path).resolve()), st.st_mtime_ns, st.st_size)


_HISTORICAL_PLAYERLOG_CACHE: dict = {}


def load_historical_playerlog(path: Path) -> list:
    """Load HISTORICAL_PLAYERLOG.json for multi-year keepability scoring.

    CACHED PER PROCESS by (path, mtime, size). The parse is 1.5 s of a 1.7 s
    load_all_data -- 87,181 rows -- and a process that loads the data twice
    paid it twice: the test suite loads it in a dozen fixtures, and a
    backtest or dry-run packet loads it once per simulated week. An edited
    file re-parses, because the stamp changes.

    The rows are read-only everywhere (keepability_v2 and report_builder
    iterate them). The LIST is copied per call so a caller that appends
    cannot reach another caller's data; the row dicts are shared, which is
    why nothing may mutate them in place.
    """
    if not path.exists():
        return []
    stamp = _file_stamp(path)
    hit = _HISTORICAL_PLAYERLOG_CACHE.get(stamp)
    if hit is not None:
        return list(hit)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"  Loaded {len(data):,} rows from HISTORICAL_PLAYERLOG.json")
        if stamp is not None:
            _HISTORICAL_PLAYERLOG_CACHE.clear()      # one season's file at a time
            _HISTORICAL_PLAYERLOG_CACHE[stamp] = data
        return list(data)
    except Exception as e:
        print(f"  WARNING: Failed to load HISTORICAL_PLAYERLOG.json: {e}")
        return []


def load_all_data(
    base_path: str | Path = ".",
    paths: dict[str, str] = None,
    season_year: str = None,
    current_week: int = None,
) -> FantasyData:
    """Load all data files and return a FantasyData container."""
    if season_year is None:
        season_year = CURRENT_SEASON_LONG
    base = Path(base_path)
    file_paths = {**DEFAULT_PATHS, **(paths or {})}

    data = FantasyData(
        playerlog=load_playerlog(base / file_paths["playerlog"]),
        lineups=load_lineups(base / file_paths["lineups"]),
        playerlist=load_playerlist(base / file_paths["playerlist"]),
        leaguehistory=load_leaguehistory(base / file_paths["leaguehistory"]),
        schedule=load_schedule(base / file_paths["schedule"]),
        injury_overrides={"players": []},     # resolved below, once PLAYERLIST is in
        records=load_records(base / file_paths["records"]),
        nba_schedule=load_nba_schedule(base / file_paths["nba_schedule"]),
        league_history_detailed=load_league_history_detailed(
            base / file_paths["league_history_detailed"]
        ),
        all_matchups=load_all_matchups(base / file_paths["all_matchups"]),
        historical_playerlog=load_historical_playerlog(
            base / file_paths["historical_playerlog"]
        ),
        season_year=season_year,
        current_week=current_week or 0,
        base_path=base,
        # frozen to a pre-season snapshot; see load_durability_prior
        durability_prior=load_durability_prior(base),
    )

    data.injury_overrides = resolve_injury_overrides(
        load_injury_overrides(base / file_paths["injury_overrides"]),
        _read_rosters_file(base / "config" / "ROSTERS.json"),
        data.playerlist["player_name"].dropna().tolist()
        if "player_name" in data.playerlist.columns else [])
    _warn_unresolved(data.injury_overrides)

    if current_week is None:
        max_week = data.playerlog["week"].max()
        data.current_week = int(max_week) if pd.notna(max_week) else 0

    return data


def atomic_write_json(path, data, indent: int = 2) -> None:
    """
    Write JSON atomically: dump to a .tmp file in the same directory, then
    os.replace() it over the target. A crash mid-write leaves the original
    file intact instead of corrupting it. (Pattern promoted from
    pull_historical_data._save_json so all cumulative state can share it.)
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent)
    tmp.replace(p)


def save_records(records: dict, path: Path) -> None:
    """Save updated RECORDS.json (atomically -- this is the project's only
    cumulative season history; a partial write here is unrecoverable)."""
    atomic_write_json(path, records)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_position_list(positions_str: str) -> list[str]:
    """Parse a positions string like 'PG,SG,SF' into a list."""
    if pd.isna(positions_str) or not positions_str:
        return []
    return [p.strip().upper() for p in str(positions_str).split(",")]


def classify_position_group(positions) -> str:
    """Classify a player into G, F, or C based on Yahoo position tags."""
    if isinstance(positions, str):
        if pd.isna(positions) or not positions.strip():
            return "F"
        tags = [t.strip().upper() for t in positions.split(",")]
    elif isinstance(positions, (list, tuple)):
        tags = [t.strip().upper() for t in positions if t]
    else:
        return "F"

    if not tags:
        return "F"

    g = sum(1 for t in tags if t in ("PG", "SG"))
    f = sum(1 for t in tags if t in ("SF", "PF"))
    c = sum(1 for t in tags if t == "C")
    mx = max(g, f, c)

    if c == mx and c >= f and c >= g:
        return "C"
    if f == mx and f >= g:
        return "F"
    return "G"


def player_eligible_for_slot(player_positions: list[str], slot: str) -> bool:
    """Check if a player can fill a given slot based on position eligibility."""
    eligible = SLOT_ELIGIBILITY.get(slot.upper(), [])
    return any(pos in eligible for pos in player_positions)


def format_games_count(x) -> str:
    """A games count for prose: '2', or '1.5' when a T makes it a half game.

    The one formatter. The betting preview's games-back lines and the
    standings storyline both render through it, so they cannot drift.
    """
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:.1f}"


def parse_record_string(record_str) -> "Record":
    """'(8-3)' or '(7-7-1)' -> Record. The one record parser.

    It used to return (wins, losses) and read anything with three parts --
    a record with a T -- as (0, 0). Unparseable still gives Record() (0-0).
    """
    parts = str(record_str or "").strip().strip("()").split("-")
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return Record()
    if len(nums) in (2, 3):
        return Record(*nums)
    return Record()


if __name__ == "__main__":
    import sys
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    print(f"Loading data from: {base.absolute()}")
    try:
        data = load_all_data(base)
        for manager in MANAGERS:
            print(f"  {manager}: {data.get_manager_record(manager)}")
    except Exception as e:
        print(f"Error: {e}")
        raise
