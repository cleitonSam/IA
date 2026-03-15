"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { History, Loader2, Search, Calendar, MessageCircle, ArrowLeft, ChevronRight, X, User, Phone, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface ConversationLog {
  conversation_id: number;
  contato_nome: string;
  contato_fone: string;
  score_lead: number;
  intencao_de_compra: string;
  status: string;
  updated_at: string;
  resumo_ia: string;
}

export default function LogsPage() {
  const [logs, setLogs] = useState<ConversationLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedLog, setSelectedLog] = useState<ConversationLog | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    fetchLogs();
  }, []);

  const fetchLogs = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await axios.get("/api-backend/management/logs", {
        headers: { Authorization: `Bearer ${token}` }
      });
      setLogs(response.data);
    } catch (error) {
      console.error("Erro ao carregar logs:", error);
    } finally {
      setLoading(false);
    }
  };

  const filteredLogs = logs.filter(log => 
    log.contato_nome?.toLowerCase().includes(search.toLowerCase()) ||
    log.contato_fone?.includes(search)
  );

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-white p-6 md:p-12">
      <div className="max-w-6xl mx-auto">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
          <div className="flex items-center gap-4">
            <a href="/dashboard" className="p-2 hover:bg-white/5 rounded-full transition-colors">
              <ArrowLeft className="w-5 h-5" />
            </a>
            <div>
              <h1 className="text-3xl font-bold flex items-center gap-3">
                <History className="w-8 h-8 text-primary" />
                Logs de Conversa
              </h1>
              <p className="text-gray-400 mt-1">Histórico completo das interações da IA.</p>
            </div>
          </div>
          
          <div className="relative w-full md:w-96">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
            <input
              type="text"
              placeholder="Buscar por nome ou telefone..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-slate-950/40 border border-white/10 rounded-xl pl-12 pr-4 py-3 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-medium"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4">
          {filteredLogs.length === 0 ? (
            <div className="text-center py-20 bg-white/5 border border-dashed border-white/10 rounded-2xl">
              <MessageCircle className="w-12 h-12 text-gray-600 mx-auto mb-4" />
              <p className="text-gray-400">Nenhum log encontrado.</p>
            </div>
          ) : (
            filteredLogs.map((log) => (
              <motion.div
                layout
                key={log.conversation_id}
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                onClick={() => setSelectedLog(log)}
                className="bg-white/5 border border-white/10 rounded-2xl p-6 flex flex-col md:flex-row gap-6 md:items-center justify-between hover:bg-white/10 cursor-pointer transition-all group border-l-4 border-l-transparent hover:border-l-blue-500"
              >
                <div className="grid grid-cols-1 md:grid-cols-4 gap-6 flex-1">
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center text-primary font-bold uppercase">
                      {log.contato_nome?.charAt(0) || <User className="w-5 h-5" />}
                    </div>
                    <div>
                      <p className="font-bold text-lg">{log.contato_nome || "Anônimo"}</p>
                      <p className="text-sm text-gray-500 flex items-center gap-1">
                        <Phone className="w-3 h-3" /> {log.contato_fone || "Sem telefone"}
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-col justify-center">
                    <p className="text-[10px] font-black text-gray-500 uppercase tracking-widest mb-1">Status</p>
                    <span className={`text-xs font-bold px-3 py-1 rounded-full w-fit ${
                      log.status === 'ativa' ? 'bg-green-500/10 text-green-400' : 'bg-gray-500/10 text-gray-400'
                    }`}>
                      {log.status.toUpperCase()}
                    </span>
                  </div>

                  <div className="flex flex-col justify-center">
                    <p className="text-[10px] font-black text-gray-500 uppercase tracking-widest mb-1">Qualificação</p>
                    <div className="flex items-center gap-2">
                       <div className="flex-1 bg-white/10 h-1.5 rounded-full overflow-hidden">
                          <div 
                            className={`h-full rounded-full ${log.score_lead > 7 ? 'bg-green-500' : log.score_lead > 4 ? 'bg-yellow-500' : 'bg-gray-500'}`} 
                            style={{ width: `${(log.score_lead || 0) * 10}%` }}
                          />
                       </div>
                       <span className="text-sm font-bold">{log.score_lead || 0}/10</span>
                    </div>
                  </div>

                  <div className="flex flex-col justify-center">
                    <p className="text-[10px] font-black text-gray-500 uppercase tracking-widest mb-1">Data/Hora</p>
                    <p className="text-sm font-medium flex items-center gap-1.5">
                      <Calendar className="w-4 h-4 text-gray-400" />
                      {new Date(log.updated_at).toLocaleString('pt-BR')}
                    </p>
                  </div>
                </div>
                
                <ChevronRight className="w-6 h-6 text-gray-600 group-hover:text-primary transition-colors" />
              </motion.div>
            ))
          )}
        </div>
      </div>

      {/* Log Modal */}
      <AnimatePresence>
        {selectedLog && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 bg-background/80 backdrop-blur-md"
              onClick={() => setSelectedLog(null)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 30 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 30 }}
              className="bg-slate-950 border border-white/10 rounded-3xl w-full max-w-3xl overflow-hidden relative shadow-2xl"
            >
              <div className="p-8 border-b border-white/10 flex items-center justify-between bg-white/[0.02]">
                <div className="flex items-center gap-4">
                  <div className="w-14 h-14 rounded-2xl bg-primary flex items-center justify-center text-black font-bold text-xl uppercase shadow-lg shadow-primary/20">
                    {selectedLog.contato_nome?.charAt(0) || "U"}
                  </div>
                  <div>
                    <h2 className="text-2xl font-bold">{selectedLog.contato_nome || "Anônimo"}</h2>
                    <p className="text-gray-400 font-medium">{selectedLog.contato_fone}</p>
                  </div>
                </div>
                <button 
                  onClick={() => setSelectedLog(null)} 
                  className="p-3 hover:bg-white/10 rounded-xl transition-all"
                >
                  <X className="w-6 h-6" />
                </button>
              </div>

              <div className="p-8 space-y-8 max-h-[70vh] overflow-y-auto custom-scrollbar">
                <div className="grid grid-cols-2 gap-6">
                  <div className="p-6 bg-white/5 rounded-2xl border border-white/5">
                    <p className="text-xs font-black text-gray-500 uppercase tracking-widest mb-3">Intenção de Compra</p>
                    <p className="text-xl font-bold flex items-center gap-2">
                       <Zap className="w-5 h-5 text-yellow-500" />
                       {selectedLog.intencao_de_compra || "Não identificada"}
                    </p>
                  </div>
                  <div className="p-6 bg-white/5 rounded-2xl border border-white/5">
                    <p className="text-xs font-black text-gray-500 uppercase tracking-widest mb-3">Score de Lead</p>
                    <p className="text-3xl font-black text-blue-500">{selectedLog.score_lead || 0}<span className="text-gray-600 text-lg font-bold">/10</span></p>
                  </div>
                </div>

                <div>
                  <p className="text-xs font-black text-gray-500 uppercase tracking-widest mb-4 flex items-center gap-2">
                    <MessageCircle className="w-4 h-4" /> Resumo da Conversa (IA)
                  </p>
                  <div className="p-8 bg-blue-500/5 border border-blue-500/10 rounded-3xl relative overflow-hidden group">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/10 blur-3xl -mr-16 -mt-16 group-hover:bg-blue-500/20 transition-all duration-700" />
                    <p className="text-gray-300 leading-relaxed text-lg italic relative z-10">
                      "{selectedLog.resumo_ia || "Nenhum resumo gerado para esta conversa."}"
                    </p>
                  </div>
                </div>
              </div>

              <div className="p-8 bg-white/[0.02] border-t border-white/10 flex justify-end">
                <button
                  onClick={() => setSelectedLog(null)}
                  className="bg-white/10 hover:bg-white/20 text-white px-8 py-3 rounded-xl font-bold transition-all"
                >
                  Fechar Visualização
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
      
      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar { width: 6px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #333; border-radius: 10px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #444; }
      `}</style>
    </div>
  );
}
