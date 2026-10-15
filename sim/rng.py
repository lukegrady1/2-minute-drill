"""mulberry32: a tiny seeded PRNG with identical output in Python and JavaScript.

JS reference (engine/rng.ts):
    t = (t + 0x6D2B79F5) | 0
    r = Math.imul(t ^ (t >>> 15), 1 | t)
    r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296
"""

from __future__ import annotations

M32 = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return ((a & M32) * (b & M32)) & M32


class Rng:
    __slots__ = ("state",)

    def __init__(self, seed: int):
        self.state = seed & M32

    def next(self) -> float:
        """Uniform float in [0, 1) with 32 bits of entropy, identical to the JS version."""
        self.state = (self.state + 0x6D2B79F5) & M32
        t = self.state
        r = _imul(t ^ (t >> 15), 1 | t)
        r = ((r + _imul(r ^ (r >> 7), 61 | r)) ^ r) & M32
        return ((r ^ (r >> 14)) & M32) / 4294967296.0

    def below(self, n: int) -> int:
        """Integer in [0, n)."""
        return int(self.next() * n)

    def chance(self, p: float) -> bool:
        return self.next() < p

    def pick_weighted(self, probs: list[float]) -> int:
        """Index drawn from a probability vector (need not sum to exactly 1)."""
        tot = 0.0
        for p in probs:          # plain left-to-right sum: Python's sum() is compensated since 3.12
            tot += p
        u = self.next() * tot
        acc = 0.0
        for i, p in enumerate(probs):
            acc += p
            if u < acc:
                return i
        return len(probs) - 1

    def fork(self) -> Rng:
        """A child generator seeded from this one, for independent sub-streams."""
        return Rng(int(self.next() * 4294967296))
