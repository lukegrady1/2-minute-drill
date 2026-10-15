"""Fit the models the simulator needs and write data/processed/models.json.

    uv run python pipeline/wp_model.py

Contents of models.json (all plain numbers so the TS engine reads it unchanged):
  wp          logistic regression on engineered features (see wp_features) -> P(posteam wins)
  fg          logistic on distance, distance^2, dome, wind, temp -> P(make)
  pat         extra point and two-point success rates (2016+)
  kickoff     receiving team's start yardline_100 histogram under 2025 rules, return-TD rate,
              onside recovery rate and resulting spots, safety free-kick start
  punt        per punting-zone histogram of the receiving team's start yardline_100, block rate
  clock       play duration by family (from stopped-clock plays) and tempo (pre-snap seconds)
              distributions for hurry / normal / milk
  looks       P(light box), P(blitz) by down x distance bucket
  tendencies  P(policy call | situation) for the auto-policy, with backoff levels
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.config import PROCESSED_DIR, cfg
from pipeline.ingest import raw_path
from pipeline.playbook import ROWS_PATH

MODELS_PATH = PROCESSED_DIR / "models.json"

# ---------------------------------------------------------------- shared feature definitions
# These are mirrored in sim/models.py and engine/models.ts. Keep the order identical.

WP_FEATURE_NAMES = [
    "sd", "sd_x_isqrt", "isqrt", "sd_x_t", "yl", "yl_x_isqrt", "down2", "down3", "down4",
    "log_togo", "down4_x_togo", "to_diff", "to_diff_x_isqrt", "spread", "spread_x_sqrt_t",
    "half1", "recv2h_x_half1", "sd_x_half1", "goal_to_go", "lead_x_isqrt", "ot",
]


def wp_features(sd, t, yl, down, togo, to_off, to_def, spread, half1, recv2h, gtg, ot):
    """Vectorized (numpy) feature builder. t = game seconds remaining in regulation."""
    t = np.asarray(t, dtype=float)
    sd = np.asarray(sd, dtype=float)
    isqrt = 1.0 / np.sqrt(t + 1.0)
    sqrt_t = np.sqrt(np.clip(t, 0, 3600) / 3600.0)
    yl = np.asarray(yl, dtype=float) / 100.0
    down = np.asarray(down, dtype=float)
    togo = np.asarray(togo, dtype=float)
    to_diff = np.asarray(to_off, dtype=float) - np.asarray(to_def, dtype=float)
    spread = np.asarray(spread, dtype=float)
    half1 = np.asarray(half1, dtype=float)
    recv2h = np.asarray(recv2h, dtype=float)
    gtg = np.asarray(gtg, dtype=float)
    ot = np.asarray(ot, dtype=float)
    lead = np.sign(sd)
    return np.column_stack([
        sd, sd * isqrt, isqrt, sd * t / 3600.0, yl, yl * isqrt,
        (down == 2), (down == 3), (down == 4),
        np.log1p(togo), (down == 4) * np.log1p(togo),
        to_diff, to_diff * isqrt, spread, spread * sqrt_t,
        half1, recv2h * half1, sd * half1, gtg, lead * isqrt, ot,
    ]).astype(float)


def fit_wp() -> dict:
    parts = []
    for s in range(cfg("seasons", "ingest_first"), cfg("seasons", "ingest_last") + 1):
        p = raw_path("pbp", s)
        if not p.exists():
            continue
        lf = pl.scan_parquet(p).select(
            "game_id", "play_id", "posteam", "home_team", "qtr", "down", "ydstogo", "yardline_100",
            "score_differential", "game_seconds_remaining", "posteam_timeouts_remaining",
            "defteam_timeouts_remaining", "spread_line", "goal_to_go", "result", "play_type",
            "game_half", "vegas_wp", "season_type",
        ).filter(pl.col("down").is_not_null() & pl.col("posteam").is_not_null()
                 & pl.col("result").is_not_null() & (pl.col("result") != 0)
                 & pl.col("score_differential").is_not_null())
        # who receives the 2H kickoff
        r2h = (pl.scan_parquet(p).filter((pl.col("play_type") == "kickoff") & (pl.col("qtr") == 3))
               .sort("play_id").group_by("game_id").agg(pl.col("posteam").first().alias("receive_2h")))
        parts.append(lf.join(r2h, on="game_id", how="left").collect().with_columns(pl.col("goal_to_go").cast(pl.Float64), pl.col("down").cast(pl.Float64), pl.col("ydstogo").cast(pl.Float64)))
    df = pl.concat(parts, how="diagonal_relaxed")
    is_home = pl.col("posteam") == pl.col("home_team")
    df = df.with_columns(
        pl.when(is_home).then(pl.col("result")).otherwise(-pl.col("result")).alias("margin"),
        pl.when(is_home).then(pl.col("spread_line")).otherwise(-pl.col("spread_line")).fill_null(0).alias("spread"),
        (pl.col("game_half") == "Half1").cast(pl.Int8).alias("half1"),
        (pl.col("receive_2h") == pl.col("posteam")).cast(pl.Int8).fill_null(0).alias("recv2h"),
        (pl.col("qtr") >= 5).cast(pl.Int8).alias("ot"),
    )
    # In OT, "game seconds remaining" from nflfastR is 0; give OT rows a small positive clock.
    df = df.with_columns(pl.when(pl.col("ot") == 1).then(pl.lit(60.0)).otherwise(pl.col("game_seconds_remaining")).alias("t"))
    X = wp_features(df["score_differential"], df["t"], df["yardline_100"], df["down"], df["ydstogo"],
                    df["posteam_timeouts_remaining"].fill_null(3), df["defteam_timeouts_remaining"].fill_null(3),
                    df["spread"], df["half1"], df["recv2h"], df["goal_to_go"].fill_null(0), df["ot"])
    y = (df["margin"] > 0).to_numpy().astype(int)
    model = LogisticRegression(max_iter=2000, C=10.0)
    model.fit(X, y)
    p = model.predict_proba(X)[:, 1]
    vegas = df["vegas_wp"].to_numpy()
    mask = ~np.isnan(vegas)
    mae_vs_vegas = float(np.mean(np.abs(p[mask] - vegas[mask])))
    ll = float(-np.mean(y * np.log(p + 1e-9) + (1 - y) * np.log(1 - p + 1e-9)))
    # calibration by decile
    bins = np.clip((p * 10).astype(int), 0, 9)
    calib = [[float(np.mean(p[bins == b])), float(np.mean(y[bins == b])), int((bins == b).sum())]
             for b in range(10) if (bins == b).sum() > 0]
    print(f"WP: {len(y):,} rows, logloss {ll:.4f}, MAE vs vegas_wp {mae_vs_vegas:.4f}")
    for pb, yb, n in calib:
        print(f"   pred {pb:.2f} -> actual {yb:.2f}  (n={n:,})")
    return {
        "features": WP_FEATURE_NAMES,
        "coef": [float(c) for c in model.coef_[0]],
        "intercept": float(model.intercept_[0]),
        "fit": {"rows": len(y), "logloss": ll, "mae_vs_vegas_wp": mae_vs_vegas, "calibration": calib},
    }


def fit_fg(rows: pl.DataFrame) -> dict:
    fg = rows.filter((pl.col("family") == "field_goal") & pl.col("kick_distance").is_not_null()
                     & pl.col("field_goal_result").is_in(["made", "missed", "blocked"]))
    ctx = []
    for s in sorted(fg["season"].unique().to_list()):
        p = raw_path("pbp", s)
        ctx.append(pl.scan_parquet(p).select("game_id", "roof", "wind", "temp").unique("game_id").collect())
    fg = fg.join(pl.concat(ctx, how="diagonal_relaxed"), on="game_id", how="left")
    indoor = fg["roof"].is_in(["dome", "closed"]).cast(pl.Int8).to_numpy()
    wind = np.where(indoor == 1, 0.0, fg["wind"].fill_null(0).to_numpy().astype(float))
    temp = np.where(indoor == 1, 65.0, fg["temp"].fill_null(60).to_numpy().astype(float))
    d = fg["kick_distance"].to_numpy().astype(float)
    taper = np.maximum(d - 52.0, 0.0)  # PLAN: taper past 52 yards to real long-range rates
    X = np.column_stack([d, d * d / 100.0, indoor, wind, (temp - 60.0) / 10.0, d * wind / 10.0, taper])
    y = (fg["field_goal_result"] == "made").to_numpy().astype(int)
    m = LogisticRegression(max_iter=2000, C=10.0).fit(X, y)
    p = m.predict_proba(X)[:, 1]
    bins = (d // 5 * 5).astype(int)
    by_bin = [[int(b), float(np.mean(y[bins == b])), float(np.mean(p[bins == b])), int((bins == b).sum())]
              for b in sorted(set(bins))]
    print(f"FG: {len(y):,} kicks. distance bin -> actual / model")
    for b, a, pm, n in by_bin:
        print(f"   {b:>2}: {a:.3f} / {pm:.3f}  (n={n})")
    return {
        "features": ["distance", "distance_sq_over_100", "indoor", "wind", "temp_minus_60_over_10", "distance_x_wind_over_10", "max_distance_minus_52_0"],
        "coef": [float(c) for c in m.coef_[0]],
        "intercept": float(m.intercept_[0]),
        "by_distance": by_bin,
        "max_attempt_distance": 68,
    }


def _hist(values: np.ndarray, lo: int | None = None, hi: int | None = None) -> dict:
    v = np.asarray(values)
    v = v[~np.isnan(v)].astype(int)
    if lo is not None:
        v = np.clip(v, lo, hi)
    uniq, counts = np.unique(v, return_counts=True)
    return {"values": [int(u) for u in uniq], "probs": [float(c / counts.sum()) for c in counts], "n": int(counts.sum())}


def _next_yardline(seasons: list[int], play_types: list[str]) -> pl.DataFrame:
    """For special-teams plays: the next snap's posteam and yardline_100, in game order."""
    parts = []
    for s in seasons:
        p = raw_path("pbp", s)
        if not p.exists():
            continue
        df = pl.scan_parquet(p).select("game_id", "play_id", "season", "play_type", "posteam", "defteam", "yardline_100",
                                       "desc", "down", "qtr", "touchback", "return_touchdown", "own_kickoff_recovery",
                                       "punt_blocked", "safety", "game_half").collect().sort(["game_id", "play_id"])
        snaps = df.filter(pl.col("play_type").is_not_null() & (pl.col("play_type") != "no_play"))
        snaps = snaps.with_columns(
            pl.col("posteam").shift(-1).over("game_id").alias("next_pos"),
            pl.col("yardline_100").shift(-1).over("game_id").alias("next_yl"),
            pl.col("play_type").shift(-1).over("game_id").alias("next_pt"),
            pl.col("game_half").shift(-1).over("game_id").alias("next_half"),
        )
        parts.append(snaps.filter(pl.col("play_type").is_in(play_types) & (pl.col("next_half") == pl.col("game_half"))))
    return pl.concat(parts, how="diagonal_relaxed")


