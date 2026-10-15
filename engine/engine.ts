/** Seeded game-ending simulator. Twin of sim/engine.py; keep RNG call order identical. */
import type { EngineData } from "./data";
import { drawHist, fgProb, winProb } from "./models";
import type { Rng } from "./rng";

export const SNAP = "snap", PAT = "pat", KICKOFF = "kickoff", FREE_KICK = "free_kick", DONE = "done";
export type Phase = typeof SNAP | typeof PAT | typeof KICKOFF | typeof FREE_KICK | typeof DONE;
export const RUN_FAMILIES = ["run_inside", "run_outside", "qb_sneak"] as const;
export const FAMILIES = ["run_inside", "run_outside", "qb_sneak", "pass", "pa", "rpo", "screen", "hail_mary", "gadget"] as const;

export interface Ctx {
  spread: number; indoor: boolean; wind: number; temp: number; playoff: boolean; endAtHalf: boolean;
}
export const defaultCtx = (): Ctx => ({ spread: 0, indoor: false, wind: 0, temp: 60, playoff: false, endAtHalf: false });

export interface Look { box: "light" | "heavy"; blitz: boolean }
export type Action =
  | { type: "play"; call: string; tempo?: string }
  | { type: "timeout"; team: number }
  | { type: "spike" } | { type: "kneel" } | { type: "fg" } | { type: "punt" }
  | { type: "xp" } | { type: "two_pt" } | { type: "kickoff" } | { type: "onside" } | { type: "free_kick" }
  | { type: "look"; box: "light" | "heavy"; blitz: boolean }
  | { type: "noop" };

export interface State {
  qtr: number; clock: number; running: boolean; poss: number; down: number; togo: number; yl: number;
  score: [number, number]; tos: [number, number]; phase: Phase; warned: boolean; recv2h: number; kickTeam: number;
  otFirst: number; otDone: [boolean, boolean]; plays: number;
}

export function newState(p: Partial<State> = {}): State {
  return { qtr: 4, clock: 120, running: false, poss: 0, down: 1, togo: 10, yl: 75, score: [0, 0], tos: [3, 3], phase: SNAP,
    warned: false, recv2h: 1, kickTeam: 0, otFirst: -1, otDone: [false, false], plays: 0, ...p,
    ...(p.score ? { score: [p.score[0], p.score[1]] as [number, number] } : {}),
    ...(p.tos ? { tos: [p.tos[0], p.tos[1]] as [number, number] } : {}),
    ...(p.otDone ? { otDone: [p.otDone[0], p.otDone[1]] as [boolean, boolean] } : {}) };
}
export function copyState(s: State): State {
  return { ...s, score: [s.score[0], s.score[1]], tos: [s.tos[0], s.tos[1]], otDone: [s.otDone[0], s.otDone[1]] };
}
export const isOT = (s: State) => s.qtr >= 5;
/** Read the phase through a call so TypeScript does not narrow it across mutations. */
export const phaseOf = (s: State): Phase => s.phase;
export const isDone = (s: State) => phaseOf(s) === DONE;
export const diff = (s: State) => s.score[s.poss] - s.score[1 - s.poss];
export const secondsLeftRegulation = (s: State) => (s.qtr >= 5 ? 0 : s.clock + (4 - s.qtr) * 900);
export const halfSecondsLeft = (s: State) => (s.qtr >= 5 ? s.clock : s.clock + (s.qtr === 1 || s.qtr === 3 ? 900 : 0));

export interface Event {
  kind: string; text: string; yards: number; call: string; look: string; row: number; level: string;
  td: boolean; turnover: boolean; firstDown: boolean; penalty: number; score: [number, number];
  duration: number; presnap: number; made: boolean | null; ended: boolean;
}
export function ev(kind: string, s: State, p: Partial<Event> = {}): Event {
  return { kind, text: "", yards: 0, call: "", look: "", row: -1, level: "", td: false, turnover: false, firstDown: false,
    penalty: 0, score: [s.score[0], s.score[1]], duration: 0, presnap: 0, made: null, ended: false, ...p };
}

