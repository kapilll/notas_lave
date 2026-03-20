/**
 * API client for the Python trading engine.
 *
 * The engine runs on localhost:8000 (FastAPI).
 * This file provides typed functions to call each endpoint.
 */

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8000";

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

export interface ScanResult {
  symbol: string;
  timeframe: string;
  regime: string;
  composite_score: number;
  direction: "LONG" | "SHORT" | null;
  agreeing_strategies: number;
  total_strategies: number;
  signals: SignalData[];
  current_price: number | null;
  timestamp: string;
}

export interface ScanOverview {
  symbol: string;
  price: number;
  regime: string;
  score: number;
  direction: "LONG" | "SHORT" | null;
  agreeing: number;
  total: number;
  top_signal: string;
  error?: string;
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

export async function scanSymbol(
  symbol: string,
  timeframe: string = "5m"
): Promise<ScanResult> {
  const res = await fetch(
    `${ENGINE_URL}/api/scan/${symbol}?timeframe=${timeframe}`
  );
  return res.json();
}

export async function scanAll(
  timeframe: string = "5m"
): Promise<ScanOverview[]> {
  const res = await fetch(
    `${ENGINE_URL}/api/scan/all?timeframe=${timeframe}`
  );
  const data = await res.json();
  return data.results;
}

export async function fetchRiskStatus(): Promise<RiskStatus> {
  const res = await fetch(`${ENGINE_URL}/api/risk/status`);
  return res.json();
}
