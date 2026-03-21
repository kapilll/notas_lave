"use client";

import { useEffect, useState, useCallback } from "react";
import type { ScanResult } from "@/lib/api";
import { STRATEGY_INFO, REGIME_INFO } from "@/lib/strategy-info";

const ENGINE = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8000";

// ═══════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════

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
    action: string; confidence: number; entry: number;
    stop_loss: number; take_profit: number; reasoning: string; risk_warnings: string[];
  };
  risk_check: { passed: boolean; rejections: string[] };
  current_price: number;
  should_trade: boolean;
}

// ═══════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════

function dir(d: string | null) {
  if (d === "LONG" || d === "BUY") return { text: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/30", label: d };
  if (d === "SHORT" || d === "SELL") return { text: "text-red-400", bg: "bg-red-500/10 border-red-500/30", label: d };
  return { text: "text-zinc-500", bg: "bg-zinc-800/50 border-zinc-700", label: "NEUTRAL" };
}

function scoreColor(s: number) {
  if (s >= 7) return "text-emerald-400";
  if (s >= 5) return "text-amber-400";
  return "text-zinc-500";
}

function pnlColor(n: number) { return n >= 0 ? "text-emerald-400" : "text-red-400"; }
function pnlSign(n: number) { return n >= 0 ? `+$${n.toFixed(2)}` : `-$${Math.abs(n).toFixed(2)}`; }

const REGIMES: Record<string, { icon: string; color: string }> = {
  TRENDING: { icon: "/", color: "text-blue-400" },
  RANGING: { icon: "~", color: "text-amber-400" },
  VOLATILE: { icon: "!", color: "text-red-400" },
  QUIET: { icon: "-", color: "text-zinc-500" },
};

// ═══════════════════════════════════════════════════════════
// CARD: Base wrapper for all sections
// ═══════════════════════════════════════════════════════════

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`bg-zinc-900/80 border border-zinc-800 rounded-xl ${className}`}>{children}</div>;
}
function CardHeader({ children }: { children: React.ReactNode }) {
  return <div className="px-5 py-3 border-b border-zinc-800/60 flex items-center justify-between">{children}</div>;
}
function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-widest">{children}</h2>;
}

// ═══════════════════════════════════════════════════════════
// STATUS BAR — Balance, P&L, Drawdown, Status
// ═══════════════════════════════════════════════════════════

