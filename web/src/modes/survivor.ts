import type { GameJson } from "../data";
import { Rng } from "@engine/rng";
import { hashStr } from "../util";

/** A deterministic shuffle of all Q4 spots for a run seed; index walks through it without repeats. */
export function survivorOrder(game: GameJson, seed: number): string[] {
  const ids = game.spots.filter((s) => s.state.qtr === 4).map((s) => s.id);
  const rng = new Rng(seed);
  for (let i = ids.length - 1; i > 0; i--) { const j = rng.below(i + 1); [ids[i], ids[j]] = [ids[j], ids[i]]; }
  return ids;
}
export const survivorSeed = (runSeed: number, index: number) => hashStr(`survivor:${runSeed}:${index}`);
