"""Coach profiles: per-coach tendency deltas vs league expectation in the same situations.

    uv run python pipeline/coaches.py

Writes data/processed/coaches.json, merged into game.json by export.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.config import PROCESSED_DIR, cfg
from pipeline.ingest import raw_path
from pipeline.playbook import ROWS_PATH
from pipeline.wp_model import dist_bucket_expr, score_state_expr, zone_expr

COACHES_PATH = PROCESSED_DIR / "coaches.json"
MIN_PLAYS = 150
PASS_FAMS = ["pass", "pa", "rpo", "screen", "hail_mary", "gadget"]
RUN_FAMS = ["run_inside", "run_outside", "qb_sneak"]


def _coach_by_game() -> pl.DataFrame:
    parts = []
    for s in range(cfg("seasons", "ingest_first"), cfg("seasons", "ingest_last") + 1):
        p = raw_path("pbp", s)
        if p.exists():
            parts.append(pl.scan_parquet(p).select("game_id", "home_team", "away_team", "home_coach", "away_coach")
                         .unique("game_id").collect())
    return pl.concat(parts, how="diagonal_relaxed")


def main() -> int:
    c = pl.col
    rows = pl.read_parquet(ROWS_PATH)
    late = ((c("qtr") == 4) & (c("quarter_seconds_remaining") <= 300)) | ((c("qtr") == 2) & (c("quarter_seconds_remaining") <= 120)) | (c("qtr") >= 5)
    df = rows.filter(late & c("down").is_not_null()).join(_coach_by_game(), on="game_id", how="left")
    df = df.with_columns(
        pl.when(c("posteam") == c("home_team_right") if "home_team_right" in df.columns else c("posteam") == c("home_team"))
        .then(c("home_coach")).otherwise(c("away_coach")).alias("coach"),
        dist_bucket_expr().alias("dist"), zone_expr().alias("zone"), score_state_expr().alias("ss"),
        c("family").is_in(PASS_FAMS).cast(pl.Float64).alias("is_pass"),
        c("family").is_in(PASS_FAMS + RUN_FAMS).alias("is_scrim"),
        (c("depth") == "deep").cast(pl.Float64).alias("is_deep"),
        (~c("family").is_in(["punt", "field_goal"])).cast(pl.Float64).alias("is_go"),
        c("timeout_after").cast(pl.Float64).alias("is_to"),
    ).filter(c("coach").is_not_null())
    cell = ["down", "dist", "zone", "ss"]

    def delta(sub: pl.DataFrame, col: str) -> pl.DataFrame:
        exp = sub.group_by(cell).agg(c(col).mean().alias("exp"))
        return sub.join(exp, on=cell).with_columns((c(col) - c("exp")).alias("d")).group_by("coach").agg(
            c("d").mean().alias(col), pl.len().alias(f"n_{col}"))

    scrim = df.filter(c("is_scrim"))
    passes = scrim.filter(c("is_pass") == 1)
    fourth = df.filter((c("down") == 4) & c("family").is_in(PASS_FAMS + RUN_FAMS + ["punt", "field_goal"]))
    running = scrim.filter(~c("clock_stops") & c("runoff_s").is_not_null() & (c("runoff_s").is_between(8, 60)) & (c("score_differential") <= 0))
    tempo = running.with_columns(c("runoff_s").cast(pl.Float64).alias("secs"))
    to_rows = scrim.filter(c("score_differential") <= 0).with_columns(c("is_to"))
    traits = delta(scrim, "is_pass").join(delta(passes, "is_deep"), on="coach", how="left") \
        .join(delta(fourth, "is_go"), on="coach", how="left").join(delta(tempo, "secs"), on="coach", how="left") \
        .join(delta(to_rows, "is_to"), on="coach", how="left")
    # two-point rate after touchdowns (all game, score state at the try)
    pat = rows.filter(c("family").is_in(["extra_point", "two_point"])).join(_coach_by_game(), on="game_id", how="left")
    pat = pat.with_columns(pl.when(c("posteam") == c("home_team")).then(c("home_coach")).otherwise(c("away_coach")).alias("coach"),
                           (c("family") == "two_point").cast(pl.Float64).alias("is_2pt"),
                           score_state_expr().alias("ss"), pl.when(c("qtr") >= 4).then(pl.lit("late")).otherwise(pl.lit("early")).alias("when"))
    exp2 = pat.group_by("ss", "when").agg(c("is_2pt").mean().alias("exp"))
    two = pat.join(exp2, on=["ss", "when"]).with_columns((c("is_2pt") - c("exp")).alias("d")).group_by("coach").agg(
        c("d").mean().alias("is_2pt"), pl.len().alias("n_is_2pt"))
    traits = traits.join(two, on="coach", how="left")
    meta = scrim.group_by("coach").agg(c("season").min().alias("from"), c("season").max().alias("to"),
                                       c("posteam").unique().sort().alias("teams"), pl.len().alias("n"))
    traits = traits.join(meta, on="coach").filter(c("n") >= MIN_PLAYS).sort("n", descending=True)
    out = []
    for r in traits.iter_rows(named=True):
        t = {"pass": r["is_pass"], "deep": r["is_deep"], "go": r["is_go"], "tempo": r["secs"], "timeout": r["is_to"], "two_pt": r["is_2pt"]}
        t = {k: (round(v, 4) if v is not None else 0.0) for k, v in t.items()}
        out.append({
            "name": r["coach"], "from": r["from"], "to": r["to"], "teams": r["teams"], "n": r["n"],
            "traits": t,
            "counts": {"pass": r["n_is_pass"], "deep": r["n_is_deep"] or 0, "go": r["n_is_go"] or 0, "tempo": r["n_secs"] or 0,
                       "timeout": r["n_is_to"] or 0, "two_pt": r["n_is_2pt"] or 0},
            # policy multipliers for the auto-policy: +10 pts of pass rate -> x1.2 on pass calls, etc.
            "shift": {"pass": round(1 + 2 * t["pass"], 3), "deep": round(1 + 3 * t["deep"], 3), "go": round(1 + 2 * t["go"], 3)},
        })
    # trait scales for the nearest-coach distance (std across coaches)
    import statistics
    scales = {k: (statistics.pstdev([o["traits"][k] for o in out]) or 1.0) for k in out[0]["traits"]}
    COACHES_PATH.write_text(json.dumps({"coaches": out, "scales": scales}, indent=1))
    print(f"{len(out)} coaches with >= {MIN_PLAYS} late plays. Scales: " + ", ".join(f"{k} {v:.3f}" for k, v in scales.items()))
    for o in out[:5]:
        print("  ", o["name"], o["n"], o["traits"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
