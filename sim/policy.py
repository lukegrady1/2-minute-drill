"""Auto-policy: how the opponent (and both teams inside a sim) choose actions.

League tendencies give P(call | situation); a few rules handle the end-game logic that
tendencies do not capture well (kneel-outs, spikes, must-kick field goals, onside kicks,
two-point charts, timeouts). Mirrors engine/policy.ts.
"""

from __future__ import annotations

from sim.data import EngineData
from sim.engine import DONE, FREE_KICK, KICKOFF, PAT, SNAP, State, dist_bucket, zone_of
from sim.rng import Rng


def score_state(diff: int) -> str:
    if diff < -8:
        return "trail2"
    if diff < 0:
        return "trail1"
    if diff == 0:
        return "tied"
    return "lead1" if diff <= 8 else "lead2"


def clock_bucket(clock: int) -> str:
    if clock <= 30:
        return "c30"
    if clock <= 60:
        return "c60"
    if clock <= 120:
        return "c120"
    if clock <= 300:
        return "c300"
    return "early"


def tempo_for(s: State) -> str:
    diff = s.diff
    late4 = s.qtr == 4 and s.clock <= 300
    late2 = s.qtr == 2 and s.clock <= 120
    if (late4 or late2 or s.ot) and diff <= 0:
        return "hurry"
    if late4 and diff > 0:
        return "milk"
    return "normal"


