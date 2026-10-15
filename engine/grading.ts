/** Grading, percentile, coach matching. Twin of sim/grading.py. */
import type { EngineData } from "./data";
import { Engine, KICKOFF, PAT, SNAP, copyState, diff, distBucket, type Action, type State } from "./engine";
import { Policy, tempoFor } from "./policy";
import { Rng } from "./rng";
import { playOut } from "./simulate";

const GADGET = new Set(["gadget", "hail_mary"]);

export interface Option { action: Action; label: string; q: number; wp1: number; n1: number; wp2: number | null; n2: number; gadget: boolean }
export const optWp = (o: Option) => (o.wp2 !== null ? o.wp2 : o.wp1);

export interface Grade {
  options: Option[]; chosen: number; best: number; gap: number; color: "green" | "yellow" | "red"; seed: number;
  better: string | null; gaps: number[];
}

export const optionSeed = (seed: number, round: number, i: number) => (seed + 1000003 * round + 7919 * i) >>> 0;

export function actionLabel(a: Action): string {
  if (a.type === "play") return a.call;
  if (a.type === "look") return `${a.box}_${a.blitz ? "blitz" : "base"}`;
  return a.type;
}
const opt = (action: Action, extra: Partial<Option> = {}): Option =>
  ({ action, label: actionLabel(action), q: 0, wp1: 0, n1: 0, wp2: null, n2: 0, gadget: action.type === "play" && GADGET.has(action.call), ...extra });

export function offenseOptions(engine: Engine, s: State, tempo: string): Option[] {
  const out: Option[] = [];
  for (const a of engine.legalActions(s)) {
    if (a.type === "timeout" && a.team !== s.poss) continue;
    out.push(opt(a.type === "play" ? { ...a, tempo } : a));
  }
  return out;
}
export function defenseOptions(_engine: Engine, s: State, team: number): Option[] {
  const out: Option[] = [];
  for (const box of ["light", "heavy"] as const) for (const blitz of [false, true]) out.push(opt({ type: "look", box, blitz }));
  if (s.running && s.tos[team] > 0) out.push(opt({ type: "timeout", team }));
  return out;
}

export function leagueQ(data: EngineData, policy: Policy, s: State, opts: Option[]): void {
  const t = data.tendencies;
  if (opts.length && opts[0].action.type === "look") {
    const cell = data.looks.by_down_dist[`${s.down}|${distBucket(s.togo)}`] ?? data.looks.overall;
    for (const o of opts) {
      if (o.action.type === "look") {
        const pb = o.action.box === "light" ? cell.p_light : 1 - cell.p_light;
        const pz = o.action.blitz ? cell.p_blitz : 1 - cell.p_blitz;
        o.q = pb * pz;
      } else o.q = 0.1;
    }
    return;
  }
  if (s.phase === PAT) { for (const o of opts) o.q = o.action.type === "xp" ? 0.9 : 0.1; return; }
  if (s.phase === KICKOFF) { for (const o of opts) o.q = o.action.type === "kickoff" ? 0.95 : 0.05; return; }
  const probs = policy.callProbs(s);
  const dirs = t.direction;
  const paDep: Record<string, number> = { short: 0.55, medium: 0.3, deep: 0.15 };
  for (const o of opts) {
    const a = o.action;
    let q = 0;
    if (a.type === "play") {
      const call = a.call;
      if (call.startsWith("pass_") || call.startsWith("pa_")) {
        const [fam, dep, d] = call.split("_");
        q = fam === "pass" ? (probs[`pass_${dep}`] ?? 0) * (dirs[dep][d] ?? 1 / 3) : (probs.pa ?? 0) * paDep[dep] * (dirs[dep][d] ?? 1 / 3);
      } else if (call.startsWith("run_")) {
        const fam = call.startsWith("run_inside") ? "run_inside" : "run_outside";
        const d = call.slice(call.lastIndexOf("_") + 1);
        q = (probs[fam] ?? 0) * (dirs.run[d] ?? 1 / 3);
      } else q = probs[call] ?? 0;
    } else if (a.type === "fg") q = probs.field_goal ?? 0;
    else if (a.type === "spike" || a.type === "kneel" || a.type === "punt") q = probs[a.type] ?? 0;
    else if (a.type === "timeout") q = policy.timeoutProb(s, a.team);
    o.q = Math.max(q, 1e-4);
  }
}

