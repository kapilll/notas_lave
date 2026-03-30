"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import type { ScanResult } from "@/lib/api";
import { STRATEGY_INFO, REGIME_INFO } from "@/lib/strategy-info";
import { useWebSocket, type WsMessage } from "@/hooks/useWebSocket";

const ENGINE =
  process.env.NEXT_PUBLIC_ENGINE_URL ||
  (typeof window !== "undefined"
    ? `http://${window.location.hostname}:8000`
    : "http://localhost:8000");

// WebSocket URL derived from ENGINE (http→ws, https→wss)
const WS_URL = ENGINE.replace(/^https?/, "ws") + "/ws";

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
  total_pnl_pct?: number;
  daily_pnl: number;
  daily_drawdown_used_pct: number;
  total_drawdown_used_pct: number;
  trades_today: number;
  open_positions: number;
  max_concurrent?: number;
  original_deposit?: number;
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

type TabId = "lab" | "strategies" | "command" | "evolution";

interface SystemHealth {
  timestamp: string;
  uptime_seconds: number;
  components: {
    lab_engine: { status: string; last_heartbeat: string | null; open_positions: number; trades_today: number; trades_since_last_review: number };
    autonomous_trader: { status: string; mode: string };
    broker: { status: string; type: string };
    market_data: { status: string; last_candle_time: string | null; symbols_tracked: number };
  };
  background_tasks: {
    last_backtest: string | null;
    last_optimizer: string | null;
    last_claude_review: string | null;
    last_checkin: string | null;
  };
  data_health: {
    db_lab_trades: number;
    db_lab_open: number;
    log_file_size_mb: number;
    wal_file_size_mb: number;
  };
  errors_last_hour: number;
}

// =============================================================
// HELPERS
// =============================================================

/** Parse UTC timestamp from API (missing Z suffix) into local Date */
function parseUTC(ts: string | null | undefined): Date | null {
  if (!ts) return null;
  // API returns "2026-03-22T20:36:07" without Z — append it so JS treats as UTC
  const s = String(ts);
  return new Date(s.endsWith("Z") || s.includes("+") ? s : s + "Z");
}

/** Format a Date as local time string (IST for India) */
function fmtTime(d: Date | null): string {
  if (!d) return "";
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
}

/** Format a Date as short date + time (for non-today periods) */
function fmtDateTime(d: Date | null): string {
  if (!d) return "";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) + " " + fmtTime(d);
}

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

function relativeTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "never";
  const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
  if (diff < 0) return "just now";
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

const REGIMES: Record<string, { icon: string; color: string; gradient: string }> = {
  TRENDING: { icon: "\u2197", color: "text-blue-400", gradient: "from-blue-500/20 to-blue-900/5" },
  RANGING: { icon: "\u2194", color: "text-amber-400", gradient: "from-amber-500/20 to-amber-900/5" },
  VOLATILE: { icon: "\u26A1", color: "text-red-400", gradient: "from-red-500/20 to-red-900/5" },
  QUIET: { icon: "\uD83D\uDD15", color: "text-zinc-500", gradient: "from-zinc-500/10 to-zinc-900/5" },
};

// =============================================================
// CARD: Base wrapper
// =============================================================

function Card({ children, className = "", glow }: { children: React.ReactNode; className?: string; glow?: string }) {
  return (
    <div className={`relative bg-zinc-900/70 border border-zinc-800/80 rounded-2xl backdrop-blur-xl overflow-hidden ${className}`}>
      {glow && <div className={`absolute inset-0 ${glow} opacity-[0.03] pointer-events-none`} />}
      {children}
    </div>
  );
}
function CardHeader({ children }: { children: React.ReactNode }) {
  return <div className="px-5 py-3.5 border-b border-zinc-800/40 flex items-center justify-between">{children}</div>;
}
function SectionTitle({ children, icon }: { children: React.ReactNode; icon?: string }) {
  return <h2 className="text-[11px] font-semibold text-zinc-300 uppercase tracking-[0.15em] flex items-center gap-2">{icon && <span className="text-sm">{icon}</span>}{children}</h2>;
}

// =============================================================
// HEADER
// =============================================================

function Header({ activeTab, onTabChange, costs, engineOnline, engineVersion }: {
  activeTab: TabId;
  onTabChange: (t: TabId) => void;
  costs: number;
  engineOnline: boolean;
  engineVersion: string;
}) {
  const tabs: { id: TabId; label: string; emoji: string; accent: string; activeBg: string }[] = [
    { id: "lab", label: "LAB", emoji: "\uD83E\uDDEA", accent: "text-violet-400", activeBg: "bg-violet-600 shadow-violet-500/30" },
    { id: "strategies", label: "STRATEGIES", emoji: "\u2694\uFE0F", accent: "text-amber-400", activeBg: "bg-amber-600 shadow-amber-500/30" },
    { id: "command", label: "COMMAND", emoji: "\uD83C\uDFAF", accent: "text-blue-400", activeBg: "bg-blue-600 shadow-blue-500/30" },
    { id: "evolution", label: "EVOLUTION", emoji: "\uD83E\uDDEC", accent: "text-emerald-400", activeBg: "bg-emerald-600 shadow-emerald-500/30" },
  ];

  return (
    <header className="flex flex-col sm:flex-row items-start sm:items-center justify-between mb-5 gap-4">
      <div className="flex items-center gap-4">
        <div>
          <h1 className="text-2xl font-black tracking-tighter bg-gradient-to-r from-violet-400 via-fuchsia-400 to-cyan-400 bg-clip-text text-transparent">
            NOTAS LAVE
          </h1>
          <p className="text-[9px] text-zinc-600 uppercase tracking-[0.25em] -mt-0.5 font-medium">Evolve or Die</p>
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
        <a href="/architecture/index.html"
          target="_blank"
          className="flex items-center gap-1.5 bg-zinc-900/80 border border-zinc-800 rounded-full px-3 py-1.5 hover:border-violet-500/50 transition-colors cursor-pointer"
          title="View architecture diagrams (LikeC4)">
          <span className="text-[10px]">🏗️</span>
          <span className="text-[10px] text-zinc-400 hidden sm:inline">ARCH</span>
        </a>
        <div className="flex items-center gap-1.5 bg-zinc-900/80 border border-zinc-800 rounded-full px-3 py-1.5">
          <span className="text-[10px] text-zinc-500">COST</span>
          <span className="text-xs font-mono font-bold text-amber-400">${costs.toFixed(2)}</span>
        </div>
        <div className="flex items-center gap-1.5 bg-zinc-900/80 border border-zinc-800 rounded-full px-3 py-1.5">
          <span className={`w-2 h-2 rounded-full ${engineOnline ? "bg-emerald-500 animate-pulse" : "bg-red-500"}`} />
          <span className="text-[10px] text-zinc-400">
            {engineOnline ? (engineVersion ? `v${engineVersion}` : "ENGINE") : "OFFLINE"}
          </span>
        </div>
      </div>
    </header>
  );
}

// =============================================================
// HEALTH BAR — compact system health display
// =============================================================

function HealthBar({ health }: { health: SystemHealth | null }) {
  const [expanded, setExpanded] = useState(false);

  if (!health?.components) return null;

  const { components: c, background_tasks: bg, data_health: dh } = health;

  // Determine overall status color
  const allOk = c.lab_engine?.status === "running" && c.broker?.status === "connected";
  const hasError = c.lab_engine?.status === "error" || c.broker?.status === "disconnected";
  const overallColor = allOk ? "border-emerald-500/30 bg-emerald-500/5" : hasError ? "border-red-500/30 bg-red-500/5" : "border-amber-500/30 bg-amber-500/5";

  function StatusDot({ status, label }: { status: string; label: string }) {
    const color = status === "running" || status === "connected" || status === "ok"
      ? "bg-emerald-500" : status === "stopped" || status === "disconnected"
      ? "bg-red-500" : "bg-amber-500";
    return (
      <div className="flex items-center gap-1.5">
        <span className={`w-1.5 h-1.5 rounded-full ${color}`} />
        <span className="text-[10px] text-zinc-400">{label}:</span>
        <span className={`text-[10px] font-bold ${color === "bg-emerald-500" ? "text-emerald-400" : color === "bg-red-500" ? "text-red-400" : "text-amber-400"}`}>
          {status.toUpperCase()}
        </span>
      </div>
    );
  }

  return (
    <div className={`border rounded-xl mb-4 transition-all ${overallColor}`}>
      {/* Compact bar — always visible */}
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-2 text-left">
        <div className="flex items-center gap-4 flex-wrap">
          <StatusDot status={c.lab_engine.status} label="Lab" />
          <StatusDot status={c.broker.status} label="Broker" />
          <StatusDot status={c.market_data.status} label="Data" />
          <div className="h-3 w-px bg-zinc-800" />
          <span className="text-[10px] text-zinc-500">Uptime: <span className="text-zinc-300 font-mono">{formatUptime(health.uptime_seconds)}</span></span>
          {c.lab_engine.last_heartbeat && (
            <>
              <div className="h-3 w-px bg-zinc-800" />
              <span className="text-[10px] text-zinc-500">Heartbeat: <span className="text-zinc-300 font-mono">{relativeTime(c.lab_engine.last_heartbeat)}</span></span>
            </>
          )}
          <div className="h-3 w-px bg-zinc-800" />
          <span className="text-[10px] text-zinc-500">Trades: <span className="text-zinc-300 font-mono">{dh.db_lab_trades}</span></span>
        </div>
        <span className="text-zinc-600 text-xs">{expanded ? "\u25B2" : "\u25BC"}</span>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-zinc-800/40 px-4 py-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-[11px]">
          {/* Components */}
          <div className="space-y-1.5">
            <div className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider mb-1">Components</div>
            <div className="text-zinc-400">Lab: <span className={c.lab_engine.status === "running" ? "text-emerald-400" : "text-red-400"}>{c.lab_engine.status}</span></div>
            <div className="text-zinc-400">Trader: <span className={c.autonomous_trader.status === "running" ? "text-emerald-400" : "text-red-400"}>{c.autonomous_trader.status}</span> ({c.autonomous_trader.mode})</div>
            <div className="text-zinc-400">Broker: <span className={c.broker.status === "connected" ? "text-emerald-400" : "text-red-400"}>{c.broker.type}</span></div>
            <div className="text-zinc-400">Symbols: <span className="text-zinc-300">{c.market_data.symbols_tracked}</span></div>
          </div>

          {/* Background Tasks */}
          <div className="space-y-1.5">
            <div className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider mb-1">Background Tasks</div>
            <div className="text-zinc-400">Backtest: <span className="text-zinc-300 font-mono">{relativeTime(bg.last_backtest)}</span></div>
            <div className="text-zinc-400">Optimizer: <span className="text-zinc-300 font-mono">{relativeTime(bg.last_optimizer)}</span></div>
            <div className="text-zinc-400">Review: <span className="text-zinc-300 font-mono">{relativeTime(bg.last_claude_review)}</span></div>
            <div className="text-zinc-400">Check-in: <span className="text-zinc-300 font-mono">{relativeTime(bg.last_checkin)}</span></div>
          </div>

          {/* Lab Stats */}
          <div className="space-y-1.5">
            <div className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider mb-1">Lab Stats</div>
            <div className="text-zinc-400">Open: <span className="text-zinc-300 font-mono">{c.lab_engine.open_positions}</span></div>
            <div className="text-zinc-400">Today: <span className="text-zinc-300 font-mono">{c.lab_engine.trades_today} trades</span></div>
            <div className="text-zinc-400">Since review: <span className="text-zinc-300 font-mono">{c.lab_engine.trades_since_last_review}</span></div>
            <div className="text-zinc-400">Total closed: <span className="text-zinc-300 font-mono">{dh.db_lab_trades}</span></div>
          </div>

          {/* Data Health */}
          <div className="space-y-1.5">
            <div className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider mb-1">Data Health</div>
            <div className="text-zinc-400">Log file: <span className="text-zinc-300 font-mono">{dh.log_file_size_mb} MB</span></div>
            <div className="text-zinc-400">WAL file: <span className="text-zinc-300 font-mono">{dh.wal_file_size_mb} MB</span></div>
            <div className="text-zinc-400">Last candle: <span className="text-zinc-300 font-mono">{relativeTime(c.market_data.last_candle_time)}</span></div>
            <div className="text-zinc-400">Errors (1h): <span className="text-zinc-300 font-mono">{health.errors_last_hour}</span></div>
          </div>
        </div>
      )}
    </div>
  );
}