export function zoneOf(yl: number): string {
  if (yl <= 10) return "gl";
  if (yl <= 20) return "rz";
  if (yl <= 60) return "mid";
  if (yl <= 80) return "own";
  return "deep";
}
export const distBucket = (togo: number) => (togo <= 3 ? "short" : togo <= 7 ? "mid" : "long");

export function callFamily(call: string): string {
  for (const fam of FAMILIES) {
    if (call === fam || call.startsWith(fam + "_")) {
      if (fam === "pass" && call.startsWith("pa_")) continue;
      return fam;
    }
  }
  throw new Error("unknown call " + call);
}
const isRun = (fam: string) => fam === "run_inside" || fam === "run_outside" || fam === "qb_sneak";

export class Engine {
  cfg: EngineData["cfg"];
  minN: number;
  private lastEnded = false;
  constructor(public data: EngineData, public ctx: Ctx) {
    this.cfg = data.cfg;
    this.minN = data.cfg.playbook.min_bucket_size;
  }

  periodLength(s: State): number {
    if (s.qtr >= 5) {
      const ot = this.cfg.rules.overtime;
      return 60 * (this.ctx.playoff ? ot.playoff_minutes : ot.regular_season_minutes);
    }
    return 900;
  }

  legalActions(s: State): Action[] {
    if (s.phase === DONE) return [];
    if (s.phase === PAT) return [{ type: "xp" }, { type: "two_pt" }];
    if (s.phase === KICKOFF) return [{ type: "kickoff" }, { type: "onside" }];
    if (s.phase === FREE_KICK) return [{ type: "free_kick" }];
    const acts: Action[] = [];
    for (const fam of RUN_FAMILIES) {
      if (fam === "qb_sneak") {
        if (s.togo <= 2 || s.yl <= 2) acts.push({ type: "play", call: "qb_sneak" });
      } else {
        for (const d of fam === "run_inside" ? ["left", "middle", "right"] : ["left", "right"]) acts.push({ type: "play", call: `${fam}_${d}` });
      }
    }
    for (const fam of ["pass", "pa"]) for (const dep of ["short", "medium", "deep"]) for (const d of ["left", "middle", "right"]) acts.push({ type: "play", call: `${fam}_${dep}_${d}` });
    acts.push({ type: "play", call: "rpo" }, { type: "play", call: "screen" });
    if (s.yl >= 30) acts.push({ type: "play", call: "hail_mary" });
    acts.push({ type: "play", call: "gadget" });
    acts.push({ type: "spike" }, { type: "kneel" });
    if (s.yl + 17 <= (this.data.fg.max_attempt_distance ?? 68)) acts.push({ type: "fg" });
    acts.push({ type: "punt" });
    if (s.tos[s.poss] > 0 && s.running) acts.push({ type: "timeout", team: s.poss });
    if (s.tos[1 - s.poss] > 0 && s.running) acts.push({ type: "timeout", team: 1 - s.poss });
    return acts;
  }

  // ---- clock
  private presnap(s: State, tempo: string, rng: Rng): [number, Event | null] {
    if (!s.running) return [0, null];
    let t = drawHist(this.data.clock.tempo[tempo], rng);
    t = Math.min(t, this.cfg.clock.play_clock_seconds);
    const before = s.clock;
    s.clock = Math.max(0, s.clock - t);
    const used = before - s.clock;
    const warnAt = this.cfg.clock.two_minute_warning_seconds;
    if (!s.warned && (s.qtr === 2 || s.qtr === 4) && before > warnAt && s.clock <= warnAt) {
      s.clock = warnAt; s.warned = true; s.running = false;
      return [before - s.clock, ev("warning", s, { text: "Two-minute warning" })];
    }
    if (s.clock === 0) return [used, this.endPeriod(s)];
    return [used, null];
  }

