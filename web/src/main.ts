import { WorkerPool } from "@engine/pool";
import { loadBuild, loadEngine, loadGame, loadHints, BASE } from "./data";
import { App } from "./ui/app";
import { el } from "./util";

async function boot(): Promise<void> {
  const root = document.getElementById("app")!;
  root.innerHTML = `<div class="hdr"><div></div><h1>Final Drive</h1><div></div></div><div class="card"><div>Loading plays and models…</div><div class="progress"><i id="prog"></i></div><div class="muted" id="prog-txt">0%</div></div>`;
  const prog = (f: number) => { const p = document.getElementById("prog"); if (p) p.style.width = `${Math.round(100 * f)}%`; const t = document.getElementById("prog-txt"); if (t) t.textContent = `${Math.round(100 * f)}%`; };
  const build = await loadBuild();
  document.querySelector('meta[name="build"]')?.setAttribute("content", build);
  const base = `${BASE}`;
  const pool = new WorkerPool(() => new Worker(new URL("../../engine/worker.ts", import.meta.url), { type: "module" }), WorkerPool.recommendedSize());
  const firstWorker = pool.start(base).catch((e) => console.error("worker init failed", e));
  const [game, loaded] = await Promise.all([loadGame(), loadEngine(prog)]);
  const app = new App({ game, data: loaded.data, pool, hints: null });
  // the rest of the workers get copies once the main thread has the data; hints load in the background
  firstWorker.then(() => pool.shareData(loaded.engineJson, loaded.playbook)).catch((e) => console.error(e));
  loadHints().then((h) => { app.deps.hints = h; }).catch(() => {});
  (window as unknown as { app: App }).app = app;
}
boot().catch((e) => { document.getElementById("app")!.appendChild(el(`<div class="card">Failed to load: ${String(e)}</div>`)); console.error(e); });