// =============================================================
// ACTION BAR — Quick actions with inline result display
// =============================================================

const ACTIONS = [
  { id: "sync-pos", label: "Sync Positions", icon: "\uD83D\uDD04", url: "/api/lab/sync-positions", method: "POST", color: "bg-violet-600 hover:bg-violet-500",
    describe: (d: Record<string, unknown>) => {
      const positions = (d.positions as Array<Record<string, unknown>>) || [];
      return [
        { label: "Positions synced", value: String(positions.length), ok: true },
        { label: "Old cleared", value: String(d.old_positions_cleared ?? 0) },
        { label: "Orphans closed", value: String(d.orphaned_entries_closed ?? 0) },
        { label: "Balance", value: `$${Number(d.balance || 0).toLocaleString()}`, ok: true },
        ...positions.map(p => ({ label: `${p.symbol}`, value: `${p.direction} @ ${Number(p.entry || 0).toFixed(2)} (${p.pnl && Number(p.pnl) >= 0 ? "+" : ""}$${Number(p.pnl || 0).toFixed(2)})`, ok: Number(p.pnl || 0) >= 0 })),
      ];
    },
  },
  { id: "sync-bal", label: "Sync Balance", icon: "\uD83D\uDCB0", url: "/api/lab/sync-balance", method: "POST", color: "bg-zinc-700 hover:bg-zinc-600",
    describe: (d: Record<string, unknown>) => [
      { label: "Status", value: d.synced ? "Synced" : "Failed", ok: !!d.synced },
      { label: "Balance", value: `$${Number(d.balance || 0).toLocaleString()}`, ok: true },
    ],
  },
  { id: "verify", label: "Verify Data", icon: "\u2705", url: "/api/lab/verify", method: "GET", color: "bg-zinc-700 hover:bg-zinc-600",
    describe: (d: Record<string, unknown>) => {
      const checks = (d.checks as Array<Record<string, unknown>>) || [];
      const items = [
        { label: "Overall", value: d.passed ? "ALL PASSED" : "ISSUES FOUND — click Sync Positions to fix", ok: !!d.passed },
        ...checks.map(c => ({ label: String(c.check), value: c.passed ? "OK" : `MISMATCH: ${c.diff ?? c.error ?? ""}`, ok: !!c.passed })),
      ];
      return items;
    },
  },
  { id: "health", label: "System Health", icon: "\uD83C\uDFE5", url: "/api/system/health", method: "GET" as const, color: "bg-zinc-700 hover:bg-zinc-600",
    describe: (d: Record<string, unknown>) => {
      const comp = (d.components as Record<string, Record<string, unknown>>) || {};
      return [
        { label: "Status", value: String(d.status || "unknown").toUpperCase(), ok: d.status === "ok" },
        ...Object.entries(comp).map(([name, info]) => ({ label: name.replace(/_/g, " "), value: String(info.status || info).toUpperCase(), ok: info.status === "running" || info.status === "connected" || info.status === "ok" })),
      ];
    },
  },
] as const;

