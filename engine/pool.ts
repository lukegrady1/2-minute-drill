/** Worker pool: min(3, cores-1) on desktop, 2 on phones. One starts immediately, the rest after the
 * main thread has its data. Grading jobs are queued FIFO; a job can be prioritised. */
import type { Action, Ctx, State } from "./engine";
import type { Grade } from "./grading";
import type { Shift } from "./policy";
import type { WorkerRequest, WorkerResponse } from "./worker";

interface Job {
  id: number; req: WorkerRequest; resolve: (g: Grade) => void; reject: (e: Error) => void;
  onProgress?: (done: number, total: number) => void; priority: number;
}

export class WorkerPool {
  private workers: { w: Worker; busy: boolean; ready: boolean }[] = [];
  private queue: Job[] = [];
  private inflight = new Map<number, Job>();
  private nextId = 1;
  private base = "";
  private engineJson: unknown = null;
  private playbook: ArrayBuffer | null = null;

  constructor(private makeWorker: () => Worker, public size: number) {}

  static recommendedSize(): number {
    const cores = typeof navigator !== "undefined" ? navigator.hardwareConcurrency || 2 : 2;
    const phone = typeof navigator !== "undefined" && /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent);
    return phone ? 2 : Math.max(1, Math.min(3, cores - 1));
  }

  /** Start the first worker now with URLs; call `shareData` later to start the rest with copies. */
  async start(base: string): Promise<void> {
    this.base = base;
    await this.spawn({ type: "init", base, id: 0 } as WorkerRequest);
  }
  async shareData(engineJson: unknown, playbook: ArrayBuffer): Promise<void> {
    this.engineJson = engineJson;
    this.playbook = playbook;
    const todo = this.size - this.workers.length;
    await Promise.all(Array.from({ length: todo }, () => this.spawn({ type: "init", base: this.base, engineJson: engineJson as never, playbook: playbook.slice(0), id: 0 })));
  }

  private spawn(init: WorkerRequest): Promise<void> {
    return new Promise((resolve, reject) => {
      const w = this.makeWorker();
      const entry = { w, busy: false, ready: false };
      this.workers.push(entry);
      w.onmessage = (ev: MessageEvent<WorkerResponse>) => {
        const m = ev.data;
        if (m.type === "ready") { entry.ready = true; resolve(); this.pump(); return; }
        const job = this.inflight.get(m.id);
        if (!job) return;
        if (m.type === "progress") job.onProgress?.(m.done, m.total);
        else if (m.type === "grade") { this.inflight.delete(m.id); entry.busy = false; job.resolve(m.grade); this.pump(); }
        else if (m.type === "error") { this.inflight.delete(m.id); entry.busy = false; job.reject(new Error(m.message)); this.pump(); }
      };
      w.onerror = (e) => { if (!entry.ready) reject(new Error(String(e.message))); };
      w.postMessage(init);
    });
  }

  grade(state: State, ctx: Ctx, chosen: Action, seed: number, team: number, shifts: [Shift, Shift],
    opts: { n1?: number; n2?: number; priority?: number; onProgress?: (d: number, t: number) => void } = {}): Promise<Grade> {
    const id = this.nextId++;
    const req: WorkerRequest = { id, type: "grade", state, ctx, chosen, seed, team, shifts, n1: opts.n1, n2: opts.n2 };
    return new Promise((resolve, reject) => {
      this.queue.push({ id, req, resolve, reject, onProgress: opts.onProgress, priority: opts.priority ?? 0 });
      this.queue.sort((a, b) => b.priority - a.priority || a.id - b.id);
      this.pump();
    });
  }

  private pump(): void {
    for (const entry of this.workers) {
      if (!entry.ready || entry.busy) continue;
      const job = this.queue.shift();
      if (!job) return;
      entry.busy = true;
      this.inflight.set(job.id, job);
      entry.w.postMessage(job.req);
    }
  }

  get pending(): number { return this.queue.length + this.inflight.size; }
  terminate(): void { for (const e of this.workers) e.w.terminate(); this.workers = []; }
}
