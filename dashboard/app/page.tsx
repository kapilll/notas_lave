"use client";

import { useEffect, useState, useCallback } from "react";
import dynamic from "next/dynamic";
import type { ScanResult } from "@/lib/api";

// Dynamic import for the chart (uses window/document — can't render on server)
const CandlestickChart = dynamic(() => import("@/components/CandlestickChart"), { ssr: false });

const ENGINE = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8000";

// -- Types --

interface ScanOverview {
  symbol: string;
  price: number;
  regime: string;
  score: number;
  direction: "LONG" | "SHORT" | null;
  agreeing: number;
  total: number;
  top_signal: string;
}

interface RiskStatus {
  balance: number;
  total_pnl: number;
  daily_pnl: number;
  daily_drawdown_used_pct: number;
  total_drawdown_used_pct: number;
  trades_today: number;
  open_positions: number;
  is_halted: boolean;
  can_trade: boolean;
}

interface EvalResult {
  symbol: string;
  timeframe: string;
  confluence: { score: number; direction: string | null; regime: string; agreeing: number; total: number };
  claude_decision: {
    action: string;
    confidence: number;
    entry: number;
    stop_loss: number;
    take_profit: number;
    reasoning: string;
    risk_warnings: string[];
  };
  risk_check: { passed: boolean; rejections: string[] };
  current_price: number;
  should_trade: boolean;
}

// -- Helpers --

function dirColor(d: string | null) {
  if (d === "LONG" || d === "BUY") return "text-emerald-400";
  if (d === "SHORT" || d === "SELL") return "text-red-400";
  return "text-zinc-500";
}

function dirBg(d: string | null) {
  if (d === "LONG" || d === "BUY") return "bg-emerald-500/10 border-emerald-500/30";
  if (d === "SHORT" || d === "SELL") return "bg-red-500/10 border-red-500/30";
  return "bg-zinc-800 border-zinc-700";
}

function scoreCol(s: number) {
  if (s >= 7) return "text-emerald-400";
  if (s >= 5) return "text-yellow-400";
  return "text-zinc-500";
}

const regimeMap: Record<string, string> = {
  TRENDING: "Trending /", RANGING: "Ranging ~",
  VOLATILE: "Volatile !", QUIET: "Quiet -",
};

// -- Risk Panel --

function RiskPanel({ r }: { r: RiskStatus | null }) {
  if (!r) return null;
  const items = [
    { label: "Balance", value: `$${r.balance.toLocaleString()}`, color: "" },
    { label: "Daily P&L", value: `${r.daily_pnl >= 0 ? "+" : ""}$${r.daily_pnl.toFixed(2)}`, color: r.daily_pnl >= 0 ? "text-emerald-400" : "text-red-400" },
    { label: "Daily DD", value: `${r.daily_drawdown_used_pct}%`, color: r.daily_drawdown_used_pct > 60 ? "text-red-400" : r.daily_drawdown_used_pct > 30 ? "text-yellow-400" : "text-emerald-400" },
    { label: "Status", value: r.is_halted ? "HALTED" : r.can_trade ? "ACTIVE" : "LIMIT", color: r.can_trade ? "text-emerald-400" : "text-red-400" },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      {items.map((it) => (
        <div key={it.label} className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <div className="text-xs text-zinc-500 uppercase tracking-wider">{it.label}</div>
          <div className={`text-xl font-mono font-bold mt-1 ${it.color}`}>{it.value}</div>
        </div>
      ))}
    </div>
  );
}

// -- Market Card --

