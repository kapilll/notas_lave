# Notas Lave

AI-powered trading decision engine for scalping Gold, Silver, BTC, and ETH. Uses multiple composite strategies competing in a strategy arena, with AI-driven trade analysis and risk management.

## Architecture

```
Market Data (CCXT / TwelveData)
  → 6 Composite Strategies (trend momentum, mean reversion, level confluence, breakout, williams, order flow)
  → Strategy Arena (best proposal wins, trust scores evolve)
  → Risk Manager (validate)
  → Broker (execute)
  → Journal + EventStore (record)
  → Telegram alerts
```

**Engine** — Python/FastAPI backend that runs strategies, manages risk, and executes trades via Delta Exchange.

**Dashboard** — Next.js frontend showing live positions, P&L, strategy leaderboard, and trade journal.

## Prerequisites

- Python 3.11+
- Node.js 20+
- Docker (optional, for containerized setup)

## Local Setup

### 1. Clone

```bash
git clone https://github.com/kapilll/notas_lave.git
cd notas_lave
```

### 2. Engine (Python backend)

```bash
cd engine

python3 -m venv .venv
source .venv/bin/activate

pip install -e .          # production deps
pip install -e ".[dev]"   # add test/dev deps

cp .env.example .env
# Edit .env with your API keys (see Environment Variables below)

python run.py
# API available at http://localhost:8000
```

### 3. Dashboard (Next.js frontend)

```bash
cd dashboard

npm install
npm run dev
# Dashboard available at http://localhost:3000
```

The dashboard connects to the engine at `http://localhost:8000` by default.

### 4. Docker (both services)

```bash
# Create engine/.env first (see step 2)

docker compose up -d
# Engine: http://localhost:8000
# Dashboard: http://localhost:3000
```

## Environment Variables

Copy `engine/.env.example` to `engine/.env` and fill in:

| Variable | Required | Description |
|----------|----------|-------------|
| `CLAUDE_PROVIDER` | Yes | `vertex` (via GCP) or `anthropic` (direct API) |
| `GOOGLE_CLOUD_PROJECT` | If vertex | GCP project ID |
| `GOOGLE_CLOUD_REGION` | If vertex | GCP region |
| `ANTHROPIC_API_KEY` | If anthropic | Direct Anthropic API key |
| `TWELVEDATA_API_KEY` | Yes | For real-time Gold/Silver spot data. Free tier at [twelvedata.com](https://twelvedata.com) |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token for trade alerts |
| `TELEGRAM_CHAT_ID` | No | Telegram chat ID for alerts |
| `BROKER` | No | Broker to use (default: `delta_testnet`) |
| `INITIAL_BALANCE` | No | Fallback balance if broker not connected (default: `100000`) |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Version and status |
| `GET /api/system/health` | Full component health check |
| `GET /api/broker/status` | Balance and positions |
| `GET /api/risk/status` | P&L, drawdown, capacity |
| `GET /api/lab/status` | Engine state |
| `GET /api/lab/positions` | Open positions with strategy/SL/TP |
| `GET /api/journal/trades` | Trade history |
| `GET /api/journal/performance` | Performance metrics |
| `WS /ws` | Live data stream |

## Running Tests

```bash
cd engine
source .venv/bin/activate

pytest                     # all tests
pytest -m unit             # fast isolated tests
pytest -m integration      # broker integration tests
pytest --cov               # with coverage report
```

## Tech Stack

- **Engine:** Python 3.11+, FastAPI, SQLAlchemy (SQLite), Anthropic AI, CCXT, Pandas, TwelveData
- **Dashboard:** Next.js 16, React 19, Tailwind CSS, Lightweight Charts
- **Infra:** Docker Compose, Cloudflare Tunnel (optional)
