/** One playable spot: the live game on the main thread, grading jobs in the pool. */
import type { EngineData } from "@engine/data";
import { DONE, Engine, FREE_KICK, KICKOFF, PAT, SNAP, copyState, isOT, type Action, type Ctx, type Event, type Look, type State } from "@engine/engine";
import { nearestCoach, percentile, playerTraits, type Coaches, type Grade } from "@engine/grading";
import { Policy, tempoFor } from "@engine/policy";
import type { WorkerPool } from "@engine/pool";
import { Rng } from "@engine/rng";
import { stateFromSpot, type Spot } from "@engine/simulate";
import type { SpotFile } from "./data";
import { hashStr } from "./util";
import { adaptiveLook } from "@engine/adaptive";

export type Turn = "offense" | "defense" | "pat" | "kickoff" | "none";
export interface Decision { idx: number; before: State; action: Action; seed: number; grade: Grade | null; event: Event; wpBefore: number; wpAfter: number; events: Event[] }

export class Session {
  engine: Engine;
  ctx: Ctx;
  state: State;
  rng: Rng;
  log: Event[] = [];
  decisions: Decision[] = [];
  policies: [Policy, Policy];
  status: "playing" | "done" = "playing";
  onGrade: ((d: Decision) => void) | null = null;
  onProgress: ((d: Decision, done: number, total: number) => void) | null = null;
  summary: Summary | null = null;
  recentCalls: string[] = [];
  announce: string | null = null;

  constructor(public data: EngineData, public spot: Spot, public file: SpotFile, public pool: WorkerPool | null, public seed: number, public coaches: Coaches) {
    const [s, ctx] = stateFromSpot(spot);
    this.state = s;
    this.ctx = ctx;
    this.engine = new Engine(data, ctx);
    this.rng = new Rng(seed);
    this.policies = [new Policy(data, file.off.shift ?? {}), new Policy(data, file.def.shift ?? {})];
  }

  get shifts(): [Record<string, number>, Record<string, number>] { return [this.file.off.shift ?? {}, this.file.def.shift ?? {}]; }

  turn(): Turn {
    const s = this.state;
    if (s.phase === DONE) return "none";
    if (s.phase === SNAP) return s.poss === 0 ? "offense" : "defense";
    if (s.phase === PAT) return s.poss === 0 ? "pat" : "none";
    if (s.phase === KICKOFF) return s.kickTeam === 0 ? "kickoff" : "none";
    return "none";
  }
  defaultTempo(): string { return tempoFor(this.state); }
  wp(): number { return this.engine.stateWp(this.state, 0); }

  /** The player acts. Returns the events that happened before control comes back (the play, then the opponent's moves). */
  act(action: Action): Decision {
    const before = copyState(this.state);
    const idx = this.decisions.length;
    const seed = hashStr(`${this.spot.id}:${this.seed}:${idx}`);
    const wpBefore = this.wp();
    let event: Event;
    if (action.type === "look") {
      // the opponent's play, with the look the player chose
      const look: Look = { box: action.box, blitz: action.blitz };
      const act = this.policies[1].choose(this.state, this.rng);
      event = act.type === "play" ? this.engine.step(this.state, act, this.rng, look) : this.engine.step(this.state, act, this.rng);
    } else if (action.type === "play" && this.state.poss === 0) {
      // the opponent's defense adapts to what you have been calling
      const { look, info } = adaptiveLook(this.data, this.state, this.recentCalls, this.rng);
      this.announce = info.announce;
      event = this.engine.step(this.state, action, this.rng, look);
      this.recentCalls.push(action.call);
    } else event = this.engine.step(this.state, action, this.rng);
    this.log.push(event);
    const d: Decision = { idx, before, action, seed, grade: null, event, wpBefore, wpAfter: 0, events: [event] };
    this.decisions.push(d);
    d.events.push(...this.autoAdvance());
    d.wpAfter = this.wp();
    if (this.state.phase === DONE) this.status = "done";
    this.requestGrade(d);
    return d;
  }