def fit_kickoff() -> dict:
    # 2025+ : touchback to the 35 under the dynamic kickoff. 2024 used the 30, so it is excluded.
    seasons = [s for s in range(2025, cfg("seasons", "ingest_last") + 1)]
    ko = _next_yardline(seasons, ["kickoff"])
    normal = ko.filter(~pl.col("desc").str.contains("(?i)onside") & ~pl.col("desc").str.contains("(?i)free kick"))
    recv = normal.filter((pl.col("next_pos") == pl.col("posteam")) & pl.col("next_yl").is_not_null() & (pl.col("return_touchdown") != 1))
    ret_td = float(normal["return_touchdown"].fill_null(0).mean())
    onside = ko.filter(pl.col("desc").str.contains("(?i)onside"))
    on_rec = onside.filter(pl.col("own_kickoff_recovery") == 1)
    on_fail = onside.filter((pl.col("own_kickoff_recovery") != 1) & (pl.col("next_pos") == pl.col("posteam")))
    # free kicks after a safety (kicking team punts/kicks from its 20)
    fk = ko.filter(pl.col("desc").str.contains("(?i)free kick") & (pl.col("next_pos") == pl.col("posteam")))
    out = {
        "rules_seasons": seasons,
        "start_yl": _hist(recv["next_yl"].to_numpy(), 1, 99),
        "return_td": ret_td,
        "onside": {
            "recovery": float(len(on_rec) / max(1, len(onside))),
            "n": len(onside),
            # kicking team recovers around its own 45-48 => yardline_100 ~ 52-55 for it
            "recover_yl": _hist(on_rec.with_columns((100 - pl.col("next_yl")).alias("yl_k"))["yl_k"].to_numpy() if len(on_rec) and "next_yl" in on_rec.columns else np.array([55.0]), 1, 99) if len(on_rec) else {"values": [55], "probs": [1.0], "n": 0},
            "fail_yl": _hist(on_fail["next_yl"].to_numpy(), 1, 99) if len(on_fail) else {"values": [45], "probs": [1.0], "n": 0},
        },
        "safety_kick_start_yl": _hist(fk["next_yl"].to_numpy(), 1, 99) if len(fk) else {"values": [65], "probs": [1.0], "n": 0},
    }
    print(f"Kickoff ({seasons}): {out['start_yl']['n']:,} normal kickoffs, mean start yl "
          f"{np.dot(out['start_yl']['values'], out['start_yl']['probs']):.1f}, return TD {ret_td:.4f}, "
          f"onside n={out['onside']['n']} recovery {out['onside']['recovery']:.3f}")
    return out