export function simulateOption(engine: Engine, s0: State, o: Option, n: number, seed: number, policies: [Policy, Policy], team = 0): number {
  const rng = new Rng(seed);
  let total = 0;
  for (let k = 0; k < n; k++) {
    const s = copyState(s0);
    const r = rng.fork();
    const a = o.action;
    if (a.type === "look") {
      const act = policies[s.poss].choose(s, r);
      if (act.type === "play") engine.step(s, act, r, { box: a.box, blitz: a.blitz });
      else engine.step(s, act, r);
    } else engine.step(s, a, r);
    const v = playOut(engine, s, r, policies);
    total += team === 0 ? v : 1 - v;
  }
  return total / n;
}

export interface GradeOpts { policies?: [Policy, Policy]; team?: number; n1?: number; n2?: number; onProgress?: (done: number, total: number) => void }

export function grade(engine: Engine, s: State, chosen: Action, seed: number, go: GradeOpts = {}): Grade {
  const data = engine.data;
  const g = data.cfg.grading;
  const n1 = go.n1 ?? g.round1_sims, n2 = go.n2 ?? g.round2_sims, team = go.team ?? 0;
  const policies = go.policies ?? [new Policy(data), new Policy(data)];
  let opts: Option[];
  if (s.phase === SNAP && s.poss !== team) opts = defenseOptions(engine, s, team);
  else if (s.phase === SNAP) {
    const tempo = chosen.type === "play" ? (chosen.tempo ?? tempoFor(s)) : tempoFor(s);
    opts = offenseOptions(engine, s, tempo);
  } else opts = engine.legalActions(s).map((a) => opt(a));
  leagueQ(data, policies[team], s, opts);
  const chosenLabel = actionLabel(chosen);
  let ci = opts.findIndex((o) => actionLabel(o.action) === chosenLabel);
  if (ci < 0) { opts.push(opt(chosen, { q: 1e-4 })); ci = opts.length - 1; }
  const total = opts.length + Math.min(opts.length, g.round2_top_k + 1);
  let done = 0;
  for (let i = 0; i < opts.length; i++) {
    opts[i].wp1 = simulateOption(engine, s, opts[i], n1, optionSeed(seed, 1, i), policies, team);
    opts[i].n1 = n1;
    go.onProgress?.(++done, total);
  }
  const eligible = opts.map((_, i) => i).filter((i) => !opts[i].gadget);
  const top = [...eligible].sort((a, b) => opts[b].wp1 - opts[a].wp1).slice(0, g.round2_top_k);
  const r2 = new Set<number>([...top, ci]);
  for (const i of [...r2].sort((a, b) => a - b)) {
    opts[i].wp2 = simulateOption(engine, s, opts[i], n2, optionSeed(seed, 2, i), policies, team);
    opts[i].n2 = n2;
    go.onProgress?.(++done, total);
  }
  let best = ci;
  let bestWp = -1;
  for (const i of eligible) if (opts[i].wp2 !== null && optWp(opts[i]) > bestWp) { best = i; bestWp = optWp(opts[i]); }
  if (bestWp < 0) best = ci;
  if (optWp(opts[ci]) > optWp(opts[best])) best = ci;
  const gap = Math.max(0, optWp(opts[best]) - optWp(opts[ci]));
  const color = gap < g.green_max_gap ? "green" : gap < g.yellow_max_gap ? "yellow" : "red";
  const gaps = opts.map((o) => Math.max(0, optWp(opts[best]) - optWp(o)));
  return { options: opts, chosen: ci, best, gap, color, seed, better: best !== ci ? opts[best].label : null, gaps };
}

export interface PercentileResult { percentile: number; cost: number; n: number; hist: number[] }

export function percentile(decisions: Grade[], data: EngineData, seed: number): PercentileResult {
  const p = data.cfg.percentile;
  const rng = new Rng(seed);
  let playerCost = 0;
  for (const d of decisions) playerCost += d.gap;
  const lo = Math.log(p.tau_log_uniform_min), hi = Math.log(p.tau_log_uniform_max);
  let worse = 0;
  const costs: number[] = [];
  const n = p.virtual_callers;
  for (let k = 0; k < n; k++) {
    const tau = Math.exp(lo + rng.next() * (hi - lo));
    const leagueOnly = rng.chance(p.pure_league_frequency_share);
    let cost = 0;
    for (const d of decisions) {
      const w = leagueOnly ? d.options.map((o) => o.q) : d.options.map((o, i) => o.q * Math.exp(-d.gaps[i] / tau));
      cost += d.gaps[rng.pickWeighted(w)];
    }
    costs.push(cost);
    if (cost > playerCost + 1e-12) worse += 1;
    else if (Math.abs(cost - playerCost) <= 1e-12) worse += 0.5;
  }
  return { percentile: (100 * worse) / n, cost: playerCost, n, hist: hist(costs, 10) };
}
function hist(costs: number[], bins: number): number[] {
  if (!costs.length) return [];
  const hi = Math.max(...costs) || 1;
  const h = new Array(bins).fill(0);
  for (const c of costs) h[Math.min(bins - 1, Math.floor((c / hi) * bins))] += 1;
  return h;
}

