"""Decision grading, the virtual play-caller percentile, and coach matching. Mirrors engine/grading.ts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sim.data import EngineData
from sim.engine import KICKOFF, PAT, SNAP, Engine, State, dist_bucket
from sim.policy import Policy, tempo_for
from sim.rng import Rng
from sim.simulate import play_out

M32 = 0xFFFFFFFF
GADGET_CALLS = {"gadget", "hail_mary"}


@dataclass
class Option:
    action: dict
    label: str
    q: float = 0.0          # league frequency of this option in this situation
    wp1: float = 0.0
    n1: int = 0
    wp2: float | None = None
    n2: int = 0
    gadget: bool = False

    @property
    def wp(self) -> float:
        return self.wp2 if self.wp2 is not None else self.wp1


@dataclass
class Grade:
    options: list[Option]
    chosen: int
    best: int
    gap: float
    color: str
    seed: int
    better: str | None = None
    gaps: list[float] = field(default_factory=list)   # per option, vs best (for the percentile)


def option_seed(seed: int, round_: int, i: int) -> int:
    return (seed + 1000003 * round_ + 7919 * i) & M32


def action_label(a: dict) -> str:
    t = a["type"]
    if t == "play":
        return a["call"]
    if t == "look":
        return f"{a['box']}_{'blitz' if a['blitz'] else 'base'}"
    if t == "timeout":
        return "timeout"
    return t


# ---------------------------------------------------------------- options + league q


def offense_options(engine: Engine, s: State, tempo: str) -> list[Option]:
    opts = []
    for a in engine.legal_actions(s):
        if a["type"] == "timeout" and a.get("team") != s.poss:
            continue
        a = dict(a)
        if a["type"] == "play":
            a["tempo"] = tempo
        opts.append(Option(action=a, label=action_label(a), gadget=a.get("call") in GADGET_CALLS))
    return opts


def defense_options(engine: Engine, s: State, team: int) -> list[Option]:
    opts = [Option(action={"type": "look", "box": b, "blitz": z}, label=f"{b}_{'blitz' if z else 'base'}")
            for b in ("light", "heavy") for z in (False, True)]
    if s.running and s.tos[team] > 0:
        opts.append(Option(action={"type": "timeout", "team": team}, label="timeout"))
    return opts


def league_q(data: EngineData, policy: Policy, s: State, opts: list[Option]) -> None:
    """Fill each option's league frequency q from the tendencies / looks / timeout tables."""
    t = data.tendencies
    if opts and opts[0].action["type"] == "look":
        key = f"{s.down}|{dist_bucket(s.togo)}"
        cell = data.looks["by_down_dist"].get(key, data.looks["overall"])
        for o in opts:
            if o.action["type"] == "look":
                pb = cell["p_light"] if o.action["box"] == "light" else 1 - cell["p_light"]
                pz = cell["p_blitz"] if o.action["blitz"] else 1 - cell["p_blitz"]
                o.q = pb * pz
            else:
                o.q = 0.1
        return
    if s.phase == PAT:
        for o in opts:
            o.q = 0.9 if o.action["type"] == "xp" else 0.1
        return
    if s.phase == KICKOFF:
        for o in opts:
            o.q = 0.95 if o.action["type"] == "kickoff" else 0.05
        return
    probs = policy.call_probs(s)     # pcall -> p
    dirs = t["direction"]
    for o in opts:
        a = o.action
        q = 0.0
        if a["type"] == "play":
            call = a["call"]
            if call.startswith(("pass_", "pa_")):
                fam, dep, d = call.split("_")
                if fam == "pass":
                    q = probs.get(f"pass_{dep}", 0.0) * dirs[dep].get(d, 1 / 3)
                else:
                    q = probs.get("pa", 0.0) * {"short": 0.55, "medium": 0.3, "deep": 0.15}[dep] * dirs[dep].get(d, 1 / 3)
            elif call.startswith("run_"):
                fam = "run_inside" if call.startswith("run_inside") else "run_outside"
                d = call.rsplit("_", 1)[1]
                q = probs.get(fam, 0.0) * dirs["run"].get(d, 1 / 3)
            else:
                q = probs.get(call, 0.0)
        elif a["type"] == "fg":
            q = probs.get("field_goal", 0.0)
        elif a["type"] in ("spike", "kneel", "punt"):
            q = probs.get(a["type"], 0.0)
        elif a["type"] == "timeout":
            q = policy.timeout_prob(s, a["team"])
        o.q = max(q, 1e-4)


