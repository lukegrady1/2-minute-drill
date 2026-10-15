/** Web Worker: loads the engine data once, then grades decisions and runs sims on request. */
import { fetchBin, makeEngineData, makePlaybook, type EngineData, type EngineJson } from "./data";
import { Engine, type Action, type Ctx, type State } from "./engine";
import { grade, type Grade } from "./grading";
import { Policy, type Shift } from "./policy";

export type WorkerRequest =
  | { id: number; type: "init"; base: string; engineJson?: EngineJson; playbook?: ArrayBuffer }
  | { id: number; type: "grade"; state: State; ctx: Ctx; chosen: Action; seed: number; team: number; shifts: [Shift, Shift]; n1?: number; n2?: number }
  | { id: number; type: "ping" };
export type WorkerResponse =
  | { id: number; type: "ready" }
  | { id: number; type: "progress"; done: number; total: number }
  | { id: number; type: "grade"; grade: Grade }
  | { id: number; type: "error"; message: string }
  | { id: number; type: "pong" };

let data: EngineData | null = null;
const post = (m: WorkerResponse) => (self as unknown as Worker).postMessage(m);

self.onmessage = async (ev: MessageEvent<WorkerRequest>) => {
  const msg = ev.data;
  try {
    if (msg.type === "init") {
      const eng = msg.engineJson ?? ((await (await fetch(msg.base + "engine_data.json")).json()) as EngineJson);
      const pb = msg.playbook ?? (await fetchBin(msg.base + "playbook.bin"));
      data = makeEngineData(eng, makePlaybook(pb));
      post({ id: msg.id, type: "ready" });
    } else if (msg.type === "grade") {
      if (!data) throw new Error("worker not initialised");
      const engine = new Engine(data, msg.ctx);
      const policies: [Policy, Policy] = [new Policy(data, msg.shifts[0]), new Policy(data, msg.shifts[1])];
      const g = grade(engine, msg.state, msg.chosen, msg.seed, {
        policies, team: msg.team, n1: msg.n1, n2: msg.n2,
        onProgress: (done, total) => post({ id: msg.id, type: "progress", done, total }),
      });
      post({ id: msg.id, type: "grade", grade: g });
    } else if (msg.type === "ping") post({ id: msg.id, type: "pong" });
  } catch (e) {
    post({ id: msg.id, type: "error", message: (e as Error).message });
  }
};
