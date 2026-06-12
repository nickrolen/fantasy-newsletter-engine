"""
content_freshness.py

Tracks recently used content across weeks to prevent repetitive newsletters.
Implements two key strategies:
1. Track what was shown and when
2. Only repeat content if there's a meaningful "trigger event" (value changed)

FRESHNESS RULES:
- Weekly facts (player performances, waivers): Always fresh, no tracking needed
- Streak facts: Only show if streak length changed
- Milestone facts: Only show if distance to milestone changed
- Career/season stats: Cooldown period (don't show for N weeks after showing)
"""

import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict


# =============================================================================
# CONFIGURATION
# =============================================================================

# Default path for freshness tracking file
DEFAULT_FRESHNESS_FILE = Path(__file__).parent.parent / "config" / "RECENT_CONTENT.json"

# Cooldown periods (weeks) for different fact types
COOLDOWN_PERIODS = {
    # Career stats - don't show for 4 weeks unless significant change
    "career_win_pct": 4,
    "career_race": 3,
    
    # H2H facts - no cooldown needed, schedule naturally spaces matchups
    "h2h_dominance": 0,
    "h2h_upset": 0,
    "h2h_milestone": 0,  # Milestones are one-time anyway (40th, 50th meeting, etc.)
    
    # Season stats
    "season_points_leader": 3,
    "season_efficiency": 3,
    
    # Injury burden facts - cooldown of 2 weeks
    "injury_burden_leader": 2,
    "injury_burden_healthiest": 2,
    "injury_burden_il_heavy": 2,
    "injury_burden_gap": 2,
    
    # Career milestones - allow weekly (the drama of being stuck is the story!)
    "career_milestone": 1,
    
    # These are trigger-only (cooldown=0 means value MUST change to show again)
    "win_streak": 0,        # Show only when streak extends
    "loss_streak": 0,       # Show only when streak extends
    "season_series": 0,     # Schedule naturally spaces matchups
    
    # Weekly facts - always fresh (inherently different each week)
    "weekly_explosion": 0,
    "weekly_fppg": 0,
    "carry_job": 0,
    "waiver_success": 0,
    "injury_disparity": 0,
    "injury_woes": 0,
    "high_efficiency": 0,
    "low_efficiency": 0,
    "positional_dominance": 0,
    "schedule_advantage": 0,
    "boom_bust": 0,
    "close_game": 0,
    "blowout": 0,
    "near_record_close": 0,
    "near_record_blowout": 0,
    "elite_consistency": 0,
    "consistency": 0,
}

# Cooldown periods for rumor mill content
TRADE_IDEA_COOLDOWN = 4  # Don't suggest same trade for 4 weeks
FA_TARGET_COOLDOWN = 3   # Don't recommend same FA to same manager for 3 weeks
DROP_CANDIDATE_COOLDOWN = 2  # Don't suggest dropping same player for 2 weeks

# Minimum change thresholds to consider a fact "changed enough" to show again
CHANGE_THRESHOLDS = {
    "career_win_pct": 1.0,      # Need 1+ percentage point change
    "career_race": 1,           # Gap must change by at least 1 win
    "career_milestone": 1,      # Distance to milestone must decrease
    "win_streak": 1,            # Streak must extend
    "loss_streak": 1,           # Streak must extend
    "season_points_gap": 50,    # Points gap must change by 50+
    "season_series": 1,         # Series record must change
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class TrackedFact:
    """Record of a fact that was shown."""
    fact_key: str
    subcategory: str
    last_shown_week: int
    last_value: float | int | str
    times_shown: int = 1
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: dict) -> "TrackedFact":
        return cls(**d)


