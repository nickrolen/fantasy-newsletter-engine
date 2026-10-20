"""
simulator_betting.py

High-fidelity Monte Carlo simulation for next-week betting lines.
Uses full position-aware lineup optimization and granular injury statuses.

Generates: Spread, Over/Under, Moneyline (American odds)
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import NamedTuple, Optional

from .data_loader import FantasyData, MANAGERS, CURRENT_SEASON
from .projections import (
    PlayerProjection,
    TeamProjections,
    load_all_team_projections,
    load_player_projections,
    game_fp_params,
)
import numpy as np

from . import absence, crn
from .data_loader import PlayerIndex
from .lineup_fill import exact_fill
from .lineup_optimizer import (
    AvailablePlayer,
    optimize_lineup,
    STARTER_SLOTS,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_NUM_SIMULATIONS = 5000
SPREAD_GRANULARITY = 0.5  # Round spreads to nearest 0.5

# Injury discount applied to avg scores, spread, and O/U.
# The simulator already accounts for INJURY_OVERRIDES (hard outs) and GTD/O statuses,
# but does NOT model random mid-week injuries (the Wednesday ankle tweak, surprise
# rest days, etc.). The league's season-long non-IL injury rate is ~14.6%, but ~3-4%
# of that is already captured by GTD/O checks at generation time. This discount
# covers the remaining unforeseeable absences.
# Applied to avg_score_a, avg_score_b, spread, and over_under so the displayed
# projections reconcile (spread == adj_avg_a - adj_avg_b, O/U == adj_avg_a +
# adj_avg_b). Moneyline and win probability are NOT adjusted -- they depend on
# relative strength, which a uniform discount does not change.
#
# RECALIBRATION NOTE (June 2026 sampling-engine fix):
# The 0.10 value was originally calibrated against the old sampler (Normal(mu, 0.8*mu)
# truncated at zero), where ~4% of "already modeled" depression was actually
# truncation artifact rather than honest injury modeling. After fixing the sampler
# (std ~= 0.35*mu, no zero floor) the empirical injury component is closer to the full
# 14.6% - 3% GTD/O ~= 11-12% -- so 0.10 remains in the right ballpark. Leaving it
# unchanged here; monitor backtested O/U accuracy and tune to ~0.08-0.12 if the
# new sampler shows a directional bias.
OU_INJURY_DISCOUNT = 0.10  # 10% -- tune up/down if O/U is still biased


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class BettingLine:
    """Betting lines for a single matchup."""
    manager_a: str
    manager_b: str
    
    # Spread (negative = favored)
    spread_a: float  # e.g., -45.5 means A favored by 45.5
    spread_b: float  # e.g., +45.5 means B is underdog by 45.5
    
    # Over/Under
    over_under: float
    
    # Win probabilities
    win_prob_a: float
    win_prob_b: float
    
    # American odds (moneyline)
    moneyline_a: int  # e.g., -150 or +120
    moneyline_b: int
    
    # Simulation stats
    avg_score_a: float = 0.0
    avg_score_b: float = 0.0
    std_dev_a: float = 0.0
    std_dev_b: float = 0.0
    
    # Team names
    team_name_a: str = ""
    team_name_b: str = ""

    # B2 decomposition: avg_score = banked + remaining_mean (discounted).
    # A pre-week line has banked 0.0 and remaining_mean == avg_score.
    banked_a: float = 0.0
    banked_b: float = 0.0
    remaining_mean_a: float = 0.0
    remaining_mean_b: float = 0.0
    projected_final_a: float = 0.0
    projected_final_b: float = 0.0


@dataclass
class PositionalMatchup:
    """Positional breakdown for a matchup."""
    position: str  # "G", "F", or "C"
    
    # Manager A
    manager_a_fp: float
    manager_a_games: float
    manager_a_players: list[str]
    
    # Manager B
    manager_b_fp: float
    manager_b_games: float
    manager_b_players: list[str]
    
    # Advantage
    advantage: str  # Manager name or "Even"
    advantage_margin: float


@dataclass
class MatchupPreview:
    """Complete betting preview for a matchup."""
    week: int
    manager_a: str
    manager_b: str
    team_name_a: str
    team_name_b: str
    
    betting_line: BettingLine
    
    # Season series
    series_a_wins: int
    series_b_wins: int
    
    # Positional matchups
    guard_matchup: PositionalMatchup
    forward_matchup: PositionalMatchup
    center_matchup: PositionalMatchup
    
    # Key players (injury-aware)
    key_player_a: str
    key_player_a_proj: float
    key_player_b: str
    key_player_b_proj: float
    
    # Standings implications
    implications: str
    
    # === Fields with defaults must come last ===
    
    # All-time series
    all_time_a_wins: int = 0
    all_time_b_wins: int = 0
    
    # H2H winning streak
    h2h_streak_holder: str = ""
    h2h_streak_length: int = 0
    h2h_streak_last_loss_season: str = ""
    
    # Injury notes for key players (if applicable)
    key_player_a_injury_note: str = ""
    key_player_b_injury_note: str = ""
    
    # Notable injuries for each team (all significant injuries, not just top player)
    notable_injuries_a: list = field(default_factory=list)
    notable_injuries_b: list = field(default_factory=list)


@dataclass
class WeeklyBettingLines:
    """All betting lines for a week."""
    week: int
    num_simulations: int
    matchup_previews: list[MatchupPreview]


# =============================================================================
# SCHEDULE HELPERS
# =============================================================================

def get_notable_injuries_for_betting(
    manager: str,
    week: int,
    injury_overrides: dict,
    rosters: dict[str, list[str]],
    exclude_season_long: bool = True,
) -> list[dict]:
    """
    Get notable injuries and returns for a manager in a given week.
    
    Args:
        manager: Manager name
        week: Week number to check
        injury_overrides: INJURY_OVERRIDES data dict
        rosters: Dict mapping manager -> list of player names
        exclude_season_long: If True, exclude players out for 18+ weeks (season-long injuries)
    
    Returns:
        List of dicts with 'player', 'notes', and optionally 'status' keys
        Status can be 'out' or 'returning'
    """
    injuries = []
    manager_roster = rosters.get(manager, [])
    
    for player_entry in injury_overrides.get("players", []):
        player_name = player_entry.get("player_name", "")
        out_weeks = player_entry.get("out_weeks", [])
        notes = player_entry.get("notes", "")
        return_week = player_entry.get("return_week")
        return_games = player_entry.get("return_games")
        total_week_games = player_entry.get("total_week_games")
        return_notes = player_entry.get("return_notes", "")
        
        # Check if this player is on the manager's roster
        if player_name not in manager_roster:
            continue
        
        # Check if player is returning this week with partial availability
        if return_week == week and return_games and total_week_games:
            injuries.append({
                "player": player_name,
                "notes": return_notes or notes,
                "status": "returning",
                "return_games": return_games,
                "total_week_games": total_week_games,
            })
            continue
        
        # Check if player is out for this week
        if week not in out_weeks:
            continue
        
        # Optionally exclude season-long injuries (18+ weeks typically means full season)
        if exclude_season_long and len(out_weeks) >= 18:
            continue
        
        injuries.append({
            "player": player_name,
            "notes": notes,
            "status": "out",
        })
    
    return injuries


def get_rosters_from_lineups(lineups_df) -> dict[str, list[str]]:
    """
    Get current rosters, preferring ROSTERS.json over LINEUPS.
    
    Returns dict mapping manager -> list of player names.
    """
    # Try ROSTERS.json first (source of truth for current rosters)
    from pathlib import Path
    import json
    
    rosters_file = Path(__file__).parent.parent / "config" / "ROSTERS.json"
    if rosters_file.exists():
        try:
            with open(rosters_file, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            config_rosters = config_data.get("rosters", config_data)
            # Filter to only manager entries (lists of players)
            rosters = {
                manager: players
                for manager, players in config_rosters.items()
                if isinstance(players, list)
            }
            if rosters:
                return rosters
        except (json.JSONDecodeError, KeyError):
            pass  # Fall through to LINEUPS method
    
    # Fall back to LINEUPS
    max_date = lineups_df['date'].max()
    recent = lineups_df[lineups_df['date'] == max_date]
    
    rosters = {}
    for manager in MANAGERS:
        players = recent[recent['manager'] == manager]['player_name'].unique().tolist()
        rosters[manager] = players
    
    return rosters


def get_next_week_data(data: FantasyData) -> Optional[dict]:
    """Get schedule data for next week."""
    next_week_num = data.current_week + 1
    for week_data in data.schedule.get("weeks", []):
        if week_data["week"] == next_week_num:
            return week_data
    return None


def get_dates_in_week(week_data: dict) -> list[date]:
    """Get all dates within a fantasy week."""
    start = datetime.strptime(week_data["start_date"], "%Y-%m-%d").date()
    end = datetime.strptime(week_data["end_date"], "%Y-%m-%d").date()
    
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    
    return dates


def get_nba_games_on_date(data: FantasyData, game_date: date) -> dict[str, str]:
    """Get NBA games on a date. Returns dict mapping team -> opponent."""
    games_dict = {}
    
    # Use the FantasyData method which handles both schedule formats
    for game in data.get_nba_games_for_date(game_date):
        home = (game.get("home_team") or game.get("home") or "").upper()
        away = (game.get("away_team") or game.get("away") or "").upper()
        if home:
            games_dict[home] = away
        if away:
            games_dict[away] = f"@{home}"
    
    return games_dict


# =============================================================================
# TAG ABSENCES (A2) -- the betting simulators' side of modules/absence.py
# =============================================================================

TAG_GAME_HORIZON_DAYS = 28   # enough calendar to find any team's next 3 games


def tag_week(data: FantasyData) -> Optional[tuple[int, list[date]]]:
    """(week, dates) the Yahoo tags were fetched for: next week."""
    wd = get_next_week_data(data)
    if not wd:
        return None
    return wd["week"], get_dates_in_week(wd)


def _roster_shape(team_projections) -> tuple:
    """Part of every cache key below: catches a roster edited in place.
    The caches assume the NBA schedule and projections are not mutated
    during a run; build new objects instead (load_all_team_projections does)."""
    return tuple((m, id(tp.players), len(tp.players)) for m, tp in sorted(team_projections.items()))


def _playing_teams(data: FantasyData, d: date) -> frozenset:
    """NBA teams with a game on d. Cached on `data`: get_nba_games_for_date
    scans the whole schedule, and the bracket simulators ask thousands of times."""
    cache = data.__dict__.setdefault("_playing_by_date", {})
    hit = cache.get(d)
    if hit is None:
        hit = cache[d] = frozenset(get_nba_games_on_date(data, d))
    return hit


def team_games_from_anchor(data: FantasyData, anchor: date) -> dict[str, list[date]]:
    """team -> its game dates from the anchor, ascending. Cached on `data`
    per anchor: get_nba_games_for_date scans the whole schedule."""
    cache = data.__dict__.setdefault("_absence_team_games", {})
    hit = cache.get(anchor)
    if hit is None:
        hit = {}
        for k in range(TAG_GAME_HORIZON_DAYS):
            d = anchor + timedelta(days=k)
            for team in get_nba_games_on_date(data, d):
                hit.setdefault(team, []).append(d)
        cache[anchor] = hit
    return hit


class KeyedDraws:
    """Common random numbers for n simulations (modules/crn.py).

    Each entity's draws are keyed by (seed, namespace, entity...) and come
    back as one array of n; simulation i reads index i. Nothing depends on
    the order of requests or on what else is simulated. Memoised per key.
    """

    def __init__(self, seed: int, n: int):
        self.seed, self.n = int(seed), int(n)
        self._memo: dict = {}

    def _get(self, kind, namespace, key):
        k = (kind, namespace) + tuple(key)
        hit = self._memo.get(k)
        if hit is None:
            fn = crn.keyed_uniforms if kind == "u" else crn.keyed_normals
            hit = fn(self.seed, namespace, *key, n=self.n)
            hit.flags.writeable = False
            self._memo[k] = hit
        return hit

    def uniforms(self, namespace: str, *key) -> np.ndarray:
        return self._get("u", namespace, key)

    def normals(self, namespace: str, *key) -> np.ndarray:
        return self._get("z", namespace, key)

    def uniforms_many(self, namespace: str, keys) -> np.ndarray:
        """[n, len(keys)]: column j is uniforms(namespace, *keys[j])."""
        return np.stack([self._get("u", namespace, k) for k in keys], axis=1)

    def normals_many(self, namespace: str, keys) -> np.ndarray:
        return np.stack([self._get("z", namespace, k) for k in keys], axis=1)


class TagBlock(NamedTuple):
    """One tagged player's absence, all simulations at once.

    games: his team's first MAX_TAG_GAMES games from the tag's anchor.
    start: how many of those were already resolved (observed) before the
           simulated window -- B2's as-of truncation; 0 for a full week.
    k:     per simulation, how many MORE games he misses from games[start].
    """
    games: list
    k: np.ndarray
    start: int = 0
    basis: str = "full chain"

    def missed(self, d: date):
        """bool over simulations, or None if d is not an open chain game."""
        if d not in self.games:
            return None
        i = self.games.index(d)
        if i < self.start:
            return None
        return self.k > (i - self.start)


def tag_blocks(
    data: FantasyData,
    team_projections: dict[str, TeamProjections],
    injury_statuses: dict = None,
    draws=None,
    tag_anchor: date = None,
    anchors: dict = None,
    tag_week_info: tuple = None,
    observed: dict = None,
    as_of: date = None,
) -> dict[str, TagBlock]:
    """player -> TagBlock.

    One draw per tagged player per simulation, keyed ("absence", player,
    anchor) -- the same key marginal_value uses, so the two engines agree on
    who is hurt for a given seed. He misses the first k of his games from
    the anchor. Precedence: an INJURY_OVERRIDES entry touching the tag's
    week suppresses the tag. An unmodelled tag raises.

    B2 (as-of re-simulation):
      anchors:       player -> his tag's anchor date (default: tag_anchor,
                     else the first day of the tag week). An UNCHANGED tag
                     keeps its original anchor; a fresh one is re-anchored
                     by the caller (week_state.reconcile_tags).
      tag_week_info: (week, dates) the tags belong to. Pass it mid-week:
                     the default reads data.current_week + 1, and
                     load_all_data advances current_week as soon as the
                     week's first log rows land.
      observed, as_of: player -> {date: played} from the logs (WeekState),
                     and the date the window starts. His chain games before
                     as_of are resolved; if the log has every one of them the
                     chain is CONDITIONED on them (same uniform,
                     absence.missed_distribution(tag, observed)), so a
                     player who sat Monday and Tuesday is not charged those
                     games again and one who played is healthy. If any is
                     missing from the log (e.g. he was not rostered) he is
                     not observed: the unconditional block, of which only the
                     games still to come are simulated. TagBlock.basis says
                     which.
    """
    if not injury_statuses:
        return {}
    obs_idx = PlayerIndex(observed or {})
    out = {}
    for name, tag, (games, anchor) in _tagged_players(
            data, team_projections, injury_statuses, tag_anchor, anchors, tag_week_info):
        resolved = [g for g in games if as_of is not None and g < as_of]
        log = obs_idx.get(name) or {}
        if not resolved:
            obs, basis = (), "full chain"
        elif all(g in log for g in resolved):
            obs = tuple(bool(log[g]) for g in resolved)
            basis = "conditioned on " + ", ".join(
                f"{g.isoformat()} {'played' if v else 'missed'}" for g, v in zip(resolved, obs))
        else:
            obs, basis = (), "not observed in the logs: unconditional block"
        k = absence.missed_from_uniform(draws.uniforms("absence", name, anchor), tag, obs)
        out[name] = TagBlock(games, np.asarray(k), len(obs), basis)
    return out


def _tagged_players(data, team_projections, injury_statuses, tag_anchor,
                    anchors=None, tag_week_info=None):
    """[(name, chain tag, (his games from the anchor, anchor))] -- everything
    about the tags that is not random. Cached on `data` by the identity of
    the inputs: every week and every matchup of a run asks the same question,
    and resolving names through PlayerIndex each time cost more than simulating.
    """
    cache = data.__dict__.setdefault("_tagged_players", {})
    anchors = anchors or {}
    key = (id(team_projections), id(injury_statuses), len(injury_statuses), tag_anchor,
           _roster_shape(team_projections), tuple(sorted((str(k), v) for k, v in anchors.items())),
           None if tag_week_info is None else (tag_week_info[0], tuple(tag_week_info[1])))
    hit = cache.get(key)
    if hit is not None and hit[0] is team_projections and hit[1] is injury_statuses:
        return hit[2]
    statuses = injury_statuses if isinstance(injury_statuses, PlayerIndex) else PlayerIndex(injury_statuses)
    absence.check_tags(statuses, [n for tp in team_projections.values() for n in tp.players])
    tw = tag_week_info if tag_week_info is not None else tag_week(data)
    anchor_idx = PlayerIndex(anchors)
    if tag_anchor is None and tw is None and not anchors:
        tagged = [n for tp in team_projections.values() for n in tp.players
                  if n in statuses and absence.chain_tag(statuses[n])]
        if tagged:
            raise ValueError(f"tags for {tagged} but no next week to anchor them to; pass tag_anchor")
        cache[key] = (team_projections, injury_statuses, [])
        return []
    default_anchor = tag_anchor or (tw[1][0] if tw is not None else None)
    out = []
    for tp in team_projections.values():
        for name, player in tp.players.items():
            if name not in statuses:
                continue
            tag = absence.chain_tag(statuses[name])
            if tag is None:
                continue
            anchor = anchor_idx.get(name, default_anchor)
            if anchor is None:
                raise ValueError(f"{name} is tagged {statuses[name]} but has no anchor date")
            if tw is not None and (anchor in tw[1] or tag_week_info is not None):
                t_week, t_dates = tw
            else:
                t_week, t_dates = None, [anchor]
            if absence.tag_suppressed(t_week, t_dates, player.out_weeks,
                                      player.return_week, player.out_from):
                continue
            games = team_games_from_anchor(data, anchor)
            team_games = games.get(player.nba_team.upper(), [])[:absence.MAX_TAG_GAMES]
            out.append((name, tag, (team_games, anchor)))
    cache[key] = (team_projections, injury_statuses, out)
    return out


# =============================================================================
# SIMULATION CORE
# =============================================================================

def _position_group(positions) -> str:
    if any(p in positions for p in ["PG", "SG"]):
        return "G"
    if any(p in positions for p in ["SF", "PF"]):
        return "F"
    return "C"


def _eligible(player, week: int, game_date: date, week_start_date: date) -> bool:
    """Deterministic availability: INJURY_OVERRIDES steps 1-2 and projection."""
    # 1. hard outs: out_weeks (whole week) and out_from (on/after, within its week)
    if week in player.out_weeks:
        return False
    if absence.out_from_applies(game_date, week_start_date, player.out_from):
        return False
    # Skip players with 0 projection (injured/inactive)
    if player.projected_fppg <= 0:
        return False
    # 2. partial return with a date: out before it
    if player.return_week == week and player.return_date:
        if game_date < datetime.strptime(player.return_date, "%Y-%m-%d").date():
            return False
    return True


def _week_plan(data, team_projections, week_data, managers):
    """Everything about a simulated week that is not random, per manager:
    [(date, [(name, mean, std, group, return_rate or None, positions,
    projected_fppg), ...]), ...] with players in projection order. Cached on
    `data` by the identity of the projections.
    """
    cache = data.__dict__.setdefault("_week_plans", {})
    key = (id(team_projections), week_data["week"], week_data.get("start_date"), tuple(managers),
           _roster_shape(team_projections))
    hit = cache.get(key)
    if hit is not None and hit[0] is team_projections:
        return hit[1]
    week_num = week_data["week"]
    dates = get_dates_in_week(week_data)
    week_start_date = dates[0] if dates else None
    plan = {}
    for manager in managers:
        ordered = sorted(team_projections[manager].players.values(), key=lambda p: -p.projected_fppg)
        days = []
        for game_date in dates:
            playing = _playing_teams(data, game_date)
            entries = []
            for player in ordered:
                if player.nba_team.upper() not in playing:
                    continue
                if not _eligible(player, week_num, game_date, week_start_date):
                    continue
                rate = None
                # 2b. partial return without a date: pro-rated, drawn per game
                if (player.return_week == week_num and not player.return_date
                        and player.return_games and player.total_week_games):
                    rate = player.return_games / player.total_week_games
                mean, std = game_fp_params(player)
                entries.append((player.player_name, mean, std,
                                _position_group(player.positions), rate,
                                frozenset(player.positions or ()), float(player.projected_fppg)))
            days.append((game_date, entries))
        plan[manager] = days
    cache[key] = (team_projections, plan)
    return plan


def legal_starters(avail: np.ndarray, entries: list, fills: dict) -> np.ndarray:
    """[n, width] bool: who starts, per simulation, as the legal optimal fill.

    A4. A day's lineup depends only on WHO is available (positions and
    projections are fixed), and with availability near 0.9 the distinct
    availability rows are far fewer than the simulations. So: pack each row
    into an integer, np.unique, run lineup_fill.exact_fill once per distinct
    pattern (memoised in `fills` across days, weeks and calls), and scatter
    the starter rows back through the inverse index. The fill weighs players
    by projected_fppg -- start/sit is decided on projections, before the
    game -- which is also the order the plan lists them in, so ties break the
    same way they always have.
    """
    n, width = avail.shape
    if width == 0:
        return avail
    if width > 62:
        raise ValueError(f"{width} players available on one day; the pattern key packs at most 62")
    keys = avail.astype(np.int64) @ (np.int64(1) << np.arange(width, dtype=np.int64))
    uniq, inverse = np.unique(keys, return_inverse=True)
    rows = np.zeros((len(uniq), width), dtype=bool)
    for u, key in enumerate(uniq):
        idx = [j for j in range(width) if (int(key) >> j) & 1]
        players = tuple((entries[j][0], entries[j][5], entries[j][6]) for j in idx)
        started = fills.get(players)
        if started is None:
            started = frozenset(exact_fill(players)[0])
            fills[players] = started
        for j in idx:
            if entries[j][0] in started:
                rows[u, j] = True
    return rows[inverse.reshape(-1)]


def simulate_week_matrix(
    data: FantasyData,
    team_projections: dict[str, TeamProjections],
    week_data: dict,
    injury_statuses: dict = None,
    draws=None,
    tag_anchor: date = None,
    managers=None,
    from_date: date = None,
    anchors: dict = None,
    tag_week_info: tuple = None,
    observed: dict = None,
) -> dict[str, dict]:
    """
    Simulate one fantasy week, all `draws.n` simulations at once.

    from_date (B2): simulate only the days on or after it -- the remainder.
    Every draw keeps its key (player, date), so a remainder is literally the
    full week's draws restricted to the remaining days: from_date = the
    week's first day is bit-identical to the full week, and nothing that
    happened before from_date can move a remaining draw. Team noise is
    scaled by sqrt(remaining NBA game-days / the week's NBA game-days) --
    variance in proportion to the week left; 1.0 for a full week, 0 for an
    empty remainder. anchors / tag_week_info / observed: see tag_blocks.

    Returns manager -> {"score", "games", "G", "F", "C"}, each an array of
    length n. Per day, per manager: the players eligible today in projection
    order; a per-simulation availability mask (return_games pro-rating, the
    A2 tag block); starters = the optimal LEGAL lineup of the available
    players (lineup_fill.exact_fill: PG SG G SF PF F C C UTIL UTIL, most
    starters then most projected points -- A4), solved once per distinct
    availability pattern (legal_starters); points = keyed normal draws on
    game_fp_params. Then team noise, floored at zero.

    With KeyedDraws every number here is keyed by entity, so a manager's
    week depends only on his own roster -- never on another roster, the
    order matchups are priced in, or what else is asked.

    injury_statuses are Yahoo tags as of tag_anchor (default: the first day
    of next week, the week they were fetched for). A tag costs a block of
    the player's first games from the anchor, so a playoff or Cup week
    months away is rightly untouched by today's tag.
    """
    dates = get_dates_in_week(week_data)
    week_start_date = dates[0] if dates else None
    managers = list(managers or MANAGERS)
    n = draws.n
    blocks = tag_blocks(data, team_projections, injury_statuses, draws, tag_anchor,
                        anchors, tag_week_info, observed, from_date)
    plan = _week_plan(data, team_projections, week_data, managers)
    noise_scale = remaining_noise_scale(data, dates, from_date)
    fills = data.__dict__.setdefault("_lineup_fills", {})

    results = {}
    for manager in managers:
        team_proj = team_projections[manager]
        res = {k: np.zeros(n) for k in ("score", "games", "G", "F", "C")}
        days = [(d, e) for d, e in plan[manager] if e and (from_date is None or d >= from_date)]
        game_keys = [(e[0], d) for d, es in days for e in es]
        z_all = draws.normals_many("game", game_keys) if game_keys else None
        rate_keys = [(e[0], d) for d, es in days for e in es if e[4] is not None]
        u_rate = dict(zip(rate_keys, draws.uniforms_many("avail", rate_keys).T)) if rate_keys else {}
        col = 0
        for game_date, entries in days:
            width = len(entries)
            avail = np.ones((n, width), dtype=bool)
            mean = np.empty(width)
            std = np.empty(width)
            for j, (name, mu, sd, _g, rate, _pos, _w) in enumerate(entries):
                mean[j], std[j] = mu, sd
                if rate is not None:
                    avail[:, j] &= u_rate[(name, game_date)] <= rate
                blk = blocks.get(name)
                out_today = blk.missed(game_date) if blk is not None else None
                if out_today is not None:
                    avail[:, j] &= ~out_today
            fp = np.where(mean > 0, mean + std * z_all[:, col:col + width], 0.0)
            col += width
            starters = legal_starters(avail, entries, fills)
            day_pts = starters * fp
            res["score"] += day_pts.sum(axis=1)
            res["games"] += starters.sum(axis=1)
            for g in ("G", "F", "C"):
                sel = [j for j, e in enumerate(entries) if e[3] == g]
                if sel:
                    res[g] += day_pts[:, sel].sum(axis=1)
        # Add team-level variance
        if week_start_date is not None:
            noise = draws.normals("noise", manager, week_start_date) * team_proj.weekly_std_dev * 0.15
            if noise_scale != 1.0:
                noise = noise * noise_scale
            res["score"] = np.maximum(0.0, res["score"] + noise)
        results[manager] = res
    return results


def remaining_noise_scale(data: FantasyData, dates: list, from_date: date = None) -> float:
    """sqrt(share of the week's NBA game-days on or after from_date).
    Exactly 1.0 for a full week (bit-identity with the pre-week line)."""
    if from_date is None or not dates or from_date <= dates[0]:
        return 1.0
    game_days = [d for d in dates if _playing_teams(data, d)]
    if not game_days:
        return 0.0
    left = sum(1 for d in game_days if d >= from_date)
    return (left / len(game_days)) ** 0.5


def schedule_week(data: FantasyData, week: int) -> dict:
    """SCHEDULE.json's entry for `week`, WITHOUT its matchups.

    A simulated week does not depend on who plays whom (simulate_week_matrix
    never reads matchups), and the bracket simulators' later-round pairings
    differ per iteration -- so a precomputed week must not carry a pairing
    it cannot honour. Raises if the week is not in the schedule.
    """
    for w in data.schedule.get("weeks", []):
        if int(w["week"]) == int(week):
            out = {k: v for k, v in w.items() if k != "matchups"}
            out["week"] = int(week)
            return out
    raise KeyError(f"week {week} is not in SCHEDULE.json; cannot simulate it")


def week_score_matrices(
    data: FantasyData,
    team_projections: dict[str, TeamProjections],
    weeks,
    injury_statuses: dict = None,
    seed: int = None,
    num_simulations: int = DEFAULT_NUM_SIMULATIONS,
    tag_anchor: date = None,
) -> dict[int, dict[str, np.ndarray]]:
    """{week: {manager: scores[n]}} -- one keyed simulation of each week.

    The playoff and Cup simulators precompute their weeks here once and read
    simulation i at index i, instead of re-simulating a week per iteration.

    ONE WEEK, ONE SIMULATED TRUTH (Nick, 10-20): the draws are keyed by the
    week's own entities and dates (crn.py), never by which competition is
    asking. So week W here at n = 10,000 is, column for column, the same week
    a betting line prices at n = 5,000 with the same seed -- the line is this
    matrix's first 5,000 columns (keyed streams are prefix-stable). A test
    asserts it.
    """
    if seed is None:
        raise ValueError("week_score_matrices needs an explicit seed")
    draws = KeyedDraws(seed, num_simulations)
    out = {}
    for w in weeks:
        wd = schedule_week(data, w)
        assert "matchups" not in wd
        res = simulate_week_matrix(data, team_projections, wd, injury_statuses, draws,
                                   tag_anchor, managers=MANAGERS)
        out[int(w)] = {m: res[m]["score"] for m in MANAGERS}
    return out


def scores_at(matrices: dict, i: int) -> dict[int, dict[str, float]]:
    """Simulation i of every precomputed week: {week: {manager: score}}."""
    return {w: {m: float(v[i]) for m, v in ms.items()} for w, ms in matrices.items()}


def _games(x) -> str:
    """A games-back count: '2', or '1.5' with a half game from a T."""
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:.1f}"


def matchup_id(manager_a: str, manager_b: str) -> str:
    """Order-free name for a pairing: the tie key must not depend on who is 'A'."""
    return "|".join(sorted((manager_a, manager_b)))


def run_matchup_simulation(
    data: FantasyData,
    team_projections: dict[str, TeamProjections],
    week_data: dict,
    manager_a: str,
    manager_b: str,
    num_simulations: int = DEFAULT_NUM_SIMULATIONS,
    injury_statuses: dict[str, str] = None,
    seed: int = None,
    week_results: dict = None,
) -> BettingLine:
    """
    Run Monte Carlo simulation for a single matchup.

    Draws are keyed (KeyedDraws(seed, num_simulations)), so this line
    depends only on the two rosters, the tags and the seed. seed=None takes
    one from the global `random` stream. week_results, if given, is
    simulate_week_matrix's output for the same seed and n (a cache: the
    answer is identical either way).

    Returns BettingLine with spread, O/U, and moneylines.
    """
    if seed is None:
        raise ValueError("run_matchup_simulation needs an explicit seed: one seed per run, chosen by the caller (generate_stats_report picks it) so every simulator prices the same week from the same draws")
    draws = KeyedDraws(seed, num_simulations)
    if week_results is None:
        week_results = simulate_week_matrix(data, team_projections, week_data, injury_statuses,
                                            draws, managers=[manager_a, manager_b])
    scores_a = week_results[manager_a]["score"]
    scores_b = week_results[manager_b]["score"]
    assert len(scores_a) == len(scores_b) == num_simulations

    return line_from_scores(manager_a, manager_b, scores_a, scores_b, draws, week_data["week"])


def line_from_scores(
    manager_a: str,
    manager_b: str,
    scores_a: np.ndarray,
    scores_b: np.ndarray,
    draws,
    week: int,
    banked_a: float = 0.0,
    banked_b: float = 0.0,
) -> BettingLine:
    """A BettingLine from simulated (remaining) scores plus banked points.

    Win probability is read off the TOTAL (banked + simulated): banked is a
    constant, so it shifts the distribution and does not widen it. The
    injury discount applies to the simulated part only -- banked points
    already happened. With banked = 0 this is the pre-week line exactly.
    """
    n = len(scores_a)
    assert len(scores_b) == n
    total_a = scores_a + banked_a
    total_b = scores_b + banked_b

    # Tie convention (project-wide): coin flip for SIMULATED ties so
    # the probability is statistically honest. This also handles the
    # degenerate all-zero week (both teams scored 0 -- e.g., no NBA
    # games in the simulated window), which would otherwise award
    # every simulation to manager_b and produce a 0%/100% line.
    # Keyed by the unordered pairing, so swapping A and B flips nothing.
    first = sorted((manager_a, manager_b))[0]
    coin = draws.uniforms("tie", matchup_id(manager_a, manager_b), week) < 0.5
    a_wins_tie = coin if manager_a == first else ~coin
    tie = total_a == total_b
    wins_a = int(((total_a > total_b) | (tie & a_wins_tie)).sum())
    wins_b = n - wins_a

    std_a = float(total_a.std())
    std_b = float(total_b.std())

    # Win probabilities
    win_prob_a = wins_a / n
    win_prob_b = wins_b / n

    # Apply injury discount to the SIMULATED points. This accounts for random
    # mid-week injuries not captured by INJURY_OVERRIDES or GTD/O statuses.
    # The discount is applied to BOTH the spread AND the O/U (and to the
    # displayed avg_score_{a,b}) so the displayed projections reconcile:
    # spread == adj_avg_a - adj_avg_b, O/U == adj_avg_a + adj_avg_b.
    # Moneyline and win probability are not adjusted -- they depend on
    # relative strength, which a uniform discount does not change.
    rem_a = float(scores_a.mean()) * (1 - OU_INJURY_DISCOUNT)
    rem_b = float(scores_b.mean()) * (1 - OU_INJURY_DISCOUNT)
    adj_avg_a = banked_a + rem_a
    adj_avg_b = banked_b + rem_b

    # Spread (difference in DISCOUNTED projected scores)
    # Negative spread = favored (expected to win by that many points).
    # If A scores more on average, A is favored, so spread_a should be negative.
    raw_spread = adj_avg_a - adj_avg_b  # Positive if A scores more
    spread_a = -round(raw_spread / SPREAD_GRANULARITY) * SPREAD_GRANULARITY  # Negate: higher score = negative spread
    spread_b = -spread_a

    # Over/Under (uses discounted avg scores)
    over_under = round((adj_avg_a + adj_avg_b) / 10) * 10  # Round to nearest 10

    # Moneylines
    moneyline_a = probability_to_american_odds(win_prob_a)
    moneyline_b = probability_to_american_odds(win_prob_b)

    # Get team names
    from .data_loader import MANAGER_TO_TEAM
    team_name_a = MANAGER_TO_TEAM.get(manager_a, manager_a)
    team_name_b = MANAGER_TO_TEAM.get(manager_b, manager_b)

    return BettingLine(
        manager_a=manager_a,
        manager_b=manager_b,
        spread_a=spread_a,
        spread_b=spread_b,
        over_under=over_under,
        win_prob_a=win_prob_a * 100,
        win_prob_b=win_prob_b * 100,
        moneyline_a=moneyline_a,
        moneyline_b=moneyline_b,
        avg_score_a=adj_avg_a,
        avg_score_b=adj_avg_b,
        std_dev_a=std_a,
        std_dev_b=std_b,
        team_name_a=team_name_a,
        team_name_b=team_name_b,
        banked_a=banked_a,
        banked_b=banked_b,
        remaining_mean_a=rem_a,
        remaining_mean_b=rem_b,
        projected_final_a=adj_avg_a,
        projected_final_b=adj_avg_b,
    )


class DecidedTie(RuntimeError):
    """A week with nothing left to play and identical banked totals."""


@dataclass
class RemainderResult:
    week: int
    as_of: date
    seed: int
    num_simulations: int
    lines: list                 # BettingLine per matchup, decomposition filled
    remaining: dict             # manager -> simulate_week_matrix arrays
    tag_blocks: dict            # player -> TagBlock (basis says how it was drawn)


def simulate_week_remainder(
    data: FantasyData,
    team_projections: dict[str, TeamProjections],
    week_data: dict,
    state,
    seed: int,
    num_simulations: int = DEFAULT_NUM_SIMULATIONS,
    injury_statuses: dict = None,
    anchors: dict = None,
) -> RemainderResult:
    """B2: the as-of line. Banked from the logs, the rest simulated.

        spread_a = (banked_a - banked_b) + E[remaining_a - remaining_b]

    `state` is week_state.week_state(data, week, as_of). Only days on or
    after state.as_of are simulated, with the SAME keyed draws as the full
    week (so as_of = the first day reproduces the pre-week line exactly, and
    no completed day's result can move a remaining draw). Tags: `anchors`
    from week_state.reconcile_tags, chains conditioned on what the logs saw.
    seed is required: a live line that changes seed between refreshes moves
    for no reason.

    Starters are legal lineups (A4), the same fill as the pre-week line.
    """
    if seed is None:
        raise ValueError("simulate_week_remainder needs an explicit seed")
    week = int(week_data["week"])
    if state.week != week:
        raise ValueError(f"state is for week {state.week}, week_data for week {week}")
    dates = get_dates_in_week(week_data)
    draws = KeyedDraws(seed, num_simulations)
    tw = (week, dates)
    rem = simulate_week_matrix(data, team_projections, week_data, injury_statuses, draws,
                               from_date=state.as_of, anchors=anchors, tag_week_info=tw,
                               observed=state.observed)
    blocks = tag_blocks(data, team_projections, injury_statuses, draws, None, anchors, tw,
                        state.observed, state.as_of)
    lines = []
    for m in week_data.get("matchups", []):
        a, b = m["manager_a"], m["manager_b"]
        ra, rb = rem[a]["score"], rem[b]["score"]
        ba, bb = state.banked[a], state.banked[b]
        if not ra.any() and not rb.any() and ba == bb and not state.remaining:
            raise DecidedTie(f"week {week} is over and {a} and {b} are tied at {ba}: a regular-season "
                             "tie counts as neither win nor loss -- there is no line to publish")
        lines.append(line_from_scores(a, b, ra, rb, draws, week, ba, bb))
    return RemainderResult(week=week, as_of=state.as_of, seed=seed,
                           num_simulations=num_simulations, lines=lines,
                           remaining=rem, tag_blocks=blocks)


# =============================================================================
# ODDS CONVERSION
# =============================================================================

def probability_to_american_odds(prob: float) -> int:
    """Convert win probability to American odds."""
    if prob <= 0:
        return 10000  # Max underdog
    if prob >= 1:
        return -10000  # Max favorite
    
    if prob >= 0.5:
        # Favorite: negative odds
        odds = -100 * prob / (1 - prob)
        return int(round(odds / 5) * 5)  # Round to nearest 5
    else:
        # Underdog: positive odds
        odds = 100 * (1 - prob) / prob
        return int(round(odds / 5) * 5)


def format_american_odds(odds: int) -> str:
    """Format American odds with +/- prefix."""
    if odds >= 0:
        return f"+{odds}"
    return str(odds)


# =============================================================================
# POSITIONAL ANALYSIS
# =============================================================================

def analyze_positional_matchup(
    team_a: TeamProjections,
    team_b: TeamProjections,
    position: str,
    manager_a: str,
    manager_b: str,
    week: int = None,
) -> PositionalMatchup:
    """
    Analyze positional matchup between two teams.
    
    Args:
        team_a, team_b: Team projections
        position: "G", "F", or "C"
        manager_a, manager_b: Manager names
        week: Week number for injury filtering (optional)
    """
    pos_map = {
        "G": ["PG", "SG"],
        "F": ["SF", "PF"],
        "C": ["C"],
    }
    eligible_positions = pos_map.get(position, [])
    
    def get_position_players(team: TeamProjections) -> tuple[float, list[str]]:
        total_fp = 0.0
        players = []
        for player in team.players.values():
            # Skip injured players if week is provided
            if week is not None and week in player.out_weeks:
                continue
            if any(p in eligible_positions for p in player.positions):
                total_fp += player.projected_fppg
                players.append(player.player_name)
        return total_fp, players
    
    fp_a, players_a = get_position_players(team_a)
    fp_b, players_b = get_position_players(team_b)
    
    margin = fp_a - fp_b
    if abs(margin) < 5:
        advantage = "Even"
    elif margin > 0:
        advantage = manager_a
    else:
        advantage = manager_b
    
    return PositionalMatchup(
        position=position,
        manager_a_fp=fp_a,
        manager_a_games=len(players_a),
        manager_a_players=players_a[:3],  # Top 3
        manager_b_fp=fp_b,
        manager_b_games=len(players_b),
        manager_b_players=players_b[:3],
        advantage=advantage,
        advantage_margin=abs(margin),
    )


def get_key_player(team: TeamProjections, week: int = None) -> tuple[str, float, str]:
    """
    Get the highest projected AVAILABLE player on a team.
    
    Args:
        team: Team projections
        week: Week number to check for injuries. If provided, players
              with this week in their out_weeks will be skipped.
    
    Returns:
        Tuple of (player_name, projected_fppg, injury_note)
        injury_note is non-empty if the top projected player is injured
        and we're returning their replacement instead.
    """
    best = None
    best_fp = 0
    injury_note = ""
    
    # First, find the theoretical best player (ignoring injuries)
    theoretical_best = None
    theoretical_best_fp = 0
    for player in team.players.values():
        if player.projected_fppg > theoretical_best_fp:
            theoretical_best_fp = player.projected_fppg
            theoretical_best = player
    
    # Now find the best AVAILABLE player
    for player in team.players.values():
        # Skip if injured this week
        if week is not None and week in player.out_weeks:
            continue
        # Skip players with 0 projection
        if player.projected_fppg <= 0:
            continue
        if player.projected_fppg > best_fp:
            best_fp = player.projected_fppg
            best = player.player_name
    
    # If the theoretical best is different from actual best, note the injury
    if theoretical_best and best and theoretical_best.player_name != best:
        if week is not None and week in theoretical_best.out_weeks:
            injury_note = f"{theoretical_best.player_name} (injured)"
    
    return (best or "N/A", best_fp, injury_note)


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def generate_weekly_betting_lines(
    data: FantasyData,
    num_simulations: int = DEFAULT_NUM_SIMULATIONS,
    injury_statuses: dict[str, str] = None,
    seed: int = None,
) -> Optional[WeeklyBettingLines]:
    """
    Generate betting lines for next week's matchups.
    
    Args:
        data: FantasyData container
        num_simulations: Number of simulations per matchup
        injury_statuses: Player -> injury status mapping
        seed: Random seed for reproducibility
    
    Returns:
        WeeklyBettingLines or None if no next week
    """
    if seed is None:
        raise ValueError("generate_weekly_betting_lines needs an explicit seed: one seed per run, chosen by the caller (generate_stats_report picks it) so every simulator prices the same week from the same draws")
    # One keyed seed for every draw this week (modules/crn.py). With a fixed
    # seed the lines are fixed; they no longer depend on matchup order.
    draw_seed = seed
    
    # Get next week schedule
    week_data = get_next_week_data(data)
    if not week_data:
        return None
    
    week_num = week_data["week"]
    
    # Load projections
    team_projections = load_all_team_projections(data)
    
    # Get H2H records
    h2h_data = data.records.get("h2h_season", {})
    
    # Get rosters for notable injuries lookup
    rosters = get_rosters_from_lineups(data.lineups)
    
    previews = []
    # Simulate the week once for every manager; each matchup reads it.
    week_results = simulate_week_matrix(data, team_projections, week_data, injury_statuses,
                                        KeyedDraws(draw_seed, num_simulations))
    
    for matchup_def in week_data["matchups"]:
        manager_a = matchup_def["manager_a"]
        manager_b = matchup_def["manager_b"]
        
        # Run simulation
        betting_line = run_matchup_simulation(
            data,
            team_projections,
            week_data,
            manager_a,
            manager_b,
            num_simulations,
            injury_statuses,
            seed=draw_seed,
            week_results=week_results,
        )
        
        # Get season series
        series_key = f"{manager_a}_vs_{manager_b}"
        alt_key = f"{manager_b}_vs_{manager_a}"
        
        series_a_wins = 0
        series_b_wins = 0
        
        if series_key in h2h_data:
            series_a_wins = h2h_data[series_key].get(manager_a.lower(), 0)
            series_b_wins = h2h_data[series_key].get(manager_b.lower(), 0)
        elif alt_key in h2h_data:
            series_a_wins = h2h_data[alt_key].get(manager_a.lower(), 0)
            series_b_wins = h2h_data[alt_key].get(manager_b.lower(), 0)
        
        # Get all-time series
        all_time_h2h = data.records.get("all_time", {}).get("h2h", {})
        all_time_key = f"{min(manager_a, manager_b)}_vs_{max(manager_a, manager_b)}"
        all_time_record = all_time_h2h.get(all_time_key, {})
        all_time_a_wins = all_time_record.get(manager_a.lower(), 0)
        all_time_b_wins = all_time_record.get(manager_b.lower(), 0)
        
        # Get H2H winning streak from historical matchups
        from .records_tracker import get_h2h_streak
        current_season_h2h = data.records.get("h2h_season", {})
        weekly_scores = data.records.get("weekly_scores", {})
        h2h_streak = get_h2h_streak(
            data.all_matchups, 
            manager_a, 
            manager_b,
            current_season=data.records.get("season_records", {}).get("season", CURRENT_SEASON),
            current_season_h2h=current_season_h2h,
            weekly_scores=weekly_scores,
            schedule=data.schedule
        )
        h2h_streak_holder = h2h_streak.get("streak_holder", "")
        h2h_streak_length = h2h_streak.get("streak_length", 0)
        h2h_streak_last_loss_season = h2h_streak.get("last_loss_season", "")
        
        # Positional matchups (now injury-aware)
        guard_matchup = analyze_positional_matchup(
            team_projections[manager_a],
            team_projections[manager_b],
            "G", manager_a, manager_b,
            week=week_num
        )
        forward_matchup = analyze_positional_matchup(
            team_projections[manager_a],
            team_projections[manager_b],
            "F", manager_a, manager_b,
            week=week_num
        )
        center_matchup = analyze_positional_matchup(
            team_projections[manager_a],
            team_projections[manager_b],
            "C", manager_a, manager_b,
            week=week_num
        )
        
        # Key players (now injury-aware)
        key_a, key_a_proj, injury_note_a = get_key_player(team_projections[manager_a], week=week_num)
        key_b, key_b_proj, injury_note_b = get_key_player(team_projections[manager_b], week=week_num)
        
        # Standings implications
        # Standings value, a T as half a win: the gap can be a half game.
        wins_a = data.get_manager_record(manager_a).standing
        wins_b = data.get_manager_record(manager_b).standing
        
        gap = abs(wins_a - wins_b)
        if wins_a > wins_b:
            # manager_a is ahead; if manager_b loses, they'd be gap+1 games back
            games_back = _games(gap + 1)
            implications = f"A {manager_b} loss would put them {games_back} games back of {manager_a}."
        elif wins_b > wins_a:
            # manager_b is ahead; if manager_a loses, they'd be gap+1 games back
            games_back = _games(gap + 1)
            implications = f"A {manager_a} loss would put them {games_back} games back of {manager_b}."
        else:
            # Tied record
            implications = f"Winner takes the tiebreaker advantage."
        
        # Get team names
        from .data_loader import MANAGER_TO_TEAM
        team_name_a = MANAGER_TO_TEAM.get(manager_a, manager_a)
        team_name_b = MANAGER_TO_TEAM.get(manager_b, manager_b)
        
        # Get notable injuries for each team
        notable_injuries_a = get_notable_injuries_for_betting(
            manager_a, week_num, data.injury_overrides, rosters
        )
        notable_injuries_b = get_notable_injuries_for_betting(
            manager_b, week_num, data.injury_overrides, rosters
        )
        
        preview = MatchupPreview(
            week=week_num,
            manager_a=manager_a,
            manager_b=manager_b,
            team_name_a=team_name_a,
            team_name_b=team_name_b,
            betting_line=betting_line,
            series_a_wins=series_a_wins,
            series_b_wins=series_b_wins,
            all_time_a_wins=all_time_a_wins,
            all_time_b_wins=all_time_b_wins,
            h2h_streak_holder=h2h_streak_holder or "",
            h2h_streak_length=h2h_streak_length,
            h2h_streak_last_loss_season=h2h_streak_last_loss_season or "",
            guard_matchup=guard_matchup,
            forward_matchup=forward_matchup,
            center_matchup=center_matchup,
            key_player_a=key_a,
            key_player_a_proj=key_a_proj,
            key_player_b=key_b,
            key_player_b_proj=key_b_proj,
            key_player_a_injury_note=injury_note_a,
            key_player_b_injury_note=injury_note_b,
            notable_injuries_a=notable_injuries_a,
            notable_injuries_b=notable_injuries_b,
            implications=implications,
        )
        
        previews.append(preview)
    
    return WeeklyBettingLines(
        week=week_num,
        num_simulations=num_simulations,
        matchup_previews=previews,
    )


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_betting_line(line: BettingLine) -> str:
    """Format a betting line as text."""
    lines = []
    lines.append(f"{line.manager_a} vs {line.manager_b}")
    lines.append(f"  Spread: {line.manager_a} {line.spread_a:+.1f}")
    lines.append(f"  O/U: {line.over_under:.0f}")
    lines.append(f"  Moneyline: {line.manager_a} {format_american_odds(line.moneyline_a)} | {line.manager_b} {format_american_odds(line.moneyline_b)}")
    lines.append(f"  Win Prob: {line.manager_a} {line.win_prob_a:.1f}% | {line.manager_b} {line.win_prob_b:.1f}%")
    lines.append(f"  Projected: {line.avg_score_a:.1f} - {line.avg_score_b:.1f}")
    return "\n".join(lines)


def format_matchup_preview(preview: MatchupPreview) -> str:
    """Format a complete matchup preview."""
    lines = []
    lines.append(f"=== WEEK {preview.week}: {preview.manager_a} vs {preview.manager_b} ===")
    lines.append("")
    lines.append(format_betting_line(preview.betting_line))
    lines.append("")
    lines.append(f"Season Series: {preview.manager_a} {preview.series_a_wins}-{preview.series_b_wins} {preview.manager_b}")
    lines.append("")
    lines.append("Positional Matchups:")
    lines.append(f"  Guards: {preview.guard_matchup.advantage} advantage ({preview.guard_matchup.advantage_margin:.1f} FPPG)")
    lines.append(f"  Forwards: {preview.forward_matchup.advantage} advantage ({preview.forward_matchup.advantage_margin:.1f} FPPG)")
    lines.append(f"  Centers: {preview.center_matchup.advantage} advantage ({preview.center_matchup.advantage_margin:.1f} FPPG)")
    lines.append("")
    lines.append("Key Players:")
    key_a_note = ''
    key_b_note = ''
    lines.append(f"  {preview.team_a_manager}{key_a_note}")
    lines.append(f"  {preview.team_b_manager}{key_b_note}")
    return "\n".join(lines)




# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from .data_loader import load_all_data
    
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    num_sims = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    
    print(f"Loading data from: {base.absolute()}")
    print(f"Running {num_sims} simulations per matchup...")
    print("-" * 60)
    
    data = load_all_data(base)
    result = generate_weekly_betting_lines(data, num_simulations=num_sims, seed=42)
    
    if result:
        for preview in result.matchup_previews:
            print(format_matchup_preview(preview))
            print()
    else:
        print("No upcoming week found in schedule.")