  private afterPlayClock(s: State, duration: number, stops: boolean): Event | null {
    const before = s.clock;
    this.lastEnded = false;
    s.clock = Math.max(0, s.clock - duration);
    s.running = !stops;
    const warnAt = this.cfg.clock.two_minute_warning_seconds;
    if (!s.warned && (s.qtr === 2 || s.qtr === 4) && before > warnAt && s.clock <= warnAt) {
      s.warned = true; s.running = false; s.clock = Math.max(s.clock, 0);
    }
    if (s.clock === 0) { this.lastEnded = true; return this.endPeriod(s); }
    return null;
  }

  private endPeriod(s: State): Event {
    s.running = false;
    if (s.qtr === 1 || s.qtr === 3) { s.qtr += 1; s.clock = 900; return ev("period", s, { text: `End of Q${s.qtr - 1}` }); }
    if (s.qtr === 2) {
      if (this.ctx.endAtHalf) { s.phase = DONE; return ev("period", s, { text: "Halftime" }); }
      s.qtr = 3; s.clock = 900; s.warned = false; s.tos = [3, 3]; s.phase = KICKOFF; s.kickTeam = 1 - s.recv2h;
      return ev("period", s, { text: "Halftime" });
    }
    if (s.qtr === 4) {
      if (s.score[0] !== s.score[1]) { s.phase = DONE; return ev("period", s, { text: "Final" }); }
      return this.startOvertime(s);
    }
    const ot = this.cfg.rules.overtime;
    if (s.score[0] !== s.score[1]) { s.phase = DONE; return ev("period", s, { text: "Final (OT)" }); }
    if (this.ctx.playoff || !ot.regular_season_can_tie) { s.qtr += 1; s.clock = this.periodLength(s); return ev("period", s, { text: `End of OT${s.qtr - 4}` }); }
    s.phase = DONE;
    return ev("period", s, { text: "Final: tie" });
  }

  private startOvertime(s: State): Event {
    const ot = this.cfg.rules.overtime;
    s.qtr = 5;
    s.clock = this.periodLength(s);
    const n = this.ctx.playoff ? ot.playoff_timeouts : ot.regular_season_timeouts;
    s.tos = [n, n]; s.warned = false; s.otDone = [false, false]; s.otFirst = -1; s.phase = KICKOFF;
    return ev("period", s, { text: "Overtime" });
  }

  private changePossession(s: State, newYl: number): void {
    if (isOT(s)) s.otDone[s.poss] = true;
    s.poss = 1 - s.poss;
    s.yl = Math.min(99, Math.max(1, newYl));
    s.down = 1; s.togo = Math.min(10, s.yl); s.running = false;
    this.otCheck(s);
  }
  private otCheck(s: State): void {
    if (!isOT(s) || s.phase === DONE) return;
    if (s.otDone[0] && s.otDone[1] && s.score[0] !== s.score[1]) s.phase = DONE;
  }
  private addScore(s: State, team: number, pts: number): void { s.score[team] += pts; s.running = false; }

  // ---- public step
  step(s: State, action: Action, rng: Rng, look: Look | null = null): Event {
    if (s.phase === DONE) return ev("done", s, { text: "Game over" });
    this.lastEnded = false;
    const e = this.dispatch(s, action, rng, look);
    if (this.lastEnded && e.kind !== "period" && e.kind !== "warning") e.ended = true;
    return e;
  }

