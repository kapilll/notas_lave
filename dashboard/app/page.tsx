"use client";

import { useEffect, useState, useCallback } from "react";
import dynamic from "next/dynamic";
import type { ScanResult } from "@/lib/api";
import { STRATEGY_INFO, REGIME_INFO } from "@/lib/strategy-info";

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

// -- Info Tooltip --

function InfoTip({ info }: { info: { howItWorks: string; bestFor: string; avoid: string; winRate: string; riskReward: string } }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-block">
      <button onClick={() => setOpen(!open)} className="text-zinc-600 hover:text-blue-400 text-[10px] ml-1 transition-colors">?</button>
      {open && (
        <div className="absolute z-50 left-0 top-5 w-72 bg-zinc-800 border border-zinc-700 rounded-lg p-3 shadow-xl text-xs text-zinc-300 space-y-2">
          <div><span className="text-zinc-500">How: </span>{info.howItWorks}</div>
          <div><span className="text-emerald-400/70">Best for: </span>{info.bestFor}</div>
          <div><span className="text-red-400/70">Avoid: </span>{info.avoid}</div>
          <div className="flex gap-4"><span>WR: {info.winRate}</span><span>R:R: {info.riskReward}</span></div>
          <button onClick={() => setOpen(false)} className="text-zinc-500 hover:text-zinc-300">close</button>
        </div>
      )}
    </span>
  );
}

// -- Signal Detail --

