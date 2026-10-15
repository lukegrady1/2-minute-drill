from sim.engine import DONE, FREE_KICK, KICKOFF, PAT, SNAP, State
from sim.rng import Rng


def test_touchdown_then_pat_then_kickoff(engine):
    s = State(qtr=4, clock=60, running=False, warned=True, down=1, togo=1, yl=1, score=[0, 0])
    for seed in range(100):
        s = State(qtr=4, clock=60, running=False, warned=True, down=1, togo=1, yl=1)
        ev = engine.step(s, {"type": "play", "call": "qb_sneak"}, Rng(seed))
        if ev.td:
            break
    assert s.score == [6, 0] and s.phase == PAT
    ev = engine.step(s, {"type": "xp"}, Rng(1))
    assert s.score[0] in (6, 7) and s.phase == KICKOFF and s.kick_team == 0
    ev = engine.step(s, {"type": "kickoff"}, Rng(1))
    assert s.phase == SNAP and s.poss == 1 and 1 <= s.yl <= 99


def test_two_point_scores_two(engine):
    s = State(qtr=4, clock=60, phase=PAT, poss=0, score=[6, 7])
    hits = 0
    for seed in range(300):
        t = s.copy()
        engine.step(t, {"type": "two_pt"}, Rng(seed))
        assert t.score[0] in (6, 8)
        hits += t.score[0] == 8
    assert 0.35 < hits / 300 < 0.6


def test_field_goal_make_rate_by_distance(engine):
    def rate(yl):
        made = 0
        for seed in range(400):
            s = State(qtr=4, clock=60, running=False, warned=True, down=4, togo=5, yl=yl)
            ev = engine.step(s, {"type": "fg"}, Rng(seed))
            made += ev.made
        return made / 400
    assert rate(10) > 0.9        # 27-yard kick
    assert 0.55 < rate(33) < 0.85  # 50-yard kick
    assert rate(45) < 0.6        # 62-yard kick


def test_field_goal_make_scores_and_kicks_off(engine):
    for seed in range(50):
        s = State(qtr=4, clock=60, running=False, warned=True, down=4, togo=5, yl=10)
        ev = engine.step(s, {"type": "fg"}, Rng(seed))
        if ev.made:
            assert s.score == [3, 0] and s.phase == KICKOFF and s.kick_team == 0
            return
    raise AssertionError


def test_missed_field_goal_spots_ball_at_kick_spot_or_20(engine):
    for seed in range(400):
        s = State(qtr=4, clock=60, running=False, warned=True, down=4, togo=5, yl=40)
        ev = engine.step(s, {"type": "fg"}, Rng(seed))
        if not ev.made:
            assert s.poss == 1 and s.yl == 100 - 47 and s.down == 1
            break
    for seed in range(400):
        s = State(qtr=4, clock=60, running=False, warned=True, down=4, togo=5, yl=5)
        ev = engine.step(s, {"type": "fg"}, Rng(seed))
        if not ev.made:
            assert s.poss == 1 and s.yl == 80  # inside the 20: ball comes out to the 20
            return


def test_safety_scores_two_for_defense_and_free_kick(engine):
    s = State(qtr=4, clock=60, running=False, warned=True, down=1, togo=10, yl=99, score=[0, 0])
    found = False
    for seed in range(2000):
        s = State(qtr=4, clock=60, running=False, warned=True, down=1, togo=10, yl=99, score=[0, 0])
        ev = engine.step(s, {"type": "play", "call": "pass_deep_left"}, Rng(seed))
        if ev.text == "Safety":
            found = True
            break
    assert found
    assert s.score == [0, 2] and s.phase == FREE_KICK and s.kick_team == 0
    engine.step(s, {"type": "free_kick"}, Rng(1))
    assert s.poss == 1 and s.phase == SNAP


def test_interception_gives_ball_to_defense(engine):
    for seed in range(2000):
        s = State(qtr=4, clock=60, running=False, warned=True, down=1, togo=10, yl=50)
        ev = engine.step(s, {"type": "play", "call": "pass_deep_middle"}, Rng(seed))
        if ev.turnover and ev.text.startswith("Interception"):
            assert s.poss == 1 or s.phase == PAT  # pick-six goes to PAT for team 1
            if s.phase == SNAP:
                assert s.down == 1 and 1 <= s.yl <= 99
            return
    raise AssertionError


def test_kickoff_touchback_lands_at_35(engine):
    tb = 0
    for seed in range(300):
        s = State(qtr=4, clock=60, phase=KICKOFF, kick_team=0, warned=True)
        ev = engine.step(s, {"type": "kickoff"}, Rng(seed))
        assert s.poss == 1 and s.phase in (SNAP, PAT)
        if ev.text == "Touchback":
            assert s.yl == 65 and not s.running
            tb += 1
    assert tb > 30


def test_onside_kick_recovery_rate(engine):
    rec = 0
    for seed in range(600):
        s = State(qtr=4, clock=60, phase=KICKOFF, kick_team=0, warned=True)
        engine.step(s, {"type": "onside"}, Rng(seed))
        rec += s.poss == 0
        assert s.phase == SNAP
    assert 0.02 < rec / 600 < 0.2


def test_score_as_time_expires_ends_game_without_kickoff(engine):
    s = State(qtr=4, clock=0, phase=PAT, poss=0, score=[6, 3], warned=True)
    engine.step(s, {"type": "xp"}, Rng(1))
    assert s.phase == DONE
    s = State(qtr=4, clock=0, phase=PAT, poss=0, score=[6, 6], warned=True)
    for seed in range(50):
        t = s.copy()
        engine.step(t, {"type": "xp"}, Rng(seed))
        if t.score == [6, 6]:   # missed XP, still tied -> overtime
            assert t.qtr == 5 and t.phase == KICKOFF
            return
