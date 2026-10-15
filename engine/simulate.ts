/** Play a game out with the auto-policy. Twin of sim/simulate.py. */
import type { EngineData } from "./data";
import { DONE, Engine, KICKOFF, SNAP, isOT, newState, type Ctx, type Event, type State, type Action } from "./engine";
import { Policy, coinTossKicker } from "./policy";
import { Rng } from "./rng";

export const MAX_STEPS = 400;

export function playOut(engine: Engine, s: State, rng: Rng, policies: [Policy, Policy], log: Event[] | null = null): number {
  let steps = 0;
  while (s.phase !== DONE && steps < MAX_STEPS) {
    steps += 1;
    if (s.phase === KICKOFF && isOT(s) && s.otFirst === -1 && s.plays >= 0 && s.clock === engine.periodLength(s)) s.kickTeam = coinTossKicker(rng);
    if (s.phase === SNAP && s.running) {
      for (const team of [1 - s.poss, s.poss]) {
        if (policies[team].wantsTimeout(s, team, rng)) {
          const e = engine.step(s, { type: "timeout", team }, rng);
          if (log) log.push(e);
          break;
        }
      }
    }
    const actor = s.phase !== KICKOFF && s.phase !== "free_kick" ? s.poss : s.kickTeam;
    let action: Action = policies[actor].choose(s, rng);
    if (action.type === "noop") break;
    if (action.type === "timeout" && (!s.running || s.tos[action.team] <= 0)) action = s.running ? { type: "spike" } : policies[actor].choose(s, rng);
    const e = engine.step(s, action, rng);
    if (log) log.push(e);
  }
  return engine.value(s);
}

export interface Spot {
  id: string; cat: string; season: number; week: number; playoff: boolean; game: string; play_id: number;
  off: string; def: string; home: string; away: string;
  state: { qtr: number; clock: number; down: number; togo: number; yl: number; score: [number, number]; tos: [number, number]; recv2h: boolean };
  ctx: { spread: number | null; roof: string | null; temp: number | null; wind: number | null; surface: string | null; coach: string | null; def_coach: string | null; date: string | null };
  real: { calls: string[]; n: number; result: string | null; points: number; outcome: string; final_margin: number | null };
  wp0: number | null; lineup: boolean;
}

export function stateFromSpot(spot: Spot): [State, Ctx] {
  const st = spot.state;
  const s = newState({ qtr: st.qtr, clock: st.clock, running: false, poss: 0, down: st.down, togo: st.togo, yl: st.yl,
    score: [st.score[0], st.score[1]], tos: [st.tos[0], st.tos[1]], phase: SNAP, warned: st.clock <= 120, recv2h: st.recv2h ? 0 : 1 });
  const roof = spot.ctx?.roof ?? "";
  const ctx: Ctx = { spread: Number(spot.ctx?.spread ?? 0), indoor: roof === "dome" || roof === "closed", wind: Number(spot.ctx?.wind ?? 0),
    temp: Number(spot.ctx?.temp ?? 60), playoff: !!spot.playoff, endAtHalf: st.qtr === 2 };
  return [s, ctx];
}

export function simulateSpot(data: EngineData, spot: Spot, n: number, seed: number): number {
  const [s0, ctx] = stateFromSpot(spot);
  const engine = new Engine(data, ctx);
  const pol: [Policy, Policy] = [new Policy(data), new Policy(data)];
  const rng = new Rng(seed);
  let total = 0;
  for (let i = 0; i < n; i++) {
    const s = { ...s0, score: [s0.score[0], s0.score[1]] as [number, number], tos: [s0.tos[0], s0.tos[1]] as [number, number], otDone: [false, false] as [boolean, boolean] };
    total += playOut(engine, s, rng.fork(), pol);
  }
  return total / n;
}
