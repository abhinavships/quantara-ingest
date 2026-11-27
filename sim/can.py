"""Synthetic CAN bus: clean traffic plus flood/fuzz/spoof/replay attack injection.
Frame = (id, payload: 8 ints, ts). Byte 7 is a rolling counter."""
import random

SPEC = {0x100: 10, 0x200: 5, 0x300: 2}   # id -> frames per second (expected)


class CanBus:
    def __init__(self, seed=0):
        self.r = random.Random(seed)
        self.ctr = {i: 0 for i in SPEC}
        self.hist = []                    # recorded frames for replay
        self.speed, self.cur, self.temp = 60.0, 100.0, 30.0
        self.attack = None

    def frame(self, i, ts):
        self.ctr[i] = (self.ctr[i] + 1) % 256
        v = {0x100: int(self.speed * 100), 0x200: int(self.cur * 10), 0x300: int(self.temp + 40)}[i]
        return (i, [v >> 8 & 255, v & 255, 0, 0, 0, 0, 0, self.ctr[i]], ts)

    def window(self, t, speed=None, cur=None, temp=None):
        """One 1-second window of frames at time t."""
        r = self.r
        if speed is not None: self.speed, self.cur, self.temp = speed, cur, temp
        out = []
        for i, hz in SPEC.items():
            n = hz + (r.choice((-1, 0, 0, 1)) if hz >= 5 else 0)
            for k in range(n):
                self.speed += r.uniform(-0.05, 0.05) if speed is None else 0
                out.append(self.frame(i, t + (k + r.random() * 0.5) / max(n, 1)))
        out.sort(key=lambda f: f[2])
        self.hist = (self.hist + out)[-300:]
        a = self.attack
        if a == "flood":
            out += [(0x100, [r.randrange(256) for _ in range(7)] + [r.randrange(256)], t + r.random()) for _ in range(300)]
        elif a == "fuzz":
            out += [(r.randrange(0x400, 0x7FF), [r.randrange(256) for _ in range(8)], t + r.random()) for _ in range(30)]
        elif a == "spoof":    # forged speed frames with plausible counter but wrong value
            for _ in range(3):
                self.ctr[0x100] = (self.ctr[0x100] + 1) % 256
                out.append((0x100, [0x4E, 0x20, 0, 0, 0, 0, 0, self.ctr[0x100]], t + r.random()))
        elif a == "replay":   # re-send recorded old frames
            out += [h for h in r.sample(self.hist[:150], 5)]
        out.sort(key=lambda f: f[2])
        return out
