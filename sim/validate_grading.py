"""Phase 3 checks: grade stability across seeds, and the percentile spread for test policies.

    uv run python sim/validate_grading.py
Writes docs/phase3_grading.md.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sim.data import load, load_game
from sim.engine import Engine
from sim.grading import grade, nearest_coach, percentile, player_traits
from sim.policy import Policy
from sim.rng import Rng
from sim.simulate import state_from_spot

DOCS = Path(__file__).resolve().parent.parent / "docs"


def drive_with_policy(data, spot, pick, seed, n1, n2):
    """Play the spot's first possession as team 0, grading each decision; `pick(grade_table)` chooses."""
    s, ctx = state_from_spot(spot)
    eng = Engine(data, ctx)
    pols = (Policy(data), Policy(data))
    rng = Rng(seed)
    decisions, calls = [], []
    steps = 0
    while s.phase == "snap" and s.poss == 0 and steps < 25:
        steps += 1
        # a provisional chosen action (needed by grade() to know the tempo); replaced by pick()
        g = grade(eng, s, {"type": "play", "call": "pass_short_middle", "tempo": "hurry"}, seed + steps, pols, n1=n1, n2=n2)
        i = pick(g, rng)
        g.chosen = i
        g.gap = max(0.0, g.options[g.best].wp - g.options[i].wp)
        g.color = "green" if g.gap < 0.01 else ("yellow" if g.gap < 0.04 else "red")
        decisions.append(g)
        calls.append((s.copy(), g.options[i].action))
        eng.step(s, g.options[i].action, rng)
    return decisions, calls


def main() -> int:
    data = load()
    game = load_game()
    n1, n2 = 150, 600   # smaller than production (600/3000) to keep the Python check quick
    md = ["# Phase 3: grading and percentile checks\n"]

    # ---- 1. stability of one decision across seeds
    spot = next(sp for sp in game["spots"] if sp["cat"] == "drill" and sp["state"]["qtr"] == 4 and sp["state"]["tos"][0] >= 2)
    s, ctx = state_from_spot(spot)
    eng = Engine(data, ctx)
    pols = (Policy(data), Policy(data))
    chosen = {"type": "play", "call": "pass_medium_right", "tempo": "hurry"}
    t0 = time.time()
    grades = [grade(eng, s, chosen, seed, pols, n1=600, n2=3000) for seed in range(1, 6)]
    dt = (time.time() - t0) / 5
    gaps = [g.gap for g in grades]
    bests = [g.options[g.best].label for g in grades]
    md.append(f"## Stability across seeds (production sim counts 600/3000)\n\nSpot {spot['id']}, state {spot['state']}, chosen `{chosen['call']}`. "
              f"{dt:.1f} s per grade in Python ({len(grades[0].options)} options).\n")
    md.append("| seed | best | gap | color |\n|---|---|---:|---|")
    for i, g in enumerate(grades, 1):
        md.append(f"| {i} | {bests[i - 1]} | {100 * g.gap:.2f}% | {g.color} |")
    md.append(f"\ngap mean {100 * statistics.mean(gaps):.2f}%, sd {100 * statistics.pstdev(gaps):.2f}%, colors {sorted({g.color for g in grades})}")
    top = sorted(grades[0].options, key=lambda o: -o.wp)[:6]
    md.append("\nTop options, seed 1:\n\n| option | q | WP r1 | WP r2 |\n|---|---:|---:|---:|")
    for o in top:
        md.append(f"| {o.label} | {o.q:.3f} | {o.wp1:.3f} | {'' if o.wp2 is None else f'{o.wp2:.3f}'} |")

    # ---- 2. percentile spread for test policies over several spots
    import math
    def best_pick(g, rng):
        return g.best
    def league_pick(g, rng):
        return rng.pick_weighted([o.q for o in g.options])
    def worst_pick(g, rng):
        return max(range(len(g.options)), key=lambda i: g.gaps[i])
    def softmax_pick(tau):
        return lambda g, rng: rng.pick_weighted([o.q * math.exp(-gp / tau) for o, gp in zip(g.options, g.gaps, strict=True)])
    policies = {"always best": best_pick, "league frequency": league_pick, "softmax tau=0.01": softmax_pick(0.01),
                "softmax tau=0.05": softmax_pick(0.05), "always worst": worst_pick}
    spots = [sp for sp in game["spots"] if sp["state"]["qtr"] == 4][:6]
    md.append(f"\n## Percentile for test policies ({len(spots)} Q4 spots, sims {n1}/{n2})\n\n| policy | " + " | ".join(sp["id"][:15] for sp in spots) + " | mean |\n|---|" + "---:|" * (len(spots) + 1))
    coach_lines = []
    for name, pick in policies.items():
        pcts = []
        for k, sp in enumerate(spots):
            decisions, calls = drive_with_policy(data, sp, pick, 100 + k, n1, n2)
            pcts.append(percentile(decisions, data, seed=7)["percentile"])
            if name == "always best" and k == 0:
                traits, counts = player_traits(calls, data, Policy(data))
                m = nearest_coach(traits, counts, game["coaches"])
                coach_lines.append(f"Best-policy drive on {sp['id']}: traits {{" + ", ".join(f"{a}: {b:+.2f}" for a, b in traits.items()) + f"}}, nearest coach **{m['coach']}**, reasons {m['reasons']}")
        md.append(f"| {name} | " + " | ".join(f"{p:.0f}" for p in pcts) + f" | {statistics.mean(pcts):.0f} |")
    md.append("\n## Coach match smoke test\n\n" + "\n".join(coach_lines))
    text = "\n".join(md) + "\n"
    DOCS.mkdir(exist_ok=True)
    (DOCS / "phase3_grading.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
