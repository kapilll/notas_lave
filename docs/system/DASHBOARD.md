# Dashboard (Frontend)

> Last verified against code: v1.7.13 (2026-03-29)

## Overview

Next.js 15 (App Router) dashboard at port 3000. Connects to engine API at same hostname, port 8000.

## Tech Stack

- **Framework:** Next.js 15, React Server Components
- **Styling:** TailwindCSS + PostCSS
- **Charting:** CandlestickChart component (custom)
- **Language:** TypeScript
- **Package manager:** npm

## Structure

```
dashboard/
├── app/
│   ├── layout.tsx       # Root layout
│   ├── page.tsx         # Main dashboard page
│   ├── globals.css      # TailwindCSS
│   └── favicon.ico
├── components/
│   └── CandlestickChart.tsx
├── lib/
│   ├── api.ts           # API client (fetch from engine)
│   └── strategy-info.ts # Strategy metadata for display
├── next.config.ts
├── package.json
├── tsconfig.json
├── postcss.config.mjs
└── eslint.config.mjs
```

## Engine Connection

```typescript
// lib/api.ts
// Auto-detects engine URL from browser hostname
const ENGINE_URL = `http://${window.location.hostname}:8000`
```

No build-time env var needed. Works on localhost and GCP VM.

## Build & Deploy

```bash
# Local dev
cd dashboard && npm run dev    # :3000 with hot reload

# Production build (on VM)
cd dashboard && npm install --silent && npm run build
# Served by systemd notas-dashboard.service via `next start`
```

## Rules

- **No build-time environment variables** for engine URL — auto-detect from hostname.
- **Dashboard is rebuilt on every deploy** — `npm run build` runs on VM.
- **CORS is `allow_origins=["*"]`** on engine side (TODO: lock down).
- **No SSR for engine data** — all engine calls are client-side fetches.