  private dispatch(s: State, action: Action, rng: Rng, look: Look | null): Event {
    const t = action.type;
    if (s.phase === PAT) return this.pat(s, t, rng);
    if (s.phase === KICKOFF) return this.kickoff(s, t === "onside", rng);
    if (s.phase === FREE_KICK) return this.freeKick(s, rng);
    if (t === "timeout") {
      const team = action.team ?? s.poss;
      if (s.tos[team] <= 0) return ev("noop", s, { text: "No timeouts left" });
      s.tos[team] -= 1; s.running = false;
      return ev("timeout", s, { text: `Timeout, team ${team}` });
    }
    if (t === "spike") return this.spike(s);
    if (t === "kneel") return this.kneel(s);
    if (t === "fg") return this.fieldGoal(s, rng);
    if (t === "punt") return this.punt(s, rng);
    if (t === "play") return this.play(s, action, rng, look);
    throw new Error("unknown action " + JSON.stringify(action));
  }

  sampleLook(s: State, rng: Rng): Look {
    const cell = this.data.looks.by_down_dist[`${s.down}|${distBucket(s.togo)}`] ?? this.data.looks.overall;
    return { box: rng.chance(cell.p_light) ? "light" : "heavy", blitz: rng.chance(cell.p_blitz) };
  }

  private play(s: State, action: { type: "play"; call: string; tempo?: string }, rng: Rng, look: Look | null): Event {
    const call = action.call;
    const fam = callFamily(call);
    const tempo = action.tempo ?? "normal";
    const [presnap, pe] = this.presnap(s, tempo, rng);
    if (pe !== null && (pe.kind === "period" || s.phase === DONE)) { pe.presnap = presnap; return pe; }
    if (look === null) look = this.sampleLook(s, rng);
    const lookKey = isRun(fam) ? `${look.box}_any` : `${look.box}_${look.blitz ? "blitz" : "base"}`;
    const [start, n, level] = this.data.playbook.cell(fam, call, lookKey, zoneOf(s.yl), this.minN);
    const i = start + rng.below(n);
    const pb = this.data.playbook.cols;
    const yards = pb.yards[i], to = pb.to[i], nullified = pb.nullified[i] === 1, pen = pb.pen[i], penYds = pb.pen_yds[i];
    const inc = pb.inc[i] === 1, sack = pb.sack[i] === 1, oob = pb.oob[i] === 1, rowTd = pb.td[i] === 1, defTd = pb.def_td[i] === 1;
    const air = pb.air[i], ret = pb.ret[i];
    const e = ev("play", s, { call, look: lookKey, row: i, level, presnap });
    let dkey: string;
    if (isRun(fam) || sack || (to === 1 && !inc)) dkey = "run";
    else if (inc || to === 2) dkey = "pass_incomplete";
    else dkey = "pass_complete";
    const duration = drawHist(this.data.clock.duration[dkey], rng);
    e.duration = duration;
    s.plays += 1;
    const off = s.poss;

    if (nullified) {
      e.penalty = pen;
      if (pen === 1) {
        const y = penYds > 0 ? Math.min(penYds, Math.floor((100 - s.yl) / 2)) : 5;
        s.yl += y; s.togo += y; e.text = `Penalty on the offense, ${y} yards`; e.yards = -y;
      } else if (pen === 2) {
        const y = penYds > 0 ? Math.min(penYds, Math.floor(s.yl / 2)) : 5;
        s.yl -= y; e.yards = y;
        if (y >= 10 || y >= s.togo) { s.down = 1; s.togo = Math.min(10, s.yl); e.firstDown = true; } else s.togo -= y;
        e.text = `Penalty on the defense, ${y} yards`;
        if (s.yl <= 0) { s.yl = 1; s.togo = 1; }
      } else e.text = "No play";
      const stop = this.afterPlayClock(s, duration, true);
      s.togo = Math.min(s.togo, s.yl);
      return stop !== null && s.phase === DONE ? stop : e;
    }

    if (to) {
      let spot = to === 2 ? s.yl - (air > -99 ? air : 0) : s.yl - yards;
      spot = Math.min(99, Math.max(0, spot));
      const newYl = 100 - spot - ret;
      e.turnover = true; e.yards = yards; e.text = to === 2 ? "Interception" : "Fumble";
      this.afterPlayClock(s, duration, true);
      if (s.phase === DONE) return e;
      if (defTd || newYl <= 0) {
        this.touchdown(s, 1 - off, e);
        e.text += ", returned for a touchdown";
        if (isOT(s)) s.otDone[off] = true;
        return e;
      }
      this.changePossession(s, newYl);
      return e;
    }

    let newYl = s.yl - yards;
    e.yards = yards;
    if (newYl <= 0 || (rowTd && yards >= s.yl)) {
      e.text = `${isRun(fam) ? "Run" : "Pass"} for ${s.yl} yards, touchdown`;
      e.yards = s.yl;
      this.afterPlayClock(s, duration, true);
      if (s.phase !== DONE) this.touchdown(s, off, e);
      return e;
    }
    if (newYl >= 100) {
      e.text = "Safety";
      this.afterPlayClock(s, duration, true);
      if (s.phase === DONE) return e;
      this.addScore(s, 1 - off, 2);
      s.phase = FREE_KICK; s.kickTeam = off;
      if (isOT(s)) { s.otDone[off] = true; this.otCheck(s); }
      return e;
    }
    if (pen === 2 && penYds > 0) { newYl = Math.max(1, newYl - Math.min(penYds, Math.floor(newYl / 2))); e.penalty = 2; }
    else if (pen === 1 && penYds > 0) { newYl = Math.min(99, newYl + Math.min(penYds, Math.floor((100 - newYl) / 2))); e.penalty = 1; }
    const gained = s.yl - newYl;
    s.yl = newYl;
    if (sack) e.text = yards === 0 ? "Sacked at the line" : `Sacked for ${-yards} yards`;
    else if (inc) e.text = "Incomplete";
    else e.text = `${isRun(fam) ? "Run" : "Pass"} for ${gained} yards` + (oob ? " (out of bounds)" : "");
    if (gained >= s.togo || (pen === 2 && penYds >= 10)) { s.down = 1; s.togo = Math.min(10, s.yl); e.firstDown = true; }
    else { s.togo -= gained; s.down += 1; }
    const w = this.cfg.clock;
    const oobStops = oob && halfSecondsLeft(s) <= (s.qtr <= 2 ? w.ob_stops_clock_inside_q2_seconds : w.ob_stops_clock_inside_q4_seconds);
    const stops = inc || oobStops || pen !== 0;
    this.afterPlayClock(s, duration, stops);
    if (s.phase === DONE) return e;
    if (s.down > 4) { e.text += ", turnover on downs"; e.turnover = true; this.changePossession(s, 100 - s.yl); }
    return e;
  }

