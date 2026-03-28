"use client";

import React, { useState, useEffect } from "react";
import {
  MessageSquare, Clock, Target, ArrowUpRight, Building2, Activity,
  Star, Zap, TrendingUp, Brain, Shield, DollarSign,
  Users, Wifi, WifiOff, AlertTriangle, CheckCircle
} from "lucide-react";
import { motion } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell
} from "recharts";
import {
  useTimeseries, useFunnel, useAIPerformance, useEmpresaMetrics,
  type TimeseriesPoint, type FunnelStage
} from "@/hooks/useDashboardData";
import { useRealtimeMetrics } from "@/hooks/useRealtimeMetrics";

// ─── Helpers ───────────────────────────────────────────────────────
function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return h > 0 ? `${d}d ${h}h` : `${d}d`;
  if (h > 0) return m > 0 ? `${h}h ${m}min` : `${h}h`;
  return `${m}min`;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return `${d.getDate().toString().padStart(2, "0")}/${(d.getMonth() + 1).toString().padStart(2, "0")}`;
  } catch { return iso; }
}

function formatCurrency(value: number): string {
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

const neon = "#00d2ff";

// ─── Custom Tooltip ────────────────────────────────────────────────
function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-900/95 border border-white/10 rounded-xl px-4 py-3 shadow-2xl backdrop-blur-xl">
      <p className="text-[10px] text-slate-400 font-bold uppercase tracking-widest mb-2">{formatDate(label)}</p>
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2 text-sm">
          <div className="w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span className="text-slate-300">{p.name}:</span>
          <span className="font-bold text-white">{typeof p.value === "number" ? p.value.toLocaleString() : p.value}</span>
        </div>
      ))}
    </div>
  );
}

// ─── KPI Card ──────────────────────────────────────────────────────
function KPICard({ label, value, icon: Icon, delay = 0 }: {
  label: string; value: string | number; icon: any; delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="bg-slate-900/50 border border-white/5 rounded-3xl p-7 relative overflow-hidden group hover:border-[#00d2ff]/20 transition-all"
    >
      <div className="absolute top-0 right-0 p-6 opacity-5 group-hover:opacity-10 transition-opacity">
        <Icon className="w-16 h-16" />
      </div>
      <div className="w-12 h-12 rounded-2xl bg-[#00d2ff]/10 border border-[#00d2ff]/20 flex items-center justify-center mb-5">
        <Icon className="w-6 h-6 text-[#00d2ff]" />
      </div>
      <p className="text-slate-500 text-[10px] font-black uppercase tracking-widest mb-1">{label}</p>
      <h3 className="text-3xl font-black">{value}</h3>
    </motion.div>
  );
}

