"""Dump fixed-seed games and one grade from the Python engine for the TS parity test.

    uv run python sim/parity_dump.py   -> engine/fixtures/parity.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sim.data import load, load_game
from sim.engine import Engine
from sim.grading import grade
from sim.policy import Policy
from sim.rng import Rng
from sim.simulate import play_out, state_from_spot

OUT = Path(__file__).resolve().parent.parent / "engine" / "fixtures" / "parity.json"


def main() -> int:
    data = load()
    game = load_game()
    spots = [sp for sp in game["spots"] if sp["state"]["qtr"] == 4][:50] + [sp for sp in game["spots"] if sp["state"]["qtr"] == 2][:10]
    games = []
    for i, sp in enumerate(spots):
        s0, ctx = state_from_spot(sp)
        eng = Engine(data, ctx)
        pol = (Policy(data), Policy(data))
        for k in range(20):
            s = s0.copy()
            log = []
            v = play_out(eng, s, Rng(i * 1000 + k), pol, log)
            games.append({"spot": sp["id"], "seed": i * 1000 + k, "value": v, "score": s.score, "qtr": s.qtr, "clock": s.clock,
                          "plays": s.plays, "events": [[e.kind, e.text, e.yards, e.score[0], e.score[1], e.presnap, e.duration] for e in log]})
    r = Rng(12345)
    rng_seq = [r.next() for _ in range(5)] + [Rng(0).next(), Rng(0xFFFFFFFF).next()]
    sp = spots[0]
    s0, ctx = state_from_spot(sp)
    eng = Engine(data, ctx)
    g = grade(eng, s0, {"type": "play", "call": "pass_medium_right", "tempo": "hurry"}, 42, n1=20, n2=60)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "rng": rng_seq,
        "games": games,
        "grade": {"spot": sp["id"], "seed": 42, "n1": 20, "n2": 60, "chosen": "pass_medium_right",
                  "options": [{"label": o.label, "q": o.q, "wp1": o.wp1, "wp2": o.wp2} for o in g.options],
                  "best": g.options[g.best].label, "gap": g.gap},
    }))
    print(f"wrote {OUT} with {len(games)} games")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
