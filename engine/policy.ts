/** Auto-policy, twin of sim/policy.py. */
import type { EngineData } from "./data";
import { DONE, FREE_KICK, KICKOFF, PAT, SNAP, diff, distBucket, isOT, zoneOf, type Action, type State } from "./engine";
import type { Rng } from "./rng";

export function scoreState(d: number): string {
  if (d < -8) return "trail2";
  if (d < 0) return "trail1";
  if (d === 0) return "tied";
  return d <= 8 ? "lead1" : "lead2";
}
export function clockBucket(clock: number): string {
  if (clock <= 30) return "c30";
  if (clock <= 60) return "c60";
  if (clock <= 120) return "c120";
  if (clock <= 300) return "c300";
  return "early";
}
export function tempoFor(s: State): string {
  const d = diff(s);
  const late4 = s.qtr === 4 && s.clock <= 300;
  const late2 = s.qtr === 2 && s.clock <= 120;
  if ((late4 || late2 || isOT(s)) && d <= 0) return "hurry";
  if (late4 && d > 0) return "milk";
  return "normal";
}

export type Shift = Record<string, number>;

export class Policy {
  t: EngineData["tendencies"];
  constructor(public data: EngineData, public shift: Shift = {}) {
    this.t = data.tendencies;
  }

  timeoutProb(s: State, team: number): number {
    if (s.phase !== SNAP || !s.running || s.tos[team] <= 0) return 0;
    const d = s.score[team] - s.score[1 - team];
    if (d > 0 || (s.qtr !== 2 && s.qtr !== 4 && !isOT(s))) return 0;
    const who = team === s.poss ? "offense" : "defense";
    if (who === "defense" && d === 0) return 0;
    const clock = s.clock;
    if ((s.qtr === 4 && clock > 240) || (s.qtr === 2 && clock > 120)) return 0;
    const cb = clock <= 30 ? "c30" : clock <= 60 ? "c60" : clock <= 120 ? "c120" : clock <= 180 ? "c180" : "c240";
    const half = s.qtr === 2 ? "h1" : "h2";
    const table = this.data.clock.timeouts;
    let cell = table.cells[`${half}|${who}|${cb}|${s.tos[team]}`];
    if (cell === undefined || cell.n < table.min_n) cell = table.cells[`h2|${who}|${cb}|${s.tos[team]}`];
    return cell ? cell.p : 0;
  }

  wantsTimeout(s: State, team: number, rng: Rng): boolean {
    const p = this.timeoutProb(s, team);
    return p > 0 && rng.chance(p);
  }

  callProbs(s: State): Record<string, number> {
    const half = isOT(s) ? "ot" : s.qtr <= 2 ? "h1" : "h2";
    const cb = clockBucket(s.clock), ss = scoreState(diff(s)), dist = distBucket(s.togo), zone = zoneOf(s.yl);
    const keys = [`L0|${half}|${cb}|${ss}|${s.down}|${dist}|${zone}`, `L1|${half}|${cb}|${ss}|${s.down}|${dist}`,
      `L2|${ss}|${s.down}|${dist}|${zone}`, `L3|${s.down}|${dist}|${zone}`, `L4|${s.down}|${dist}`];
    let cell: { n: number; p: Record<string, number> } | undefined;
    for (const k of keys) {
      const c = this.t.cells[k];
      if (c !== undefined && c.n >= this.t.min_cell_n) { cell = c; break; }
    }
    const probs: Record<string, number> = cell ? { ...cell.p } : { pass_short: 1 };
    for (const k of Object.keys(this.shift)) {
      const m = this.shift[k];
      for (const call of Object.keys(probs)) {
        if ((k === "pass" && (call.startsWith("pass") || call === "pa" || call === "rpo" || call === "screen")) ||
            (k === "deep" && call === "pass_deep") || (k === "go" && s.down === 4 && call !== "punt" && call !== "field_goal")) probs[call] *= m;
      }
    }
    let tot = 0;
    for (const v of Object.values(probs)) tot += v;
    tot = tot || 1;
    const out: Record<string, number> = {};
    for (const [k, v] of Object.entries(probs)) out[k] = v / tot;
    return out;
  }

  pick(probs: Record<string, number>, rng: Rng): string {
    const keys = Object.keys(probs);
    return keys[rng.pickWeighted(keys.map((k) => probs[k]))];
  }

  choose(s: State, rng: Rng): Action {
    if (s.phase === PAT) return this.patChoice(s);
    if (s.phase === KICKOFF) return this.kickoffChoice(s);
    if (s.phase === FREE_KICK) return { type: "free_kick" };
    if (s.phase === DONE) return { type: "noop" };
    return this.snap(s, rng);
  }

  private patChoice(s: State): Action {
    const team = s.poss;
    const d = s.score[team] - s.score[1 - team];
    const late = (s.qtr === 4 && s.clock <= 300) || isOT(s);
    if (late && [-2, -5, -10, -13, -16, 1, 4].includes(d)) return { type: "two_pt" };
    if (s.qtr === 4 && s.clock <= 60 && d === -2) return { type: "two_pt" };
    return { type: "xp" };
  }

