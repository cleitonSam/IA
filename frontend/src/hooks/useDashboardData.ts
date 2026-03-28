"use client";

import useSWR from "swr";

const getAuthHeaders = () => ({
  Authorization: `Bearer ${typeof window !== "undefined" ? localStorage.getItem("token") : ""}`,
});

const fetcher = async (url: string) => {
  const res = await fetch(url, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

// ─── Timeseries ────────────────────────────────────────────────────
export interface TimeseriesPoint {
  periodo: string;
  conversas: number;
  leads: number;
  intencao: number;
  tempo_resp: number;
  custo_usd: number;
  tokens: number;
}

export interface TimeseriesData {
  granularity: string;
  days: number;
  series: TimeseriesPoint[];
}

export function useTimeseries(days: number = 30, unidadeId?: number) {
  const params = new URLSearchParams({ days: String(days) });
  if (unidadeId) params.set("unidade_id", String(unidadeId));
  return useSWR<TimeseriesData>(
    `/api-backend/dashboard/metrics/timeseries?${params}`,
    fetcher,
    { refreshInterval: 60000, revalidateOnFocus: true }
  );
}

// ─── Funnel ────────────────────────────────────────────────────────
export interface FunnelStage {
  id: string;
  label: string;
  value: number;
  color: string;
  taxa: number;
}

export interface FunnelData {
  days: number;
  stages: FunnelStage[];
}

export function useFunnel(days: number = 30, unidadeId?: number) {
  const params = new URLSearchParams({ days: String(days) });
  if (unidadeId) params.set("unidade_id", String(unidadeId));
  return useSWR<FunnelData>(
    `/api-backend/dashboard/metrics/funnel?${params}`,
    fetcher,
    { refreshInterval: 60000, revalidateOnFocus: true }
  );
}

// ─── AI Performance ────────────────────────────────────────────────
export interface AIPerformanceData {
  days: number;
  ia: {
    total_chamadas: number;
    latencia_media_ms: number;
    cache_hit_rate: number;
    fallback_rate: number;
    custo_total_usd: number;
    custo_por_conversa: number;
    total_tokens: number;
  };
  conversas: {
    total: number;
    msgs_cliente_media: number;
    msgs_ia_media: number;
    tempo_resposta_medio: number;
  };
  escalacoes: number;
  mensagens_lidas: number;
  taxa_escalacao: number;
  atividade_por_hora: { hora: number; chamadas: number }[];
}

export function useAIPerformance(days: number = 7) {
  return useSWR<AIPerformanceData>(
    `/api-backend/dashboard/metrics/ai-performance?days=${days}`,
    fetcher,
    { refreshInterval: 60000, revalidateOnFocus: true }
  );
}

// ─── Empresa Metrics (já existente, agora com SWR) ──────────────────
export interface EmpresaMetrics {
  date: string;
  days: number;
  totals: Record<string, number>;
  por_unidade: Array<Record<string, any>>;
}

export function useEmpresaMetrics(days: number = 30) {
  return useSWR<EmpresaMetrics>(
    `/api-backend/dashboard/metrics/empresa?days=${days}`,
    fetcher,
    { refreshInterval: 60000, revalidateOnFocus: true }
  );
}
