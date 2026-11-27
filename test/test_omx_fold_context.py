"""The automatic fold orders its candidates by the record of its own situation once it has a few tries there."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts" / "foundation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_auto_fold as af  # noqa: E402
from cell_choices import Choices  # noqa: E402

HOME = [0.8, -62.2, 53.0, 51.9, 44.6, 48.8]
NAMES = ["park", "lift_then_park", "lift_pan+10", "lift_pan-10", "elbow_in_then_park"]


def test_fold_context_is_a_few_coarse_buckets():
    assert af.fold_context([0, 10.0, 0, 0, 0], HOME, True) == "low/far"
    assert af.fold_context([0, -40.0, 0, 0, 0], HOME, False) == "high/near"
    assert len({af.fold_context([0, lift, 0, 0, 0], HOME, low) for lift in range(-90, 60, 5) for low in (0, 1)}) == 4


def test_two_contexts_learn_different_orders_and_an_unseen_one_keeps_the_global_order(tmp_path):
    path = tmp_path / "choices.json"
    seed = Choices(path)
    for name in NAMES:
        seed.offer(af.CHOICE, name, "D-1048")
    seed.save()

    def learn(context, name, ok):
        af._learn({"choices_path": str(path), "candidate": name, "result": "folded" if ok else "held", "context": context}, ok)

    for _ in range(3):  # resting low far out: lift overloads, the forearm-in fold works
        learn("low/far", "lift_then_park", False)
        learn("low/far", "elbow_in_then_park", True)
    for _ in range(4):  # high and near: lift_pan-10 works
        learn("high/near", "lift_pan-10", True)
    ch = Choices(path)
    global_order = ch.ranked(af.CHOICE, NAMES)
    low_far = ch.ranked_in_context(af.CHOICE, NAMES, "low/far")
    high_near = ch.ranked_in_context(af.CHOICE, NAMES, "high/near")
    assert low_far[0] == "elbow_in_then_park" and low_far[-1] == "lift_then_park"
    assert high_near[0] == "lift_pan-10" and low_far != high_near
    assert ch.ranked_in_context(af.CHOICE, NAMES, "high/far") == global_order  # never seen: the global record
    assert ch.ranked_in_context(af.CHOICE, NAMES, None) == global_order
    assert sorted(low_far) == sorted(high_near) == sorted(NAMES)  # only the order changes, never the set


def test_a_context_with_too_few_tries_falls_back_to_the_global_order(tmp_path):
    ch = Choices(tmp_path / "choices.json")
    for name in NAMES:
        ch.offer(af.CHOICE, name, "D-1048")
    for _ in range(3):
        ch.outcome(af.CHOICE, "lift_pan+10", True)
    ch.offer(f"{af.CHOICE}@low/near", "park", "D-1048")
    ch.outcome(f"{af.CHOICE}@low/near", "park", True)  # one try is not enough to override the global record
    assert ch.ranked_in_context(af.CHOICE, NAMES, "low/near") == ch.ranked(af.CHOICE, NAMES)
    assert ch.ranked_in_context(af.CHOICE, NAMES, "low/near")[0] == "lift_pan+10"
