#!/usr/bin/env python3
"""
fetch_injury_statuses.py

Fetches current injury statuses for all rostered players from Yahoo Fantasy API.
Returns a dict mapping player_name -> injury status (e.g., "Q", "O", "HEALTHY").

Used by generate_stats_report.py to provide accurate injury data to betting simulations.

A FAILED FETCH IS NOT "NOBODY IS HURT" (Nick, 10-21)
----------------------------------------------------
Every line and every odds figure reads these tags, and they change every
week. fetch_injury_statuses() RAISES InjuryFetchError on every failure path
(no Yahoo libraries, no oauth2.json, auth failure, no rostered players
returned, the player-details call failing) -- it never returns {} to mean
"failed". A successful fetch returns a status for every rostered player,
HEALTHY included, so "fetched, nobody tagged" is a full dict of HEALTHY and
"failed" is an exception: the two can no longer look alike.

injury_input() is the one decision for a build: resolve the names, settle any
out-for-season tag that contradicts the overrides file, and if the tags are
needed but unavailable, refuse unless the caller passed the explicit override.
Its record() goes into the report metadata and the point-in-time capture
either way.
"""

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

try:
    from yahoo_oauth import OAuth2
    import yahoo_fantasy_api as yfa
    YAHOO_API_AVAILABLE = True
except ImportError:
    YAHOO_API_AVAILABLE = False


# ---------- CONFIGURATION (from league_config.json via data_loader) ----------

from .data_loader import PlayerIndex, LEAGUE_KEY, TEAM_TO_MANAGER, YAHOO_GAME_CODE

# Alias for backwards compatibility
FANTASY_TEAM_TO_MANAGER = TEAM_TO_MANAGER


class InjuryFetchError(RuntimeError):
    """The Yahoo injury fetch failed or returned nothing."""


class InjuryStatusesUnavailable(RuntimeError):
    """Tags are needed for this run and there are none: refuse."""


# ---------- HELPERS ----------

def strip_accents(text: str) -> str:
    """Return ASCII-only version of a name (e.g., 'Don??i??' -> 'Doncic')."""
    if not isinstance(text, str):
        return text
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def get_league(oauth) -> "yfa.League":
    """Return League object for your NBA league."""
    return yfa.League(oauth, LEAGUE_KEY)


def normalize_injury_status(status: Optional[str]) -> str:
    """
    Normalize a Yahoo injury status to the designation modules/absence.py names.

    THE 2026-27 VOCABULARY (measured against the live API 2026-10-22)
        P    probable      -> healthy
        Q    questionable  -> the chain
        D    doubtful      -> the chain
        O    out           -> the chain
        OFS  out for season-> a season-long out
    Only O and OFS may occupy an IL slot. SUSP (suspended) and NA (not on an
    NBA roster) are NOT injury designations: they pass through unchanged and
    absence.py treats them as no-effect and logs them. Until 2026-10-22 both
    were mapped to O here, which charged an injury-shaped three-game recovery
    for a suspension.

    The retired designations (GTD, DTD, INJ, IL, IL+) are deliberately NOT
    mapped: anything unknown passes through unchanged so absence.py raises on
    it, naming the vocabulary change. This function normalises spelling; it
    does not decide policy.

    Returns the upper-case designation, or "HEALTHY" for no tag.
    """
    if not status or str(status).strip() == "":
        return "HEALTHY"

    status_upper = str(status).strip().upper()

    # Long forms Yahoo has been seen to use for the live designations.
    status_map = {
        "P": "P",
        "PROBABLE": "P",
        "Q": "Q",
        "QUESTIONABLE": "Q",
        "D": "D",
        "DOUBTFUL": "D",
        "O": "O",
        "OUT": "O",
        "OFS": "OFS",
        "OUT FOR SEASON": "OFS",
        "OUT FOR THE SEASON": "OFS",
        "SUSP": "SUSP",
        "SUSPENDED": "SUSP",
        "NA": "NA",
    }

    return status_map.get(status_upper, status_upper)