def fit_punt() -> dict:
    seasons = list(range(cfg("seasons", "ingest_first"), cfg("seasons", "ingest_last") + 1))
    pu = _next_yardline(seasons, ["punt"])
    zones = [(1, 35), (36, 45), (46, 55), (56, 65), (66, 75), (76, 85), (86, 99)]  # punting team's yardline_100
    table = []
    for lo, hi in zones:
        z = pu.filter((pl.col("yardline_100") >= lo) & (pl.col("yardline_100") <= hi))
        recv = z.filter((pl.col("next_pos") == pl.col("defteam")) & pl.col("next_yl").is_not_null() & (pl.col("return_touchdown") != 1))
        blocked = z.filter(pl.col("punt_blocked") == 1)
        table.append({
            "from_min": lo, "from_max": hi, "n": len(z),
            "next_yl": _hist(recv["next_yl"].to_numpy(), 1, 99),
            "blocked": float(len(blocked) / max(1, len(z))),
            "return_td": float(z["return_touchdown"].fill_null(0).mean()),
            "mean_net": float((100 - recv["next_yl"].to_numpy() - (100 - recv["yardline_100"].to_numpy())).mean()) if len(recv) else None,
        })
    print("Punt zones: " + ", ".join(f"{t['from_min']}-{t['from_max']}: n={t['n']} net {t['mean_net']:.1f}" for t in table if t["mean_net"] is not None))
    return {"zones": table}


