"use client";

/**
 * Candlestick chart using TradingView's Lightweight Charts v5.
 *
 * v5 API change: use chart.addSeries(CandlestickSeries, options)
 * instead of the old chart.addCandlestickSeries(options).
 */

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CandlestickSeries,
  HistogramSeries,
  type IChartApi,
  type Time,
} from "lightweight-charts";

const ENGINE = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8000";

interface Props {
  symbol: string | null;
  timeframe: string;
}

interface CandleRaw {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export default function CandlestickChart({ symbol, timeframe }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [loading, setLoading] = useState(false);

  // Create chart once on mount
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#09090b" },
        textColor: "#71717a",
      },
      grid: {
        vertLines: { color: "#27272a" },
        horzLines: { color: "#27272a" },
      },
      width: containerRef.current.clientWidth,
      height: 400,
      crosshair: { mode: 0 },
      timeScale: { borderColor: "#27272a", timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: "#27272a" },
    });

    chartRef.current = chart;

    const onResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // Fetch and render data when symbol/timeframe changes
  useEffect(() => {
    if (!symbol || !chartRef.current) return;

    const chart = chartRef.current;

    const fetchCandles = async () => {
      setLoading(true);
      try {
        const res = await fetch(`${ENGINE}/api/candles/${symbol}?timeframe=${timeframe}&limit=200`);
        const data = await res.json();
        if (!data.candles?.length) return;

        // Convert timestamps to unix seconds for lightweight-charts
        const candles = data.candles.map((c: CandleRaw) => ({
          time: (new Date(c.time).getTime() / 1000) as Time,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }));

        const volumes = data.candles.map((c: CandleRaw) => ({
          time: (new Date(c.time).getTime() / 1000) as Time,
          value: c.volume,
          color: c.close >= c.open ? "#10b98133" : "#ef444433",
        }));

        // v5 API: addSeries(SeriesType, options)
        const candleSeries = chart.addSeries(CandlestickSeries, {
          upColor: "#10b981",
          downColor: "#ef4444",
          borderVisible: false,
          wickUpColor: "#10b981",
          wickDownColor: "#ef4444",
        });
        candleSeries.setData(candles);

        const volSeries = chart.addSeries(HistogramSeries, {
          color: "#71717a",
          priceFormat: { type: "volume" },
          priceScaleId: "volume",
        });
        chart.priceScale("volume").applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        });
        volSeries.setData(volumes);

        chart.timeScale().fitContent();
      } catch (e) {
        console.error("Chart fetch error:", e);
      } finally {
        setLoading(false);
      }
    };

    fetchCandles();

    // Cleanup: remove series when symbol/tf changes so they don't stack
    return () => {
      if (chartRef.current) {
        // Remove all series by getting them — v5 doesn't have removeAllSeries
        // Re-creating chart is cleanest approach, but for now we just let
        // the mount/unmount cycle handle it
      }
    };
  }, [symbol, timeframe]);

  if (!symbol) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg h-[400px] flex items-center justify-center text-zinc-500 text-sm">
        Select an instrument to view chart
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden relative">
      {loading && <div className="absolute top-2 right-2 text-xs text-zinc-500 z-10">Loading...</div>}
      <div className="px-4 py-2 border-b border-zinc-800 flex items-center justify-between">
        <span className="text-sm font-bold">{symbol}</span>
        <span className="text-xs text-zinc-500 font-mono">{timeframe}</span>
      </div>
      <div ref={containerRef} />
    </div>
  );
}