class Policy:
    def __init__(self, data: EngineData, shift: dict | None = None):
        self.data = data
        self.t = data.tendencies
        self.cfg = data.cfg
        self.shift = shift or {}   # per-coach multipliers on call probabilities (coaches.py)

    # ---- timeouts, called between plays -------------------------------------
    def wants_timeout(self, s: State, team: int, rng: Rng) -> bool:
        """Data-driven: P(timeout | half, caller role, clock bucket, caller's timeouts left)."""
        p = self.timeout_prob(s, team)
        return p > 0 and rng.chance(p)

    def choose(self, s: State, rng: Rng) -> dict:
        if s.phase == PAT:
            return self._pat(s)
        if s.phase == KICKOFF:
            return self._kickoff(s)
        if s.phase == FREE_KICK:
            return {"type": "free_kick"}
        if s.phase == DONE:
            return {"type": "noop"}
        return self._snap(s, rng)

    def _pat(self, s: State) -> dict:
        team = s.poss
        diff = s.score[team] - s.score[1 - team]
        late = (s.qtr == 4 and s.clock <= 300) or s.ot
        if late and diff in (-2, -5, -10, -13, -16, 1, 4):
            return {"type": "two_pt"}
        if s.qtr == 4 and s.clock <= 60 and diff == -2:
            return {"type": "two_pt"}
        return {"type": "xp"}

    def _kickoff(self, s: State) -> dict:
        k = s.kick_team
        diff = s.score[k] - s.score[1 - k]
        if diff < 0 and s.qtr == 4:
            budget = 60 + 45 * s.tos[k]   # seconds the kicking team could still get back with a stop
            if s.clock <= budget:
                return {"type": "onside"}
        return {"type": "kickoff"}

    # ---- scrimmage ----------------------------------------------------------
    def _snap(self, s: State, rng: Rng) -> dict:
        diff = s.diff
        tempo = tempo_for(s)
        last_period = s.qtr == 4 or s.ot or (s.qtr == 2)
        opp_tos = s.tos[1 - s.poss]

        # kneel out
        if diff > 0 and s.qtr == 4 and s.down <= 3:
            kneels = 4 - s.down
            burn = max(0, kneels - opp_tos) * 42 + min(kneels, opp_tos) * 2
            if burn >= s.clock:
                return {"type": "kneel"}
        if diff > 0 and s.qtr == 4 and s.down == 4 and s.clock <= 2:
            return {"type": "kneel"}

        in_fg_range = s.yl + 17 <= 58
        need_fg = -3 <= diff <= 0 and (s.qtr == 4 or s.ot or s.qtr == 2)
        # ---- end-game clock management when a field goal is enough
        if need_fg and in_fg_range and s.clock <= 40:
            if s.running and s.tos[s.poss] > 0:
                return {"type": "timeout", "team": s.poss}
            if s.running and s.down <= 3:
                return {"type": "spike"}
            if not s.running and (s.clock <= 15 or s.down == 4):
                return {"type": "fg"}
        # last-play logic
        if last_period and s.clock <= 6 and not s.running or (last_period and s.running and s.clock <= 8 and s.tos[s.poss] == 0):
            if in_fg_range and (diff in (-3, -2, -1, 0) or (s.qtr == 2)):
                return {"type": "fg"}
            if s.qtr == 2 and not in_fg_range:
                return {"type": "play", "call": "hail_mary" if s.yl >= 30 else "pass_deep_middle", "tempo": "hurry"}
            if diff < 0:
                return {"type": "play", "call": "hail_mary" if s.yl >= 30 else "pass_deep_middle", "tempo": "hurry"}
        # must-kick: 4th down, trailing by <= 3 or tied, late, in range
        if s.down == 4 and in_fg_range and (s.qtr == 4 or s.ot) and s.clock <= 150 and -3 <= diff <= 0:
            return {"type": "fg"}
        if s.down == 4 and in_fg_range and s.qtr == 2 and s.clock <= 30:
            return {"type": "fg"}
        # spike to stop the clock
        if s.running and s.tos[s.poss] == 0 and diff <= 0 and s.down <= 3 and (
                (s.qtr == 4 and s.clock <= 25) or (s.qtr == 2 and s.clock <= 20)):
            return {"type": "spike"}

        pcall = self._sample_call(s, rng)
        # expand the policy call into a concrete playbook call
        if pcall in ("field_goal",):
            if not in_fg_range or s.yl + 17 > self.data.fg.get("max_attempt_distance", 68):
                pcall = "punt" if diff >= 0 or s.clock > 180 else "pass_medium"
            else:
                return {"type": "fg"}
        if pcall == "punt":
            if (s.qtr == 4 and diff < 0 and s.clock <= 240 and s.tos[s.poss] < 3) or (s.qtr == 4 and diff < 0 and s.clock <= 120):
                pcall = "pass_medium"  # no punting when trailing late
            else:
                return {"type": "punt"}
        if pcall == "kneel":
            return {"type": "kneel"} if diff > 0 else {"type": "play", "call": "run_inside_middle", "tempo": tempo}
        if pcall == "spike":
            return {"type": "spike"} if s.running and s.down <= 3 else {"type": "play", "call": "pass_short_middle", "tempo": "hurry"}
        if pcall == "qb_sneak":
            if s.togo > 2 and s.yl > 2:
                pcall = "run_inside"
            else:
                return {"type": "play", "call": "qb_sneak", "tempo": tempo}
        if pcall == "hail_mary":
            if s.yl < 30 or s.clock > 20:
                pcall = "pass_deep"
            else:
                return {"type": "play", "call": "hail_mary", "tempo": "hurry"}
        if pcall in ("rpo", "screen"):
            return {"type": "play", "call": pcall, "tempo": tempo}
        if pcall in ("run_inside", "run_outside"):
            d = self._pick(self.t["direction"]["run"], rng)
            if pcall == "run_outside" and d == "middle":
                d = "left" if rng.chance(0.5) else "right"
            return {"type": "play", "call": f"{pcall}_{d}", "tempo": tempo}
        if pcall == "pa":
            dep = self._pick({"short": 0.55, "medium": 0.3, "deep": 0.15}, rng)
            d = self._pick(self.t["direction"][dep], rng)
            return {"type": "play", "call": f"pa_{dep}_{d}", "tempo": tempo}
        dep = pcall.split("_")[1]  # pass_short / pass_medium / pass_deep
        d = self._pick(self.t["direction"][dep], rng)
        return {"type": "play", "call": f"pass_{dep}_{d}", "tempo": tempo}

    def _pick(self, probs: dict[str, float], rng: Rng) -> str:
        keys = list(probs.keys())
        return keys[rng.pick_weighted([probs[k] for k in keys])]

    def timeout_prob(self, s: State, team: int) -> float:
        if s.phase != SNAP or not s.running or s.tos[team] <= 0:
            return 0.0
        diff = s.score[team] - s.score[1 - team]
        if diff > 0 or (s.qtr not in (2, 4) and not s.ot):
            return 0.0
        who = "offense" if team == s.poss else "defense"
        if who == "defense" and diff == 0:
            return 0.0
        clock = s.clock
        if (s.qtr == 4 and clock > 240) or (s.qtr == 2 and clock > 120):
            return 0.0
        cb = "c30" if clock <= 30 else "c60" if clock <= 60 else "c120" if clock <= 120 else "c180" if clock <= 180 else "c240"
        half = "h1" if s.qtr == 2 else "h2"
        table = self.data.clock["timeouts"]
        cell = table["cells"].get(f"{half}|{who}|{cb}|{s.tos[team]}")
        if cell is None or cell["n"] < table["min_n"]:
            cell = table["cells"].get(f"h2|{who}|{cb}|{s.tos[team]}")
        return float(cell["p"]) if cell else 0.0

    def call_probs(self, s: State) -> dict[str, float]:
        """League P(policy call | situation) with backoff and this coach's shift applied."""
        half = "ot" if s.ot else ("h1" if s.qtr <= 2 else "h2")
        cb = clock_bucket(s.clock)
        ss = score_state(s.diff)
        dist = dist_bucket(s.togo)
        zone = zone_of(s.yl)
        keys = [f"L0|{half}|{cb}|{ss}|{s.down}|{dist}|{zone}", f"L1|{half}|{cb}|{ss}|{s.down}|{dist}",
                f"L2|{ss}|{s.down}|{dist}|{zone}", f"L3|{s.down}|{dist}|{zone}", f"L4|{s.down}|{dist}"]
        cells = self.t["cells"]
        cell = None
        for k in keys:
            c = cells.get(k)
            if c is not None and c["n"] >= self.t["min_cell_n"]:
                cell = c
                break
        probs = dict(cell["p"]) if cell else {"pass_short": 1.0}
        for k, m in self.shift.items():
            for call in list(probs):
                if (k == "pass" and (call.startswith("pass") or call in ("pa", "rpo", "screen"))) or \
                   (k == "deep" and call == "pass_deep") or (k == "go" and s.down == 4 and call not in ("punt", "field_goal")):
                    probs[call] *= m
        tot = 0.0
        for v in probs.values():
            tot += v
        tot = tot or 1.0
        return {k: v / tot for k, v in probs.items()}

    def _sample_call(self, s: State, rng: Rng) -> str:
        return self._pick(self.call_probs(s), rng)


def coin_toss_kicker(rng: Rng) -> int:
    """Seeded OT coin toss. The winner receives, so the loser kicks."""
    return 0 if rng.chance(0.5) else 1
