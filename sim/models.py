"""Model evaluation shared by the engine: WP, FG, histogram draws. Mirrors engine/models.ts."""

from __future__ import annotations

import math

from sim.rng import Rng


def wp_features(sd, t, yl, down, togo, to_off, to_def, spread, half1, recv2h, gtg, ot) -> list[float]:
    """Scalar twin of pipeline.wp_model.wp_features. Keep the order identical."""
    isqrt = 1.0 / math.sqrt(t + 1.0)
    sqrt_t = math.sqrt(min(max(t, 0.0), 3600.0) / 3600.0)
    ylf = yl / 100.0
    to_diff = float(to_off - to_def)
    lead = (sd > 0) - (sd < 0)
    return [
        sd, sd * isqrt, isqrt, sd * t / 3600.0, ylf, ylf * isqrt,
        1.0 if down == 2 else 0.0, 1.0 if down == 3 else 0.0, 1.0 if down == 4 else 0.0,
        math.log1p(togo), (1.0 if down == 4 else 0.0) * math.log1p(togo),
        to_diff, to_diff * isqrt, spread, spread * sqrt_t,
        half1, recv2h * half1, sd * half1, gtg, lead * isqrt, ot,
    ]


def logistic(coef: list[float], intercept: float, x: list[float]) -> float:
    z = intercept
    for c, v in zip(coef, x, strict=True):
        z += c * v
    if z > 30:
        return 1.0
    if z < -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def win_prob(wp_model: dict, sd: float, t: float, yl: float, down: int, togo: int, to_off: int,
             to_def: int, spread: float, half1: int, recv2h: int, gtg: int, ot: int) -> float:
    x = wp_features(sd, t, yl, down, togo, to_off, to_def, spread, half1, recv2h, gtg, ot)
    return logistic(wp_model["coef"], wp_model["intercept"], x)


def fg_prob(fg_model: dict, distance: float, indoor: bool, wind: float, temp: float) -> float:
    if distance > fg_model.get("max_attempt_distance", 68):
        return 0.0
    w = 0.0 if indoor else wind
    tp = 65.0 if indoor else temp
    x = [distance, distance * distance / 100.0, 1.0 if indoor else 0.0, w, (tp - 60.0) / 10.0,
         distance * w / 10.0, max(distance - 52.0, 0.0)]
    return logistic(fg_model["coef"], fg_model["intercept"], x)


def draw_hist(h: dict, rng: Rng) -> int:
    """Sample a value from a {"values": [...], "probs": [...]} histogram."""
    return int(h["values"][rng.pick_weighted(h["probs"])])
