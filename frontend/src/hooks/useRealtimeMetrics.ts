"use client";

import { useState, useEffect, useRef, useCallback } from "react";

interface RealtimeMetrics {
  timestamp: string;
  conversas_ativas: number;
  conversas_pausadas: number;
  circuit_breaker: string;
  hoje: {
    conversas: number;
    leads: number;
    intencao: number;
    tempo_resposta: number;
    taxa_conversao: number;
  };
  funil: {
    links_enviados: number;
    planos_exibidos: number;
    matriculas: number;
    escalacoes: number;
  };
  ia: {
    tokens: number;
    custo_usd: number;
    chamadas: number;
  };
  sentimento: {
    positivo: number;
    neutro: number;
    frustrado: number;
    irritado: number;
  };
}

interface UseRealtimeMetricsReturn {
  data: RealtimeMetrics | null;
  connected: boolean;
  error: string | null;
  reconnecting: boolean;
}

export function useRealtimeMetrics(empresaId: number | null): UseRealtimeMetricsReturn {
  const [data, setData] = useState<RealtimeMetrics | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptRef = useRef(0);
  const maxReconnectAttempts = 10;

  const connect = useCallback(() => {
    if (!empresaId) return;

    const token = localStorage.getItem("token");
    if (!token) {
      setError("Token de autenticacao ausente");
      return;
    }

    // Determine WebSocket URL
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/api-backend/ws/dashboard/${empresaId}?token=${token}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setError(null);
        setReconnecting(false);
        reconnectAttemptRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          if (!parsed.pong) {
            setData(parsed);
          }
        } catch {
          // Ignore parse errors
        }
      };

      ws.onclose = (event) => {
        setConnected(false);
        wsRef.current = null;

        if (event.code !== 1000 && reconnectAttemptRef.current < maxReconnectAttempts) {
          setReconnecting(true);
          const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 30000);
          reconnectAttemptRef.current += 1;
          reconnectTimerRef.current = setTimeout(connect, delay);
        }
      };

      ws.onerror = () => {
        setError("Erro na conexao WebSocket");
      };
    } catch (err) {
      setError("Falha ao conectar WebSocket");
    }
  }, [empresaId]);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close(1000);
        wsRef.current = null;
      }
    };
  }, [connect]);

  // Ping keepalive every 30s
  useEffect(() => {
    if (!connected || !wsRef.current) return;
    const interval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ ping: true }));
      }
    }, 30000);
    return () => clearInterval(interval);
  }, [connected]);

  return { data, connected, error, reconnecting };
}