def fetch_injury_statuses(
    oauth_file: str = "oauth2.json",
    verbose: bool = False,
) -> dict[str, str]:
    """
    Fetch current injury statuses for all rostered players.
    
    Args:
        oauth_file: Path to Yahoo OAuth2 credentials file
        verbose: If True, print progress information
    
    Returns:
        Dict mapping player_name -> injury status, one for every rostered
        player (HEALTHY included: "fetched, nobody tagged" is a full dict of
        HEALTHY, never an empty one -- see the module docstring).
        Status is one of "HEALTHY", "P", "Q", "D", "O", "OFS", or the
        non-injury "SUSP" / "NA" (normalize_injury_status).
    """
    if not YAHOO_API_AVAILABLE:
        raise InjuryFetchError("yahoo_oauth / yahoo_fantasy_api are not installed")
    if not Path(oauth_file).exists():
        raise InjuryFetchError(f"OAuth file not found at {oauth_file}")
    # Authenticate (fail-fast, never prompts).
    try:
        from .yahoo_auth import build_oauth
        oauth = build_oauth(oauth_file, OAuth2=OAuth2)
    except Exception as e:
        raise InjuryFetchError(f"Yahoo auth failed: {e}") from e
    try:
        lg = get_league(oauth)
    except Exception as e:
        raise InjuryFetchError(f"could not open the Yahoo league: {e}") from e
    
    if verbose:
        print("Fetching injury statuses from Yahoo...")
    
    # Get all teams
    try:
        teams_json = lg.teams()
    except Exception as e:
        raise InjuryFetchError(f"could not list the league's teams: {e}") from e
    
    injury_statuses = PlayerIndex()
    all_player_ids = []
    player_id_to_name = {}
    
    # First pass: collect all player IDs from rosters
    for team_key, team_data in teams_json.items():
        team_name = team_data["name"]
        team_obj = lg.to_team(team_key)
        
        # Get current roster
        try:
            roster = team_obj.roster()
        except Exception as e:
            raise InjuryFetchError(f"could not read {team_name}'s roster: {e}") from e
        
        for player in roster:
            player_id = int(player["player_id"])
            player_name = strip_accents(player["name"])
            
            all_player_ids.append(player_id)
            player_id_to_name[player_id] = player_name
            
            # Get injury status from roster data if available
            # Yahoo sometimes includes status in roster response
            status = player.get("status")
            if status:
                injury_statuses[player_name] = normalize_injury_status(status)
    
    if not all_player_ids:
        raise InjuryFetchError("Yahoo returned no rostered players")

    # Second pass: get detailed player info for more accurate injury status
    # player_details() often has more up-to-date injury info. Its failure is
    # a failed fetch: the roster pass alone is not known to carry every tag.
    if all_player_ids:
        try:
            details = lg.player_details(all_player_ids)
            
            for player_detail in details:
                player_id = int(player_detail["player_id"])
                player_name = player_id_to_name.get(player_id)
                
                if player_name:
                    # Check multiple possible status fields
                    status = (
                        player_detail.get("status") or 
                        player_detail.get("injury_status") or
                        player_detail.get("status_full")
                    )
                    
                    normalized = normalize_injury_status(status)
                    
                    # Only update if we found a non-healthy status
                    # (roster endpoint might have already caught it)
                    if normalized != "HEALTHY" or player_name not in injury_statuses:
                        injury_statuses[player_name] = normalized
                        
        except Exception as e:
            raise InjuryFetchError(f"player_details failed ({e}); the roster-level "
                                   "statuses alone are not a complete tag list") from e
    
    # Ensure all players have a status (default to HEALTHY)
    for player_name in player_id_to_name.values():
        if player_name not in injury_statuses:
            injury_statuses[player_name] = "HEALTHY"
    
    if verbose:
        # Count by status
        status_counts = {}
        for status in injury_statuses.values():
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print(f"Fetched statuses for {len(injury_statuses)} players:")
        for status, count in sorted(status_counts.items()):
            print(f"  {status}: {count}")
        
        # Show non-healthy players
        non_healthy = {k: v for k, v in injury_statuses.items() if v != "HEALTHY"}
        if non_healthy:
            print("\nNon-healthy players:")
            for player, status in sorted(non_healthy.items()):
                print(f"  {player}: {status}")
    
    return injury_statuses