function SignalDetail({ scan }: { scan: ScanResult | null }) {
  if (!scan) return <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 text-center text-zinc-500">Select an instrument to view signals</div>;

  const regimeInfo = REGIME_INFO[scan.regime];

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">Strategy Signals</h3>
          <div className="text-xs text-zinc-500 mt-0.5">
            {scan.timeframe} | {regimeMap[scan.regime] || scan.regime} | {scan.agreeing_strategies}/{scan.total_strategies} agree
          </div>
          {regimeInfo && (
            <div className="text-[10px] text-zinc-600 mt-1">
              {regimeInfo.description} Best: {regimeInfo.bestStrategies.split(",")[0]}
            </div>
          )}
        </div>
        <div className={`px-3 py-1.5 rounded-lg border ${dirBg(scan.direction)}`}>
          <div className={`text-xl font-mono font-bold ${dirColor(scan.direction)}`}>{scan.composite_score.toFixed(1)}</div>
        </div>
      </div>
      <div className="space-y-2">
        {scan.signals.map((sig, i) => {
          const info = STRATEGY_INFO[sig.strategy];
          return (
            <div key={i} className={`border rounded-lg p-2.5 ${sig.direction ? dirBg(sig.direction) : "bg-zinc-800/50 border-zinc-700/50"}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium">
                    {info?.displayName || sig.strategy.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())}
                  </span>
                  {info && <InfoTip info={info} />}
                  {info && <span className="text-[9px] text-zinc-600">{info.category}</span>}
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
          );
        })}
      </div>
    </div>
  );
}

// -- Tools Panel --

function ToolsPanel({ selected, tf }: { selected: string | null; tf: string }) {
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const tools = [
    { id: "backtest", label: "Backtest", desc: "Test strategies on historical data for selected instrument", needsSymbol: true },
    { id: "journal", label: "Signal Journal", desc: "View all past evaluations and Claude decisions", needsSymbol: false },
    { id: "trades", label: "Trade History", desc: "View closed trades with P&L and exit reasons", needsSymbol: false },
    { id: "performance", label: "Strategy Performance", desc: "Which strategies contribute most to wins/losses", needsSymbol: false },
    { id: "strategies", label: "Strategy Guide", desc: "Learn about all 14 strategies, when to use them, what to avoid", needsSymbol: false },
    { id: "learning", label: "AI Insights", desc: "Learning engine analysis — strategy performance by instrument, regime, hour", needsSymbol: false },
    { id: "recommendations", label: "Recommendations", desc: "AI-generated suggestions for weight adjustments and strategy tuning", needsSymbol: false },
    { id: "calendar", label: "News Calendar", desc: "Upcoming economic events and news blackout status", needsSymbol: false },
    { id: "review", label: "Weekly Review", desc: "Claude AI analyzes your trades and sends report via Telegram", needsSymbol: false },
    { id: "optimize", label: "Optimize", desc: "Run walk-forward parameter optimization for selected instrument", needsSymbol: true },
    { id: "accuracy", label: "Prediction Accuracy", desc: "ML-style accuracy score — are our predictions getting better?", needsSymbol: false },
    { id: "costs", label: "Token Costs", desc: "Claude API token usage and costs — runtime vs build", needsSymbol: false },
    { id: "test-alert", label: "Test Telegram", desc: "Send a test message to verify Telegram alerts work", needsSymbol: false },
    { id: "scan-now", label: "Scan Now", desc: "Manually trigger one scan cycle across all instruments", needsSymbol: false },
    { id: "alert-status", label: "Alert Status", desc: "Check if the background alert scanner is running", needsSymbol: false },
  ];

  const runTool = async (toolId: string) => {
    setActiveTab(toolId);
    if (toolId === "strategies") { setResult(null); return; }

    // POST endpoints
    if (toolId === "test-alert" || toolId === "scan-now" || toolId === "review" || toolId === "optimize") {
      setLoading(true);
      setResult(null);
      try {
        const postUrls: Record<string, string> = {
          "test-alert": `${ENGINE}/api/alerts/test`,
          "scan-now": `${ENGINE}/api/alerts/scan-now`,
          "review": `${ENGINE}/api/learning/review`,
          "optimize": `${ENGINE}/api/learning/optimize/${selected}?timeframe=${tf}`,
        };
        const url = postUrls[toolId];
        const res = await fetch(url, { method: "POST" });
        setResult(await res.json());
      } catch { setResult({ error: "Failed" }); }
      finally { setLoading(false); }
      return;
    }

    setLoading(true);
    setResult(null);
    try {
      const urls: Record<string, string> = {
        backtest: `${ENGINE}/api/backtest/${selected}?timeframe=${tf}`,
        "alert-status": `${ENGINE}/api/alerts/status`,
        journal: `${ENGINE}/api/journal/signals?limit=20`,
        trades: `${ENGINE}/api/journal/trades?limit=20`,
        performance: `${ENGINE}/api/journal/performance`,
        learning: `${ENGINE}/api/learning/analysis`,
        recommendations: `${ENGINE}/api/learning/recommendations`,
        calendar: `${ENGINE}/api/calendar/status`,
        accuracy: `${ENGINE}/api/accuracy/score`,
        costs: `${ENGINE}/api/costs/summary`,
      };
      const res = await fetch(urls[toolId]);
      setResult(await res.json());
    } catch { setResult({ error: "Failed to fetch" }); }
    finally { setLoading(false); }
  };

  return (
    <div className="mt-6">
      <h2 className="text-sm font-medium text-zinc-500 uppercase tracking-wider mb-3">Tools</h2>
      <div className="flex flex-wrap gap-2 mb-4">
        {tools.map((t) => (
          <button
            key={t.id}
            onClick={() => runTool(t.id)}
            disabled={t.needsSymbol && !selected}
            title={t.desc}
            className={`px-3 py-2 text-xs rounded-lg border transition-all ${
              activeTab === t.id ? "bg-blue-600 border-blue-500 text-white" :
              t.needsSymbol && !selected ? "bg-zinc-900 border-zinc-800 text-zinc-600 cursor-not-allowed" :
              "bg-zinc-900 border-zinc-800 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
            }`}
          >
            <div className="font-medium">{t.label}</div>
            <div className="text-[10px] mt-0.5 opacity-60">{t.desc.slice(0, 50)}</div>
          </button>
        ))}
      </div>

      {activeTab && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
          {loading && <div className="text-zinc-500 text-sm">Loading...</div>}

          {activeTab === "strategies" && (
            <div className="space-y-4">
              <h3 className="text-sm font-bold">Strategy Guide — All 14 Strategies</h3>
              {Object.values(STRATEGY_INFO).map((s) => (
                <div key={s.name} className="border border-zinc-800 rounded-lg p-3 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold">{s.displayName}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">{s.category}</span>
                  </div>
                  <div className="text-xs text-zinc-400">{s.description}</div>
                  <div className="text-xs text-zinc-300"><span className="text-zinc-500">How: </span>{s.howItWorks}</div>
                  <div className="text-xs"><span className="text-emerald-400/70">Best for: </span>{s.bestFor}</div>
                  <div className="text-xs"><span className="text-red-400/70">Avoid: </span>{s.avoid}</div>
                  <div className="flex gap-4 text-xs text-zinc-400">
                    <span>Win Rate: {s.winRate}</span>
                    <span>R:R: {s.riskReward}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {activeTab === "backtest" && result && !loading && (
            <div className="space-y-3">
              <h3 className="text-sm font-bold">Backtest Results — {(result as Record<string, unknown>).symbol as string} {(result as Record<string, unknown>).timeframe as string}</h3>
              {(result as Record<string, unknown>).error ? (
                <div className="text-red-400 text-sm">{(result as Record<string, unknown>).error as string}</div>
              ) : (
                <>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                    {[
                      { l: "Period", v: result.period as string },
                      { l: "Trades", v: String(result.total_trades) },
                      { l: "Win Rate", v: `${result.win_rate}%`, c: (result.win_rate as number) >= 50 ? "text-emerald-400" : "text-red-400" },
                      { l: "Net P&L", v: `$${(result.net_pnl as number)?.toLocaleString()}`, c: (result.net_pnl as number) >= 0 ? "text-emerald-400" : "text-red-400" },
                      { l: "Profit Factor", v: String(result.profit_factor), c: (result.profit_factor as number) >= 1.5 ? "text-emerald-400" : "text-yellow-400" },
                      { l: "Max Drawdown", v: `${result.max_drawdown_pct}%`, c: (result.max_drawdown_pct as number) <= 10 ? "text-emerald-400" : "text-red-400" },
                      { l: "Sharpe", v: String(result.sharpe_ratio) },
                      { l: "Expectancy", v: `$${result.expectancy}/trade` },
                    ].map((m) => (
                      <div key={m.l} className="bg-zinc-800/50 rounded p-2">
                        <div className="text-[10px] text-zinc-500 uppercase">{m.l}</div>
                        <div className={`font-mono font-bold ${m.c || ""}`}>{m.v}</div>
                      </div>
                    ))}
                  </div>
                  {result.strategy_stats && (
                    <div>
                      <div className="text-xs text-zinc-500 uppercase mt-3 mb-1">Per-Strategy Breakdown</div>
                      {Object.entries(result.strategy_stats as Record<string, Record<string, number>>).map(([name, stats]) => (
                        <div key={name} className="flex items-center justify-between text-xs py-1 border-b border-zinc-800/50">
                          <span className="font-medium">{STRATEGY_INFO[name]?.displayName || name}</span>
                          <span className="font-mono">
                            {stats.trades} trades |
                            <span className={stats.win_rate >= 50 ? " text-emerald-400" : " text-red-400"}> {stats.win_rate}% WR</span> |
                            <span className={stats.pnl >= 0 ? " text-emerald-400" : " text-red-400"}> ${stats.pnl?.toLocaleString()}</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {activeTab === "journal" && result && !loading && (
            <div>
              <h3 className="text-sm font-bold mb-2">Signal Journal (Last 20)</h3>
              <div className="space-y-1 max-h-96 overflow-y-auto">
                {((result as Record<string, unknown>).signals as Array<Record<string, unknown>> || []).map((s, i) => (
                  <div key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-zinc-800/50">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{s.symbol as string}</span>
                      <span className={dirColor(s.direction as string)}>{s.direction as string || "—"}</span>
                      <span className="text-zinc-500">{s.regime as string}</span>
                    </div>
                    <div className="flex items-center gap-3 font-mono">
                      <span className={scoreCol(s.score as number)}>{(s.score as number)?.toFixed(1)}</span>
                      <span className={dirColor(s.claude_action as string)}>{s.claude_action as string}</span>
                      <span className={s.should_trade ? "text-emerald-400" : "text-zinc-600"}>{s.should_trade ? "TRADE" : "SKIP"}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === "trades" && result && !loading && (
            <div>
              <h3 className="text-sm font-bold mb-2">Trade History</h3>
              {((result as Record<string, unknown>).trades as Array<Record<string, unknown>> || []).length === 0 ? (
                <div className="text-zinc-500 text-sm">No trades yet. Evaluate setups and click &quot;Take This Trade&quot; to start.</div>
              ) : (
                <div className="space-y-1 max-h-96 overflow-y-auto">
                  {((result as Record<string, unknown>).trades as Array<Record<string, unknown>>).map((t, i) => (
                    <div key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-zinc-800/50">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{t.symbol as string}</span>
                        <span className={dirColor(t.direction as string)}>{t.direction as string}</span>
                        <span className="text-zinc-500">{t.exit_reason as string}</span>
                      </div>
                      <span className={`font-mono font-bold ${(t.pnl as number) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {(t.pnl as number) >= 0 ? "+" : ""}${(t.pnl as number)?.toFixed(2)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === "performance" && result && !loading && (
            <div>
              <h3 className="text-sm font-bold mb-2">Strategy Performance</h3>
              {((result as Record<string, unknown>).strategies as Array<Record<string, unknown>> || []).length === 0 ? (
                <div className="text-zinc-500 text-sm">No closed trades to analyze yet.</div>
              ) : (
                <div className="space-y-1">
                  {((result as Record<string, unknown>).strategies as Array<Record<string, unknown>>).map((s, i) => (
                    <div key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-zinc-800/50">
                      <span className="font-medium">{STRATEGY_INFO[s.strategy as string]?.displayName || s.strategy as string}</span>
                      <span className="font-mono">
                        {s.total_trades as number} trades |
                        <span className={(s.win_rate as number) >= 50 ? " text-emerald-400" : " text-red-400"}> {(s.win_rate as number)?.toFixed(1)}%</span> |
                        <span className={(s.total_pnl as number) >= 0 ? " text-emerald-400" : " text-red-400"}> ${(s.total_pnl as number)?.toFixed(2)}</span>
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {activeTab === "calendar" && result && !loading && (() => {
            const r = result as Record<string, unknown>;
            const events = (r.upcoming_events || []) as Array<Record<string, unknown>>;
            return (
              <div className="space-y-3">
                <h3 className="text-sm font-bold">News Calendar & Blackout Status</h3>
                <div className={`px-3 py-2 rounded text-sm font-medium ${r.is_blocked ? "bg-red-900/50 text-red-300" : "bg-emerald-900/30 text-emerald-300"}`}>
                  {r.is_blocked ? `BLACKOUT ACTIVE: ${(r.blocking_event as Record<string, unknown>)?.name}` : "No active blackout — trading allowed"}
                </div>
                <div className="text-xs text-zinc-500">Blackout window: {String(r.blackout_minutes)} min before/after HIGH impact events</div>
                <h4 className="text-xs font-bold text-zinc-400 mt-3">Upcoming Events</h4>
                <div className="space-y-1">
                  {events.map((e, i) => (
                    <div key={i} className="flex justify-between items-center text-xs border-b border-zinc-800 py-1.5">
                      <div>
                        <span className={`inline-block w-2 h-2 rounded-full mr-2 ${e.impact === "HIGH" ? "bg-red-500" : e.impact === "MEDIUM" ? "bg-yellow-500" : "bg-zinc-500"}`} />
                        <span className="text-zinc-200">{String(e.name)}</span>
                      </div>
                      <span className="text-zinc-500">{new Date(String(e.datetime)).toLocaleString()}</span>
                    </div>
                  ))}
                  {events.length === 0 && <div className="text-zinc-500 text-xs">No upcoming events</div>}
                </div>
              </div>
            );
          })()}

          {activeTab === "learning" && result && !loading && (() => {
            const r = result as Record<string, unknown>;
            const overall = ((r.overall as Record<string, unknown>)?.overall || {}) as Record<string, unknown>;
            const byInstrument = (r.by_instrument || {}) as Record<string, Record<string, Record<string, unknown>>>;
            return (
              <div className="space-y-4">
                <h3 className="text-sm font-bold">Learning Engine Analysis</h3>
                <div className="grid grid-cols-4 gap-3">
                  {[["Trades", overall.trades], ["Win Rate", `${overall.win_rate}%`], ["Profit Factor", overall.profit_factor], ["Net P&L", `$${Number(overall.total_pnl || 0).toFixed(2)}`]].map(([label, val]) => (
                    <div key={String(label)} className="bg-zinc-800/50 rounded p-2 text-center">
                      <div className="text-[10px] text-zinc-500">{String(label)}</div>
                      <div className="text-sm font-bold">{String(val)}</div>
                    </div>
                  ))}
                </div>
                <h4 className="text-xs font-bold text-zinc-400">Strategy x Instrument</h4>
                {Object.entries(byInstrument).map(([sym, strats]) => (
                  <div key={sym}>
                    <div className="text-xs font-medium text-zinc-300 mb-1">{sym}</div>
                    <div className="space-y-0.5">
                      {Object.entries(strats).sort((a, b) => Number((b[1] as Record<string, unknown>).total_pnl) - Number((a[1] as Record<string, unknown>).total_pnl)).map(([name, sRaw]) => {
                        const s = sRaw as Record<string, unknown>;
                        return (
                        <div key={name} className="flex justify-between text-xs">
                          <span className="text-zinc-400">{name}</span>
                          <span className={Number(s.total_pnl) >= 0 ? "text-emerald-400" : "text-red-400"}>
                            {String(s.trades)}t {String(s.win_rate)}% ${Number(s.total_pnl).toFixed(0)}
                          </span>
                        </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            );
          })()}

          {activeTab === "accuracy" && result && !loading && (() => {
            const r = result as Record<string, unknown>;
            if (r.status === "no_data") {
              return (
                <div className="space-y-3">
                  <h3 className="text-sm font-bold">Prediction Accuracy</h3>
                  <div className="text-sm text-zinc-500">{String(r.message)}</div>
                </div>
              );
            }
            const byStrategy = (r.by_strategy || {}) as Record<string, Record<string, unknown>>;
            const calibration = (r.calibration || {}) as Record<string, Record<string, unknown>>;
            const byRegime = (r.by_regime || {}) as Record<string, Record<string, unknown>>;
            const outcomes = (r.outcomes || {}) as Record<string, number>;
            return (
              <div className="space-y-5">
                <h3 className="text-sm font-bold">Prediction Accuracy Score</h3>

                {/* Main Score Cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Direction Accuracy</div>
                    <div className={`text-3xl font-mono font-bold mt-1 ${Number(r.direction_accuracy) >= 55 ? "text-emerald-400" : Number(r.direction_accuracy) >= 45 ? "text-yellow-400" : "text-red-400"}`}>
                      {String(r.direction_accuracy)}%
                    </div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">Price moved in predicted direction</div>
                  </div>
                  <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Target Accuracy</div>
                    <div className={`text-3xl font-mono font-bold mt-1 ${Number(r.target_accuracy) >= 40 ? "text-emerald-400" : Number(r.target_accuracy) >= 25 ? "text-yellow-400" : "text-red-400"}`}>
                      {String(r.target_accuracy)}%
                    </div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">TP hit before SL</div>
                  </div>
                  <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Total Predictions</div>
                    <div className="text-3xl font-mono font-bold mt-1">{String(r.total_predictions)}</div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">Last {String(r.period_days)} days</div>
                  </div>
                  <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Outcomes</div>
                    <div className="text-xs font-mono mt-2 space-y-1">
                      <div><span className="text-emerald-400">TP:</span> {outcomes.tp_hit || 0}</div>
                      <div><span className="text-red-400">SL:</span> {outcomes.sl_hit || 0}</div>
                      <div><span className="text-zinc-400">TO:</span> {outcomes.timeout || 0}</div>
                    </div>
                  </div>
                </div>

                {/* Score Calibration */}
                {Object.keys(calibration).length > 0 && (
                  <div>
                    <div className="text-xs font-bold text-zinc-400 mb-2">Score Calibration — Do higher scores predict better?</div>
                    <div className="space-y-1">
                      {Object.entries(calibration).map(([bucket, stats]) => {
                        const acc = Number((stats as Record<string, unknown>).direction_accuracy);
                        const width = Math.max(5, acc);
                        return (
                          <div key={bucket} className="flex items-center gap-2 text-xs">
                            <span className="w-12 text-right text-zinc-500 font-mono">{bucket}</span>
                            <div className="flex-1 bg-zinc-800 rounded-full h-4 overflow-hidden">
                              <div
                                className={`h-full rounded-full ${acc >= 55 ? "bg-emerald-500" : acc >= 45 ? "bg-yellow-500" : "bg-red-500"}`}
                                style={{ width: `${width}%` }}
                              />
                            </div>
                            <span className="w-16 text-right font-mono">{acc}%</span>
                            <span className="w-8 text-zinc-600">{String((stats as Record<string, unknown>).predictions)}t</span>
                          </div>
                        );
                      })}
                    </div>
                    <div className="text-[10px] text-zinc-600 mt-1">Bars should get longer as score increases. If they don&apos;t, the scoring system needs tuning.</div>
                  </div>
                )}

                {/* Per-Strategy Accuracy */}
                {Object.keys(byStrategy).length > 0 && (
                  <div>
                    <div className="text-xs font-bold text-zinc-400 mb-2">Per-Strategy Accuracy</div>
                    <div className="space-y-1">
                      {Object.entries(byStrategy).map(([name, stats]) => (
                        <div key={name} className="flex items-center justify-between text-xs py-1 border-b border-zinc-800/50">
                          <span className="font-medium">{STRATEGY_INFO[name]?.displayName || name}</span>
                          <span className="font-mono">
                            <span className={Number((stats as Record<string, unknown>).direction_accuracy) >= 55 ? "text-emerald-400" : "text-zinc-400"}>
                              {String((stats as Record<string, unknown>).direction_accuracy)}% dir
                            </span>
                            {" | "}
                            <span className={Number((stats as Record<string, unknown>).target_accuracy) >= 40 ? "text-emerald-400" : "text-zinc-400"}>
                              {String((stats as Record<string, unknown>).target_accuracy)}% tgt
                            </span>
                            {" | "}
                            <span className="text-zinc-500">{String((stats as Record<string, unknown>).total)}t</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Per-Regime Accuracy */}
                {Object.keys(byRegime).length > 0 && (
                  <div>
                    <div className="text-xs font-bold text-zinc-400 mb-2">Per-Regime Accuracy</div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                      {Object.entries(byRegime).map(([regime, stats]) => (
                        <div key={regime} className="bg-zinc-800/30 rounded p-2 text-center">
                          <div className="text-[10px] text-zinc-500">{regime}</div>
                          <div className={`text-lg font-mono font-bold ${Number((stats as Record<string, unknown>).accuracy) >= 55 ? "text-emerald-400" : "text-zinc-400"}`}>
                            {String((stats as Record<string, unknown>).accuracy)}%
                          </div>
                          <div className="text-[10px] text-zinc-600">{String((stats as Record<string, unknown>).total)} predictions</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Fetch accuracy history for the graph */}
                <AccuracyGraph />
              </div>
            );
          })()}

          {activeTab === "costs" && result && !loading && (() => {
            const r = result as Record<string, unknown>;
            const runtime = (r.runtime || {}) as Record<string, unknown>;
            const build = (r.build || {}) as Record<string, unknown>;
            const byPurpose = ((runtime.by_purpose || {}) as Record<string, Record<string, unknown>>);
            return (
              <div className="space-y-5">
                <h3 className="text-sm font-bold">Token Usage & Costs</h3>

                {/* Cost Summary Cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Runtime Cost</div>
                    <div className="text-2xl font-mono font-bold mt-1 text-blue-400">
                      ${Number(runtime.total_cost || 0).toFixed(4)}
                    </div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">{String(runtime.calls || 0)} API calls</div>
                  </div>
                  <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Build Cost</div>
                    <div className="text-2xl font-mono font-bold mt-1 text-purple-400">
                      ${Number(build.total_cost || 0).toFixed(2)}
                    </div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">{String(build.calls || 0)} sessions</div>
                  </div>
                  <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Total Cost</div>
                    <div className="text-2xl font-mono font-bold mt-1">
                      ${Number(r.total_cost || 0).toFixed(2)}
                    </div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">Last {String(r.period_days)} days</div>
                  </div>
                  <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Tokens Used</div>
                    <div className="text-lg font-mono font-bold mt-1">
                      {((Number(runtime.total_tokens_in || 0) + Number(runtime.total_tokens_out || 0)) / 1000).toFixed(1)}K
                    </div>
                    <div className="text-[10px] text-zinc-600 mt-0.5">
                      In: {(Number(runtime.total_tokens_in || 0) / 1000).toFixed(1)}K |
                      Out: {(Number(runtime.total_tokens_out || 0) / 1000).toFixed(1)}K
                    </div>
                  </div>
                </div>

                {/* Runtime Breakdown by Purpose */}
                {Object.keys(byPurpose).length > 0 && (
                  <div>
                    <div className="text-xs font-bold text-zinc-400 mb-2">Runtime Cost Breakdown</div>
                    <div className="space-y-1">
                      {Object.entries(byPurpose).sort((a, b) => Number(b[1].cost) - Number(a[1].cost)).map(([purpose, stats]) => (
                        <div key={purpose} className="flex items-center justify-between text-xs py-1.5 border-b border-zinc-800/50">
                          <span className="font-medium capitalize">{purpose.replace(/_/g, " ")}</span>
                          <span className="font-mono">
                            <span className="text-blue-400">${Number(stats.cost).toFixed(4)}</span>
                            {" | "}
                            <span className="text-zinc-400">{String(stats.calls)} calls</span>
                            {" | "}
                            <span className="text-zinc-500">{((Number(stats.tokens_in) + Number(stats.tokens_out)) / 1000).toFixed(1)}K tok</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Log Build Cost Button */}
                <div className="border border-zinc-700 rounded-lg p-3">
                  <div className="text-xs font-bold text-zinc-400 mb-2">Log Build Session Cost</div>
                  <div className="flex gap-2">
                    <input
                      id="build-cost-input"
                      type="number"
                      step="0.01"
                      placeholder="Cost in USD"
                      className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs font-mono text-zinc-200 w-24"
                    />
                    <input
                      id="build-desc-input"
                      type="text"
                      placeholder="Session description"
                      className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 flex-1"
                    />
                    <button
                      onClick={async () => {
                        const costEl = document.getElementById("build-cost-input") as HTMLInputElement;
                        const descEl = document.getElementById("build-desc-input") as HTMLInputElement;
                        const cost = parseFloat(costEl?.value || "0");
                        const desc = descEl?.value || "";
                        if (cost > 0) {
                          await fetch(`${ENGINE}/api/costs/log-build?cost=${cost}&description=${encodeURIComponent(desc)}`, { method: "POST" });
                          costEl.value = "";
                          descEl.value = "";
                          runTool("costs"); // Refresh
                        }
                      }}
                      className="px-3 py-1 text-xs bg-purple-600 hover:bg-purple-500 text-white rounded transition-colors"
                    >
                      Log
                    </button>
                  </div>
                </div>
              </div>
            );
          })()}

          {(activeTab === "recommendations" || activeTab === "review" || activeTab === "optimize") && result && !loading && (
            <div>
              <h3 className="text-sm font-bold mb-2">
                {activeTab === "recommendations" ? "AI Recommendations" : activeTab === "review" ? "Weekly Review" : "Optimization Results"}
              </h3>
              {activeTab === "review" && (result as Record<string, unknown>).review_text ? (
                <div className="text-xs text-zinc-300 whitespace-pre-wrap bg-zinc-800/50 rounded p-3 mb-3">
                  {String((result as Record<string, unknown>).review_text)}
                </div>
              ) : null}
              <pre className="text-xs bg-zinc-800/50 rounded p-3 overflow-auto text-zinc-300 max-h-96">
                {JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}

          {(activeTab === "test-alert" || activeTab === "scan-now" || activeTab === "alert-status") && result && !loading && (
            <div>
              <h3 className="text-sm font-bold mb-2">
                {activeTab === "test-alert" ? "Telegram Test" : activeTab === "scan-now" ? "Scan Results" : "Alert Scanner Status"}
              </h3>
              <pre className="text-xs bg-zinc-800/50 rounded p-3 overflow-auto text-zinc-300">
                {JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// -- Accuracy Graph (rolling accuracy over time) --

function AccuracyGraph() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    fetch(`${ENGINE}/api/accuracy/history?window=20`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (!data || (data as Record<string, unknown>).status !== "ready") {
    return (
      <div className="text-xs text-zinc-500 mt-2">
        {(data as Record<string, unknown>)?.message as string || "Loading accuracy history..."}
      </div>
    );
  }

  const points = ((data as Record<string, unknown>).points || []) as Array<Record<string, unknown>>;
  const trend = (data as Record<string, unknown>).trend as string;
  const firstAvg = Number((data as Record<string, unknown>).first_half_avg || 0);
  const secondAvg = Number((data as Record<string, unknown>).second_half_avg || 0);

  if (points.length < 2) return null;

  // Simple SVG sparkline chart
  const width = 600;
  const height = 120;
  const padding = 20;
  const chartW = width - padding * 2;
  const chartH = height - padding * 2;

  const minAcc = Math.max(0, Math.min(...points.map((p) => Number(p.direction_accuracy))) - 5);
  const maxAcc = Math.min(100, Math.max(...points.map((p) => Number(p.direction_accuracy))) + 5);
  const range = maxAcc - minAcc || 1;

  const toX = (i: number) => padding + (i / (points.length - 1)) * chartW;
  const toY = (v: number) => padding + chartH - ((v - minAcc) / range) * chartH;

  const dirPath = points.map((p, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(Number(p.direction_accuracy)).toFixed(1)}`).join(" ");
  const tgtPath = points.map((p, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(Number(p.target_accuracy)).toFixed(1)}`).join(" ");

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs font-bold text-zinc-400">Accuracy Trend (rolling {String((data as Record<string, unknown>).window_size)} predictions)</div>
        <div className={`text-xs font-mono px-2 py-0.5 rounded ${
          trend === "improving" ? "bg-emerald-500/20 text-emerald-400" :
          trend === "declining" ? "bg-red-500/20 text-red-400" :
          "bg-zinc-800 text-zinc-400"
        }`}>
          {trend === "improving" ? "IMPROVING" : trend === "declining" ? "DECLINING" : "STABLE"}
          {trend !== "insufficient_data" && ` (${firstAvg}% -> ${secondAvg}%)`}
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full bg-zinc-800/30 rounded-lg">
        {/* 50% reference line */}
        <line x1={padding} y1={toY(50)} x2={width - padding} y2={toY(50)} stroke="#52525b" strokeWidth="0.5" strokeDasharray="4,4" />
        <text x={padding - 2} y={toY(50) + 3} textAnchor="end" fill="#71717a" fontSize="8">50%</text>

        {/* Target accuracy line (dimmer) */}
        <path d={tgtPath} fill="none" stroke="#a78bfa" strokeWidth="1.5" opacity="0.4" />

        {/* Direction accuracy line (primary) */}
        <path d={dirPath} fill="none" stroke="#34d399" strokeWidth="2" />

        {/* Data points on direction line */}
        {points.filter((_, i) => i % Math.max(1, Math.floor(points.length / 10)) === 0 || i === points.length - 1).map((p, i) => (
          <circle key={i} cx={toX(points.indexOf(p))} cy={toY(Number(p.direction_accuracy))} r="2.5" fill="#34d399" />
        ))}

        {/* Legend */}
        <line x1={width - 150} y1={10} x2={width - 135} y2={10} stroke="#34d399" strokeWidth="2" />
        <text x={width - 130} y={13} fill="#a1a1aa" fontSize="8">Direction</text>
        <line x1={width - 80} y1={10} x2={width - 65} y2={10} stroke="#a78bfa" strokeWidth="1.5" opacity="0.4" />
        <text x={width - 60} y={13} fill="#a1a1aa" fontSize="8">Target</text>
      </svg>
      <div className="text-[10px] text-zinc-600 mt-1">
        Green line: % of times price moved in predicted direction. Purple: % TP hit before SL. Goal: both lines trending up.
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

      {/* Tools Panel */}
      <ToolsPanel selected={selected} tf={tf} />

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
