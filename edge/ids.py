"""Edge IDS: whitelist, rate, plausibility, rolling-counter checks plus a small
PCA autoencoder (numpy) for novelty; alerts need two consecutive flagged windows."""
import numpy as np

SPEC = {0x100: 10, 0x200: 5, 0x300: 2}
DEC = {0x100: (lambda p: (p[0] << 8 | p[1]) / 100, 0, 250, 5.0),   # decode, lo, hi, max step
       0x200: (lambda p: (p[0] << 8 | p[1]) / 10, -400, 600, 120.0),
       0x300: (lambda p: p[0] - 40, -40, 100, 6.0)}


def feats(frames):
    v = []
    for i, hz in SPEC.items():
        fs = [f for f in frames if f[0] == i]
        vals = [DEC[i][0](f[1]) for f in fs]
        v += [len(fs) / hz, float(np.mean(np.abs(np.diff(vals)))) / DEC[i][3] if len(vals) > 1 else 0.0]
    v.append(sum(1 for f in frames if f[0] not in SPEC) / 10)
    return np.array(v)


class PcaAE:
    def __init__(self, k=3): self.k = k

    def fit(self, X):
        X = np.asarray(X); self.mu = X.mean(0)
        _, _, vt = np.linalg.svd(X - self.mu, full_matrices=False)
        self.W = vt[:self.k]
        self.thr = 3.0 * max(self.score_many(X).max(), 0.02)    # margin above worst clean window
        return self

    def score(self, x):
        d = x - self.mu
        return float(np.linalg.norm(d - self.W.T @ (self.W @ d)))

    def score_many(self, X): return np.array([self.score(x) for x in X])


class Ids:
    def __init__(self, model: PcaAE):
        self.m, self.last_ctr, self.last_val, self.prev_flags = model, {}, {}, set()
        self.novelty = 0.0

    def window(self, frames, own_speed=None):
        """-> (flags this window, confirmed attack types)"""
        flags = set()
        by = {}
        for f in sorted(frames, key=lambda f: f[2]):
            by.setdefault(f[0], []).append(f)
        for i, fs in by.items():
            if i not in SPEC:
                flags.add("fuzz"); continue
            if len(fs) > 1.5 * SPEC[i] + 1: flags.add("flood")
            dec, lo, hi, step = DEC[i]
            for _, p, _ in fs:
                c, v = p[7], dec(p)
                lc = self.last_ctr.get(i)
                if lc is not None and c != (lc + 1) % 256:
                    flags.add("replay")
                lv = self.last_val.get(i)
                if not lo <= v <= hi or (lv is not None and abs(v - lv) > step): flags.add("spoof")
                self.last_ctr[i], self.last_val[i] = c, v
        if own_speed is not None and 0x100 in by:
            if abs(DEC[0x100][0](by[0x100][-1][1]) - own_speed) > 25: flags.add("spoof")
        x = feats(frames)
        self.novelty = self.m.score(x) / self.m.thr
        if self.novelty > 1.0 and not flags: flags.add("novel")
        confirmed = flags & self.prev_flags if flags else set()
        if flags and not confirmed and ("novel" in flags and "novel" in self.prev_flags):
            confirmed = {"novel"}
        self.prev_flags = flags
        return flags, confirmed
