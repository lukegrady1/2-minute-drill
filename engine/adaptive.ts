/** Adaptive defense: tilt the look toward what beats the player's recent calls (PLAN: exp(k * confidence * edge)). */
import type { EngineData } from "./data";
import { callFamily, distBucket, zoneOf, type Look, type State } from "./engine";
import type { Rng } from "./rng";

const LOOKS: Look[] = [{ box: "light", blitz: false }, { box: "light", blitz: true }, { box: "heavy", blitz: false }, { box: "heavy", blitz: true }];
const lookKey = (fam: string, l: Look) => (fam === "run_inside" || fam === "run_outside" || fam === "qb_sneak" ? `${l.box}_any` : `${l.box}_${l.blitz ? "blitz" : "base"}`);

/** Mean yards a call gains against a look, from the library cell (zone-specific when big enough). */
function meanYards(data: EngineData, call: string, look: Look, zone: string): number | null {
  const fam = callFamily(call);
  const pb = data.playbook;
  const [start, n, level] = pb.cell(fam, call, lookKey(fam, look), zone, data.cfg.playbook.min_bucket_size);
  if (level === "L1" || level === "L0") return null;   // look is not in the key: no information
  let s = 0;
  for (let i = start; i < start + n; i++) s += pb.cols.yards[i] - (pb.cols.to[i] ? 45 : 0);   // a turnover costs ~45 yards of value
  return s / n;
}

export interface Adaptive { recent: string[]; announce: string | null; weights: number[] }

export function adaptiveLook(data: EngineData, s: State, recentCalls: string[], rng: Rng): { look: Look; info: Adaptive } {
  const cfg = data.cfg as unknown as { adaptive_defense: { k: number; recent_calls_window: number; recency_decay: number; announce_min_streak: number } };
  const ad = cfg.adaptive_defense;
  const recent = recentCalls.slice(-ad.recent_calls_window);
  const cell = data.looks.by_down_dist[`${s.down}|${distBucket(s.togo)}`] ?? data.looks.overall;
  const base = LOOKS.map((l) => (l.box === "light" ? cell.p_light : 1 - cell.p_light) * (l.blitz ? cell.p_blitz : 1 - cell.p_blitz));
  const zone = zoneOf(s.yl);
  // edge per look: how much worse (for the offense) the recent calls do against it, in [-1, 1]
  const edges = LOOKS.map((l) => {
    let num = 0, den = 0;
    recent.forEach((call, i) => {
      const w = Math.pow(ad.recency_decay, recent.length - 1 - i);
      const vs = meanYards(data, call, l, zone);
      const avg = LOOKS.map((m) => meanYards(data, call, m, zone)).filter((x): x is number => x !== null);
      if (vs === null || !avg.length) return;
      const mean = avg.reduce((a, b) => a + b, 0) / avg.length;
      num += w * (mean - vs); den += w;
    });
    return den ? Math.max(-1, Math.min(1, (num / den) / 3)) : 0;   // 3 yards of edge = fully confident tilt
  });
  const conf = Math.min(1, recent.length / ad.recent_calls_window);
  const weights = base.map((b, i) => b * Math.exp(ad.k * conf * edges[i]));
  const look = LOOKS[rng.pickWeighted(weights)];
  // announce when the player has leaned one way for a while
  let announce: string | null = null;
  const fams = recent.map((c) => (c.startsWith("run") || c === "qb_sneak" ? "run" : "pass"));
  const streak = fams.length >= ad.announce_min_streak && fams.slice(-ad.announce_min_streak).every((f) => f === fams[fams.length - 1]);
  if (streak && conf >= 0.5) {
    const top = weights.indexOf(Math.max(...weights));
    const l = LOOKS[top];
    if (fams[fams.length - 1] === "run" && l.box === "heavy") announce = `They're loading the box: you've run ${ad.announce_min_streak} straight`;
    if (fams[fams.length - 1] === "pass" && l.blitz) announce = `They're bringing the blitz: you've thrown ${ad.announce_min_streak} straight`;
  }
  return { look, info: { recent, announce, weights } };
}