# ---------------------------------------------------------------- simulation of one option


def simulate_option(engine: Engine, s0: State, opt: Option, n: int, seed: int,
                    policies: tuple[Policy, Policy], team: int = 0) -> float:
    rng = Rng(seed)
    total = 0.0
    for _ in range(n):
        s = s0.copy()
        r = rng.fork()
        a = opt.action
        if a["type"] == "look":
            # opponent's play with this look forced; team is on defense
            act = policies[s.poss].choose(s, r)
            if act["type"] == "play":
                engine.step(s, act, r, look={"box": a["box"], "blitz": a["blitz"]})
            else:
                engine.step(s, act, r)
        else:
            engine.step(s, a, r)
        v = play_out(engine, s, r, policies)
        total += v if team == 0 else 1.0 - v
    return total / n


def grade(engine: Engine, s: State, chosen: dict, seed: int, policies: tuple[Policy, Policy] | None = None,
          team: int = 0, n1: int | None = None, n2: int | None = None) -> Grade:
    data = engine.data
    g = data.cfg["grading"]
    n1 = n1 or g["round1_sims"]
    n2 = n2 or g["round2_sims"]
    policies = policies or (Policy(data), Policy(data))
    if s.phase == SNAP and s.poss != team:
        opts = defense_options(engine, s, team)
    elif s.phase == SNAP:
        tempo = chosen.get("tempo", tempo_for(s)) if chosen.get("type") == "play" else tempo_for(s)
        opts = offense_options(engine, s, tempo)
    else:
        opts = [Option(action=a, label=action_label(a)) for a in engine.legal_actions(s)]
    league_q(data, policies[team], s, opts)
    ci = next((i for i, o in enumerate(opts) if action_label(o.action) == action_label(chosen)), None)
    if ci is None:
        opts.append(Option(action=chosen, label=action_label(chosen), q=1e-4, gadget=chosen.get("call") in GADGET_CALLS))
        ci = len(opts) - 1
    # round 1
    for i, o in enumerate(opts):
        o.wp1 = simulate_option(engine, s, o, n1, option_seed(seed, 1, i), policies, team)
        o.n1 = n1
    # round 2: top-k eligible + chosen, fresh seeds
    eligible = [i for i, o in enumerate(opts) if not o.gadget]
    top = sorted(eligible, key=lambda i: -opts[i].wp1)[: g["round2_top_k"]]
    for i in set(top) | {ci}:
        opts[i].wp2 = simulate_option(engine, s, opts[i], n2, option_seed(seed, 2, i), policies, team)
        opts[i].n2 = n2
    best = max((i for i in eligible if opts[i].wp2 is not None), key=lambda i: opts[i].wp2, default=ci)
    if opts[ci].wp > opts[best].wp:
        best = ci
    gap = max(0.0, opts[best].wp - opts[ci].wp)
    color = "green" if gap < g["green_max_gap"] else ("yellow" if gap < g["yellow_max_gap"] else "red")
    gaps = [max(0.0, opts[best].wp - o.wp) for o in opts]
    return Grade(options=opts, chosen=ci, best=best, gap=gap, color=color, seed=seed,
                 better=(opts[best].label if best != ci else None), gaps=gaps)


# ---------------------------------------------------------------- percentile


def percentile(decisions: list[Grade], data: EngineData, seed: int) -> dict:
    """Share of virtual play-callers whose total WP cost over the drive exceeds the player's."""
    p = data.cfg["percentile"]
    rng = Rng(seed)
    player_cost = sum(d.gap for d in decisions)
    lo, hi = math.log(p["tau_log_uniform_min"]), math.log(p["tau_log_uniform_max"])
    worse = 0.0
    costs = []
    n = p["virtual_callers"]
    for _ in range(n):
        tau = math.exp(lo + rng.next() * (hi - lo))
        league_only = rng.chance(p["pure_league_frequency_share"])
        cost = 0.0
        for d in decisions:
            if league_only:
                w = [o.q for o in d.options]
            else:
                w = [o.q * math.exp(-gap / tau) for o, gap in zip(d.options, d.gaps, strict=True)]
            i = rng.pick_weighted(w)
            cost += d.gaps[i]
        costs.append(cost)
        if cost > player_cost + 1e-12:
            worse += 1
        elif abs(cost - player_cost) <= 1e-12:
            worse += 0.5
    return {"percentile": 100.0 * worse / n, "cost": player_cost, "n": n,
            "hist": _hist(costs, 10)}


