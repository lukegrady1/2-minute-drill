"""Build the play library: every real play mapped to a call, a defensive look,
personnel, formation, depth, direction, and its outcome.

    uv run python pipeline/playbook.py build [--seasons 2016-2026]
    uv run python pipeline/playbook.py report

Output: data/processed/playbook_rows.parquet (one row per play) and
        data/processed/playbook_report.md (bucket counts vs the Phase 1 exit criterion).

Call taxonomy (the `call` column; `family`, `depth`, `direction` are also stored):
  run_inside_{left,middle,right}   run_outside_{left,right}   qb_sneak
  pass_{short,medium,deep}_{left,middle,right}
  pa_{short,medium,deep}_{left,middle,right}   (play action, FTN 2022+)
  rpo (FTN 2022+)   screen   hail_mary   gadget (FTN trick plays)
  spike   kneel   two_point   field_goal   punt   extra_point   kickoff   onside_kick
Scrambles, sacks, throwaways and penalty-nullified dropbacks are outcomes of pass calls; they
have no air yards, so their depth/direction are drawn (seeded) from data-derived weights.

Defensive look: box light (<= 6) / heavy, x blitz (>= 5 rushers) / base. Rushers are not
charted on run plays, so run rows carry look '<box>_any' and the sampler ignores blitz for runs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.config import PROCESSED_DIR, cfg
from pipeline.ingest import parse_seasons, raw_path
from pipeline.normalize import (
    FORMATIONS,
    PERSONNEL_CLASSES,
    normalize_formation,
    parse_personnel,
)

ROWS_PATH = PROCESSED_DIR / "playbook_rows.parquet"
REPORT_PATH = PROCESSED_DIR / "playbook_report.md"

PBP_COLS = [
    "game_id", "play_id", "season", "week", "season_type", "posteam", "defteam", "home_team",
    "away_team", "qtr", "game_half", "down", "ydstogo", "yardline_100", "goal_to_go",
    "score_differential", "half_seconds_remaining", "quarter_seconds_remaining",
    "game_seconds_remaining", "posteam_timeouts_remaining", "defteam_timeouts_remaining",
    "play_type", "pass", "rush", "qb_kneel", "qb_spike", "qb_scramble", "qb_dropback",
    "two_point_attempt", "no_huddle", "shotgun", "desc", "timeout", "timeout_team",
    "pass_length", "pass_location", "air_yards", "yards_after_catch", "run_location", "run_gap",
    "yards_gained", "first_down", "touchdown", "interception", "fumble_lost", "sack",
    "complete_pass", "incomplete_pass", "out_of_bounds", "safety", "return_yards",
    "return_touchdown", "penalty", "penalty_type", "penalty_yards", "penalty_team",
    "kick_distance", "field_goal_result", "extra_point_result", "two_point_conv_result",
    "punt_blocked", "punt_inside_twenty", "punt_in_endzone", "punt_out_of_bounds",
    "punt_downed", "punt_fair_catch", "kickoff_in_endzone", "kickoff_out_of_bounds",
    "kickoff_fair_catch", "own_kickoff_recovery", "touchback",
    "epa", "wpa", "wp", "vegas_wp", "receiver_player_id", "rusher_player_id",
    "passer_player_id", "fixed_drive", "fixed_drive_result", "aborted_play",
]

PART_COLS = [
    "offense_formation", "offense_personnel", "defense_personnel", "defenders_in_box",
    "number_of_pass_rushers", "defense_coverage_type", "defense_man_zone_type", "was_pressure",
    "time_to_throw", "route", "offense_players", "defense_players",
]

FTN_COLS = [
    "qb_location", "n_offense_backfield", "n_defense_box", "n_pass_rushers", "n_blitzers",
    "is_no_huddle", "is_motion", "is_play_action", "is_screen_pass", "is_rpo", "is_trick_play",
    "is_qb_sneak", "is_qb_out_of_pocket", "is_throw_away", "is_drop", "is_catchable_ball",
    "is_contested_ball", "is_interception_worthy",
]


# dtypes for columns a season's file may lack, so joins and whens stay typed
_NULL_DTYPES: dict[str, pl.DataType] = {
    **{c: pl.Utf8 for c in ["offense_formation", "offense_personnel", "defense_personnel",
                             "defense_coverage_type", "defense_man_zone_type", "route",
                             "offense_players", "defense_players", "qb_location"]},
    **{c: pl.Int32 for c in ["defenders_in_box", "number_of_pass_rushers", "n_defense_box",
                              "n_pass_rushers", "n_blitzers", "n_offense_backfield"]},
    "time_to_throw": pl.Float64,
    **{c: pl.Boolean for c in ["was_pressure", "is_no_huddle", "is_motion", "is_play_action",
                                "is_screen_pass", "is_rpo", "is_trick_play", "is_qb_sneak",
                                "is_qb_out_of_pocket", "is_throw_away", "is_drop",
                                "is_catchable_ball", "is_contested_ball", "is_interception_worthy"]},
}


def _typed_null(c: str) -> pl.Expr:
    return pl.lit(None, dtype=_NULL_DTYPES.get(c, pl.Float64)).alias(c)


# --------------------------------------------------------------------------- loading


def _scan(dataset: str, season: int) -> pl.LazyFrame | None:
    p = raw_path(dataset, season)
    return pl.scan_parquet(p) if p.exists() else None


def _position_map(season: int) -> pl.LazyFrame | None:
    r = _scan("rosters_weekly", season)
    if r is None:
        return None
    return (
        r.filter(pl.col("gsis_id").is_not_null() & pl.col("position").is_not_null())
        .sort("week")
        .group_by("gsis_id")
        .agg(pl.col("position").last().alias("position"))
    )


def load_season(season: int) -> pl.DataFrame | None:
    pbp = _scan("pbp", season)
    if pbp is None:
        return None
    have = set(pbp.collect_schema().names())
    cols = [c for c in PBP_COLS if c in have]
    missing = [c for c in PBP_COLS if c not in have]
    df = pbp.select(cols).with_columns(pl.col("play_id").cast(pl.Int64))
    for c in missing:
        df = df.with_columns(_typed_null(c))

    part = _scan("participation", season)
    if part is not None:
        pc = set(part.collect_schema().names())
        sel = [pl.col("nflverse_game_id").alias("game_id"), pl.col("play_id").cast(pl.Int64)]
        sel += [pl.col(c) for c in PART_COLS if c in pc]
        p = part.select(sel).unique(subset=["game_id", "play_id"])
        df = df.join(p, on=["game_id", "play_id"], how="left")
    for c in PART_COLS:
        if c not in df.collect_schema().names():
            df = df.with_columns(_typed_null(c))

    ftn = _scan("ftn", season)
    if ftn is not None:
        fc = set(ftn.collect_schema().names())
        sel = [pl.col("nflverse_game_id").alias("game_id"),
               pl.col("nflverse_play_id").cast(pl.Int64).alias("play_id")]
        sel += [pl.col(c) for c in FTN_COLS if c in fc]
        f = ftn.select(sel).unique(subset=["game_id", "play_id"])
        df = df.join(f, on=["game_id", "play_id"], how="left")
    for c in FTN_COLS:
        if c not in df.collect_schema().names():
            df = df.with_columns(_typed_null(c))

    pos = _position_map(season)
    if pos is not None:
        df = df.join(pos.rename({"gsis_id": "receiver_player_id", "position": "target_pos_raw"}),
                     on="receiver_player_id", how="left")
        df = df.join(pos.rename({"gsis_id": "rusher_player_id", "position": "rusher_pos"}),
                     on="rusher_player_id", how="left")
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias("target_pos_raw"),
                             pl.lit(None, dtype=pl.Utf8).alias("rusher_pos"))
    return df.collect()


# --------------------------------------------------------------------------- features


def add_clock(df: pl.DataFrame) -> pl.DataFrame:
    """runoff_s = seconds from this snap to the next snap in the same half; timeout_after."""
    is_timeout_row = (pl.col("play_type") == "no_play") & pl.col("desc").str.starts_with("Timeout")
    is_snap = pl.col("play_type").is_not_null() & ~is_timeout_row
    df = df.sort(["game_id", "play_id"]).with_columns(
        is_snap.alias("_snap"), is_timeout_row.alias("_to")
    )
    df = df.with_columns(pl.col("_snap").cum_sum().over("game_id").alias("_grp"))
    df = df.with_columns(
        pl.col("_to").sum().over(["game_id", "_grp"]).gt(0).alias("timeout_after")
    )
    snaps = (
        df.filter(pl.col("_snap"))
        .select("game_id", "play_id", "game_half", "game_seconds_remaining")
        .with_columns(
            pl.col("game_seconds_remaining").shift(-1).over("game_id").alias("_next_gsr"),
            pl.col("game_half").shift(-1).over("game_id").alias("_next_half"),
        )
        .with_columns(
            pl.when(pl.col("_next_half") == pl.col("game_half"))
            .then(pl.col("game_seconds_remaining") - pl.col("_next_gsr"))
            .otherwise(None)
            .alias("runoff_s")
        )
        .select("game_id", "play_id", "runoff_s")
    )
    return df.join(snaps, on=["game_id", "play_id"], how="left").drop("_snap", "_to", "_grp")


def add_personnel_formation(df: pl.DataFrame) -> pl.DataFrame:
    """Vectorized via a lookup over the few hundred unique strings."""
    pairs = (
        df.select("offense_personnel", "offense_formation", "qb_location").unique()
    )
    rows = []
    for pers, form, qbl in pairs.iter_rows():
        p = parse_personnel(pers)
        rows.append({
            "offense_personnel": pers, "offense_formation": form, "qb_location": qbl,
            "personnel_group": p.group if p else None,
            "personnel_class": p.klass if p else None,
            "n_rb": p.rb if p else None, "n_te": p.te if p else None,
            "n_wr": p.wr if p else None, "n_ol": p.ol if p else None,
            "formation": normalize_formation(form, p, qbl),
        })
    lut = pl.DataFrame(rows, schema={
        "offense_personnel": pl.Utf8, "offense_formation": pl.Utf8, "qb_location": pl.Utf8,
        "personnel_group": pl.Utf8, "personnel_class": pl.Utf8, "n_rb": pl.Int32,
        "n_te": pl.Int32, "n_wr": pl.Int32, "n_ol": pl.Int32, "formation": pl.Utf8,
    })
    return df.join(lut, on=["offense_personnel", "offense_formation", "qb_location"], how="left",
                   nulls_equal=True)


def add_look(df: pl.DataFrame) -> pl.DataFrame:
    box = pl.coalesce(pl.col("defenders_in_box"), pl.col("n_defense_box")).cast(pl.Int32)
    rushers = pl.coalesce(pl.col("number_of_pass_rushers"), pl.col("n_pass_rushers")).cast(pl.Int32)
    light_max = cfg("playbook", "light_box_max")
    blitz_min = cfg("playbook", "blitz_min_rushers")
    df = df.with_columns(box.alias("box_count"), rushers.alias("rushers_count"))
    df = df.with_columns(
        pl.when(pl.col("box_count").is_null()).then(None)
        .when(pl.col("box_count") <= light_max).then(pl.lit("light")).otherwise(pl.lit("heavy"))
        .alias("box"),
        pl.when(pl.col("rushers_count").is_null() | (pl.col("rushers_count") <= 0)).then(None)
        .otherwise(pl.col("rushers_count") >= blitz_min).alias("blitz"),
    )
    return df


def _draw(rng: np.random.Generator, choices: list[str], weights: np.ndarray) -> str:
    w = weights / weights.sum()
    return choices[rng.choice(len(choices), p=w)]


def add_calls(df: pl.DataFrame, rng: np.random.Generator) -> pl.DataFrame:
    c = pl.col
    d = cfg("playbook", "depth_buckets")
    is_pass_family = (c("play_type") == "pass") | (c("qb_scramble") == 1) | (
        (c("play_type") == "no_play") & (c("pass") == 1))
    is_run_family = ((c("play_type") == "run") & (c("qb_scramble") != 1)) | (
        (c("play_type") == "no_play") & (c("rush") == 1) & (c("pass") != 1))
    onside = c("desc").str.contains("(?i)onside")

    thrown = (c("play_type") == "pass") & (c("sack") == 0) & c("air_yards").is_not_null()
    depth = (
        pl.when(~thrown).then(None)
        .when(c("air_yards") <= d["short_max_air_yards"]).then(pl.lit("short"))
        .when(c("air_yards") <= d["medium_max_air_yards"]).then(pl.lit("medium"))
        .otherwise(pl.lit("deep"))
    )
    hail = thrown & (c("air_yards") >= 30) & (c("air_yards") >= c("yardline_100") - 5) & (
        c("half_seconds_remaining") <= 15)
    sneak = (c("is_qb_sneak") == True) | (
        (c("play_type") == "run") & (c("qb_scramble") != 1) & (c("rusher_pos") == "QB")
        & (c("run_location") == "middle") & (c("ydstogo") <= 2) & c("is_qb_sneak").is_null())
    inside = (c("run_location") == "middle") | (c("run_gap") == "guard")
    outside = c("run_gap").is_in(["tackle", "end"])

    df = df.with_columns(
        depth.alias("depth"),
        pl.when(is_pass_family).then(c("pass_location"))
        .when(is_run_family).then(c("run_location")).otherwise(None).alias("direction"),
        pl.when(c("qb_kneel") == 1).then(pl.lit("kneel"))
        .when(c("qb_spike") == 1).then(pl.lit("spike"))
        .when(c("two_point_attempt") == 1).then(pl.lit("two_point"))
        .when(c("play_type") == "field_goal").then(pl.lit("field_goal"))
        .when(c("play_type") == "punt").then(pl.lit("punt"))
        .when(c("play_type") == "extra_point").then(pl.lit("extra_point"))
        .when((c("play_type") == "kickoff") & onside).then(pl.lit("onside_kick"))
        .when(c("play_type") == "kickoff").then(pl.lit("kickoff"))
        .when(c("is_trick_play") == True).then(pl.lit("gadget"))
        .when(sneak).then(pl.lit("qb_sneak"))
        .when(c("is_rpo") == True).then(pl.lit("rpo"))
        .when((c("is_screen_pass") == True) | (c("route") == "SCREEN")).then(pl.lit("screen"))
        .when(hail).then(pl.lit("hail_mary"))
        .when(is_pass_family & (c("is_play_action") == True)).then(pl.lit("pa"))
        .when(is_pass_family).then(pl.lit("pass"))
        .when(is_run_family & inside).then(pl.lit("run_inside"))
        .when(is_run_family & outside).then(pl.lit("run_outside"))
        .when(is_run_family).then(pl.lit("run_unknown"))
        .otherwise(None)
        .alias("family"),
    )

    # ---- seeded draws for rows whose call needs a depth/direction they don't have
    known = df.filter(c("family").is_in(["pass", "pa"]) & c("depth").is_not_null())
    # P(depth | down group) x pressure rate(depth): data-derived weights for sacks/scrambles
    pr = known.filter(c("was_pressure").is_not_null()).group_by("depth").agg(
        pl.col("was_pressure").cast(pl.Float64).mean().alias("p"))
    pressure = {k: v for k, v in pr.iter_rows()} or {"short": 1, "medium": 1, "deep": 1}
    depths = ["short", "medium", "deep"]
    down_key = pl.when(c("down").is_null()).then(1).otherwise(c("down")).cast(pl.Int32)
    known = known.with_columns(down_key.alias("_dk"))
    pd_ = known.group_by("_dk", "depth").len().to_dict(as_series=False)
    depth_w: dict[int, np.ndarray] = {}
    for dk in (1, 2, 3, 4):
        w = np.array([
            sum(n for k, dd, n in zip(pd_["_dk"], pd_["depth"], pd_["len"], strict=True)
                if k == dk and dd == x) for x in depths], dtype=float) + 1.0
        depth_w[dk] = w * np.array([pressure.get(x, 1.0) for x in depths])
    dirs = ["left", "middle", "right"]
    dd_ = known.filter(c("direction").is_not_null()).group_by("depth", "direction").len() \
        .to_dict(as_series=False)
    dir_w = {x: np.array([
        sum(n for dd, di, n in zip(dd_["depth"], dd_["direction"], dd_["len"], strict=True)
            if dd == x and di == y) for y in dirs], dtype=float) + 1.0 for x in depths}
    runs = df.filter(c("family").is_in(["run_inside", "run_outside"]))
    rin = runs.filter(c("family") == "run_inside").height + 1.0
    rout = runs.filter(c("family") == "run_outside").height + 1.0
    run_dir = runs.filter(c("direction").is_not_null()).group_by("direction").len() \
        .to_dict(as_series=False)
    run_dir_w = np.array([sum(n for di, n in zip(run_dir["direction"], run_dir["len"], strict=True)
                              if di == y) for y in dirs], dtype=float) + 1.0

    need = df.filter(
        (c("family").is_in(["pass", "pa"]) & (c("depth").is_null() | c("direction").is_null()))
        | (c("family") == "run_unknown")
        | (c("family").is_in(["run_inside", "run_outside"]) & c("direction").is_null())
    ).select("game_id", "play_id", "family", "depth", "direction", "down")
    out = {"game_id": [], "play_id": [], "depth_d": [], "direction_d": [], "family_d": []}
    for gid, pid, fam, dep, dire, down in need.iter_rows():
        dk = int(down) if down is not None else 1
        if fam in ("pass", "pa"):
            dep2 = dep if dep is not None else _draw(rng, depths, depth_w[dk])
            dire2 = dire if dire is not None else _draw(rng, dirs, dir_w[dep2])
            fam2 = fam
        else:
            fam2 = fam if fam != "run_unknown" else _draw(rng, ["run_inside", "run_outside"],
                                                          np.array([rin, rout]))
            dep2 = None
            dire2 = dire if dire is not None else _draw(rng, dirs, run_dir_w)
        out["game_id"].append(gid); out["play_id"].append(pid)
        out["depth_d"].append(dep2); out["direction_d"].append(dire2); out["family_d"].append(fam2)
    drawn = pl.DataFrame(out, schema={"game_id": pl.Utf8, "play_id": pl.Int64, "depth_d": pl.Utf8,
                                      "direction_d": pl.Utf8, "family_d": pl.Utf8})
    df = df.join(drawn, on=["game_id", "play_id"], how="left").with_columns(
        pl.coalesce(c("depth_d"), c("depth")).alias("depth"),
        pl.coalesce(c("direction_d"), c("direction")).alias("direction"),
        pl.coalesce(c("family_d"), c("family")).alias("family"),
        c("depth_d").is_not_null().alias("depth_drawn"),
    ).drop("depth_d", "direction_d", "family_d")

    # ---- final call string
    df = df.with_columns(
        pl.when(c("family").is_in(["pass", "pa"]))
        .then(pl.concat_str([c("family"), c("depth"), c("direction")], separator="_"))
        .when(c("family").is_in(["run_inside", "run_outside"]))
        .then(pl.concat_str([c("family"), c("direction")], separator="_"))
        .otherwise(c("family"))
        .alias("call"),
        pl.when(c("family").is_in(["run_inside", "run_outside", "qb_sneak"]))
        .then(pl.concat_str([c("box"), pl.lit("any")], separator="_"))
        .when(c("box").is_null()).then(None)
        .when(c("blitz").is_null()).then(pl.concat_str([c("box"), pl.lit("any")], separator="_"))
        .otherwise(pl.concat_str([c("box"), pl.when(c("blitz")).then(pl.lit("blitz")).otherwise(pl.lit("base"))], separator="_"))
        .alias("look"),
    )
    return df


def add_outcomes(df: pl.DataFrame) -> pl.DataFrame:
    c = pl.col
    return df.with_columns(
        (c("play_type") == "no_play").alias("nullified"),
        ((c("interception") == 1) | (c("fumble_lost") == 1)).alias("turnover"),
        (c("penalty_team") == c("posteam")).alias("penalty_on_offense"),
        pl.when(c("target_pos_raw").is_in(["FB", "HB"])).then(pl.lit("RB"))
        .when(c("target_pos_raw").is_in(["WR", "TE", "RB", "QB"])).then(c("target_pos_raw"))
        .when(c("target_pos_raw").is_not_null()).then(pl.lit("OTHER")).otherwise(None)
        .alias("target_pos"),
        ((c("incomplete_pass") == 1) | (c("out_of_bounds") == 1) | (c("touchdown") == 1)
         | (c("interception") == 1) | (c("fumble_lost") == 1) | (c("penalty") == 1)
         | (c("safety") == 1) | c("timeout_after")).alias("clock_stops"),
    )


OUT_COLS = [
    # identity + situation
    "season", "week", "season_type", "game_id", "play_id", "posteam", "defteam", "home_team",
    "away_team", "qtr", "game_half", "down", "ydstogo", "yardline_100", "goal_to_go",
    "score_differential", "half_seconds_remaining", "quarter_seconds_remaining",
    "game_seconds_remaining", "posteam_timeouts_remaining", "defteam_timeouts_remaining",
    "fixed_drive", "fixed_drive_result", "wp", "vegas_wp", "wpa", "epa",
    # the call
    "family", "call", "depth", "direction", "depth_drawn", "personnel_group", "personnel_class",
    "n_rb", "n_te", "n_wr", "n_ol", "formation", "no_huddle", "shotgun", "is_motion",
    "is_play_action", "is_rpo", "is_screen_pass", "target_pos", "route",
    # the look
    "look", "box", "blitz", "box_count", "rushers_count", "n_blitzers", "defense_personnel",
    "defense_coverage_type", "defense_man_zone_type",
    # the outcome
    "yards_gained", "first_down", "touchdown", "turnover", "interception", "fumble_lost",
    "sack", "complete_pass", "incomplete_pass", "out_of_bounds", "safety", "return_yards",
    "return_touchdown", "penalty", "penalty_type", "penalty_yards", "penalty_on_offense",
    "nullified", "qb_scramble", "runoff_s", "timeout_after", "clock_stops",
    # animation hints
    "air_yards", "yards_after_catch", "time_to_throw", "was_pressure", "is_throw_away",
    "is_drop", "is_qb_out_of_pocket",
    # special teams
    "kick_distance", "field_goal_result", "extra_point_result", "two_point_conv_result",
    "punt_blocked", "punt_inside_twenty", "punt_in_endzone", "punt_out_of_bounds", "punt_downed",
    "punt_fair_catch", "kickoff_in_endzone", "kickoff_out_of_bounds", "kickoff_fair_catch",
    "own_kickoff_recovery", "touchback",
    # who was on the field
    "offense_players", "defense_players",
]


def build_season(season: int, rng: np.random.Generator) -> pl.DataFrame | None:
    df = load_season(season)
    if df is None:
        return None
    df = add_clock(df)
    df = df.filter(pl.col("play_type").is_not_null() & pl.col("posteam").is_not_null())
    df = add_personnel_formation(df)
    df = add_look(df)
    df = add_calls(df, rng)
    df = add_outcomes(df)
    df = df.filter(pl.col("family").is_not_null())
    return df.select([c for c in OUT_COLS if c in df.columns])


def cmd_build(args: argparse.Namespace) -> int:
    seasons = parse_seasons(args.seasons)
    rng = np.random.default_rng(cfg("pipeline", "seed"))
    parts = []
    for s in seasons:
        df = build_season(s, rng)
        if df is None:
            print(f"  {s}: no pbp file, skipped")
            continue
        print(f"  {s}: {df.height:,} rows")
        parts.append(df)
    out = pl.concat(parts, how="diagonal_relaxed")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out.write_parquet(ROWS_PATH, compression="zstd")
    print(f"Wrote {ROWS_PATH} ({out.height:,} rows, {out.width} cols)")
    return cmd_report(args)


# --------------------------------------------------------------------------- report

OFFENSE_CALL_FAMILIES = ["run_inside", "run_outside", "qb_sneak", "pass", "pa", "rpo", "screen",
                         "hail_mary", "gadget"]
RUN_LOOKS = ["light_any", "heavy_any"]
PASS_LOOKS = ["light_base", "light_blitz", "heavy_base", "heavy_blitz"]


def _cells(df: pl.DataFrame, call_col: str) -> pl.DataFrame:
    """Count rows per (call, look) over the looks that call can be sampled under."""
    runs = df.filter(pl.col("family").is_in(["run_inside", "run_outside", "qb_sneak"]))
    passes = df.filter(pl.col("family").is_in(["pass", "pa", "rpo", "screen", "hail_mary", "gadget"]))
    # pass rows whose blitz is unknown ('<box>_any') can only feed the box-level backoff
    pr = passes.filter(pl.col("look").is_in(PASS_LOOKS))
    rr = runs.filter(pl.col("look").is_in(RUN_LOOKS))
    grid = []
    for sub, looks in ((rr, RUN_LOOKS), (pr, PASS_LOOKS)):
        calls = sub.select(call_col).unique().to_series().to_list()
        counts = sub.group_by(call_col, "look").len().to_dict(as_series=False)
        have = {(a, b): n for a, b, n in zip(counts[call_col], counts["look"], counts["len"], strict=True)}
        for call in sorted(calls):
            for look in looks:
                grid.append({"call": call, "look": look, "n": have.get((call, look), 0)})
    return pl.DataFrame(grid)


def _pivot_md(cells: pl.DataFrame, min_n: int) -> str:
    looks = [lk for lk in RUN_LOOKS + PASS_LOOKS if lk in cells["look"].unique().to_list()]
    piv = cells.pivot(on="look", index="call", values="n").fill_null(0)
    piv = piv.select(["call"] + [lk for lk in looks if lk in piv.columns])
    hdr = "| call | " + " | ".join(piv.columns[1:]) + " |"
    sep = "|---|" + "|".join("---:" for _ in piv.columns[1:]) + "|"
    lines = [hdr, sep]
    for row in piv.iter_rows():
        cells_s = []
        for v in row[1:]:
            cells_s.append(f"**{v:,}**" if v < min_n and v > 0 else (f"{v:,}" if v else "·"))
        lines.append(f"| {row[0]} | " + " | ".join(cells_s) + " |")
    return "\n".join(lines)


def cmd_report(args: argparse.Namespace) -> int:
    df = pl.read_parquet(ROWS_PATH)
    min_n = cfg("playbook", "min_bucket_size")
    seasons = sorted(df["season"].unique().to_list())
    md = [(f"# Playbook bucket report\n\nSeasons {seasons[0]}-{seasons[-1]}, {df.height:,} plays. "
          f"Minimum bucket size {min_n}. Bold = below minimum, · = empty.\n")]

    # Family-level overview
    fam = df.group_by("family").len().sort("len", descending=True)
    md.append("## Plays per call family\n")
    md.append("| family | plays |\n|---|---:|")
    md += [f"| {f} | {n:,} |" for f, n in fam.iter_rows()]

    def section(title: str, sub: pl.DataFrame, call_col: str) -> dict:
        cells = _cells(sub, call_col)
        # only count cells where a look is defined for that call family
        total = cells.height
        ok = cells.filter(pl.col("n") >= min_n).height
        md.append(f"\n## {title}\n")
        md.append(f"Cells >= {min_n}: **{ok}/{total} ({100 * ok / total:.1f}%)**. "
                  f"Exit criterion: 90%.\n")
        md.append(_pivot_md(cells, min_n))
        return {"ok": ok, "total": total}

    off = df.filter(pl.col("family").is_in(OFFENSE_CALL_FAMILIES))
    r_full = section("Full option x look (what the player actually picks: type x depth x direction)",
                     off, "call")
    r_fam = section("Call family x look (coarse backoff level)", off, "family")
    off_recent = off.filter(pl.col("season") >= cfg("seasons", "spots_first"))
    r_recent = section(f"Full option x look, seasons {cfg('seasons', 'spots_first')}+ only",
                       off_recent, "call")

    # Personnel x formation coverage, for the backoff design
    md.append("\n## Personnel class x formation (all offensive plays)\n")
    pf = off.filter(pl.col("personnel_class").is_not_null() & pl.col("formation").is_not_null()) \
        .group_by("personnel_class", "formation").len() \
        .pivot(on="formation", index="personnel_class", values="len").fill_null(0)
    pf = pf.select(["personnel_class"] + [f for f in FORMATIONS if f in pf.columns])
    pf = pf.with_columns(pl.col("personnel_class").cast(pl.Enum(list(PERSONNEL_CLASSES)))).sort("personnel_class")
    md.append("| personnel | " + " | ".join(pf.columns[1:]) + " |")
    md.append("|---|" + "|".join("---:" for _ in pf.columns[1:]) + "|")
    md += ["| " + str(r[0]) + " | " + " | ".join(f"{v:,}" for v in r[1:]) + " |" for r in pf.iter_rows()]

    # Late-game subset: what the spots will actually sample from
    late = off.filter(((pl.col("qtr") == 4) & (pl.col("quarter_seconds_remaining") <= cfg("spots", "q4_max_seconds_left")))
                      | ((pl.col("qtr") == 2) & (pl.col("quarter_seconds_remaining") <= cfg("spots", "q2_max_seconds_left"))))
    r_late = section("Full option x look, late-game plays only (Q4 <= 2:30 or Q2 <= 2:00)", late, "call")

    md.append("\n## Depth / direction draws\n")
    n_drawn = off.filter(pl.col("depth_drawn")).height
    md.append(f"{n_drawn:,} pass-family rows ({100 * n_drawn / max(1, off.filter(pl.col('family').is_in(['pass', 'pa'])).height):.1f}% of dropbacks) "
              "had no air yards (sack, scramble, throwaway, nullified) and were given a seeded depth/direction "
              "weighted by P(depth | down) x pressure rate(depth).")

    text = "\n".join(md) + "\n"
    REPORT_PATH.write_text(text)
    print(text)
    print(f"Wrote {REPORT_PATH}")
    summary = {"full": r_full, "family": r_fam, "recent": r_recent, "late": r_late}
    print("SUMMARY", summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--seasons")
    b.set_defaults(fn=cmd_build)
    r = sub.add_parser("report")
    r.add_argument("--seasons")
    r.set_defaults(fn=cmd_report)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
