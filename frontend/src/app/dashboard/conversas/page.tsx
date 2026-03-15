"use client";

import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  MessageSquare, Search, Filter, ChevronLeft, ChevronRight,
  Building2, Star, Flame, Clock, User, X, ArrowLeft, RefreshCw
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

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  const statusColor: Record<string, string> = {
    open: "bg-emerald-500/15 text-emerald-400",
    resolved: "bg-gray-500/15 text-gray-400",
    closed: "bg-gray-700/20 text-gray-500",
    encerrada: "bg-gray-500/15 text-gray-400",
    pending: "bg-amber-500/15 text-amber-400",
  };

  const statusLabel: Record<string, string> = {
    open: "Aberta", resolved: "Resolvida", closed: "Fechada",
    encerrada: "Encerrada", pending: "Pendente"
  };

  return (
    <div className="min-h-screen bg-[#080810] text-white flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-20 bg-[#080810]/90 backdrop-blur-xl border-b border-white/5 px-6 py-4 flex items-center gap-4">
        <a href="/dashboard" className="p-2 rounded-xl hover:bg-white/5 transition-all">
          <ArrowLeft className="w-5 h-5 text-gray-400" />
        </a>
        <div>
          <h1 className="font-bold text-lg">Central de Conversas</h1>
          <p className="text-xs text-gray-500">{total} conversas encontradas</p>
        </div>
        <button onClick={fetchConversations} className="ml-auto p-2 rounded-xl hover:bg-white/5 transition-all text-gray-400">
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* List Panel */}
        <div className={`flex flex-col w-full ${selected ? "hidden lg:flex lg:w-2/5 xl:w-1/3" : ""}`}>
          {/* Filters */}
          <div className="bg-[#0a0a14] border-b border-white/5 px-4 py-3 space-y-3">
            <form onSubmit={handleSearch} className="flex gap-2">
              <div className="flex-1 relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                  value={buscaInput}
                  onChange={e => setBuscaInput(e.target.value)}
                  placeholder="Buscar por nome ou telefone..."
                  className="w-full bg-white/5 border border-white/10 rounded-xl pl-9 pr-4 py-2 text-sm focus:outline-none focus:border-violet-500/50"
                />
              </div>
              <button type="submit" className="bg-violet-600 hover:bg-violet-500 px-4 py-2 rounded-xl text-sm font-bold transition-all">
                Buscar
              </button>
            </form>
            <div className="flex gap-2 flex-wrap">
              <select
                value={filterUnidade}
                onChange={e => { setFilterUnidade(e.target.value ? Number(e.target.value) : ""); setOffset(0); }}
                className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-gray-300 focus:outline-none">
                <option value="">Todas as Unidades</option>
                {unidades.map(u => <option key={u.id} value={u.id}>{u.nome}</option>)}
              </select>
              <select
                value={filterStatus}
                onChange={e => { setFilterStatus(e.target.value); setOffset(0); }}
                className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-gray-300 focus:outline-none">
                <option value="">Todos os Status</option>
                <option value="open">Aberta</option>
                <option value="resolved">Resolvida</option>
                <option value="closed">Fechada</option>
                <option value="encerrada">Encerrada</option>
              </select>
              {(busca || filterStatus || filterUnidade) && (
                <button onClick={clearFilters} className="flex items-center gap-1 bg-rose-500/10 text-rose-400 border border-rose-500/20 rounded-lg px-3 py-1.5 text-xs font-bold hover:bg-rose-500/20 transition-all">
                  <X className="w-3 h-3" /> Limpar
                </button>
              )}
            </div>
          </div>

          {/* Conversation List */}
          <div className="flex-1 overflow-y-auto divide-y divide-white/[0.04]">
            {loading ? (
              [...Array(6)].map((_, i) => (
                <div key={i} className="px-4 py-4 animate-pulse">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-white/5 rounded-xl flex-shrink-0" />
                    <div className="flex-1 space-y-2">
                      <div className="h-3 bg-white/5 rounded w-2/3" />
                      <div className="h-2 bg-white/5 rounded w-1/2" />
                    </div>
                  </div>
                </div>
              ))
            ) : conversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-center px-4">
                <MessageSquare className="w-10 h-10 text-gray-700 mb-3" />
                <p className="text-sm text-gray-500">Nenhuma conversa encontrada</p>
              </div>
            ) : (
              conversations.map((conv) => (
                <button
                  key={conv.id}
                  onClick={() => setSelected(conv)}
                  className={`w-full text-left px-4 py-4 hover:bg-white/[0.03] transition-all ${selected?.id === conv.id ? "bg-violet-600/10 border-l-2 border-violet-500" : ""}`}>
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-600/30 to-indigo-600/30 border border-white/10 flex items-center justify-center text-sm font-bold flex-shrink-0">
                      {conv.contato_nome?.charAt(0) || "?"}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <p className="text-sm font-bold truncate">{conv.contato_nome || "Anônimo"}</p>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full flex-shrink-0 ${statusColor[conv.status] || "bg-gray-500/15 text-gray-400"}`}>
                          {statusLabel[conv.status] || conv.status}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 truncate">{conv.contato_fone || conv.contato_telefone}</p>
                      {conv.resumo_ia && (
                        <p className="text-xs text-gray-600 truncate mt-1">{conv.resumo_ia}</p>
                      )}
                      <div className="flex items-center gap-3 mt-2">
                        <div className="flex gap-0.5">
                          {[1,2,3,4,5].map(s => (
                            <div key={s} className={`w-1 h-1 rounded-full ${s <= (conv.score_lead || 0) ? "bg-violet-400" : "bg-white/10"}`} />
                          ))}
                        </div>
                        {conv.intencao_de_compra && (
                          <span className="text-[9px] font-bold text-rose-400 flex items-center gap-0.5">
                            <Flame className="w-2.5 h-2.5" /> Quente
                          </span>
                        )}
                        {conv.unidade_nome && (
                          <span className="text-[9px] text-gray-600 flex items-center gap-0.5 ml-auto">
                            <Building2 className="w-2.5 h-2.5" /> {conv.unidade_nome}
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
            <div className="border-t border-white/5 px-4 py-3 flex items-center justify-between bg-[#0a0a14]">
              <span className="text-xs text-gray-500">{currentPage} / {totalPages}</span>
              <div className="flex gap-2">
                <button onClick={() => setOffset(Math.max(0, offset - limit))} disabled={offset === 0}
                  className="p-1.5 rounded-lg hover:bg-white/5 disabled:opacity-30 transition-all">
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button onClick={() => setOffset(offset + limit)} disabled={currentPage >= totalPages}
                  className="p-1.5 rounded-lg hover:bg-white/5 disabled:opacity-30 transition-all">
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Detail Panel */}
        <AnimatePresence>
          {selected && (
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              className="flex-1 border-l border-white/5 flex flex-col bg-[#0a0a14]">
              {/* Detail Header */}
              <div className="px-6 py-4 border-b border-white/5 flex items-center gap-4">
                <button onClick={() => setSelected(null)} className="lg:hidden p-2 rounded-xl hover:bg-white/5">
                  <ArrowLeft className="w-4 h-4" />
                </button>
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-600/40 to-indigo-600/40 border border-white/10 flex items-center justify-center font-bold">
                  {selected.contato_nome?.charAt(0) || "?"}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-bold">{selected.contato_nome || "Anônimo"}</p>
                  <p className="text-xs text-gray-500">{selected.contato_fone || selected.contato_telefone}</p>
                </div>
                <span className={`text-xs font-bold px-3 py-1 rounded-full ${statusColor[selected.status] || "bg-gray-500/15 text-gray-400"}`}>
                  {statusLabel[selected.status] || selected.status}
                </span>
              </div>

              <div className="flex-1 overflow-y-auto p-6 space-y-5">
                {/* Stats */}
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: "Score", value: `${selected.score_lead || 0}/5`, icon: Star },
                    { label: "Intenção", value: selected.intencao_de_compra ? "🔥 Alta" : "Normal", icon: Flame },
                    { label: "Msgs Cliente", value: selected.total_mensagens_cliente || 0, icon: User },
                    { label: "Msgs IA", value: selected.total_mensagens_ia || 0, icon: MessageSquare },
                  ].map(stat => (
                    <div key={stat.label} className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
                      <p className="text-xs text-gray-500 mb-1">{stat.label}</p>
                      <p className="text-lg font-bold">{stat.value}</p>
                    </div>
                  ))}
                </div>

                {/* Info */}
                <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4 space-y-3">
                  {[
                    { label: "Unidade", value: selected.unidade_nome },
                    { label: "Canal", value: selected.canal },
                    { label: "Criado em", value: selected.created_at ? new Date(selected.created_at).toLocaleString("pt-BR") : "—" },
                    { label: "Última atividade", value: selected.updated_at ? new Date(selected.updated_at).toLocaleString("pt-BR") : "—" },
                  ].map(row => row.value && (
                    <div key={row.label} className="flex justify-between items-center text-sm">
                      <span className="text-gray-500">{row.label}</span>
                      <span className="font-medium text-right truncate max-w-[60%]">{row.value}</span>
                    </div>
                  ))}
                </div>

                {/* Resumo IA */}
                {selected.resumo_ia && (
                  <div className="bg-violet-500/5 border border-violet-500/20 rounded-xl p-4">
                    <p className="text-xs font-bold text-violet-400 mb-2 uppercase tracking-widest">Resumo da IA</p>
                    <p className="text-sm text-gray-300 leading-relaxed">{selected.resumo_ia}</p>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
