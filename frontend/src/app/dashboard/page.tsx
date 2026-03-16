"use client";

import { useEffect, useState } from "react";
import axios from "axios";
import {
  TrendingUp, Users, MessageSquare, Clock, Target, ArrowUpRight,
  ChevronRight, LayoutDashboard, Settings, LogOut, Bell,
  Building2, Brain, HelpCircle, Network, Zap, ChevronDown,
  Activity, Star, ArrowRight, Sparkles, MessageSquare as MsgIcon,
  BarChart3
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<any>(null);
  const [empresaMetrics, setEmpresaMetrics] = useState<any>(null);
  const [perUnit, setPerUnit] = useState<any[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [initialLoading, setInitialLoading] = useState(true);
  const [user, setUser] = useState<any>(null);
  const [unidades, setUnidades] = useState<any[]>([]);
  const [selectedUnidadeId, setSelectedUnidadeId] = useState<number | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [unitDropdownOpen, setUnitDropdownOpen] = useState(false);

  const selectedUnit = unidades.find(u => u.id === selectedUnidadeId);

  useEffect(() => {
    const fetchInitial = async () => {
      const token = localStorage.getItem("token");
      if (!token) { window.location.href = "/login"; return; }
      try {
        const config = { headers: { Authorization: `Bearer ${token}` } };
        const [userRes, unitsRes, empMetRes] = await Promise.all([
          axios.get(`/api-backend/auth/me`, config),
          axios.get(`/api-backend/dashboard/unidades`, config),
          axios.get(`/api-backend/dashboard/metrics/empresa?days=30`, config)
        ]);
        setUser(userRes.data);
        setUnidades(unitsRes.data);
        setEmpresaMetrics(empMetRes.data?.totals || null);
        setPerUnit(empMetRes.data?.por_unidade || []);
        if (unitsRes.data.length > 0) setSelectedUnidadeId(unitsRes.data[0].id);
      } catch (err) {
        console.error(err);
      } finally {
        setInitialLoading(false);
      }
    };
    fetchInitial();
  }, []);

  useEffect(() => {
    if (!selectedUnidadeId) return;
    const fetchData = async () => {
      setLoading(true);
      const token = localStorage.getItem("token");
      try {
        const config = { headers: { Authorization: `Bearer ${token}` } };
        const [metricsRes, convRes] = await Promise.all([
          axios.get(`/api-backend/dashboard/metrics?unidade_id=${selectedUnidadeId}&days=30`, config),
          axios.get(`/api-backend/dashboard/conversations?unidade_id=${selectedUnidadeId}&limit=5`, config)
        ]);
        setMetrics(metricsRes.data.metrics);
        setConversations(convRes.data?.data || convRes.data || []);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [selectedUnidadeId]);

  if (initialLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="relative w-16 h-16">
            <div className="absolute inset-0 rounded-full border-2 border-primary/20 animate-ping" />
            <div className="absolute inset-0 rounded-full border-2 border-t-primary animate-spin" />
            <Sparkles className="absolute inset-0 m-auto w-6 h-6 text-primary" />
          </div>
          <p className="text-sm text-gray-500 font-medium tracking-widest uppercase">Fluxo Digital & Tech</p>
        </div>
      </div>
    );
  }

  if (!initialLoading && unidades.length === 0) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-4">
        <div className="bg-white/5 border border-white/10 rounded-3xl p-12 text-center max-w-md w-full backdrop-blur-xl">
          <div className="w-16 h-16 bg-primary/10 border border-primary/20 rounded-2xl flex items-center justify-center mx-auto mb-6">
            <Building2 className="w-8 h-8 text-primary" />
          </div>
          <h2 className="text-2xl font-bold text-white mb-3">Nenhuma unidade ativa</h2>
          <p className="text-gray-400 mb-8 text-sm leading-relaxed">
            Configure sua primeira unidade no Fluxo Digital & Tech para começar.
          </p>
          <a href="/dashboard/units"
            className="inline-flex items-center gap-2 bg-primary hover:bg-primary/90 text-black font-bold py-3 px-6 rounded-xl transition-all">
            <Settings className="w-4 h-4" /> Configurar Agora
          </a>
        </div>
      </div>
    );
  }

  const navItems = [
    { label: "Visão Geral", icon: LayoutDashboard, href: "/dashboard", active: true },
    { label: "Insights IA", icon: BarChart3, href: "/dashboard/insights" },
    { label: "Conversas", icon: MsgIcon, href: "/dashboard/conversas" },
    { label: "Unidades", icon: Building2, href: "/dashboard/units" },
    { label: "Personalidade IA", icon: Brain, href: "/dashboard/personality" },
    { label: "FAQ Neural", icon: HelpCircle, href: "/dashboard/faq" },
    { label: "Integrações", icon: Network, href: "/dashboard/integrations" },
  ];

  return (
    <div className="min-h-screen bg-background text-white flex overflow-hidden">
      {/* ── Sidebar ── */}
      <aside className={`
        fixed lg:relative inset-y-0 left-0 z-40 w-64 flex flex-col
        bg-slate-950 border-r border-white/5
        transform transition-transform duration-300 ease-in-out
        ${sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}
      `}>
        {/* Logo */}
        <div className="px-6 py-8 border-b border-white/5">
          <div className="flex items-center gap-3 group cursor-pointer" onClick={() => window.location.href = "/dashboard"}>
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-secondary flex items-center justify-center shadow-lg shadow-primary/20 group-hover:scale-110 transition-transform">
              <Zap className="w-5 h-5 text-black font-black" />
            </div>
            <div>
              <p className="font-black text-lg leading-tight tracking-tighter">
                Fluxo <span className="font-light text-primary/80">Digital & Tech</span>
              </p>
              <p className="text-[10px] text-gray-500 uppercase tracking-[0.2em] font-bold">Elite Platform</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          <p className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-gray-600">Principal</p>
          {navItems.map((item) => (
            <a key={item.href} href={item.href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all group ${
                item.active
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-gray-400 hover:text-white hover:bg-white/5"
              }`}>
              <item.icon className={`w-4 h-4 flex-shrink-0 ${item.active ? "text-primary" : "group-hover:text-white"}`} />
              {item.label}
              {item.active && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-primary shadow-[0_0_8px_rgba(0,210,255,0.6)]" />}
            </a>
          ))}

          {user?.perfil === "admin_master" && (
            <>
              <p className="px-3 py-2 pt-4 text-[10px] font-bold uppercase tracking-widest text-gray-600">Admin</p>
              <a href="/admin"
                className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-gray-400 hover:text-white hover:bg-white/5 transition-all group">
                <Settings className="w-4 h-4 flex-shrink-0 group-hover:text-white" />
                Painel Master
              </a>
            </>
          )}
        </nav>

        {/* User Footer */}
        <div className="px-3 py-4 border-t border-white/5">
          <div className="flex items-center gap-3 px-3 py-2.5 rounded-xl mb-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-secondary flex items-center justify-center text-xs font-bold flex-shrink-0 text-black">
              {user?.nome?.charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold truncate">{user?.nome}</p>
              <p className="text-[10px] text-primary/80 font-medium truncate">{user?.perfil === 'admin_master' ? 'Gestor Master' : user?.perfil}</p>
            </div>
          </div>
          <button
            onClick={() => { localStorage.removeItem("token"); window.location.href = "/login"; }}
            className="flex items-center gap-2 w-full px-3 py-2 rounded-xl text-sm text-red-400 hover:bg-red-500/10 transition-all">
            <LogOut className="w-4 h-4" />
            Sair da conta
          </button>
        </div>
      </aside>

      {/* Backdrop (Mobile) */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-30 bg-background/60 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* ── Main ── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Bar */}
        <header className="sticky top-0 z-20 bg-background/80 backdrop-blur-xl border-b border-white/5 px-6 py-3.5 flex items-center justify-between gap-4">
          <button onClick={() => setSidebarOpen(true)} className="lg:hidden p-2 rounded-lg hover:bg-white/5">
            <LayoutDashboard className="w-5 h-5 text-primary" />
          </button>

          {/* Unit Selector */}
          <div className="relative">
            <button
              onClick={() => setUnitDropdownOpen(!unitDropdownOpen)}
              className="flex items-center gap-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl px-4 py-2 text-sm font-medium transition-all">
              <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse flex-shrink-0" />
              <span className="max-w-[200px] truncate">{selectedUnit?.nome || "Selecione"}</span>
              <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${unitDropdownOpen ? "rotate-180" : ""}`} />
            </button>
            <AnimatePresence>
              {unitDropdownOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -8, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -8, scale: 0.95 }}
                  className="absolute top-full mt-2 left-0 w-64 bg-slate-900 border border-white/10 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden z-50">
                  <div className="p-2">
                    {unidades.map((u) => (
                      <button key={u.id}
                        onClick={() => { setSelectedUnidadeId(u.id); setUnitDropdownOpen(false); }}
                        className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-left transition-all ${
                          u.id === selectedUnidadeId ? "bg-primary/20 text-primary" : "hover:bg-white/5 text-gray-300"
                        }`}>
                        <Building2 className="w-4 h-4 flex-shrink-0" />
                        {u.nome}
                      </button>
                    ))}
                  </div>
                  <div className="px-3 pb-2">
                    <a href="/dashboard/units"
                      className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs text-primary/70 hover:bg-primary/10 transition-all w-full">
                      <Settings className="w-3 h-3" /> Gerenciar unidades
                    </a>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          <div className="flex items-center gap-3 ml-auto">
            <a href="/dashboard/units"
              className="hidden sm:flex items-center gap-2 bg-primary hover:bg-primary/90 text-black text-sm font-bold px-4 py-2 rounded-xl transition-all shadow-lg shadow-primary/20">
              <Settings className="w-4 h-4" /> Configurações
            </a>
            <button className="relative p-2.5 rounded-xl bg-white/5 hover:bg-white/10 transition-all border border-white/5">
              <Bell className="w-4 h-4 text-gray-400" />
              <span className="absolute top-2 right-2 w-1.5 h-1.5 bg-rose-500 rounded-full" />
            </button>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
          {/* Page title */}
          <div className="mb-8">
            <h1 className="text-2xl font-bold mb-1">
              Olá, {user?.nome?.split(" ")[0]} 👋
            </h1>
            <p className="text-sm text-gray-500">
              {new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" })} · {selectedUnit?.nome}
            </p>
          </div>

          {/* KPI Cards — filtra pela unidade selecionada */}
          <div className="flex items-center gap-2 mb-3">
            <span className="text-[10px] font-bold text-gray-600 uppercase tracking-widest">Métricas dos últimos 30 dias</span>
            {selectedUnit && <span className="text-[10px] font-bold text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-full">{selectedUnit.nome}</span>}
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            {[
              { label: "Total Conversas", value: (metrics?.total_conversas ?? empresaMetrics?.total_conversas) ?? "—", icon: MsgIcon, color: "blue", delta: undefined },
              { label: "Leads Qualificados", value: (metrics?.leads_qualificados ?? empresaMetrics?.leads_qualificados) ?? "—", icon: Star, color: "sky", delta: undefined },
              { label: "Taxa de Conversão", value: metrics?.taxa_conversao != null ? `${metrics.taxa_conversao}%` : (empresaMetrics?.taxa_conversao != null ? `${empresaMetrics.taxa_conversao}%` : "—"), icon: TrendingUp, color: "emerald", delta: undefined },
              { label: "Tempo Médio", value: (metrics?.tempo_medio_resposta != null ? metrics.tempo_medio_resposta : empresaMetrics?.tempo_medio_resposta) != null ? `${Math.round(metrics?.tempo_medio_resposta ?? empresaMetrics?.tempo_medio_resposta)}s` : "—", icon: Clock, color: "amber", delta: undefined },
            ].map((card, i) => (
              <motion.div
                key={card.label}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.07 }}
                className="bg-slate-900/40 hover:bg-slate-800/40 border border-white/[0.06] hover:border-primary/20 rounded-2xl p-5 transition-all group">
                <div className="flex items-start justify-between mb-4">
                  <div className={`p-2 rounded-lg bg-primary/10`}>
                    <card.icon className={`w-4 h-4 text-primary`} />
                  </div>
                </div>
                <p className="text-xs text-gray-500 mb-1">{card.label}</p>
                <p className="text-2xl font-bold tracking-tight">{loading ? <span className="inline-block w-12 h-6 bg-white/5 rounded animate-pulse" /> : card.value}</p>
              </motion.div>
            ))}
          </div>

          {/* Main Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
            {/* Funil */}
            <div className="lg:col-span-3 bg-slate-900/40 border border-white/[0.06] rounded-2xl p-6">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="font-bold text-base">Funil de Vendas</h2>
                  <p className="text-xs text-gray-500 mt-0.5">Evolução dos leads em tempo real</p>
                </div>
                <div className="flex items-center gap-1.5 text-[10px] font-bold text-emerald-400 bg-emerald-400/10 px-2.5 py-1.5 rounded-full">
                  <Activity className="w-3 h-3" /> AO VIVO
                </div>
              </div>
              <div className="space-y-5">
                 {[
                  { label: "Contatos Totais", count: metrics?.total_conversas || 0, total: metrics?.total_conversas || 1, color: "blue" },
                  { label: "Interesse Detectado", count: metrics?.leads_qualificados || 0, total: metrics?.total_conversas || 1, color: "sky" },
                  { label: "Oportunidades", count: metrics?.intencao_compra || 0, total: metrics?.total_conversas || 1, color: "violet" },
                  { label: "Link de Venda Enviado", count: metrics?.total_links_enviados || 0, total: metrics?.total_conversas || 1, color: "cyan" },
                  { label: "Matrículas Finalizadas", count: metrics?.total_matriculas || 0, total: metrics?.total_conversas || 1, color: "emerald" },
                ].map((step, i) => {
                  const pct = Math.min(100, (step.count / step.total) * 100);
                  return (
                    <div key={step.label}>
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-sm font-medium text-gray-300">{step.label}</span>
                        <span className="text-xs font-bold text-gray-500">{step.count} · {Math.round(pct)}%</span>
                      </div>
                      <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                        <motion.div
                          initial={{ width: 0 }} animate={{ width: `${pct}%` }}
                          transition={{ duration: 1, delay: 0.2 + i * 0.1 }}
                          className={`h-full rounded-full bg-primary/80 shadow-[0_0_8px_rgba(0,210,255,0.5)]`}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Leads Quentes */}
            <div className="lg:col-span-2 bg-slate-900/40 border border-white/[0.06] rounded-2xl p-6 flex flex-col">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="font-bold text-base">Leads Recentes</h2>
                  <p className="text-xs text-gray-500 mt-0.5">Oportunidades em aberto</p>
                </div>
                <Users className="w-4 h-4 text-gray-600" />
              </div>
              <div className="flex-1 space-y-2">
                {conversations.length === 0 && !loading ? (
                  <div className="flex-1 flex flex-col items-center justify-center py-8 text-center">
                    <MessageSquare className="w-8 h-8 text-gray-700 mb-2" />
                    <p className="text-sm text-gray-600">Nenhum lead ainda</p>
                  </div>
                ) : (
                  conversations.map((conv: any, i) => (
                    <motion.div
                      key={conv.conversation_id || i}
                      initial={{ opacity: 0, x: 10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.05 }}
                      className="flex items-center gap-3 p-3 rounded-xl hover:bg-primary/5 transition-all group cursor-pointer border border-transparent hover:border-primary/10">
                      <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-primary/30 to-secondary/30 border border-white/10 flex items-center justify-center text-sm font-bold flex-shrink-0">
                        {conv.contato_nome?.charAt(0) || "?"}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-bold truncate group-hover:text-primary transition-colors">{conv.contato_nome || "Anônimo"}</p>
                        <p className="text-xs text-gray-500 truncate">{conv.contato_fone}</p>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <div className="flex items-center gap-1 mb-1 justify-end">
                          {[1,2,3,4,5].map(s => (
                            <div key={s} className={`w-1.5 h-1.5 rounded-full ${s <= (conv.score_lead || 0) ? "bg-primary" : "bg-white/10"}`} />
                          ))}
                        </div>
                        {conv.intencao_de_compra && (
                          <span className="text-[9px] font-bold bg-rose-500/20 text-rose-400 px-2 py-0.5 rounded-full uppercase">Quente</span>
                        )}
                      </div>
                    </motion.div>
                  ))
                )}
              </div>
              <button className="mt-4 w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-white/5 hover:bg-primary/5 text-xs font-bold text-gray-500 hover:text-primary transition-all" onClick={() => { window.location.href = "/dashboard/conversas"; }}>
                Ver todas as conversas <ArrowRight className="w-3 h-3" />
              </button>
            </div>
          </div>

          {/* Quick Access */}
          <div className="mt-6">
            <p className="text-xs font-bold text-gray-600 uppercase tracking-widest mb-3">Acesso Rápido</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { label: "Insights", icon: BarChart3, href: "/dashboard/insights", desc: "Análise de conversão" },
                { label: "Conversas", icon: MsgIcon, href: "/dashboard/conversas", desc: "Central de leads" },
                { label: "Unidades", icon: Building2, href: "/dashboard/units", desc: "Gerenciar filiais" },
                { label: "Personalidade", icon: Brain, href: "/dashboard/personality", desc: "Cérebro da IA" },
              ].map(item => (
                <a key={item.label} href={item.href}
                  className="bg-slate-900/40 hover:bg-slate-800/40 border border-white/[0.06] hover:border-primary/20 rounded-2xl p-4 transition-all group">
                  <item.icon className="w-5 h-5 text-gray-500 group-hover:text-primary mb-3 transition-colors" />
                  <p className="text-sm font-bold mb-0.5">{item.label}</p>
                  <p className="text-xs text-gray-600">{item.desc}</p>
                </a>
              ))}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
