"""backfill_player_records prints each record under its own label
(HANDOFF_SEASON_PERFORMERS_ASOF_2026-10-30 s.4): "Best Season Total FP" printed
the FPPG, and longest_player_tenure printed '?'."""
import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import backfill_player_records as b   # noqa: E402


def _games():
    out = []
    for season in ("2022-23", "2023-24", "2024-25"):
        for w in range(1, 4):
            for d in range(3):
                for p, fp in (("A Player", 40.0 + d), ("B Player", 20.0)):
                    out.append({"season": season, "week": w, "date": f"2023-0{w}-1{d}",
                                "manager": "Nick", "player_name": p, "fantasy_points": fp})
    return out


def _printed(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(_games())
    return buf.getvalue()


def test_best_season_total_fp_prints_the_total_not_the_fppg():
    text = _printed(b.compute_player_leaderboards)
    assert "Best Season Total FP: 369.0 by A Player (2022-23)" in text   # 9 games x 41.0


def test_longest_player_tenure_prints_its_seasons():
    text = _printed(b.compute_expanded_leaderboards)
    assert "longest_player_tenure: 3 by A Player" in text
    assert "longest_player_tenure: ?" not in text
