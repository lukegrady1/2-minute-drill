"""Play a game out from a state with the auto-policy for everyone not being controlled."""

from __future__ import annotations

from sim.data import EngineData
from sim.engine import DONE, KICKOFF, Ctx, Engine, Event, State
from sim.policy import Policy, coin_toss_kicker
from sim.rng import Rng

MAX_STEPS = 400


def play_out(engine: Engine, s: State, rng: Rng, policies: tuple[Policy, Policy],
             log: list[Event] | None = None) -> float:
    """Advance `s` to the end (or halftime) using the two teams' policies. Returns value for team 0."""
    steps = 0
    while s.phase != DONE and steps < MAX_STEPS:
        steps += 1
        # OT coin toss when overtime starts
        if s.phase == KICKOFF and s.ot and s.ot_first == -1 and s.plays >= 0 and s.clock == _ot_len(engine, s):
            s.kick_team = coin_toss_kicker(rng)
        # defense or offense may call a timeout before the snap
        if s.phase == "snap" and s.running:
            for team in (1 - s.poss, s.poss):
                if policies[team].wants_timeout(s, team, rng):
                    ev = engine.step(s, {"type": "timeout", "team": team}, rng)
                    if log is not None:
                        log.append(ev)
                    break
        actor = s.poss if s.phase != KICKOFF and s.phase != "free_kick" else s.kick_team
        action = policies[actor].choose(s, rng)
        if action["type"] == "noop":
            break
        if action["type"] == "timeout" and (not s.running or s.tos[action["team"]] <= 0):
            action = {"type": "spike"} if s.running else policies[actor].choose(s, rng)
        ev = engine.step(s, action, rng)
        if log is not None:
            log.append(ev)
    return engine.value(s)


def _ot_len(engine: Engine, s: State) -> int:
    ot = engine.cfg["rules"]["overtime"]
    return 60 * (ot["playoff_minutes"] if engine.ctx.playoff else ot["regular_season_minutes"])


def state_from_spot(spot: dict) -> tuple[State, Ctx]:
    st = spot["state"]
    ctx = spot.get("ctx", {})
    s = State(qtr=st["qtr"], clock=st["clock"], running=False, poss=0, down=st["down"], togo=st["togo"],
              yl=st["yl"], score=[st["score"][0], st["score"][1]], tos=[st["tos"][0], st["tos"][1]],
              phase="snap", warned=st["clock"] <= 120, recv2h=0 if st.get("recv2h") else 1)
    roof = ctx.get("roof") or ""
    c = Ctx(spread=float(ctx.get("spread") or 0.0), indoor=roof in ("dome", "closed"),
            wind=float(ctx.get("wind") or 0.0), temp=float(ctx.get("temp") or 60.0),
            playoff=bool(spot.get("playoff")), end_at_half=st["qtr"] == 2)
    return s, c


def simulate_spot(data: EngineData, spot: dict, n: int, seed: int) -> float:
    """Mean value for team 0 over n games from the spot's start state, both sides on auto-policy."""
    s0, ctx = state_from_spot(spot)
    engine = Engine(data, ctx)
    pol = (Policy(data), Policy(data))
    rng = Rng(seed)
    total = 0.0
    for _ in range(n):
        s = s0.copy()
        total += play_out(engine, s, rng.fork(), pol)
    return total / n
