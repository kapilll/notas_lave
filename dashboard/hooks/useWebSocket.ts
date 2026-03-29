"use client";

/**
 * useWebSocket — core WebSocket hook for the Notas Lave dashboard.
 *
 * Features:
 * - Auto-connect on mount
 * - Auto-pong: replies to server pings to stay alive
 * - Reconnect with exponential backoff (1s → 2s → 4s → 8s → 16s → 30s max)
 * - Subscribe to topics on connect → server sends snapshots immediately
 * - Exposes `send()` and `requestSnapshot()` for manual actions
 *
 * Protocol:
 *   Server → Client: {"type": "ping"}                          → we reply {"type": "pong"}
 *   Server → Client: {"type": "connected", "client_id": "..."}
 *   Client → Server: {"action": "subscribe", "topics": [...]}
 *   Client → Server: {"type": "snapshot"}                     → server resends all snapshots
 *   Server → Client: {"topic": "...", "data": {...}, "ts": "ISO", "snapshot": true}
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type WsStatus = "connecting" | "connected" | "reconnecting" | "disconnected";

export interface WsMessage {
  type?: string;
  topic?: string;
  data?: unknown;
  ts?: string;
  snapshot?: boolean;
  client_id?: string;
  detail?: string;
}

interface UseWebSocketOptions {
  /** WebSocket URL, e.g. "ws://localhost:8000/ws" */
  url: string;
  /** Topics to subscribe to on connect */
  topics: string[];
  /** Called for every non-ping message from the server */
  onMessage: (msg: WsMessage) => void;
}

interface UseWebSocketResult {
  status: WsStatus;
  /** ISO timestamp of last successful connection */
  lastConnected: Date | null;
  /** Send any message over the WebSocket */
  send: (msg: object) => void;
  /** Ask server for a fresh snapshot of all subscribed topics */
  requestSnapshot: () => void;
}

export function useWebSocket({
  url,
  topics,
  onMessage,
}: UseWebSocketOptions): UseWebSocketResult {
  const [status, setStatus] = useState<WsStatus>("connecting");
  const [lastConnected, setLastConnected] = useState<Date | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Keep refs fresh so callbacks always see latest values
  const topicsRef = useRef(topics);
  const onMessageRef = useRef(onMessage);

  useEffect(() => { topicsRef.current = topics; }, [topics]);
  useEffect(() => { onMessageRef.current = onMessage; }, [onMessage]);

  const connect = useCallback(() => {
    // Don't open a second connection if one is already open/opening
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) return;

    setStatus(reconnectAttemptRef.current > 0 ? "reconnecting" : "connecting");

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      // URL invalid or WS not available — schedule retry
      const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 30000);
      reconnectAttemptRef.current++;
      reconnectTimerRef.current = setTimeout(connect, delay);
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptRef.current = 0;
      setStatus("connected");
      setLastConnected(new Date());
      // Subscribe to all topics — server sends snapshots immediately
      ws.send(JSON.stringify({ action: "subscribe", topics: topicsRef.current }));
    };

    ws.onmessage = (event) => {
      try {
        const msg: WsMessage = JSON.parse(event.data as string);
        // Auto-pong to keep connection alive
        if (msg.type === "ping") {
          ws.send(JSON.stringify({ type: "pong" }));
          return;
        }
        onMessageRef.current(msg);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      setStatus("reconnecting");
      // Exponential backoff capped at 30s
      const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 30_000);
      reconnectAttemptRef.current++;
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // onclose fires after onerror — let it handle reconnect
      ws.close();
    };
  }, [url]);

  const send = useCallback((msg: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  const requestSnapshot = useCallback(() => {
    send({ type: "snapshot" });
  }, [send]);

  useEffect(() => {
    // Only run in the browser
    if (typeof window === "undefined") return;
    connect();
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect]);

  return { status, lastConnected, send, requestSnapshot };
}
