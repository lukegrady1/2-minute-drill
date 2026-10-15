/** WP / FG / histogram evaluation, identical to sim/models.py. */
import type { Hist, LogisticModel } from "./data";
import type { Rng } from "./rng";

export function wpFeatures(sd: number, t: number, yl: number, down: number, togo: number, toOff: number, toDef: number,
  spread: number, half1: number, recv2h: number, gtg: number, ot: number): number[] {
  const isqrt = 1 / Math.sqrt(t + 1);
  const sqrtT = Math.sqrt(Math.min(Math.max(t, 0), 3600) / 3600);
  const ylf = yl / 100;
  const toDiff = toOff - toDef;
  const lead = sd > 0 ? 1 : sd < 0 ? -1 : 0;
  const d2 = down === 2 ? 1 : 0, d3 = down === 3 ? 1 : 0, d4 = down === 4 ? 1 : 0;
  return [
    sd, sd * isqrt, isqrt, (sd * t) / 3600, ylf, ylf * isqrt,
    d2, d3, d4,
    Math.log1p(togo), d4 * Math.log1p(togo),
    toDiff, toDiff * isqrt, spread, spread * sqrtT,
    half1, recv2h * half1, sd * half1, gtg, lead * isqrt, ot,
  ];
}

export function logistic(coef: number[], intercept: number, x: number[]): number {
  let z = intercept;
  for (let i = 0; i < coef.length; i++) z += coef[i] * x[i];
  if (z > 30) return 1;
  if (z < -30) return 0;
  return 1 / (1 + Math.exp(-z));
}

export function winProb(m: LogisticModel, sd: number, t: number, yl: number, down: number, togo: number, toOff: number,
  toDef: number, spread: number, half1: number, recv2h: number, gtg: number, ot: number): number {
  return logistic(m.coef, m.intercept, wpFeatures(sd, t, yl, down, togo, toOff, toDef, spread, half1, recv2h, gtg, ot));
}

export function fgProb(m: LogisticModel & { max_attempt_distance?: number }, distance: number, indoor: boolean, wind: number, temp: number): number {
  if (distance > (m.max_attempt_distance ?? 68)) return 0;
  const w = indoor ? 0 : wind;
  const tp = indoor ? 65 : temp;
  const x = [distance, (distance * distance) / 100, indoor ? 1 : 0, w, (tp - 60) / 10, (distance * w) / 10, Math.max(distance - 52, 0)];
  return logistic(m.coef, m.intercept, x);
}

export function drawHist(h: Hist, rng: Rng): number {
  return h.values[rng.pickWeighted(h.probs)];
}