  private kickoffChoice(s: State): Action {
    const k = s.kickTeam;
    const d = s.score[k] - s.score[1 - k];
    if (d < 0 && s.qtr === 4) {
      const budget = 60 + 45 * s.tos[k];
      if (s.clock <= budget) return { type: "onside" };
    }
    return { type: "kickoff" };
  }

  private snap(s: State, rng: Rng): Action {
    const d = diff(s);
    const tempo = tempoFor(s);
    const lastPeriod = s.qtr === 4 || isOT(s) || s.qtr === 2;
    const oppTos = s.tos[1 - s.poss];
    if (d > 0 && s.qtr === 4 && s.down <= 3) {
      const kneels = 4 - s.down;
      const burn = Math.max(0, kneels - oppTos) * 42 + Math.min(kneels, oppTos) * 2;
      if (burn >= s.clock) return { type: "kneel" };
    }
    if (d > 0 && s.qtr === 4 && s.down === 4 && s.clock <= 2) return { type: "kneel" };
    const inFgRange = s.yl + 17 <= 58;
    const needFg = -3 <= d && d <= 0 && (s.qtr === 4 || isOT(s) || s.qtr === 2);
    if (needFg && inFgRange && s.clock <= 40) {
      if (s.running && s.tos[s.poss] > 0) return { type: "timeout", team: s.poss };
      if (s.running && s.down <= 3) return { type: "spike" };
      if (!s.running && (s.clock <= 15 || s.down === 4)) return { type: "fg" };
    }
    if ((lastPeriod && s.clock <= 6 && !s.running) || (lastPeriod && s.running && s.clock <= 8 && s.tos[s.poss] === 0)) {
      if (inFgRange && ([-3, -2, -1, 0].includes(d) || s.qtr === 2)) return { type: "fg" };
      if (s.qtr === 2 && !inFgRange) return { type: "play", call: s.yl >= 30 ? "hail_mary" : "pass_deep_middle", tempo: "hurry" };
      if (d < 0) return { type: "play", call: s.yl >= 30 ? "hail_mary" : "pass_deep_middle", tempo: "hurry" };
    }
    if (s.down === 4 && inFgRange && (s.qtr === 4 || isOT(s)) && s.clock <= 150 && -3 <= d && d <= 0) return { type: "fg" };
    if (s.down === 4 && inFgRange && s.qtr === 2 && s.clock <= 30) return { type: "fg" };
    if (s.running && s.tos[s.poss] === 0 && d <= 0 && s.down <= 3 && ((s.qtr === 4 && s.clock <= 25) || (s.qtr === 2 && s.clock <= 20))) return { type: "spike" };

    let pcall = this.pick(this.callProbs(s), rng);
    if (pcall === "field_goal") {
      if (!inFgRange || s.yl + 17 > (this.data.fg.max_attempt_distance ?? 68)) pcall = d >= 0 || s.clock > 180 ? "punt" : "pass_medium";
      else return { type: "fg" };
    }
    if (pcall === "punt") {
      if ((s.qtr === 4 && d < 0 && s.clock <= 240 && s.tos[s.poss] < 3) || (s.qtr === 4 && d < 0 && s.clock <= 120)) pcall = "pass_medium";
      else return { type: "punt" };
    }
    if (pcall === "kneel") return d > 0 ? { type: "kneel" } : { type: "play", call: "run_inside_middle", tempo };
    if (pcall === "spike") return s.running && s.down <= 3 ? { type: "spike" } : { type: "play", call: "pass_short_middle", tempo: "hurry" };
    if (pcall === "qb_sneak") {
      if (s.togo > 2 && s.yl > 2) pcall = "run_inside";
      else return { type: "play", call: "qb_sneak", tempo };
    }
    if (pcall === "hail_mary") {
      if (s.yl < 30 || s.clock > 20) pcall = "pass_deep";
      else return { type: "play", call: "hail_mary", tempo: "hurry" };
    }
    if (pcall === "rpo" || pcall === "screen") return { type: "play", call: pcall, tempo };
    if (pcall === "run_inside" || pcall === "run_outside") {
      let dd = this.pick(this.t.direction.run, rng);
      if (pcall === "run_outside" && dd === "middle") dd = rng.chance(0.5) ? "left" : "right";
      return { type: "play", call: `${pcall}_${dd}`, tempo };
    }
    if (pcall === "pa") {
      const dep = this.pick({ short: 0.55, medium: 0.3, deep: 0.15 }, rng);
      const dd = this.pick(this.t.direction[dep], rng);
      return { type: "play", call: `pa_${dep}_${dd}`, tempo };
    }
    const dep = pcall.split("_")[1];
    const dd = this.pick(this.t.direction[dep], rng);
    return { type: "play", call: `pass_${dep}_${dd}`, tempo };
  }
}

export const coinTossKicker = (rng: Rng): number => (rng.chance(0.5) ? 0 : 1);
