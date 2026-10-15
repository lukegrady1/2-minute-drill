/** Types for the exported data and the binary playbook decoder (sim/data.py twin). */

export interface Hist { values: number[]; probs: number[]; n?: number }
export interface LogisticModel { coef: number[]; intercept: number; features?: string[] }
export interface PuntZone { from_min: number; from_max: number; next_yl: Hist; blocked: number; return_td: number }
export interface TendencyCell { n: number; p: Record<string, number> }

export interface EngineConfig {
  playbook: { min_bucket_size: number; light_box_max: number; blitz_min_rushers: number };
  grading: { round1_sims: number; round2_sims: number; round2_top_k: number; green_max_gap: number; yellow_max_gap: number };
  percentile: { virtual_callers: number; tau_log_uniform_min: number; tau_log_uniform_max: number; pure_league_frequency_share: number };
  clock: { play_clock_seconds: number; two_minute_warning_seconds: number; ob_stops_clock_inside_q2_seconds: number; ob_stops_clock_inside_q4_seconds: number };
  rules: { kickoff_touchback_yardline: number; overtime: { regular_season_minutes: number; playoff_minutes: number; regular_season_timeouts: number; playoff_timeouts: number; regular_season_can_tie: boolean } };
  workers: { desktop_max: number; phone_max: number };
  [k: string]: unknown;
}

export interface EngineJson {
  config: EngineConfig;
  wp: LogisticModel;
  fg: LogisticModel & { max_attempt_distance: number };
  pat: { xp: number; two_pt: number };
  kickoff: { start_yl: Hist; return_td: number; onside: { recovery: number; recover_yl: Hist; fail_yl: Hist }; safety_kick_start_yl: Hist };
  punt: { zones: PuntZone[] };
  clock: { duration: Record<string, Hist>; tempo: Record<string, Hist>; timeouts: { cells: Record<string, { p: number; n: number }>; min_n: number } };
  looks: { by_down_dist: Record<string, { p_light: number; p_blitz: number; n: number }>; overall: { p_light: number; p_blitz: number } };
  tendencies: { calls: string[]; cells: Record<string, TendencyCell>; direction: Record<string, Record<string, number>>; min_cell_n: number };
}

export type Cell = [start: number, len: number];
export type Level = "L0" | "L1" | "L2" | "L3";

export interface Playbook {
  n: number;
  cols: Record<string, Int8Array | Int16Array>;
  index: Record<Level, Record<string, Cell>>;
  codebooks: Record<string, string[]>;
  /** Most specific cell with >= minN rows. */
  cell(family: string, call: string, look: string, zone: string, minN: number): [number, number, Level];
}

export interface EngineData {
  cfg: EngineConfig;
  wp: LogisticModel;
  fg: EngineJson["fg"];
  pat: EngineJson["pat"];
  kickoff: EngineJson["kickoff"];
  punt: EngineJson["punt"];
  clock: EngineJson["clock"];
  looks: EngineJson["looks"];
  tendencies: EngineJson["tendencies"];
  playbook: Playbook;
}

interface BinHeader {
  n: number;
  columns: { name: string; dtype: string; offset: number; length: number }[];
  index?: Record<Level, Record<string, Cell>>;
  codebooks?: Record<string, string[]>;
}

/** Decode a (already gunzipped) .bin: u32 header length, JSON header, raw little-endian arrays. */
export function decodeBin(buf: ArrayBuffer): { header: BinHeader; cols: Record<string, Int8Array | Int16Array> } {
  const view = new DataView(buf);
  const hlen = view.getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hlen))) as BinHeader;
  const base = 4 + hlen;
  const cols: Record<string, Int8Array | Int16Array> = {};
  for (const c of header.columns) {
    const off = base + c.offset;
    if (c.dtype === "i1") cols[c.name] = new Int8Array(buf.slice(off, off + c.length));
    else if (c.dtype === "i2") cols[c.name] = new Int16Array(buf.slice(off, off + c.length * 2));
    else throw new Error("unknown dtype " + c.dtype);
  }
  return { header, cols };
}

export function makePlaybook(buf: ArrayBuffer): Playbook {
  const { header, cols } = decodeBin(buf);
  const index = header.index!;
  return {
    n: header.n,
    cols,
    index,
    codebooks: header.codebooks ?? {},
    cell(family, call, look, zone, minN) {
      const tries: [Level, string][] = [
        ["L3", `${family}|${call}|${look}|${zone}`],
        ["L2", `${family}|${call}|${look}`],
        ["L1", `${family}|${call}`],
        ["L0", family],
      ];
      for (const [lvl, key] of tries) {
        const c = index[lvl][key];
        if (c && c[1] >= minN) return [c[0], c[1], lvl];
      }
      const c = index.L0[family];
      if (!c) throw new Error("no rows for family " + family);
      return [c[0], c[1], "L0"];
    },
  };
}

export function makeEngineData(eng: EngineJson, playbook: Playbook): EngineData {
  return { cfg: eng.config, wp: eng.wp, fg: eng.fg, pat: eng.pat, kickoff: eng.kickoff, punt: eng.punt, clock: eng.clock,
    looks: eng.looks, tendencies: eng.tendencies, playbook };
}

/** Browser: fetch + gunzip via DecompressionStream. */
export async function fetchBin(url: string, onProgress?: (loaded: number) => void): Promise<ArrayBuffer> {
  const res = await fetch(url);
  if (!res.ok || !res.body) throw new Error(`fetch ${url}: ${res.status}`);
  let stream: ReadableStream<Uint8Array> = res.body;
  if (onProgress) {
    let loaded = 0;
    const counter = new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, ctrl) { loaded += chunk.byteLength; onProgress(loaded); ctrl.enqueue(chunk); },
    });
    stream = stream.pipeThrough(counter);
  }
  const ds = new DecompressionStream("gzip") as unknown as ReadableWritablePair<Uint8Array, Uint8Array>;
  return await new Response(stream.pipeThrough(ds)).arrayBuffer();
}