// ─── Funnel Component ──────────────────────────────────────────────
function FunnelChart({ stages }: { stages: FunnelStage[] }) {
  const maxValue = Math.max(...stages.map(s => s.value), 1);
  return (
    <div className="space-y-4">
      {stages.map((stage, i) => {
        const widthPct = Math.max((stage.value / maxValue) * 100, 8);
        return (
          <motion.div
            key={stage.id}
            initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.1 }}
          >
            <div className="flex items-center justify-between mb-1.5 px-1">
              <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">{stage.label}</span>
              <div className="flex items-center gap-2">
                {i > 0 && (
                  <span className="text-[10px] font-bold text-slate-500">{stage.taxa}%</span>
                )}
                <span className="text-sm font-black text-white">{stage.value}</span>
              </div>
            </div>
            <div className="h-8 bg-white/5 rounded-xl overflow-hidden border border-white/[0.03]">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${widthPct}%` }}
                transition={{ duration: 1.2, delay: 0.3 + i * 0.15, ease: "circOut" }}
                className="h-full rounded-xl flex items-center pl-3"
                style={{ background: `linear-gradient(90deg, ${stage.color}cc, ${stage.color})` }}
              >
                <span className="text-[10px] font-black text-white/90 whitespace-nowrap">
                  {stage.value > 0 ? stage.value : ""}
                </span>
              </motion.div>
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}

// ─── Real-time Status Badge ────────────────────────────────────────
function StatusBadge({ connected, reconnecting }: { connected: boolean; reconnecting: boolean }) {
  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-[10px] font-bold uppercase tracking-widest border ${
      connected
        ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
        : reconnecting
        ? "bg-amber-500/10 border-amber-500/20 text-amber-400"
        : "bg-red-500/10 border-red-500/20 text-red-400"
    }`}>
      {connected ? (
        <><Wifi className="w-3 h-3" /> Tempo Real</>
      ) : reconnecting ? (
        <><WifiOff className="w-3 h-3 animate-pulse" /> Reconectando...</>
      ) : (
        <><WifiOff className="w-3 h-3" /> Offline</>
      )}
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────
export default function InsightsPage() {
  const [selectedRange, setSelectedRange] = useState("7 dias");
  const [empresaId, setEmpresaId] = useState<number | null>(null);

  // Get empresa_id from JWT
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split(".")[1]));
        setEmpresaId(payload.empresa_id || null);
      } catch { /* ignore */ }
    }
  }, []);

  const days = selectedRange === "hoje" ? 1 : selectedRange === "7 dias" ? 7 : 30;

  // SWR hooks for data
  const { data: tsData, isLoading: tsLoading } = useTimeseries(days);
  const { data: funnelData } = useFunnel(days);
  const { data: aiData } = useAIPerformance(Math.min(days, 30));
  const { data: empData, isLoading: empLoading } = useEmpresaMetrics(days);

  // WebSocket real-time
  const { data: rtData, connected, reconnecting } = useRealtimeMetrics(empresaId);

  const totals = empData?.totals || {};
  const porUnidade = empData?.por_unidade || [];
  const series = tsData?.series || [];
  const stages = funnelData?.stages || [];
  const loading = tsLoading && empLoading;

  // Prepare chart data with formatted dates
  const chartData = series.map((s: TimeseriesPoint) => ({
    ...s,
    name: formatDate(s.periodo),
  }));

  // Activity by hour data
  const hourData = aiData?.atividade_por_hora?.map(h => ({
    hora: `${h.hora}h`,
    chamadas: h.chamadas,
  })) || [];

  // Sentiment pie data
  const sentimentData = rtData ? [
    { name: "Positivo", value: rtData.sentimento.positivo, color: "#22c55e" },
    { name: "Neutro", value: rtData.sentimento.neutro, color: "#6366f1" },
    { name: "Frustrado", value: rtData.sentimento.frustrado, color: "#f59e0b" },
    { name: "Irritado", value: rtData.sentimento.irritado, color: "#ef4444" },
  ].filter(s => s.value > 0) : [];

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="insights" />
      <main className="flex-1 min-w-0 overflow-auto">
        <div className="fixed top-0 right-0 w-[500px] h-[400px] bg-[#00d2ff]/3 rounded-full blur-[120px] pointer-events-none" />
        <div className="relative z-10 p-8 lg:p-10 max-w-7xl mx-auto pb-20">

          {/* Header */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-8 mb-12">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-1.5 h-5 bg-[#00d2ff] rounded-full" />
                <span className="text-[10px] font-black text-[#00d2ff] uppercase tracking-[0.4em]">Fluxo Digital & Tech</span>
                <StatusBadge connected={connected} reconnecting={reconnecting} />
              </div>
              <h1 className="text-4xl font-black tracking-tight" style={{ background: "linear-gradient(135deg,#fff 0%,#00d2ff 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                Inteligencia Estrategica
              </h1>
              <p className="text-slate-500 mt-2 text-sm italic">Analise profunda com dados em tempo real, graficos e metricas de IA.</p>
            </div>
            <div className="flex p-1.5 bg-slate-900/60 border border-white/8 rounded-2xl">
              {["hoje", "7 dias", "30 dias"].map((r) => (
                <button key={r} onClick={() => setSelectedRange(r)}
                  className={`px-6 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest transition-all ${selectedRange === r ? "bg-[#00d2ff] text-black" : "text-slate-500 hover:text-white"}`}>
                  {r}
                </button>
              ))}
            </div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-40">
              <Zap className="w-10 h-10 text-[#00d2ff] animate-pulse" />
            </div>
          ) : (
            <>
              {/* ── Real-time bar (quando conectado) ─────────────── */}
              {rtData && connected && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}
                  className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-8"
                >
                  {[
                    { label: "Ativas Agora", value: rtData.conversas_ativas, icon: Activity, color: "text-emerald-400" },
                    { label: "Pausadas", value: rtData.conversas_pausadas, icon: AlertTriangle, color: "text-amber-400" },
                    { label: "Chamadas IA", value: rtData.ia.chamadas, icon: Brain, color: "text-[#00d2ff]" },
                    { label: "Tokens Hoje", value: rtData.ia.tokens.toLocaleString(), icon: Zap, color: "text-purple-400" },
                    { label: "Custo Hoje", value: formatCurrency(rtData.ia.custo_usd), icon: DollarSign, color: "text-green-400" },
                    { label: "Circuit Breaker", value: rtData.circuit_breaker, icon: rtData.circuit_breaker === "CLOSED" ? CheckCircle : Shield, color: rtData.circuit_breaker === "CLOSED" ? "text-emerald-400" : "text-red-400" },
                  ].map((item) => (
                    <div key={item.label} className="bg-slate-900/30 border border-white/5 rounded-2xl p-4 flex items-center gap-3">
                      <item.icon className={`w-5 h-5 ${item.color} flex-shrink-0`} />
                      <div className="min-w-0">
                        <p className="text-[9px] text-slate-500 font-bold uppercase tracking-widest truncate">{item.label}</p>
                        <p className="text-lg font-black">{item.value}</p>
                      </div>
                    </div>
                  ))}
                </motion.div>
              )}

              {/* ── KPI Grid ─────────────────────────────────────── */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
                <KPICard label="Conversas IA" value={totals.total_conversas || 0} icon={MessageSquare} delay={0} />
                <KPICard label="Taxa de Conversao" value={`${totals.taxa_conversao || 0}%`} icon={Target} delay={0.1} />
                <KPICard label="Leads Quentes" value={totals.leads_qualificados || 0} icon={Star} delay={0.2} />
                <KPICard label="Tempo Resposta" value={formatDuration(totals.tempo_medio_resposta || 0)} icon={Clock} delay={0.3} />
              </div>

              {/* ── Charts Row ───────────────────────────────────── */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-12">

                {/* Conversas + Leads Area Chart */}
                <motion.div
                  initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}
                  className="bg-slate-900/50 border border-white/5 rounded-3xl p-8"
                >
                  <div className="flex items-center gap-3 mb-6">
                    <TrendingUp className="w-5 h-5 text-[#00d2ff]" />
                    <h2 className="text-lg font-black">Conversas & Leads</h2>
                  </div>
                  <div className="h-[280px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={chartData}>
                        <defs>
                          <linearGradient id="gradConversas" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                          </linearGradient>
                          <linearGradient id="gradLeads" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor={neon} stopOpacity={0.3} />
                            <stop offset="95%" stopColor={neon} stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                        <XAxis dataKey="name" tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} />
                        <Tooltip content={<ChartTooltip />} />
                        <Area type="monotone" dataKey="conversas" name="Conversas" stroke="#6366f1" fill="url(#gradConversas)" strokeWidth={2} />
                        <Area type="monotone" dataKey="leads" name="Leads" stroke={neon} fill="url(#gradLeads)" strokeWidth={2} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </motion.div>

                {/* Custo IA Line Chart */}
                <motion.div
                  initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}
                  className="bg-slate-900/50 border border-white/5 rounded-3xl p-8"
                >
                  <div className="flex items-center gap-3 mb-6">
                    <DollarSign className="w-5 h-5 text-emerald-400" />
                    <h2 className="text-lg font-black">Custo IA & Tokens</h2>
                  </div>
                  <div className="h-[280px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                        <XAxis dataKey="name" tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} />
                        <YAxis yAxisId="left" tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} />
                        <YAxis yAxisId="right" orientation="right" tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} />
                        <Tooltip content={<ChartTooltip />} />
                        <Line yAxisId="left" type="monotone" dataKey="custo_usd" name="Custo USD" stroke="#22c55e" strokeWidth={2} dot={false} />
                        <Line yAxisId="right" type="monotone" dataKey="tokens" name="Tokens" stroke="#a78bfa" strokeWidth={2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </motion.div>
              </div>

              {/* ── Bottom Row: Units + Funnel + AI Stats ────────── */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">

                {/* Unit Performance */}
                <div className="lg:col-span-5 space-y-8">
                  <motion.div
                    initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}
                    className="bg-slate-900/50 border border-white/5 rounded-3xl p-8"
                  >
                    <div className="flex items-center gap-3 mb-8">
                      <Building2 className="w-6 h-6 text-[#00d2ff]" />
                      <h2 className="text-xl font-black">Performance por Unidade</h2>
                    </div>
                    <div className="space-y-6">
                      {porUnidade.map((u: any, i: number) => {
                        const maxConv = Math.max(...porUnidade.map((item: any) => item.total_conversas || 1));
                        const width = `${((u.total_conversas || 0) / maxConv) * 100}%`;
                        const rate = u.total_conversas > 0 ? Math.round((u.leads_qualificados / u.total_conversas) * 100) : 0;
                        return (
                          <div key={u.id} className="group">
                            <div className="flex items-center justify-between mb-2.5 px-1">
                              <div className="flex items-center gap-3">
                                <div className="w-7 h-7 rounded-lg bg-white/5 flex items-center justify-center text-[10px] font-black text-slate-500 group-hover:bg-[#00d2ff]/20 group-hover:text-[#00d2ff] transition-all">
                                  {String(i + 1).padStart(2, "0")}
                                </div>
                                <span className="font-bold text-sm">{u.nome}</span>
                              </div>
                              <div className="flex items-center gap-4">
                                <span className="text-[11px] font-black text-slate-500">Rate: <span className="text-white">{rate}%</span></span>
                                <span className="text-sm font-black">{u.total_conversas} <span className="text-[10px] text-slate-500">leads</span></span>
                              </div>
                            </div>
                            <div className="h-2.5 bg-white/5 rounded-full overflow-hidden border border-white/[0.03]">
                              <motion.div initial={{ width: 0 }} animate={{ width }} transition={{ duration: 1.5, delay: 0.4 + i * 0.1, ease: "circOut" }}
                                className="h-full bg-gradient-to-r from-blue-600 to-[#00d2ff] rounded-full" />
                            </div>
                          </div>
                        );
                      })}
                      {porUnidade.length === 0 && (
                        <p className="text-slate-500 text-sm text-center py-8">Nenhuma unidade com dados no periodo.</p>
                      )}
                    </div>
                  </motion.div>
                </div>

                {/* Funnel + Sentiment */}
                <div className="lg:col-span-4 space-y-6">
                  <motion.div
                    initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}
                    className="bg-[#00d2ff]/5 border border-[#00d2ff]/20 rounded-3xl p-8"
                  >
                    <div className="flex items-center justify-between mb-6">
                      <h2 className="text-lg font-black uppercase tracking-widest">Funil de Conversao</h2>
                      <Users className="w-5 h-5 text-[#00d2ff] animate-pulse" />
                    </div>
                    {stages.length > 0 ? (
                      <FunnelChart stages={stages} />
                    ) : (
                      <p className="text-slate-500 text-sm text-center py-8">Sem dados de funil no periodo.</p>
                    )}
                  </motion.div>

                  {/* Sentiment Pie */}
                  {sentimentData.length > 0 && (
                    <motion.div
                      initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.6 }}
                      className="bg-slate-900/50 border border-white/5 rounded-3xl p-8"
                    >
                      <div className="flex items-center gap-3 mb-4">
                        <Activity className="w-5 h-5 text-purple-400" />
                        <h2 className="text-lg font-black">Sentimento (Tempo Real)</h2>
                      </div>
                      <div className="h-[180px]">
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie
                              data={sentimentData}
                              cx="50%"
                              cy="50%"
                              innerRadius={50}
                              outerRadius={75}
                              paddingAngle={3}
                              dataKey="value"
                            >
                              {sentimentData.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={entry.color} />
                              ))}
                            </Pie>
                            <Tooltip
                              contentStyle={{ background: "#0f172a", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "12px" }}
                              labelStyle={{ color: "#94a3b8" }}
                              itemStyle={{ color: "#fff" }}
                            />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="flex flex-wrap gap-3 mt-2 justify-center">
                        {sentimentData.map(s => (
                          <div key={s.name} className="flex items-center gap-1.5">
                            <div className="w-2.5 h-2.5 rounded-full" style={{ background: s.color }} />
                            <span className="text-[10px] font-bold text-slate-400">{s.name} ({s.value})</span>
                          </div>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </div>

                {/* AI Performance Stats */}
                <div className="lg:col-span-3 space-y-6">
                  <motion.div
                    initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}
                    className="bg-slate-900/50 border border-white/5 rounded-3xl p-8"
                  >
                    <div className="flex items-center gap-3 mb-6">
                      <Brain className="w-5 h-5 text-purple-400" />
                      <h2 className="text-lg font-black">Performance IA</h2>
                    </div>
                    <div className="space-y-5">
                      {aiData && [
                        { label: "Cache Hit Rate", value: `${aiData.ia.cache_hit_rate}%`, color: aiData.ia.cache_hit_rate > 30 ? "text-emerald-400" : "text-amber-400" },
                        { label: "Latencia Media", value: `${aiData.ia.latencia_media_ms}ms`, color: aiData.ia.latencia_media_ms < 3000 ? "text-emerald-400" : "text-red-400" },
                        { label: "Fallback Rate", value: `${aiData.ia.fallback_rate}%`, color: aiData.ia.fallback_rate < 5 ? "text-emerald-400" : "text-amber-400" },
                        { label: "Taxa Escalacao", value: `${aiData.taxa_escalacao}%`, color: "text-purple-400" },
                        { label: "Custo/Conversa", value: formatCurrency(aiData.ia.custo_por_conversa), color: "text-green-400" },
                        { label: "Msgs/Conversa", value: `${aiData.conversas.msgs_ia_media}`, color: "text-slate-300" },
                      ].map((stat) => (
                        <div key={stat.label} className="flex items-center justify-between">
                          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">{stat.label}</span>
                          <span className={`text-sm font-black ${stat.color}`}>{stat.value}</span>
                        </div>
                      ))}
                    </div>
                  </motion.div>

                  {/* Activity by Hour */}
                  {hourData.length > 0 && (
                    <motion.div
                      initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.6 }}
                      className="bg-slate-900/50 border border-white/5 rounded-3xl p-8"
                    >
                      <h3 className="text-sm font-black uppercase tracking-widest text-slate-400 mb-4">Atividade por Hora</h3>
                      <div className="h-[120px]">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={hourData}>
                            <XAxis dataKey="hora" tick={{ fill: "#64748b", fontSize: 8 }} axisLine={false} tickLine={false} interval={2} />
                            <YAxis hide />
                            <Tooltip
                              contentStyle={{ background: "#0f172a", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "8px", fontSize: "12px" }}
                              labelStyle={{ color: "#94a3b8" }}
                              itemStyle={{ color: "#fff" }}
                            />
                            <Bar dataKey="chamadas" name="Chamadas" fill={neon} radius={[4, 4, 0, 0]} />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </motion.div>
                  )}

                  {/* Export */}
                  <motion.div
                    initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.7 }}
                    className="bg-slate-900/50 border border-white/5 rounded-3xl p-8"
                  >
                    <h3 className="text-lg font-black uppercase tracking-widest mb-4">Exportar</h3>
                    <p className="text-xs text-slate-500 mb-6 leading-relaxed">Baixe sua base de leads qualificados para alimentar CRM externo.</p>
                    <button className="w-full bg-white text-black py-4 rounded-2xl font-black uppercase tracking-widest text-xs flex items-center justify-center gap-2 hover:scale-105 transition-all">
                      Extrair Base (CSV) <ArrowUpRight className="w-4 h-4" />
                    </button>
                  </motion.div>
                </div>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
