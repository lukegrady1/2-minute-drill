from sim.engine import DONE, KICKOFF, PAT, SNAP, State
from sim.rng import Rng


def test_regulation_tie_starts_overtime_with_rules(engine):
    s = State(qtr=4, clock=3, running=True, warned=True, score=[20, 20], tos=[0, 1])
    engine.step(s, {"type": "kneel"}, Rng(1))
    assert s.qtr == 5 and s.phase == KICKOFF
    assert s.clock == 600 and s.tos == [2, 2]


def test_playoff_overtime_length_and_timeouts(playoff_engine):
    s = State(qtr=4, clock=3, running=True, warned=True, score=[20, 20])
    playoff_engine.step(s, {"type": "kneel"}, Rng(1))
    assert s.clock == 900 and s.tos == [3, 3]


def test_both_teams_possess_even_after_opening_touchdown(engine):
    s = State(qtr=5, clock=600, phase=KICKOFF, kick_team=1, score=[20, 20], tos=[2, 2])
    engine.step(s, {"type": "kickoff"}, Rng(1))
    assert s.poss == 0 and s.ot_first == 0
    # team 0 scores a TD on its first possession
    s.yl, s.down, s.togo = 1, 1, 1
    for seed in range(100):
        t = s.copy()
        ev = engine.step(t, {"type": "play", "call": "qb_sneak"}, Rng(seed))
        if ev.td:
            s = t
            break
    assert s.score == [26, 20] and s.phase == PAT and s.phase != DONE
    engine.step(s, {"type": "xp"}, Rng(1))
    assert s.phase == KICKOFF and s.ot_done == [True, False]   # team 1 still gets its possession


def test_second_possession_touchdown_ends_game(engine):
    s = State(qtr=5, clock=400, phase=SNAP, poss=1, score=[23, 20], tos=[2, 2], ot_first=0, ot_done=[True, False],
              yl=1, down=1, togo=1)
    for seed in range(100):
        t = s.copy()
        ev = engine.step(t, {"type": "play", "call": "qb_sneak"}, Rng(seed))
        if ev.td:
            assert t.phase == DONE and t.score == [23, 26]
            assert engine.value(t) == 0.0
            return
    raise AssertionError


def test_second_possession_field_goal_ties_and_goes_sudden_death(engine):
    s = State(qtr=5, clock=400, phase=SNAP, poss=1, score=[23, 20], tos=[2, 2], ot_first=0, ot_done=[True, False],
              yl=10, down=4, togo=5)
    for seed in range(100):
        t = s.copy()
        ev = engine.step(t, {"type": "fg"}, Rng(seed))
        if ev.made:
            assert t.score == [23, 23] and t.phase == KICKOFF and t.ot_done == [True, True]
            # next score wins: team 0 kicks a FG
            engine.step(t, {"type": "kickoff"}, Rng(seed))
            t.yl, t.down, t.togo = 10, 4, 5
            for s2 in range(100):
                u = t.copy()
                ev2 = engine.step(u, {"type": "fg"}, Rng(s2))
                if ev2.made:
                    assert u.phase == DONE and engine.value(u) == 1.0
                    return
    raise AssertionError


def test_second_possession_turnover_ends_game_if_trailing(engine):
    s = State(qtr=5, clock=400, phase=SNAP, poss=1, score=[23, 20], tos=[2, 2], ot_first=0, ot_done=[True, False],
              yl=60, down=4, togo=12)
    for seed in range(400):
        t = s.copy()
        ev = engine.step(t, {"type": "play", "call": "pass_short_middle"}, Rng(seed))
        if ev.turnover:
            assert t.phase == DONE and engine.value(t) == 1.0
            return
    raise AssertionError


def test_regular_season_overtime_expires_as_tie(engine):
    s = State(qtr=5, clock=3, running=True, warned=True, score=[23, 23], ot_first=0, ot_done=[True, True])
    engine.step(s, {"type": "kneel"}, Rng(1))
    assert s.phase == DONE and engine.value(s) == 0.5


def test_playoff_overtime_continues_when_tied(playoff_engine):
    s = State(qtr=5, clock=3, running=True, warned=True, score=[23, 23], ot_first=0, ot_done=[True, True])
    playoff_engine.step(s, {"type": "kneel"}, Rng(1))
    assert s.phase != DONE and s.qtr == 6 and s.clock == 900