  private touchdown(s: State, team: number, e: Event): void {
    e.td = true;
    this.addScore(s, team, 6);
    s.phase = PAT; s.poss = team; s.kickTeam = team;
    if (isOT(s)) {
      this.otCheck(s);
      if (isDone(s)) return;
      if (s.otDone[1 - team] || (s.otFirst !== -1 && s.otFirst !== team)) { s.otDone[team] = true; s.phase = DONE; }
    }
  }

  private spike(s: State): Event {
    let presnap = 0;
    if (s.running) {
      presnap = Math.min(s.clock, 3);
      s.clock -= presnap;
      if (s.clock === 0) return this.endPeriod(s);
    }
    s.plays += 1; s.down += 1;
    const e = ev("spike", s, { text: "Spike", presnap, duration: 2 });
    this.afterPlayClock(s, 2, true);
    if (s.phase !== DONE && s.down > 4) { e.turnover = true; this.changePossession(s, 100 - s.yl); }
    return e;
  }

  private kneel(s: State): Event {
    const before = s.clock;
    if (s.running) {
      s.clock = Math.max(0, s.clock - this.cfg.clock.play_clock_seconds);
      const warnAt = this.cfg.clock.two_minute_warning_seconds;
      if (!s.warned && (s.qtr === 2 || s.qtr === 4) && before > warnAt && s.clock <= warnAt) {
        s.clock = warnAt; s.warned = true; s.running = false;
        return ev("warning", s, { text: "Two-minute warning", presnap: before - warnAt });
      }
      if (s.clock === 0) return this.endPeriod(s);
    }
    const presnap = before - s.clock;
    s.plays += 1; s.yl = Math.min(99, s.yl + 1); s.down += 1; s.togo += 1;
    const e = ev("kneel", s, { text: "Kneel", yards: -1, presnap, duration: 2 });
    this.afterPlayClock(s, 2, false);
    if (s.phase !== DONE && s.down > 4) { e.turnover = true; this.changePossession(s, 100 - s.yl); }
    return e;
  }

