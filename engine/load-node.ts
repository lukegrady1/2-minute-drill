/** Node-side loader for tests and the parity harness. */
import { gunzipSync } from "node:zlib";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { makeEngineData, makePlaybook, type EngineData, type EngineJson } from "./data";

export const DATA_DIR = fileURLToPath(new URL("../web/public/data/", import.meta.url));

export function loadNode(): EngineData {
  const eng = JSON.parse(readFileSync(DATA_DIR + "engine_data.json", "utf8")) as EngineJson;
  const gz = readFileSync(DATA_DIR + "playbook.bin");
  const raw = gunzipSync(gz);
  const buf = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength) as ArrayBuffer;
  return makeEngineData(eng, makePlaybook(buf));
}
export function loadGameNode(): { spots: import("./simulate").Spot[]; coaches: import("./grading").Coaches; [k: string]: unknown } {
  return JSON.parse(readFileSync(DATA_DIR + "game.json", "utf8"));
}