def _hist(costs: list[float], bins: int) -> list[int]:
    if not costs:
        return []
    hi = max(costs) or 1.0
    h = [0] * bins
    for c in costs:
        h[min(bins - 1, int(c / hi * bins))] += 1
    return h


# ---------------------------------------------------------------- "you coached like"

TRAIT_LABELS = {
    "pass": ("threw more than the league would", "ran more than the league would"),
    "deep": ("took more deep shots", "kept it short"),
    "go": ("went for it on 4th down", "kicked on 4th down"),
    "timeout": ("burned timeouts early", "sat on timeouts"),
    "tempo": ("played slower", "played faster"),
}


def player_traits(decisions: list[tuple[State, dict]], data: EngineData, policy: Policy) -> tuple[dict, dict]:
    """Per-trait (delta vs league, supporting count) from the player's calls at their states."""
    acc = {k: [0.0, 0] for k in ("pass", "deep", "go", "timeout", "tempo")}
    for s, a in decisions:
        if s.phase != SNAP:
            continue
        probs = policy.call_probs(s)
        is_play = a["type"] == "play"
        if is_play or a["type"] in ("fg", "punt"):
            exp_pass = sum(v for k, v in probs.items() if k.startswith("pass") or k in ("pa", "rpo", "screen", "hail_mary"))
            exp_scrim = sum(v for k, v in probs.items() if k not in ("field_goal", "punt", "kneel", "spike"))
            if is_play and exp_scrim > 0:
                call = a["call"]
                is_pass = not call.startswith("run") and call != "qb_sneak"
                acc["pass"][0] += (1.0 if is_pass else 0.0) - exp_pass / exp_scrim
                acc["pass"][1] += 1
                if is_pass:
                    exp_deep = (probs.get("pass_deep", 0) + 0.15 * probs.get("pa", 0) + probs.get("hail_mary", 0)) / max(exp_pass, 1e-9)
                    acc["deep"][0] += (1.0 if "deep" in call or call == "hail_mary" else 0.0) - exp_deep
                    acc["deep"][1] += 1
            if s.down == 4:
                exp_go = 1.0 - probs.get("field_goal", 0) - probs.get("punt", 0)
                acc["go"][0] += (1.0 if is_play else 0.0) - exp_go
                acc["go"][1] += 1
        if s.running and s.tos[0] > 0 and s.diff <= 0 and s.poss == 0:
            exp_to = policy.timeout_prob(s, 0)
            acc["timeout"][0] += (1.0 if a["type"] == "timeout" else 0.0) - exp_to
            acc["timeout"][1] += 1
        if is_play and s.running:
            tempo = a.get("tempo", "normal")
            mean = {"hurry": 18.0, "normal": 32.0, "milk": 36.0}[tempo]
            exp_t = {"hurry": 18.0, "normal": 32.0, "milk": 36.0}[tempo_for(s)]
            acc["tempo"][0] += mean - exp_t
            acc["tempo"][1] += 1
    # shrink toward 0 with few decisions: a 3-call drive should not look like a 3,000-play career
    k = 4.0
    traits = {kk: (v[0] / v[1] * v[1] / (v[1] + k) if v[1] else 0.0) for kk, v in acc.items()}
    counts = {kk: v[1] for kk, v in acc.items()}
    return traits, counts


def nearest_coach(traits: dict, counts: dict, coaches: dict, min_support: int = 3) -> dict:
    scales = coaches.get("scales", {})
    best, best_d = None, float("inf")
    for coach in coaches.get("coaches", []):
        d = 0.0
        for k, v in traits.items():
            if counts.get(k, 0) == 0:
                continue
            sc = scales.get(k, 1.0) or 1.0
            d += ((v - coach["traits"].get(k, 0.0)) / sc) ** 2
        if d < best_d:
            best, best_d = coach, d
    reasons = []
    if best:
        for k, (pos, neg) in TRAIT_LABELS.items():
            if counts.get(k, 0) >= min_support and abs(traits.get(k, 0.0)) > (scales.get(k, 1.0) or 1.0):
                same_sign = (traits[k] > 0) == (best["traits"].get(k, 0.0) > 0)
                if same_sign:
                    reasons.append(pos if traits[k] > 0 else neg)
    return {"coach": best["name"] if best else None, "distance": best_d, "reasons": reasons}
