/** Leaderboard + daily score API (Cloudflare Worker in api/) and GA4 events. Both are optional. */
declare const __API_BASE__: string | undefined;
const API = (typeof __API_BASE__ === "string" && __API_BASE__) || (import.meta.env.VITE_API_BASE as string | undefined) || "";
const GA_ID = (import.meta.env.VITE_GA_ID as string | undefined) || "";

export interface DailyResult { rank: number; n: number; histogram: number[]; spotAvgs: Record<string, number>; top: { name: string; score: number }[] }
export interface BoardRow { name: string; best: number; at: number }

async function post<T>(path: string, body: unknown): Promise<T | null> {
  if (!API) return null;
  try {
    // text/plain keeps the request CORS-simple (no preflight)
    const r = await fetch(API + path, { method: "POST", headers: { "content-type": "text/plain" }, body: JSON.stringify(body) });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch { return null; }
}
export const postDaily = (b: { date: string; key: string; name?: string; score: number; spots: string[] }) => post<DailyResult>("/daily", b);
export const getDaily = async (date: string): Promise<DailyResult | null> => { if (!API) return null; try { return await (await fetch(`${API}/daily?date=${date}`)).json(); } catch { return null; } };
export const postBoard = (b: { name: string; key: string; best: number }) => post<{ rows: BoardRow[]; taken: boolean }>("/board", b);
export const getBoard = async (): Promise<{ rows: BoardRow[] } | null> => { if (!API) return null; try { return await (await fetch(`${API}/board`)).json(); } catch { return null; } };

type GtagFn = (...args: unknown[]) => void;
export function track(event: string, params: Record<string, unknown> = {}): void {
  const w = window as unknown as { gtag?: GtagFn; dataLayer?: unknown[] };
  if (!GA_ID) return;
  if (!w.gtag) {
    w.dataLayer = w.dataLayer || [];
    w.gtag = function () { w.dataLayer!.push(arguments); } as GtagFn;
    const s = document.createElement("script"); s.async = true; s.src = `https://www.googletagmanager.com/gtag/js?id=${GA_ID}`; document.head.appendChild(s);
    w.gtag("js", new Date()); w.gtag("config", GA_ID, { anonymize_ip: true });
  }
  w.gtag("event", event, params);
}