def fit_pat(rows: pl.DataFrame) -> dict:
    xp = rows.filter(pl.col("family") == "extra_point")
    tp = rows.filter(pl.col("family") == "two_point")
    out = {
        "xp": float((xp["extra_point_result"] == "good").mean()),
        "two_pt": float((tp["two_point_conv_result"] == "success").mean()),
        "n_xp": len(xp), "n_two_pt": len(tp),
    }
    print(f"PAT: xp {out['xp']:.3f} (n={out['n_xp']:,}), 2pt {out['two_pt']:.3f} (n={out['n_two_pt']:,})")
    return out


def fit_clock(rows: pl.DataFrame) -> dict:
    """Play duration from stopped-clock plays; tempo from running-clock plays."""
    off = rows.filter(pl.col("family").is_in(["run_inside", "run_outside", "qb_sneak", "pass", "pa", "rpo", "screen", "hail_mary", "gadget"])
                      & pl.col("runoff_s").is_not_null() & (pl.col("runoff_s") >= 0))
    # Play duration = runoff on plays after which the clock is certainly stopped and no timeout
    # was taken: incompletions anywhere, and out-of-bounds plays inside the stopping window
    # (Q2 <= 2:00, Q4 <= 5:00), where there is no ready-for-play restart to pollute the gap.
    in_window = ((pl.col("qtr") == 2) & (pl.col("quarter_seconds_remaining") <= 120)) | (
        (pl.col("qtr") == 4) & (pl.col("quarter_seconds_remaining") <= 300))
    inc_rows = off.filter((pl.col("incomplete_pass") == 1) & ~pl.col("timeout_after") & (pl.col("runoff_s") <= 15))
    oob_rows = off.filter((pl.col("out_of_bounds") == 1) & in_window & ~pl.col("timeout_after")
                          & (pl.col("runoff_s") <= 15) & (pl.col("touchdown") != 1))
    dur = {
        "run": _hist(oob_rows.filter(pl.col("family").is_in(["run_inside", "run_outside", "qb_sneak"]))["runoff_s"].to_numpy(), 1, 15),
        "pass_complete": _hist(oob_rows.filter(pl.col("complete_pass") == 1)["runoff_s"].to_numpy(), 1, 15),
        "pass_incomplete": _hist(inc_rows["runoff_s"].to_numpy(), 1, 15),
    }
    # Tempo: pre-snap seconds = runoff - typical duration (6 s), running-clock plays only
    crosses_2min = (pl.col("quarter_seconds_remaining") > 120) & (pl.col("quarter_seconds_remaining") - pl.col("runoff_s") <= 120)
    running = off.filter(~pl.col("clock_stops") & (pl.col("runoff_s") <= 60) & (pl.col("runoff_s") >= 8)
                         & ~crosses_2min & (pl.col("quarter_seconds_remaining") - pl.col("runoff_s") > 0))
    q4_late = (pl.col("qtr") == 4) & (pl.col("quarter_seconds_remaining") <= 300)
    q2_late = (pl.col("qtr") == 2) & (pl.col("quarter_seconds_remaining") <= 120)
    # hurry = a real two-minute drill: trailing or tied inside Q4 2:30 / Q2 2:00 with the clock running
    drill = ((pl.col("qtr") == 4) & (pl.col("quarter_seconds_remaining") <= cfg("spots", "q4_max_seconds_left"))) | q2_late
    hurry = running.filter(drill & (pl.col("score_differential") <= 0))
    milk = running.filter(q4_late & (pl.col("score_differential") > 0) & (pl.col("no_huddle") != 1))
    normal = running.filter((pl.col("no_huddle") != 1) & ~(q4_late | q2_late))
    tempo = {k: _hist(np.clip(v["runoff_s"].to_numpy() - 6, 0, 40), 0, 40) for k, v in (("hurry", hurry), ("normal", normal), ("milk", milk))}
    for k, h in tempo.items():
        print(f"Clock tempo {k}: n={h['n']:,} mean pre-snap {np.dot(h['values'], h['probs']):.1f}s")
    for k, h in dur.items():
        print(f"Clock duration {k}: n={h['n']:,} mean {np.dot(h['values'], h['probs']):.1f}s")
    return {"duration": dur, "tempo": tempo, "play_duration_offset_s": 6, "timeouts": fit_timeouts(rows)}


