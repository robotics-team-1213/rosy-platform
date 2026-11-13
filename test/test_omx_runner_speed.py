"""runner_speed: the chunk runner's slow-only adaptive frame reader."""
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import runner_speed  # noqa: E402

FRAMES = [[float(k), -20.0, 30.0, 40.0, 0.0, 50.0] for k in range(1, 11)]  # pan 1 -> 10, one unit a frame


def runner(lag, adapt=1, recording=False):
    return SimpleNamespace(
        queue=[list(f) for f in FRAMES], target=[0.0, -20.0, 30.0, 40.0, 0.0, 50.0], lag=lag, chunk="goto x",
        params={"runner.speed_adapt": adapt, "runner.speed_min": 0.4, "runner.pace_lag": 1.6},
        recorder=SimpleNamespace(active=lambda: recording),
        speed=1.0, speed_low=1.0, speed_out=None, speed_base=None, speed_phase=0.0)


def play(r):
    out = []
    while r.queue:
        r.target = runner_speed.take(r)
        out.append(r.target)
    return out


def test_speed_is_full_under_half_the_pace_lag_and_floors_at_it():
    assert runner_speed.target_speed(0.0) == 1.0 and runner_speed.target_speed(0.8) == 1.0
    assert abs(runner_speed.target_speed(1.2) - 0.7) < 1e-9 and runner_speed.target_speed(5.0) == 0.4


def test_shadow_mode_reads_one_frame_a_tick_but_reports_the_speed_it_would_use():
    r = runner(lag=1.6, adapt=0)
    assert play(r) == FRAMES
    assert r.speed_low < 1.0


def test_a_lagging_arm_is_read_slower_never_faster_and_ends_exactly_on_the_last_frame():
    r = runner(lag=1.6)
    out = play(r)
    assert len(out) > len(FRAMES) and out[-1] == FRAMES[-1]
    steps = [b[0] - a[0] for a, b in zip([[0.0]] + out, out)]
    assert all(-1e-9 <= s <= 1.0 + 1e-9 for s in steps)  # slow-only: never a bigger step than the plan's
    assert all(abs(b - a) <= runner_speed.SLEW + 1e-9 for a, b in zip(steps, steps[1:-1]))  # last: lands on the end


def test_a_recording_episode_and_a_clean_arm_keep_nominal_timing():
    assert play(runner(lag=1.6, recording=True)) == FRAMES
    assert play(runner(lag=0.2)) == FRAMES


def test_a_target_changed_elsewhere_restarts_the_blend_from_there():
    r = runner(lag=1.6)
    r.speed = 0.5
    first = runner_speed.take(r)
    r.target = [99.0, -20.0, 30.0, 40.0, 0.0, 50.0]  # a hold or damping moved the target
    nxt = runner_speed.take(r)
    assert first[0] < 1.0 and nxt[0] < 99.0 and nxt[0] > first[0]
