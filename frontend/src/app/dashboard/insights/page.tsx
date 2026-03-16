"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import {
  MessageSquare, Clock, Target, ArrowUpRight, Building2, Activity,
  Star, Zap, BarChart3, PieChart
} from "lucide-react";
import { motion } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

export default function InsightsPage() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<any>(null);
  const [selectedRange, setSelectedRange] = useState("hoje");

  const getConfig = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } });

  useEffect(() => { fetchInsights(); }, [selectedRange]);

  const fetchInsights = async () => {
    setLoading(true);
    try {
      const days = selectedRange === "hoje" ? 1 : selectedRange === "7 dias" ? 7 : 30;
      const res = await axios.get(`/api-backend/dashboard/metrics/empresa?days=${days}`, getConfig());
      setData(res.data);
    } catch (error) { console.error("Erro:", error); }
    finally { setLoading(false); }
  };

  const totals = data?.totals || {};
  const porUnidade = data?.por_unidade || [];
  const neon = "#00d2ff";

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
              </div>
              <h1 className="text-4xl font-black tracking-tight" style={{ background: "linear-gradient(135deg,#fff 0%,#00d2ff 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                Inteligência Estratégica
              </h1>
              <p className="text-slate-500 mt-2 text-sm italic">Análise profunda de conversão, performance de unidades e uso de IA.</p>
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
              {/* KPI Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
                {[
                  { label: "Conversas IA", value: totals.total_conversas || 0, icon: MessageSquare },
                  { label: "Taxa de Conversão", value: `${totals.taxa_conversao || 0}%`, icon: Target },
                  { label: "Leads Quentes", value: totals.leads_qualificados || 0, icon: Star },
                  { label: "Tempo Resposta", value: `${totals.tempo_medio_resposta || 0}s`, icon: Clock },
                ].map((kpi, i) => (
                  <motion.div key={kpi.label} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.1 }}
                    className="bg-slate-900/50 border border-white/5 rounded-3xl p-7 relative overflow-hidden group hover:border-[#00d2ff]/20 transition-all">
                    <div className="absolute top-0 right-0 p-6 opacity-5 group-hover:opacity-10 transition-opacity">
                      <kpi.icon className="w-16 h-16" />
                    </div>
                    <div className="w-12 h-12 rounded-2xl bg-[#00d2ff]/10 border border-[#00d2ff]/20 flex items-center justify-center mb-5">
                      <kpi.icon className="w-6 h-6 text-[#00d2ff]" />
                    </div>
                    <p className="text-slate-500 text-[10px] font-black uppercase tracking-widest mb-1">{kpi.label}</p>
                    <h3 className="text-3xl font-black">{kpi.value}</h3>
                  </motion.div>
                ))}
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
                {/* Unit Performance */}
                <div className="lg:col-span-8 space-y-8">
                  <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-8">
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
                    </div>
                  </div>

                </div>

                {/* Funnel */}
                <div className="lg:col-span-4 space-y-6">
                  <div className="bg-[#00d2ff]/5 border border-[#00d2ff]/20 rounded-3xl p-8">
                    <div className="flex items-center justify-between mb-8">
                      <h2 className="text-lg font-black uppercase tracking-widest">Funil</h2>
                      <Activity className="w-5 h-5 text-[#00d2ff] animate-pulse" />
                    </div>
                    <div className="space-y-8 relative">
                      <div className="absolute left-[15px] top-4 bottom-4 w-[2px] bg-gradient-to-b from-[#00d2ff]/40 to-transparent" />
                      {[
                        { label: "Oportunidades", val: totals.total_conversas || 0, color: "bg-blue-600" },
                        { label: "Qualificados", val: totals.leads_qualificados || 0, color: "bg-[#00d2ff]" },
                        { label: "Intenção Alta", val: totals.intencao_compra || 0, color: "bg-emerald-500" },
                      ].map((step) => (
                        <div key={step.label} className="relative pl-12">
                          <div className={`absolute left-0 top-1 w-8 h-8 rounded-full ${step.color} flex items-center justify-center z-10 border-4 border-[#020617]`}>
                            <div className="w-2 h-2 rounded-full bg-white animate-pulse" />
                          </div>
                          <h5 className="font-black text-xs uppercase tracking-[0.2em] text-slate-500">{step.label}</h5>
                          <p className="text-2xl font-black">{step.val}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-8">
                    <h3 className="text-lg font-black uppercase tracking-widest mb-4">Exportar</h3>
                    <p className="text-xs text-slate-500 mb-6 leading-relaxed">Baixe sua base de leads qualificados para alimentar CRM externo.</p>
                    <button className="w-full bg-white text-black py-4 rounded-2xl font-black uppercase tracking-widest text-xs flex items-center justify-center gap-2 hover:scale-105 transition-all">
                      Extrair Base (CSV) <ArrowUpRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
