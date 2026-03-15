"use client";

import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  MessageSquare, Search, Filter, ChevronLeft, ChevronRight,
  Building2, Star, Flame, Clock, User, X, ArrowLeft, RefreshCw,
  Download, FileSpreadsheet, Zap
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

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
}

export default function ConversasPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [unidades, setUnidades] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit] = useState(20);
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
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [offset, filterUnidade, filterStatus, busca]);

  useEffect(() => {
    const fetchUnidades = async () => {
      try {
        const res = await axios.get("/api-backend/dashboard/unidades", config);
        setUnidades(res.data);
      } catch { }
    };
    fetchUnidades();
  }, []);

  useEffect(() => { fetchConversations(); }, [fetchConversations]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setBusca(buscaInput);
    setOffset(0);
  };

  const clearFilters = () => {
    setBusca(""); setBuscaInput(""); setFilterStatus(""); setFilterUnidade(""); setOffset(0);
  };

  const exportLeads = () => {
    const headers = ["Nome", "Telefone", "Score", "Qualificado", "Intencao", "Status", "Unidade", "Mensagens Cliente", "IA", "Data"];
    const rows = conversations.map(c => [
      c.contato_nome || "Anônimo",
      c.contato_fone || c.contato_telefone || "",
      c.score_lead || 0,
      c.lead_qualificado ? "Sim" : "Não",
      c.intencao_de_compra ? "Sim" : "Não",
      c.status,
      c.unidade_nome || "",
      c.total_mensagens_cliente || 0,
      c.total_mensagens_ia || 0,
      c.created_at ? new Date(c.created_at).toLocaleDateString() : ""
    ]);

    const csvContent = [headers, ...rows].map(e => e.join(",")).join("\n");
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", `leads_fluxo_${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  const statusColor: Record<string, string> = {
    open: "bg-emerald-500/15 text-emerald-400",
    resolved: "bg-blue-500/15 text-blue-400",
    closed: "bg-gray-700/20 text-gray-500",
    encerrada: "bg-gray-500/15 text-gray-400",
    pending: "bg-amber-500/15 text-amber-400",
  };

  const statusLabel: Record<string, string> = {
    open: "Aberta", resolved: "Atendido", closed: "Fechada",
    encerrada: "Encerrada", pending: "Pendente"
  };

  return (
    <div className="min-h-screen bg-mesh text-white flex flex-col">
      {/* Normalized Header */}
      <header className="sticky top-0 z-30 bg-black/40 backdrop-blur-xl border-b border-white/5 px-6 py-4 flex items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <a href="/dashboard" className="p-2.5 bg-white/5 hover:bg-primary/10 rounded-xl transition-all border border-white/10 group">
            <ArrowLeft className="w-5 h-5 group-hover:text-primary transition-colors" />
          </a>
          <div>
            <h1 className="text-xl font-black flex items-center gap-3">
              <MessageSquare className="w-6 h-6 text-primary neon-glow" />
              <span className="text-gradient">Central de Inteligência</span>
            </h1>
            <p className="text-[10px] text-gray-500 font-bold uppercase tracking-widest">{total} conversas mapeadas</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button 
             onClick={exportLeads}
             className="hidden sm:flex items-center gap-2 bg-white/5 hover:bg-white/10 border border-white/10 px-4 py-2.5 rounded-xl text-xs font-black uppercase tracking-widest transition-all"
          >
            <Download className="w-4 h-4 text-primary" /> Exportar Leads
          </button>
          <button onClick={fetchConversations} className="p-2.5 bg-white/5 rounded-xl hover:bg-primary/10 transition-all border border-white/10">
            <RefreshCw className={`w-4 h-4 text-primary ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* List Panel */}
        <div className={`flex flex-col w-full bg-black/20 backdrop-blur-md ${selected ? "hidden lg:flex lg:w-2/5 xl:w-[400px]" : ""}`}>
          {/* Filters */}
          <div className="p-4 space-y-4 bg-white/[0.02] border-b border-white/5 shadow-2xl shadow-black/40">
            <form onSubmit={handleSearch} className="relative group">
               <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600 group-focus-within:text-primary transition-colors" />
               <input
                 value={buscaInput}
                 onChange={e => setBuscaInput(e.target.value)}
                 placeholder="Filtrar por nome ou fone..."
                 className="w-full bg-black/40 border border-white/10 rounded-2xl pl-12 pr-4 py-4 text-sm font-medium focus:outline-none focus:ring-1 focus:ring-primary/40 focus:border-primary/40 transition-all"
               />
            </form>
            <div className="flex gap-2 flex-wrap">
              <select
                value={filterUnidade}
                onChange={e => { setFilterUnidade(e.target.value ? Number(e.target.value) : ""); setOffset(0); }}
                className="bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-[10px] font-black uppercase tracking-widest text-gray-400 focus:outline-none focus:text-white transition-all cursor-pointer">
                <option value="">Unidade: Todas</option>
                {unidades.map(u => <option key={u.id} value={u.id}>{u.nome}</option>)}
              </select>
              <select
                value={filterStatus}
                onChange={e => { setFilterStatus(e.target.value); setOffset(0); }}
                className="bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-[10px] font-black uppercase tracking-widest text-gray-400 focus:outline-none focus:text-white transition-all cursor-pointer">
                <option value="">Status: Todos</option>
                <option value="open">Abertas</option>
                <option value="resolved">Atendidas</option>
                <option value="closed">Fechadas</option>
              </select>
              {(busca || filterStatus || filterUnidade) && (
                <button onClick={clearFilters} className="bg-rose-500/10 text-rose-400 border border-rose-500/20 rounded-xl px-3 py-2 text-[10px] font-black hover:bg-rose-500/20 transition-all">
                  Limpar
                </button>
              )}
            </div>
          </div>

          {/* List Content */}
          <div className="flex-1 overflow-y-auto custom-scrollbar">
            {loading ? (
              [...Array(6)].map((_, i) => (
                <div key={i} className="px-6 py-6 border-b border-white/[0.03] animate-pulse">
                   <div className="flex items-center gap-4">
                      <div className="w-12 h-12 bg-white/5 rounded-2xl" />
                      <div className="flex-1 space-y-3">
                         <div className="h-3 bg-white/5 rounded w-1/2" />
                         <div className="h-2 bg-white/5 rounded w-1/3" />
                      </div>
                   </div>
                </div>
              ))
            ) : conversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-24 px-6 text-center">
                 <div className="w-16 h-16 bg-white/5 rounded-3xl flex items-center justify-center mb-6">
                    <MessageSquare className="w-8 h-8 text-gray-700" />
                 </div>
                 <p className="text-lg font-black text-gray-400 uppercase tracking-widest">Vazio</p>
                 <p className="text-xs text-gray-600 mt-2 italic">Nenhum registro encontrado com estes filtros.</p>
              </div>
            ) : (
              conversations.map((conv) => (
                <button
                  key={conv.id}
                  onClick={() => setSelected(conv)}
                  className={`w-full text-left px-6 py-6 border-b border-white/[0.03] transition-all relative group ${selected?.id === conv.id ? "bg-primary/5 shadow-inner" : "hover:bg-white/[0.02]"}`}>
                  
                  {selected?.id === conv.id && <div className="absolute left-0 top-6 bottom-6 w-1 bg-primary rounded-r-full shadow-[0_0_10px_rgba(0,242,255,0.8)]" />}
                  
                  <div className="flex items-start gap-4">
                    <div className="w-14 h-14 rounded-3xl bg-black/40 border border-white/5 flex items-center justify-center text-lg font-black flex-shrink-0 group-hover:border-primary/40 transition-colors">
                      {conv.contato_nome?.charAt(0) || "?"}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-4 mb-2">
                        <p className="text-sm font-black truncate group-hover:text-primary transition-colors">{conv.contato_nome || "Anônimo"}</p>
                        <span className={`text-[10px] font-black px-3 py-1 rounded-full uppercase tracking-widest ${statusColor[conv.status] || "bg-gray-500/15 text-gray-400"}`}>
                          {statusLabel[conv.status] || conv.status}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 font-bold mb-3">{conv.contato_fone || conv.contato_telefone}</p>
                      
                      <div className="flex items-center gap-4">
                         <div className="flex gap-1">
                           {[1,2,3,4,5].map(s => (
                             <div key={s} className={`w-1.5 h-1.5 rounded-full ${s <= (conv.score_lead || 0) ? "bg-primary shadow-[0_0_5px_rgba(0,242,255,0.5)]" : "bg-white/10"}`} />
                           ))}
                         </div>
                         {conv.intencao_de_compra && (
                           <span className="text-[9px] font-black text-rose-400 flex items-center gap-1 uppercase tracking-widest bg-rose-400/10 px-2 py-0.5 rounded-full">
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
            <div className="p-4 border-t border-white/5 bg-black/40 flex items-center justify-between backdrop-blur-xl">
               <span className="text-[10px] font-black text-gray-500 uppercase tracking-widest">{currentPage} / {totalPages}</span>
               <div className="flex gap-2">
                 <button onClick={() => setOffset(Math.max(0, offset - limit))} disabled={offset === 0} className="p-2.5 bg-white/5 rounded-xl hover:bg-white/10 border border-white/5 disabled:opacity-20 transition-all">
                   <ChevronLeft className="w-4 h-4" />
                 </button>
                 <button onClick={() => setOffset(offset + limit)} disabled={currentPage >= totalPages} className="p-2.5 bg-white/5 rounded-xl hover:bg-white/10 border border-white/5 disabled:opacity-20 transition-all">
                   <ChevronRight className="w-4 h-4" />
                 </button>
               </div>
            </div>
          )}
        </div>

        {/* Detail Panel */}
        <AnimatePresence>
          {selected ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex-1 flex flex-col bg-black/40 backdrop-blur-xl border-l border-white/5 overflow-hidden">
              
              <div className="p-8 border-b border-white/5 bg-white/[0.01]">
                <div className="flex items-center justify-between mb-8 lg:hidden">
                    <button onClick={() => setSelected(null)} className="p-3 bg-white/5 rounded-2xl hover:bg-primary/20 transition-all border border-white/10">
                       <ArrowLeft className="w-5 h-5" />
                    </button>
                </div>

                <div className="flex items-center gap-10">
                   <div className="w-32 h-32 rounded-[2.5rem] bg-gradient-to-br from-blue-600/20 to-primary/20 border-2 border-primary/20 flex items-center justify-center text-5xl font-black text-primary relative">
                      {selected.contato_nome?.charAt(0) || "?"}
                      <div className="absolute -bottom-2 -right-2 p-3 bg-primary text-black rounded-2xl shadow-xl">
                        <Zap className="w-5 h-5 font-black" />
                      </div>
                   </div>
                   <div className="flex-1">
                      <div className="flex items-center gap-4 mb-3">
                         <h2 className="text-3xl font-black">{selected.contato_nome || "Anônimo"}</h2>
                         <span className={`text-[10px] font-black px-4 py-1.5 rounded-full uppercase tracking-widest bg-primary/10 text-primary border border-primary/20`}>
                            {statusLabel[selected.status] || selected.status}
                         </span>
                      </div>
                      <p className="text-lg text-gray-500 font-bold flex items-center gap-3">
                         <Clock className="w-5 h-5 text-primary/40" />
                         {selected.contato_fone || selected.contato_telefone}
                      </p>
                   </div>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-10 custom-scrollbar space-y-12">
                 <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
                    {[
                      { label: "Lead Score", value: `${selected.score_lead || 0}/5`, icon: Star, color: "primary" },
                      { label: "Intenção", value: selected.intencao_de_compra ? "ALTA 🔥" : "MÉDIA", icon: Flame, color: "rose-500" },
                      { label: "Mensagens", value: (selected.total_mensagens_cliente || 0) + (selected.total_mensagens_ia || 0), icon: MessageSquare, color: "blue-500" },
                      { label: "Fase Funil", value: selected.status === 'open' ? "NEGOCIAÇÃO" : "FINALIZADO", icon: Target, color: "emerald-500" }
                    ].map(stat => (
                      <div key={stat.label} className="glass rounded-3xl p-6">
                         <div className="flex items-center gap-3 mb-4">
                            <stat.icon className={`w-4 h-4 text-${stat.color}`} />
                            <span className="text-[10px] font-black text-gray-500 uppercase tracking-widest">{stat.label}</span>
                         </div>
                         <p className="text-2xl font-black tracking-tighter">{stat.value}</p>
                      </div>
                    ))}
                 </div>

                 <div className="glass rounded-[2.5rem] p-10 relative overflow-hidden">
                    <div className="absolute top-0 right-0 p-8 opacity-5">
                       <Zap className="w-32 h-32" />
                    </div>
                    <div className="flex items-center gap-4 mb-8">
                       <div className="w-10 h-10 rounded-2xl bg-primary/10 flex items-center justify-center">
                          <Brain className="w-5 h-5 text-primary" />
                       </div>
                       <h3 className="text-xl font-black uppercase tracking-widest">Resumo Neural</h3>
                    </div>
                    <p className="text-gray-400 text-lg leading-relaxed font-medium italic">
                      "{selected.resumo_ia || "Nenhuma análise detalhada disponível para este lead até o momento."}"
                    </p>
                 </div>

                 <div className="glass rounded-[2rem] p-8 space-y-6">
                    <h4 className="text-[10px] font-black text-gray-500 uppercase tracking-[0.2em] mb-4">Informações de Tráfego</h4>
                    {[
                      { label: "Unidade de Origem", value: selected.unidade_nome, icon: Building2 },
                      { label: "Canal de Entrada", value: selected.canal, icon: Zap },
                      { label: "Mapeamento em", value: selected.created_at ? new Date(selected.created_at).toLocaleString("pt-BR") : "—", icon: Clock },
                    ].map(row => (
                      <div key={row.label} className="flex justify-between items-center pb-4 border-b border-white/5 last:border-0 last:pb-0">
                         <span className="text-sm font-bold text-gray-500 flex items-center gap-3">
                           <row.icon className="w-4 h-4 text-primary/40" /> {row.label}
                         </span>
                         <span className="text-sm font-black text-white">{row.value}</span>
                      </div>
                    ))}
                 </div>
              </div>
            </motion.div>
          ) : (
            <div className="flex-1 hidden lg:flex flex-col items-center justify-center opacity-20 select-none">
               <Bot className="w-32 h-32 mb-8 animate-float" />
               <p className="text-2xl font-black uppercase tracking-[0.5em]">Neural Insight</p>
               <p className="text-sm font-bold italic mt-2 underline decoration-primary underline-offset-8">Selecione uma interação para análise profunda</p>
            </div>
          )}
        </AnimatePresence>
      </div>
      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar { width: 5px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0, 242, 255, 0.1); border-radius: 10px; }
        @keyframes float { 0% { transform: translateY(0px); } 50% { transform: translateY(-20px); } 100% { transform: translateY(0px); } }
        .animate-float { animation: float 6s ease-in-out infinite; }
      `}</style>
    </div>
  );
}
