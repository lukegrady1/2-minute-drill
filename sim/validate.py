"""Validate the simulator: replay real Q4 spots and compare simulated win rates to reality.

    uv run python sim/validate.py [--n 100] [--max-spots 2000]

Writes docs/phase2_validation.md. PLAN.md exit: within ~3 points overall and by bucket.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sim.data import load, load_game
from sim.simulate import simulate_spot

DOCS = Path(__file__).resolve().parent.parent / "docs"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--max-spots", type=int, default=5000)
    ap.add_argument("--q2", action="store_true", help="also validate Q2 spots against the WP model")
    args = ap.parse_args(argv)

    data = load()
    game = load_game()
    spots = [sp for sp in game["spots"] if sp["state"]["qtr"] == 4 and sp["real"]["outcome"] in ("win", "loss", "tie")]
    spots = spots[: args.max_spots]
    rows = []
    for i, sp in enumerate(spots):
        sim = simulate_spot(data, sp, args.n, seed=1000 + i)
        actual = {"win": 1.0, "loss": 0.0, "tie": 0.5}[sp["real"]["outcome"]]
        st = sp["state"]
        rows.append({
            "id": sp["id"], "cat": sp["cat"], "sim": sim, "actual": actual, "vegas": sp.get("wp0"),
            "diff": st["score"][0] - st["score"][1], "tos": st["tos"][0], "clock": st["clock"],
            "yl": st["yl"], "down": st["down"],
        })
    sim = np.array([r["sim"] for r in rows]); act = np.array([r["actual"] for r in rows])
    veg = np.array([r["vegas"] if r["vegas"] is not None else np.nan for r in rows])
    md = [f"# Phase 2 validation\n\n{len(rows):,} Q4 spots x {args.n} sims each, both sides on auto-policy.\n"]
    md.append("| metric | value |\n|---|---:|")
    md.append(f"| mean simulated win rate | {sim.mean():.3f} |")
    md.append(f"| mean actual win rate | {act.mean():.3f} |")
    md.append(f"| gap (points) | {100 * (sim.mean() - act.mean()):+.1f} |")
    md.append(f"| mean nflverse vegas_wp at the spot | {np.nanmean(veg):.3f} |")
    md.append(f"| MAE sim vs vegas_wp | {np.nanmean(np.abs(sim - veg)):.3f} |")
    md.append(f"| Brier sim | {np.mean((sim - act) ** 2):.4f} |")
    md.append(f"| Brier vegas_wp | {np.nanmean((veg - act) ** 2):.4f} |")

    def bucket(name, keyfn):
        md.append(f"\n## By {name}\n\n| bucket | n | sim | actual | gap | vegas |\n|---|---:|---:|---:|---:|---:|")
        groups: dict = {}
        for r in rows:
            groups.setdefault(keyfn(r), []).append(r)
        for k in sorted(groups, key=lambda x: (str(type(x)), x)):
            g = groups[k]
            s_ = np.mean([r["sim"] for r in g]); a_ = np.mean([r["actual"] for r in g])
            v_ = np.nanmean([r["vegas"] if r["vegas"] is not None else np.nan for r in g])
            md.append(f"| {k} | {len(g)} | {s_:.3f} | {a_:.3f} | {100 * (s_ - a_):+.1f} | {v_:.3f} |")

    bucket("category", lambda r: r["cat"])
    bucket("score margin", lambda r: ("trail 9+" if r["diff"] < -8 else "trail 4-8" if r["diff"] < -3 else "trail 1-3" if r["diff"] < 0
                                     else "tied" if r["diff"] == 0 else "lead 1-3" if r["diff"] <= 3 else "lead 4-8"))
    bucket("timeouts left (offense)", lambda r: r["tos"])
    bucket("clock", lambda r: "0:00-0:30" if r["clock"] <= 30 else "0:31-1:00" if r["clock"] <= 60 else "1:01-2:00" if r["clock"] <= 120 else "2:01-2:30")
    bucket("field position", lambda r: "own 1-20" if r["yl"] > 80 else "own 21-50" if r["yl"] > 50 else "opp 49-21" if r["yl"] > 20 else "red zone")
    # calibration deciles
    md.append("\n## Calibration (sim decile -> actual)\n\n| sim range | n | sim | actual |\n|---|---:|---:|---:|")
    dec = np.clip((sim * 10).astype(int), 0, 9)
    for b in range(10):
        m = dec == b
        if m.sum():
            md.append(f"| {b / 10:.1f}-{(b + 1) / 10:.1f} | {m.sum()} | {sim[m].mean():.3f} | {act[m].mean():.3f} |")
    text = "\n".join(md) + "\n"
    DOCS.mkdir(exist_ok=True)
    (DOCS / "phase2_validation.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
