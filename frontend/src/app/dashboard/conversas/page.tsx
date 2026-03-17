"use client";

import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  MessageSquare, Search, ChevronLeft, ChevronRight,
  Building2, Star, Flame, Clock, X, RefreshCw,
  Download, Zap, Bot, BarChart3, Target, Brain
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

interface Conversation {
  id: number;
  conversation_id: string;
  contato_nome: string;
  contato_fone: string;
  contato_telefone: string;
  score_lead: number;
  lead_qualificado: boolean;
  intencao_de_compra: boolean;
  status: string;
  updated_at: string;
  created_at: string;
  total_mensagens_cliente: number;
  total_mensagens_ia: number;
  resumo_ia: string;
  canal: string;
  unidade_nome: string;
  pausada: boolean;
}

const statusColor: Record<string, string> = {
  open: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20",
  resolved: "bg-[#00d2ff]/10 text-[#00d2ff] border border-[#00d2ff]/20",
  closed: "bg-slate-700/20 text-slate-500 border border-slate-700/20",
  encerrada: "bg-slate-500/15 text-slate-400 border border-slate-500/20",
  pending: "bg-amber-500/15 text-amber-400 border border-amber-500/20",
};
const statusLabel: Record<string, string> = {
  open: "Aberta", resolved: "Atendido", closed: "Fechada", encerrada: "Encerrada", pending: "Pendente"
};

