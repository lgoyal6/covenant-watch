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
| `NEXT_PUBLIC_DEMO_CIK` | first company | Demo company for `/demo` (see `lib/demo.ts`) |
| `NEXT_PUBLIC_DEMO_COVENANT`, `NEXT_PUBLIC_DEMO_PERIOD` | auto | Pin the demo covenant id and quarter (`YYYY-MM-DD`) |

## Routes

- `/` company search (`?q=`) with covenant status chips and current headroom
- `/company/[cik]` covenant cards, headroom timeline, quarter table, refusals; `?cov=<id>&q=<period_end>` deep-links a covenant and opens the provenance drawer
- `/eval` eval report, rendered generically (unknown keys are shown, missing ones say so)
- `/demo` pinned five-step walkthrough (docs/PLAN.md section 9); `?step=1..5`, arrow keys move between steps

Any response with `"source": "fixture"` shows a FIXTURE DATA banner and badges. If the API is down, every page shows how to start it.

No UI kit or chart library: charts are hand-rolled SVG in `components/Timeline.tsx`.