  private fieldGoal(s: State, rng: Rng): Event {
    const late = (s.qtr === 4 && s.clock <= 300) || (s.qtr === 2 && s.clock <= 120) || isOT(s);
    const [presnap, pe] = this.presnap(s, late && diff(s) <= 0 ? "hurry" : "normal", rng);
    if (pe !== null && (pe.kind === "period" || s.phase === DONE)) return pe;
    s.plays += 1;
    const dist = s.yl + 17;
    const p = fgProb(this.data.fg, dist, this.ctx.indoor, this.ctx.wind, this.ctx.temp);
    const made = rng.chance(p);
    const off = s.poss;
    const e = ev("fg", s, { text: `${dist}-yard field goal ${made ? "is good" : "is no good"}`, presnap, duration: 5, made });
    this.afterPlayClock(s, 5, true);
    if (s.phase === DONE) return e;
    if (made) {
      this.addScore(s, off, 3); e.score = [s.score[0], s.score[1]];
      s.phase = KICKOFF; s.kickTeam = off;
      if (isOT(s)) { s.otDone[off] = true; this.otCheck(s); }
    } else {
      const spot = s.yl + 7;
      this.changePossession(s, spot >= 20 ? 100 - spot : 80);
    }
    return e;
  }

  private punt(s: State, rng: Rng): Event {
    const [presnap, pe] = this.presnap(s, "normal", rng);
    if (pe !== null && (pe.kind === "period" || s.phase === DONE)) return pe;
    s.plays += 1;
    const zones = this.data.punt.zones;
    const zone = zones.find((z) => z.from_min <= s.yl && s.yl <= z.from_max) ?? zones[zones.length - 1];
    const off = s.poss;
    const e = ev("punt", s, { text: "Punt", presnap, duration: 8 });
    this.afterPlayClock(s, 8, true);
    if (s.phase === DONE) return e;
    if (rng.chance(zone.blocked)) { e.text = "Punt blocked"; this.changePossession(s, 100 - s.yl); return e; }
    if (rng.chance(zone.return_td)) {
      e.text = "Punt returned for a touchdown";
      if (isOT(s)) s.otDone[off] = true;
      this.touchdown(s, 1 - off, e);
      return e;
    }
    this.changePossession(s, drawHist(zone.next_yl, rng));
    return e;
  }

  private pat(s: State, kind: string, rng: Rng): Event {
    const team = s.poss;
    let e: Event;
    if (kind === "two_pt") {
      const ok = rng.chance(this.data.pat.two_pt);
      if (ok) this.addScore(s, team, 2);
      e = ev("pat", s, { text: "Two-point try " + (ok ? "is good" : "fails"), made: ok });
    } else {
      const ok = rng.chance(this.data.pat.xp);
      if (ok) this.addScore(s, team, 1);
      e = ev("pat", s, { text: "Extra point " + (ok ? "is good" : "is no good"), made: ok });
    }
    s.phase = KICKOFF; s.kickTeam = team;
    if (isOT(s)) { s.otDone[team] = true; this.otCheck(s); }
    if (!isDone(s) && s.qtr === 4 && s.clock === 0) this.endPeriodAfterScore(s);
    return e;
  }

