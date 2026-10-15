from sim.engine import DONE, SNAP, State
from sim.rng import Rng


def run_play(engine, s, call="pass_short_middle", tempo="normal", seed=1, look=None):
    return engine.step(s, {"type": "play", "call": call, "tempo": tempo}, Rng(seed), look)


def test_presnap_runoff_only_when_clock_running(engine):
    s = State(qtr=4, clock=100, running=False)
    ev = run_play(engine, s)
    assert ev.presnap == 0
    s2 = State(qtr=4, clock=100, running=True, warned=True)
    ev2 = run_play(engine, s2)
    assert ev2.presnap > 0
    assert ev2.presnap <= engine.cfg["clock"]["play_clock_seconds"]


def test_two_minute_warning_stops_clock_at_120(engine):
    s = State(qtr=4, clock=125, running=True, warned=False)
    ev = engine.step(s, {"type": "kneel"}, Rng(3))   # a kneel bleeds the play clock across 2:00
    assert ev.kind == "warning"
    assert s.clock == 120 and s.warned and not s.running
    # warning is taken once per half
    s.running = True
    s.clock = 119
    ev2 = run_play(engine, s)
    assert ev2.kind != "warning"


def test_two_minute_warning_after_a_play_that_crosses(engine):
    s = State(qtr=4, clock=123, running=False, warned=False)
    # a completed pass in bounds keeps the clock running, but the warning stops it
    for seed in range(50):
        s = State(qtr=4, clock=123, running=False, warned=False)
        ev = run_play(engine, s, seed=seed)
        if ev.kind == "play" and "yards" in ev.text and "Incomplete" not in ev.text and s.clock < 123 and s.clock <= 120:
            assert s.warned and not s.running
            return
    raise AssertionError("no crossing play found")


def test_incomplete_pass_stops_clock_and_advances_down(engine):
    s = State(qtr=4, clock=60, running=True, warned=True, down=1, togo=10, yl=50)
    found = False
    for seed in range(200):
        s = State(qtr=4, clock=60, running=False, warned=True, down=1, togo=10, yl=50)
        ev = run_play(engine, s, seed=seed)
        if ev.text == "Incomplete":
            assert not s.running and s.down == 2 and s.togo == 10 and s.yl == 50
            found = True
            break
    assert found


def test_out_of_bounds_stops_clock_inside_five_minutes_only(engine):
    def find_oob(clock):
        for seed in range(400):
            s = State(qtr=4, clock=clock, running=False, warned=clock <= 120, down=1, togo=10, yl=50)
            ev = run_play(engine, s, call="pass_short_right", seed=seed)
            if ev.kind == "play" and "out of bounds" in ev.text and not ev.turnover and not ev.td:
                return s
        raise AssertionError("no OOB play found")
    assert not find_oob(200).running       # inside 5:00, the clock stays stopped
    assert find_oob(600).running           # outside 5:00, it restarts on the ready signal


def test_timeout_decrements_and_stops_clock(engine):
    s = State(qtr=4, clock=90, running=True, warned=True, tos=[2, 3])
    ev = engine.step(s, {"type": "timeout", "team": 0}, Rng(1))
    assert ev.kind == "timeout" and s.tos == [1, 3] and not s.running
    s.tos = [0, 3]
    s.running = True
    ev = engine.step(s, {"type": "timeout", "team": 0}, Rng(1))
    assert ev.kind == "noop" and s.running


def test_spike_costs_a_down_and_stops_clock(engine):
    s = State(qtr=4, clock=30, running=True, warned=True, down=2, togo=5, yl=30)
    ev = engine.step(s, {"type": "spike"}, Rng(1))
    assert ev.kind == "spike" and s.down == 3 and s.togo == 5 and s.yl == 30 and not s.running
    assert s.clock < 30


def test_kneel_bleeds_play_clock_when_running(engine):
    s = State(qtr=4, clock=100, running=True, warned=True, down=1, togo=10, yl=50, score=[21, 17])
    ev = engine.step(s, {"type": "kneel"}, Rng(1))
    assert ev.kind == "kneel"
    assert s.clock == 100 - engine.cfg["clock"]["play_clock_seconds"] - 2
    assert s.down == 2 and s.yl == 51 and s.running


def test_period_rolls_over_q3_to_q4_and_ends_game_in_q4(engine):
    s = State(qtr=3, clock=5, running=True, warned=False)
    engine.step(s, {"type": "kneel"}, Rng(1))
    assert s.qtr == 4 and s.clock == 900 and s.phase == SNAP
    s = State(qtr=4, clock=5, running=True, warned=True, score=[10, 7])
    engine.step(s, {"type": "kneel"}, Rng(1))
    assert s.phase == DONE and engine.value(s) == 1.0


def test_halftime_stop_for_q2_spot(data):
    from sim.engine import Ctx, Engine
    eng = Engine(data, Ctx(end_at_half=True))
    s = State(qtr=2, clock=3, running=True, warned=True, score=[14, 14], recv2h=0)
    eng.step(s, {"type": "kneel"}, Rng(1))
    assert s.phase == DONE and s.qtr == 2
    v = eng.value(s)
    assert 0.45 < v < 0.65   # tied at the half and receiving: a slight edge


def test_turnover_on_downs_flips_field(engine):
    s = State(qtr=4, clock=60, running=False, warned=True, down=4, togo=15, yl=40)
    for seed in range(300):
        s = State(qtr=4, clock=60, running=False, warned=True, down=4, togo=15, yl=40)
        ev = run_play(engine, s, call="run_inside_middle", seed=seed)
        if ev.turnover and "downs" in ev.text:
            assert s.poss == 1 and s.down == 1 and s.togo == 10 and 50 <= s.yl <= 75
            return
    raise AssertionError("no turnover on downs found")


def test_backoff_levels_available(data):
    pb = data.playbook
    min_n = data.cfg["playbook"]["min_bucket_size"]
    _start, n, level = pb.cell("pass", "pass_short_left", "light_base", "mid", min_n)
    assert level == "L3" and n >= min_n
    _start, n, level = pb.cell("hail_mary", "hail_mary", "heavy_blitz", "deep", min_n)
    assert level in ("L1", "L0") and n >= min_n