function ActionBar({ onComplete }: { onComplete?: () => void }) {
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<Array<{ label: string; value: string; ok?: boolean }> | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const runAction = async (action: typeof ACTIONS[number]) => {
    if (activeAction === action.id) { setActiveAction(null); setActionResult(null); return; }
    setActiveAction(action.id);
    setActionLoading(true);
    setActionResult(null);
    try {
      const res = await fetch(`${ENGINE}${action.url}`, { method: action.method || "GET" });
      const data = await res.json();
      setActionResult(action.describe(data as Record<string, unknown>));
      // Refresh dashboard data after any POST action
      if (action.method === "POST" && onComplete) onComplete();
    } catch {
      setActionResult([{ label: "Error", value: "Failed to connect to engine", ok: false }]);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {ACTIONS.map((action) => (
          <button key={action.id} onClick={() => runAction(action)}
            className={`px-3 py-1.5 text-[10px] font-bold text-white rounded-lg transition-all flex items-center gap-1.5 ${
              activeAction === action.id ? "ring-2 ring-violet-400/50 " + action.color : action.color
            }`}>
            <span>{action.icon}</span>{action.label}
          </button>
        ))}
      </div>
      {activeAction && (
        <div className="mt-2 bg-zinc-900/80 border border-zinc-800 rounded-xl p-4 animate-in fade-in duration-200">
          {actionLoading ? (
            <div className="text-zinc-500 text-xs text-center py-2">Running...</div>
          ) : actionResult && (
            <div className="space-y-1.5">
              {actionResult.map((item, i) => (
                <div key={i} className="flex items-center justify-between text-xs">
                  <span className="text-zinc-400">{item.label}</span>
                  <span className={`font-mono font-bold ${
                    item.ok === true ? "text-emerald-400" : item.ok === false ? "text-red-400" : "text-zinc-200"
                  }`}>{item.value}</span>
                </div>
              ))}
              <button onClick={() => { setActiveAction(null); setActionResult(null); }}
                className="text-[10px] text-zinc-600 hover:text-zinc-400 mt-2">Dismiss</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// =============================================================
// TAB 1: LAB  (Purple/Violet theme)
// =============================================================

type TradePeriod = "today" | "week" | "month" | "all";

interface LabMarket {
  symbol: string;
  price: number;
  has_position: boolean;
  direction?: string;
  pnl?: number;
  health?: string;
}

function LabTab({ risk, positions, labTrades, stratPerf, overview, labMarkets, selected, onSelect, tf, onClose, tradePeriod, onPeriodChange, tradeSummary, onRefresh, health, paceInfo }: {
  risk: RiskStatus | null;
  positions: Array<Record<string, unknown>>;
  labTrades: Array<Record<string, unknown>>;
  stratPerf: Array<Record<string, unknown>>;
  overview: ScanOverview[];
  labMarkets: LabMarket[];
  selected: string | null;
  onSelect: (s: string) => void;
  tf: string;
  onClose: (id: string) => void;
  tradePeriod: TradePeriod;
  onPeriodChange: (p: TradePeriod) => void;
  tradeSummary: { total: number; wins: number; losses: number; win_rate: number; total_pnl: number } | null;
  onRefresh: () => void;
  health: SystemHealth | null;
  paceInfo: { entry_tfs: string[]; min_rr: number; max_concurrent: number } | null;
}) {
  // Sort strategies by win rate descending
  const ranked = [...stratPerf].sort((a, b) => Number(b.win_rate || 0) - Number(a.win_rate || 0));

  return (
    <div className="space-y-4 animate-in fade-in duration-300">
      {/* Stats Cards */}
      {risk && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Balance", value: `$${risk.balance.toLocaleString()}`, color: "text-white", gradient: "from-violet-600/20 via-violet-500/10 to-transparent", border: "border-violet-500/25", icon: "\uD83D\uDCB0" },
            { label: "Trades", value: String(tradeSummary?.total ?? 0), color: "text-white", gradient: "from-blue-600/20 via-blue-500/10 to-transparent", border: "border-blue-500/25", icon: "\uD83D\uDCC8" },
            { label: "Win Rate", value: labTrades.length > 0 ? `${((labTrades.filter(t => Number(t.pnl) > 0).length / labTrades.length) * 100).toFixed(0)}%` : "--", color: "text-white", gradient: "from-cyan-600/20 via-cyan-500/10 to-transparent", border: "border-cyan-500/25", icon: "\uD83C\uDFAF" },
            { label: "P&L", value: pnlSign(tradeSummary?.total_pnl ?? 0), color: (tradeSummary?.total_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400", gradient: (tradeSummary?.total_pnl ?? 0) >= 0 ? "from-emerald-600/20 via-emerald-500/10 to-transparent" : "from-red-600/20 via-red-500/10 to-transparent", border: (tradeSummary?.total_pnl ?? 0) >= 0 ? "border-emerald-500/25" : "border-red-500/25", icon: (tradeSummary?.total_pnl ?? 0) >= 0 ? "\uD83D\uDD25" : "\u2744\uFE0F" },
          ].map((stat) => (
            <div key={stat.label} className={`relative overflow-hidden bg-gradient-to-br ${stat.gradient} border ${stat.border} rounded-2xl p-3 backdrop-blur-sm`}>
              <div className="text-[10px] text-zinc-400 uppercase tracking-[0.15em] flex items-center gap-1.5 mb-1">
                <span className="text-sm">{stat.icon}</span>{stat.label}
              </div>
              <div className={`text-xl font-mono font-black tracking-tight ${stat.color}`}>{stat.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Engine Status Strip */}
      <div className="flex flex-wrap gap-2 px-0.5">
        {/* Engine running/stopped */}
        {health?.components?.lab_engine && (() => {
          const running = health.components.lab_engine.status === "running";
          return (
            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold border ${running ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400" : "bg-red-500/10 border-red-500/30 text-red-400"}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${running ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`} />
              ENGINE {running ? "RUNNING" : "STOPPED"}
            </span>
          );
        })()}
        {/* Broker */}
        {health?.components?.broker && (() => {
          const connected = health.components.broker.status === "connected";
          return (
            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold border ${connected ? "bg-blue-500/10 border-blue-500/30 text-blue-400" : "bg-red-500/10 border-red-500/30 text-red-400"}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-blue-400" : "bg-red-400"}`} />
              {(health.components.broker.type || "BROKER").toUpperCase().replace("_", " ")}
            </span>
          );
        })()}
        {/* Can Trade */}
        {risk && (
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold border ${risk.can_trade ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400" : "bg-red-500/10 border-red-500/30 text-red-400"}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${risk.can_trade ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`} />
            {risk.can_trade ? "CAN TRADE" : "HALTED"}
          </span>
        )}
        {/* Open positions */}
        {risk && (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold border bg-zinc-800/60 border-zinc-700/50 text-zinc-300">
            {risk.open_positions}/{risk.max_concurrent ?? 5} POSITIONS
          </span>
        )}
        {/* Drawdown */}
        {risk && (
          <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold border ${risk.total_drawdown_used_pct < 5 ? "bg-zinc-800/60 border-zinc-700/50 text-zinc-400" : risk.total_drawdown_used_pct < 8 ? "bg-amber-500/10 border-amber-500/30 text-amber-400" : "bg-red-500/10 border-red-500/30 text-red-400"}`}>
            DD {risk.total_drawdown_used_pct.toFixed(1)}%
          </span>
        )}
        {/* Scanning timeframes */}
        {paceInfo && paceInfo.entry_tfs.length > 0 && (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold border bg-violet-500/10 border-violet-500/30 text-violet-400">
            SCAN {paceInfo.entry_tfs.join(" ")}
          </span>
        )}
        {/* Min R:R */}
        {paceInfo && (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold border bg-zinc-800/60 border-zinc-700/50 text-zinc-400">
            MIN R:R {paceInfo.min_rr}:1
          </span>
        )}
        {/* Markets tracked */}
        {health?.components?.market_data && (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold border bg-zinc-800/60 border-zinc-700/50 text-zinc-400">
            {health.components.market_data.symbols_tracked} MARKETS
          </span>
        )}
        {/* Total trades in DB */}
        {health?.data_health && health.data_health.db_lab_trades > 0 && (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold border bg-zinc-800/60 border-zinc-700/50 text-zinc-400">
            {health.data_health.db_lab_trades} TOTAL TRADES
          </span>
        )}
      </div>

      {/* Quick Actions */}
      <ActionBar onComplete={onRefresh} />

      {/* Main 3-column layout: Leaderboard | Trade History | Positions */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_2fr_1fr] gap-4 items-start">
        {/* Strategy Leaderboard */}
        <Card className="border-violet-500/20">
          <CardHeader>
            <SectionTitle icon={"\uD83C\uDFC6"}>Strategy Leaderboard</SectionTitle>
            <span className="text-[10px] text-zinc-500">{ranked.length} strategies</span>
          </CardHeader>
          <div className="p-4 space-y-2 max-h-[320px] overflow-y-auto">
            {ranked.length === 0 ? (
              <div className="text-center py-10 text-zinc-600">
                <div className="text-3xl mb-3 opacity-40">&#x1F3C6;</div>
                <div className="text-sm font-medium text-zinc-500">No strategy data yet. Run some trades!</div>
                <div className="text-[10px] text-zinc-700 mt-1">Strategies will be ranked by performance</div>
              </div>
            ) : ranked.map((s, i) => {
              const wr = Number(s.win_rate || 0);
              const barColor = wr >= 55 ? "bg-emerald-500" : wr >= 45 ? "bg-amber-500" : "bg-red-500";
              const medal = i === 0 ? "\uD83E\uDD47" : i === 1 ? "\uD83E\uDD48" : i === 2 ? "\uD83E\uDD49" : `#${i + 1}`;
              const stratName = (s.name || s.strategy || "unknown") as string;
              const trades = Number(s.trades || s.total_trades || 0);
              const wins = Number(s.wins || 0);
              const losses = Number(s.losses || (trades - wins));
              return (
                <div key={stratName} className="group">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm w-7 text-right">{medal}</span>
                      <span className="text-xs font-medium text-zinc-200">
                        {STRATEGY_INFO[stratName]?.displayName || stratName}
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
                  <div className="text-[10px] text-zinc-600 mt-0.5">{wins}W / {losses}L | {trades} trades</div>
                </div>
              );
            })}
          </div>
        </Card>

        {/* CENTER column: Trade History */}
        <Card className="border-violet-500/20">
          {/* Header */}
          <div className="px-5 py-4 border-b border-zinc-800/40">
            <div className="flex items-center justify-between mb-3">
              <SectionTitle icon={"\u26A1"}>Trade History</SectionTitle>
              {tradeSummary && tradeSummary.total > 0 && (
                <div className="flex items-center gap-4 text-[11px] font-mono">
                  <span className="text-zinc-500">{tradeSummary.total} trades</span>
                  <span className="text-zinc-400">{tradeSummary.wins}W / {tradeSummary.losses}L</span>
                  <span className={`font-bold ${tradeSummary.win_rate >= 50 ? "text-emerald-400" : "text-amber-400"}`}>{tradeSummary.win_rate}% WR</span>
                  <span className={`font-bold text-sm ${pnlColor(tradeSummary.total_pnl)}`}>{pnlSign(tradeSummary.total_pnl)}</span>
                </div>
              )}
            </div>
            <div className="flex gap-1.5">
              {([
                { id: "today" as TradePeriod, label: "Today" },
                { id: "week" as TradePeriod, label: "This Week" },
                { id: "month" as TradePeriod, label: "This Month" },
                { id: "all" as TradePeriod, label: "All Time" },
              ]).map((p) => (
                <button key={p.id} onClick={() => onPeriodChange(p.id)}
                  className={`px-3 py-1 text-[10px] font-bold rounded-full transition-all ${
                    tradePeriod === p.id
                      ? "bg-violet-600 text-white shadow-sm"
                      : "text-zinc-500 hover:text-zinc-300 bg-zinc-800/40 hover:bg-zinc-800"
                  }`}>{p.label}</button>
              ))}
            </div>
          </div>

          {labTrades.length === 0 ? (
            <div className="text-center py-16 text-zinc-600 text-sm">
              No trades {tradePeriod === "today" ? "today" : tradePeriod === "week" ? "this week" : tradePeriod === "month" ? "this month" : ""} yet
            </div>
          ) : (() => {
            // Separate real trades from system housekeeping
            const realTrades = labTrades.filter(t => String(t.exit_reason || "") !== "dup_cleanup");
            const systemEvents = labTrades.filter(t => String(t.exit_reason || "") === "dup_cleanup");

            const exitReasonBadge = (reason: string) => {
              if (reason === "tp_hit") return { label: "TP Hit", cls: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40" };
              if (reason === "sl_hit") return { label: "SL Hit", cls: "bg-red-500/20 text-red-400 border-red-500/40" };
              if (reason === "exchange_close") return { label: "Exchange Closed", cls: "bg-blue-500/20 text-blue-400 border-blue-500/40" };
              if (reason === "manual") return { label: "Manual Close", cls: "bg-amber-500/20 text-amber-400 border-amber-500/40" };
              return { label: reason || "Closed", cls: "bg-zinc-800 text-zinc-500 border-zinc-700" };
            };

            // Price progress track: shows where exit landed between SL and TP
            const PriceTrack = ({ entry, exit, sl, tp, direction }: { entry: number; exit: number; sl: number; tp: number; direction: string }) => {
              if (!entry || !sl || !tp) return null;
              const isLong = direction === "LONG";
              const low = isLong ? sl : tp;
              const high = isLong ? tp : sl;
              const range = high - low;
              if (range <= 0) return null;
              const entryPct = Math.max(0, Math.min(100, ((entry - low) / range) * 100));
              const exitPct = exit ? Math.max(0, Math.min(100, ((exit - low) / range) * 100)) : entryPct;
              const isProfit = isLong ? exit > entry : exit < entry;
              return (
                <div className="relative h-2 rounded-full bg-zinc-800 overflow-visible mt-2 mb-1">
                  {/* Loss zone (left) and profit zone (right) */}
                  <div className="absolute inset-y-0 left-0 rounded-l-full bg-red-500/20" style={{ width: `${entryPct}%` }} />
                  <div className="absolute inset-y-0 right-0 rounded-r-full bg-emerald-500/20" style={{ left: `${entryPct}%` }} />
                  {/* Entry marker */}
                  <div className="absolute top-1/2 -translate-y-1/2 w-0.5 h-3 bg-zinc-400 rounded-full" style={{ left: `${entryPct}%` }} />
                  {/* Exit marker */}
                  {exit > 0 && (
                    <div className={`absolute top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full border ${isProfit ? "bg-emerald-400 border-emerald-300" : "bg-red-400 border-red-300"}`}
                      style={{ left: `calc(${exitPct}% - 3px)` }} />
                  )}
                  {/* Labels */}
                  <div className="absolute -bottom-4 left-0 text-[8px] text-red-400/70 font-mono">{isLong ? "SL" : "TP"}</div>
                  <div className="absolute -bottom-4 right-0 text-[8px] text-emerald-400/70 font-mono">{isLong ? "TP" : "SL"}</div>
                </div>
              );
            };

            return (
              <div className="divide-y divide-zinc-800/40 overflow-y-auto max-h-[calc(100vh-260px)]">
                {/* Real trades */}
                {realTrades.slice(0, 50).map((t, i) => {
                  const pnl = Number(t.pnl || 0);
                  const isWin = pnl > 0;
                  const openedAt = parseUTC(t.opened_at as string);
                  const closedAt = parseUTC(t.closed_at as string);
                  const timeOpen = fmtTime(openedAt);
                  const timeClose = fmtTime(closedAt);
                  const durationMs = (openedAt && closedAt) ? closedAt.getTime() - openedAt.getTime() : 0;
                  const durationMin = Math.round(durationMs / 60000);
                  const durationStr = durationMin < 60 ? `${durationMin}m` : `${Math.floor(durationMin / 60)}h ${durationMin % 60}m`;
                  const grade = String(t.outcome_grade || "");
                  const lesson = String(t.lessons_learned || "");
                  const strategy = String(t.proposing_strategy || "");
                  const entry = Number(t.entry_price || 0);
                  const exit = Number(t.exit_price || 0);
                  const sl = Number(t.stop_loss || 0);
                  const tp = Number(t.take_profit || 0);
                  const posSize = Number(t.position_size || 0);
                  const score = Number(t.strategy_score || t.confluence_score || 0);
                  const direction = String(t.direction || "");
                  const exitReason = String(t.exit_reason || "");
                  const stratDisplay = STRATEGY_INFO[strategy]?.displayName || (strategy ? strategy.replace(/_/g, " ").replace(/\b\w/g, (l: string) => l.toUpperCase()) : "—");
                  const reasonBadge = exitReasonBadge(exitReason);
                  const gradeStyle = grade === "A" ? "text-emerald-300 bg-emerald-500/20 border-emerald-500/40" :
                    grade === "B" ? "text-green-300 bg-green-500/20 border-green-500/40" :
                    grade === "C" ? "text-amber-300 bg-amber-500/20 border-amber-500/40" :
                    grade === "D" ? "text-orange-300 bg-orange-500/20 border-orange-500/40" :
                    grade === "F" ? "text-red-300 bg-red-500/20 border-red-500/40" : "text-zinc-500 bg-zinc-800 border-zinc-700";
                  // R:R ratio
                  const risk = Math.abs(entry - sl);
                  const reward = Math.abs(tp - entry);
                  const rr = risk > 0 ? (reward / risk).toFixed(1) : null;
                  // Zero P&L on non-dup trades = reconcile bug (exited at entry)
                  const zeroExplain = pnl === 0 && entry > 0 && Math.abs(exit - entry) < 0.0001;

                  return (
                    <div key={i} className={`px-5 py-4 transition-colors ${
                      pnl > 0 ? "hover:bg-emerald-500/5" : pnl < 0 ? "hover:bg-red-500/5" : "hover:bg-zinc-800/30"
                    }`}>
                      {/* Row 1: identity + P&L */}
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex items-center gap-2.5 flex-wrap">
                          {/* Grade */}
                          {grade ? (
                            <span className={`text-xs font-black font-mono px-2 py-0.5 rounded border ${gradeStyle}`}>{grade}</span>
                          ) : (
                            <span className="text-base">{pnl > 0 ? "\u2705" : pnl < 0 ? "\u274C" : "⬜"}</span>
                          )}
                          {/* Symbol + direction */}
                          <span className="text-sm font-bold text-zinc-100 tracking-wide">{t.symbol as string}</span>
                          <span className={`text-xs font-bold px-2 py-0.5 rounded-md ${dir(direction).bg} ${dir(direction).text} border border-current/20`}>{direction}</span>
                          {/* Timeframe */}
                          {String(t.timeframe || "") && (
                            <span className="text-[10px] font-mono font-bold text-violet-400 bg-violet-500/10 px-1.5 py-0.5 rounded">{String(t.timeframe)}</span>
                          )}
                          {/* Strategy */}
                          <span className="text-[11px] text-cyan-400/80">{stratDisplay}</span>
                        </div>
                        {/* P&L — big and prominent */}
                        <div className="text-right shrink-0">
                          <div className={`text-xl font-mono font-black ${pnlColor(pnl)}`}>{pnlSign(pnl)}</div>
                          {zeroExplain && (
                            <div className="text-[9px] text-zinc-600 mt-0.5">closed at entry price</div>
                          )}
                        </div>
                      </div>

                      {/* Row 2: exit reason + time */}
                      <div className="flex items-center gap-2 mt-2">
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${reasonBadge.cls}`}>{reasonBadge.label}</span>
                        {openedAt && <span className="text-[10px] text-zinc-600 font-mono">{timeOpen} → {timeClose || "?"}</span>}
                        {durationMin > 0 && <span className="text-[10px] text-zinc-600 font-mono">({durationStr})</span>}
                        {score > 0 && <span className="text-[10px] text-violet-400/60 font-mono ml-auto">Score {score.toFixed(0)}</span>}
                        {rr && <span className="text-[10px] text-zinc-500 font-mono">R:R {rr}</span>}
                      </div>

                      {/* Row 3: price track visual */}
                      {entry > 0 && sl > 0 && tp > 0 && (
                        <div className="mt-3 mb-2">
                          <PriceTrack entry={entry} exit={exit} sl={sl} tp={tp} direction={direction} />
                        </div>
                      )}

                      {/* Row 4: price details */}
                      <div className="flex items-center gap-4 mt-4 text-[10px] font-mono flex-wrap">
                        {entry > 0 && (
                          <div className="flex flex-col">
                            <span className="text-zinc-600 mb-0.5">ENTRY</span>
                            <span className="text-zinc-300 font-bold">{entry.toFixed(entry > 1000 ? 2 : 4)}</span>
                          </div>
                        )}
                        {exit > 0 && (
                          <div className="flex flex-col">
                            <span className="text-zinc-600 mb-0.5">EXIT</span>
                            <span className={`font-bold ${pnlColor(pnl)}`}>{exit.toFixed(exit > 1000 ? 2 : 4)}</span>
                          </div>
                        )}
                        {sl > 0 && (
                          <div className="flex flex-col">
                            <span className="text-red-500/60 mb-0.5">STOP LOSS</span>
                            <span className="text-red-400/80">{sl.toFixed(sl > 1000 ? 2 : 4)}</span>
                          </div>
                        )}
                        {tp > 0 && (
                          <div className="flex flex-col">
                            <span className="text-emerald-500/60 mb-0.5">TAKE PROFIT</span>
                            <span className="text-emerald-400/80">{tp.toFixed(tp > 1000 ? 2 : 4)}</span>
                          </div>
                        )}
                        {posSize > 0 && (
                          <div className="flex flex-col">
                            <span className="text-zinc-600 mb-0.5">SIZE</span>
                            <span className="text-zinc-400">{posSize.toFixed(posSize < 1 ? 4 : 2)}</span>
                          </div>
                        )}
                      </div>

                      {/* Lesson (if graded by AI) */}
                      {lesson && (
                        <div className="mt-3 text-[10px] text-zinc-500 italic bg-zinc-800/30 rounded-lg px-3 py-2 border-l-2 border-violet-500/30">
                          {lesson}
                        </div>
                      )}
                    </div>
                  );
                })}

                {/* System Events (dup_cleanup) — collapsed section */}
                {systemEvents.length > 0 && (
                  <div className="px-5 py-3 bg-zinc-900/40">
                    <div className="text-[10px] text-zinc-600 font-semibold uppercase tracking-wider mb-2">
                      System Events ({systemEvents.length}) — not real trades
                    </div>
                    <div className="space-y-1.5">
                      {systemEvents.map((t, i) => {
                        const openedAt = parseUTC(t.opened_at as string);
                        const entry = Number(t.entry_price || 0);
                        return (
                          <div key={i} className="flex items-center gap-3 text-[10px] font-mono text-zinc-700 py-1 px-2 rounded bg-zinc-800/20">
                            <span className="text-zinc-600">⬜</span>
                            <span className="text-zinc-500">{t.symbol as string}</span>
                            <span className={dir(t.direction as string).text}>{t.direction as string}</span>
                            {openedAt && <span>{fmtTime(openedAt)}</span>}
                            {entry > 0 && <span>@ {entry.toFixed(2)}</span>}
                            <span className="text-zinc-700 ml-auto">dup_cleanup — $0.00</span>
                            <span className="text-zinc-700 text-[9px] italic">Engine removed duplicate open position</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </Card>

        {/* RIGHT column: Open Positions */}
        <Card className="border-emerald-500/20">
          <CardHeader>
            <SectionTitle icon={"\uD83D\uDCCA"}>Open Positions</SectionTitle>
            <div className="flex items-center gap-2">
              {positions.length > 0 && (
                <span className="text-xs font-mono bg-violet-500/20 text-violet-400 px-2 py-0.5 rounded-full animate-pulse">{positions.length} live</span>
              )}
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-[10px] font-mono text-emerald-500/60">LIVE</span>
            </div>
          </CardHeader>
          <div className="p-3 overflow-y-auto max-h-[calc(100vh-300px)]">
            {positions.length === 0 ? (
              <div className="text-center py-8 text-zinc-600">
                <div className="text-3xl mb-2 opacity-30 animate-pulse">&#x1F50D;</div>
                <div className="text-xs font-medium text-zinc-500">No open positions</div>
                <div className="text-[10px] text-zinc-700 mt-1">Scanning 18 markets...</div>
              </div>
            ) : (
              <div className="space-y-3">
                {positions.map((p) => {
                  const d = dir(p.direction as string);
                  const pnl = Number(p.unrealized_pnl || 0);
                  const isProfit = pnl >= 0;
                  const posStrategy = String(p.proposing_strategy || "");
                  const posStratDisplay = STRATEGY_INFO[posStrategy]?.displayName || (posStrategy ? posStrategy.replace(/_/g, " ").replace(/\b\w/g, (l: string) => l.toUpperCase()) : "");
                  return (
                    <div key={p.id as string} className={`rounded-xl p-3.5 border-2 transition-all ${
                      isProfit ? "border-emerald-500/40 bg-gradient-to-br from-emerald-500/10 to-zinc-900/50" : "border-red-500/40 bg-gradient-to-br from-red-500/10 to-zinc-900/50"
                    }`}>
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="text-sm font-bold text-zinc-100">{p.symbol as string}</span>
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${d.text} bg-zinc-800/60`}>{d.label}</span>
                        </div>
                        <div className={`text-lg font-mono font-bold ${pnlColor(pnl)}`}>{pnlSign(pnl)}</div>
                      </div>
                      {/* Strategy name */}
                      {posStratDisplay && (
                        <div className="text-[10px] text-cyan-400/80 mb-2">{posStratDisplay}</div>
                      )}
                      {Number(p.entry_price) > 0 && Number(p.take_profit) > 0 && Number(p.stop_loss) > 0 && (
                        <div className="mb-2">
                          <div className="w-full bg-zinc-800 rounded-full h-1.5 overflow-hidden">
                            <div className={`h-full rounded-full transition-all duration-500 ${isProfit ? "bg-emerald-500" : "bg-red-500"}`}
                              style={{ width: `${Math.min(100, Math.max(0, ((Number(p.current_price) - Number(p.entry_price)) / (Number(p.take_profit) - Number(p.entry_price))) * 100))}%` }} />
                          </div>
                          <div className="flex justify-between text-[9px] text-zinc-600 mt-0.5">
                            <span>SL {(p.stop_loss as number).toFixed(2)}</span>
                            <span>TP {(p.take_profit as number).toFixed(2)}</span>
                          </div>
                        </div>
                      )}
                      <div className="flex items-center justify-between">
                        <div className="flex gap-2 text-[10px] font-mono text-zinc-400 flex-wrap">
                          <span>Now <span className="text-zinc-200">{Number(p.current_price || 0).toFixed(2)}</span></span>
                          {String(p.timeframe || "") !== "" && (
                            <span className="text-violet-400">{String(p.timeframe)}</span>
                          )}
                        </div>
                        <button onClick={() => onClose(p.id as string)}
                          className="px-2.5 py-1 text-[10px] bg-zinc-700 hover:bg-red-600 text-zinc-400 hover:text-white rounded-lg transition-all font-medium">
                          Close
                        </button>
                      </div>
                      {String(p.health_reason || "") !== "" && (
                        <div className="text-[10px] text-zinc-500 mt-1 font-mono">{String(p.health_reason)}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </Card>
      </div>{/* end main 3-col grid */}

      {/* Markets — ALL 18 lab instruments */}
      <Card className="border-violet-500/20">
        <CardHeader>
          <SectionTitle icon={"\uD83C\uDF0D"}>Markets</SectionTitle>
          <span className="text-[10px] text-zinc-500">{labMarkets.length} instruments monitored</span>
        </CardHeader>
        <div className="p-4 grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2.5">
          {labMarkets.map((m) => {
            const hasPos = m.has_position;
            const posDir = m.direction ? dir(m.direction) : null;
            const pnl = m.pnl || 0;
            // Find scan score for this instrument
            const scan = overview.find(o => o.symbol === m.symbol);
            const score = scan?.score || 0;
            return (
              <div key={m.symbol} onClick={() => onSelect(m.symbol)}
                className={`rounded-2xl p-3.5 border transition-all cursor-pointer group ${
                  selected === m.symbol
                    ? "border-violet-500/60 bg-violet-500/10 ring-1 ring-violet-500/20"
                    : hasPos
                      ? pnl >= 0
                        ? "border-emerald-500/30 bg-emerald-500/5 hover:bg-emerald-500/10"
                        : "border-red-500/30 bg-red-500/5 hover:bg-red-500/10"
                      : "border-zinc-800/60 bg-zinc-900/30 hover:border-zinc-700 hover:bg-zinc-800/40"
                }`}>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-bold text-zinc-100 group-hover:text-white transition-colors">{m.symbol.replace("USD", "")}</span>
                  {hasPos && posDir && (
                    <span className={`text-[8px] font-black px-1.5 py-0.5 rounded-full ${posDir.text} bg-zinc-800/80`}>{posDir.label}</span>
                  )}
                  {!hasPos && score >= 3 && (
                    <span className="text-[8px] font-bold text-amber-400 animate-pulse">&#x2B50;</span>
                  )}
                </div>
                <div className="text-sm font-mono font-semibold text-zinc-200">
                  {m.price > 0 ? (m.price >= 100 ? `$${m.price.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : `$${m.price.toFixed(4)}`) : "---"}
                </div>
                {scan?.regime && REGIMES[scan.regime] && (
                  <div className={`text-[8px] font-bold mt-1 ${REGIMES[scan.regime].color}`}>
                    {REGIMES[scan.regime].icon} {scan.regime}
                  </div>
                )}
                {score > 0 && !hasPos && (
                  <div className={`text-[9px] font-mono mt-0.5 ${scoreColor(score)}`}>
                    {scan?.direction === "LONG" ? "\u25B2" : scan?.direction === "SHORT" ? "\u25BC" : "\u25CF"} {score.toFixed(1)}
                  </div>
                )}
                {hasPos && (
                  <div className={`text-[10px] font-mono font-bold mt-1 ${pnlColor(pnl)}`}>{pnlSign(pnl)}</div>
                )}
              </div>
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

// =============================================================
// STRATEGIES TAB — Arena: strategies compete independently
// =============================================================

function StrategiesTab({ strategies, arenaData }: {
  strategies: Array<Record<string, unknown>>;
  arenaData: {
    leaderboard: Array<Record<string, unknown>>;
    active_proposals: Array<Record<string, unknown>>;
  } | null;
}) {
  const [expandedStrategy, setExpandedStrategy] = useState<string | null>(null);
  const [proposalsBlur, setProposalsBlur] = useState(false);
  const prevArenaRef = useRef(arenaData);

  // Blur proposals briefly when new arena data arrives via WS
  useEffect(() => {
    if (arenaData && arenaData !== prevArenaRef.current) {
      prevArenaRef.current = arenaData;
      setProposalsBlur(true);
      const t = setTimeout(() => setProposalsBlur(false), 400);
      return () => clearTimeout(t);
    }
  }, [arenaData]);

  const leaderboard = arenaData?.leaderboard || [];
  const proposals = arenaData?.active_proposals || [];

  const STATUS_COLORS: Record<string, string> = {
    proven: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
    standard: "text-amber-400 bg-amber-500/10 border-amber-500/30",
    caution: "text-orange-400 bg-orange-500/10 border-orange-500/30",
    suspended: "text-red-400 bg-red-500/10 border-red-500/30",
  };

  const STRATEGY_COLORS: Record<string, string> = {
    trend_momentum: "from-blue-500/20 to-blue-900/10 border-blue-500/30",
    mean_reversion: "from-violet-500/20 to-violet-900/10 border-violet-500/30",
    level_confluence: "from-amber-500/20 to-amber-900/10 border-amber-500/30",
    breakout_system: "from-emerald-500/20 to-emerald-900/10 border-emerald-500/30",
    williams_system: "from-cyan-500/20 to-cyan-900/10 border-cyan-500/30",
    order_flow_system: "from-pink-500/20 to-pink-900/10 border-pink-500/30",
  };

  return (
    <div className="space-y-4 animate-in fade-in duration-300">
      {/* Arena Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold text-amber-400 uppercase tracking-wider flex items-center gap-2">
          <span>{"\u2694\uFE0F"}</span> Strategy Arena — Competing Traders
        </h2>
        <span className="text-xs text-zinc-500">6 strategies competing</span>
      </div>

      {/* Active Proposals */}
      {proposals.length > 0 && (
        <Card glow="bg-gradient-to-r from-amber-500 to-orange-500">
          <div className="p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="text-xs font-bold text-amber-400 uppercase tracking-wider">Live Proposals</div>
              <div className="text-[10px] text-zinc-600">Winner = 40% signal + 25% R:R + 20% trust + 15% WR</div>
            </div>
            <div className={`grid grid-cols-1 md:grid-cols-2 gap-3 transition-all duration-500 ${proposalsBlur ? "blur-[1px] opacity-80" : "blur-0 opacity-100"}`}>
              {proposals.map((p, i) => {
                const entry = Number(p.entry || 0);
                const sl = Number(p.stop_loss || 0);
                const tp = Number(p.take_profit || 0);
                const rr = Number(p.risk_reward || 0);
                const riskPct = Number(p.risk_pct || 0);
                const profitPct = Number(p.profit_pct || 0);
                const arenaScore = Number(p.arena_score || 0);
                const trust = Number(p.trust_score || 50);
                const wr = Number(p.win_rate || 0);
                const rank = Number(p.rank || i + 1);
                const riskUsd = Number(p.risk_usd || 0);
                const profitUsd = Number(p.profit_usd || 0);
                const notionalUsd = Number(p.notional_usd || 0);
                const marginUsd = Number(p.margin_usd || 0);
                const willExecute = p.will_execute === true;
                const blockReason = p.block_reason ? String(p.block_reason) : null;
                const isLeader = rank === 1;
                return (
                <div key={i} className={`rounded-xl p-4 border transition-colors ${isLeader ? "bg-amber-950/30 border-amber-500/50 ring-1 ring-amber-500/20" : "bg-zinc-800/60 border-zinc-700/50 hover:border-amber-500/30"}`}>
                  {isLeader && (
                    <div className="flex items-center gap-2 mb-2 pb-2 border-b border-amber-500/20">
                      <span className="text-[10px] font-black text-amber-400 uppercase tracking-widest bg-amber-500/10 px-2 py-0.5 rounded-full border border-amber-500/30">NEXT TO EXECUTE</span>
                      <span className="text-[9px] text-amber-500/70">Highest arena score wins</span>
                    </div>
                  )}
                  <div className="flex justify-between items-center mb-2">
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-black w-5 h-5 rounded-full flex items-center justify-center ${isLeader ? "bg-amber-500 text-black" : rank === 2 ? "bg-zinc-400 text-black" : rank === 3 ? "bg-amber-700 text-white" : "bg-zinc-700 text-zinc-400"}`}>
                        {rank}
                      </span>
                      <div>
                        <span className="text-sm font-bold text-zinc-200">
                          {String(p.strategy).replace(/_/g, " ").replace(/\b\w/g, (l: string) => l.toUpperCase())}
                        </span>
                        <span className="text-[10px] text-zinc-600 ml-2">trust {trust.toFixed(0)} | WR {wr.toFixed(0)}%</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-mono font-black ${dir(String(p.direction)).text}`}>{String(p.direction)}</span>
                      <span className="text-xs text-zinc-400">{String(p.symbol)}</span>
                      <span className="text-[10px] text-zinc-600">{String(p.timeframe)}</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2 mb-2">
                    <div className="bg-zinc-900/60 rounded-lg p-2 text-center">
                      <div className="text-[9px] text-zinc-500 uppercase">Entry</div>
                      <div className="text-xs font-mono font-bold text-zinc-200">${entry.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
                    </div>
                    <div className="bg-red-900/20 rounded-lg p-2 text-center border border-red-500/10">
                      <div className="text-[9px] text-red-400 uppercase">Stop Loss</div>
                      <div className="text-xs font-mono font-bold text-red-400">${sl.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
                    </div>
                    <div className="bg-emerald-900/20 rounded-lg p-2 text-center border border-emerald-500/10">
                      <div className="text-[9px] text-emerald-400 uppercase">Take Profit</div>
                      <div className="text-xs font-mono font-bold text-emerald-400">${tp.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2 mb-2">
                    <div className="bg-red-950/30 rounded-lg p-2 border border-red-500/20">
                      <div className="text-[9px] text-red-400 uppercase mb-0.5">Risking</div>
                      <div className="flex items-baseline gap-1.5">
                        <span className="text-sm font-mono font-black text-red-400">${riskUsd.toFixed(2)}</span>
                        <span className="text-[10px] text-red-500/60">{riskPct.toFixed(2)}%</span>
                      </div>
                    </div>
                    <div className="bg-emerald-950/30 rounded-lg p-2 border border-emerald-500/20">
                      <div className="text-[9px] text-emerald-400 uppercase mb-0.5">To Make</div>
                      <div className="flex items-baseline gap-1.5">
                        <span className="text-sm font-mono font-black text-emerald-400">+${profitUsd.toFixed(2)}</span>
                        <span className="text-[10px] text-emerald-500/60">+{profitPct.toFixed(2)}%</span>
                      </div>
                    </div>
                  </div>
                  {notionalUsd > 0 && (
                    <div className="bg-zinc-900/40 rounded-lg p-2 mb-2 flex items-center justify-between">
                      <div>
                        <span className="text-[9px] text-zinc-500 uppercase">Capital trading</span>
                        <div className="text-xs font-mono font-bold text-zinc-300">${notionalUsd.toLocaleString(undefined, {maximumFractionDigits: 0})}</div>
                      </div>
                      {marginUsd > 0 && marginUsd !== notionalUsd && (
                        <div className="text-right">
                          <span className="text-[9px] text-zinc-500 uppercase">Margin</span>
                          <div className="text-xs font-mono font-bold text-zinc-400">${marginUsd.toFixed(2)}</div>
                        </div>
                      )}
                    </div>
                  )}
                  <div className={`rounded-lg p-2 mb-2 flex items-center gap-2 ${willExecute ? "bg-emerald-950/30 border border-emerald-500/20" : "bg-red-950/30 border border-red-500/20"}`}>
                    <span className={`text-[10px] font-black uppercase tracking-wider ${willExecute ? "text-emerald-400" : "text-red-400"}`}>
                      {willExecute ? "READY" : "BLOCKED"}
                    </span>
                    <span className={`text-[9px] ${willExecute ? "text-emerald-500/60" : "text-red-400/70"}`}>
                      {willExecute ? "passes position sizing & risk checks" : (blockReason || "position size = 0")}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 mb-2">
                    <div className="bg-zinc-900/40 rounded-lg p-1.5 text-center">
                      <div className="text-[9px] text-zinc-500">R:R Ratio</div>
                      <div className={`text-xs font-mono font-bold ${rr >= 2.5 ? "text-emerald-400" : rr >= 2 ? "text-amber-400" : "text-red-400"}`}>{rr.toFixed(1)}:1</div>
                    </div>
                    <div className="bg-amber-900/30 rounded-lg p-1.5 text-center border border-amber-500/20">
                      <div className="text-[9px] text-amber-400">Arena Score</div>
                      <div className="text-xs font-mono font-black text-amber-400">{arenaScore.toFixed(0)}</div>
                    </div>
                  </div>
                  <div className="mb-2">
                    <div className="flex justify-between text-[9px] text-zinc-500 mb-0.5">
                      <span>Signal Score</span>
                      <span>{String(p.score)}/100</span>
                    </div>
                    <div className="w-full bg-zinc-900/60 rounded-full h-1.5">
                      <div className={`h-full rounded-full ${Number(p.score) >= 70 ? "bg-emerald-500" : Number(p.score) >= 50 ? "bg-amber-500" : "bg-red-500"}`}
                        style={{ width: `${Math.min(100, Number(p.score))}%` }} />
                    </div>
                  </div>
                  {Array.isArray(p.factors) && p.factors.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {(p.factors as string[]).slice(0, 6).map((f, j) => (
                        <span key={j} className="text-[9px] bg-zinc-900/60 text-zinc-400 px-1.5 py-0.5 rounded">{f}</span>
                      ))}
                    </div>
                  )}
                </div>
                );
              })}
            </div>
          </div>
        </Card>
      )}

      {/* Leaderboard */}
      {leaderboard.length === 0 ? (
        <Card>
          <div className="p-12 text-center">
            <div className="text-4xl mb-3">{"\uD83C\uDFC6"}</div>
            <div className="text-zinc-400 text-sm">Arena is warming up</div>
            <div className="text-zinc-600 text-xs mt-1">Strategies are competing independently. The leaderboard will populate as trades are placed and closed.</div>
          </div>
        </Card>
      ) : (
        <div className="space-y-3">
          {leaderboard.map((s, rank) => {
            const name = String(s.name || "unknown");
            const trust = Number(s.trust_score || 50);
            const wr = Number(s.win_rate || 0);
            const trades = Number(s.total_trades || 0);
            const pnl = Number(s.total_pnl || 0);
            const pf = Number(s.profit_factor || 0);
            const streak = Number(s.current_streak || 0);
            const status = String(s.status || "standard");
            const threshold = Number(s.min_signal_score || 65);
            const isExpanded = expandedStrategy === name;
            const colorClass = STRATEGY_COLORS[name] || "from-zinc-500/20 to-zinc-900/10 border-zinc-500/30";
            const statusClass = STATUS_COLORS[status] || STATUS_COLORS.standard;

            return (
              <div key={name}
                className={`bg-gradient-to-br ${colorClass} border rounded-xl overflow-hidden cursor-pointer transition-all duration-300 hover:scale-[1.01]`}
                onClick={() => setExpandedStrategy(isExpanded ? null : name)}>

                <div className="p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className="text-2xl font-black text-zinc-600 font-mono w-8">#{rank + 1}</div>
                      <div>
                        <div className="font-bold text-sm text-zinc-100">
                          {name.replace(/_/g, " ").replace(/\b\w/g, (l: string) => l.toUpperCase())}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className={`text-[10px] px-2 py-0.5 rounded-full border ${statusClass}`}>{status.toUpperCase()}</span>
                          <span className="text-[10px] text-zinc-600">Threshold: {threshold}</span>
                        </div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-2xl font-mono font-black ${pnlColor(pnl)}`}>
                        {trades > 0 ? pnlSign(pnl) : "--"}
                      </div>
                      <div className="text-[10px] text-zinc-500">{trades} trades</div>
                    </div>
                  </div>

                  {/* Trust Score Bar */}
                  <div className="mb-3">
                    <div className="flex justify-between text-[10px] text-zinc-500 mb-1">
                      <span>Trust Score</span>
                      <span className={trust >= 70 ? "text-emerald-400" : trust >= 40 ? "text-amber-400" : "text-red-400"}>
                        {trust.toFixed(0)}/100
                      </span>
                    </div>
                    <div className="w-full bg-zinc-800/60 rounded-full h-2.5">
                      <div className={`h-full rounded-full transition-all duration-700 ${
                        trust >= 70 ? "bg-emerald-500" : trust >= 40 ? "bg-amber-500" : "bg-red-500"
                      }`} style={{ width: `${trust}%` }} />
                    </div>
                  </div>

                  {/* Stats Grid */}
                  <div className="grid grid-cols-5 gap-2 text-xs">
                    <div className="bg-zinc-900/40 rounded-lg p-2 text-center">
                      <div className="text-[10px] text-zinc-500">Win Rate</div>
                      <div className={`font-mono font-bold ${wr >= 55 ? "text-emerald-400" : wr >= 45 ? "text-amber-400" : "text-red-400"}`}>
                        {trades > 0 ? `${wr.toFixed(0)}%` : "--"}
                      </div>
                    </div>
                    <div className="bg-zinc-900/40 rounded-lg p-2 text-center">
                      <div className="text-[10px] text-zinc-500">W/L</div>
                      <div className="font-mono font-bold text-zinc-200">
                        {String(s.wins || 0)}/{String(s.losses || 0)}
                      </div>
                    </div>
                    <div className="bg-zinc-900/40 rounded-lg p-2 text-center">
                      <div className="text-[10px] text-zinc-500">PF</div>
                      <div className={`font-mono font-bold ${pf >= 1.5 ? "text-emerald-400" : pf >= 1 ? "text-amber-400" : "text-red-400"}`}>
                        {pf > 0 ? pf.toFixed(1) : "--"}
                      </div>
                    </div>
                    <div className="bg-zinc-900/40 rounded-lg p-2 text-center">
                      <div className="text-[10px] text-zinc-500">Streak</div>
                      <div className={`font-mono font-bold ${streak > 0 ? "text-emerald-400" : streak < 0 ? "text-red-400" : "text-zinc-500"}`}>
                        {streak > 0 ? `W${streak}` : streak < 0 ? `L${Math.abs(streak)}` : "--"}
                      </div>
                    </div>
                    <div className="bg-zinc-900/40 rounded-lg p-2 text-center">
                      <div className="text-[10px] text-zinc-500">Expect</div>
                      <div className={`font-mono font-bold ${Number(s.expectancy || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {trades > 0 ? `$${Number(s.expectancy || 0).toFixed(2)}` : "--"}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Expanded: recent proposals and trades */}
                {isExpanded && (
                  <div className="border-t border-zinc-800/40 p-4 space-y-3 animate-in fade-in duration-200">
                    <div className="grid grid-cols-2 gap-3 text-xs">
                      <div className="bg-zinc-900/50 rounded-lg p-3">
                        <div className="text-zinc-500 mb-1">Best Trade</div>
                        <div className="font-mono font-bold text-emerald-400">{pnlSign(Number(s.best_trade || 0))}</div>
                      </div>
                      <div className="bg-zinc-900/50 rounded-lg p-3">
                        <div className="text-zinc-500 mb-1">Worst Trade</div>
                        <div className="font-mono font-bold text-red-400">{pnlSign(Number(s.worst_trade || 0))}</div>
                      </div>
                      <div className="bg-zinc-900/50 rounded-lg p-3">
                        <div className="text-zinc-500 mb-1">Avg Win</div>
                        <div className="font-mono font-bold text-emerald-400">{pnlSign(Number(s.avg_win || 0))}</div>
                      </div>
                      <div className="bg-zinc-900/50 rounded-lg p-3">
                        <div className="text-zinc-500 mb-1">Avg Loss</div>
                        <div className="font-mono font-bold text-red-400">{pnlSign(Number(s.avg_loss || 0))}</div>
                      </div>
                    </div>
                    <div className="text-[10px] text-zinc-600">
                      Max consecutive wins: {String(s.consecutive_wins || 0)} |
                      Max consecutive losses: {String(s.consecutive_losses || 0)} |
                      Last trade: {s.last_trade_at ? relativeTime(String(s.last_trade_at)) : "never"}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

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
  const [labRisk, setLabRisk] = useState<RiskStatus | null>(null);
  const [labPositions, setLabPositions] = useState<Array<Record<string, unknown>>>([]);
  const [labSummary, setLabSummary] = useState<Record<string, unknown> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ScanResult | null>(null);
  const [evalData, setEvalData] = useState<EvalResult | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [positions, setPositions] = useState<Array<Record<string, unknown>>>([]);
  const [labTrades, setLabTrades] = useState<Array<Record<string, unknown>>>([]);
  const [stratPerf, setStratPerf] = useState<Array<Record<string, unknown>>>([]);
  const [costsData, setCostsData] = useState<Record<string, unknown> | null>(null);
  const [strategyDetails, setStrategyDetails] = useState<Array<Record<string, unknown>>>([]);
  const [tf, setTf] = useState("5m");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [engineOnline, setEngineOnline] = useState(false);
  const [engineVersion, setEngineVersion] = useState<string>("");
  const [tradePeriod, setTradePeriod] = useState<TradePeriod>("today");
  const [tradeSummary, setTradeSummary] = useState<{ total: number; wins: number; losses: number; win_rate: number; total_pnl: number } | null>(null);
  const [labMarkets, setLabMarkets] = useState<LabMarket[]>([]);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [labPace, setLabPace] = useState<string>("");
  const [labPaceInfo, setLabPaceInfo] = useState<{ entry_tfs: string[]; min_rr: number; max_concurrent: number } | null>(null);
  const [labStatus, setLabStatus] = useState<{ broker_connected: boolean; consecutive_errors: number; exec_log: Array<Record<string, unknown>> } | null>(null);
  const [arenaData, setArenaData] = useState<{
    leaderboard: Array<Record<string, unknown>>;
    active_proposals: Array<Record<string, unknown>>;
  } | null>(null);
  const [tradeRejections, setTradeRejections] = useState<Array<{ symbol: string; reason: string; ts: string }>>([]);

  // WebSocket — live data replaces polling for positions, risk, arena, lab/broker status
  const WS_TOPICS = [
    "trade.positions", "risk.status", "arena.proposals", "arena.leaderboard",
    "lab.status", "broker.status", "system.health", "trade.executed", "trade.rejected",
  ] as const;

  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (!msg.topic || !msg.data) return;
    switch (msg.topic) {
      case "trade.positions":
        setLabPositions(msg.data as Array<Record<string, unknown>>);
        break;
      case "risk.status": {
        const d = msg.data as Record<string, unknown>;
        setLabRisk((prev) => ({ ...prev, balance: d.balance, total_pnl: d.pnl, total_pnl_pct: d.pnl_pct, total_drawdown_used_pct: d.drawdown_pct } as typeof prev));
        break;
      }
      case "arena.proposals":
        setArenaData(msg.data as typeof arenaData);
        break;
      case "arena.leaderboard":
        setArenaData((prev) => prev
          ? { ...prev, leaderboard: msg.data as Array<Record<string, unknown>> }
          : { leaderboard: msg.data as Array<Record<string, unknown>>, active_proposals: [] }
        );
        break;
      case "lab.status": {
        const d = msg.data as Record<string, unknown>;
        setLabStatus((prev) => ({
          ...prev,
          broker_connected: d.broker_connected as boolean,
          consecutive_errors: d.consecutive_errors as number,
          exec_log: prev?.exec_log ?? [],
        }));
        break;
      }
      case "broker.status": {
        const d = msg.data as Record<string, unknown>;
        setLabStatus((prev) => prev
          ? { ...prev, broker_connected: d.connected as boolean }
          : { broker_connected: d.connected as boolean, consecutive_errors: 0, exec_log: [] }
        );
        break;
      }
      case "system.health":
        setHealth(msg.data as typeof health);
        setEngineOnline(true);
        break;
      case "trade.rejected": {
        const d = msg.data as Record<string, unknown>;
        const rejection = {
          symbol: String(d.symbol || ""),
          reason: String(d.reason || "broker rejected order"),
          ts: msg.ts || new Date().toISOString(),
        };
        setTradeRejections((prev) => [rejection, ...prev].slice(0, 5));
        // Auto-clear after 8s (longer so user can read the reason)
        setTimeout(() => setTradeRejections((prev) => prev.filter((r) => r !== rejection)), 8000);
        break;
      }
    }
  }, []);

  const { status: wsStatus, lastConnected: wsLastConnected, requestSnapshot } = useWebSocket({
    url: WS_URL,
    topics: [...WS_TOPICS],
    onMessage: handleWsMessage,
  });

  // When WS connects, mark engine online
  useEffect(() => {
    if (wsStatus === "connected") setEngineOnline(true);
    if (wsStatus === "reconnecting") setEngineOnline(false);
  }, [wsStatus]);

  const refresh = useCallback(async () => {
    try {
      const [ovRes, rkRes, posRes, tradesRes, perfRes, costsRes, labRkRes, labPosRes, labSumRes, labTradesRes] = await Promise.all([
        fetch(`${ENGINE}/api/scan/all?timeframe=${tf}`),
        fetch(`${ENGINE}/api/risk/status`),
        fetch(`${ENGINE}/api/trade/positions`),
        fetch(`${ENGINE}/api/journal/trades?limit=30`),
        fetch(`${ENGINE}/api/journal/performance`),
        fetch(`${ENGINE}/api/costs/summary`),
        fetch(`${ENGINE}/api/lab/risk`),
        fetch(`${ENGINE}/api/lab/positions`),
        fetch(`${ENGINE}/api/lab/summary`),
        fetch(`${ENGINE}/api/lab/trades?limit=50&period=${tradePeriod}`),
      ]);
      if (!ovRes.ok || !rkRes.ok) throw new Error("fail");
      setOverview((await ovRes.json()).results || []);
      setRisk(await rkRes.json());
      if (posRes.ok) setPositions((await posRes.json()).positions || []);
      if (tradesRes.ok) {
        const trData = await tradesRes.json();
        // Use lab trades if available, fall back to production trades
        if (labTradesRes.ok) {
          const labTrData = await labTradesRes.json();
          setLabTrades(labTrData.trades?.length > 0 ? labTrData.trades : trData.trades || []);
          if (labTrData.summary) setTradeSummary(labTrData.summary);
        } else {
          setLabTrades(trData.trades || []);
        }
      }
      if (perfRes.ok) setStratPerf((await perfRes.json()).strategies || []);
      if (costsRes.ok) setCostsData(await costsRes.json());
      // Lab-specific data
      if (labRkRes.ok) setLabRisk(await labRkRes.json());
      if (labPosRes.ok) setLabPositions((await labPosRes.json()).positions || []);
      if (labSumRes.ok) setLabSummary(await labSumRes.json());
      // Fetch strategy details + lab markets + system health
      try {
        const [sdRes, lmRes, healthRes, labStatusRes] = await Promise.all([
          fetch(`${ENGINE}/api/lab/strategies`),
          fetch(`${ENGINE}/api/lab/markets`),
          fetch(`${ENGINE}/api/system/health`),
          fetch(`${ENGINE}/api/lab/status`),
        ]);
        if (sdRes.ok) setStrategyDetails((await sdRes.json()).strategies || []);
        if (lmRes.ok) setLabMarkets((await lmRes.json()).markets || []);
        if (healthRes.ok) setHealth(await healthRes.json());
        if (labStatusRes.ok) setLabStatus(await labStatusRes.json());
        try {
          const paceRes = await fetch(`${ENGINE}/api/lab/pace`);
          if (paceRes.ok) { const pd = await paceRes.json(); setLabPace(pd.pace || "balanced"); setLabPaceInfo({ entry_tfs: pd.entry_tfs || [], min_rr: pd.min_rr || 2, max_concurrent: pd.max_concurrent || 3 }); }
        } catch {}
      } catch { /* ignore */ }
      // Fetch version from /health
      try {
        const vRes = await fetch(`${ENGINE}/health`);
        if (vRes.ok) { const vd = await vRes.json(); setEngineVersion(vd.version || ""); }
      } catch {}
      setErr(null);
      setEngineOnline(true);
      setLastRefresh(new Date());
    } catch (e: unknown) {
      const isNetworkError = e instanceof TypeError && String(e).includes("fetch");
      setErr(
        isNetworkError
          ? "Cannot reach engine \u2014 run: cd engine && ../.venv/bin/python run.py"
          : "Engine returned an error \u2014 check engine logs for details"
      );
      setEngineOnline(false);
      setEngineVersion("");
    } finally { setLoading(false); }
  }, [tf, tradePeriod]);

  useEffect(() => {
    if (!selected) return;
    setEvalData(null);
    fetch(`${ENGINE}/api/scan/${selected}?timeframe=${tf}`)
      .then((r) => r.json()).then(setDetail).catch(() => setDetail(null));
  }, [selected, tf]);

  // Initial load — WS provides live updates after this
  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleEvaluate = useCallback(async () => {
    if (!selected) return;
    setEvalLoading(true);
    try { setEvalData(await (await fetch(`${ENGINE}/api/evaluate/${selected}?timeframe=${tf}`)).json()); }
    catch { setEvalData(null); }
    finally { setEvalLoading(false); }
  }, [selected, tf]);

  const handleClose = async (id: string) => {
    if (!confirm("Close this position?")) return;
    const endpoint = activeTab === "lab" ? `/api/lab/close/${id}` : `/api/trade/close/${id}`;
    await fetch(`${ENGINE}${endpoint}`, { method: "POST" });
    refresh();
  };

  const todayCost = Number((costsData as Record<string, unknown>)?.total_cost || 0);

  // Tab accent colors for the timeframe selector
  const tabAccent: Record<TabId, { active: string; ring: string }> = {
    lab: { active: "bg-violet-600 text-white", ring: "ring-violet-500/20" },
    strategies: { active: "bg-amber-600 text-white", ring: "ring-amber-500/20" },
    command: { active: "bg-blue-600 text-white", ring: "ring-blue-500/20" },
    evolution: { active: "bg-emerald-600 text-white", ring: "ring-emerald-500/20" },
  };

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-4 lg:px-8 lg:py-6">
      <Header activeTab={activeTab} onTabChange={setActiveTab} costs={todayCost} engineOnline={engineOnline} engineVersion={engineVersion} />

      {/* System Health Bar */}
      {engineOnline && <HealthBar health={health} />}

      {/* Error Banner */}
      {err && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 mb-4 text-red-400 text-sm flex items-center gap-2">
          <span>{"\u26A0\uFE0F"}</span>{err}
        </div>
      )}

      {/* Timeframe Selector (Command/Evolution only) + Refresh */}
      <div className="flex items-center justify-between mb-4">
        {activeTab === "command" || activeTab === "evolution" ? (
          <div className="flex items-center gap-1.5 bg-zinc-900/80 border border-zinc-800 rounded-full p-1">
            {["1m", "5m", "15m", "30m", "1h"].map((t) => (
              <button key={t} onClick={() => setTf(t)}
                className={`px-3 py-1.5 text-xs font-mono rounded-full transition-all ${
                  tf === t ? tabAccent[activeTab].active : "text-zinc-500 hover:text-zinc-300"
                }`}>{t}</button>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2">
            {activeTab === "lab" && (
              <>
                <span className="text-[10px] text-zinc-600 mr-1">Pace:</span>
                {["conservative", "balanced", "aggressive"].map((p) => {
                  const isActive = labPace === p;
                  const styles = p === "conservative"
                    ? { active: "bg-blue-600 text-white shadow-lg shadow-blue-500/30 border-blue-400", inactive: "bg-blue-600/10 text-blue-400/60 hover:bg-blue-600/30 border-blue-500/20" }
                    : p === "balanced"
                    ? { active: "bg-violet-600 text-white shadow-lg shadow-violet-500/30 border-violet-400", inactive: "bg-violet-600/10 text-violet-400/60 hover:bg-violet-600/30 border-violet-500/20" }
                    : { active: "bg-orange-600 text-white shadow-lg shadow-orange-500/30 border-orange-400", inactive: "bg-orange-600/10 text-orange-400/60 hover:bg-orange-600/30 border-orange-500/20" };
                  return (
                    <button key={p} onClick={async () => {
                      await fetch(`${ENGINE}/api/lab/pace/${p}`, { method: "POST" });
                      setLabPace(p);
                      refresh();
                    }}
                      className={`px-3 py-1 text-[10px] font-bold rounded-full transition-all border ${isActive ? styles.active : styles.inactive}`}>
                      {p === "conservative" ? "\uD83D\uDEE1\uFE0F Safe" : p === "balanced" ? "\u2696\uFE0F Balanced" : "\uD83D\uDD25 Aggro"}
                    </button>
                  );
                })}
              </>
            )}
            {activeTab !== "lab" && (
              <span className="text-[10px] text-zinc-600">Lab scans: 15m, 30m, 1h (entry) + 4h, 1d (context)</span>
            )}
          </div>
        )}
        <div className="flex items-center gap-3">
          {/* WS connection status indicator */}
          <div className="flex items-center gap-1.5">
            {wsStatus === "connected" && (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-[10px] text-emerald-500/70 font-mono">LIVE</span>
              </>
            )}
            {wsStatus === "reconnecting" && (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-ping" />
                <span className="text-[10px] text-amber-500/70 font-mono">RECONNECTING</span>
              </>
            )}
            {wsStatus === "connecting" && (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 animate-pulse" />
                <span className="text-[10px] text-zinc-500/70 font-mono">CONNECTING</span>
              </>
            )}
          </div>
          {wsLastConnected && (
            <span className="text-[10px] text-zinc-600 font-mono">
              {wsLastConnected.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true })}
            </span>
          )}
          <button onClick={() => { requestSnapshot(); refresh(); }}
            className="px-4 py-1.5 text-xs bg-zinc-800/60 text-zinc-400 hover:text-zinc-200 rounded-full transition-all hover:bg-zinc-800 flex items-center gap-1.5">
            {"\u21BB"} Refresh
          </button>
        </div>
      </div>

      {/* Broker Offline Banner — shown when engine is up but broker is disconnected */}
      {engineOnline && labStatus && labStatus.broker_connected === false && (
        <div className="mx-4 mb-2 px-4 py-2.5 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center gap-2 text-xs text-red-400">
          <span className="text-red-500 font-bold">&#x26A0;</span>
          <span><strong>Broker disconnected</strong> &mdash; positions and balance shown may be stale. Check Delta Exchange API status.</span>
        </div>
      )}

      {/* Engine Errors Banner — shown after 3+ consecutive tick failures */}
      {engineOnline && labStatus && labStatus.consecutive_errors >= 3 && (
        <div className="mx-4 mb-2 px-4 py-2.5 bg-amber-500/10 border border-amber-500/30 rounded-lg flex items-center gap-2 text-xs text-amber-400">
          <span className="text-amber-500 font-bold">&#x26A0;</span>
          <span><strong>Lab engine degraded</strong> &mdash; {labStatus.consecutive_errors} consecutive tick errors. Engine backing off. Check logs.</span>
        </div>
      )}

      {/* Trade Rejection Toasts — auto-dismiss after 8s */}
      {tradeRejections.length > 0 && (
        <div className="fixed bottom-4 right-4 flex flex-col gap-2 z-50 max-w-md">
          {tradeRejections.map((r, i) => (
            <div key={i} className="px-4 py-3 bg-orange-500/10 border border-orange-500/30 rounded-lg text-xs text-orange-400 shadow-lg backdrop-blur">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-orange-500">&#x26D4;</span>
                <strong>Trade rejected &mdash; {r.symbol}</strong>
              </div>
              <div className="text-[10px] text-orange-300/70 font-mono pl-5 break-all">{r.reason}</div>
            </div>
          ))}
        </div>
      )}

      {/* Loading State */}
      {loading ? (
        <div className="flex items-center justify-center py-24">
          <div className="text-center">
            <div className="relative">
              <div className="w-16 h-16 rounded-full border-2 border-violet-500/20 border-t-violet-500 animate-spin mx-auto" />
              <div className="absolute inset-0 flex items-center justify-center text-xl">&#x1F9EA;</div>
            </div>
            <div className="text-zinc-500 mt-4 text-sm">Connecting to engine...</div>
            <div className="text-[10px] text-zinc-700 mt-1">Scanning 18 markets</div>
          </div>
        </div>
      ) : (
        <>
          {activeTab === "lab" && (
            <LabTab
              risk={labRisk || risk} positions={labPositions.length > 0 ? labPositions : positions} labTrades={labTrades} stratPerf={strategyDetails}
              overview={overview} labMarkets={labMarkets} selected={selected} onSelect={setSelected} tf={tf} onClose={handleClose}
              tradePeriod={tradePeriod} onPeriodChange={setTradePeriod} tradeSummary={tradeSummary}
              onRefresh={refresh} health={health} paceInfo={labPaceInfo}
            />
          )}
          {activeTab === "strategies" && (
            <StrategiesTab strategies={strategyDetails} arenaData={arenaData} />
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
      <footer className="mt-12 text-center text-[10px] text-zinc-700/60 border-t border-zinc-800/20 pt-6 pb-2">
        <span className="bg-gradient-to-r from-violet-500/40 via-fuchsia-500/40 to-cyan-500/40 bg-clip-text text-transparent font-bold tracking-wider">NOTAS LAVE</span>
        {" \u00B7 "}v2 Architecture{" \u00B7 "}Built with Claude
      </footer>
    </main>
  );
}