def fit_timeouts(rows: pl.DataFrame) -> dict:
    """P(a timeout is called after a running-clock play) by who would call it, clock bucket,
    and the caller's timeouts left. 'offense' = the trailing/tied offense, 'defense' = the trailing
    defense (the offense leads). Q4 inside 4:00 and Q2 inside 2:00."""
    c = pl.col
    fams = ["pass", "pa", "screen", "rpo", "run_inside", "run_outside", "qb_sneak"]
    stops_by_play = (c("incomplete_pass") == 1) | (c("out_of_bounds") == 1) | (c("touchdown") == 1) | c("turnover") | (c("penalty") == 1)
    sub = rows.filter(c("family").is_in(fams) & ~stops_by_play & (
        ((c("qtr") == 4) & (c("quarter_seconds_remaining") <= 240)) | ((c("qtr") == 2) & (c("quarter_seconds_remaining") <= 120))))
    sub = sub.with_columns(
        pl.when(c("quarter_seconds_remaining") <= 30).then(pl.lit("c30")).when(c("quarter_seconds_remaining") <= 60).then(pl.lit("c60"))
        .when(c("quarter_seconds_remaining") <= 120).then(pl.lit("c120")).when(c("quarter_seconds_remaining") <= 180).then(pl.lit("c180"))
        .otherwise(pl.lit("c240")).alias("cb"),
        pl.when(c("score_differential") <= 0).then(pl.lit("offense")).otherwise(pl.lit("defense")).alias("who"),
        pl.when(c("score_differential") <= 0).then(c("posteam_timeouts_remaining")).otherwise(c("defteam_timeouts_remaining")).alias("caller_tos"),
        pl.when(c("qtr") == 2).then(pl.lit("h1")).otherwise(pl.lit("h2")).alias("half"),
    ).filter(c("caller_tos").is_not_null())
    g = sub.group_by("half", "who", "cb", "caller_tos").agg(c("timeout_after").mean().alias("p"), pl.len().alias("n"))
    cells = {f"{h}|{w}|{cb}|{int(t)}": {"p": float(p), "n": int(n)} for h, w, cb, t, p, n in g.iter_rows()}
    print(f"Timeouts: {len(cells)} cells from {sub.height:,} running-clock plays")
    return {"cells": cells, "min_n": 20}