function MarketCard({ item, onSelect, selected }: { item: ScanOverview; onSelect: (s: string) => void; selected: boolean }) {
  return (
    <button onClick={() => onSelect(item.symbol)} className={`w-full text-left bg-zinc-900 border rounded-lg p-4 transition-all hover:border-zinc-600 ${selected ? "border-blue-500 ring-1 ring-blue-500/30" : "border-zinc-800"}`}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-bold">{item.symbol}</div>
          <div className="text-lg font-mono mt-0.5">${item.price?.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? "..."}</div>
        </div>
        <div className="text-right">
          <div className={`text-2xl font-mono font-bold ${scoreCol(item.score)}`}>{item.score.toFixed(1)}</div>
          <div className={`text-xs font-medium ${dirColor(item.direction)}`}>{item.direction || "NEUTRAL"}</div>
        </div>
      </div>
      <div className="flex items-center justify-between mt-3 text-xs text-zinc-500">
        <span>{regimeMap[item.regime] || item.regime}</span>
        <span>{item.agreeing}/{item.total} agree</span>
      </div>
    </button>
  );
}

// -- Claude Decision Panel --

function ClaudePanel({ evalData, loading, onEvaluate }: {
  evalData: EvalResult | null;
  loading: boolean;
  onEvaluate: () => void;
}) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">AI Decision</h3>
        <button
          onClick={onEvaluate}
          disabled={loading}
          className="px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white rounded-md transition-colors"
        >
          {loading ? "Evaluating..." : "Evaluate Trade"}
        </button>
      </div>

      {!evalData ? (
        <div className="text-sm text-zinc-500 text-center py-4">
          Select a market and click &quot;Evaluate Trade&quot; to get AI analysis
        </div>
      ) : (
        <div className="space-y-4">
          {/* Decision Header */}
          <div className={`border rounded-lg p-4 ${
            evalData.should_trade
              ? evalData.claude_decision.action === "BUY" ? "bg-emerald-500/10 border-emerald-500/40" : "bg-red-500/10 border-red-500/40"
              : "bg-zinc-800 border-zinc-700"
          }`}>
            <div className="flex items-center justify-between">
              <div>
                <div className={`text-2xl font-bold ${dirColor(evalData.claude_decision.action)}`}>
                  {evalData.claude_decision.action}
                </div>
                <div className="text-xs text-zinc-500 mt-0.5">{evalData.symbol} | {evalData.timeframe}</div>
              </div>
              <div className="text-right">
                <div className={`text-3xl font-mono font-bold ${scoreCol(evalData.claude_decision.confidence)}`}>
                  {evalData.claude_decision.confidence}
                </div>
                <div className="text-xs text-zinc-500">confidence</div>
              </div>
            </div>

            {evalData.should_trade && (
              <div className="grid grid-cols-3 gap-3 mt-4 text-sm font-mono">
                <div>
                  <div className="text-xs text-zinc-500">Entry</div>
                  <div>{evalData.claude_decision.entry.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-xs text-red-400/70">Stop Loss</div>
                  <div className="text-red-400">{evalData.claude_decision.stop_loss.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-xs text-emerald-400/70">Take Profit</div>
                  <div className="text-emerald-400">{evalData.claude_decision.take_profit.toFixed(2)}</div>
                </div>
              </div>
            )}
          </div>

          {/* Reasoning */}
          <div>
            <div className="text-xs text-zinc-500 uppercase tracking-wider mb-1">Reasoning</div>
            <div className="text-sm text-zinc-300 bg-zinc-800/50 rounded-lg p-3">
              {evalData.claude_decision.reasoning}
            </div>
          </div>

          {/* Three Gates Status */}
          <div>
            <div className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Verification Gates</div>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 text-xs">
                <span className={evalData.confluence.score >= 6 ? "text-emerald-400" : "text-red-400"}>
                  {evalData.confluence.score >= 6 ? "PASS" : "FAIL"}
                </span>
                <span className="text-zinc-400">Gate 1: Confluence Score {evalData.confluence.score}/10 (min 6.0)</span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className={evalData.claude_decision.confidence >= 7 ? "text-emerald-400" : evalData.claude_decision.action === "SKIP" ? "text-zinc-500" : "text-red-400"}>
                  {evalData.claude_decision.confidence >= 7 ? "PASS" : evalData.claude_decision.action === "SKIP" ? "SKIP" : "FAIL"}
                </span>
                <span className="text-zinc-400">Gate 2: Claude Confidence {evalData.claude_decision.confidence}/10 (min 7)</span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className={evalData.risk_check.passed ? "text-emerald-400" : "text-red-400"}>
                  {evalData.risk_check.passed ? "PASS" : "FAIL"}
                </span>
                <span className="text-zinc-400">Gate 3: Risk Manager</span>
              </div>
            </div>
          </div>

          {/* Risk Warnings */}
          {(evalData.claude_decision.risk_warnings.length > 0 || evalData.risk_check.rejections.length > 0) && (
            <div>
              <div className="text-xs text-red-400/70 uppercase tracking-wider mb-1">Warnings</div>
              <div className="space-y-1">
                {evalData.claude_decision.risk_warnings.map((w, i) => (
                  <div key={`cw-${i}`} className="text-xs text-red-400 bg-red-500/5 rounded px-2 py-1">{w}</div>
                ))}
                {evalData.risk_check.rejections.map((w, i) => (
                  <div key={`rr-${i}`} className="text-xs text-red-400 bg-red-500/5 rounded px-2 py-1">{w}</div>
                ))}
              </div>
            </div>
          )}

          {/* Final Verdict + Take Trade */}
          <div className={`text-center py-3 rounded-lg text-sm font-bold ${
            evalData.should_trade
              ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
              : "bg-zinc-800 text-zinc-500 border border-zinc-700"
          }`}>
            {evalData.should_trade ? "TRADE APPROVED" : "DO NOT TRADE"}
          </div>
          {evalData.should_trade && (
            <button
              onClick={async () => {
                const res = await fetch(`${ENGINE}/api/trade/open/${evalData.symbol}?timeframe=${evalData.timeframe}`, { method: "POST" });
                const data = await res.json();
                alert(data.status === "opened"
                  ? `Position opened! ${data.position.direction} ${evalData.symbol} @ ${data.position.entry_price}. Risk: $${data.risk_amount}`
                  : `Trade rejected: ${data.reason || data.rejections?.join(", ")}`);
              }}
              className="w-full mt-2 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-bold transition-colors"
            >
              Take This Trade
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// -- Signal Detail --

function SignalDetail({ scan }: { scan: ScanResult | null }) {
  if (!scan) return <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 text-center text-zinc-500">Select an instrument to view signals</div>;

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">Strategy Signals</h3>
          <div className="text-xs text-zinc-500 mt-0.5">{scan.timeframe} | {regimeMap[scan.regime] || scan.regime} | {scan.agreeing_strategies}/{scan.total_strategies} agree</div>
        </div>
        <div className={`px-3 py-1.5 rounded-lg border ${dirBg(scan.direction)}`}>
          <div className={`text-xl font-mono font-bold ${dirColor(scan.direction)}`}>{scan.composite_score.toFixed(1)}</div>
        </div>
      </div>
      <div className="space-y-2">
        {scan.signals.map((sig, i) => (
          <div key={i} className={`border rounded-lg p-2.5 ${sig.direction ? dirBg(sig.direction) : "bg-zinc-800/50 border-zinc-700/50"}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">{sig.strategy.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())}</span>
                {sig.strength !== "NONE" && (
                  <span className={`text-[10px] px-1 py-0.5 rounded ${sig.strength === "STRONG" ? "bg-emerald-500/20 text-emerald-400" : sig.strength === "MODERATE" ? "bg-yellow-500/20 text-yellow-400" : "bg-zinc-700 text-zinc-400"}`}>
                    {sig.strength}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 text-xs font-mono">
                {sig.direction && <span className={dirColor(sig.direction)}>{sig.direction}</span>}
                <span className={scoreCol(sig.score / 10)}>{sig.score.toFixed(0)}</span>
              </div>
            </div>
            <div className="text-[11px] text-zinc-400 mt-1">{sig.reason}</div>
            {sig.entry && (
              <div className="flex gap-3 mt-1.5 text-[11px] font-mono">
                <span>E: {sig.entry.toFixed(2)}</span>
                <span className="text-red-400">SL: {sig.stop_loss?.toFixed(2)}</span>
                <span className="text-emerald-400">TP: {sig.take_profit?.toFixed(2)}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// -- Main Page --

export default function Dashboard() {
  const [overview, setOverview] = useState<ScanOverview[]>([]);
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ScanResult | null>(null);
  const [evalData, setEvalData] = useState<EvalResult | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [positions, setPositions] = useState<Array<Record<string, unknown>>>([]);
  const [tradeSummary, setTradeSummary] = useState<Record<string, unknown> | null>(null);
  const [tf, setTf] = useState("5m");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [ovRes, rkRes, posRes, sumRes] = await Promise.all([
        fetch(`${ENGINE}/api/scan/all?timeframe=${tf}`),
        fetch(`${ENGINE}/api/risk/status`),
        fetch(`${ENGINE}/api/trade/positions`),
        fetch(`${ENGINE}/api/trade/summary`),
      ]);
      if (!ovRes.ok || !rkRes.ok) throw new Error("fail");
      setOverview((await ovRes.json()).results || []);
      setRisk(await rkRes.json());
      if (posRes.ok) setPositions((await posRes.json()).positions || []);
      if (sumRes.ok) setTradeSummary(await sumRes.json());
      setErr(null);
    } catch {
      setErr("Engine offline. Run: cd engine && python run.py");
    } finally {
      setLoading(false);
    }
  }, [tf]);

  // Fetch detail when symbol selected
  useEffect(() => {
    if (!selected) return;
    setEvalData(null); // Reset evaluation when switching symbols
    fetch(`${ENGINE}/api/scan/${selected}?timeframe=${tf}`)
      .then((r) => r.json()).then(setDetail).catch(() => setDetail(null));
  }, [selected, tf]);

  // Auto-refresh every 30 seconds
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  // Evaluate trade with Claude
  const handleEvaluate = useCallback(async () => {
    if (!selected) return;
    setEvalLoading(true);
    try {
      const res = await fetch(`${ENGINE}/api/evaluate/${selected}?timeframe=${tf}`);
      const data = await res.json();
      setEvalData(data);
    } catch {
      setEvalData(null);
    } finally {
      setEvalLoading(false);
    }
  }, [selected, tf]);

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Notas Lave</h1>
          <p className="text-sm text-zinc-500">AI Trading Co-Pilot</p>
        </div>
        <div className="flex items-center gap-2">
          {["1m","5m","15m","30m","1h"].map((t) => (
            <button key={t} onClick={() => setTf(t)} className={`px-3 py-1.5 text-xs font-mono rounded-md ${tf === t ? "bg-blue-600 text-white" : "bg-zinc-800 text-zinc-400 hover:text-zinc-200"}`}>{t}</button>
          ))}
          <button onClick={refresh} className="ml-2 px-3 py-1.5 text-xs bg-zinc-800 text-zinc-400 hover:text-zinc-200 rounded-md">Refresh</button>
        </div>
      </div>

      {err && <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-6 text-red-400 text-sm">{err}</div>}

      <RiskPanel r={risk} />

      {/* Chart */}
      {selected && (
        <div className="mb-6">
          <CandlestickChart symbol={selected} timeframe={tf} />
        </div>
      )}

      {/* Main Grid: Markets | Signals + Claude */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Markets (left sidebar) */}
        <div className="lg:col-span-3 space-y-3">
          <h2 className="text-sm font-medium text-zinc-500 uppercase tracking-wider mb-2">Markets</h2>
          {loading ? <div className="text-zinc-500 text-sm">Loading...</div> : overview.map((it) => (
            <MarketCard key={it.symbol} item={it} onSelect={setSelected} selected={selected === it.symbol} />
          ))}
        </div>

        {/* Signals (middle) */}
        <div className="lg:col-span-5">
          <h2 className="text-sm font-medium text-zinc-500 uppercase tracking-wider mb-2">Signals</h2>
          <SignalDetail scan={detail} />
        </div>

        {/* Claude Decision (right) */}
        <div className="lg:col-span-4">
          <h2 className="text-sm font-medium text-zinc-500 uppercase tracking-wider mb-2">AI Decision</h2>
          <ClaudePanel evalData={evalData} loading={evalLoading} onEvaluate={handleEvaluate} />
        </div>
      </div>

      {/* Open Positions + Trade Summary */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
        {/* Open Positions */}
        <div className="lg:col-span-2">
          <h2 className="text-sm font-medium text-zinc-500 uppercase tracking-wider mb-2">
            Open Positions ({positions.length})
          </h2>
          {positions.length === 0 ? (
            <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 text-center text-zinc-500 text-sm">
              No open positions
            </div>
          ) : (
            <div className="space-y-2">
              {positions.map((p) => (
                <div key={p.id as string} className={`bg-zinc-900 border rounded-lg p-4 ${dirBg(p.direction as string)}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-bold">{p.symbol as string}</span>
                      <span className={`text-xs font-medium ${dirColor(p.direction as string)}`}>{p.direction as string}</span>
                      {p.breakeven as boolean && <span className="text-[10px] px-1 py-0.5 rounded bg-blue-500/20 text-blue-400">BE</span>}
                    </div>
                    <div className="flex items-center gap-4">
                      <div className={`text-lg font-mono font-bold ${(p.unrealized_pnl as number) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {(p.unrealized_pnl as number) >= 0 ? "+" : ""}${(p.unrealized_pnl as number).toFixed(2)}
                      </div>
                      <button
                        onClick={async () => {
                          if (!confirm(`Close ${p.symbol} position?`)) return;
                          await fetch(`${ENGINE}/api/trade/close/${p.id}`, { method: "POST" });
                          refresh();
                        }}
                        className="px-2 py-1 text-xs bg-zinc-700 hover:bg-zinc-600 rounded transition-colors"
                      >
                        Close
                      </button>
                    </div>
                  </div>
                  <div className="flex gap-4 mt-2 text-xs font-mono text-zinc-400">
                    <span>Entry: {(p.entry_price as number).toFixed(2)}</span>
                    <span>Now: {(p.current_price as number).toFixed(2)}</span>
                    <span className="text-red-400">SL: {(p.stop_loss as number).toFixed(2)}</span>
                    <span className="text-emerald-400">TP: {(p.take_profit as number).toFixed(2)}</span>
                    <span>Score: {(p.confluence_score as number).toFixed(1)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Trade Summary */}
        <div>
          <h2 className="text-sm font-medium text-zinc-500 uppercase tracking-wider mb-2">Performance</h2>
          <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
            {!tradeSummary ? (
              <div className="text-sm text-zinc-500 text-center">No trades yet</div>
            ) : (
              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Total Trades</span>
                  <span className="font-mono">{tradeSummary.total_trades as number}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Win Rate</span>
                  <span className={`font-mono ${(tradeSummary.win_rate as number) >= 50 ? "text-emerald-400" : "text-red-400"}`}>
                    {(tradeSummary.win_rate as number).toFixed(1)}%
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">W / L</span>
                  <span className="font-mono">
                    <span className="text-emerald-400">{tradeSummary.wins as number}</span>
                    {" / "}
                    <span className="text-red-400">{tradeSummary.losses as number}</span>
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Total P&L</span>
                  <span className={`font-mono font-bold ${(tradeSummary.total_pnl as number) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {(tradeSummary.total_pnl as number) >= 0 ? "+" : ""}${(tradeSummary.total_pnl as number).toFixed(2)}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