export default function ConversasPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [summarizing, setSummarizing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [unidades, setUnidades] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const limit = 20;
  const [busca, setBusca] = useState("");
  const [buscaInput, setBuscaInput] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterUnidade, setFilterUnidade] = useState<number | "">("");
  const [selected, setSelected] = useState<Conversation | null>(null);

  const token = typeof window !== "undefined" ? localStorage.getItem("token") : "";
  const config = { headers: { Authorization: `Bearer ${token}` } };

  const fetchConversations = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.append("limit", limit.toString());
      params.append("offset", offset.toString());
      if (filterUnidade) params.append("unidade_id", filterUnidade.toString());
      if (filterStatus) params.append("status", filterStatus);
      if (busca) params.append("busca", busca);
      const res = await axios.get(`/api-backend/dashboard/conversations?${params}`, config);
      setConversations(res.data.data || []);
      setTotal(res.data.total || 0);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [offset, filterUnidade, filterStatus, busca]);

  useEffect(() => {
    axios.get("/api-backend/dashboard/unidades", config).then(r => setUnidades(r.data)).catch(() => {});
  }, []);

  useEffect(() => { fetchConversations(); }, [fetchConversations]);

  const handleSearch = (e: React.FormEvent) => { e.preventDefault(); setBusca(buscaInput); setOffset(0); };
  const clearFilters = () => { setBusca(""); setBuscaInput(""); setFilterStatus(""); setFilterUnidade(""); setOffset(0); };

  const exportLeads = async () => {
    setExporting(true);
    try {
      const params = new URLSearchParams();
      if (filterUnidade) params.append("unidade_id", filterUnidade.toString());
      if (filterStatus) params.append("status", filterStatus);
      const res = await axios.get(`/api-backend/management/export-leads?${params}`, config);
      const allLeads = res.data || [];
      const headers = ["Nome", "Telefone", "Score", "Qualificado", "Intencao", "Status", "Unidade", "Msgs Cliente", "IA", "Data"];
      const rows = allLeads.map((c: any) => [
        c.contato_nome || "Anônimo", c.contato_fone || c.contato_telefone || "",
        c.score_lead || 0, c.lead_qualificado ? "Sim" : "Não", c.intencao_de_compra ? "Sim" : "Não",
        c.status, c.unidade_nome || "", c.total_mensagens_cliente || 0, c.total_mensagens_ia || 0,
        c.created_at ? new Date(c.created_at).toLocaleString() : ""
      ]);
      const csv = [headers, ...rows].map(e => e.map((v: any) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
      const blob = new Blob([new Uint8Array([0xEF, 0xBB, 0xBF]), csv], { type: "text/csv;charset=utf-8;" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `leads_${new Date().toISOString().split("T")[0]}.csv`;
      document.body.appendChild(link); link.click(); document.body.removeChild(link);
    } catch (err) { console.error(err); }
    finally { setExporting(false); }
  };
  
  const handleGenerateSummary = async () => {
    if (!selected) return;
    setSummarizing(true);
    try {
      const res = await axios.post(`/api-backend/dashboard/conversations/${selected.conversation_id}/resumo`, {}, config);
      if (res.data.status === "success") {
        const newSummary = res.data.resumo_ia;
        setSelected({ ...selected, resumo_ia: newSummary });
        setConversations(conversations.map(c => c.conversation_id === selected.conversation_id ? { ...c, resumo_ia: newSummary } : c));
      }
    } catch (err) {
      console.error("Erro ao gerar resumo:", err);
    } finally {
      setSummarizing(false);
    }
  };

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="conversas" />
      <main className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="flex-shrink-0 bg-slate-950/80 border-b border-white/5 px-8 py-5 flex items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <MessageSquare className="w-5 h-5 text-[#00d2ff]" />
              <h1 className="text-xl font-black" style={{ background: "linear-gradient(135deg,#fff 0%,#00d2ff 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                Central de Inteligência
              </h1>
            </div>
            <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">{total} conversas mapeadas</p>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={exportLeads} disabled={exporting}
              className="hidden sm:flex items-center gap-2 bg-white/5 hover:bg-[#00d2ff]/10 border border-white/8 px-4 py-2.5 rounded-xl text-xs font-black uppercase tracking-widest transition-all text-slate-400 hover:text-[#00d2ff] hover:border-[#00d2ff]/20 disabled:opacity-50">
              <Download className="w-4 h-4" /> {exporting ? "Exportando..." : "Exportar Leads"}
            </button>
            <button onClick={() => fetchConversations()} className="p-2.5 bg-white/5 hover:bg-[#00d2ff]/10 rounded-xl border border-white/8 transition-all">
              <RefreshCw className={`w-4 h-4 text-[#00d2ff] ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </header>

        <div className="flex-1 flex overflow-hidden">
          {/* List Panel */}
          <div className={`flex flex-col bg-slate-900/20 border-r border-white/5 ${selected ? "hidden lg:flex lg:w-[380px]" : "w-full"}`}>
            {/* Filters */}
            <div className="p-5 space-y-3 bg-slate-950/30 border-b border-white/5">
              <form onSubmit={handleSearch} className="relative">
                <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                <input value={buscaInput} onChange={e => setBuscaInput(e.target.value)} placeholder="Buscar por nome ou fone..."
                  className="w-full bg-slate-900/60 border border-white/8 rounded-2xl pl-11 pr-4 py-3.5 text-sm focus:outline-none focus:border-[#00d2ff]/40 transition-all" />
              </form>
              <div className="flex gap-2 flex-wrap">
                <select value={filterUnidade} onChange={e => { setFilterUnidade(e.target.value ? Number(e.target.value) : ""); setOffset(0); }}
                  className="bg-slate-900/60 border border-white/8 rounded-xl px-3 py-2.5 text-[11px] font-black uppercase text-slate-500 focus:outline-none cursor-pointer flex-1">
                  <option value="">Todas Unidades</option>
                  {unidades.map(u => <option key={u.id} value={u.id}>{u.nome}</option>)}
                </select>
                <select value={filterStatus} onChange={e => { setFilterStatus(e.target.value); setOffset(0); }}
                  className="bg-slate-900/60 border border-white/8 rounded-xl px-3 py-2.5 text-[11px] font-black uppercase text-slate-500 focus:outline-none cursor-pointer flex-1">
                  <option value="">Todos Status</option>
                  <option value="open">Abertas</option>
                  <option value="resolved">Atendidas</option>
                  <option value="closed">Fechadas</option>
                </select>
                {(busca || filterStatus || filterUnidade) && (
                  <button onClick={clearFilters} className="bg-red-500/10 text-red-400 border border-red-500/20 rounded-xl px-3 py-2 text-[10px] font-black transition-all hover:bg-red-500/20">
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>

            {/* List */}
            <div className="flex-1 overflow-y-auto custom-scrollbar">
              {loading ? (
                [...Array(6)].map((_, i) => (
                  <div key={i} className="px-5 py-5 border-b border-white/[0.03] animate-pulse">
                    <div className="flex items-center gap-4">
                      <div className="w-11 h-11 bg-white/5 rounded-2xl" />
                      <div className="flex-1 space-y-2">
                        <div className="h-3 bg-white/5 rounded w-1/2" />
                        <div className="h-2 bg-white/5 rounded w-1/3" />
                      </div>
                    </div>
                  </div>
                ))
              ) : conversations.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-20 text-center px-6">
                  <MessageSquare className="w-12 h-12 text-slate-700 mb-4" />
                  <p className="font-black text-slate-400 uppercase tracking-widest text-sm">Nenhum resultado</p>
                </div>
              ) : (
                conversations.map(conv => (
                  <button key={conv.id} onClick={() => setSelected(conv)}
                    className={`w-full text-left px-5 py-5 border-b border-white/[0.03] transition-all relative group ${selected?.id === conv.id ? "bg-[#00d2ff]/5" : "hover:bg-white/[0.02]"}`}>
                    {selected?.id === conv.id && <div className="absolute left-0 top-4 bottom-4 w-0.5 bg-[#00d2ff] rounded-r-full shadow-[0_0_8px_rgba(0,210,255,0.6)]" />}
                    <div className="flex items-start gap-4">
                      <div className="w-11 h-11 rounded-2xl bg-slate-900/60 border border-white/5 flex items-center justify-center text-base font-black flex-shrink-0 group-hover:border-[#00d2ff]/20 transition-colors">
                        {conv.contato_nome?.charAt(0) || "?"}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2 mb-1.5">
                          <p className="text-sm font-black truncate group-hover:text-[#00d2ff] transition-colors">{conv.contato_nome || "Anônimo"}</p>
                          <span className={`text-[9px] font-black px-2.5 py-1 rounded-full uppercase tracking-wider flex-shrink-0 ${statusColor[conv.status] || "bg-slate-700/20 text-slate-500"}`}>
                            {statusLabel[conv.status] || conv.status}
                          </span>
                        </div>
                        <p className="text-xs text-slate-500 font-medium mb-2">{conv.contato_fone || conv.contato_telefone}</p>
                        <div className="flex items-center gap-3">
                          <div className="flex gap-1">
                            {[1, 2, 3, 4, 5].map(s => (
                              <div key={s} className={`w-1.5 h-1.5 rounded-full ${s <= (conv.score_lead || 0) ? "bg-[#00d2ff] shadow-[0_0_4px_rgba(0,210,255,0.5)]" : "bg-white/10"}`} />
                            ))}
                          </div>
                          {conv.pausada && (
                            <span className="text-[9px] font-black text-amber-400 flex items-center gap-1 bg-amber-400/10 px-2 py-0.5 rounded-full border border-amber-400/20">
                              <Bot className="w-2.5 h-2.5" /> IA Pausada
                            </span>
                          )}
                          {conv.intencao_de_compra && (
                            <span className="text-[9px] font-black text-rose-400 flex items-center gap-1 bg-rose-400/10 px-2 py-0.5 rounded-full">
                              <Flame className="w-2.5 h-2.5" /> Quente
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </button>
                ))
              )}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="p-4 border-t border-white/5 bg-slate-950/40 flex items-center justify-between">
                <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Pág. {currentPage}/{totalPages}</span>
                <div className="flex gap-2">
                  <button onClick={() => setOffset(Math.max(0, offset - limit))} disabled={offset === 0}
                    className="p-2.5 bg-white/5 rounded-xl border border-white/5 hover:bg-white/10 disabled:opacity-20 transition-all">
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <button onClick={() => setOffset(offset + limit)} disabled={currentPage >= totalPages}
                    className="p-2.5 bg-white/5 rounded-xl border border-white/5 hover:bg-white/10 disabled:opacity-20 transition-all">
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Detail Panel */}
          <AnimatePresence>
            {selected ? (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                className="flex-1 flex flex-col overflow-hidden bg-[#020617]/40 border-l border-white/5">
                <div className="p-8 border-b border-white/5">
                  <div className="flex items-center justify-between mb-6 lg:hidden">
                    <button onClick={() => setSelected(null)} className="p-2.5 bg-white/5 rounded-xl border border-white/5 hover:bg-[#00d2ff]/10 transition-all">
                      <ChevronLeft className="w-5 h-5" />
                    </button>
                  </div>
                  <div className="flex items-center gap-6">
                    <div className="w-20 h-20 rounded-[2rem] bg-gradient-to-br from-blue-600/20 to-[#00d2ff]/20 border-2 border-[#00d2ff]/20 flex items-center justify-center text-4xl font-black text-[#00d2ff] relative flex-shrink-0">
                      {selected.contato_nome?.charAt(0) || "?"}
                      <div className="absolute -bottom-2 -right-2 p-2.5 bg-[#00d2ff] text-black rounded-xl shadow-lg">
                        <Zap className="w-4 h-4" />
                      </div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-2 flex-wrap">
                        <h2 className="text-2xl font-black truncate">{selected.contato_nome || "Anônimo"}</h2>
                        <span className={`text-[10px] font-black px-3 py-1.5 rounded-full uppercase tracking-widest ${statusColor[selected.status] || "bg-slate-700/20 text-slate-500"}`}>
                          {statusLabel[selected.status] || selected.status}
                        </span>
                      </div>
                      <p className="text-slate-500 font-bold flex items-center gap-2 text-sm">
                        <Clock className="w-4 h-4 text-[#00d2ff]/40" />
                        {selected.contato_fone || selected.contato_telefone}
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-3">
                      <button 
                        onClick={async () => {
                          try {
                            const res = await axios.post(`/api-backend/dashboard/conversations/${selected.conversation_id}/toggle-ia`, {}, config);
                            const newStatus = res.data.pausada;
                            setSelected({ ...selected, pausada: newStatus });
                            setConversations(conversations.map(c => c.conversation_id === selected.conversation_id ? { ...c, pausada: newStatus } : c));
                          } catch (err) { console.error(err); }
                        }}
                        className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all border ${
                          selected.pausada 
                            ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20" 
                            : "bg-amber-500/10 text-amber-400 border-amber-500/20 hover:bg-amber-500/20"
                        }`}
                      >
                        {selected.pausada ? (
                          <><Zap className="w-4 h-4" /> Ativar IA</>
                        ) : (
                          <><X className="w-4 h-4" /> Pausar IA</>
                        )}
                      </button>
                      {selected.pausada && (
                        <span className="text-[10px] font-black text-amber-500 bg-amber-500/10 px-3 py-1 rounded-full border border-amber-500/15 animate-pulse">
                          AUTOMAÇÃO DESATIVADA
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto p-8 space-y-8 custom-scrollbar">
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    {[
                      { label: "Lead Score", value: `${selected.score_lead || 0}/5`, icon: Star },
                      { label: "Intenção", value: selected.intencao_de_compra ? "ALTA 🔥" : "MÉDIA", icon: Flame },
                      { label: "Mensagens", value: (selected.total_mensagens_cliente || 0) + (selected.total_mensagens_ia || 0), icon: MessageSquare },
                      { label: "Fase Funil", value: selected.status === "open" ? "NEGOCIAÇÃO" : "FINALIZADO", icon: Target },
                    ].map(stat => (
                      <div key={stat.label} className="bg-slate-900/50 border border-white/5 rounded-2xl p-5 hover:border-[#00d2ff]/15 transition-all">
                        <div className="flex items-center gap-2 mb-3">
                          <stat.icon className="w-4 h-4 text-[#00d2ff]/50" />
                          <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">{stat.label}</span>
                        </div>
                        <p className="text-xl font-black">{stat.value}</p>
                      </div>
                    ))}
                  </div>

                  <div className="bg-slate-900/50 border border-white/5 rounded-2xl p-7 hover:border-[#00d2ff]/15 transition-all">
                    <div className="flex items-center justify-between mb-5">
                      <div className="flex items-center gap-3">
                        <Brain className="w-5 h-5 text-[#00d2ff]" />
                        <h3 className="text-lg font-black uppercase tracking-widest">Resumo Neural</h3>
                      </div>
                      <button 
                        onClick={handleGenerateSummary}
                        disabled={summarizing}
                        className="flex items-center gap-2 px-3 py-1.5 bg-[#00d2ff]/10 hover:bg-[#00d2ff]/20 border border-[#00d2ff]/20 rounded-lg text-[10px] font-black uppercase tracking-tighter transition-all disabled:opacity-50"
                      >
                        {summarizing ? (
                          <><RefreshCw className="w-3 h-3 animate-spin" /> Gerando...</>
                        ) : (
                          <><Zap className="w-3 h-3" /> Gerar Resumo</>
                        )}
                      </button>
                    </div>
                    <p className="text-slate-400 leading-relaxed italic">
                      "{selected.resumo_ia || "Nenhuma análise disponível para este lead."}"
                    </p>
                  </div>

                  <div className="bg-slate-900/50 border border-white/5 rounded-2xl p-7 space-y-4">
                    <h4 className="text-[11px] font-black text-slate-500 uppercase tracking-widest mb-2">Informações de Tráfego</h4>
                    {[
                      { label: "Unidade de Origem", value: selected.unidade_nome, icon: Building2 },
                      { label: "Canal de Entrada", value: selected.canal, icon: Zap },
                      { label: "Registrado em", value: selected.created_at ? new Date(selected.created_at).toLocaleString("pt-BR") : "—", icon: Clock },
                    ].map(row => (
                      <div key={row.label} className="flex justify-between items-center py-3 border-b border-white/5 last:border-0 last:pb-0">
                        <span className="text-sm font-bold text-slate-500 flex items-center gap-2.5">
                          <row.icon className="w-4 h-4 text-[#00d2ff]/40" /> {row.label}
                        </span>
                        <span className="text-sm font-black">{row.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </motion.div>
            ) : (
              <div className="flex-1 hidden lg:flex flex-col items-center justify-center opacity-20 select-none">
                <Bot className="w-28 h-28 mb-6" />
                <p className="text-xl font-black uppercase tracking-[0.4em]">Neural Insight</p>
                <p className="text-sm italic mt-2 text-slate-400">Selecione uma interação para análise profunda</p>
              </div>
            )}
          </AnimatePresence>
        </div>
      </main>

      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar { width: 4px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0,210,255,0.1); border-radius: 10px; }
      `}</style>
    </div>
  );
}