  private endPeriodAfterScore(s: State): void {
    if (s.qtr === 4) {
      if (s.score[0] !== s.score[1]) s.phase = DONE; else this.startOvertime(s);
    } else if (s.qtr === 2) this.endPeriod(s);
  }

  private kickoff(s: State, onside: boolean, rng: Rng): Event {
    const kicker = s.kickTeam, receiver = 1 - kicker;
    if (isOT(s) && s.otFirst === -1) s.otFirst = receiver;
    s.plays += 1;
    const ko = this.data.kickoff;
    if (onside) {
      if (rng.chance(ko.onside.recovery)) {
        s.poss = kicker; s.yl = drawHist(ko.onside.recover_yl, rng); s.down = 1; s.togo = 10; s.phase = SNAP; s.running = false;
        return ev("kickoff", s, { text: "Onside kick recovered by the kicking team" });
      }
      s.poss = receiver; s.yl = drawHist(ko.onside.fail_yl, rng); s.down = 1; s.togo = 10; s.phase = SNAP; s.running = false;
      return ev("kickoff", s, { text: "Onside kick fails" });
    }
    if (rng.chance(ko.return_td)) {
      const e = ev("kickoff", s, { text: "Kickoff returned for a touchdown" });
      this.afterPlayClock(s, 12, true);
      if (!isDone(s)) { s.poss = receiver; this.touchdown(s, receiver, e); }
      return e;
    }
    s.poss = receiver; s.yl = drawHist(ko.start_yl, rng); s.down = 1; s.togo = 10; s.phase = SNAP;
    const touchback = s.yl === 100 - this.cfg.rules.kickoff_touchback_yardline;
    this.afterPlayClock(s, touchback ? 0 : 6, touchback);
    return ev("kickoff", s, { text: touchback ? "Touchback" : `Kickoff returned to the ${100 - s.yl}` });
  }

  private freeKick(s: State, rng: Rng): Event {
    const receiver = 1 - s.kickTeam;
    s.plays += 1;
    s.poss = receiver; s.yl = drawHist(this.data.kickoff.safety_kick_start_yl, rng); s.down = 1; s.togo = 10; s.phase = SNAP;
    this.afterPlayClock(s, 5, true);
    return ev("kickoff", s, { text: "Free kick after the safety" });
  }

  value(s: State): number {
    if (s.phase === DONE && !(this.ctx.endAtHalf && s.qtr === 2)) {
      if (s.score[0] > s.score[1]) return 1;
      if (s.score[0] < s.score[1]) return 0;
      return 0.5;
    }
    const recv = s.recv2h;
    const sd = s.score[recv] - s.score[1 - recv];
    const spread = recv === 0 ? this.ctx.spread : -this.ctx.spread;
    const halftime = s.qtr === 2 && s.phase === DONE;
    const t = halftime ? 1800 : secondsLeftRegulation(s);
    const yl = halftime ? 100 - this.cfg.rules.kickoff_touchback_yardline : s.yl;
    const wp = winProb(this.data.wp, sd, t, yl, 1, 10, 3, 3, spread, 0, 0, 0, isOT(s) ? 1 : 0);
    return recv === 0 ? wp : 1 - wp;
  }

  stateWp(s: State, team = 0): number {
    if (s.phase === DONE) { const v = this.value(s); return team === 0 ? v : 1 - v; }
    const p = s.poss;
    const sd = s.score[p] - s.score[1 - p];
    const spread = p === 0 ? this.ctx.spread : -this.ctx.spread;
    const half1 = s.qtr <= 2 ? 1 : 0;
    const t = !isOT(s) ? secondsLeftRegulation(s) : Math.max(1, s.clock);
    const wp = winProb(this.data.wp, sd, t, s.yl, s.down, s.togo, s.tos[p], s.tos[1 - p], spread, half1, s.recv2h === p ? 1 : 0,
      s.togo >= s.yl ? 1 : 0, isOT(s) ? 1 : 0);
    return p === team ? wp : 1 - wp;
  }
}