class FreshnessTracker:
    """
    Tracks content freshness across weeks.
    
    Usage:
        tracker = FreshnessTracker.load()
        
        # Check if a fact should be shown
        if tracker.should_show_fact(fact_key, subcategory, current_value, current_week):
            # Include the fact
            tracker.record_fact(fact_key, subcategory, current_value, current_week)
        
        tracker.save()
    """
    
    def __init__(self, filepath: Path = None):
        if filepath is not None and not isinstance(filepath, Path):
            filepath = Path(filepath)
        self.filepath = filepath or DEFAULT_FRESHNESS_FILE
        self.fun_facts: dict[str, TrackedFact] = {}
        self.trade_ideas: dict[str, dict] = {}
        self.free_agent_recs: dict[str, dict] = {}
        self._current_week: int = 0
    
    @classmethod
    def load(cls, filepath: Path = None) -> "FreshnessTracker":
        """Load tracker from JSON file, or create new if doesn't exist."""
        tracker = cls(filepath)
        
        if tracker.filepath.exists():
            try:
                with open(tracker.filepath, 'r') as f:
                    data = json.load(f)
                
                # Load fun facts
                for key, fact_data in data.get("fun_facts", {}).items():
                    tracker.fun_facts[key] = TrackedFact.from_dict(fact_data)
                
                # Load trade ideas
                tracker.trade_ideas = data.get("trade_ideas", {})
                
                # Load free agent recs
                tracker.free_agent_recs = data.get("free_agent_recs", {})
                
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Warning: Could not load freshness tracker: {e}")
                print("Starting with fresh tracker.")
        
        return tracker
    
    def save(self):
        """Save tracker to JSON file."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "fun_facts": {k: v.to_dict() for k, v in self.fun_facts.items()},
            "trade_ideas": self.trade_ideas,
            "free_agent_recs": self.free_agent_recs,
        }
        
        # Atomic write (tmp + replace) so a crash can't corrupt freshness state;
        # explicit utf-8 so player names survive non-UTF8 default locales.
        tmp = self.filepath.with_suffix(self.filepath.suffix + ".tmp")
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.filepath)
    
    def set_current_week(self, week: int):
        """Set current week for freshness calculations."""
        self._current_week = week
    
    # =========================================================================
    # FUN FACTS
    # =========================================================================
    
    def should_show_fact(
        self,
        fact_key: str,
        subcategory: str,
        current_value: float | int | str,
        current_week: int = None,
    ) -> bool:
        """
        Determine if a fact should be shown based on freshness rules.
        
        Args:
            fact_key: Unique identifier for this fact (e.g., "career_milestone:hayden:100")
            subcategory: Type of fact (e.g., "career_milestone", "win_streak")
            current_value: Current value of the metric being tracked
            current_week: Current week number
        
        Returns:
            True if fact should be shown, False if stale/repetitive
        """
        if current_week is None:
            current_week = self._current_week
        
        # Never shown before - always show
        if fact_key not in self.fun_facts:
            return True
        
        tracked = self.fun_facts[fact_key]
        weeks_since_shown = current_week - tracked.last_shown_week
        
        # Check if value changed enough (trigger event)
        value_changed = self._value_changed_enough(
            subcategory, tracked.last_value, current_value
        )
        
        if value_changed:
            return True
        
        # Check cooldown period
        cooldown = COOLDOWN_PERIODS.get(subcategory, 2)
        
        # If cooldown is 0, this fact is PURELY trigger-based
        # Only show when value changes, never on cooldown alone
        if cooldown == 0:
            return False  # Value didn't change, don't show
        
        # For facts with cooldowns, show again after cooldown expires
        if weeks_since_shown < cooldown:
            return False
        
        # Past cooldown, can show again
        return True
    
    def _value_changed_enough(
        self,
        subcategory: str,
        old_value: float | int | str,
        new_value: float | int | str,
    ) -> bool:
        """Check if value changed enough to warrant showing again."""
        threshold = CHANGE_THRESHOLDS.get(subcategory)
        
        if threshold is None:
            # No threshold defined - any change counts
            return old_value != new_value
        
        try:
            old_num = float(old_value)
            new_num = float(new_value)
            
            # For streaks and milestones, we want increases
            if subcategory in ["win_streak", "loss_streak"]:
                return new_num > old_num
            
            # For "distance to milestone", we want decreases
            if subcategory == "career_milestone":
                return new_num < old_num
            
            # For everything else, absolute change
            return abs(new_num - old_num) >= threshold
            
        except (ValueError, TypeError):
            # Non-numeric values - any change counts
            return old_value != new_value
    
    def record_fact(
        self,
        fact_key: str,
        subcategory: str,
        current_value: float | int | str,
        current_week: int = None,
    ):
        """Record that a fact was shown this week."""
        if current_week is None:
            current_week = self._current_week
        
        if fact_key in self.fun_facts:
            tracked = self.fun_facts[fact_key]
            tracked.last_shown_week = current_week
            tracked.last_value = current_value
            tracked.times_shown += 1
        else:
            self.fun_facts[fact_key] = TrackedFact(
                fact_key=fact_key,
                subcategory=subcategory,
                last_shown_week=current_week,
                last_value=current_value,
                times_shown=1,
            )
    
    def get_fact_history(self, fact_key: str) -> Optional[TrackedFact]:
        """Get history for a specific fact."""
        return self.fun_facts.get(fact_key)
    
    # =========================================================================
    # TRADE IDEAS
    # =========================================================================
    
    def should_show_trade(
        self,
        trade_key: str,
        current_week: int = None,
        cooldown_weeks: int = None,
    ) -> bool:
        """Check if a trade idea should be shown (not shown recently)."""
        if current_week is None:
            current_week = self._current_week
        if cooldown_weeks is None:
            cooldown_weeks = TRADE_IDEA_COOLDOWN
        
        if trade_key not in self.trade_ideas:
            return True
        
        last_shown = self.trade_ideas[trade_key].get("last_shown_week", 0)
        return (current_week - last_shown) >= cooldown_weeks
    
    def record_trade(self, trade_key: str, current_week: int = None):
        """Record that a trade idea was shown."""
        if current_week is None:
            current_week = self._current_week
        
        if trade_key not in self.trade_ideas:
            self.trade_ideas[trade_key] = {"times_shown": 0}
        
        self.trade_ideas[trade_key]["last_shown_week"] = current_week
        self.trade_ideas[trade_key]["times_shown"] = \
            self.trade_ideas[trade_key].get("times_shown", 0) + 1
    
    # =========================================================================
    # FREE AGENT RECOMMENDATIONS  
    # =========================================================================
    
    def should_show_fa_rec(
        self,
        player_name: str,
        manager: str,
        current_week: int = None,
        cooldown_weeks: int = None,
    ) -> bool:
        """Check if a free agent recommendation should be shown."""
        if current_week is None:
            current_week = self._current_week
        if cooldown_weeks is None:
            cooldown_weeks = FA_TARGET_COOLDOWN
        
        key = f"{player_name}:{manager}"
        
        if key not in self.free_agent_recs:
            return True
        
        last_shown = self.free_agent_recs[key].get("last_shown_week", 0)
        return (current_week - last_shown) >= cooldown_weeks
    
    def record_fa_rec(self, player_name: str, manager: str, current_week: int = None):
        """Record that a free agent was recommended."""
        if current_week is None:
            current_week = self._current_week
        
        key = f"{player_name}:{manager}"
        
        if key not in self.free_agent_recs:
            self.free_agent_recs[key] = {"times_shown": 0}
        
        self.free_agent_recs[key]["last_shown_week"] = current_week
        self.free_agent_recs[key]["times_shown"] = \
            self.free_agent_recs[key].get("times_shown", 0) + 1
    
    # =========================================================================
    # DROP CANDIDATES
    # =========================================================================
    
    def should_show_drop(
        self,
        player_name: str,
        manager: str,
        current_week: int = None,
        cooldown_weeks: int = None,
    ) -> bool:
        """Check if a drop candidate should be shown."""
        if current_week is None:
            current_week = self._current_week
        if cooldown_weeks is None:
            cooldown_weeks = DROP_CANDIDATE_COOLDOWN
        
        key = f"drop:{player_name}:{manager}"
        
        # Store drop candidates in free_agent_recs dict (reuse structure)
        if key not in self.free_agent_recs:
            return True
        
        last_shown = self.free_agent_recs[key].get("last_shown_week", 0)
        return (current_week - last_shown) >= cooldown_weeks
    
    def record_drop(self, player_name: str, manager: str, current_week: int = None):
        """Record that a drop candidate was shown."""
        if current_week is None:
            current_week = self._current_week
        
        key = f"drop:{player_name}:{manager}"
        
        if key not in self.free_agent_recs:
            self.free_agent_recs[key] = {"times_shown": 0}
        
        self.free_agent_recs[key]["last_shown_week"] = current_week
        self.free_agent_recs[key]["times_shown"] = \
            self.free_agent_recs[key].get("times_shown", 0) + 1
    
    # =========================================================================
    # CLEANUP
    # =========================================================================
    
    def cleanup_old_entries(self, current_week: int, max_age_weeks: int = 10):
        """Remove entries older than max_age_weeks to keep file size manageable."""
        cutoff = current_week - max_age_weeks
        
        # Clean fun facts
        self.fun_facts = {
            k: v for k, v in self.fun_facts.items()
            if v.last_shown_week >= cutoff
        }
        
        # Clean trade ideas
        self.trade_ideas = {
            k: v for k, v in self.trade_ideas.items()
            if v.get("last_shown_week", 0) >= cutoff
        }
        
        # Clean FA recs
        self.free_agent_recs = {
            k: v for k, v in self.free_agent_recs.items()
            if v.get("last_shown_week", 0) >= cutoff
        }


# =============================================================================
# FACT KEY GENERATORS
# =============================================================================

def make_fact_key(subcategory: str, **kwargs) -> str:
    """
    Generate a unique key for a fact based on its type and details.
    
    Examples:
        make_fact_key("career_milestone", manager="Hayden", milestone=100)
        -> "career_milestone:hayden:100"
        
        make_fact_key("win_streak", manager="Nick")
        -> "win_streak:nick"
        
        make_fact_key("h2h_dominance", manager_a="Nick", manager_b="Garrett")
        -> "h2h_dominance:garrett:nick"  (alphabetized)
    """
    parts = [subcategory]
    
    # Handle different fact types
    if subcategory == "career_milestone":
        parts.append(kwargs.get("manager", "").lower())
        parts.append(str(kwargs.get("milestone", "")))
    
    elif subcategory == "career_race":
        parts.append(kwargs.get("chaser", "").lower())
    
    elif subcategory in ["win_streak", "loss_streak"]:
        parts.append(kwargs.get("manager", "").lower())
    
    elif subcategory == "career_win_pct":
        parts.append(kwargs.get("manager", "").lower())
    
    elif subcategory in ["h2h_dominance", "h2h_milestone", "h2h_upset"]:
        # Alphabetize managers for consistent keys
        managers = sorted([
            kwargs.get("manager_a", kwargs.get("dominant", "")).lower(),
            kwargs.get("manager_b", kwargs.get("dominated", "")).lower(),
        ])
        parts.extend(managers)
    
    elif subcategory == "season_series":
        managers = sorted([
            kwargs.get("manager_a", "").lower(),
            kwargs.get("manager_b", "").lower(),
        ])
        parts.extend(managers)
    
    elif subcategory in ["weekly_explosion", "weekly_fppg", "carry_job"]:
        parts.append(kwargs.get("player", "").lower().replace(" ", "_"))
    
    elif subcategory == "waiver_success":
        parts.append(kwargs.get("player", "").lower().replace(" ", "_"))
        parts.append(kwargs.get("manager", "").lower())
    
    elif subcategory in ["injury_disparity", "injury_woes", "high_efficiency", "low_efficiency"]:
        parts.append(kwargs.get("manager", "").lower())
    
    elif subcategory == "positional_dominance":
        parts.append(kwargs.get("winner", "").lower())
        parts.append(kwargs.get("loser", "").lower())
        parts.append(kwargs.get("position", "").lower())
    
    elif subcategory == "schedule_advantage":
        parts.append(kwargs.get("advantaged", "").lower())
        parts.append(kwargs.get("disadvantaged", "").lower())
    
    elif subcategory == "boom_bust":
        parts.append(kwargs.get("manager", "").lower())
    
    elif subcategory in ["close_game", "blowout"]:
        parts.append(kwargs.get("matchup", "").lower())
    
    elif subcategory in ["near_record_close", "near_record_blowout"]:
        parts.append(kwargs.get("matchup", str(kwargs.get("this_week", ""))).lower())
    
    elif subcategory in ["elite_consistency", "consistency"]:
        parts.append(kwargs.get("player", "").lower().replace(" ", "_"))
        parts.append(kwargs.get("manager", "").lower())
    
    elif subcategory == "season_points_leader":
        parts.append(kwargs.get("manager", "").lower())
    
    else:
        # Generic: just use any manager/player in kwargs
        if "manager" in kwargs:
            parts.append(kwargs["manager"].lower())
        if "player" in kwargs:
            parts.append(kwargs["player"].lower().replace(" ", "_"))
    
    return ":".join(str(p) for p in parts if p)


def get_fact_value(subcategory: str, details: dict) -> float | int | str:
    """
    Extract the trackable value from a fact's details.
    
    This is the value we compare week-over-week to detect changes.
    """
    if subcategory == "career_milestone":
        return details.get("away", 0)
    
    elif subcategory == "career_race":
        return details.get("gap", 0)
    
    elif subcategory in ["win_streak", "loss_streak"]:
        return details.get("length", details.get("streak", 0))
    
    elif subcategory == "career_win_pct":
        return details.get("win_pct", details.get("pct", 0))
    
    elif subcategory in ["h2h_dominance", "h2h_milestone"]:
        return details.get("total", details.get("record", ""))
    
    elif subcategory == "season_series":
        return f"{details.get('wins', 0)}-{details.get('losses', 0)}"
    
    elif subcategory in ["weekly_explosion", "weekly_fppg"]:
        return details.get("fp", details.get("fppg", 0))
    
    elif subcategory == "waiver_success":
        return details.get("fp", 0)
    
    elif subcategory in ["injury_disparity", "injury_woes"]:
        return details.get("injuries", 0)
    
    elif subcategory in ["high_efficiency", "low_efficiency"]:
        return details.get("efficiency", 0)
    
    elif subcategory == "positional_dominance":
        return details.get("gap", 0)
    
    elif subcategory == "schedule_advantage":
        return details.get("gap", 0)
    
    elif subcategory == "boom_bust":
        # Track by the spread between best and worst
        best = details.get("best", {}).get("fp", 0)
        worst = details.get("worst", {}).get("fp", 0)
        return best - worst
    
    elif subcategory in ["close_game", "blowout", "near_record_close", "near_record_blowout"]:
        return details.get("margin", details.get("this_week", 0))
    
    elif subcategory in ["elite_consistency", "consistency"]:
        return details.get("min", 0)
    
    else:
        # Default: return first numeric value found, or empty string
        for v in details.values():
            if isinstance(v, (int, float)):
                return v
        return ""


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def filter_fresh_facts(
    facts: list,
    tracker: FreshnessTracker,
    current_week: int,
    min_count: int = 0,
) -> list:
    """
    Filter a list of FunFact objects to only include fresh ones, with fallback.
    
    Args:
        facts: List of FunFact objects (from fun_facts_generator)
        tracker: FreshnessTracker instance
        current_week: Current week number
        min_count: Minimum number of facts to return (will use least-stale if needed)
    
    Returns:
        Filtered list of facts (fresh first, then least-stale if needed)
    """
    fresh_facts = []
    stale_facts = []
    
    for fact in facts:
        # Generate key and get trackable value
        fact_key = make_fact_key(fact.subcategory, **fact.details)
        fact_value = get_fact_value(fact.subcategory, fact.details)
        
        # Check if should show
        if tracker.should_show_fact(fact_key, fact.subcategory, fact_value, current_week):
            fresh_facts.append(fact)
        else:
            # Track staleness for fallback
            tracked = tracker.fun_facts.get(fact_key)
            last_shown = tracked.last_shown_week if tracked else 0
            stale_facts.append((fact, last_shown))
    
    if len(fresh_facts) >= min_count:
        return fresh_facts
    
    # Add least-recently-shown stale items
    stale_facts.sort(key=lambda x: x[1])
    
    result = fresh_facts.copy()
    for fact, _ in stale_facts:
        if len(result) >= min_count:
            break
        result.append(fact)
    
    return result


def record_shown_facts(
    facts: list,
    tracker: FreshnessTracker,
    current_week: int,
):
    """
    Record that facts were shown in the newsletter.
    
    Call this AFTER finalizing which facts to include.
    """
    for fact in facts:
        fact_key = make_fact_key(fact.subcategory, **fact.details)
        fact_value = get_fact_value(fact.subcategory, fact.details)
        tracker.record_fact(fact_key, fact.subcategory, fact_value, current_week)


# =============================================================================
# RUMOR MILL HELPERS
# =============================================================================

def make_trade_key(manager_a: str, manager_b: str, gives_a: list[str], receives_a: list[str]) -> str:
    """
    Generate a unique key for a trade idea.
    
    Key is alphabetized by manager names and primary players for consistency.
    E.g., "nick:garrett:luka_doncic:victor_wembanyama"
    """
    # Alphabetize managers
    if manager_a.lower() > manager_b.lower():
        manager_a, manager_b = manager_b, manager_a
        gives_a, receives_a = receives_a, gives_a
    
    # Use primary player from each side
    player_a = gives_a[0].lower().replace(" ", "_") if gives_a else "unknown"
    player_b = receives_a[0].lower().replace(" ", "_") if receives_a else "unknown"
    
    return f"{manager_a.lower()}:{manager_b.lower()}:{player_a}:{player_b}"


def filter_fresh_trades(
    trade_ideas: list,
    tracker: FreshnessTracker,
    current_week: int,
    min_count: int = 0,
) -> list:
    """
    Filter trade ideas to only include fresh ones, with fallback to least-stale.
    
    Args:
        trade_ideas: List of TradeIdea objects
        tracker: FreshnessTracker instance
        current_week: Current week number
        min_count: Minimum number of trades to return (will use least-stale if needed)
    
    Returns:
        Filtered list of trade ideas (fresh first, then least-stale if needed)
    """
    fresh_trades = []
    stale_trades = []
    
    for idea in trade_ideas:
        trade_key = make_trade_key(
            idea.manager_a, idea.manager_b,
            idea.gives_a, idea.receives_a
        )
        
        if tracker.should_show_trade(trade_key, current_week):
            fresh_trades.append(idea)
        else:
            # Track staleness for fallback
            last_shown = tracker.trade_ideas.get(trade_key, {}).get("last_shown_week", 0)
            stale_trades.append((idea, last_shown))
    
    # If we have enough fresh content, return it
    if len(fresh_trades) >= min_count:
        return fresh_trades
    
    # Otherwise, add least-recently-shown stale items to meet quota
    stale_trades.sort(key=lambda x: x[1])  # Sort by last_shown_week ascending (oldest first)
    
    result = fresh_trades.copy()
    for idea, _ in stale_trades:
        if len(result) >= min_count:
            break
        result.append(idea)
    
    return result


def record_shown_trades(
    trade_ideas: list,
    tracker: FreshnessTracker,
    current_week: int,
):
    """Record that trade ideas were shown."""
    for idea in trade_ideas:
        trade_key = make_trade_key(
            idea.manager_a, idea.manager_b,
            idea.gives_a, idea.receives_a
        )
        tracker.record_trade(trade_key, current_week)


def filter_fresh_fa_targets(
    fa_targets: list,
    tracker: FreshnessTracker,
    current_week: int,
    min_count: int = 0,
) -> list:
    """
    Filter free agent targets to only include fresh ones, with fallback to least-stale.
    
    Args:
        fa_targets: List of FreeAgentTarget objects
        tracker: FreshnessTracker instance
        current_week: Current week number
        min_count: Minimum number of targets to return (will use least-stale if needed)
    
    Returns:
        Filtered list of FA targets (fresh first, then least-stale if needed)
    """
    fresh_targets = []
    stale_targets = []
    
    for target in fa_targets:
        key = f"{target.player_name}:{target.target_manager}"
        
        if tracker.should_show_fa_rec(target.player_name, target.target_manager, current_week):
            fresh_targets.append(target)
        else:
            last_shown = tracker.free_agent_recs.get(key, {}).get("last_shown_week", 0)
            stale_targets.append((target, last_shown))
    
    if len(fresh_targets) >= min_count:
        return fresh_targets
    
    # Add least-recently-shown stale items
    stale_targets.sort(key=lambda x: x[1])
    
    result = fresh_targets.copy()
    for target, _ in stale_targets:
        if len(result) >= min_count:
            break
        result.append(target)
    
    return result


def record_shown_fa_targets(
    fa_targets: list,
    tracker: FreshnessTracker,
    current_week: int,
):
    """Record that FA targets were shown."""
    for target in fa_targets:
        tracker.record_fa_rec(target.player_name, target.target_manager, current_week)


def filter_fresh_drop_candidates(
    drop_candidates: list,
    tracker: FreshnessTracker,
    current_week: int,
    min_count: int = 0,
) -> list:
    """
    Filter drop candidates to only include fresh ones, with fallback to least-stale.
    
    Args:
        drop_candidates: List of DropCandidate objects
        tracker: FreshnessTracker instance
        current_week: Current week number
        min_count: Minimum number of drops to return (will use least-stale if needed)
    
    Returns:
        Filtered list of drop candidates (fresh first, then least-stale if needed)
    """
    fresh_drops = []
    stale_drops = []
    
    for drop in drop_candidates:
        key = f"drop:{drop.player_name}:{drop.manager}"
        
        if tracker.should_show_drop(drop.player_name, drop.manager, current_week):
            fresh_drops.append(drop)
        else:
            last_shown = tracker.free_agent_recs.get(key, {}).get("last_shown_week", 0)
            stale_drops.append((drop, last_shown))
    
    if len(fresh_drops) >= min_count:
        return fresh_drops
    
    # Add least-recently-shown stale items
    stale_drops.sort(key=lambda x: x[1])
    
    result = fresh_drops.copy()
    for drop, _ in stale_drops:
        if len(result) >= min_count:
            break
        result.append(drop)
    
    return result


def record_shown_drop_candidates(
    drop_candidates: list,
    tracker: FreshnessTracker,
    current_week: int,
):
    """Record that drop candidates were shown."""
    for drop in drop_candidates:
        tracker.record_drop(drop.player_name, drop.manager, current_week)
