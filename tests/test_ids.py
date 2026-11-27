import pytest
from sim.can import CanBus
from edge.ids import Ids, PcaAE, feats


def train(seed=1, n=300):
    b = CanBus(seed)
    return PcaAE().fit([feats(b.window(t)) for t in range(n)])


M = train()


def run(attack, seed, n=40, start=10):
    b, ids, conf, flags = CanBus(seed), Ids(M), set(), 0
    for t in range(n):
        b.attack = attack if t >= start else None
        f, c = ids.window(b.window(t), own_speed=b.speed)
        if t < start: assert not f and not c, f"false positive at {t}: {f}"
        conf |= c; flags += bool(f)
    return conf


def test_zero_false_positives_on_clean():
    for seed in range(20):            # 20 x 400 windows of clean traffic
        b, ids = CanBus(100 + seed), Ids(M)
        for t in range(400):
            f, c = ids.window(b.window(t), own_speed=b.speed)
            assert not f and not c, (seed, t, f)


@pytest.mark.parametrize("attack", ["flood", "fuzz", "spoof", "replay"])
def test_detects_attack(attack):
    for seed in (3, 4, 5):
        got = run(attack, seed)
        assert attack in got, f"{attack} undetected seed {seed}: {got}"


def test_two_window_confirmation():
    b, ids = CanBus(9), Ids(M)
    for t in range(5): ids.window(b.window(t))
    b.attack = "fuzz"; f, c = ids.window(b.window(5))
    assert f and not c                  # first flagged window is not enough
    f, c = ids.window(b.window(6))
    assert "fuzz" in c
