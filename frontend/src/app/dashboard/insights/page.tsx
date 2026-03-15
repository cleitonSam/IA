"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { 
  TrendingUp, Users, MessageSquare, Clock, Target, ArrowUpRight, 
  ChevronRight, ArrowLeft, Building2, Brain, Activity, Star, 
  Zap, DollarSign, Cpu, BarChart3, PieChart
} from "lucide-react";
import { motion } from "framer-motion";

export default function InsightsPage() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<any>(null);
  const [selectedRange, setSelectedRange] = useState("hoje");

  const getConfig = () => {
    const token = localStorage.getItem("token");
    return { headers: { Authorization: `Bearer ${token}` } };
  };

  useEffect(() => {
    fetchInsights();
  }, [selectedRange]);

  const fetchInsights = async () => {
    setLoading(true);
    try {
      // Usando o endpoint de métricas agregadas da empresa
      const res = await axios.get("/api-backend/dashboard/metrics/empresa", getConfig());
      setData(res.data);
    } catch (error) {
      console.error("Erro ao carregar insights:", error);
    } finally {
      setLoading(false);
    }
  };

  if (loading && !data) {
    return (
       <div className="min-h-screen bg-black flex items-center justify-center">
         <div className="flex flex-col items-center gap-4">
           <Zap className="w-10 h-10 text-primary animate-pulse" />
           <p className="text-[10px] font-black uppercase tracking-[0.3em] text-gray-500">Sincronizando Dados...</p>
         </div>
       </div>
    );
  }

  const totals = data?.totals || {};
  const porUnidade = data?.por_unidade || [];

  return (
    <div className="min-h-screen bg-mesh text-white p-6 md:p-12 pb-40">
      <div className="max-w-7xl mx-auto">
        
        {/* Unitary Header Structure - Standardized */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-8 mb-16">
          <div className="flex items-center gap-5">
            <a href="/dashboard" className="p-3.5 bg-white/5 hover:bg-primary/10 rounded-2xl transition-all border border-white/10 hover:border-primary/30 group">
              <ArrowLeft className="w-5 h-5 group-hover:text-primary transition-colors" />
            </a>
            <div>
              <h1 className="text-4xl font-black flex items-center gap-3">
                <BarChart3 className="w-10 h-10 text-primary neon-glow" />
                <span className="text-gradient">Inteligência Estratégica</span>
              </h1>
              <p className="text-gray-400 mt-1 font-medium italic opacity-80">Análise profunda de conversão, performance de unidades e uso de IA.</p>
            </div>
          </div>

          <div className="flex p-2 bg-black/40 border border-white/10 rounded-[2rem] blue-tint">
             {["hoje", "7 dias", "30 dias"].map((range) => (
               <button
                 key={range}
                 onClick={() => setSelectedRange(range)}
                 className={`px-8 py-3 rounded-[1.5rem] text-[10px] font-black uppercase tracking-widest transition-all ${
                   selectedRange === range ? "bg-primary text-black shadow-lg shadow-primary/20" : "text-gray-500 hover:text-white"
                 }`}
               >
                 {range}
               </button>
             ))}
          </div>
        </div>

        {/* KPI Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
           {[
             { label: "Conversas IA", value: totals.total_conversas || 0, icon: MessageSquare, color: "blue", trend: "+12%" },
             { label: "Taxa de Conversão", value: `${totals.taxa_conversao}%`, icon: Target, color: "emerald", trend: "+3.4%" },
             { label: "Leads Quentes", value: totals.leads_qualificados || 0, icon: Star, color: "amber", trend: "+5%" },
             { label: "Tempo Resposta", value: `${totals.tempo_medio_resposta}s`, icon: Clock, color: "primary", trend: "-1.2s" },
           ].map((kpi, i) => (
             <motion.div
               key={kpi.label}
               initial={{ opacity: 0, y: 20 }}
               animate={{ opacity: 1, y: 0 }}
               transition={{ delay: i * 0.1 }}
               className="glass rounded-[2rem] p-8 relative overflow-hidden group"
             >
                <div className="absolute top-0 right-0 p-8 opacity-5 group-hover:opacity-10 transition-opacity">
                  <kpi.icon className="w-20 h-20" />
                </div>
                <div className="flex items-center justify-between mb-4">
                  <div className={`p-4 rounded-2xl bg-${kpi.color === 'primary' ? 'primary' : kpi.color + '-500'}/10 border border-${kpi.color === 'primary' ? 'primary' : kpi.color + '-500'}/20`}>
                    <kpi.icon className={`w-6 h-6 text-${kpi.color === 'primary' ? 'primary' : kpi.color + '-400'}`} />
                  </div>
                  <span className="text-[10px] font-black text-emerald-400 bg-emerald-400/10 px-3 py-1 rounded-full">{kpi.trend}</span>
                </div>
                <p className="text-gray-500 text-[10px] font-black uppercase tracking-widest mb-1">{kpi.label}</p>
                <h3 className="text-3xl font-black">{kpi.value}</h3>
             </motion.div>
           ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10">
          
          {/* Main Chart Section - Unit Breakdown */}
          <div className="lg:col-span-8 space-y-10">
             <div className="glass rounded-[2.5rem] p-10">
                <div className="flex items-center justify-between mb-10">
                  <div>
                    <h2 className="text-2xl font-black flex items-center gap-3">
                      <Building2 className="w-7 h-7 text-primary" /> Performance por Unidade
                    </h2>
                    <p className="text-sm text-gray-500 mt-1">Comparativo de volume e qualidade dos leads.</p>
                  </div>
                  <PieChart className="w-6 h-6 text-gray-700" />
                </div>

                <div className="space-y-8">
                  {porUnidade.map((u: any, i: number) => {
                    const maxConv = Math.max(...porUnidade.map((item: any) => item.total_conversas || 1));
                    const width = `${((u.total_conversas || 0) / maxConv) * 100}%`;
                    const convRate = u.total_conversas > 0 ? Math.round((u.leads_qualificados / u.total_conversas) * 100) : 0;

                    return (
                      <div key={u.id} className="group">
                        <div className="flex items-center justify-between mb-3 px-2">
                           <div className="flex items-center gap-3">
                              <div className="w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center text-[10px] font-black text-gray-500 group-hover:bg-primary/20 group-hover:text-primary transition-all">
                                0{i+1}
                              </div>
                              <span className="font-bold text-sm tracking-tight">{u.nome}</span>
                           </div>
                           <div className="flex items-center gap-6">
                              <span className="text-[10px] font-black text-gray-500 uppercase">Rate: <span className="text-white">{convRate}%</span></span>
                              <span className="text-sm font-black">{u.total_conversas} <span className="text-[10px] text-gray-500 ml-1">leads</span></span>
                           </div>
                        </div>
                        <div className="h-3 bg-white/5 rounded-full overflow-hidden relative border border-white/[0.03]">
                           <motion.div 
                             initial={{ width: 0 }}
                             animate={{ width }}
                             transition={{ duration: 1.5, delay: 0.5 + i * 0.1, ease: "circOut" }}
                             className="h-full bg-gradient-to-r from-blue-600 to-primary rounded-full relative"
                           >
                             <div className="absolute inset-0 bg-white/20 opacity-0 group-hover:opacity-100 transition-opacity" />
                           </motion.div>
                        </div>
                      </div>
                    );
                  })}
                </div>
             </div>

             {/* AI & Monetization Section */}
             <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div className="glass rounded-[2rem] p-8 border-primary/10">
                   <div className="flex items-center gap-4 mb-8">
                      <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center">
                        <Cpu className="w-6 h-6 text-primary" />
                      </div>
                      <div>
                        <h4 className="font-black text-sm uppercase tracking-widest">Cérebro Neural Ativo</h4>
                        <p className="text-[10px] text-gray-500 font-bold uppercase">gpt-4o-mini (Optimized)</p>
                      </div>
                   </div>
                   <div className="space-y-4">
                      <div className="flex items-center justify-between text-[11px] font-bold">
                        <span className="text-gray-500 uppercase">Uptime Cognitivo</span>
                        <span className="text-emerald-400">99.98%</span>
                      </div>
                      <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                        <div className="w-[99%] h-full bg-emerald-500" />
                      </div>
                   </div>
                </div>

                <div className="glass rounded-[2rem] p-8 border-amber-500/10">
                   <div className="flex items-center gap-4 mb-8">
                      <div className="w-12 h-12 rounded-2xl bg-amber-500/10 flex items-center justify-center">
                        <DollarSign className="w-6 h-6 text-amber-500" />
                      </div>
                      <div>
                        <h4 className="font-black text-sm uppercase tracking-widest">Investimento IA</h4>
                        <p className="text-[10px] text-gray-500 font-bold uppercase">Estimativa USD (Moeda Base)</p>
                      </div>
                   </div>
                   <div className="flex items-baseline gap-2">
                      <span className="text-3xl font-black text-amber-400">$12.45</span>
                      <span className="text-[10px] text-gray-500 font-black uppercase">Acumulado Mes</span>
                   </div>
                </div>
             </div>
          </div>

          {/* Sidebar Section - Funnel & Quick Actions */}
          <div className="lg:col-span-4 space-y-10">
             <div className="glass rounded-[2.5rem] p-10 bg-primary/5 border-primary/20">
                <div className="flex items-center justify-between mb-10">
                    <h2 className="text-xl font-black uppercase tracking-widest">Funil de Conversão</h2>
                    <Activity className="w-5 h-5 text-primary animate-pulse" />
                </div>

                <div className="space-y-12 relative">
                   <div className="absolute left-[15px] top-6 bottom-6 w-[2px] bg-gradient-to-b from-primary/40 to-transparent" />
                   
                   {[
                     { label: "Oportunidades", desc: "Leads totais", val: totals.total_conversas || 0, color: "bg-blue-600" },
                     { label: "Qualificados", desc: "Interesse detectado", val: totals.leads_qualificados || 0, color: "bg-primary" },
                     { label: "Intenção Alta", desc: "Fase de fechamento", val: totals.intencao_compra || 0, color: "bg-emerald-500" },
                   ].map((step, i) => (
                     <div key={step.label} className="relative pl-12">
                        <div className={`absolute left-0 top-1 w-8 h-8 rounded-full ${step.color} shadow-lg shadow-black/40 flex items-center justify-center z-10 border-4 border-[#0d0d1a]`}>
                           <div className="w-2 h-2 rounded-full bg-white animate-pulse" />
                        </div>
                        <div>
                           <h5 className="font-black text-xs uppercase tracking-[0.2em]">{step.label}</h5>
                           <div className="flex items-baseline gap-2">
                             <span className="text-2xl font-black">{step.val}</span>
                             <span className="text-[10px] text-gray-500 font-medium italic">{step.desc}</span>
                           </div>
                        </div>
                     </div>
                   ))}
                </div>
             </div>

             <div className="glass rounded-[2.5rem] p-10">
                <h3 className="text-lg font-black uppercase tracking-widest mb-8">Exportar Inteligência</h3>
                <p className="text-xs text-gray-500 mb-8 leading-relaxed">
                  Baixe sua base de leads qualificados para alimentar CRM externo ou auditoria de fechamento.
                </p>
                <button className="w-full bg-white text-black py-5 rounded-[2rem] font-black uppercase tracking-widest text-xs flex items-center justify-center gap-3 hover:scale-105 active:scale-95 transition-all shadow-xl">
                   Extrair Base (CSV)
                   <ArrowUpRight className="w-4 h-4" />
                </button>
             </div>
          </div>

        </div>
      </div>
    </div>
  );
}