// ---- "you coached like"
export interface Coach { name: string; from: number; to: number; teams: string[]; n: number; traits: Record<string, number>; counts: Record<string, number>; shift: Record<string, number> }
export interface Coaches { coaches: Coach[]; scales: Record<string, number> }
const TRAIT_LABELS: Record<string, [string, string]> = {
  pass: ["threw more than the league would", "ran more than the league would"],
  deep: ["took more deep shots", "kept it short"],
  go: ["went for it on 4th down", "kicked on 4th down"],
  timeout: ["burned timeouts early", "sat on timeouts"],
  tempo: ["played slower", "played faster"],
};
const TEMPO_MEAN: Record<string, number> = { hurry: 18, normal: 32, milk: 36 };

export function playerTraits(decisions: [State, Action][], policy: Policy): [Record<string, number>, Record<string, number>] {
  const acc: Record<string, [number, number]> = { pass: [0, 0], deep: [0, 0], go: [0, 0], timeout: [0, 0], tempo: [0, 0] };
  for (const [s, a] of decisions) {
    if (s.phase !== SNAP) continue;
    const probs = policy.callProbs(s);
    const isPlay = a.type === "play";
    if (isPlay || a.type === "fg" || a.type === "punt") {
      let expPass = 0, expScrim = 0;
      for (const [k, v] of Object.entries(probs)) {
        if (k.startsWith("pass") || k === "pa" || k === "rpo" || k === "screen" || k === "hail_mary") expPass += v;
        if (!["field_goal", "punt", "kneel", "spike"].includes(k)) expScrim += v;
      }
      if (isPlay && expScrim > 0) {
        const call = a.call;
        const isPass = !call.startsWith("run") && call !== "qb_sneak";
        acc.pass[0] += (isPass ? 1 : 0) - expPass / expScrim; acc.pass[1] += 1;
        if (isPass) {
          const expDeep = ((probs.pass_deep ?? 0) + 0.15 * (probs.pa ?? 0) + (probs.hail_mary ?? 0)) / Math.max(expPass, 1e-9);
          acc.deep[0] += (call.includes("deep") || call === "hail_mary" ? 1 : 0) - expDeep; acc.deep[1] += 1;
        }
      }
      if (s.down === 4) { acc.go[0] += (isPlay ? 1 : 0) - (1 - (probs.field_goal ?? 0) - (probs.punt ?? 0)); acc.go[1] += 1; }
    }
    if (s.running && s.tos[0] > 0 && diff(s) <= 0 && s.poss === 0) { acc.timeout[0] += (a.type === "timeout" ? 1 : 0) - policy.timeoutProb(s, 0); acc.timeout[1] += 1; }
    if (isPlay && s.running) { acc.tempo[0] += TEMPO_MEAN[a.tempo ?? "normal"] - TEMPO_MEAN[tempoFor(s)]; acc.tempo[1] += 1; }
  }
  const k = 4;
  const traits: Record<string, number> = {}, counts: Record<string, number> = {};
  for (const [name, [sum, n]] of Object.entries(acc)) { traits[name] = n ? (sum / n) * (n / (n + k)) : 0; counts[name] = n; }
  return [traits, counts];
}

export function nearestCoach(traits: Record<string, number>, counts: Record<string, number>, coaches: Coaches, minSupport = 3) {
  const scales = coaches.scales ?? {};
  let best: Coach | null = null, bestD = Infinity;
  for (const c of coaches.coaches ?? []) {
    let d = 0;
    for (const [k, v] of Object.entries(traits)) {
      if (!(counts[k] ?? 0)) continue;
      const sc = scales[k] || 1;
      d += ((v - (c.traits[k] ?? 0)) / sc) ** 2;
    }
    if (d < bestD) { best = c; bestD = d; }
  }
  const reasons: string[] = [];
  if (best) for (const [k, [pos, neg]] of Object.entries(TRAIT_LABELS)) {
    if ((counts[k] ?? 0) >= minSupport && Math.abs(traits[k] ?? 0) > (scales[k] || 1)) {
      const same = traits[k] > 0 === (best.traits[k] ?? 0) > 0;
      if (same) reasons.push(traits[k] > 0 ? pos : neg);
    }
  }
  return { coach: best?.name ?? null, distance: bestD, reasons };
}
