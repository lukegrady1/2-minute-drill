import { fetchBin, makeEngineData, makePlaybook, type EngineData, type EngineJson } from "@engine/data";
import type { Coaches } from "@engine/grading";
import type { Spot } from "@engine/simulate";

export interface CallDef { id: string; label: string; family: string; depth?: string; dirs?: string[]; gadget?: boolean }
export interface GameJson {
  name: string; launch: string; disclaimer: string;
  categories: { id: string; label: string; blurb: string }[];
  calls: CallDef[];
  spots: (Spot & { chunk: number })[];
  schedule: { day: number; scored: string; spots: Record<string, string> }[];
  featured: Record<string, { title: string; story: string }>;
  coaches: Coaches;
}
export interface Player { id: string; name: string; pos: string; grp: string; num: number | null; rating: number }
export interface SideFile { team: string; coach: string | null; players: Player[]; k: Player | null; p: Player | null; shift: Record<string, number>; personnel?: string | null; formation?: string | null }
export interface SpotFile { off: SideFile; def: SideFile }

export const BASE = `${import.meta.env.BASE_URL}data/`;
let version = "dev";
export const v = (file: string) => `${BASE}${file}?v=${version}`;

export async function loadBuild(): Promise<string> {
  try { version = ((await (await fetch(`${BASE}build.json?t=${Date.now()}`)).json()) as { build: string }).build; } catch { version = "dev"; }
  return version;
}
export const loadGame = async (): Promise<GameJson> => (await fetch(v("game.json"))).json();

export interface Loaded { engineJson: EngineJson; playbook: ArrayBuffer; data: EngineData }
export async function loadEngine(onProgress: (frac: number) => void): Promise<Loaded> {
  const engineJson = (await (await fetch(v("engine_data.json"))).json()) as EngineJson;
  onProgress(0.1);
  const playbook = await fetchBin(v("playbook.bin"), (loaded) => onProgress(0.1 + 0.9 * Math.min(1, loaded / 620000)));
  const data = makeEngineData(engineJson, makePlaybook(playbook));
  onProgress(1);
  return { engineJson, playbook, data };
}
export async function loadHints(): Promise<Record<string, Int8Array | Int16Array>> {
  const { decodeBin } = await import("@engine/data");
  return decodeBin(await fetchBin(v("hints.bin"))).cols;
}
const chunkCache = new Map<number, Promise<Record<string, SpotFile>>>();
export function loadSpotFile(spot: { id: string; chunk: number }): Promise<SpotFile> {
  if (!chunkCache.has(spot.chunk)) chunkCache.set(spot.chunk, fetch(v(`spots/s${String(spot.chunk).padStart(3, "0")}.json`)).then((r) => r.json()));
  return chunkCache.get(spot.chunk)!.then((c) => c[spot.id]);
}
