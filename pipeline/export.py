"""Assemble the files the game loads, into web/public/data/.

    uv run python pipeline/export.py

  engine_data.json   models.json (WP, FG, PAT, kickoff, punt, clock, looks, tendencies)
                     + the playbook codebooks (category labels for each coded column)
  playbook.json      columnar play library sorted by (family, call, look, zone) with cell offsets
  game.json          calls, categories, spots (state + real result), 365-day schedule, coaches
  spots/sNN.json     per-spot lineups (participation ids) and ratings (ratings.py, later phase)

The Python reference simulator (sim/) reads these same files, so Python and TypeScript are
guaranteed to see identical data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.config import PROCESSED_DIR, ROOT, cfg
from pipeline.playbook import ROWS_PATH
from pipeline.spots import SPOTS_PATH
from pipeline.wp_model import MODELS_PATH, zone_expr

OUT_DIR = ROOT / "web" / "public" / "data"

LIB_FAMILIES = ["run_inside", "run_outside", "qb_sneak", "pass", "pa", "rpo", "screen", "hail_mary", "gadget"]
LOOKS = ["light_any", "heavy_any", "light_base", "light_blitz", "heavy_base", "heavy_blitz"]
ZONES = ["gl", "rz", "mid", "own", "deep"]
PERSONNEL = ["11", "12", "21", "13", "22", "10", "jumbo", "other"]
FORMATIONS = ["SHOTGUN", "SINGLEBACK", "I_FORM", "EMPTY", "PISTOL", "JUMBO", "WILDCAT"]
TARGETS = ["WR", "TE", "RB", "QB", "OTHER"]
COVERAGES = ["COVER_0", "COVER_1", "COVER_2", "COVER_3", "COVER_4", "COVER_6", "2_MAN", "PREVENT", "OTHER"]

# The player-facing call list (label, family, depth, direction). Direction/depth null = chosen in UI.
CALLS = [
    {"id": "run_inside", "label": "Inside run", "family": "run_inside", "dirs": ["left", "middle", "right"]},
    {"id": "run_outside", "label": "Outside run", "family": "run_outside", "dirs": ["left", "right"]},
    {"id": "qb_sneak", "label": "QB sneak", "family": "qb_sneak"},
    {"id": "pass_short", "label": "Short pass", "family": "pass", "depth": "short", "dirs": ["left", "middle", "right"]},
    {"id": "pass_medium", "label": "Medium pass", "family": "pass", "depth": "medium", "dirs": ["left", "middle", "right"]},
    {"id": "pass_deep", "label": "Deep pass", "family": "pass", "depth": "deep", "dirs": ["left", "middle", "right"]},
    {"id": "pa_short", "label": "Play action, short", "family": "pa", "depth": "short", "dirs": ["left", "middle", "right"]},
    {"id": "pa_medium", "label": "Play action, medium", "family": "pa", "depth": "medium", "dirs": ["left", "middle", "right"]},
    {"id": "pa_deep", "label": "Play action, deep", "family": "pa", "depth": "deep", "dirs": ["left", "middle", "right"]},
    {"id": "rpo", "label": "RPO", "family": "rpo"},
    {"id": "screen", "label": "Screen", "family": "screen"},
    {"id": "hail_mary", "label": "Hail Mary", "family": "hail_mary", "gadget": True},
    {"id": "gadget", "label": "Trick play", "family": "gadget", "gadget": True},
    {"id": "spike", "label": "Spike", "family": "spike"},
    {"id": "kneel", "label": "Kneel", "family": "kneel"},
    {"id": "field_goal", "label": "Field goal", "family": "field_goal"},
    {"id": "punt", "label": "Punt", "family": "punt"},
    {"id": "timeout", "label": "Timeout", "family": "timeout"},
]
CATEGORIES = [
    {"id": "drill", "label": "Two-minute drill", "blurb": "Trailing with the ball. Go win it."},
    {"id": "protect", "label": "Protect the lead", "blurb": "Ahead with the ball. Don't give it back."},
    {"id": "tight", "label": "Tied, or end of the half", "blurb": "Every point and every second counts."},
]


def _code(col: pl.Expr, cats: list[str], default: int = -1) -> pl.Expr:
    return col.replace_strict({c: i for i, c in enumerate(cats)}, default=default, return_dtype=pl.Int16)


def export_playbook() -> dict:
    df = pl.read_parquet(ROWS_PATH).filter(pl.col("family").is_in(LIB_FAMILIES) & pl.col("look").is_not_null())
    c = pl.col
    late = ((c("qtr") == 4) & (c("quarter_seconds_remaining") <= cfg("spots", "q4_max_seconds_left"))) | (
        (c("qtr") == 2) & (c("quarter_seconds_remaining") <= cfg("spots", "q2_max_seconds_left")))
    df = df.with_columns(
        zone_expr().alias("zone"),
        late.alias("late"),
        pl.when(c("interception") == 1).then(2).when(c("fumble_lost") == 1).then(1).otherwise(0).cast(pl.Int16).alias("to"),
        pl.when((c("penalty_yards").is_null()) | (c("penalty_yards") <= 0)).then(0)
        .when(c("penalty_on_offense")).then(1).otherwise(2).cast(pl.Int16).alias("pen"),
    ).sort(["family", "call", "look", "zone", "season", "game_id", "play_id"])
    n = df.height
    i16 = lambda e: e.fill_null(0).cast(pl.Int16)
    cols = df.select(
        i16(c("yards_gained")).alias("yards"),
        i16(c("first_down")).alias("fd"),
        i16(c("touchdown")).alias("td"),
        c("to"),
        i16(c("return_touchdown")).alias("def_td"),
        i16(c("safety")).alias("safety"),
        i16(c("sack")).alias("sack"),
        i16(c("incomplete_pass")).alias("inc"),
        i16(c("complete_pass")).alias("comp"),
        i16(c("out_of_bounds")).alias("oob"),
        c("pen"),
        i16(c("penalty_yards")).alias("pen_yds"),
        c("nullified").cast(pl.Int16).alias("nullified"),
        i16(c("qb_scramble")).alias("scr"),
        c("air_yards").fill_null(-99).cast(pl.Int16).alias("air"),
        c("yards_after_catch").fill_null(-99).cast(pl.Int16).alias("yac"),
        (c("time_to_throw") * 10).fill_null(-1).cast(pl.Int16).alias("ttt10"),
        c("return_yards").fill_null(0).cast(pl.Int16).alias("ret"),
        c("clock_stops").cast(pl.Int16).alias("stops"),
        c("late").cast(pl.Int16).alias("late"),
        c("season").cast(pl.Int16).alias("season"),
        _code(c("personnel_class"), PERSONNEL).alias("pers"),
        _code(c("formation"), FORMATIONS).alias("form"),
        _code(c("target_pos"), TARGETS).alias("tgt"),
        c("was_pressure").cast(pl.Int16).fill_null(-1).alias("press"),
        _code(c("defense_coverage_type"), COVERAGES).alias("cov"),
        c("yardline_100").fill_null(50).cast(pl.Int16).alias("yl"),
    )
    routes = sorted(df["route"].drop_nulls().unique().to_list())
    route_col = _code(c("route"), routes).alias("route")
    cols = cols.with_columns(df.select(route_col)["route"])

    # cell offsets at each hierarchy level (rows are sorted so each prefix is contiguous)
    keys = df.select("family", "call", "look", "zone")
    index: dict[str, dict[str, list[int]]] = {"L3": {}, "L2": {}, "L1": {}, "L0": {}}
    fam = keys["family"].to_list(); call = keys["call"].to_list(); look = keys["look"].to_list(); zone = keys["zone"].to_list()
    def add(level: str, key: str, i: int) -> None:
        cell = index[level].get(key)
        if cell is None:
            index[level][key] = [i, 1]
        else:
            cell[1] += 1
    for i in range(n):
        add("L3", f"{fam[i]}|{call[i]}|{look[i]}|{zone[i]}", i)
        add("L2", f"{fam[i]}|{call[i]}|{look[i]}", i)
        add("L1", f"{fam[i]}|{call[i]}", i)
        add("L0", fam[i], i)
    out = {
        "version": 1,
        "n": n,
        "columns": {k: cols[k].to_list() for k in cols.columns},
        "index": index,
        "codebooks": {"look": LOOKS, "zone": ZONES, "personnel": PERSONNEL, "formation": FORMATIONS,
                      "target": TARGETS, "coverage": COVERAGES, "route": routes},
    }
    (OUT_DIR / "playbook.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"playbook.json: {n:,} rows, {len(index['L3']):,} L3 cells, "
          f"{(OUT_DIR / 'playbook.json').stat().st_size / 1e6:.1f} MB")
    return out


def _schedule(spots: pl.DataFrame, rng: np.random.Generator) -> list[dict]:
    """365 days x 3 spots (one per category), scored category rotating, no spot reused."""
    pools = {cat: spots.filter(pl.col("category") == cat)["spot_id"].to_list() for cat in ("drill", "protect", "tight")}
    for v in pools.values():
        rng.shuffle(v)
    days = []
    cats = ["drill", "protect", "tight"]
    for d in range(cfg("spots", "schedule_days")):
        picks = {}
        for cat in cats:
            pool = pools[cat]
            picks[cat] = pool[d % len(pool)]
        days.append({"day": d, "scored": cats[d % 3], "spots": picks})
    return days


def export_game(models: dict) -> dict:
    spots = pl.read_parquet(SPOTS_PATH).filter(~pl.col("kneel_start"))
    rng = np.random.default_rng(cfg("pipeline", "seed"))
    recs = []
    for r in spots.iter_rows(named=True):
        recs.append({
            "id": r["spot_id"],
            "cat": r["category"],
            "season": r["season"], "week": r["week"], "playoff": r["season_type"] == "POST",
            "game": r["game_id"], "play_id": int(r["play_id"]),
            "off": r["posteam"], "def": r["defteam"], "home": r["home_team"], "away": r["away_team"],
            "state": {
                "qtr": int(r["qtr"]), "clock": int(r["quarter_seconds_remaining"]),
                "down": int(r["down"]), "togo": int(r["ydstogo"]), "yl": int(r["yardline_100"]),
                "score": [int(r["posteam_score"] or 0), int(r["defteam_score"] or 0)],
                "tos": [int(r["posteam_timeouts_remaining"] or 0), int(r["defteam_timeouts_remaining"] or 0)],
                "recv2h": bool(r["pos_receives_2h"]) if r["pos_receives_2h"] is not None else False,
            },
            "ctx": {"spread": r["pos_spread"], "roof": r["roof"], "temp": r["temp"], "wind": r["wind"],
                    "surface": r["surface"], "coach": r["pos_coach"], "def_coach": r["def_coach"],
                    "date": str(r["game_date"]) if r["game_date"] else None},
            "real": {"calls": r["real_calls"], "n": int(r["real_n_plays"]), "result": r["real_drive_result"],
                     "points": int(r["real_drive_points"]), "outcome": r["real_outcome"],
                     "final_margin": int(r["final_margin"]) if r["final_margin"] is not None else None},
            "wp0": r["vegas_wp"],
            "lineup": bool(r["has_lineup"]),
        })
    game = {
        "version": 1,
        "name": cfg("game", "name"),
        "launch": cfg("game", "launch_date"),
        "disclaimer": cfg("game", "disclaimer"),
        "categories": CATEGORIES,
        "calls": CALLS,
        "spots": recs,
        "schedule": _schedule(spots, rng),
        "featured": json.loads((ROOT / "pipeline" / "featured.json").read_text()) if (ROOT / "pipeline" / "featured.json").exists() else {},
        "coaches": json.loads((PROCESSED_DIR / "coaches.json").read_text()) if (PROCESSED_DIR / "coaches.json").exists() else {"coaches": [], "scales": {}},
    }
    (OUT_DIR / "game.json").write_text(json.dumps(game, separators=(",", ":")))
    print(f"game.json: {len(recs):,} spots, {len(game['schedule'])} days, "
          f"{(OUT_DIR / 'game.json').stat().st_size / 1e6:.2f} MB")
    return game


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "spots").mkdir(exist_ok=True)
    models = json.loads(MODELS_PATH.read_text())
    engine = {"version": 1, "config": json.loads((ROOT / "config" / "tuning.json").read_text()), **models}
    (OUT_DIR / "engine_data.json").write_text(json.dumps(engine, separators=(",", ":")))
    print(f"engine_data.json: {(OUT_DIR / 'engine_data.json').stat().st_size / 1e6:.2f} MB")
    export_playbook()
    game = export_game(models)
    export_spot_chunks(game)
    return 0




# --------------------------------------------------------------------------- spot chunks

OFF_SLOTS = ["QB", "RB", "WR", "WR", "WR", "TE", "OL", "OL", "OL", "OL", "OL"]
DEF_SLOTS = ["DL", "DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB", "DB"]


def _lineup_from_ids(ids: str | None, ratings: pl.DataFrame, season: int) -> list[dict]:
    if not ids:
        return []
    want = [i for i in ids.split(";") if i]
    sub = ratings.filter((pl.col("season") == season) & pl.col("gsis_id").is_in(want))
    by = {r["gsis_id"]: r for r in sub.iter_rows(named=True)}
    out = []
    for i in want:
        r = by.get(i)
        if r is None:
            out.append({"id": i, "name": "?", "pos": "?", "grp": "OTHER", "num": None, "rating": 70})
        else:
            out.append({"id": i, "name": r["full_name"], "pos": r["position"], "grp": r["grp"], "num": r["jersey_number"], "rating": int(r["rating"])})
    return out


def _lineup_from_depth(team: str, season: int, ratings: pl.DataFrame, slots: list[str], side: str) -> list[dict]:
    from pipeline.ingest import raw_path
    p = raw_path("depth_charts", season)
    if not p.exists():
        return []
    dc = pl.read_parquet(p)
    if "pos_rank" not in dc.columns:
        return []
    dc = dc.filter(pl.col("team") == team).sort("dt")
    latest = dc.filter(pl.col("dt") == dc["dt"].max())
    r = ratings.filter((pl.col("season") == season) & (pl.col("team") == team))
    by = {x["gsis_id"]: x for x in r.iter_rows(named=True)}
    picked: list[dict] = []
    used: set[str] = set()
    need = {g: slots.count(g) for g in set(slots)}
    for g, n in need.items():
        cands = [x for x in latest.iter_rows(named=True) if x["gsis_id"] and by.get(x["gsis_id"], {}).get("grp") == g]
        cands.sort(key=lambda x: (x["pos_rank"] or 9, -by[x["gsis_id"]]["rating"]))
        for x in cands:
            if len([p_ for p_ in picked if p_["grp"] == g]) >= n:
                break
            if x["gsis_id"] in used:
                continue
            rr = by[x["gsis_id"]]
            picked.append({"id": x["gsis_id"], "name": rr["full_name"], "pos": rr["position"], "grp": g, "num": rr["jersey_number"], "rating": int(rr["rating"])})
            used.add(x["gsis_id"])
    return picked


def _specialist(team: str, season: int, ratings: pl.DataFrame, grp: str) -> dict | None:
    r = ratings.filter((pl.col("season") == season) & (pl.col("team") == team) & (pl.col("grp") == grp)).sort("snaps", descending=True)
    if r.height == 0:
        return None
    x = r.row(0, named=True)
    return {"id": x["gsis_id"], "name": x["full_name"], "num": x["jersey_number"], "rating": int(x["rating"])}


def export_spot_chunks(game: dict) -> None:
    ratings = pl.read_parquet(PROCESSED_DIR / "ratings.parquet")
    rows = pl.read_parquet(ROWS_PATH, columns=["game_id", "play_id", "offense_players", "defense_players", "personnel_class", "formation"])
    coaches = {c["name"]: c for c in game["coaches"].get("coaches", [])}
    per = cfg("spots", "spots_per_chunk")
    spots = game["spots"]
    chunks: dict[int, dict] = {}
    for idx, sp in enumerate(spots):
        row = rows.filter((pl.col("game_id") == sp["game"]) & (pl.col("play_id") == sp["play_id"]))
        off = _lineup_from_ids(row["offense_players"][0] if row.height else None, ratings, sp["season"])
        de = _lineup_from_ids(row["defense_players"][0] if row.height else None, ratings, sp["season"])
        if len(off) < 11:
            off = _lineup_from_depth(sp["off"], sp["season"], ratings, OFF_SLOTS, "off")
        if len(de) < 11:
            de = _lineup_from_depth(sp["def"], sp["season"], ratings, DEF_SLOTS, "def")
        entry = {
            "off": {"team": sp["off"], "coach": sp["ctx"].get("coach"), "players": off,
                    "k": _specialist(sp["off"], sp["season"], ratings, "K"), "p": _specialist(sp["off"], sp["season"], ratings, "P"),
                    "shift": coaches.get(sp["ctx"].get("coach") or "", {}).get("shift", {}),
                    "personnel": row["personnel_class"][0] if row.height else None, "formation": row["formation"][0] if row.height else None},
            "def": {"team": sp["def"], "coach": sp["ctx"].get("def_coach"), "players": de,
                    "k": _specialist(sp["def"], sp["season"], ratings, "K"), "p": _specialist(sp["def"], sp["season"], ratings, "P"),
                    "shift": coaches.get(sp["ctx"].get("def_coach") or "", {}).get("shift", {})},
        }
        chunks.setdefault(idx // per, {})[sp["id"]] = entry
        sp["chunk"] = idx // per
    for k, v in chunks.items():
        (OUT_DIR / "spots" / f"s{k:03d}.json").write_text(json.dumps(v, separators=(",", ":")))
    sizes = [(OUT_DIR / "spots" / f"s{k:03d}.json").stat().st_size for k in chunks]
    print(f"spots/: {len(chunks)} chunks, {min(sizes) / 1e3:.0f}-{max(sizes) / 1e3:.0f} KB each")
    (OUT_DIR / "game.json").write_text(json.dumps(game, separators=(",", ":")))


if __name__ == "__main__":
    raise SystemExit(main())