@dataclass
class InjuryInput:
    """The tags a build runs on, and how it got them."""
    statuses: dict                       # roster spelling -> status; {} if unavailable
    available: bool
    problem: Optional[str] = None        # why they are unavailable
    override: bool = False               # ran anyway (--allow-no-injury-statuses)
    unmatched_healthy: list = field(default_factory=list)
    rostered_without_status: list = field(default_factory=list)
    noted: list = field(default_factory=list)   # SUSP / NA: no-effect, logged
    season_out_conflicts: list = field(default_factory=list)   # OFS vs a stated return

    def record(self) -> dict:
        return {
            "available": self.available,
            "count": len(self.statuses),
            "non_healthy": sorted(n for n, v in self.statuses.items() if str(v).upper() != "HEALTHY"),
            "problem": self.problem,
            "override": self.override,
            "unmatched_healthy": list(self.unmatched_healthy),
            "rostered_without_status": list(self.rostered_without_status),
            # Not injury designations and not an absence rule: the baseline
            # hazard already carries their games through projected GP. Named
            # here so an INJURY_OVERRIDES entry can be judged (Nick, 10-22).
            "noted_tags": list(self.noted),
            # OFS against a stated return, resolved in the overrides file's
            # favour because --allow-season-out-conflict was passed.
            "season_out_override": bool(self.season_out_conflicts),
            "season_out_conflicts": list(self.season_out_conflicts),
        }


def injury_input(fetch: Optional[Callable[[], dict]], rostered, needed: bool,
                 allow_missing: bool = False, not_fetched_reason: Optional[str] = None,
                 projections=None, allow_season_out_conflict: bool = False) -> InjuryInput:
    """Fetch (if `fetch` is given), resolve names, settle OFS, and decide.

    needed: this run prices lines/odds from the tags (simulations on, not
    --repro). Unavailable tags on a needed run RAISE InjuryStatusesUnavailable
    unless allow_missing -- then the run goes ahead on no tags and the record
    says so. A tag whose name matches no rostered player raises
    absence.UnresolvedTagName (never a dropped tag).

    projections (name -> PlayerProjection, with INJURY_OVERRIDES applied):
    an OFS tag the overrides file states a return for raises
    absence.SeasonOutConflict, unless allow_season_out_conflict -- then the
    OVERRIDE WINS, the tag is dropped for this run, and record() carries the
    conflict for the report metadata and the capture.
    """
    from . import absence
    problem = None
    raw = {}
    if fetch is None:
        problem = f"not fetched ({not_fetched_reason or 'no fetch attempted'})"
    else:
        try:
            raw = fetch()
        except InjuryFetchError as e:
            problem = f"fetch failed: {e}"
        else:
            if not raw:
                problem = "fetch returned nothing"
    if problem is not None:
        if needed and not allow_missing:
            raise InjuryStatusesUnavailable(
                f"no injury statuses: {problem}. Every betting line and odds figure would be "
                "priced as though nobody in the league is hurt. Fix the fetch, or pass "
                "--allow-no-injury-statuses to run anyway (recorded in the report metadata "
                "and the point-in-time capture).")
        return InjuryInput({}, False, problem, override=needed)
    resolved, unmatched, missing = absence.resolve_tags(raw, rostered)
    resolved, conflicts = absence.resolve_season_out_conflicts(
        resolved, projections, allow_season_out_conflict)
    return InjuryInput(resolved, True, None, False, unmatched, missing,
                       absence.noted_tags(resolved), conflicts)


if __name__ == "__main__":
    import argparse
    import json
    
    parser = argparse.ArgumentParser(
        description="Fetch current injury statuses from Yahoo Fantasy API"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path for JSON (optional, prints to stdout if not specified)",
    )
    parser.add_argument(
        "--oauth-file",
        type=str,
        default="oauth2.json",
        help="Path to Yahoo OAuth2 credentials file",
    )
    
    args = parser.parse_args()
    
    statuses = fetch_injury_statuses(oauth_file=args.oauth_file, verbose=True)
    
    if args.output:
        with open(args.output, 'w', encoding="utf-8") as f:
            json.dump(statuses, f, indent=2)
        print(f"\nSaved to {args.output}")
    else:
        print("\nJSON output:")
        print(json.dumps(statuses, indent=2))
