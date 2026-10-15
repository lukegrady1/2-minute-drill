"""Seeded game-ending simulator: state, legal actions, and step(). Mirrors engine/engine.ts.

Teams are indices: 0 = the player's team in a spot, 1 = the opponent. `poss` is the team with
the ball. Scores, timeouts, and the OT bookkeeping are indexed the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from sim.data import EngineData
from sim.models import draw_hist, fg_prob, win_prob
from sim.rng import Rng

SNAP, PAT, KICKOFF, FREE_KICK, DONE = "snap", "pat", "kickoff", "free_kick", "done"
RUN_FAMILIES = ("run_inside", "run_outside", "qb_sneak")
PASS_FAMILIES = ("pass", "pa", "rpo", "screen", "hail_mary", "gadget")


@dataclass
class Ctx:
    """Per-game context that does not change during the sim."""
    spread: float = 0.0          # from team 0's perspective (positive = team 0 favored)
    indoor: bool = False
    wind: float = 0.0
    temp: float = 60.0
    playoff: bool = False
    end_at_half: bool = False    # Q2 spots stop at halftime and are valued by the WP model


@dataclass
class State:
    qtr: int = 4
    clock: int = 120
    running: bool = False
    poss: int = 0
    down: int = 1
    togo: int = 10
    yl: int = 75
    score: list[int] = field(default_factory=lambda: [0, 0])
    tos: list[int] = field(default_factory=lambda: [3, 3])
    phase: str = SNAP
    warned: bool = False
    recv2h: int = 1
    kick_team: int = 0
    ot_first: int = -1               # team that possessed first in OT (-1 = not in OT)
    ot_done: list[bool] = field(default_factory=lambda: [False, False])
    plays: int = 0

    def copy(self) -> State:
        return replace(self, score=list(self.score), tos=list(self.tos), ot_done=list(self.ot_done))

    @property
    def ot(self) -> bool:
        return self.qtr >= 5

    @property
    def diff(self) -> int:
        """Score margin from the possessing team's view."""
        return self.score[self.poss] - self.score[1 - self.poss]

    def seconds_left_regulation(self) -> int:
        if self.qtr >= 5:
            return 0
        return self.clock + (4 - self.qtr) * 900

    def half_seconds_left(self) -> int:
        if self.qtr >= 5:
            return self.clock
        return self.clock + (900 if self.qtr in (1, 3) else 0)


@dataclass
class Event:
    """What happened on one step, for the UI, the log, and tests."""
    kind: str                       # play | timeout | spike | kneel | fg | punt | pat | kickoff | period | warning
    text: str = ""
    yards: int = 0
    call: str = ""
    look: str = ""
    row: int = -1
    level: str = ""
    td: bool = False
    turnover: bool = False
    first_down: bool = False
    penalty: int = 0
    score: list[int] = field(default_factory=lambda: [0, 0])
    duration: int = 0
    presnap: int = 0
    made: bool | None = None
    ended: bool = False             # the period (or game) ended on this step


# ---------------------------------------------------------------- helpers


def zone_of(yl: int) -> str:
    if yl <= 10:
        return "gl"
    if yl <= 20:
        return "rz"
    if yl <= 60:
        return "mid"
    if yl <= 80:
        return "own"
    return "deep"


def dist_bucket(togo: int) -> str:
    return "short" if togo <= 3 else ("mid" if togo <= 7 else "long")


def call_family(call: str) -> str:
    for fam in ("run_inside", "run_outside", "qb_sneak", "pass", "pa", "rpo", "screen", "hail_mary", "gadget"):
        if call == fam or call.startswith(fam + "_"):
            if fam == "pass" and call.startswith("pa_"):
                continue
            return fam
    raise ValueError(f"unknown call {call}")


def _period_length(state: State, data: EngineData, ctx: Ctx) -> int:
    if state.qtr >= 5:
        ot = data.cfg["rules"]["overtime"]
        return 60 * (ot["playoff_minutes"] if ctx.playoff else ot["regular_season_minutes"])
    return 900


# ---------------------------------------------------------------- the engine


