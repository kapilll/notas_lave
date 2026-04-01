/**
 * API client for the Python trading engine.
 *
 * The engine runs on localhost:8000 (FastAPI).
 * This file provides typed functions to call each endpoint.
 */

const ENGINE_URL =
  process.env.NEXT_PUBLIC_ENGINE_URL ||
  (typeof window !== "undefined"
    ? `http://${window.location.hostname}:8000`
    : "http://localhost:8000");

export interface PriceData {
  price: number | null;
  symbol: string;
  timestamp: string;
}

export interface SignalData {
  strategy: string;
  direction: "LONG" | "SHORT" | null;
  strength: "STRONG" | "MODERATE" | "WEAK" | "NONE";
  score: number;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  reason: string;
  metadata: Record<string, unknown>;
}

export interface RiskStatus {
  balance: number;
  total_pnl: number;
  total_pnl_pct: number;
  daily_pnl: number;
  daily_drawdown_used_pct: number;
  total_drawdown_used_pct: number;
  trades_today: number;
  open_positions: number;
  is_halted: boolean;
  can_trade: boolean;
}

export async function fetchPrices(): Promise<Record<string, PriceData>> {
  const res = await fetch(`${ENGINE_URL}/api/prices`);
  const data = await res.json();
  return data.prices;
}

export async function fetchRiskStatus(): Promise<RiskStatus> {
  const res = await fetch(`${ENGINE_URL}/api/risk/status`);
  return res.json();
}
