"""Ingest nflverse data for the pipeline.

Usage (from repo root):
    uv run python pipeline/ingest.py pull                      # all default datasets, config seasons
    uv run python pipeline/ingest.py pull --seasons 2023-2026 --datasets pbp,participation
    uv run python pipeline/ingest.py pull --force              # re-download even if cached
    uv run python pipeline/ingest.py report                    # field completeness per season

Every (dataset, season) lands in data/raw/<dataset>/<dataset>_<season>.parquet.
A manifest of what was pulled (rows, columns, status, errors) is written to
data/raw/manifest.json so later stages can see which seasons are missing.

Data: nflverse (https://github.com/nflverse), CC-BY-4.0. Credit it in the app.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.config import PROCESSED_DIR, RAW_DIR, cfg, ingest_seasons

# --------------------------------------------------------------------------- datasets

# name -> (loader kwargs builder, first season, per-season?)
# Loaders are resolved lazily so `report` works without importing nflreadpy.
DEFAULT_DATASETS = ["pbp", "participation", "rosters_weekly", "schedules", "ftn", "players"]
EXTRA_DATASETS = ["depth_charts", "injuries"]
ALL_DATASETS = DEFAULT_DATASETS + EXTRA_DATASETS


def _loaders() -> dict[str, tuple[Callable[..., pl.DataFrame], int | None, bool]]:
    import nflreadpy as nfl
    from nflreadpy.config import update_config

    # Persist nflreadpy's own HTTP cache next to our raw data so re-runs are cheap.
    update_config(cache_mode="filesystem", cache_dir=RAW_DIR / ".nflreadpy_cache")

    return {
        # name: (loader, first season, per_season)
        "pbp": (nfl.load_pbp, 1999, True),
        "participation": (nfl.load_participation, 2016, True),
        "rosters_weekly": (nfl.load_rosters_weekly, 2002, True),
        "schedules": (nfl.load_schedules, 1999, True),
        "ftn": (nfl.load_ftn_charting, cfg("seasons", "ftn_first"), True),
        "players": (nfl.load_players, None, False),
        "depth_charts": (nfl.load_depth_charts, 2001, True),
        "injuries": (nfl.load_injuries, 2009, True),
    }


def raw_path(dataset: str, season: int | None) -> Path:
    d = RAW_DIR / dataset
    return d / (f"{dataset}_{season}.parquet" if season is not None else f"{dataset}.parquet")


def manifest_path() -> Path:
    return RAW_DIR / "manifest.json"


def load_manifest() -> dict:
    p = manifest_path()
    if p.exists():
        return json.loads(p.read_text())
    return {"entries": {}}


def save_manifest(m: dict) -> None:
    manifest_path().write_text(json.dumps(m, indent=2, sort_keys=True))


# --------------------------------------------------------------------------- pull


def pull_one(
    name: str,
    loader: Callable[..., pl.DataFrame],
    season: int | None,
    force: bool,
    manifest: dict,
) -> None:
    key = f"{name}/{season}" if season is not None else name
    out = raw_path(name, season)
    if out.exists() and not force:
        print(f"  [skip] {key:<22} cached ({out.relative_to(RAW_DIR.parent.parent)})")
        return

    t0 = time.time()
    try:
        if season is None:
            df = loader()
        elif name == "schedules":
            # schedules is one file for all seasons; filter after download
            df = loader(True).filter(pl.col("season") == season)
        else:
            df = loader(season)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(out, compression="zstd")
        entry = {
            "status": "ok",
            "rows": df.height,
            "cols": df.width,
            "seconds": round(time.time() - t0, 1),
            "pulled_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        print(f"  [ok]   {key:<22} {df.height:>8,} rows x {df.width:>3} cols  {entry['seconds']:>6}s")
    except ValueError as e:
        # nflreadpy raises ValueError for seasons a dataset does not cover yet
        # (e.g. participation is published a season in arrears). That is a gap, not a failure.
        entry = {"status": "unavailable", "reason": str(e)[:300],
                 "pulled_at": datetime.now(UTC).isoformat(timespec="seconds")}
        print(f"  [n/a]  {key:<22} {entry['reason']}")
    except Exception as e:  # noqa: BLE001 - we want to keep going past one bad season
        msg = f"{type(e).__name__}: {e}"
        entry = {
            "status": "error",
            "error": msg.splitlines()[0][:300],
            "pulled_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        print(f"  [FAIL] {key:<22} {entry['error']}")
        if "--debug" in sys.argv:
            traceback.print_exc()
    manifest["entries"][key] = entry
    save_manifest(manifest)


def cmd_pull(args: argparse.Namespace) -> int:
    seasons = parse_seasons(args.seasons)
    datasets = ALL_DATASETS if args.datasets == "all" else args.datasets.split(",")
    unknown = [d for d in datasets if d not in ALL_DATASETS]
    if unknown:
        print(f"Unknown datasets: {unknown}. Known: {ALL_DATASETS}")
        return 2

    loaders = _loaders()
    manifest = load_manifest()
    manifest["last_pull"] = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"Pulling {datasets} for seasons {seasons[0]}-{seasons[-1]} into {RAW_DIR}")
    for name in datasets:
        loader, first, per_season = loaders[name]
        print(f"\n== {name}")
        if not per_season:
            pull_one(name, loader, None, args.force, manifest)
            continue
        for s in seasons:
            if first is not None and s < first:
                print(f"  [skip] {name}/{s:<17} dataset starts {first}")
                continue
            pull_one(name, loader, s, args.force, manifest)

    errors = {k: v for k, v in manifest["entries"].items() if v.get("status") == "error"}
    print(f"\nDone. {len(errors)} failed entries." + (f" See {manifest_path()}" if errors else ""))
    for k, v in errors.items():
        print(f"  {k}: {v['error']}")
    return 0


# --------------------------------------------------------------------------- report

PARTICIPATION_FIELDS = [
    # (column, label) -- all evaluated as "% of rows non-null and non-empty"
    ("offense_personnel", "personnel"),
    ("offense_formation", "formation"),
    ("defense_personnel", "def_personnel"),
    ("defenders_in_box", "box"),
    ("number_of_pass_rushers", "rushers"),
    ("defense_coverage_type", "coverage"),
    ("defense_man_zone_type", "man_zone"),
    ("was_pressure", "pressure"),
    ("time_to_throw", "ttt"),
    ("route", "route"),
    ("offense_players", "off_ids"),
    ("defense_players", "def_ids"),
]


def _nonempty(col: str) -> pl.Expr:
    c = pl.col(col)
    return c.is_not_null() & (c.cast(pl.Utf8).str.strip_chars() != "")


def _pct(num: int, den: int) -> float | None:
    return round(100.0 * num / den, 1) if den else None


def _scan(dataset: str, season: int) -> pl.LazyFrame | None:
    p = raw_path(dataset, season)
    return pl.scan_parquet(p) if p.exists() else None


def report_season(season: int) -> dict:
    row: dict = {"season": season}

    pbp = _scan("pbp", season)
    if pbp is None:
        row["pbp_rows"] = None
        return row

    pbp_cols = pbp.collect_schema().names()
    scrim = pbp.filter(pl.col("play_type").is_in(["run", "pass"])).select(
        "game_id", "play_id", "play_type", "sack", "air_yards", "week", "season_type"
    )
    scrim_df = scrim.collect()
    row["pbp_rows"] = pbp.select(pl.len()).collect().item()
    row["scrimmage_plays"] = scrim_df.height
    row["weeks"] = scrim_df["week"].n_unique()
    row["games"] = scrim_df["game_id"].n_unique()

    # ---- air_yards: pass plays that were actually thrown (exclude sacks)
    thrown = scrim_df.filter((pl.col("play_type") == "pass") & (pl.col("sack") == 0))
    row["pass_thrown"] = thrown.height
    row["air_yards_pct"] = _pct(thrown["air_yards"].is_not_null().sum(), thrown.height)
    if "pass_length" in pbp_cols:
        pl_df = pbp.filter((pl.col("play_type") == "pass") & (pl.col("sack") == 0)).select(
            pl.col("pass_length").is_not_null().sum().alias("n")
        ).collect()
        row["pass_length_pct"] = _pct(pl_df["n"][0], thrown.height)

    # ---- participation
    part = _scan("participation", season)
    if part is None:
        row["part_rows"] = 0
        row["part_join_pct"] = 0.0
        for _, label in PARTICIPATION_FIELDS:
            row[f"{label}_pct"] = None
        return row

    part_cols = part.collect_schema().names()
    game_key = "nflverse_game_id" if "nflverse_game_id" in part_cols else "game_id"
    sel = [pl.col(game_key).alias("game_id"), pl.col("play_id").cast(pl.Int64)]
    for col, _ in PARTICIPATION_FIELDS:
        if col in part_cols:
            sel.append(_nonempty(col).alias(f"__{col}"))
    part_df = part.select(sel).collect()
    row["part_rows"] = part_df.height

    joined = scrim_df.select("game_id", pl.col("play_id").cast(pl.Int64)).join(
        part_df, on=["game_id", "play_id"], how="left"
    )
    has_row = joined.select(pl.col(f"__{PARTICIPATION_FIELDS[0][0]}").is_not_null().sum()).item() \
        if f"__{PARTICIPATION_FIELDS[0][0]}" in joined.columns else 0
    row["part_join_pct"] = _pct(has_row, scrim_df.height)

    for col, label in PARTICIPATION_FIELDS:
        flag = f"__{col}"
        if flag not in joined.columns:
            row[f"{label}_pct"] = None  # column absent in this season's file
            continue
        # share of scrimmage plays where the field is populated (null join => not populated)
        n = joined.select(pl.col(flag).fill_null(False).sum()).item()
        row[f"{label}_pct"] = _pct(n, scrim_df.height)

    # ---- FTN charting (2022+)
    ftn = _scan("ftn", season)
    if ftn is not None:
        ftn_cols = ftn.collect_schema().names()
        gk = "nflverse_game_id" if "nflverse_game_id" in ftn_cols else "game_id"
        pk = "nflverse_play_id" if "nflverse_play_id" in ftn_cols else "play_id"
        ftn_df = ftn.select(pl.col(gk).alias("game_id"), pl.col(pk).cast(pl.Int64).alias("play_id")) \
            .unique().with_columns(pl.lit(True).alias("__ftn")).collect()
        j = scrim_df.select("game_id", pl.col("play_id").cast(pl.Int64)).join(
            ftn_df, on=["game_id", "play_id"], how="left"
        )
        row["ftn_join_pct"] = _pct(j["__ftn"].fill_null(False).sum(), scrim_df.height)
    else:
        row["ftn_join_pct"] = None
    return row


def cmd_report(args: argparse.Namespace) -> int:
    seasons = parse_seasons(args.seasons)
    rows = [report_season(s) for s in seasons]
    df = pl.DataFrame(rows, infer_schema_length=None)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = PROCESSED_DIR / "field_coverage.csv"
    df.write_csv(out_csv)

    # Headline table: the three fields the plan cares about most, plus join rates.
    headline_cols = [c for c in [
        "season", "games", "scrimmage_plays", "part_join_pct", "personnel_pct",
        "formation_pct", "pass_thrown", "air_yards_pct", "ftn_join_pct",
    ] if c in df.columns]
    detail_cols = [c for c in [
        "season", "def_personnel_pct", "box_pct", "rushers_pct", "coverage_pct",
        "man_zone_pct", "pressure_pct", "ttt_pct", "route_pct", "off_ids_pct", "def_ids_pct",
    ] if c in df.columns]

    with pl.Config(tbl_rows=50, tbl_cols=20, tbl_width_chars=160, fmt_str_lengths=20):
        print("\nField completeness, headline (percent of scrimmage plays; air_yards is % of thrown passes)")
        print(df.select(headline_cols))
        print("\nParticipation detail fields (percent of scrimmage plays)")
        print(df.select(detail_cols))
    print(f"\nWrote {out_csv}")

    md = PROCESSED_DIR / "field_coverage.md"
    md.write_text(_to_markdown(df.select(headline_cols)) + "\n\n" + _to_markdown(df.select(detail_cols)) + "\n")
    print(f"Wrote {md}")
    return 0


def _to_markdown(df: pl.DataFrame) -> str:
    cols = df.columns
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in df.iter_rows():
        cells = []
        for col, v in zip(cols, r, strict=True):
            if v is None:
                cells.append("")
            elif isinstance(v, int) and col != "season":
                cells.append(f"{v:,}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- cli


def parse_seasons(spec: str | None) -> list[int]:
    if not spec:
        return ingest_seasons()
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pull", help="download datasets to data/raw")
    p.add_argument("--seasons", help="e.g. 2016-2026 or 2023,2024 (default: config)")
    p.add_argument("--datasets", default=",".join(DEFAULT_DATASETS),
                   help=f"comma list or 'all'. Default: {','.join(DEFAULT_DATASETS)}. Extra: {EXTRA_DATASETS}")
    p.add_argument("--force", action="store_true", help="re-download cached files")
    p.add_argument("--debug", action="store_true", help="print tracebacks on failure")
    p.set_defaults(fn=cmd_pull)

    r = sub.add_parser("report", help="per-season completeness of personnel/formation/air_yards etc.")
    r.add_argument("--seasons", help="e.g. 2016-2026 (default: config)")
    r.set_defaults(fn=cmd_report)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