function StatusBar({ r, tradesCount }: { r: RiskStatus | null; tradesCount: number }) {
  if (!r) return null;

  const ddColor = r.daily_drawdown_used_pct > 60 ? "text-red-400" : r.daily_drawdown_used_pct > 30 ? "text-amber-400" : "text-emerald-400";
  const statusColor = r.is_halted ? "bg-red-500" : r.can_trade ? "bg-emerald-500" : "bg-amber-500";
  const statusText = r.is_halted ? "HALTED" : r.can_trade ? "LIVE" : "LIMIT";

  return (
    <div className="flex items-center gap-6 text-sm mb-6 bg-zinc-900/60 border border-zinc-800 rounded-xl px-5 py-3">
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${statusColor} animate-pulse`} />
        <span className="text-zinc-400 font-medium">{statusText}</span>
      </div>
      <div className="h-4 w-px bg-zinc-800" />
      <div>
        <span className="text-zinc-500 text-xs">Balance</span>
        <span className="ml-2 font-mono font-bold text-zinc-100">${r.balance.toLocaleString()}</span>
      </div>
      <div>
        <span className="text-zinc-500 text-xs">Daily</span>
        <span className={`ml-2 font-mono font-bold ${pnlColor(r.daily_pnl)}`}>{pnlSign(r.daily_pnl)}</span>
      </div>
      <div>
        <span className="text-zinc-500 text-xs">Total</span>
        <span className={`ml-2 font-mono font-bold ${pnlColor(r.total_pnl)}`}>{pnlSign(r.total_pnl)}</span>
      </div>
      <div>
        <span className="text-zinc-500 text-xs">DD</span>
        <span className={`ml-2 font-mono font-bold ${ddColor}`}>{r.daily_drawdown_used_pct.toFixed(0)}%</span>
      </div>
      <div className="ml-auto text-zinc-500 text-xs">
        {r.trades_today} trades today | {tradesCount} positions open
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// LIVE TRADES — Most prominent section
// ═══════════════════════════════════════════════════════════

function LiveTrades({ positions, onClose, summary }: {
  positions: Array<Record<string, unknown>>;
  onClose: (id: string) => void;
  summary: Record<string, unknown> | null;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <SectionTitle>Live Trades</SectionTitle>
          {positions.length > 0 && (
            <span className="text-xs font-mono bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded-full">{positions.length} open</span>
          )}
        </div>
        {summary && (
          <div className="flex items-center gap-4 text-xs font-mono">
            <span className="text-zinc-500">{String(summary.total_trades || 0)} total</span>
            <span className={pnlColor(Number(summary.win_rate || 0) >= 50 ? 1 : -1)}>
              {Number(summary.win_rate || 0).toFixed(1)}% WR
            </span>
            <span className={pnlColor(Number(summary.total_pnl || 0))}>
              {pnlSign(Number(summary.total_pnl || 0))}
            </span>
          </div>
        )}
      </CardHeader>

      <div className="p-4">
        {positions.length === 0 ? (
          <div className="text-center py-8 text-zinc-600">
            <div className="text-lg mb-1">No open positions</div>
            <div className="text-xs">The autonomous agent will place trades when signals qualify</div>
          </div>
        ) : (
          <div className="space-y-2">
            {positions.map((p) => {
              const d = dir(p.direction as string);
              const pnl = p.unrealized_pnl as number;
              return (
                <div key={p.id as string} className={`border rounded-lg p-4 ${d.bg} transition-all`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-base font-bold text-zinc-100">{p.symbol as string}</span>
                      <span className={`text-xs font-bold px-2 py-0.5 rounded ${d.text} bg-zinc-800/60`}>{d.label}</span>
                      {p.breakeven as boolean && <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 font-medium">BREAKEVEN</span>}
                    </div>
                    <div className="flex items-center gap-4">
                      <div className={`text-xl font-mono font-bold ${pnlColor(pnl)}`}>{pnlSign(pnl)}</div>
                      <button onClick={() => onClose(p.id as string)}
                        className="px-3 py-1.5 text-xs bg-zinc-700 hover:bg-red-600 text-zinc-300 hover:text-white rounded-lg transition-all font-medium">
                        Close
                      </button>
                    </div>
                  </div>
                  <div className="flex gap-5 mt-3 text-xs font-mono">
                    <span className="text-zinc-400">Entry <span className="text-zinc-200">{(p.entry_price as number).toFixed(2)}</span></span>
                    <span className="text-zinc-400">Now <span className="text-zinc-200">{(p.current_price as number).toFixed(2)}</span></span>
                    <span className="text-zinc-400">SL <span className="text-red-400">{(p.stop_loss as number).toFixed(2)}</span></span>
                    <span className="text-zinc-400">TP <span className="text-emerald-400">{(p.take_profit as number).toFixed(2)}</span></span>
                    <span className="text-zinc-400">Score <span className="text-zinc-200">{(p.confluence_score as number).toFixed(1)}</span></span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════
// MARKETS — Horizontal instrument cards
// ═══════════════════════════════════════════════════════════

function Markets({ items, selected, onSelect }: {
  items: ScanOverview[]; selected: string | null; onSelect: (s: string) => void;
}) {
  return (
    <Card>
      <CardHeader><SectionTitle>Markets</SectionTitle></CardHeader>
      <div className="p-4 grid grid-cols-2 lg:grid-cols-4 gap-3">
        {items.map((item) => {
          const d = dir(item.direction);
          const regime = REGIMES[item.regime] || { icon: "?", color: "text-zinc-500" };
          const isSelected = selected === item.symbol;
          return (
            <button key={item.symbol} onClick={() => onSelect(item.symbol)}
              className={`text-left rounded-lg p-4 border transition-all hover:border-zinc-600 ${
                isSelected ? "border-blue-500 bg-blue-500/5 ring-1 ring-blue-500/20" : "border-zinc-800 bg-zinc-800/30"
              }`}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-bold text-zinc-100">{item.symbol}</span>
                <span className={`text-xl font-mono font-bold ${scoreColor(item.score)}`}>{item.score.toFixed(1)}</span>
              </div>
              <div className="text-lg font-mono text-zinc-200">${item.price?.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? "..."}</div>
              <div className="flex items-center justify-between mt-2 text-xs">
                <span className={d.text + " font-medium"}>{d.label}</span>
                <span className={regime.color}>{regime.icon} {item.regime}</span>
              </div>
              <div className="text-[10px] text-zinc-600 mt-1">{item.agreeing}/{item.total} strategies agree</div>
            </button>
          );
        })}
      </div>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════
// SIGNAL DETAIL + AI DECISION — Shown when a market is selected
// ═══════════════════════════════════════════════════════════

function MarketDetail({ scan, evalData, evalLoading, onEvaluate }: {
  scan: ScanResult | null;
  evalData: EvalResult | null;
  evalLoading: boolean;
  onEvaluate: () => void;
}) {
  if (!scan) return null;

  const regimeInfo = REGIME_INFO[scan.regime];
  const regime = REGIMES[scan.regime] || { icon: "?", color: "text-zinc-500" };
  const d = dir(scan.direction);

  // Split into active and inactive
  const active = scan.signals.filter((s) => s.direction !== null);
  const inactive = scan.signals.filter((s) => s.direction === null);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <SectionTitle>{scan.symbol} Signals</SectionTitle>
          <span className="text-xs text-zinc-500 font-mono">{scan.timeframe}</span>
          <span className={`text-xs ${regime.color}`}>{regime.icon} {scan.regime}</span>
          <span className={`text-xs font-mono px-2 py-0.5 rounded border ${d.bg} ${d.text}`}>
            {d.label} {scan.composite_score.toFixed(1)}/10
          </span>
          {regimeInfo && <span className="text-[10px] text-zinc-600 hidden lg:inline">Best: {regimeInfo.bestStrategies.split(",")[0]}</span>}
        </div>
        <button onClick={onEvaluate} disabled={evalLoading}
          className="px-4 py-2 text-xs font-medium bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white rounded-lg transition-colors">
          {evalLoading ? "Evaluating..." : "Evaluate with AI"}
        </button>
      </CardHeader>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 divide-y lg:divide-y-0 lg:divide-x divide-zinc-800/60">
        {/* Left: Signals */}
        <div className="p-4 space-y-1.5 max-h-[400px] overflow-y-auto">
          {active.length > 0 && active.map((sig, i) => {
            const info = STRATEGY_INFO[sig.strategy];
            const sd = dir(sig.direction);
            return (
              <div key={i} className={`border rounded-lg p-3 ${sd.bg}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-zinc-200">
                      {info?.displayName || sig.strategy.replace(/_/g, " ")}
                    </span>
                    {sig.strength !== "NONE" && (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                        sig.strength === "STRONG" ? "bg-emerald-500/20 text-emerald-400" : "bg-amber-500/20 text-amber-400"
                      }`}>{sig.strength}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs font-mono">
                    <span className={sd.text}>{sd.label}</span>
                    <span className={scoreColor(sig.score / 10)}>{sig.score.toFixed(0)}</span>
                  </div>
                </div>
                <div className="text-[11px] text-zinc-400 mt-1">{sig.reason}</div>
                {sig.entry && (
                  <div className="flex gap-4 mt-2 text-[11px] font-mono">
                    <span className="text-zinc-300">E: {sig.entry.toFixed(2)}</span>
                    <span className="text-red-400">SL: {sig.stop_loss?.toFixed(2)}</span>
                    <span className="text-emerald-400">TP: {sig.take_profit?.toFixed(2)}</span>
                  </div>
                )}
              </div>
            );
          })}
          {active.length === 0 && <div className="text-sm text-zinc-600 text-center py-4">No active signals</div>}
          {inactive.length > 0 && (
            <details className="mt-2">
              <summary className="text-[10px] text-zinc-600 cursor-pointer hover:text-zinc-400">{inactive.length} inactive strategies</summary>
              <div className="mt-1 space-y-0.5">
                {inactive.map((sig, i) => (
                  <div key={i} className="text-[10px] text-zinc-600 py-0.5">{sig.strategy}: {sig.reason}</div>
                ))}
              </div>
            </details>
          )}
        </div>

        {/* Right: AI Decision */}
        <div className="p-4">
          {!evalData ? (
            <div className="text-center py-8 text-zinc-600">
              <div className="text-sm">Click &quot;Evaluate with AI&quot; for Claude analysis</div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className={`border rounded-lg p-4 ${evalData.should_trade
                ? evalData.claude_decision.action === "BUY" ? "bg-emerald-500/10 border-emerald-500/40" : "bg-red-500/10 border-red-500/40"
                : "bg-zinc-800/50 border-zinc-700"
              }`}>
                <div className="flex items-center justify-between">
                  <div>
                    <div className={`text-2xl font-bold ${dir(evalData.claude_decision.action).text}`}>{evalData.claude_decision.action}</div>
                    <div className="text-[10px] text-zinc-500 mt-0.5">{evalData.symbol} | {evalData.timeframe}</div>
                  </div>
                  <div className="text-right">
                    <div className={`text-3xl font-mono font-bold ${scoreColor(evalData.claude_decision.confidence)}`}>{evalData.claude_decision.confidence}</div>
                    <div className="text-[10px] text-zinc-500">confidence</div>
                  </div>
                </div>
                {evalData.should_trade && (
                  <div className="grid grid-cols-3 gap-3 mt-3 text-sm font-mono">
                    <div><div className="text-[10px] text-zinc-500">Entry</div><div className="text-zinc-200">{evalData.claude_decision.entry.toFixed(2)}</div></div>
                    <div><div className="text-[10px] text-red-400/70">SL</div><div className="text-red-400">{evalData.claude_decision.stop_loss.toFixed(2)}</div></div>
                    <div><div className="text-[10px] text-emerald-400/70">TP</div><div className="text-emerald-400">{evalData.claude_decision.take_profit.toFixed(2)}</div></div>
                  </div>
                )}
              </div>

              <div className="text-xs text-zinc-300 bg-zinc-800/40 rounded-lg p-3">{evalData.claude_decision.reasoning}</div>

              {/* Gates */}
              <div className="space-y-1">
                {[
                  { pass: evalData.confluence.score >= 6, label: `Gate 1: Score ${evalData.confluence.score}/10` },
                  { pass: evalData.claude_decision.confidence >= 7, label: `Gate 2: Confidence ${evalData.claude_decision.confidence}/10` },
                  { pass: evalData.risk_check.passed, label: "Gate 3: Risk Manager" },
                ].map((g) => (
                  <div key={g.label} className="flex items-center gap-2 text-xs">
                    <span className={`w-1.5 h-1.5 rounded-full ${g.pass ? "bg-emerald-500" : "bg-red-500"}`} />
                    <span className="text-zinc-400">{g.label}</span>
                  </div>
                ))}
              </div>

              {/* Warnings */}
              {(evalData.claude_decision.risk_warnings.length > 0 || evalData.risk_check.rejections.length > 0) && (
                <div className="space-y-1">
                  {[...evalData.claude_decision.risk_warnings, ...evalData.risk_check.rejections].map((w, i) => (
                    <div key={i} className="text-[10px] text-red-400 bg-red-500/5 rounded px-2 py-1">{w}</div>
                  ))}
                </div>
              )}

              <div className={`text-center py-2 rounded-lg text-sm font-bold ${
                evalData.should_trade ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30" : "bg-zinc-800 text-zinc-500 border border-zinc-700"
              }`}>{evalData.should_trade ? "TRADE APPROVED" : "DO NOT TRADE"}</div>

              {evalData.should_trade && (
                <button onClick={async () => {
                  const res = await fetch(`${ENGINE}/api/trade/open/${evalData.symbol}?timeframe=${evalData.timeframe}`, { method: "POST" });
                  const data = await res.json();
                  alert(data.status === "opened"
                    ? `Opened ${data.position.direction} ${evalData.symbol} @ ${data.position.entry_price}`
                    : `Rejected: ${data.reason || data.rejections?.join(", ")}`);
                }} className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-bold transition-colors">
                  Take This Trade
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════
// TOOLS — Organized into tab groups
// ═══════════════════════════════════════════════════════════

type ToolGroup = { label: string; tools: { id: string; label: string; url: string; method?: string; needsSymbol?: boolean }[] };

function ToolsSection({ selected, tf }: { selected: string | null; tf: string }) {
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const groups: ToolGroup[] = [
    { label: "Analysis", tools: [
      { id: "backtest", label: "Backtest", url: `/api/backtest/${selected}?timeframe=${tf}`, needsSymbol: true },
      { id: "walkforward", label: "Walk-Forward", url: `/api/backtest/walk-forward/${selected}?timeframe=${tf}`, needsSymbol: true },
      { id: "montecarlo", label: "Monte Carlo", url: `/api/backtest/monte-carlo/${selected}?timeframe=${tf}`, needsSymbol: true },
      { id: "accuracy", label: "Accuracy", url: "/api/accuracy/score" },
      { id: "performance", label: "Strategy Perf", url: "/api/journal/performance" },
    ]},
    { label: "Learning", tools: [
      { id: "learning", label: "AI Insights", url: "/api/learning/analysis" },
      { id: "recommendations", label: "Recommendations", url: "/api/learning/recommendations" },
      { id: "abtests", label: "A/B Tests", url: "/api/ab-test/results" },
      { id: "review", label: "Weekly Review", url: "/api/learning/review", method: "POST" },
      { id: "optimize", label: "Optimize", url: `/api/learning/optimize/${selected}?timeframe=${tf}`, method: "POST", needsSymbol: true },
    ]},
    { label: "Trading", tools: [
      { id: "trades", label: "Trade History", url: "/api/journal/trades?limit=30" },
      { id: "journal", label: "Signal Journal", url: "/api/journal/signals?limit=30" },
      { id: "calendar", label: "News Calendar", url: "/api/calendar/status" },
      { id: "costs", label: "Token Costs", url: "/api/costs/summary" },
    ]},
    { label: "System", tools: [
      { id: "scan-now", label: "Scan Now", url: "/api/alerts/scan-now", method: "POST" },
      { id: "alert-status", label: "Alert Status", url: "/api/alerts/status" },
      { id: "test-alert", label: "Test Telegram", url: "/api/alerts/test", method: "POST" },
      { id: "agent-status", label: "Agent Status", url: "/api/agent/status" },
    ]},
  ];

  const runTool = async (tool: typeof groups[0]["tools"][0]) => {
    setActiveTab(tool.id);
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch(`${ENGINE}${tool.url}`, { method: tool.method || "GET" });
      setResult(await res.json());
    } catch { setResult({ error: "Failed to connect to engine" }); }
    finally { setLoading(false); }
  };

  return (
    <Card>
      <CardHeader><SectionTitle>Tools</SectionTitle></CardHeader>
      <div className="p-4">
        {/* Tool group tabs */}
        <div className="flex flex-wrap gap-4 mb-4">
          {groups.map((group) => (
            <div key={group.label} className="space-y-1.5">
              <div className="text-[10px] font-medium text-zinc-600 uppercase tracking-wider">{group.label}</div>
              <div className="flex gap-1.5">
                {group.tools.map((tool) => {
                  const disabled = tool.needsSymbol && !selected;
                  return (
                    <button key={tool.id} onClick={() => !disabled && runTool(tool)} disabled={disabled}
                      className={`px-3 py-1.5 text-xs rounded-lg transition-all font-medium ${
                        activeTab === tool.id ? "bg-blue-600 text-white" :
                        disabled ? "bg-zinc-900 text-zinc-700 cursor-not-allowed" :
                        "bg-zinc-800/60 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                      }`}>
                      {tool.label}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Results */}
        {activeTab && (
          <div className="border-t border-zinc-800/60 pt-4">
            {loading && <div className="text-zinc-500 text-sm py-4 text-center">Loading...</div>}

            {/* Accuracy — rich rendering */}
            {activeTab === "accuracy" && result && !loading && (() => {
              const r = result;
              if (r.status === "no_data") return <div className="text-sm text-zinc-500">{String(r.message)}</div>;
              const calibration = (r.calibration || {}) as Record<string, Record<string, unknown>>;
              const byStrategy = (r.by_strategy || {}) as Record<string, Record<string, unknown>>;
              return (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {[
                      { label: "Direction Accuracy", value: `${r.direction_accuracy}%`, color: Number(r.direction_accuracy) >= 55 ? "text-emerald-400" : "text-amber-400" },
                      { label: "Target Accuracy", value: `${r.target_accuracy}%`, color: Number(r.target_accuracy) >= 40 ? "text-emerald-400" : "text-amber-400" },
                      { label: "Predictions", value: String(r.total_predictions), color: "text-zinc-200" },
                      { label: "Period", value: `${r.period_days} days`, color: "text-zinc-200" },
                    ].map((m) => (
                      <div key={m.label} className="bg-zinc-800/40 rounded-lg p-3 text-center">
                        <div className="text-[10px] text-zinc-500 uppercase">{m.label}</div>
                        <div className={`text-2xl font-mono font-bold mt-1 ${m.color}`}>{m.value}</div>
                      </div>
                    ))}
                  </div>
                  {Object.keys(calibration).length > 0 && (
                    <div>
                      <div className="text-xs font-medium text-zinc-400 mb-2">Score Calibration</div>
                      {Object.entries(calibration).map(([bucket, stats]) => {
                        const acc = Number((stats as Record<string, unknown>).direction_accuracy);
                        return (
                          <div key={bucket} className="flex items-center gap-2 text-xs mb-1">
                            <span className="w-12 text-right text-zinc-500 font-mono">{bucket}</span>
                            <div className="flex-1 bg-zinc-800 rounded-full h-3 overflow-hidden">
                              <div className={`h-full rounded-full ${acc >= 55 ? "bg-emerald-500" : acc >= 45 ? "bg-amber-500" : "bg-red-500"}`}
                                style={{ width: `${Math.max(5, acc)}%` }} />
                            </div>
                            <span className="w-12 text-right font-mono text-zinc-300">{acc}%</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {Object.keys(byStrategy).length > 0 && (
                    <div>
                      <div className="text-xs font-medium text-zinc-400 mb-2">Per-Strategy</div>
                      {Object.entries(byStrategy).map(([name, stats]) => (
                        <div key={name} className="flex justify-between text-xs py-1 border-b border-zinc-800/30">
                          <span className="text-zinc-300">{STRATEGY_INFO[name]?.displayName || name}</span>
                          <span className="font-mono">
                            <span className={Number((stats as Record<string, unknown>).direction_accuracy) >= 55 ? "text-emerald-400" : "text-zinc-400"}>
                              {String((stats as Record<string, unknown>).direction_accuracy)}%
                            </span>
                            <span className="text-zinc-600 ml-2">{String((stats as Record<string, unknown>).total)}t</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Costs — rich rendering */}
            {activeTab === "costs" && result && !loading && (() => {
              const r = result;
              const runtime = (r.runtime || {}) as Record<string, unknown>;
              const build = (r.build || {}) as Record<string, unknown>;
              const byPurpose = (runtime.by_purpose || {}) as Record<string, Record<string, unknown>>;
              return (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="bg-zinc-800/40 rounded-lg p-3 text-center">
                      <div className="text-[10px] text-zinc-500 uppercase">Runtime</div>
                      <div className="text-xl font-mono font-bold text-blue-400 mt-1">${Number(runtime.total_cost || 0).toFixed(4)}</div>
                      <div className="text-[10px] text-zinc-600">{String(runtime.calls || 0)} calls</div>
                    </div>
                    <div className="bg-zinc-800/40 rounded-lg p-3 text-center">
                      <div className="text-[10px] text-zinc-500 uppercase">Build</div>
                      <div className="text-xl font-mono font-bold text-purple-400 mt-1">${Number(build.total_cost || 0).toFixed(2)}</div>
                    </div>
                    <div className="bg-zinc-800/40 rounded-lg p-3 text-center">
                      <div className="text-[10px] text-zinc-500 uppercase">Total</div>
                      <div className="text-xl font-mono font-bold text-zinc-200 mt-1">${Number(r.total_cost || 0).toFixed(2)}</div>
                    </div>
                    <div className="bg-zinc-800/40 rounded-lg p-3 text-center">
                      <div className="text-[10px] text-zinc-500 uppercase">Tokens</div>
                      <div className="text-xl font-mono font-bold text-zinc-200 mt-1">
                        {((Number(runtime.total_tokens_in || 0) + Number(runtime.total_tokens_out || 0)) / 1000).toFixed(1)}K
                      </div>
                    </div>
                  </div>
                  {Object.keys(byPurpose).length > 0 && Object.entries(byPurpose).map(([purpose, stats]) => (
                    <div key={purpose} className="flex justify-between text-xs py-1 border-b border-zinc-800/30">
                      <span className="text-zinc-300 capitalize">{purpose.replace(/_/g, " ")}</span>
                      <span className="font-mono text-blue-400">${Number(stats.cost).toFixed(4)} <span className="text-zinc-500">{String(stats.calls)} calls</span></span>
                    </div>
                  ))}
                  <div className="flex gap-2 mt-2">
                    <input id="bc" type="number" step="0.01" placeholder="$ cost" className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs font-mono text-zinc-200 w-20" />
                    <input id="bd" type="text" placeholder="Description" className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 flex-1" />
                    <button onClick={async () => {
                      const c = parseFloat((document.getElementById("bc") as HTMLInputElement)?.value || "0");
                      const d = (document.getElementById("bd") as HTMLInputElement)?.value || "";
                      if (c > 0) { await fetch(`${ENGINE}/api/costs/log-build?cost=${c}&description=${encodeURIComponent(d)}`, { method: "POST" }); }
                    }} className="px-3 py-1 text-xs bg-purple-600 hover:bg-purple-500 text-white rounded font-medium">Log Build</button>
                  </div>
                </div>
              );
            })()}

            {/* Calendar */}
            {activeTab === "calendar" && result && !loading && (() => {
              const events = ((result as Record<string, unknown>).upcoming_events || []) as Array<Record<string, unknown>>;
              return (
                <div className="space-y-3">
                  <div className={`px-3 py-2 rounded text-sm font-medium ${result.is_blocked ? "bg-red-900/50 text-red-300" : "bg-emerald-900/30 text-emerald-300"}`}>
                    {result.is_blocked ? `BLACKOUT: ${(result.blocking_event as Record<string, unknown>)?.name}` : "No blackout — trading allowed"}
                  </div>
                  {events.map((e, i) => (
                    <div key={i} className="flex justify-between text-xs border-b border-zinc-800/30 py-1.5">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${e.impact === "HIGH" ? "bg-red-500" : "bg-amber-500"}`} />
                        <span className="text-zinc-200">{String(e.name)}</span>
                      </div>
                      <span className="text-zinc-500 font-mono">{new Date(String(e.datetime)).toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              );
            })()}

            {/* Trades / Journal / Performance — table format */}
            {activeTab === "trades" && result && !loading && (
              <div className="max-h-80 overflow-y-auto space-y-1">
                {((result.trades || []) as Array<Record<string, unknown>>).map((t, i) => (
                  <div key={i} className="flex justify-between text-xs py-1.5 border-b border-zinc-800/30">
                    <div className="flex items-center gap-2">
                      <span className="text-zinc-200 font-medium">{t.symbol as string}</span>
                      <span className={dir(t.direction as string).text}>{t.direction as string}</span>
                      <span className="text-zinc-600">{t.exit_reason as string}</span>
                    </div>
                    <span className={`font-mono font-bold ${pnlColor(t.pnl as number)}`}>{pnlSign(t.pnl as number)}</span>
                  </div>
                ))}
                {((result.trades || []) as Array<unknown>).length === 0 && <div className="text-zinc-600 text-sm text-center py-4">No trades yet</div>}
              </div>
            )}

            {activeTab === "journal" && result && !loading && (
              <div className="max-h-80 overflow-y-auto space-y-1">
                {((result.signals || []) as Array<Record<string, unknown>>).map((s, i) => (
                  <div key={i} className="flex justify-between text-xs py-1.5 border-b border-zinc-800/30">
                    <div className="flex items-center gap-2">
                      <span className="text-zinc-200 font-medium">{s.symbol as string}</span>
                      <span className={dir(s.direction as string).text}>{s.direction as string || "—"}</span>
                      <span className="text-zinc-600">{s.regime as string}</span>
                    </div>
                    <div className="flex gap-3 font-mono">
                      <span className={scoreColor(s.score as number)}>{(s.score as number)?.toFixed(1)}</span>
                      <span className={s.should_trade ? "text-emerald-400" : "text-zinc-600"}>{s.should_trade ? "TRADE" : "SKIP"}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {activeTab === "performance" && result && !loading && (
              <div className="space-y-1">
                {((result.strategies || []) as Array<Record<string, unknown>>).map((s, i) => (
                  <div key={i} className="flex justify-between text-xs py-1.5 border-b border-zinc-800/30">
                    <span className="text-zinc-200 font-medium">{STRATEGY_INFO[s.strategy as string]?.displayName || s.strategy as string}</span>
                    <span className="font-mono">
                      {s.total_trades as number}t
                      <span className={pnlColor((s.win_rate as number) >= 50 ? 1 : -1)}> {(s.win_rate as number)?.toFixed(1)}%</span>
                      <span className={pnlColor(s.total_pnl as number)}> {pnlSign(s.total_pnl as number)}</span>
                    </span>
                  </div>
                ))}
                {((result.strategies || []) as Array<unknown>).length === 0 && <div className="text-zinc-600 text-sm text-center py-4">No data yet</div>}
              </div>
            )}

            {/* Backtest results */}
            {(activeTab === "backtest" || activeTab === "walkforward") && result && !loading && (
              <div className="space-y-3">
                {result.error ? <div className="text-red-400 text-sm">{String(result.error)}</div> : (
                  <>
                    {activeTab === "walkforward" && result.overfit_warning && (
                      <div className="bg-red-900/30 border border-red-500/30 rounded-lg px-3 py-2 text-xs text-red-300">
                        Overfit ratio: {String(result.overfit_ratio)}x — in-sample performance is significantly better than out-of-sample
                      </div>
                    )}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                      {(() => {
                        const d = activeTab === "walkforward" ? (result.out_of_sample || {}) as Record<string, unknown> : result;
                        return [
                          { l: "Trades", v: String(d.total_trades), c: "" },
                          { l: "Win Rate", v: `${d.win_rate}%`, c: Number(d.win_rate) >= 50 ? "text-emerald-400" : "text-red-400" },
                          { l: "Net P&L", v: `$${Number(d.net_pnl || 0).toLocaleString()}`, c: Number(d.net_pnl) >= 0 ? "text-emerald-400" : "text-red-400" },
                          { l: "Profit Factor", v: String(d.profit_factor), c: Number(d.profit_factor) >= 1.5 ? "text-emerald-400" : "text-amber-400" },
                          { l: "Max DD", v: `${d.max_drawdown_pct || d.max_dd_pct}%`, c: Number(d.max_drawdown_pct || d.max_dd_pct) <= 10 ? "text-emerald-400" : "text-red-400" },
                          { l: "Sharpe", v: String(d.sharpe_ratio || "—"), c: "" },
                        ].map((m) => (
                          <div key={m.l} className="bg-zinc-800/40 rounded p-2">
                            <div className="text-[10px] text-zinc-500 uppercase">{m.l}</div>
                            <div className={`font-mono font-bold ${m.c}`}>{m.v}</div>
                          </div>
                        ));
                      })()}
                    </div>
                    {activeTab === "walkforward" && result.per_fold && (
                      <div>
                        <div className="text-xs font-medium text-zinc-400 mb-1">Per-Fold Results (OOS)</div>
                        {(result.per_fold as Array<Record<string, unknown>>).map((f) => (
                          <div key={String(f.fold)} className="flex justify-between text-xs py-1 border-b border-zinc-800/30">
                            <span className="text-zinc-500">Fold {String(f.fold)}</span>
                            <span className="font-mono">
                              {String(f.trades)}t | {String(f.win_rate)}% WR |
                              <span className={pnlColor(f.net_pnl as number)}> ${String(f.net_pnl)}</span> | PF {String(f.profit_factor)}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {/* Fallback JSON for anything without a custom renderer */}
            {!["accuracy", "costs", "calendar", "trades", "journal", "performance", "backtest", "walkforward"].includes(activeTab || "") && result && !loading && (
              <div>
                {(result as Record<string, unknown>).review_text && (
                  <div className="text-xs text-zinc-300 whitespace-pre-wrap bg-zinc-800/40 rounded p-3 mb-3">{String((result as Record<string, unknown>).review_text)}</div>
                )}
                <pre className="text-xs bg-zinc-800/30 rounded p-3 overflow-auto text-zinc-400 max-h-80">{JSON.stringify(result, null, 2)}</pre>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════

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
      setErr("Engine offline — run: cd engine && ../.venv/bin/python run.py");
    } finally { setLoading(false); }
  }, [tf]);

  useEffect(() => {
    if (!selected) return;
    setEvalData(null);
    fetch(`${ENGINE}/api/scan/${selected}?timeframe=${tf}`)
      .then((r) => r.json()).then(setDetail).catch(() => setDetail(null));
  }, [selected, tf]);

  useEffect(() => { refresh(); const id = setInterval(refresh, 30_000); return () => clearInterval(id); }, [refresh]);

  const handleEvaluate = useCallback(async () => {
    if (!selected) return;
    setEvalLoading(true);
    try { setEvalData(await (await fetch(`${ENGINE}/api/evaluate/${selected}?timeframe=${tf}`)).json()); }
    catch { setEvalData(null); }
    finally { setEvalLoading(false); }
  }, [selected, tf]);

  const handleClose = async (id: string) => {
    if (!confirm("Close this position?")) return;
    await fetch(`${ENGINE}/api/trade/close/${id}`, { method: "POST" });
    refresh();
  };

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-4 lg:p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-zinc-100">Notas Lave</h1>
          <p className="text-xs text-zinc-600">Autonomous Trading Engine</p>
        </div>
        <div className="flex items-center gap-1.5">
          {["1m","5m","15m","30m","1h"].map((t) => (
            <button key={t} onClick={() => setTf(t)}
              className={`px-3 py-1.5 text-xs font-mono rounded-lg transition-all ${
                tf === t ? "bg-blue-600 text-white" : "bg-zinc-800/60 text-zinc-500 hover:text-zinc-300"
              }`}>{t}</button>
          ))}
          <button onClick={refresh} className="ml-2 px-3 py-1.5 text-xs bg-zinc-800/60 text-zinc-500 hover:text-zinc-300 rounded-lg">Refresh</button>
        </div>
      </div>

      {err && <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 mb-4 text-red-400 text-sm">{err}</div>}

      <StatusBar r={risk} tradesCount={positions.length} />

      <div className="space-y-4">
        {/* Section 1: Live Trades — most prominent */}
        <LiveTrades positions={positions} onClose={handleClose} summary={tradeSummary} />

        {/* Section 2: Markets */}
        {loading ? (
          <Card><div className="p-8 text-center text-zinc-600">Loading markets...</div></Card>
        ) : (
          <Markets items={overview} selected={selected} onSelect={setSelected} />
        )}

        {/* Section 3: Selected Market Detail (signals + AI) */}
        <MarketDetail scan={detail} evalData={evalData} evalLoading={evalLoading} onEvaluate={handleEvaluate} />

        {/* Section 4: Tools */}
        <ToolsSection selected={selected} tf={tf} />
      </div>
    </main>
  );
}
