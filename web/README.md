# Covenant Watch web

Next.js (App Router, TypeScript) frontend over the read-only API in `api/main.py`.

## Run

```sh
# 1. API (repo root)
uv run uvicorn api.main:app --port 8000

# 2. Web (this folder)
cd web
npm install
npm run dev          # http://localhost:3000
# or a production build
npm run build && npm start
```

## Config

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | API base URL (browser and server; inlined at build time) |
| `API_URL` | unset | Server-only runtime override of the API URL |

## Routes

- `/` landing page
- `/dashboard` covenant overview across every company: status mix over time, closest to breach, accuracy and early-warning KPIs, events, refusals
- `/companies` company search (`?q=`) with covenant status chips and current headroom
- `/company/[cik]` covenant overview, headroom timeline, threshold schedule, quarter table, refusals; `?cov=<id>&q=<period_end>` deep-links a covenant and opens the provenance drawer
- `/eval` eval report, rendered generically (unknown keys are shown, missing ones say so)

Responses with `"source": "fixture"` or `"demo"` show a small "Example data" or "Demo data" label next to the title; real pipeline data has no label. If the API is down, every page shows how to start it.

No UI kit or chart library: charts are hand-rolled SVG in `components/Timeline.tsx`, `components/CovenantBento.tsx` and `components/ui/finance-bento.tsx`.
