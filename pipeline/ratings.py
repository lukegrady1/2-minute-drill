"""Player ratings (40-99) per season, own derivation from nflverse box-score events.

    uv run python pipeline/ratings.py        -> data/processed/ratings.parquet
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.config import PROCESSED_DIR, cfg
from pipeline.ingest import raw_path

RATINGS_PATH = PROCESSED_DIR / "ratings.parquet"

GROUP = {
    "QB": "QB", "RB": "RB", "FB": "RB", "HB": "RB", "WR": "WR", "TE": "TE",
    "T": "OL", "G": "OL", "C": "OL", "OL": "OL", "OT": "OL", "OG": "OL",
    "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "EDGE": "DL",
    "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB",
    "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "DB": "DB",
    "K": "K", "P": "P", "LS": "LS",
}
SHRINK = {"QB": 150, "RB": 80, "WR": 40, "TE": 40, "OL": 100, "DL": 250, "LB": 250, "DB": 300, "K": 20, "P": 25}


def _z(col: str) -> pl.Expr:
    return ((pl.col(col) - pl.col(col).mean()) / (pl.col(col).std() + 1e-9)).fill_null(0.0)


def season_ratings(season: int) -> pl.DataFrame | None:
    c = pl.col
    if not raw_path("pbp", season).exists():
        return None
    pbp = pl.scan_parquet(raw_path("pbp", season))
    ros = pl.read_parquet(raw_path("rosters_weekly", season), columns=["week", "team", "position", "jersey_number", "full_name", "gsis_id"])
    ros = ros.filter(c("gsis_id").is_not_null()).sort("week").group_by("gsis_id").agg(
        c("team").last(), c("position").last(), c("jersey_number").last(), c("full_name").last())
    ros = ros.with_columns(c("position").replace_strict(GROUP, default="OTHER").alias("grp"))

    plays = pbp.filter(c("play_type").is_in(["pass", "run"])).collect()
    team_off = plays.group_by("posteam").agg(pl.len().alias("team_snaps"))
    # ---- snap counts (participation) or depth-chart prior (2026)
    part_path = raw_path("participation", season)
    if part_path.exists():
        part = pl.read_parquet(part_path, columns=["nflverse_game_id", "play_id", "possession_team", "offense_players", "defense_players"])
        snaps = pl.concat([
            part.select(c("offense_players").str.split(";").alias("ids")).explode("ids"),
            part.select(c("defense_players").str.split(";").alias("ids")).explode("ids"),
        ]).filter(c("ids").is_not_null() & (c("ids") != "")).group_by("ids").len().rename({"ids": "gsis_id", "len": "snaps"})
        snaps = snaps.join(ros.select("gsis_id", "team"), on="gsis_id", how="left").join(team_off, left_on="team", right_on="posteam", how="left")
        snaps = snaps.with_columns((c("snaps") / c("team_snaps")).clip(0, 1.2).alias("snap_share")).select("gsis_id", "snaps", "snap_share")
    else:
        dc = pl.read_parquet(raw_path("depth_charts", season)) if raw_path("depth_charts", season).exists() else None
        if dc is not None and "pos_rank" in dc.columns:
            dc = dc.sort("dt").group_by("gsis_id").agg(c("pos_rank").last())
            snaps = dc.with_columns(pl.when(c("pos_rank") == 1).then(0.8).when(c("pos_rank") == 2).then(0.3).otherwise(0.1).alias("snap_share"),
                                    pl.lit(0).alias("snaps")).select("gsis_id", "snaps", "snap_share")
        else:
            snaps = ros.select("gsis_id", pl.lit(0).alias("snaps"), pl.lit(0.3).alias("snap_share"))

    # ---- offensive stats
    drop = plays.filter(c("qb_dropback") == 1).group_by("passer_player_id").agg(
        c("qb_epa").mean().alias("qb_epa"), c("cpoe").mean().alias("cpoe"), pl.len().alias("n_qb")).rename({"passer_player_id": "gsis_id"})
    rush = plays.filter(c("rusher_player_id").is_not_null() & (c("qb_scramble") != 1)).group_by("rusher_player_id").agg(
        c("epa").mean().alias("rush_epa"), c("success").mean().alias("rush_succ"), pl.len().alias("n_rush")).rename({"rusher_player_id": "gsis_id"})
    tgt = plays.filter(c("receiver_player_id").is_not_null()).group_by("receiver_player_id").agg(
        c("epa").mean().alias("tgt_epa"), c("yards_gained").mean().alias("ypt"), pl.len().alias("n_tgt")).rename({"receiver_player_id": "gsis_id"})
    team_pass = plays.filter(c("pass") == 1).group_by("posteam").agg(pl.len().alias("team_pass"))
    # team-level OL: sack rate and rush epa
    team_ol = plays.group_by("posteam").agg(
        (c("sack").sum() / c("pass").sum()).alias("sack_rate"), c("epa").filter(c("rush") == 1).mean().alias("team_rush_epa"))
    # ---- defensive stats (per player event counts)
    def count(colname: str, w: float = 1.0) -> pl.DataFrame:
        return plays.filter(c(colname).is_not_null()).group_by(colname).agg((pl.len() * w).alias("v")).rename({colname: "gsis_id"})
    events = {
        "sacks": [("sack_player_id", 1.0), ("half_sack_1_player_id", 0.5), ("half_sack_2_player_id", 0.5)],
        "hits": [("qb_hit_1_player_id", 1.0), ("qb_hit_2_player_id", 1.0)],
        "tfl": [("tackle_for_loss_1_player_id", 1.0), ("tackle_for_loss_2_player_id", 1.0)],
        "tackles": [("solo_tackle_1_player_id", 1.0), ("solo_tackle_2_player_id", 1.0), ("assist_tackle_1_player_id", 0.5),
                    ("assist_tackle_2_player_id", 0.5), ("tackle_with_assist_1_player_id", 0.7)],
        "pd": [("pass_defense_1_player_id", 1.0), ("pass_defense_2_player_id", 1.0)],
        "ints": [("interception_player_id", 1.0)],
        "ff": [("forced_fumble_player_1_player_id", 1.0)],
    }
    dstats = ros.select("gsis_id")
    for name, cols in events.items():
        acc = pl.concat([count(col, w) for col, w in cols]).group_by("gsis_id").agg(c("v").sum().alias(name))
        dstats = dstats.join(acc, on="gsis_id", how="left")
    team_def = plays.group_by("defteam").agg(
        c("epa").filter(c("pass") == 1).mean().alias("team_pass_epa_allowed"), c("epa").filter(c("rush") == 1).mean().alias("team_rush_epa_allowed"))
    # ---- kickers and punters
    fg = pbp.filter(c("play_type") == "field_goal").select("kicker_player_id", "kick_distance", "field_goal_result", "roof", "wind", "temp").collect()
    if fg.height:
        import json

        from sim.models import fg_prob
        fgm = json.loads((PROCESSED_DIR / "models.json").read_text())["fg"]
        exp = [fg_prob(fgm, d or 40, (r or "") in ("dome", "closed"), w or 0.0, t or 60.0) for d, r, w, t in
               zip(fg["kick_distance"], fg["roof"], fg["wind"], fg["temp"], strict=True)]
        fg = fg.with_columns(pl.Series("exp", exp), (c("field_goal_result") == "made").cast(pl.Float64).alias("made"))
        kick = fg.group_by("kicker_player_id").agg((c("made") - c("exp")).mean().alias("fg_resid"), pl.len().alias("n_fg")).rename({"kicker_player_id": "gsis_id"})
    else:
        kick = pl.DataFrame({"gsis_id": [], "fg_resid": [], "n_fg": []})
    pu = pbp.filter((c("play_type") == "punt") & c("kick_distance").is_not_null()).select("punter_player_id", "kick_distance", "return_yards", "yardline_100").collect()
    pu = pu.with_columns((c("kick_distance") - c("return_yards").fill_null(0)).alias("net"), (c("yardline_100") // 10).alias("zone"))
    pu = pu.with_columns((c("net") - c("net").mean().over("zone")).alias("net_oe"))
    punt = pu.group_by("punter_player_id").agg(c("net_oe").mean().alias("punt_oe"), pl.len().alias("n_punt")).rename({"punter_player_id": "gsis_id"})

    df = (ros.join(snaps, on="gsis_id", how="left").join(drop, on="gsis_id", how="left").join(rush, on="gsis_id", how="left")
          .join(tgt, on="gsis_id", how="left").join(team_pass, left_on="team", right_on="posteam", how="left")
          .join(team_ol, left_on="team", right_on="posteam", how="left").join(dstats, on="gsis_id", how="left")
          .join(team_def, left_on="team", right_on="defteam", how="left").join(kick, on="gsis_id", how="left").join(punt, on="gsis_id", how="left"))
    df = df.with_columns(c("snap_share").fill_null(0.0), c("snaps").fill_null(0))
    for name in events:
        df = df.with_columns(c(name).fill_null(0.0))
    df = df.with_columns((c("snaps").cast(pl.Float64) + 1.0).alias("dsn"))

    # ---- per-group raw score and sample size
    def group_score(g: str) -> tuple[pl.Expr, pl.Expr]:
        if g == "QB":
            return (_z("qb_epa") + _z("cpoe")), c("n_qb").fill_null(0)
        if g == "RB":
            return (_z("rush_epa") + 0.7 * _z("rush_succ") + 0.4 * _z("tgt_epa")), c("n_rush").fill_null(0) + 0.5 * c("n_tgt").fill_null(0)
        if g in ("WR", "TE"):
            return (_z("tgt_epa") + _z("ypt") + 0.8 * _z("tgt_share")), c("n_tgt").fill_null(0)
        if g == "OL":
            # team-level signal only, so cap its weight at 0.6 (150 / (150 + 100))
            return (-_z("sack_rate") + _z("team_rush_epa")), pl.lit(150.0)
        if g == "DL":
            return (_z("press_rate") + 0.5 * _z("tfl_rate") - 0.3 * _z("team_rush_epa_allowed")), c("snaps").cast(pl.Float64)
        if g == "LB":
            return (_z("tkl_rate") + 0.7 * _z("tfl_rate") + 0.5 * _z("press_rate")), c("snaps").cast(pl.Float64)
        if g == "DB":
            return (_z("pd_rate") + 0.5 * _z("tkl_rate") - 0.5 * _z("team_pass_epa_allowed")), c("snaps").cast(pl.Float64)
        if g == "K":
            return _z("fg_resid"), c("n_fg").fill_null(0)
        if g == "P":
            return _z("punt_oe"), c("n_punt").fill_null(0)
        return pl.lit(0.0), pl.lit(0.0)

    df = df.with_columns(
        (c("n_tgt").fill_null(0) / c("team_pass").fill_null(500)).alias("tgt_share"),
        ((c("sacks") + 0.5 * c("hits") + c("ff")) / c("dsn") * 100).alias("press_rate"),
        (c("tfl") / c("dsn") * 100).alias("tfl_rate"),
        (c("tackles") / c("dsn") * 100).alias("tkl_rate"),
        ((c("pd") + 2 * c("ints")) / c("dsn") * 100).alias("pd_rate"),
    )
    parts = []
    for g, k in SHRINK.items():
        sub = df.filter(c("grp") == g)
        if sub.height == 0:
            continue
        # z-scores computed among players with real involvement so backups do not define the scale
        active = sub.filter(c("snap_share") >= 0.2) if g not in ("K", "P") else sub.filter(c("snaps") >= 0)
        score, n = group_score(g)
        act = active.with_columns(score.alias("raw"), n.alias("nn"))
        # map every player through the active population's mean/std
        mu, sd = act["raw"].mean() or 0.0, act["raw"].std() or 1.0
        sub = sub.with_columns(score.alias("raw0"), n.alias("nn"))
        # recompute raw for all using the active mean/std by re-expressing z against active stats
        sub = sub.with_columns(((c("raw0") - (sub.filter(c("snap_share") >= 0.2)["raw0"].mean() or 0.0)) / ((sub.filter(c("snap_share") >= 0.2)["raw0"].std() or 1.0))).alias("z"))
        sub = sub.with_columns((c("nn") / (c("nn") + k)).alias("w"))
        # stat percentile among the active population
        zs = np.sort(act.with_columns(((c("raw") - mu) / sd).alias("z"))["z"].to_numpy())
        pct = np.searchsorted(zs, sub["z"].to_numpy(), side="right") / max(1, len(zs))
        prior = np.where(sub["snap_share"].to_numpy() >= 0.6, 0.5, np.where(sub["snap_share"].to_numpy() >= 0.3, 0.3, 0.15))
        w = sub["w"].to_numpy()
        blended = w * pct + (1 - w) * prior
        rating = np.round(cfg("ratings", "min") + (cfg("ratings", "max") - cfg("ratings", "min")) * np.power(blended, 0.67)).astype(int)
        parts.append(sub.with_columns(pl.Series("stat_pct", pct), pl.Series("rating", rating)).select(
            "gsis_id", "team", "position", "grp", pl.col("jersey_number").cast(pl.Int32), "full_name",
            pl.col("snaps").cast(pl.Int64), pl.col("snap_share").cast(pl.Float64), "stat_pct", pl.col("rating").cast(pl.Int32)))
    out = pl.concat(parts, how="diagonal_relaxed").with_columns(pl.lit(season).cast(pl.Int32).alias("season"))
    return out


def main() -> int:
    seasons = list(range(cfg("seasons", "spots_first"), cfg("seasons", "ingest_last") + 1))
    parts = [r for s in seasons if (r := season_ratings(s)) is not None]
    out = pl.concat(parts, how="diagonal_relaxed")
    out.write_parquet(RATINGS_PATH, compression="zstd")
    print(f"Wrote {RATINGS_PATH}: {out.height:,} player-seasons")
    starters = out.filter(pl.col("snap_share") >= 0.6)
    print(starters.group_by("grp").agg(pl.col("rating").median().alias("median_starter"), pl.col("rating").min().alias("min"),
                                       pl.col("rating").max().alias("max"), pl.len()).sort("grp"))
    print(out.filter((pl.col("season") == 2025) & (pl.col("grp") == "QB")).sort("rating", descending=True).select("full_name", "team", "rating", "snap_share").head(8))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