def dist_bucket_expr() -> pl.Expr:
    return (pl.when(pl.col("ydstogo") <= 3).then(pl.lit("short"))
            .when(pl.col("ydstogo") <= 7).then(pl.lit("mid")).otherwise(pl.lit("long")))


def zone_expr() -> pl.Expr:
    return (pl.when(pl.col("yardline_100") <= 10).then(pl.lit("gl"))
            .when(pl.col("yardline_100") <= 20).then(pl.lit("rz"))
            .when(pl.col("yardline_100") <= 60).then(pl.lit("mid"))
            .when(pl.col("yardline_100") <= 80).then(pl.lit("own"))
            .otherwise(pl.lit("deep")))


def score_state_expr() -> pl.Expr:
    sd = pl.col("score_differential")
    return (pl.when(sd < -8).then(pl.lit("trail2"))
            .when(sd < 0).then(pl.lit("trail1"))
            .when(sd == 0).then(pl.lit("tied"))
            .when(sd <= 8).then(pl.lit("lead1")).otherwise(pl.lit("lead2")))


def clock_bucket_expr() -> pl.Expr:
    s = pl.col("quarter_seconds_remaining")
    return (pl.when(s <= 30).then(pl.lit("c30"))
            .when(s <= 60).then(pl.lit("c60"))
            .when(s <= 120).then(pl.lit("c120"))
            .when(s <= 300).then(pl.lit("c300")).otherwise(pl.lit("early")))


POLICY_CALLS = ["run_inside", "run_outside", "qb_sneak", "pass_short", "pass_medium", "pass_deep",
                "screen", "pa", "rpo", "hail_mary", "spike", "kneel", "field_goal", "punt"]