class Engine:
    def __init__(self, data: EngineData, ctx: Ctx):
        self.data = data
        self.ctx = ctx
        self.cfg = data.cfg
        self.min_n = data.cfg["playbook"]["min_bucket_size"]

    # ---- legal actions ------------------------------------------------------
    def legal_actions(self, s: State) -> list[dict]:
        if s.phase == DONE:
            return []
        if s.phase == PAT:
            return [{"type": "xp"}, {"type": "two_pt"}]
        if s.phase == KICKOFF:
            return [{"type": "kickoff"}, {"type": "onside"}]
        if s.phase == FREE_KICK:
            return [{"type": "free_kick"}]
        acts: list[dict] = []
        for fam in RUN_FAMILIES:
            if fam == "qb_sneak":
                if s.togo <= 2 or s.yl <= 2:
                    acts.append({"type": "play", "call": "qb_sneak"})
            else:
                for d in (("left", "middle", "right") if fam == "run_inside" else ("left", "right")):
                    acts.append({"type": "play", "call": f"{fam}_{d}"})
        for fam in ("pass", "pa"):
            for dep in ("short", "medium", "deep"):
                for d in ("left", "middle", "right"):
                    acts.append({"type": "play", "call": f"{fam}_{dep}_{d}"})
        acts += [{"type": "play", "call": "rpo"}, {"type": "play", "call": "screen"}]
        if s.yl >= 30:
            acts.append({"type": "play", "call": "hail_mary"})
        acts.append({"type": "play", "call": "gadget"})
        acts.append({"type": "spike"})
        acts.append({"type": "kneel"})
        if s.yl + 17 <= self.data.fg.get("max_attempt_distance", 68):
            acts.append({"type": "fg"})
        acts.append({"type": "punt"})
        if s.tos[s.poss] > 0 and s.running:
            acts.append({"type": "timeout", "team": s.poss})
        if s.tos[1 - s.poss] > 0 and s.running:
            acts.append({"type": "timeout", "team": 1 - s.poss})
        return acts

    # ---- clock --------------------------------------------------------------
    def _presnap(self, s: State, tempo: str, rng: Rng) -> tuple[int, Event | None]:
        """Run the clock before the snap. Returns (seconds used, period/warning event or None)."""
        if not s.running:
            return 0, None
        t = draw_hist(self.data.clock["tempo"][tempo], rng)
        t = min(t, self.cfg["clock"]["play_clock_seconds"])
        before = s.clock
        s.clock = max(0, s.clock - t)
        used = before - s.clock
        warn_at = self.cfg["clock"]["two_minute_warning_seconds"]
        if (not s.warned) and s.qtr in (2, 4) and before > warn_at and s.clock <= warn_at:
            s.clock = warn_at
            s.warned = True
            s.running = False
            return before - s.clock, Event(kind="warning", text="Two-minute warning", score=list(s.score))
        if s.clock == 0:
            return used, self._end_period(s)
        return used, None

    def _after_play_clock(self, s: State, duration: int, stops: bool) -> Event | None:
        before = s.clock
        self._last_ended = False
        s.clock = max(0, s.clock - duration)
        s.running = not stops
        warn_at = self.cfg["clock"]["two_minute_warning_seconds"]
        if (not s.warned) and s.qtr in (2, 4) and before > warn_at and s.clock <= warn_at:
            s.warned = True
            s.running = False
            s.clock = max(s.clock, 0)
        if s.clock == 0:
            self._last_ended = True
            return self._end_period(s)
        return None

    def _end_period(self, s: State) -> Event:
        """Clock hit zero. Advance the period or end the game."""
        s.running = False
        if s.qtr == 1 or s.qtr == 3:
            s.qtr += 1
            s.clock = 900
            return Event(kind="period", text=f"End of Q{s.qtr - 1}", score=list(s.score))
        if s.qtr == 2:
            if self.ctx.end_at_half:
                s.phase = DONE
                return Event(kind="period", text="Halftime", score=list(s.score))
            s.qtr = 3
            s.clock = 900
            s.warned = False
            s.tos = [3, 3]
            s.phase = KICKOFF
            s.kick_team = 1 - s.recv2h
            return Event(kind="period", text="Halftime", score=list(s.score))
        if s.qtr == 4:
            if s.score[0] != s.score[1]:
                s.phase = DONE
                return Event(kind="period", text="Final", score=list(s.score))
            return self._start_overtime(s)
        # overtime period expired
        ot = self.cfg["rules"]["overtime"]
        if s.score[0] != s.score[1]:
            s.phase = DONE
            return Event(kind="period", text="Final (OT)", score=list(s.score))
        if self.ctx.playoff or not ot["regular_season_can_tie"]:
            s.qtr += 1
            s.clock = _period_length(s, self.data, self.ctx)
            return Event(kind="period", text=f"End of OT{s.qtr - 4}", score=list(s.score))
        s.phase = DONE
        return Event(kind="period", text="Final: tie", score=list(s.score))

    def _start_overtime(self, s: State) -> Event:
        ot = self.cfg["rules"]["overtime"]
        s.qtr = 5
        s.clock = _period_length(s, self.data, self.ctx)
        n_to = ot["playoff_timeouts"] if self.ctx.playoff else ot["regular_season_timeouts"]
        s.tos = [n_to, n_to]
        s.warned = False
        s.ot_done = [False, False]
        s.ot_first = -1
        s.phase = KICKOFF
        # coin toss is resolved by the caller (policy) through the kick_team it sets; default: team 1 kicks
        return Event(kind="period", text="Overtime", score=list(s.score))

    # ---- possession changes -------------------------------------------------
    def _change_possession(self, s: State, new_yl_for_new_team: int) -> None:
        """Ball goes to the other team at its yardline_100. Handles OT bookkeeping."""
        if s.ot:
            s.ot_done[s.poss] = True
        s.poss = 1 - s.poss
        s.yl = min(99, max(1, new_yl_for_new_team))
        s.down = 1
        s.togo = min(10, s.yl)
        s.running = False
        self._ot_check(s)

    def _ot_check(self, s: State) -> None:
        """Under the 2025 rule both teams possess once; after that it is sudden death."""
        if not s.ot or s.phase == DONE:
            return
        if s.ot_done[0] and s.ot_done[1] and s.score[0] != s.score[1]:
            s.phase = DONE

    def _score(self, s: State, team: int, points: int) -> None:
        s.score[team] += points
        s.running = False

    # ---- public step --------------------------------------------------------
    def step(self, s: State, action: dict, rng: Rng, look: dict | None = None) -> Event:
        """Mutates s. `look` = {"box": "light"|"heavy", "blitz": bool} chosen by the defense (or None)."""
        if s.phase == DONE:
            return Event(kind="done", text="Game over", score=list(s.score))
        self._last_ended = False
        action["type"]
        ev = self._dispatch(s, action, rng, look)
        if getattr(self, "_last_ended", False) and ev.kind not in ("period", "warning"):
            ev.ended = True
        return ev

    def _dispatch(self, s: State, action: dict, rng: Rng, look: dict | None) -> Event:
        t = action["type"]
        if s.phase == PAT:
            return self._pat(s, t, rng)
        if s.phase == KICKOFF:
            return self._kickoff(s, t == "onside", rng)
        if s.phase == FREE_KICK:
            return self._free_kick(s, rng)
        if t == "timeout":
            team = action.get("team", s.poss)
            if s.tos[team] <= 0:
                return Event(kind="noop", text="No timeouts left", score=list(s.score))
            s.tos[team] -= 1
            s.running = False
            return Event(kind="timeout", text=f"Timeout, team {team}", score=list(s.score))
        if t == "spike":
            return self._spike(s, rng)
        if t == "kneel":
            return self._kneel(s, rng)
        if t == "fg":
            return self._field_goal(s, rng)
        if t == "punt":
            return self._punt(s, rng)
        if t == "play":
            return self._play(s, action, rng, look)
        raise ValueError(f"unknown action {action}")

    # ---- scrimmage plays ----------------------------------------------------
    def sample_look(self, s: State, rng: Rng) -> dict:
        key = f"{s.down}|{dist_bucket(s.togo)}"
        cell = self.data.looks["by_down_dist"].get(key, self.data.looks["overall"])
        return {"box": "light" if rng.chance(cell["p_light"]) else "heavy", "blitz": rng.chance(cell["p_blitz"])}

    def _play(self, s: State, action: dict, rng: Rng, look: dict | None) -> Event:
        call = action["call"]
        fam = call_family(call)
        tempo = action.get("tempo", "normal")
        presnap, ev = self._presnap(s, tempo, rng)
        if ev is not None and (ev.kind == "period" or s.phase == DONE):
            ev.presnap = presnap
            return ev
        if look is None:
            look = self.sample_look(s, rng)
        look_key = f"{look['box']}_any" if fam in RUN_FAMILIES else f"{look['box']}_{'blitz' if look['blitz'] else 'base'}"
        start, n, level = self.data.playbook.cell(fam, call, look_key, zone_of(s.yl), self.min_n)
        i = start + rng.below(n)
        pb = self.data.playbook.cols
        yards = pb["yards"][i]
        to = pb["to"][i]
        nullified = pb["nullified"][i] == 1
        pen = pb["pen"][i]
        pen_yds = pb["pen_yds"][i]
        inc = pb["inc"][i] == 1
        sack = pb["sack"][i] == 1
        oob = pb["oob"][i] == 1
        row_td = pb["td"][i] == 1
        def_td = pb["def_td"][i] == 1
        air = pb["air"][i]
        ret = pb["ret"][i]

        ev = Event(kind="play", call=call, look=look_key, row=i, level=level, presnap=presnap, score=list(s.score))
        # play duration from the clock model
        if fam in RUN_FAMILIES or sack or (to == 1 and not inc):
            dkey = "run"
        elif inc or to == 2:
            dkey = "pass_incomplete"
        else:
            dkey = "pass_complete"
        duration = draw_hist(self.data.clock["duration"][dkey], rng)
        ev.duration = duration
        s.plays += 1
        off = s.poss

        # ---- penalties that wipe out the play
        if nullified:
            ev.penalty = pen
            if pen == 1:  # on the offense: lose yards, replay the down
                y = min(pen_yds, (100 - s.yl) // 2) if pen_yds > 0 else 5
                s.yl += y
                s.togo += y
                ev.text = f"Penalty on the offense, {y} yards"
                ev.yards = -y
            elif pen == 2:  # on the defense
                y = min(pen_yds, s.yl // 2) if pen_yds > 0 else 5
                s.yl -= y
                ev.yards = y
                if y >= 10 or y >= s.togo:
                    s.down, s.togo = 1, min(10, s.yl)
                    ev.first_down = True
                else:
                    s.togo -= y
                ev.text = f"Penalty on the defense, {y} yards"
                if s.yl <= 0:  # DPI in the end zone places the ball at the 1
                    s.yl = 1
                    s.togo = 1
            else:  # no_play with no penalty info (rare): replay the down
                ev.text = "No play"
            stop = self._after_play_clock(s, duration, stops=True)
            s.togo = min(s.togo, s.yl)
            return stop if (stop is not None and s.phase == DONE) else ev

        # ---- turnovers
        if to:
            if to == 2:
                spot = s.yl - (air if air > -99 else 0)
            else:
                spot = s.yl - yards
            spot = min(99, max(0, spot))
            new_yl = 100 - spot - ret
            ev.turnover = True
            ev.yards = yards
            ev.text = "Interception" if to == 2 else "Fumble"
            self._after_play_clock(s, duration, stops=True)
            if s.phase == DONE:
                return ev
            if def_td or new_yl <= 0:
                self._touchdown(s, 1 - off, ev)
                ev.text += ", returned for a touchdown"
                if s.ot:
                    s.ot_done[off] = True
                return ev
            self._change_possession(s, new_yl)
            return ev

        # ---- the gain
        new_yl = s.yl - yards
        ev.yards = yards
        if new_yl <= 0 or (row_td and yards >= s.yl):
            ev.text = f"{'Run' if fam in RUN_FAMILIES else 'Pass'} for {s.yl} yards, touchdown"
            ev.yards = s.yl
            self._after_play_clock(s, duration, stops=True)
            if s.phase != DONE:
                self._touchdown(s, off, ev)
            return ev
        if new_yl >= 100:
            ev.text = "Safety"
            self._after_play_clock(s, duration, stops=True)
            if s.phase == DONE:
                return ev
            self._score(s, 1 - off, 2)
            s.phase = FREE_KICK
            s.kick_team = off
            if s.ot:
                s.ot_done[off] = True
                self._ot_check(s)
            return ev
        # penalty tacked on after a play that stands
        if pen == 2 and pen_yds > 0:
            new_yl = max(1, new_yl - min(pen_yds, new_yl // 2))
            ev.penalty = 2
        elif pen == 1 and pen_yds > 0:
            new_yl = min(99, new_yl + min(pen_yds, (100 - new_yl) // 2))
            ev.penalty = 1
        gained = s.yl - new_yl
        s.yl = new_yl
        if sack:
            ev.text = "Sacked at the line" if yards == 0 else f"Sacked for {-yards} yards"
        elif inc:
            ev.text = "Incomplete"
        else:
            ev.text = f"{'Run' if fam in RUN_FAMILIES else 'Pass'} for {gained} yards" + (" (out of bounds)" if oob else "")
        if gained >= s.togo or (pen == 2 and pen_yds >= 10):
            s.down, s.togo = 1, min(10, s.yl)
            ev.first_down = True
        else:
            s.togo -= gained
            s.down += 1
        # clock
        warn = self.cfg["clock"]
        oob_stops = oob and s.half_seconds_left() <= (warn["ob_stops_clock_inside_q2_seconds"] if s.qtr <= 2 else warn["ob_stops_clock_inside_q4_seconds"])
        stops = inc or oob_stops or pen != 0
        self._after_play_clock(s, duration, stops)
        if s.phase == DONE:
            return ev
        if s.down > 4:
            ev.text += ", turnover on downs"
            ev.turnover = True
            self._change_possession(s, 100 - s.yl)
        return ev

    def _touchdown(self, s: State, team: int, ev: Event) -> None:
        ev.td = True
        self._score(s, team, 6)
        s.phase = PAT
        s.poss = team
        s.kick_team = team
        if s.ot:
            self._ot_check(s)
            if s.phase == DONE:
                return
            # In OT, a TD on the second possession (or after both have possessed) ends it; no PAT needed.
            if s.ot_done[1 - team] or (s.ot_first != -1 and s.ot_first != team):
                s.ot_done[team] = True
                s.phase = DONE

    def _spike(self, s: State, rng: Rng) -> Event:
        # A spike is snapped as soon as the line is set: ~3 s of runoff, not a full huddle.
        presnap = 0
        if s.running:
            presnap = min(s.clock, 3)
            s.clock -= presnap
            if s.clock == 0:
                return self._end_period(s)
        s.plays += 1
        s.down += 1
        ev = Event(kind="spike", text="Spike", presnap=presnap, duration=2, score=list(s.score))
        self._after_play_clock(s, 2, stops=True)
        if s.phase != DONE and s.down > 4:
            ev.turnover = True
            self._change_possession(s, 100 - s.yl)
        return ev

    def _kneel(self, s: State, rng: Rng) -> Event:
        # A kneel bleeds the full play clock if the clock was running.
        before = s.clock
        if s.running:
            s.clock = max(0, s.clock - self.cfg["clock"]["play_clock_seconds"])
            warn_at = self.cfg["clock"]["two_minute_warning_seconds"]
            if (not s.warned) and s.qtr in (2, 4) and before > warn_at and s.clock <= warn_at:
                s.clock, s.warned, s.running = warn_at, True, False
                return Event(kind="warning", text="Two-minute warning", presnap=before - warn_at, score=list(s.score))
            if s.clock == 0:
                return self._end_period(s)
        presnap = before - s.clock
        s.plays += 1
        s.yl = min(99, s.yl + 1)
        s.down += 1
        s.togo += 1
        ev = Event(kind="kneel", text="Kneel", yards=-1, presnap=presnap, duration=2, score=list(s.score))
        self._after_play_clock(s, 2, stops=False)
        if s.phase != DONE and s.down > 4:
            ev.turnover = True
            self._change_possession(s, 100 - s.yl)
        return ev

    def _field_goal(self, s: State, rng: Rng) -> Event:
        # A kicking team that trails or is tied late rushes the unit on; otherwise it huddles.
        late = (s.qtr == 4 and s.clock <= 300) or (s.qtr == 2 and s.clock <= 120) or s.ot
        presnap, ev = self._presnap(s, "hurry" if (late and s.diff <= 0) else "normal", rng)
        if ev is not None and (ev.kind == "period" or s.phase == DONE):
            return ev
        s.plays += 1
        dist = s.yl + 17
        p = fg_prob(self.data.fg, dist, self.ctx.indoor, self.ctx.wind, self.ctx.temp)
        made = rng.chance(p)
        off = s.poss
        ev = Event(kind="fg", text=f"{dist}-yard field goal {'is good' if made else 'is no good'}", presnap=presnap, duration=5, made=made, score=list(s.score))
        self._after_play_clock(s, 5, stops=True)
        if s.phase == DONE:
            return ev
        if made:
            self._score(s, off, 3)
            ev.score = list(s.score)
            s.phase = KICKOFF
            s.kick_team = off
            if s.ot:
                s.ot_done[off] = True
                self._ot_check(s)
        else:
            spot = s.yl + 7
            self._change_possession(s, 100 - spot if spot >= 20 else 80)
        return ev

    def _punt(self, s: State, rng: Rng) -> Event:
        presnap, ev = self._presnap(s, "normal", rng)
        if ev is not None and (ev.kind == "period" or s.phase == DONE):
            return ev
        s.plays += 1
        zone = next((z for z in self.data.punt["zones"] if z["from_min"] <= s.yl <= z["from_max"]), self.data.punt["zones"][-1])
        off = s.poss
        ev = Event(kind="punt", text="Punt", presnap=presnap, duration=8, score=list(s.score))
        self._after_play_clock(s, 8, stops=True)
        if s.phase == DONE:
            return ev
        if rng.chance(zone["blocked"]):
            ev.text = "Punt blocked"
            self._change_possession(s, 100 - s.yl)
            return ev
        if rng.chance(zone["return_td"]):
            ev.text = "Punt returned for a touchdown"
            if s.ot:
                s.ot_done[off] = True
            self._touchdown(s, 1 - off, ev)
            return ev
        self._change_possession(s, draw_hist(zone["next_yl"], rng))
        return ev

    # ---- special phases -----------------------------------------------------
    def _pat(self, s: State, kind: str, rng: Rng) -> Event:
        team = s.poss
        if kind == "two_pt":
            ok = rng.chance(self.data.pat["two_pt"])
            if ok:
                self._score(s, team, 2)
            ev = Event(kind="pat", text="Two-point try " + ("is good" if ok else "fails"), made=ok, score=list(s.score))
        else:
            ok = rng.chance(self.data.pat["xp"])
            if ok:
                self._score(s, team, 1)
            ev = Event(kind="pat", text="Extra point " + ("is good" if ok else "is no good"), made=ok, score=list(s.score))
        s.phase = KICKOFF
        s.kick_team = team
        if s.ot:
            s.ot_done[team] = True
            self._ot_check(s)
        if s.phase != DONE and s.qtr == 4 and s.clock == 0:
            self._end_period_after_score(s)
        return ev

    def _end_period_after_score(self, s: State) -> None:
        """A score as time expired: the game (or half) ends without the kickoff."""
        if s.qtr == 4:
            if s.score[0] != s.score[1]:
                s.phase = DONE
            else:
                self._start_overtime(s)
        elif s.qtr == 2:
            self._end_period(s)

    def _kickoff(self, s: State, onside: bool, rng: Rng) -> Event:
        kicker = s.kick_team
        receiver = 1 - kicker
        if s.ot and s.ot_first == -1:
            s.ot_first = receiver
        s.plays += 1
        ko = self.data.kickoff
        if onside:
            if rng.chance(ko["onside"]["recovery"]):
                s.poss = kicker
                s.yl = draw_hist(ko["onside"]["recover_yl"], rng)
                s.down, s.togo = 1, 10
                s.phase = SNAP
                s.running = False
                return Event(kind="kickoff", text="Onside kick recovered by the kicking team", score=list(s.score))
            s.poss = receiver
            s.yl = draw_hist(ko["onside"]["fail_yl"], rng)
            s.down, s.togo = 1, 10
            s.phase = SNAP
            s.running = False
            return Event(kind="kickoff", text="Onside kick fails", score=list(s.score))
        if rng.chance(ko["return_td"]):
            ev = Event(kind="kickoff", text="Kickoff returned for a touchdown", score=list(s.score))
            self._after_play_clock(s, 12, stops=True)
            if s.phase != DONE:
                s.poss = receiver
                self._touchdown(s, receiver, ev)
            return ev
        s.poss = receiver
        s.yl = draw_hist(ko["start_yl"], rng)
        s.down, s.togo = 1, 10
        s.phase = SNAP
        touchback = s.yl == 100 - self.cfg["rules"]["kickoff_touchback_yardline"]
        self._after_play_clock(s, 0 if touchback else 6, stops=touchback)
        return Event(kind="kickoff", text="Touchback" if touchback else f"Kickoff returned to the {100 - s.yl}", score=list(s.score))

    def _free_kick(self, s: State, rng: Rng) -> Event:
        receiver = 1 - s.kick_team
        s.plays += 1
        s.poss = receiver
        s.yl = draw_hist(self.data.kickoff["safety_kick_start_yl"], rng)
        s.down, s.togo = 1, 10
        s.phase = SNAP
        self._after_play_clock(s, 5, stops=True)
        return Event(kind="kickoff", text="Free kick after the safety", score=list(s.score))

    # ---- valuation ----------------------------------------------------------
    def value(self, s: State) -> float:
        """Win value for team 0: 1 / 0 / 0.5 when done, or the WP model at a halftime stop."""
        if s.phase == DONE and not (self.ctx.end_at_half and s.qtr == 2):
            if s.score[0] > s.score[1]:
                return 1.0
            if s.score[0] < s.score[1]:
                return 0.0
            return 0.5
        # halftime (or an unfinished state): WP model from team 0's view.
        recv = s.recv2h
        sd = s.score[recv] - s.score[1 - recv]
        spread = self.ctx.spread if recv == 0 else -self.ctx.spread
        t = 1800 if s.qtr == 2 and s.phase == DONE else s.seconds_left_regulation()
        yl = 100 - self.cfg["rules"]["kickoff_touchback_yardline"] if (s.qtr == 2 and s.phase == DONE) else s.yl
        wp = win_prob(self.data.wp, sd, t, yl, 1, 10, 3, 3, spread, 0, 0, 0, 1 if s.ot else 0)
        return wp if recv == 0 else 1.0 - wp

    def state_wp(self, s: State, team: int = 0) -> float:
        """Instant WP of `team` in any live state (used for penalty decisions and the UI)."""
        if s.phase == DONE:
            v = self.value(s)
            return v if team == 0 else 1.0 - v
        p = s.poss
        sd = s.score[p] - s.score[1 - p]
        spread = self.ctx.spread if p == 0 else -self.ctx.spread
        half1 = 1 if s.qtr <= 2 else 0
        t = s.seconds_left_regulation() if not s.ot else max(1, s.clock)
        wp = win_prob(self.data.wp, sd, t, s.yl, s.down, s.togo, s.tos[p], s.tos[1 - p], spread,
                      half1, 1 if s.recv2h == p else 0, 1 if s.togo >= s.yl else 0, 1 if s.ot else 0)
        return wp if p == team else 1.0 - wp
