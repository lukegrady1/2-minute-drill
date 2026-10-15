import type { GameJson } from "../data";
import { daysBetween, hashStr, todayKey } from "../util";

export function dayNumber(game: GameJson, date = todayKey()): number {
  return Math.max(0, daysBetween(game.launch, date));
}
export function todaysSpots(game: GameJson, date = todayKey()) {
  const day = dayNumber(game, date);
  const sched = game.schedule[day % game.schedule.length];
  const byId = new Map(game.spots.map((s) => [s.id, s]));
  return { day, scored: sched.scored, spots: game.categories.map((c) => ({ cat: c, spot: byId.get(sched.spots[c.id])!, scored: sched.scored === c.id })) };
}
export const dailySeed = (spotId: string, date: string) => hashStr(`daily:${spotId}:${date}`);
