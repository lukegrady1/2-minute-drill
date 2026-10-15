"""Extract playable spots (real late-game drives) from the play library.

    uv run python pipeline/spots.py build

A spot is the first qualifying snap of a possession:
  Q4 with <= 2:30 left and a one-score game (|margin| <= 8), or Q2 with <= 2:00 left,
  seasons >= config seasons.spots_first, regular season and playoffs.
Category: drill (trailing with the ball), protect (leading with the ball),
          tight (tied, or any end-of-half spot).

Output: data/processed/spots.parquet and data/processed/spots_summary.md.
Each row stores the start state the simulator needs, the game context (weather, spread,
coaches), and what really happened (the real drive's calls, its result, and the final score).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.config import PROCESSED_DIR, cfg
from pipeline.ingest import raw_path
from pipeline.playbook import ROWS_PATH

SPOTS_PATH = PROCESSED_DIR / "spots.parquet"
SUMMARY_PATH = PROCESSED_DIR / "spots_summary.md"

DRIVE_POINTS = {
    "Touchdown": 7, "Field goal": 3, "Opp touchdown": -7, "Safety": -2,
}
SNAP_FAMILIES = ["run_inside", "run_outside", "qb_sneak", "pass", "pa", "rpo", "screen",
                 "hail_mary", "gadget", "spike", "kneel", "field_goal", "punt"]


def _game_context(seasons: list[int]) -> pl.DataFrame:
    """Per-game context from pbp: final score, spread, weather, coaches, 2H receiver."""
    parts = []
    for s in seasons:
        p = raw_path("pbp", s)
        if not p.exists():
            continue
        lf = pl.scan_parquet(p)
        have = set(lf.collect_schema().names())
        cols = [c for c in ["game_id", "home_team", "away_team", "home_score", "away_score",
                            "spread_line", "total_line", "roof", "surface", "temp", "wind",
                            "home_coach", "away_coach", "div_game", "game_date", "stadium"]
                if c in have]
        ctx = lf.select(cols).group_by("game_id").agg([pl.col(c).drop_nulls().first() for c in cols if c != "game_id"])
        # the team receiving the opening kickoff of the second half
        r2h = (lf.filter((pl.col("play_type") == "kickoff") & (pl.col("qtr") == 3))
               .sort("play_id").group_by("game_id").agg(pl.col("posteam").first().alias("receive_2h")))
        parts.append(ctx.join(r2h, on="game_id", how="left").collect())
    return pl.concat(parts, how="diagonal_relaxed")


def _scores(seasons: list[int]) -> pl.DataFrame:
    parts = []
    for s in seasons:
        p = raw_path("pbp", s)
        if p.exists():
            parts.append(pl.scan_parquet(p).select(
                "game_id", pl.col("play_id").cast(pl.Int64), "posteam_score", "defteam_score").collect())
    return pl.concat(parts)


def build() -> pl.DataFrame:
    c = pl.col
    seasons = list(range(cfg("seasons", "spots_first"), cfg("seasons", "ingest_last") + 1))
    q4 = cfg("spots", "q4_max_seconds_left")
    q2 = cfg("spots", "q2_max_seconds_left")
    margin = cfg("spots", "one_score_max_margin")

    rows = (pl.read_parquet(ROWS_PATH)
            .filter(c("season").is_in(seasons) & c("family").is_in(SNAP_FAMILIES) & c("down").is_not_null()))
    rows = rows.join(_scores(seasons), on=["game_id", "play_id"], how="left")

    qualifies = (
        ((c("qtr") == 4) & (c("quarter_seconds_remaining") <= q4) & (c("score_differential").abs() <= margin))
        | ((c("qtr") == 2) & (c("quarter_seconds_remaining") <= q2))
    )
    rows = rows.with_columns(qualifies.alias("_q")).sort(["game_id", "play_id"])

    # The real drive from the spot onward: calls and outcome for "vs the real coach".
    drive = (rows.filter(c("_q")).group_by("game_id", "fixed_drive").agg(
        c("play_id").first().alias("play_id"),
        c("call").alias("real_calls"),
        c("play_id").alias("real_play_ids"),
        pl.len().alias("real_n_plays"),
        c("family").first().alias("real_first_family"),
        c("fixed_drive_result").first().alias("real_drive_result"),
    ))
    spots = rows.join(drive.select("game_id", "fixed_drive", "play_id", "real_calls", "real_play_ids",
                                   "real_n_plays", "real_first_family", "real_drive_result"),
                      on=["game_id", "fixed_drive", "play_id"], how="inner")

    ctx = _game_context(seasons)
    spots = spots.join(ctx, on="game_id", how="left", suffix="_ctx")

    is_home = c("posteam") == c("home_team")
    spots = spots.with_columns(
        pl.concat_str([c("game_id"), c("fixed_drive").cast(pl.Int64)], separator="_d").alias("spot_id"),
        pl.when(c("qtr") == 2).then(pl.lit("tight"))
        .when(c("score_differential") < 0).then(pl.lit("drill"))
        .when(c("score_differential") > 0).then(pl.lit("protect"))
        .otherwise(pl.lit("tight")).alias("category"),
        # spread from the possession team's perspective (positive = posteam favored)
        pl.when(is_home).then(c("spread_line")).otherwise(-c("spread_line")).alias("pos_spread"),
        pl.when(is_home).then(c("home_coach")).otherwise(c("away_coach")).alias("pos_coach"),
        pl.when(is_home).then(c("away_coach")).otherwise(c("home_coach")).alias("def_coach"),
        pl.when(is_home).then(c("home_score") - c("away_score"))
        .otherwise(c("away_score") - c("home_score")).alias("final_margin"),
        (c("receive_2h") == c("posteam")).alias("pos_receives_2h"),
        c("real_drive_result").replace_strict(DRIVE_POINTS, default=0).alias("real_drive_points"),
        (c("real_first_family") == "kneel").alias("kneel_start"),
        c("offense_players").is_not_null().alias("has_lineup"),
    ).with_columns(
        pl.when(c("final_margin") > 0).then(pl.lit("win")).when(c("final_margin") < 0).then(pl.lit("loss"))
        .otherwise(pl.lit("tie")).alias("real_outcome"),
    )

    out_cols = [
        "spot_id", "season", "week", "season_type", "game_id", "play_id", "fixed_drive", "category",
        "posteam", "defteam", "home_team", "away_team",
        # start state
        "qtr", "quarter_seconds_remaining", "half_seconds_remaining", "game_seconds_remaining",
        "down", "ydstogo", "yardline_100", "goal_to_go", "posteam_score", "defteam_score",
        "score_differential", "posteam_timeouts_remaining", "defteam_timeouts_remaining",
        "pos_receives_2h", "wp", "vegas_wp",
        # context
        "pos_spread", "spread_line", "total_line", "roof", "surface", "temp", "wind", "stadium",
        "pos_coach", "def_coach", "game_date",
        # what really happened
        "real_calls", "real_play_ids", "real_n_plays", "real_drive_result", "real_drive_points",
        "final_margin", "real_outcome", "kneel_start", "has_lineup",
    ]
    return spots.select([x for x in out_cols if x in spots.columns]).sort(["season", "week", "game_id", "play_id"])


def summarize(spots: pl.DataFrame) -> str:
    md = [(f"# Spots\n\n{spots.height:,} spots from seasons "
          f"{spots['season'].min()}-{spots['season'].max()} (target {cfg('spots', 'target_count')}). "
          f"{spots.filter(pl.col('kneel_start')).height:,} begin with a kneel (flagged, excluded from the pool).\n")]
    pool = spots.filter(~pl.col("kneel_start"))
    md.append(f"Playable pool: **{pool.height:,}**\n")
    piv = pool.group_by("season", "category").len().pivot(on="category", index="season", values="len").fill_null(0).sort("season")
    md.append("| season | " + " | ".join(piv.columns[1:]) + " | total |")
    md.append("|---|" + "|".join("---:" for _ in piv.columns[1:]) + "|---:|")
    for r in piv.iter_rows():
        md.append(f"| {r[0]} | " + " | ".join(f"{v:,}" for v in r[1:]) + f" | {sum(r[1:]):,} |")
    md.append("\n## Pool by category\n")
    for cat, n in pool.group_by("category").len().sort("category").iter_rows():
        md.append(f"- {cat}: {n:,}")
    md.append("\n## Real outcome from the possession team's view (Q4 spots)\n")
    q4 = pool.filter(pl.col("qtr") == 4)
    for cat, o, n in q4.group_by("category", "real_outcome").len().sort("category", "real_outcome").iter_rows():
        md.append(f"- {cat} / {o}: {n:,}")
    md.append("\n## Start state spread\n")
    md.append("- down: " + ", ".join(f"{int(d)}: {n:,}" for d, n in pool.group_by("down").len().sort("down").iter_rows()))
    md.append("- posteam timeouts: " + ", ".join(f"{int(t)}: {n:,}" for t, n in pool.group_by("posteam_timeouts_remaining").len().sort("posteam_timeouts_remaining").iter_rows()))
    md.append(f"- median clock (s): Q4 {q4['quarter_seconds_remaining'].median():.0f}, Q2 {pool.filter(pl.col('qtr') == 2)['quarter_seconds_remaining'].median():.0f}")
    md.append(f"- real drive length (plays): median {pool['real_n_plays'].median():.0f}, max {pool['real_n_plays'].max()}")
    md.append(f"- with the real 22-man lineup available: {pool.filter(pl.col('has_lineup')).height:,} "
              f"({100 * pool.filter(pl.col('has_lineup')).height / pool.height:.0f}%)")
    md.append(f"- playoff spots: {pool.filter(pl.col('season_type') == 'POST').height:,}")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    ap.parse_args(argv)
    spots = build()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    spots.write_parquet(SPOTS_PATH, compression="zstd")
    text = summarize(spots)
    SUMMARY_PATH.write_text(text)
    print(text)
    print(f"Wrote {SPOTS_PATH} and {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
