"use client";

import { useEffect, useState, useCallback } from "react";
import type { ScanResult } from "@/lib/api";
import { STRATEGY_INFO, REGIME_INFO } from "@/lib/strategy-info";

const ENGINE = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8000";

// =============================================================
// TYPES
// =============================================================

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

type TabId = "lab" | "command" | "evolution";

// =============================================================
// HELPERS
// =============================================================

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

const REGIMES: Record<string, { icon: string; color: string; gradient: string }> = {
  TRENDING: { icon: "\u2197", color: "text-blue-400", gradient: "from-blue-500/20 to-blue-900/5" },
  RANGING: { icon: "\u2194", color: "text-amber-400", gradient: "from-amber-500/20 to-amber-900/5" },
  VOLATILE: { icon: "\u26A1", color: "text-red-400", gradient: "from-red-500/20 to-red-900/5" },
  QUIET: { icon: "\uD83D\uDD15", color: "text-zinc-500", gradient: "from-zinc-500/10 to-zinc-900/5" },
};

// =============================================================
// CARD: Base wrapper
// =============================================================

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`bg-zinc-900/80 border border-zinc-800 rounded-xl backdrop-blur-sm ${className}`}>{children}</div>;
}
function CardHeader({ children }: { children: React.ReactNode }) {
  return <div className="px-5 py-3 border-b border-zinc-800/60 flex items-center justify-between">{children}</div>;
}
function SectionTitle({ children, icon }: { children: React.ReactNode; icon?: string }) {
  return <h2 className="text-xs font-semibold text-zinc-200 uppercase tracking-widest flex items-center gap-2">{icon && <span>{icon}</span>}{children}</h2>;
}

// =============================================================
// HEADER
// =============================================================

