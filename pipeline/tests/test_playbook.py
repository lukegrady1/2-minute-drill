import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.playbook import add_clock


def _row(pid, ptype, gsr, half="Half1", desc="play"):
    return {"game_id": "g", "play_id": pid, "play_type": ptype, "game_seconds_remaining": gsr,
            "game_half": half, "desc": desc}


def test_runoff_is_seconds_to_next_snap_in_same_half():
    df = pl.DataFrame([
        _row(1, None, 3600, desc="GAME"),
        _row(2, "kickoff", 3600),
        _row(3, "run", 3600),
        _row(4, "pass", 3565),          # 35 s after the run
        _row(5, "no_play", 3540, desc="Timeout #1 by X at 59:00."),
        _row(6, "pass", 3540),          # the snap after the timeout
        _row(7, None, 1800, desc="END QUARTER 2"),
        _row(8, "kickoff", 1800, half="Half2"),
    ])
    out = add_clock(df).sort("play_id")
    by = {r["play_id"]: r for r in out.to_dicts()}
    assert by[3]["runoff_s"] == 35
    assert by[4]["runoff_s"] == 25            # pass at 3565 -> next snap (play 6) at 3540
    assert by[4]["timeout_after"] is True     # timeout row sits between play 4 and play 6
    assert by[3]["timeout_after"] is False
    assert by[6]["runoff_s"] is None          # next snap is in the other half
    assert by[2]["runoff_s"] == 0             # kickoff and first snap share the clock


def test_timeout_rows_are_not_snaps():
    df = pl.DataFrame([
        _row(1, "run", 100),
        _row(2, "no_play", 90, desc="Timeout #2 by Y at 01:30."),
        _row(3, "no_play", 90, desc="(1:30) Penalty on Z, False Start, 5 yards - No Play."),
        _row(4, "pass", 85),
    ])
    out = add_clock(df).sort("play_id")
    by = {r["play_id"]: r for r in out.to_dicts()}
    assert by[1]["runoff_s"] == 10            # the no-play penalty snap counts as the next snap
    assert by[1]["timeout_after"] is True
    assert by[3]["runoff_s"] == 5