  /** Opponent moves until the player must act again. */
  autoAdvance(): Event[] {
    const out: Event[] = [];
    let guard = 0;
    while (this.state.phase !== DONE && guard++ < 60) {
      const s = this.state;
      if (s.phase === KICKOFF && isOT(s) && s.otFirst === -1 && s.clock === this.engine.periodLength(s)) s.kickTeam = this.rng.chance(0.5) ? 0 : 1;
      // opponent timeout before a snap (either side of the ball)
      if (s.phase === SNAP && s.running && this.policies[1].wantsTimeout(s, 1, this.rng)) {
        out.push(this.engine.step(s, { type: "timeout", team: 1 }, this.rng));
        continue;
      }
      const t = this.turn();
      if (t !== "none") break;
      const actor = s.phase === KICKOFF || s.phase === FREE_KICK ? s.kickTeam : s.poss;
      let a = this.policies[actor].choose(s, this.rng);
      if (a.type === "noop") break;
      if (a.type === "timeout" && (!s.running || s.tos[a.team] <= 0)) a = s.running ? { type: "spike" } : this.policies[actor].choose(s, this.rng);
      out.push(this.engine.step(s, a, this.rng));
    }
    this.log.push(...out);
    return out;
  }

  private requestGrade(d: Decision): void {
    if (!this.pool) return;
    this.pool.grade(d.before, this.ctx, d.action, d.seed, 0, this.shifts, {
      priority: 1,
      onProgress: (done, total) => this.onProgress?.(d, done, total),
    }).then((g) => { d.grade = g; this.onGrade?.(d); }).catch((e) => console.error("grade failed", e));
  }
  regrade(d: Decision): void { this.requestGrade(d); }
  get gradesPending(): boolean { return this.decisions.some((d) => d.grade === null); }

  finish(): Summary {
    const graded = this.decisions.filter((d) => d.grade !== null).map((d) => d.grade!);
    const pr = percentile(graded, this.data, hashStr(`${this.spot.id}:pct`));
    const [traits, counts] = playerTraits(this.decisions.map((d) => [d.before, d.action]), this.policies[0]);
    const coach = nearestCoach(traits, counts, this.coaches);
    const s = this.state;
    const q2 = this.spot.state.qtr === 2;
    let mine: number, real: number, resultText: string, vsCoach: "W" | "L" | "T";
    if (q2) {
      mine = this.pointsOnFirstPossession();
      real = this.spot.real.points;
      resultText = `${mine >= 0 ? "+" : ""}${mine} on the drive`;
      vsCoach = mine > real ? "W" : mine < real ? "L" : "T";
    } else {
      mine = s.score[0] > s.score[1] ? 1 : s.score[0] < s.score[1] ? 0 : 0.5;
      real = this.spot.real.outcome === "win" ? 1 : this.spot.real.outcome === "loss" ? 0 : 0.5;
      resultText = mine === 1 ? `Won ${s.score[0]}-${s.score[1]}` : mine === 0 ? `Lost ${s.score[0]}-${s.score[1]}` : `Tied ${s.score[0]}-${s.score[1]}`;
      vsCoach = mine > real ? "W" : mine < real ? "L" : "T";
    }
    const squares = this.decisions.map((d) => (d.grade ? d.grade.color : "none"));
    this.summary = { percentile: pr.percentile, cost: pr.cost, hist: pr.hist, coach: coach.coach, reasons: coach.reasons, traits, resultText, vsCoach, mine, real, squares,
      costliest: [...this.decisions].filter((d) => d.grade).sort((a, b) => b.grade!.gap - a.grade!.gap).slice(0, 3).map((d) => ({ idx: d.idx, gap: d.grade!.gap, call: labelOf(d.action), better: d.grade!.better })) };
    return this.summary;
  }

  private pointsOnFirstPossession(): number {
    // points scored by team 0 (minus points given up) during its first possession of the spot
    const start = this.spot.state.score;
    let i = 0;
    for (; i < this.log.length; i++) {
      const e = this.log[i];
      if (e.turnover || e.kind === "punt" || e.kind === "period" || (e.kind === "fg")) { i++; break; }
      if (e.td) { i++; break; }
    }
    const e = this.log[Math.min(i, this.log.length) - 1] ?? this.log[this.log.length - 1];
    if (!e) return 0;
    // the event score is the pre-event score; use the state after the possession
    const after = i < this.log.length ? this.log[i].score : this.state.score;
    return after[0] - start[0] - (after[1] - start[1]);
  }
}

export interface Summary {
  percentile: number; cost: number; hist: number[]; coach: string | null; reasons: string[]; traits: Record<string, number>;
  resultText: string; vsCoach: "W" | "L" | "T"; mine: number; real: number; squares: string[];
  costliest: { idx: number; gap: number; call: string; better: string | null }[];
}

export function labelOf(a: Action): string {
  if (a.type === "play") return a.call.replace(/_/g, " ");
  if (a.type === "look") return `${a.box} box, ${a.blitz ? "blitz" : "no blitz"}`;
  return a.type.replace(/_/g, " ");
}