def fit_tendencies(rows: pl.DataFrame) -> dict:
    off = rows.filter(pl.col("family").is_in(POLICY_CALLS + ["pass", "gadget"]) & pl.col("down").is_not_null())
    off = off.with_columns(
        pl.when(pl.col("family") == "pass").then(pl.concat_str([pl.lit("pass_"), pl.col("depth")]))
        .when(pl.col("family") == "gadget").then(pl.lit("pass_short"))
        .otherwise(pl.col("family")).alias("pcall"),
        dist_bucket_expr().alias("dist"), zone_expr().alias("zone"), score_state_expr().alias("ss"),
        clock_bucket_expr().alias("cb"),
        pl.when(pl.col("qtr") >= 5).then(pl.lit("ot")).when(pl.col("qtr") <= 2).then(pl.lit("h1")).otherwise(pl.lit("h2")).alias("half"),
    ).filter(pl.col("pcall").is_in(POLICY_CALLS)).with_columns(pl.col("down").cast(pl.Int32))
    # late-game rows carry the situational signal; include all rows for the coarse backoff
    late = off.filter(pl.col("cb") != "early")
    levels = {
        "L0": ["half", "cb", "ss", "down", "dist", "zone"],
        "L1": ["half", "cb", "ss", "down", "dist"],
        "L2": ["ss", "down", "dist", "zone"],
        "L3": ["down", "dist", "zone"],
        "L4": ["down", "dist"],
    }
    cells = {}
    for lvl, keys in levels.items():
        src = late if lvl in ("L0", "L1", "L2") else off
        g = src.group_by(keys + ["pcall"]).len()
        tot = g.group_by(keys).agg(pl.col("len").sum().alias("n"))
        g = g.join(tot, on=keys)
        for row in g.iter_rows(named=True):
            key = lvl + "|" + "|".join(str(row[k]) for k in keys)
            cell = cells.setdefault(key, {"n": int(row["n"]), "p": {}})
            cell["p"][row["pcall"]] = float(row["len"] / row["n"])
    # direction given depth, for expanding pass_short -> pass_short_left etc.
    dirs = {}
    for dep in ("short", "medium", "deep"):
        sub = off.filter((pl.col("pcall") == f"pass_{dep}") & pl.col("direction").is_not_null()).group_by("direction").len()
        n = sub["len"].sum()
        dirs[dep] = {d: float(k / n) for d, k in sub.iter_rows()}
    rsub = off.filter(pl.col("family").is_in(["run_inside", "run_outside"]) & pl.col("direction").is_not_null()).group_by("direction").len()
    dirs["run"] = {d: float(k / rsub["len"].sum()) for d, k in rsub.iter_rows()}
    print(f"Tendencies: {len(cells):,} cells across {len(levels)} levels; {late.height:,} late-game rows")
    return {"levels": levels, "calls": POLICY_CALLS, "cells": cells, "direction": dirs,
            "min_cell_n": 20}


def fit_looks(rows: pl.DataFrame) -> dict:
    off = rows.filter(pl.col("family").is_in(["run_inside", "run_outside", "pass", "pa", "rpo", "screen"]) & pl.col("box").is_not_null()
                      & pl.col("down").is_not_null())
    off = off.with_columns(dist_bucket_expr().alias("dist"), zone_expr().alias("zone"))
    g = off.group_by("down", "dist").agg(
        (pl.col("box") == "light").mean().alias("p_light"),
        pl.col("blitz").drop_nulls().mean().alias("p_blitz"), pl.len().alias("n"))
    cells = {f"{int(d)}|{s}": {"p_light": float(pl_), "p_blitz": float(pb), "n": int(n)} for d, s, pl_, pb, n in g.iter_rows()}
    overall = {"p_light": float((off["box"] == "light").mean()), "p_blitz": float(off["blitz"].drop_nulls().mean())}
    print(f"Looks: overall light box {overall['p_light']:.3f}, blitz {overall['p_blitz']:.3f}")
    return {"by_down_dist": cells, "overall": overall}


def main() -> int:
    rows = pl.read_parquet(ROWS_PATH)
    models = {
        "version": 1,
        "wp": fit_wp(),
        "fg": fit_fg(rows),
        "pat": fit_pat(rows),
        "kickoff": fit_kickoff(),
        "punt": fit_punt(),
        "clock": fit_clock(rows),
        "looks": fit_looks(rows),
        "tendencies": fit_tendencies(rows),
    }
    MODELS_PATH.write_text(json.dumps(models))
    print(f"Wrote {MODELS_PATH} ({MODELS_PATH.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
