"use client";

import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle2,
  Sparkles,
  Trash2,
  RefreshCw,
  AlertCircle,
} from "lucide-react";

type ConfigStatus = {
  empresa_id: number;
  tem_personalidade_ativa: boolean;
  completude_pct: number;
  campos_ok: string[];
  campos_vazios: { campo: string; descricao: string }[];
  contadores: {
    faqs_ativas: number;
    kb_items: number;
    planos_ativos: number;
    unidades_ativas: number;
  };
  alertas: string[];
};

type FlushTipo =
  | "all"
  | "faq"
  | "kb"
  | "personalidade"
  | "planos"
  | "integracao";

const LABEL_FLUSH: Record<FlushTipo, string> = {
  all: "Limpar memória inteira do bot",
  faq: "Cache de FAQ",
  kb: "Cache de base de conhecimento",
  personalidade: "Cache de personalidade",
  planos: "Cache de planos",
  integracao: "Cache de integração",
};

export default function BotCompletudeCard() {
  const [status, setStatus] = useState<ConfigStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [flushing, setFlushing] = useState<FlushTipo | null>(null);
  const [lastFlush, setLastFlush] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    const token =
      typeof window !== "undefined" ? localStorage.getItem("token") : null;
    if (!token) return;
    try {
      const { data } = await axios.get<ConfigStatus>(
        "/api-backend/api/cache/config-status",
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setStatus(data);
    } catch (err) {
      console.error("[BotCompletudeCard] erro ao buscar status:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const doFlush = async (tipo: FlushTipo) => {
    const token = localStorage.getItem("token");
    if (!token) return;

    // Confirmação só pra "all" (ação mais agressiva)
    if (tipo === "all") {
      if (
        !window.confirm(
          "Limpar a memória inteira do bot? A próxima mensagem vai recarregar TUDO do banco. Recomendado após muitas alterações."
        )
      )
        return;
    }

    setFlushing(tipo);
    try {
      const endpoint =
        tipo === "all"
          ? "/api-backend/api/cache/flush"
          : `/api-backend/api/cache/flush/${tipo}`;
      await axios.post(
        endpoint,
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setLastFlush(new Date().toLocaleTimeString("pt-BR"));
      await fetchStatus(); // refaz a leitura após flush
    } catch (err) {
      console.error("[BotCompletudeCard] erro ao limpar:", err);
      window.alert("Não foi possível limpar o cache. Tenta de novo em alguns segundos.");
    } finally {
      setFlushing(null);
    }
  };

  if (loading) {
    return (
      <div className="mb-6 bg-slate-900/40 border border-white/[0.06] rounded-2xl p-5">
        <div className="h-4 w-48 bg-white/5 rounded animate-pulse mb-3" />
        <div className="h-2 w-full bg-white/5 rounded animate-pulse" />
      </div>
    );
  }

  if (!status) return null;

  const pct = Math.max(0, Math.min(100, status.completude_pct ?? 0));
  const barColor =
    pct >= 80
      ? "from-emerald-400 to-emerald-500"
      : pct >= 50
      ? "from-amber-400 to-amber-500"
      : "from-rose-400 to-rose-500";

  const pctTextColor =
    pct >= 80
      ? "text-emerald-400"
      : pct >= 50
      ? "text-amber-400"
      : "text-rose-400";

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.15 }}
      className="mb-6 bg-slate-900/40 border border-white/[0.06] hover:border-primary/20 rounded-2xl p-5 transition-all"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <Sparkles className="w-5 h-5 text-primary" />
          </div>
          <div>
            <p className="text-sm font-bold">Completude do Bot</p>
            <p className="text-xs text-gray-500">
              Quanto da personalidade vem dos campos que você preencheu
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchStatus}
            disabled={flushing !== null}
            className="inline-flex items-center gap-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl px-3 py-1.5 text-xs font-medium text-gray-300 transition-all disabled:opacity-50"
            title="Recarregar status"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Atualizar
          </button>
          <button
            onClick={() => doFlush("all")}
            disabled={flushing !== null}
            className="inline-flex items-center gap-2 bg-primary/10 hover:bg-primary/20 border border-primary/30 rounded-xl px-3 py-1.5 text-xs font-bold text-primary transition-all disabled:opacity-50"
            title={LABEL_FLUSH.all}
          >
            {flushing === "all" ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Trash2 className="w-3.5 h-3.5" />
            )}
            Limpar memória do bot
          </button>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-gray-500">
            {status.campos_ok.length} de{" "}
            {status.campos_ok.length + status.campos_vazios.length} campos
            preenchidos
          </span>
          <span className={`text-2xl font-bold tracking-tight ${pctTextColor}`}>
            {pct.toFixed(0)}%
          </span>
        </div>
        <div className="h-2 w-full bg-white/5 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.6 }}
            className={`h-full bg-gradient-to-r ${barColor}`}
          />
        </div>
      </div>

      {/* Alertas */}
      {status.alertas && status.alertas.length > 0 && (
        <div className="mb-4 space-y-2">
          {status.alertas.map((a, i) => (
            <div
              key={i}
              className="flex items-start gap-2 bg-rose-500/5 border border-rose-500/20 rounded-xl px-3 py-2 text-xs"
            >
              <AlertTriangle className="w-3.5 h-3.5 text-rose-400 flex-shrink-0 mt-0.5" />
              <span className="text-rose-200/90 leading-relaxed">{a}</span>
            </div>
          ))}
        </div>
      )}

      {/* Contadores */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <MiniStat
          label="FAQs ativas"
          value={status.contadores.faqs_ativas}
          critico={status.contadores.faqs_ativas < 3}
        />
        <MiniStat
          label="Base de conhecimento"
          value={status.contadores.kb_items}
        />
        <MiniStat
          label="Planos ativos"
          value={status.contadores.planos_ativos}
          critico={status.contadores.planos_ativos === 0}
        />
        <MiniStat
          label="Unidades ativas"
          value={status.contadores.unidades_ativas}
          critico={status.contadores.unidades_ativas === 0}
        />
      </div>

      {/* Campos vazios */}
      {status.campos_vazios.length > 0 ? (
        <div>
          <p className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wider">
            Campos para preencher ({status.campos_vazios.length})
          </p>
          <div className="flex flex-wrap gap-2">
            {status.campos_vazios.slice(0, 8).map((c) => (
              <a
                key={c.campo}
                href="/dashboard/personality"
                title={c.descricao}
                className="inline-flex items-center gap-1.5 bg-amber-500/5 hover:bg-amber-500/10 border border-amber-500/20 rounded-xl px-3 py-1.5 text-[11px] font-medium text-amber-300 transition-all"
              >
                <AlertCircle className="w-3 h-3" />
                {c.campo.replace(/_/g, " ")}
              </a>
            ))}
            {status.campos_vazios.length > 8 && (
              <a
                href="/dashboard/personality"
                className="inline-flex items-center gap-1 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl px-3 py-1.5 text-[11px] font-medium text-gray-400 transition-all"
              >
                +{status.campos_vazios.length - 8} mais…
              </a>
            )}
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-xs text-emerald-400 bg-emerald-500/5 border border-emerald-500/20 rounded-xl px-3 py-2">
          <CheckCircle2 className="w-3.5 h-3.5" />
          Todos os campos críticos preenchidos. Bot usa 100% do seu conteúdo.
        </div>
      )}

      {/* Last flush timestamp */}
      {lastFlush && (
        <p className="text-[10px] text-gray-600 mt-3 font-medium">
          Memória limpa às {lastFlush} · próxima mensagem usa conteúdo atualizado
        </p>
      )}
    </motion.div>
  );
}

function MiniStat({
  label,
  value,
  critico,
}: {
  label: string;
  value: number;
  critico?: boolean;
}) {
  return (
    <div
      className={`bg-slate-950/40 border ${
        critico ? "border-rose-500/30" : "border-white/[0.06]"
      } rounded-xl px-3 py-2.5`}
    >
      <p className="text-[10px] text-gray-500 uppercase tracking-widest mb-1">
        {label}
      </p>
      <p
        className={`text-lg font-bold ${
          critico ? "text-rose-400" : "text-white"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
