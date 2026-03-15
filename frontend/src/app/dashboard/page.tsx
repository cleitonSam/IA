"use client";

import { useEffect, useState } from "react";
import axios from "axios";
import {
  TrendingUp, Users, MessageSquare, Clock, Target, ArrowUpRight,
  ChevronRight, LayoutDashboard, Settings, LogOut, Bell,
  Building2, Brain, HelpCircle, Network, Zap, ChevronDown,
  Activity, Star, ArrowRight, Sparkles, MessageSquare as MsgIcon
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
          axios.get(`/api-backend/dashboard/metrics/empresa`, config)
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
          axios.get(`/api-backend/dashboard/metrics?unidade_id=${selectedUnidadeId}`, config),
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
      <div className="min-h-screen bg-[#080810] flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="relative w-16 h-16">
            <div className="absolute inset-0 rounded-full border-2 border-violet-500/20 animate-ping" />
            <div className="absolute inset-0 rounded-full border-2 border-t-violet-500 animate-spin" />
            <Sparkles className="absolute inset-0 m-auto w-6 h-6 text-violet-400" />
          </div>
          <p className="text-sm text-gray-500 font-medium tracking-widest uppercase">Carregando</p>
        </div>
      </div>
    );
  }

  if (!initialLoading && unidades.length === 0) {
    return (
      <div className="min-h-screen bg-[#080810] flex items-center justify-center p-4">
        <div className="bg-white/5 border border-white/10 rounded-3xl p-12 text-center max-w-md w-full backdrop-blur-xl">
          <div className="w-16 h-16 bg-violet-500/10 border border-violet-500/20 rounded-2xl flex items-center justify-center mx-auto mb-6">
            <Building2 className="w-8 h-8 text-violet-400" />
          </div>
          <h2 className="text-2xl font-bold text-white mb-3">Nenhuma unidade ativa</h2>
          <p className="text-gray-400 mb-8 text-sm leading-relaxed">
            Configure sua primeira unidade para começar a ver dados no painel.
          </p>
          <a href="/dashboard/settings"
            className="inline-flex items-center gap-2 bg-violet-600 hover:bg-violet-500 text-white font-bold py-3 px-6 rounded-xl transition-all">
            <Settings className="w-4 h-4" /> Configurar Agora
          </a>
        </div>
      </div>
    );
  }

  const navItems = [
    { label: "Visão Geral", icon: LayoutDashboard, href: "/dashboard", active: true },
    { label: "Conversas", icon: MsgIcon, href: "/dashboard/conversas" },
    { label: "Unidades", icon: Building2, href: "/dashboard/settings" },
    { label: "Personalidade IA", icon: Brain, href: "/dashboard/settings" },
    { label: "FAQ", icon: HelpCircle, href: "/dashboard/settings" },
    { label: "Integrações", icon: Network, href: "/dashboard/settings" },
  ];

  return (
    <div className="min-h-screen bg-[#080810] text-white flex overflow-hidden">
      {/* ── Sidebar ── */}
      <aside className={`
        fixed lg:relative inset-y-0 left-0 z-40 w-64 flex flex-col
        bg-[#0d0d1a] border-r border-white/5
        transform transition-transform duration-300 ease-in-out
        ${sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}
      `}>
        {/* Logo */}
        <div className="px-6 py-6 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-violet-500/30">
              <Zap className="w-5 h-5 text-white" />
            </div>
            <div>
              <p className="font-bold text-sm tracking-tight">Antigravity IA</p>
              <p className="text-[10px] text-gray-500 uppercase tracking-widest">Dashboard</p>
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
                  ? "bg-violet-600/15 text-violet-300 border border-violet-500/20"
                  : "text-gray-400 hover:text-white hover:bg-white/5"
              }`}>
              <item.icon className={`w-4 h-4 flex-shrink-0 ${item.active ? "text-violet-400" : "group-hover:text-white"}`} />
              {item.label}
              {item.active && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-violet-400" />}
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
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-xs font-bold flex-shrink-0">
              {user?.nome?.charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold truncate">{user?.nome}</p>
              <p className="text-[10px] text-violet-400 font-medium truncate">{user?.perfil === 'admin_master' ? 'Gestor Master' : user?.perfil}</p>
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
        <div className="fixed inset-0 z-30 bg-black/60 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* ── Main ── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Bar */}
        <header className="sticky top-0 z-20 bg-[#080810]/80 backdrop-blur-xl border-b border-white/5 px-6 py-3.5 flex items-center justify-between gap-4">
          <button onClick={() => setSidebarOpen(true)} className="lg:hidden p-2 rounded-lg hover:bg-white/5">
            <LayoutDashboard className="w-5 h-5" />
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
                  className="absolute top-full mt-2 left-0 w-64 bg-[#0d0d1a] border border-white/10 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden z-50">
                  <div className="p-2">
                    {unidades.map((u) => (
                      <button key={u.id}
                        onClick={() => { setSelectedUnidadeId(u.id); setUnitDropdownOpen(false); }}
                        className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-left transition-all ${
                          u.id === selectedUnidadeId ? "bg-violet-600/20 text-violet-300" : "hover:bg-white/5 text-gray-300"
                        }`}>
                        <Building2 className="w-4 h-4 flex-shrink-0" />
                        {u.nome}
                      </button>
                    ))}
                  </div>
                  <div className="px-3 pb-2">
                    <a href="/dashboard/settings"
                      className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs text-violet-400 hover:bg-violet-600/10 transition-all w-full">
                      <Settings className="w-3 h-3" /> Gerenciar unidades
                    </a>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          <div className="flex items-center gap-3 ml-auto">
            <a href="/dashboard/settings"
              className="hidden sm:flex items-center gap-2 bg-violet-600 hover:bg-violet-500 text-white text-sm font-bold px-4 py-2 rounded-xl transition-all">
              <Settings className="w-4 h-4" /> Central de Gestão
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

          {/* KPI Cards: company-wide + per-unit selected */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            {[
              { label: "Total Conversas", value: (empresaMetrics?.total_conversas ?? metrics?.total_conversas) ?? "—", icon: MsgIcon, color: "violet", delta: undefined },
              { label: "Leads Qualificados", value: (empresaMetrics?.leads_qualificados ?? metrics?.leads_qualificados) ?? "—", icon: Star, color: "indigo", delta: undefined },
              { label: "Taxa de Conversão", value: empresaMetrics?.taxa_conversao != null ? `${empresaMetrics.taxa_conversao}%` : (metrics?.taxa_conversao ? `${metrics.taxa_conversao}%` : "—"), icon: TrendingUp, color: "emerald", delta: undefined },
              { label: "Tempo Médio", value: (empresaMetrics?.tempo_medio_resposta ?? metrics?.tempo_medio_resposta) ? `${Math.round(empresaMetrics?.tempo_medio_resposta ?? metrics?.tempo_medio_resposta)}s` : "—", icon: Clock, color: "amber", delta: undefined },
            ].map((card, i) => (
              <motion.div
                key={card.label}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.07 }}
                className="bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] hover:border-white/10 rounded-2xl p-5 transition-all group">
                <div className="flex items-start justify-between mb-4">
                  <div className={`p-2 rounded-lg bg-${card.color}-500/10`}>
                    <card.icon className={`w-4 h-4 text-${card.color}-400`} />
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
            <div className="lg:col-span-3 bg-white/[0.03] border border-white/[0.06] rounded-2xl p-6">
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
                  { label: "Contatos Totais", count: metrics?.total_conversas || 0, total: metrics?.total_conversas || 1, color: "violet" },
                  { label: "Interesse Detectado", count: metrics?.leads_qualificados || 0, total: metrics?.total_conversas || 1, color: "indigo" },
                  { label: "Link de Venda Enviado", count: metrics?.total_links_enviados || 0, total: metrics?.total_conversas || 1, color: "blue" },
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
                          className={`h-full rounded-full bg-${step.color}-500 shadow-[0_0_8px_rgba(139,92,246,0.5)]`}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Leads Quentes */}
            <div className="lg:col-span-2 bg-white/[0.03] border border-white/[0.06] rounded-2xl p-6 flex flex-col">
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
                      className="flex items-center gap-3 p-3 rounded-xl hover:bg-white/5 transition-all group cursor-pointer border border-transparent hover:border-white/5">
                      <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-600/30 to-indigo-600/30 border border-white/10 flex items-center justify-center text-sm font-bold flex-shrink-0">
                        {conv.contato_nome?.charAt(0) || "?"}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-bold truncate">{conv.contato_nome || "Anônimo"}</p>
                        <p className="text-xs text-gray-500 truncate">{conv.contato_fone}</p>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <div className="flex items-center gap-1 mb-1 justify-end">
                          {[1,2,3,4,5].map(s => (
                            <div key={s} className={`w-1.5 h-1.5 rounded-full ${s <= (conv.score_lead || 0) ? "bg-violet-400" : "bg-white/10"}`} />
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
              <button className="mt-4 w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-white/5 hover:bg-white/5 text-xs font-bold text-gray-500 hover:text-white transition-all" onClick={() => { window.location.href = "/dashboard/conversas"; }}>
                Ver todas as conversas <ArrowRight className="w-3 h-3" />
              </button>
            </div>
          </div>

          {/* Quick Access */}
          <div className="mt-6">
            <p className="text-xs font-bold text-gray-600 uppercase tracking-widest mb-3">Acesso Rápido</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { label: "Conversas", icon: MsgIcon, href: "/dashboard/conversas", desc: "Central de leads" },
                { label: "Unidades", icon: Building2, href: "/dashboard/settings", desc: "Gerenciar filiais" },
                { label: "Personalidade IA", icon: Brain, href: "/dashboard/settings", desc: "Configurar IA" },
                { label: "Integrações", icon: Network, href: "/dashboard/settings", desc: "Chatwoot, EVO..." },
              ].map(item => (
                <a key={item.label} href={item.href}
                  className="bg-white/[0.03] hover:bg-white/[0.07] border border-white/[0.06] hover:border-violet-500/20 rounded-2xl p-4 transition-all group">
                  <item.icon className="w-5 h-5 text-gray-500 group-hover:text-violet-400 mb-3 transition-colors" />
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
