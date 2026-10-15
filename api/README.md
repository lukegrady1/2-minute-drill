# api/

Cloudflare Worker + D1 for the Survivor leaderboard (`/board`) and daily scores (`/daily`).

```
cd api
npx wrangler d1 create final-drive            # paste the id into wrangler.toml
npx wrangler d1 execute final-drive --file schema.sql
npx wrangler deploy
```
Set `ALLOWED_ORIGIN` in wrangler.toml to the site's origin, and `VITE_API_BASE` (the Worker URL) when
building the site. Add a Cloudflare rate-limit rule on `/daily` and `/board` (e.g. 10 req/min per IP).
