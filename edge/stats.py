"""Statistics layer: rolling window mean/std/slope/EWMA, z-score, rate of change."""
import math
from collections import deque


class Roll:
    def __init__(self, n=60, alpha=0.2):
        self.w, self.alpha, self.ewma, self.last = deque(maxlen=n), alpha, None, None

    def push(self, x, dt=1.0):
        self.rate = 0.0 if self.last is None else (x - self.last) / dt
        self.last = x
        self.w.append(x)
        self.ewma = x if self.ewma is None else self.alpha * x + (1 - self.alpha) * self.ewma

    @property
    def mean(self): return sum(self.w) / len(self.w) if self.w else 0.0

    @property
    def std(self):
        n = len(self.w)
        if n < 2: return 0.0
        m = self.mean
        return math.sqrt(sum((v - m) ** 2 for v in self.w) / (n - 1))

    @property
    def slope(self):
        """least-squares slope per sample"""
        n = len(self.w)
        if n < 3: return 0.0
        xm, ym = (n - 1) / 2, self.mean
        num = sum((i - xm) * (v - ym) for i, v in enumerate(self.w))
        den = sum((i - xm) ** 2 for i in range(n))
        return num / den

    def z(self, x):
        s = max(self.std, 1e-6)
        return (x - self.mean) / s
