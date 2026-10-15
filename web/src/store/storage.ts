/** localStorage under one versioned key. Every call is wrapped; failures fall back to memory. */
const KEY = "fd:v1";
let mem: Store | null = null;

export interface DriveSave {
  spotId: string; status: "playing" | "done"; seed: number; actions: unknown[]; grades: unknown[];
  percentile?: number; result?: string; coach?: string; summary?: unknown; startedAt: number;
}
export interface Store {
  progress: Record<string, Record<string, DriveSave>>;  // date -> spotId -> save
  stats: { played: number; streak: number; lastDay: string | null; best: number; hist: number[]; wlt: [number, number, number] };
  survivor: { best: number; run: { seed: number; index: number; wins: number; alive: boolean; current?: DriveSave } | null };
  name: string; key: string; seenHelp: boolean;
}
const fresh = (): Store => ({ progress: {}, stats: { played: 0, streak: 0, lastDay: null, best: 0, hist: new Array(10).fill(0), wlt: [0, 0, 0] },
  survivor: { best: 0, run: null }, name: "", key: Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2), seenHelp: false });

export function load(): Store {
  if (mem) return mem;
  try {
    const raw = localStorage.getItem(KEY);
    mem = raw ? { ...fresh(), ...(JSON.parse(raw) as Store) } : fresh();
  } catch { mem = fresh(); }
  return mem;
}
export function save(): void {
  if (!mem) return;
  try { localStorage.setItem(KEY, JSON.stringify(mem)); } catch { /* storage full or blocked */ }
}
export function update(fn: (s: Store) => void): void { fn(load()); save(); }