function Header({ activeTab, onTabChange, costs, engineOnline }: {
  activeTab: TabId;
  onTabChange: (t: TabId) => void;
  costs: number;
  engineOnline: boolean;
}) {
  const tabs: { id: TabId; label: string; emoji: string; accent: string; activeBg: string }[] = [
    { id: "lab", label: "LAB", emoji: "\uD83E\uDDEA", accent: "text-violet-400", activeBg: "bg-violet-600 shadow-violet-500/30" },
    { id: "command", label: "COMMAND", emoji: "\uD83C\uDFAF", accent: "text-blue-400", activeBg: "bg-blue-600 shadow-blue-500/30" },
    { id: "evolution", label: "EVOLUTION", emoji: "\uD83E\uDDEC", accent: "text-emerald-400", activeBg: "bg-emerald-600 shadow-emerald-500/30" },
  ];

  return (
    <header className="flex flex-col sm:flex-row items-start sm:items-center justify-between mb-5 gap-4">
      <div className="flex items-center gap-4">
        <div>
          <h1 className="text-2xl font-black tracking-tight bg-gradient-to-r from-violet-400 via-blue-400 to-cyan-400 bg-clip-text text-transparent">
            NOTAS LAVE
          </h1>
          <p className="text-[10px] text-zinc-500 uppercase tracking-[0.2em] -mt-0.5">Not a Slave</p>
        </div>
      </div>

      {/* Tab Pills */}
      <div className="flex items-center gap-2 bg-zinc-900/80 border border-zinc-800 rounded-full p-1">
        {tabs.map((tab) => (
          <button key={tab.id} onClick={() => onTabChange(tab.id)}
            className={`px-4 py-2 text-xs font-bold rounded-full transition-all duration-300 flex items-center gap-1.5 ${
              activeTab === tab.id
                ? `${tab.activeBg} text-white shadow-lg`
                : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60"
            }`}>
            <span>{tab.emoji}</span>
            <span className="hidden sm:inline">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Right side badges */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 bg-zinc-900/80 border border-zinc-800 rounded-full px-3 py-1.5">
          <span className="text-[10px] text-zinc-500">COST</span>
          <span className="text-xs font-mono font-bold text-amber-400">${costs.toFixed(2)}</span>
        </div>
        <div className="flex items-center gap-1.5 bg-zinc-900/80 border border-zinc-800 rounded-full px-3 py-1.5">
          <span className={`w-2 h-2 rounded-full ${engineOnline ? "bg-emerald-500 animate-pulse" : "bg-red-500"}`} />
          <span className="text-[10px] text-zinc-400">{engineOnline ? "ENGINE" : "OFFLINE"}</span>
        </div>
      </div>
    </header>
  );
}

// =============================================================
// TAB 1: LAB  (Purple/Violet theme)
// =============================================================

function LabTab({ risk, positions, labTrades, stratPerf, overview, selected, onSelect, tf, onClose }: {
  risk: RiskStatus | null;
  positions: Array<Record<string, unknown>>;
  labTrades: Array<Record<string, unknown>>;
  stratPerf: Array<Record<string, unknown>>;
  overview: ScanOverview[];
  selected: string | null;
  onSelect: (s: string) => void;
  tf: string;
  onClose: (id: string) => void;
}) {
  // Sort strategies by win rate descending
  const ranked = [...stratPerf].sort((a, b) => Number(b.win_rate || 0) - Number(a.win_rate || 0));

  return (
    <div className="space-y-4 animate-in fade-in duration-300">
      {/* Status Bar */}
      {risk && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Lab Balance", value: `$${risk.balance.toLocaleString()}`, color: "text-violet-300", icon: "\uD83D\uDCB0" },
            { label: "Trades Today", value: String(risk.trades_today), color: "text-violet-300", icon: "\uD83D\uDCC8" },
            { label: "Win Rate", value: labTrades.length > 0 ? `${((labTrades.filter(t => Number(t.pnl) > 0).length / labTrades.length) * 100).toFixed(0)}%` : "--", color: "text-violet-300", icon: "\uD83C\uDFAF" },
            { label: "Total P&L", value: pnlSign(risk.total_pnl), color: pnlColor(risk.total_pnl).replace("text-", "text-"), icon: risk.total_pnl >= 0 ? "\uD83D\uDD25" : "\u2744\uFE0F" },
          ].map((stat) => (
            <div key={stat.label} className="bg-gradient-to-br from-violet-500/10 to-zinc-900/50 border border-violet-500/20 rounded-xl p-4">
              <div className="text-[10px] text-zinc-400 uppercase tracking-wider flex items-center gap-1">
                <span>{stat.icon}</span>{stat.label}
              </div>
              <div className={`text-xl font-mono font-bold mt-1 ${stat.color}`}>{stat.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Strategy Leaderboard + Live Feed */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Strategy Leaderboard */}
        <Card className="border-violet-500/20">
          <CardHeader>
            <SectionTitle icon={"\uD83C\uDFC6"}>Strategy Leaderboard</SectionTitle>
            <span className="text-[10px] text-zinc-500">{ranked.length} strategies</span>
          </CardHeader>
          <div className="p-4 space-y-2 max-h-[320px] overflow-y-auto">
            {ranked.length === 0 ? (
              <div className="text-center py-8 text-zinc-600 text-sm">No strategy data yet. Run some trades!</div>
            ) : ranked.map((s, i) => {
              const wr = Number(s.win_rate || 0);
              const barColor = wr >= 55 ? "bg-emerald-500" : wr >= 45 ? "bg-amber-500" : "bg-red-500";
              const medal = i === 0 ? "\uD83E\uDD47" : i === 1 ? "\uD83E\uDD48" : i === 2 ? "\uD83E\uDD49" : `#${i + 1}`;
              return (
                <div key={s.strategy as string} className="group">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm w-7 text-right">{medal}</span>
                      <span className="text-xs font-medium text-zinc-200">
                        {STRATEGY_INFO[s.strategy as string]?.displayName || s.strategy as string}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-xs font-mono">
                      <span className={pnlColor(Number(s.total_pnl || 0))}>{pnlSign(Number(s.total_pnl || 0))}</span>
                      <span className={wr >= 55 ? "text-emerald-400" : wr >= 45 ? "text-amber-400" : "text-red-400"}>{wr.toFixed(0)}%</span>
                    </div>
                  </div>
                  <div className="w-full bg-zinc-800 rounded-full h-2 overflow-hidden">
                    <div className={`h-full rounded-full transition-all duration-500 ${barColor}`}
                      style={{ width: `${Math.max(5, wr)}%` }} />
                  </div>
                  <div className="text-[10px] text-zinc-600 mt-0.5">{s.wins as number}W / {s.losses as number}L | {s.total_trades as number} trades</div>
                </div>
              );
            })}
          </div>
        </Card>

        {/* Live Trade Feed */}
        <Card className="border-violet-500/20">
          <CardHeader>
            <SectionTitle icon={"\u26A1"}>Live Feed</SectionTitle>
            <span className="text-[10px] text-zinc-500">{labTrades.length} recent</span>
          </CardHeader>
          <div className="p-4 space-y-1.5 max-h-[320px] overflow-y-auto">
            {labTrades.length === 0 ? (
              <div className="text-center py-8 text-zinc-600 text-sm">Waiting for trades...</div>
            ) : labTrades.slice(0, 30).map((t, i) => {
              const pnl = Number(t.pnl || 0);
              const isWin = pnl > 0;
              return (
                <div key={i} className={`flex items-center justify-between py-2 px-3 rounded-lg transition-all ${
                  isWin ? "bg-emerald-500/5 hover:bg-emerald-500/10" : "bg-red-500/5 hover:bg-red-500/10"
                }`}>
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{isWin ? "\u2705" : "\u274C"}</span>
                    <span className="text-xs font-medium text-zinc-200">{t.symbol as string}</span>
                    <span className={`text-[10px] font-bold ${dir(t.direction as string).text}`}>{t.direction as string}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[10px] text-zinc-600">{t.exit_reason as string || ""}</span>
                    <span className={`text-sm font-mono font-bold ${pnlColor(pnl)}`}>{pnlSign(pnl)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      {/* Open Positions */}
      <Card className="border-violet-500/20">
        <CardHeader>
          <SectionTitle icon={"\uD83D\uDCCA"}>Open Positions</SectionTitle>
          {positions.length > 0 && (
            <span className="text-xs font-mono bg-violet-500/20 text-violet-400 px-2 py-0.5 rounded-full animate-pulse">{positions.length} live</span>
          )}
        </CardHeader>
        <div className="p-4">
          {positions.length === 0 ? (
            <div className="text-center py-6 text-zinc-600">
              <div className="text-2xl mb-2">{"\uD83D\uDD2D"}</div>
              <div className="text-sm">No open positions. The agent is scanning for opportunities...</div>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {positions.map((p) => {
                const d = dir(p.direction as string);
                const pnl = Number(p.unrealized_pnl || 0);
                const isProfit = pnl >= 0;
                return (
                  <div key={p.id as string} className={`rounded-xl p-4 border-2 transition-all ${
                    isProfit ? "border-emerald-500/40 bg-gradient-to-br from-emerald-500/10 to-zinc-900/50" : "border-red-500/40 bg-gradient-to-br from-red-500/10 to-zinc-900/50"
                  }`}>
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <span className="text-base font-bold text-zinc-100">{p.symbol as string}</span>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${d.text} bg-zinc-800/60`}>{d.label}</span>
                      </div>
                      <div className={`text-xl font-mono font-bold ${pnlColor(pnl)}`}>{pnlSign(pnl)}</div>
                    </div>
                    {Number(p.entry_price) > 0 && Number(p.take_profit) > 0 && Number(p.stop_loss) > 0 && (
                      <div className="mb-3">
                        <div className="w-full bg-zinc-800 rounded-full h-1.5 overflow-hidden">
                          <div className={`h-full rounded-full transition-all duration-500 ${isProfit ? "bg-emerald-500" : "bg-red-500"}`}
                            style={{ width: `${Math.min(100, Math.max(0, ((Number(p.current_price) - Number(p.entry_price)) / (Number(p.take_profit) - Number(p.entry_price))) * 100))}%` }} />
                        </div>
                        <div className="flex justify-between text-[9px] text-zinc-600 mt-0.5">
                          <span>SL {(p.stop_loss as number).toFixed(2)}</span>
                          <span>Entry {(p.entry_price as number).toFixed(2)}</span>
                          <span>TP {(p.take_profit as number).toFixed(2)}</span>
                        </div>
                      </div>
                    )}
                    <div className="flex items-center justify-between">
                      <div className="flex gap-3 text-[11px] font-mono text-zinc-400">
                        <span>Now <span className="text-zinc-200">{Number(p.current_price || 0).toFixed(2)}</span></span>
                        <span>Score <span className="text-zinc-200">{Number(p.confluence_score || 0).toFixed(1)}</span></span>
                      </div>
                      <button onClick={() => onClose(p.id as string)}
                        className="px-3 py-1 text-[10px] bg-zinc-700 hover:bg-red-600 text-zinc-400 hover:text-white rounded-lg transition-all font-medium">
                        Close
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Card>

      {/* Markets */}
      <Card className="border-violet-500/20">
        <CardHeader><SectionTitle icon={"\uD83C\uDF0D"}>Markets</SectionTitle></CardHeader>
        <div className="p-4 grid grid-cols-2 lg:grid-cols-4 gap-3">
          {overview.map((item) => {
            const d = dir(item.direction);
            const regime = REGIMES[item.regime] || { icon: "?", color: "text-zinc-500", gradient: "from-zinc-500/10 to-zinc-900/5" };
            const isSelected = selected === item.symbol;
            return (
              <button key={item.symbol} onClick={() => onSelect(item.symbol)}
                className={`text-left rounded-xl p-4 border-2 transition-all hover:scale-[1.02] bg-gradient-to-br ${regime.gradient} ${
                  isSelected ? "border-violet-500 ring-2 ring-violet-500/30 shadow-lg shadow-violet-500/10" : "border-zinc-800 hover:border-zinc-600"
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
    </div>
  );
}

// =============================================================
// TAB 2: COMMAND CENTER  (Blue theme)
// =============================================================

function CommandTab({ risk, positions, overview, selected, onSelect, detail, evalData, evalLoading, onEvaluate, tf, onClose }: {
  risk: RiskStatus | null;
  positions: Array<Record<string, unknown>>;
  overview: ScanOverview[];
  selected: string | null;
  onSelect: (s: string) => void;
  detail: ScanResult | null;
  evalData: EvalResult | null;
  evalLoading: boolean;
  onEvaluate: () => void;
  tf: string;
  onClose: (id: string) => void;
}) {
  const [toolResult, setToolResult] = useState<Record<string, unknown> | null>(null);
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [toolLoading, setToolLoading] = useState(false);

  const tools = [
    { id: "backtest", label: "\uD83D\uDD2C Backtest", url: `/api/backtest/${selected}?timeframe=${tf}`, needsSymbol: true },
    { id: "walkforward", label: "\uD83E\uDDEA Walk-Forward", url: `/api/backtest/walk-forward/${selected}?timeframe=${tf}`, needsSymbol: true },
    { id: "montecarlo", label: "\uD83C\uDFB2 Monte Carlo", url: `/api/backtest/monte-carlo/${selected}?timeframe=${tf}`, needsSymbol: true },
    { id: "accuracy", label: "\uD83C\uDFAF Accuracy", url: "/api/accuracy/score" },
    { id: "calendar", label: "\uD83D\uDCC5 Calendar", url: "/api/calendar/status" },
    { id: "agent", label: "\uD83E\uDD16 Agent", url: "/api/agent/status" },
  ];

  const runTool = async (tool: typeof tools[0]) => {
    if (activeTool === tool.id) { setActiveTool(null); setToolResult(null); return; }
    setActiveTool(tool.id); setToolLoading(true); setToolResult(null);
    try {
      const res = await fetch(`${ENGINE}${tool.url}`);
      setToolResult(await res.json());
    } catch { setToolResult({ error: "Failed to connect" }); }
    finally { setToolLoading(false); }
  };

  return (
    <div className="space-y-4 animate-in fade-in duration-300">
      {/* Status Bar */}
      {risk && (
        <div className="flex flex-wrap items-center gap-4 text-sm bg-gradient-to-r from-blue-500/10 to-zinc-900/50 border border-blue-500/20 rounded-xl px-5 py-3">
          <div className="flex items-center gap-2">
            <span className={`w-2.5 h-2.5 rounded-full ${risk.is_halted ? "bg-red-500" : risk.can_trade ? "bg-emerald-500" : "bg-amber-500"} animate-pulse`} />
            <span className="text-zinc-300 font-medium">{risk.is_halted ? "HALTED" : risk.can_trade ? "READY" : "LIMIT"}</span>
          </div>
          <div className="h-4 w-px bg-zinc-700" />
          <div><span className="text-zinc-500 text-xs">Balance</span><span className="ml-2 font-mono font-bold text-zinc-50">${risk.balance.toLocaleString()}</span></div>
          <div><span className="text-zinc-500 text-xs">DD</span><span className={`ml-2 font-mono font-bold ${risk.daily_drawdown_used_pct > 60 ? "text-red-400" : risk.daily_drawdown_used_pct > 30 ? "text-amber-400" : "text-emerald-400"}`}>{risk.daily_drawdown_used_pct.toFixed(0)}%</span></div>
          <div><span className="text-zinc-500 text-xs">Daily</span><span className={`ml-2 font-mono font-bold ${pnlColor(risk.daily_pnl)}`}>{pnlSign(risk.daily_pnl)}</span></div>
          <div className="ml-auto text-zinc-500 text-xs">{positions.length} positions | {risk.trades_today} trades today</div>
        </div>
      )}

      {/* Open Positions */}
      {positions.length > 0 && (
        <Card className="border-blue-500/20">
          <CardHeader>
            <SectionTitle icon={"\uD83D\uDCCA"}>Open Positions</SectionTitle>
            <span className="text-xs font-mono bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded-full">{positions.length} open</span>
          </CardHeader>
          <div className="p-4 space-y-2">
            {positions.map((p) => {
              const d = dir(p.direction as string);
              const pnl = Number(p.unrealized_pnl || 0);
              return (
                <div key={p.id as string} className={`border rounded-lg p-4 ${d.bg} transition-all`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="font-bold text-zinc-100">{p.symbol as string}</span>
                      <span className={`text-xs font-bold px-2 py-0.5 rounded ${d.text} bg-zinc-800/60`}>{d.label}</span>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className={`text-xl font-mono font-bold ${pnlColor(pnl)}`}>{pnlSign(pnl)}</span>
                      <button onClick={() => onClose(p.id as string)} className="px-3 py-1.5 text-xs bg-zinc-700 hover:bg-red-600 text-zinc-300 hover:text-white rounded-lg transition-all font-medium">Close</button>
                    </div>
                  </div>
                  <div className="flex gap-5 mt-2 text-xs font-mono">
                    <span className="text-zinc-400">Entry <span className="text-zinc-200">{Number(p.entry_price || 0).toFixed(2)}</span></span>
                    <span className="text-zinc-400">SL <span className="text-red-400">{Number(p.stop_loss || 0).toFixed(2)}</span></span>
                    <span className="text-zinc-400">TP <span className="text-emerald-400">{Number(p.take_profit || 0).toFixed(2)}</span></span>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* Markets + Signal Detail */}
      <Card className="border-blue-500/20">
        <CardHeader><SectionTitle icon={"\uD83C\uDF0D"}>Markets & Signals</SectionTitle></CardHeader>
        <div className="p-4 grid grid-cols-2 lg:grid-cols-4 gap-3">
          {overview.map((item) => {
            const d = dir(item.direction);
            const regime = REGIMES[item.regime] || { icon: "?", color: "text-zinc-500", gradient: "from-zinc-500/10 to-zinc-900/5" };
            const isSelected = selected === item.symbol;
            return (
              <button key={item.symbol} onClick={() => onSelect(item.symbol)}
                className={`text-left rounded-xl p-4 border transition-all bg-gradient-to-br ${regime.gradient} ${
                  isSelected ? "border-blue-500 ring-1 ring-blue-500/20" : "border-zinc-800 hover:border-zinc-600"
                }`}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-bold text-zinc-100">{item.symbol}</span>
                  <span className={`text-lg font-mono font-bold ${scoreColor(item.score)}`}>{item.score.toFixed(1)}</span>
                </div>
                <div className="text-base font-mono text-zinc-200">${item.price?.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? "..."}</div>
                <div className="flex items-center justify-between mt-1 text-xs">
                  <span className={d.text + " font-medium"}>{d.label}</span>
                  <span className={regime.color}>{regime.icon} {item.regime}</span>
                </div>
              </button>
            );
          })}
        </div>
      </Card>

      {/* Signal Detail Panel */}
      {detail && detail.signals && (
        <Card className="border-blue-500/20">
          <CardHeader>
            <div className="flex items-center gap-3">
              <SectionTitle>{detail.symbol} Signals</SectionTitle>
              <span className="text-xs text-zinc-500 font-mono">{detail.timeframe}</span>
              <span className={`text-xs font-mono px-2 py-0.5 rounded border ${dir(detail.direction).bg} ${dir(detail.direction).text}`}>
                {dir(detail.direction).label} {detail.composite_score.toFixed(1)}/10
              </span>
              {REGIME_INFO[detail.regime] && <span className="text-[10px] text-zinc-600 hidden lg:inline">Best: {REGIME_INFO[detail.regime].bestStrategies.split(",")[0]}</span>}
            </div>
            <button onClick={onEvaluate} disabled={evalLoading}
              className="px-4 py-2 text-xs font-medium bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white rounded-lg transition-colors">
              {evalLoading ? "Evaluating..." : "\uD83E\uDD16 Evaluate with AI"}
            </button>
          </CardHeader>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 divide-y lg:divide-y-0 lg:divide-x divide-zinc-800/60">
            {/* Left: Signals */}
            <div className="p-4 space-y-1.5 max-h-[350px] overflow-y-auto">
              {(detail.signals || []).filter(s => s.direction !== null).map((sig, i) => {
                const info = STRATEGY_INFO[sig.strategy];
                const sd = dir(sig.direction);
                return (
                  <div key={i} className={`border rounded-lg p-3 ${sd.bg}`}>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-zinc-200">{info?.displayName || sig.strategy.replace(/_/g, " ")}</span>
                      <div className="flex items-center gap-2 text-xs font-mono">
                        <span className={sd.text}>{sd.label}</span>
                        <span className={scoreColor(sig.score / 10)}>{sig.score.toFixed(0)}</span>
                      </div>
                    </div>
                    <div className="text-[11px] text-zinc-400 mt-1">{sig.reason}</div>
                  </div>
                );
              })}
              {(detail.signals || []).filter(s => s.direction !== null).length === 0 && (
                <div className="text-sm text-zinc-600 text-center py-4">No active signals</div>
              )}
            </div>
            {/* Right: AI Decision */}
            <div className="p-4">
              {!evalData ? (
                <div className="text-center py-8 text-zinc-600 text-sm">Click &quot;Evaluate with AI&quot; for Claude analysis</div>
              ) : (
                <div className="space-y-3">
                  <div className={`border rounded-lg p-4 ${evalData.should_trade
                    ? evalData.claude_decision.action === "BUY" ? "bg-emerald-500/10 border-emerald-500/40" : "bg-red-500/10 border-red-500/40"
                    : "bg-zinc-800/50 border-zinc-700"
                  }`}>
                    <div className="flex items-center justify-between">
                      <div className={`text-2xl font-bold ${dir(evalData.claude_decision.action).text}`}>{evalData.claude_decision.action}</div>
                      <div className={`text-3xl font-mono font-bold ${scoreColor(evalData.claude_decision.confidence)}`}>{evalData.claude_decision.confidence}</div>
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
                  <div className={`text-center py-2 rounded-lg text-sm font-bold ${
                    evalData.should_trade ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30" : "bg-zinc-800 text-zinc-500 border border-zinc-700"
                  }`}>{evalData.should_trade ? "\u2705 TRADE APPROVED" : "\u274C DO NOT TRADE"}</div>
                  {evalData.should_trade && (
                    <button onClick={async () => {
                      const res = await fetch(`${ENGINE}/api/trade/open/${evalData.symbol}?timeframe=${evalData.timeframe}`, { method: "POST" });
                      const data = await res.json();
                      alert(data.status === "opened" ? `Opened ${data.position.direction} ${evalData.symbol}` : `Rejected: ${data.reason || data.rejections?.join(", ")}`);
                    }} className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-bold transition-colors">
                      Take This Trade
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* Tools */}
      <Card className="border-blue-500/20">
        <CardHeader><SectionTitle icon={"\uD83D\uDEE0\uFE0F"}>Tools</SectionTitle></CardHeader>
        <div className="p-4">
          <div className="flex flex-wrap gap-2 mb-4">
            {tools.map((tool) => {
              const disabled = tool.needsSymbol && !selected;
              return (
                <button key={tool.id} onClick={() => !disabled && runTool(tool)} disabled={disabled}
                  className={`px-4 py-2 text-xs rounded-lg transition-all font-medium ${
                    activeTool === tool.id ? "bg-blue-600 text-white shadow-lg shadow-blue-500/20" :
                    disabled ? "bg-zinc-900 text-zinc-700 cursor-not-allowed" :
                    "bg-zinc-800/60 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                  }`}>{tool.label}</button>
              );
            })}
          </div>
          {activeTool && (
            <div className="border-t border-zinc-800/60 pt-4">
              {toolLoading ? <div className="text-zinc-500 text-sm py-4 text-center">Loading...</div>
                : toolResult && <pre className="text-xs bg-zinc-800/30 rounded-lg p-3 overflow-auto text-zinc-400 max-h-80 font-mono">{JSON.stringify(toolResult, null, 2)}</pre>}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

// =============================================================
// TAB 3: EVOLUTION  (Green/Emerald theme)
// =============================================================

function EvolutionTab({ costs, stratPerf }: {
  costs: Record<string, unknown> | null;
  stratPerf: Array<Record<string, unknown>>;
}) {
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);
  const [reviewText, setReviewText] = useState<string | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [toolResult, setToolResult] = useState<Record<string, unknown> | null>(null);
  const [toolLoading, setToolLoading] = useState(false);

  useEffect(() => {
    fetch(`${ENGINE}/api/learning/analysis`).then(r => r.json()).then(setAnalysis).catch(() => {});
  }, []);

  const runReview = async () => {
    setReviewLoading(true);
    try {
      const res = await fetch(`${ENGINE}/api/learning/review`, { method: "POST" });
      const data = await res.json();
      setReviewText(data.review_text || JSON.stringify(data, null, 2));
    } catch { setReviewText("Failed to generate review"); }
    finally { setReviewLoading(false); }
  };

  const tools = [
    { id: "recommendations", label: "\uD83D\uDCA1 Recommendations", url: "/api/learning/recommendations" },
    { id: "abtests", label: "\uD83E\uDDEA A/B Tests", url: "/api/ab-test/results" },
    { id: "performance", label: "\uD83D\uDCC8 Strategy Perf", url: "/api/journal/performance" },
    { id: "trades", label: "\uD83D\uDCDC Trade History", url: "/api/journal/trades?limit=50" },
  ];

  const runTool = async (tool: typeof tools[0]) => {
    if (activeTool === tool.id) { setActiveTool(null); setToolResult(null); return; }
    setActiveTool(tool.id); setToolLoading(true); setToolResult(null);
    try { setToolResult(await (await fetch(`${ENGINE}${tool.url}`)).json()); }
    catch { setToolResult({ error: "Failed to connect" }); }
    finally { setToolLoading(false); }
  };

  const runtime = (costs as Record<string, unknown>)?.runtime as Record<string, unknown> || {};
  const totalCost = Number((costs as Record<string, unknown>)?.total_cost || 0);
  const runtimeCost = Number(runtime.total_cost || 0);
  const runtimeCalls = Number(runtime.calls || 0);

  // Build accuracy trend from strategy data
  const overallWR = analysis ? Number((analysis.overall as Record<string, unknown>)?.win_rate || 0) : 0;

  // Find top performers (diamonds)
  const diamonds = [...stratPerf]
    .filter(s => Number(s.win_rate || 0) >= 60 && Number(s.total_trades || 0) >= 5)
    .sort((a, b) => Number(b.win_rate || 0) - Number(a.win_rate || 0));

  return (
    <div className="space-y-4 animate-in fade-in duration-300">
      {/* Accuracy Trend */}
      <Card className="border-emerald-500/20">
        <CardHeader><SectionTitle icon={"\uD83D\uDCC8"}>System Accuracy</SectionTitle></CardHeader>
        <div className="p-5">
          <div className="flex items-end gap-4 mb-4">
            <div>
              <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Current Win Rate</div>
              <div className={`text-4xl font-mono font-black ${overallWR >= 55 ? "text-emerald-400" : overallWR >= 45 ? "text-amber-400" : "text-red-400"}`}>
                {overallWR > 0 ? `${overallWR.toFixed(1)}%` : "--"}
              </div>
            </div>
            {analysis && Number((analysis.overall as Record<string, unknown>)?.trades ?? 0) > 0 && (
              <div className="text-xs text-zinc-500 mb-1">from {String((analysis.overall as Record<string, unknown>).trades)} trades</div>
            )}
          </div>
          {/* Visual bar */}
          <div className="w-full bg-zinc-800 rounded-full h-4 overflow-hidden relative">
            <div className={`h-full rounded-full transition-all duration-1000 ${overallWR >= 55 ? "bg-gradient-to-r from-emerald-600 to-emerald-400" : overallWR >= 45 ? "bg-gradient-to-r from-amber-600 to-amber-400" : "bg-gradient-to-r from-red-600 to-red-400"}`}
              style={{ width: `${Math.max(5, overallWR)}%` }} />
            <div className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-white/70">
              {overallWR > 0 ? `${overallWR.toFixed(1)}% WIN RATE` : "NO DATA YET"}
            </div>
          </div>
          <div className="flex justify-between text-[9px] text-zinc-600 mt-1">
            <span>0%</span>
            <span className="text-amber-500/50">45%</span>
            <span className="text-emerald-500/50">55%</span>
            <span>100%</span>
          </div>
        </div>
      </Card>

      {/* Claude Reports + Costs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Claude Reports */}
        <Card className="border-emerald-500/20">
          <CardHeader>
            <SectionTitle icon={"\uD83E\uDD16"}>Claude Reports</SectionTitle>
            <button onClick={runReview} disabled={reviewLoading}
              className="px-3 py-1.5 text-xs font-medium bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-700 text-white rounded-lg transition-colors">
              {reviewLoading ? "Thinking..." : "\uD83D\uDCDD Generate Review"}
            </button>
          </CardHeader>
          <div className="p-4 max-h-[300px] overflow-y-auto">
            {reviewText ? (
              <div className="text-xs text-zinc-300 whitespace-pre-wrap bg-emerald-500/5 border border-emerald-500/10 rounded-lg p-4 leading-relaxed">{reviewText}</div>
            ) : analysis ? (
              <div className="space-y-3">
                <div className="text-xs text-zinc-400">Latest analysis summary:</div>
                {(analysis.by_instrument as Record<string, Record<string, unknown>> | undefined) && Object.entries(analysis.by_instrument as Record<string, Record<string, unknown>>).map(([inst, data]) => (
                  <div key={inst} className="flex justify-between text-xs py-1.5 border-b border-zinc-800/30">
                    <span className="text-zinc-200 font-medium">{inst}</span>
                    <span className="font-mono">
                      <span className={pnlColor(Number(data.win_rate || 0) >= 50 ? 1 : -1)}>{Number(data.win_rate || 0).toFixed(0)}% WR</span>
                      <span className="text-zinc-600 ml-2">{String(data.trades || 0)}t</span>
                    </span>
                  </div>
                ))}
                <div className="text-[10px] text-zinc-600">Click &quot;Generate Review&quot; for a full Claude analysis</div>
              </div>
            ) : (
              <div className="text-center py-8 text-zinc-600 text-sm">No learning data yet. Run some trades first!</div>
            )}
          </div>
        </Card>

        {/* Costs */}
        <Card className="border-emerald-500/20">
          <CardHeader><SectionTitle icon={"\uD83D\uDCB8"}>Token Costs</SectionTitle></CardHeader>
          <div className="p-4">
            <div className="grid grid-cols-3 gap-3 mb-4">
              <div className="bg-gradient-to-br from-emerald-500/10 to-zinc-900/50 rounded-xl p-3 text-center">
                <div className="text-[10px] text-zinc-500 uppercase">Runtime</div>
                <div className="text-xl font-mono font-bold text-emerald-400 mt-1">${runtimeCost.toFixed(4)}</div>
                <div className="text-[10px] text-zinc-600">{runtimeCalls} calls</div>
              </div>
              <div className="bg-gradient-to-br from-violet-500/10 to-zinc-900/50 rounded-xl p-3 text-center">
                <div className="text-[10px] text-zinc-500 uppercase">Build</div>
                <div className="text-xl font-mono font-bold text-violet-400 mt-1">${(totalCost - runtimeCost).toFixed(2)}</div>
              </div>
              <div className="bg-gradient-to-br from-blue-500/10 to-zinc-900/50 rounded-xl p-3 text-center">
                <div className="text-[10px] text-zinc-500 uppercase">Total</div>
                <div className="text-xl font-mono font-bold text-blue-400 mt-1">${totalCost.toFixed(2)}</div>
              </div>
            </div>
            <div className="flex gap-2">
              <input id="evo-bc" type="number" step="0.01" placeholder="$ cost" className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1.5 text-xs font-mono text-zinc-200 w-20" />
              <input id="evo-bd" type="text" placeholder="Description" className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1.5 text-xs text-zinc-200 flex-1" />
              <button onClick={async () => {
                const c = parseFloat((document.getElementById("evo-bc") as HTMLInputElement)?.value || "0");
                const d = (document.getElementById("evo-bd") as HTMLInputElement)?.value || "";
                if (c > 0) await fetch(`${ENGINE}/api/costs/log-build?cost=${c}&description=${encodeURIComponent(d)}`, { method: "POST" });
              }} className="px-3 py-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-medium transition-colors">Log</button>
            </div>
          </div>
        </Card>
      </div>

      {/* Diamonds Found */}
      <Card className="border-emerald-500/20">
        <CardHeader>
          <SectionTitle icon={"\uD83D\uDC8E"}>Diamonds Found</SectionTitle>
          <span className="text-[10px] text-zinc-500">Strategies with 60%+ WR and 5+ trades</span>
        </CardHeader>
        <div className="p-4">
          {diamonds.length === 0 ? (
            <div className="text-center py-6 text-zinc-600">
              <div className="text-2xl mb-2">{"\u26CF\uFE0F"}</div>
              <div className="text-sm">No diamonds yet. Keep mining (trading) to find them!</div>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {diamonds.map((s) => {
                const wr = Number(s.win_rate || 0);
                return (
                  <div key={s.strategy as string} className="bg-gradient-to-br from-emerald-500/15 to-zinc-900/50 border border-emerald-500/30 rounded-xl p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-bold text-emerald-300">
                        {"\uD83D\uDC8E"} {STRATEGY_INFO[s.strategy as string]?.displayName || s.strategy as string}
                      </span>
                      <span className="text-xl font-mono font-black text-emerald-400">{wr.toFixed(0)}%</span>
                    </div>
                    <div className="w-full bg-zinc-800 rounded-full h-2 overflow-hidden mb-2">
                      <div className="h-full rounded-full bg-gradient-to-r from-emerald-600 to-emerald-400 transition-all duration-500"
                        style={{ width: `${wr}%` }} />
                    </div>
                    <div className="flex gap-4 text-[11px] text-zinc-400 font-mono">
                      <span>{s.total_trades as number} trades</span>
                      <span>{s.wins as number}W / {s.losses as number}L</span>
                      <span className={pnlColor(Number(s.total_pnl || 0))}>{pnlSign(Number(s.total_pnl || 0))}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Card>

      {/* Tools */}
      <Card className="border-emerald-500/20">
        <CardHeader><SectionTitle icon={"\uD83D\uDEE0\uFE0F"}>Exploration Tools</SectionTitle></CardHeader>
        <div className="p-4">
          <div className="flex flex-wrap gap-2 mb-4">
            {tools.map((tool) => (
              <button key={tool.id} onClick={() => runTool(tool)}
                className={`px-4 py-2 text-xs rounded-lg transition-all font-medium ${
                  activeTool === tool.id ? "bg-emerald-600 text-white shadow-lg shadow-emerald-500/20" :
                  "bg-zinc-800/60 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                }`}>{tool.label}</button>
            ))}
          </div>
          {activeTool && (
            <div className="border-t border-zinc-800/60 pt-4">
              {toolLoading ? <div className="text-zinc-500 text-sm py-4 text-center">Loading...</div>
                : toolResult && <pre className="text-xs bg-zinc-800/30 rounded-lg p-3 overflow-auto text-zinc-400 max-h-80 font-mono">{JSON.stringify(toolResult, null, 2)}</pre>}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

// =============================================================
// MAIN PAGE
// =============================================================

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState<TabId>("lab");
  const [overview, setOverview] = useState<ScanOverview[]>([]);
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ScanResult | null>(null);
  const [evalData, setEvalData] = useState<EvalResult | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [positions, setPositions] = useState<Array<Record<string, unknown>>>([]);
  const [labTrades, setLabTrades] = useState<Array<Record<string, unknown>>>([]);
  const [stratPerf, setStratPerf] = useState<Array<Record<string, unknown>>>([]);
  const [costsData, setCostsData] = useState<Record<string, unknown> | null>(null);
  const [tf, setTf] = useState("5m");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [engineOnline, setEngineOnline] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [ovRes, rkRes, posRes, tradesRes, perfRes, costsRes] = await Promise.all([
        fetch(`${ENGINE}/api/scan/all?timeframe=${tf}`),
        fetch(`${ENGINE}/api/risk/status`),
        fetch(`${ENGINE}/api/trade/positions`),
        fetch(`${ENGINE}/api/journal/trades?limit=30`),
        fetch(`${ENGINE}/api/journal/performance`),
        fetch(`${ENGINE}/api/costs/summary`),
      ]);
      if (!ovRes.ok || !rkRes.ok) throw new Error("fail");
      setOverview((await ovRes.json()).results || []);
      setRisk(await rkRes.json());
      if (posRes.ok) setPositions((await posRes.json()).positions || []);
      if (tradesRes.ok) setLabTrades((await tradesRes.json()).trades || []);
      if (perfRes.ok) setStratPerf((await perfRes.json()).strategies || []);
      if (costsRes.ok) setCostsData(await costsRes.json());
      setErr(null);
      setEngineOnline(true);
    } catch {
      setErr("Engine offline \u2014 run: cd engine && ../.venv/bin/python run.py");
      setEngineOnline(false);
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

  const todayCost = Number((costsData as Record<string, unknown>)?.total_cost || 0);

  // Tab accent colors for the timeframe selector
  const tabAccent: Record<TabId, { active: string; ring: string }> = {
    lab: { active: "bg-violet-600 text-white", ring: "ring-violet-500/20" },
    command: { active: "bg-blue-600 text-white", ring: "ring-blue-500/20" },
    evolution: { active: "bg-emerald-600 text-white", ring: "ring-emerald-500/20" },
  };

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-4 lg:p-6 max-w-[1600px] mx-auto">
      <Header activeTab={activeTab} onTabChange={setActiveTab} costs={todayCost} engineOnline={engineOnline} />

      {/* Error Banner */}
      {err && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 mb-4 text-red-400 text-sm flex items-center gap-2">
          <span>{"\u26A0\uFE0F"}</span>{err}
        </div>
      )}

      {/* Timeframe Selector + Refresh */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-1.5 bg-zinc-900/80 border border-zinc-800 rounded-full p-1">
          {["1m", "5m", "15m", "30m", "1h"].map((t) => (
            <button key={t} onClick={() => setTf(t)}
              className={`px-3 py-1.5 text-xs font-mono rounded-full transition-all ${
                tf === t ? tabAccent[activeTab].active : "text-zinc-500 hover:text-zinc-300"
              }`}>{t}</button>
          ))}
        </div>
        <button onClick={refresh}
          className="px-4 py-1.5 text-xs bg-zinc-800/60 text-zinc-400 hover:text-zinc-200 rounded-full transition-all hover:bg-zinc-800 flex items-center gap-1.5">
          {"\u21BB"} Refresh
        </button>
      </div>

      {/* Loading State */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <div className="text-4xl mb-3 animate-bounce">{"\uD83E\uDDEA"}</div>
            <div className="text-zinc-500">Connecting to engine...</div>
          </div>
        </div>
      ) : (
        <>
          {activeTab === "lab" && (
            <LabTab
              risk={risk} positions={positions} labTrades={labTrades} stratPerf={stratPerf}
              overview={overview} selected={selected} onSelect={setSelected} tf={tf} onClose={handleClose}
            />
          )}
          {activeTab === "command" && (
            <CommandTab
              risk={risk} positions={positions} overview={overview} selected={selected} onSelect={setSelected}
              detail={detail} evalData={evalData} evalLoading={evalLoading} onEvaluate={handleEvaluate}
              tf={tf} onClose={handleClose}
            />
          )}
          {activeTab === "evolution" && (
            <EvolutionTab costs={costsData} stratPerf={stratPerf} />
          )}
        </>
      )}

      {/* Footer */}
      <footer className="mt-8 text-center text-[10px] text-zinc-700 border-t border-zinc-800/30 pt-4">
        NOTAS LAVE {"\u00B7"} Evolve or Die {"\u00B7"} Built with Claude
      </footer>
    </main>
  );
}
