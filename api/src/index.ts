/** Cloudflare Worker: GET/POST /board (Survivor best runs), GET/POST /daily (today's percentiles).
 * POSTs are text/plain JSON so browsers skip the CORS preflight. Only ALLOWED_ORIGIN may call. */
export interface Env { DB: D1Database; ALLOWED_ORIGIN: string }

const BAD = ["fuck", "shit", "cunt", "nigg", "fag", "bitch", "ass", "dick", "cock", "pussy", "slut", "whore", "nazi", "rape"];
const cleanName = (n: unknown): string => {
  let s = String(n ?? "").replace(/[^\w .'-]/g, "").trim().slice(0, 16);
  if (BAD.some((b) => s.toLowerCase().includes(b))) s = "";
  return s;
};
const slug = (n: string) => n.toLowerCase().replace(/[^a-z0-9]/g, "");
async function sha(s: string): Promise<string> {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
}
const json = (data: unknown, origin: string, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json", "access-control-allow-origin": origin, "cache-control": "no-store" } });

const dayKey = (d: Date) => `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
function dateOk(date: string): boolean {
  // today or yesterday in any timezone: accept a +-1 day window around UTC today
  const now = new Date();
  const days = [-2, -1, 0, 1].map((k) => dayKey(new Date(now.getTime() + k * 86400000)));
  return /^\d{4}-\d{2}-\d{2}$/.test(date) && days.includes(date);
}

async function dailySummary(env: Env, date: string, myScore: number | null, origin: string): Promise<Response> {
  const rows = (await env.DB.prepare("SELECT name, score FROM daily WHERE date = ? ORDER BY score DESC LIMIT 5000").bind(date).all<{ name: string; score: number }>()).results;
  const n = rows.length;
  const histogram = new Array(10).fill(0);
  for (const r of rows) histogram[Math.min(9, Math.floor(r.score / 10))] += 1;
  const rank = myScore === null ? null : 1 + rows.filter((r) => r.score > myScore).length;
  const top = rows.slice(0, 10).map((r) => ({ name: r.name || "anon", score: Math.round(r.score) }));
  return json({ rank, n, histogram, spotAvgs: {}, top }, origin);
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const origin = env.ALLOWED_ORIGIN || "*";
    if (req.method === "OPTIONS") return new Response(null, { headers: { "access-control-allow-origin": origin, "access-control-allow-methods": "GET,POST", "access-control-allow-headers": "content-type" } });
    const reqOrigin = req.headers.get("origin");
    if (req.method === "POST" && env.ALLOWED_ORIGIN && reqOrigin && reqOrigin !== env.ALLOWED_ORIGIN) return json({ error: "origin" }, origin, 403);
    try {
      if (url.pathname === "/board" && req.method === "GET") {
        const rows = (await env.DB.prepare("SELECT name, best, at FROM board ORDER BY best DESC, at ASC LIMIT 50").all()).results;
        return json({ rows }, origin);
      }
      if (url.pathname === "/board" && req.method === "POST") {
        const b = JSON.parse(await req.text()) as { name?: string; key?: string; best?: number };
        const name = cleanName(b.name);
        const best = Number(b.best);
        if (!name || !b.key || !Number.isFinite(best) || best < 0 || best > 500) return json({ error: "bad" }, origin, 400);
        const keyHash = await sha(String(b.key));
        const s = slug(name);
        const existing = await env.DB.prepare("SELECT key_hash, best FROM board WHERE slug = ?").bind(s).first<{ key_hash: string; best: number }>();
        let taken = false;
        if (existing && existing.key_hash !== keyHash) taken = true;
        else if (!existing || best > existing.best) {
          await env.DB.prepare("INSERT INTO board (slug, name, key_hash, best, at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(slug) DO UPDATE SET best = excluded.best, at = excluded.at")
            .bind(s, name, keyHash, Math.round(best), Date.now()).run();
        }
        const rows = (await env.DB.prepare("SELECT name, best, at FROM board ORDER BY best DESC, at ASC LIMIT 50").all()).results;
        return json({ rows, taken }, origin);
      }
      if (url.pathname === "/daily" && req.method === "GET") {
        const date = url.searchParams.get("date") ?? dayKey(new Date());
        if (!dateOk(date)) return json({ error: "date" }, origin, 400);
        return dailySummary(env, date, null, origin);
      }
      if (url.pathname === "/daily" && req.method === "POST") {
        const b = JSON.parse(await req.text()) as { date?: string; key?: string; name?: string; score?: number; spots?: string[] };
        const score = Number(b.score);
        if (!b.date || !dateOk(b.date) || !b.key || !Number.isFinite(score) || score < 0 || score > 100) return json({ error: "bad" }, origin, 400);
        const keyHash = await sha(String(b.key));
        // only the first result per key per date counts
        await env.DB.prepare("INSERT OR IGNORE INTO daily (date, key_hash, name, score, spots, at) VALUES (?, ?, ?, ?, ?, ?)")
          .bind(b.date, keyHash, cleanName(b.name), score, JSON.stringify((b.spots ?? []).slice(0, 3)), Date.now()).run();
        const mine = await env.DB.prepare("SELECT score FROM daily WHERE date = ? AND key_hash = ?").bind(b.date, keyHash).first<{ score: number }>();
        return dailySummary(env, b.date, mine?.score ?? score, origin);
      }
      return json({ error: "not found" }, origin, 404);
    } catch (e) {
      return json({ error: String((e as Error).message) }, origin, 500);
    }
  },
};
