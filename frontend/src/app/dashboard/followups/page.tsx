"use client";

import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  MessageSquare, History, Layout, Clock, Play, Plus, Trash2, 
  RefreshCw, CheckCircle2, AlertCircle, Calendar, Settings2,
  Brain, Send, Sparkles, ChevronRight
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

interface FollowupTemplate {
  id: number;
  tipo: string;
  mensagem: string;
  delay_minutos: number;
  ordem: number;
  unidade_id: number | null;
  ativo: boolean;
}

interface FollowupHistory {
  id: number;
  contato_nome: string;
  tipo: string;
  mensagem: string;
  status: string;
  agendado_para: string;
  enviado_em: string | null;
  erro_log: string | null;
  unidade_nome: string;
}

const statusConfig: Record<string, { icon: any, color: string, label: string }> = {
  pendente: { icon: Clock, color: "text-amber-400 bg-amber-400/10 border-amber-400/20", label: "Pendente" },
  enviado: { icon: CheckCircle2, color: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20", label: "Enviado" },
  cancelado: { icon: AlertCircle, color: "text-slate-400 bg-slate-400/10 border-slate-400/20", label: "Cancelado" },
  erro: { icon: AlertCircle, color: "text-rose-400 bg-rose-400/10 border-rose-400/20", label: "Erro" },
};

export default function FollowupsPage() {
  const [templates, setTemplates] = useState<FollowupTemplate[]>([]);
  const [history, setHistory] = useState<FollowupHistory[]>([]);
  const [unidades, setUnidades] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"history" | "templates">("history");
  
  // States for Template Modal
  const [showModal, setShowModal] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<Partial<FollowupTemplate> | null>(null);
  const [saving, setSaving] = useState(false);

  const token = typeof window !== "undefined" ? localStorage.getItem("token") : "";
  const api = axios.create({
    baseURL: "/api-backend",
    headers: { Authorization: `Bearer ${token}` }
  });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [tRes, hRes, uRes] = await Promise.all([
        api.get("/management/followups/templates"),
        api.get("/management/followups/history"),
        api.get("/dashboard/unidades")
      ]);
      setTemplates(tRes.data || []);
      setHistory(hRes.data || []);
      setUnidades(uRes.data || []);
    } catch (err) {
      console.error("Erro ao buscar dados:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleSaveTemplate = async () => {
    if (!editingTemplate?.mensagem) return;
    setSaving(true);
    try {
      if (editingTemplate.id) {
        await api.put(`/management/followups/templates/${editingTemplate.id}`, editingTemplate);
      } else {
        await api.post("/management/followups/templates", {
            ...editingTemplate,
            ordem: editingTemplate.ordem || templates.length + 1,
            delay_minutos: editingTemplate.delay_minutos || 60,
            tipo: "recarga",
            ativo: true
        });
      }
      setShowModal(false);
      fetchData();
    } catch (err) {
      console.error("Erro ao salvar template:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteTemplate = async (id: number) => {
    if (!confirm("Tem certeza que deseja remover este template?")) return;
    try {
      await api.delete(`/management/followups/templates/${id}`);
      fetchData();
    } catch (err) {
      console.error("Erro ao deletar:", err);
    }
  };

  return (
    <div className="flex h-screen bg-[#0a0b10] text-slate-200 overflow-hidden font-sans">
      <DashboardSidebar activePage="followups" />

      <main className="flex-1 flex flex-col overflow-hidden relative">
        {/* Background Gradients */}
        <div className="absolute top-[-10%] right-[-5%] w-[40%] h-[40%] bg-[#00d2ff]/5 blur-[120px] rounded-full pointer-events-none" />
        <div className="absolute bottom-[-10%] left-[-5%] w-[40%] h-[40%] bg-purple-500/5 blur-[120px] rounded-full pointer-events-none" />

        <header className="p-8 pb-4 flex items-center justify-between relative z-10">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">
              Followups & Reengajamento
            </h1>
            <p className="text-slate-400 mt-1">Gerencie réguas de contato automáticas e inteligentes</p>
          </div>
          
          <div className="flex gap-4">
            <button 
              onClick={fetchData}
              className="p-3 bg-slate-800/40 hover:bg-slate-800/60 border border-slate-700/50 rounded-xl transition-all"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button 
              onClick={() => { setEditingTemplate({}); setShowModal(true); }}
              className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-[#00d2ff] to-[#3a7bd5] hover:opacity-90 text-white font-semibold rounded-xl transition-all shadow-lg shadow-blue-500/20"
            >
              <Plus className="w-5 h-5" />
              Novo Template
            </button>
          </div>
        </header>

        {/* Tabs */}
        <div className="px-8 mt-4 flex gap-8 border-b border-slate-800/50 relative z-10">
          <button 
            onClick={() => setActiveTab("history")}
            className={`pb-4 text-sm font-medium transition-all relative ${activeTab === 'history' ? 'text-[#00d2ff]' : 'text-slate-500 hover:text-slate-400'}`}
          >
            <div className="flex items-center gap-2">
              <History className="w-4 h-4" />
              Histórico de Envios
            </div>
            {activeTab === 'history' && <motion.div layoutId="tab" className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#00d2ff]" />}
          </button>
          <button 
            onClick={() => setActiveTab("templates")}
            className={`pb-4 text-sm font-medium transition-all relative ${activeTab === 'templates' ? 'text-[#00d2ff]' : 'text-slate-500 hover:text-slate-400'}`}
          >
            <div className="flex items-center gap-2">
              <Layout className="w-4 h-4" />
              Régua de Templates
            </div>
            {activeTab === 'templates' && <motion.div layoutId="tab" className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#00d2ff]" />}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-8 relative z-10 custom-scrollbar">
          <AnimatePresence mode="wait">
            {activeTab === 'history' ? (
              <motion.div 
                key="history"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="grid gap-4"
              >
                {history.length === 0 && !loading ? (
                  <div className="p-20 text-center bg-slate-900/20 border border-dashed border-slate-800 rounded-3xl">
                    <History className="w-12 h-12 text-slate-600 mx-auto mb-4" />
                    <p className="text-slate-500">Nenhum followup enviado ou agendado ainda.</p>
                  </div>
                ) : (
                  <div className="bg-slate-900/30 border border-slate-800/50 rounded-2xl overflow-hidden backdrop-blur-md">
                    <table className="w-full text-left border-collapse">
                      <thead>
                        <tr className="bg-slate-800/30 text-slate-400 text-xs font-semibold uppercase tracking-wider">
                          <th className="px-6 py-4">Lead / Unidade</th>
                          <th className="px-6 py-4">Mensagem Preview</th>
                          <th className="px-6 py-4">Agendado / Enviado</th>
                          <th className="px-6 py-4">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/50">
                        {history.map((h) => (
                          <tr key={h.id} className="hover:bg-slate-800/20 transition-colors group">
                            <td className="px-6 py-4">
                              <div className="flex flex-col">
                                <span className="font-semibold text-white">{h.contato_nome || "Lead"}</span>
                                <span className="text-xs text-slate-500 flex items-center gap-1 mt-0.5">
                                  <Calendar className="w-3 h-3" /> {h.unidade_nome}
                                </span>
                              </div>
                            </td>
                            <td className="px-6 py-4">
                              <p className="text-sm text-slate-400 max-w-xs truncate italic">"{h.mensagem}"</p>
                              <span className="text-[10px] uppercase font-bold text-slate-600 bg-slate-800 px-1.5 py-0.5 rounded mt-1 inline-block tracking-tight">
                                {h.tipo}
                              </span>
                            </td>
                            <td className="px-6 py-4">
                              <div className="flex flex-col gap-1">
                                <span className="text-xs text-slate-300">
                                  {new Date(h.agendado_para).toLocaleString('pt-BR')}
                                </span>
                                {h.enviado_em && (
                                  <span className="text-[10px] text-emerald-500 flex items-center gap-1">
                                    <Send className="w-2.5 h-2.5" /> {new Date(h.enviado_em).toLocaleTimeString('pt-BR')}
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="px-6 py-4">
                              <span className={`px-3 py-1 rounded-full text-[11px] font-bold border flex items-center gap-1.5 w-fit ${statusConfig[h.status]?.color || statusConfig.pendente.color}`}>
                                {(() => {
                                  const Icon = statusConfig[h.status]?.icon || Clock;
                                  return <Icon className="w-3 h-3" />;
                                })()}
                                {statusConfig[h.status]?.label || h.status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </motion.div>
            ) : (
              <motion.div 
                key="templates"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="grid gap-6 md:grid-cols-2 lg:grid-cols-3"
              >
                {templates.map((t, idx) => (
                  <motion.div 
                    key={t.id}
                    layoutId={`template-${t.id}`}
                    className="p-6 bg-slate-900/40 border border-slate-800/50 rounded-2xl group hover:border-[#00d2ff]/30 transition-all flex flex-col backdrop-blur-md"
                  >
                    <div className="flex justify-between items-start mb-4">
                      <div className="p-2 bg-blue-500/10 rounded-lg">
                        <MessageSquare className="w-5 h-5 text-[#00d2ff]" />
                      </div>
                      <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button 
                          onClick={() => { setEditingTemplate(t); setShowModal(true); }}
                          className="p-1.5 hover:bg-slate-800 rounded-md transition-colors text-slate-400"
                        >
                          <Settings2 className="w-4 h-4" />
                        </button>
                        <button 
                          onClick={() => handleDeleteTemplate(t.id)}
                          className="p-1.5 hover:bg-rose-500/20 rounded-md transition-colors text-slate-400 hover:text-rose-400"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 mb-2">
                       <span className="text-[10px] font-bold text-[#00d2ff] bg-[#00d2ff]/10 px-2 py-0.5 rounded uppercase tracking-wider">
                          Template #{idx + 1}
                       </span>
                       <span className="text-[10px] font-bold text-slate-500 bg-slate-800 px-2 py-0.5 rounded uppercase tracking-wider">
                          +{t.delay_minutos} min
                       </span>
                    </div>

                    <p className="text-slate-300 text-sm flex-1 line-clamp-4 leading-relaxed tracking-wide">
                      "{t.mensagem}"
                    </p>

                    <div className="mt-6 pt-4 border-t border-slate-800/50 flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <div className={`w-1.5 h-1.5 rounded-full ${t.ativo ? 'bg-emerald-500 ring-4 ring-emerald-500/10' : 'bg-slate-600'}`} />
                        <span className="text-xs text-slate-400 font-medium">
                          {t.ativo ? 'Ativo' : 'Pausado'}
                        </span>
                      </div>
                      <span className="text-[10px] text-slate-500">
                        {t.unidade_id ? 'Unidade Específica' : 'Global (Todas)'}
                      </span>
                    </div>
                  </motion.div>
                ))}

                <button 
                  onClick={() => { setEditingTemplate({}); setShowModal(true); }}
                  className="p-8 bg-slate-900/20 border-2 border-dashed border-slate-800/50 rounded-2xl flex flex-col items-center justify-center gap-4 hover:border-[#00d2ff]/30 hover:bg-slate-800/10 transition-all group"
                >
                  <div className="p-3 bg-slate-800 rounded-full group-hover:scale-110 transition-transform">
                    <Plus className="w-6 h-6 text-slate-400 group-hover:text-[#00d2ff]" />
                  </div>
                  <span className="text-slate-500 font-medium group-hover:text-slate-300">Novo Passo da Régua</span>
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>

      {/* Modal */}
      <AnimatePresence>
        {showModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
            <motion.div 
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="bg-[#111218] border border-slate-800 w-full max-w-xl rounded-3xl overflow-hidden shadow-2xl"
            >
              <div className="p-8 pb-0 flex justify-between items-center">
                <h2 className="text-2xl font-bold text-white flex items-center gap-3">
                  <Brain className="w-6 h-6 text-[#00d2ff]" />
                  Configurar Followup
                </h2>
                <button onClick={() => setShowModal(false)} className="text-slate-500 hover:text-white transition-colors">
                  <X className="w-6 h-6" />
                </button>
              </div>

              <div className="p-8 space-y-6">
                <div className="space-y-2">
                  <label className="text-xs font-bold text-slate-500 uppercase tracking-widest pl-1">
                    Mensagem Base (Template)
                  </label>
                  <div className="relative group">
                    <textarea 
                      value={editingTemplate?.mensagem || ""}
                      onChange={e => setEditingTemplate({ ...editingTemplate, mensagem: e.target.value })}
                      placeholder="Olá {{nome}}, gostaria de continuar nosso assunto sobre a {{unidade}}..."
                      className="w-full h-32 bg-slate-900/50 border border-slate-800 rounded-2xl p-4 text-slate-300 placeholder:text-slate-600 focus:outline-none focus:border-[#00d2ff]/50 focus:ring-4 focus:ring-blue-500/5 transition-all resize-none"
                    />
                    <div className="absolute right-4 bottom-4 flex items-center gap-1 text-[10px] text-slate-600 group-hover:text-slate-400">
                      <Sparkles className="w-3 h-3 text-[#00d2ff]" />
                      Será reescrito por IA no envio
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-slate-500 uppercase tracking-widest pl-1">
                      Delay (Minutos)
                    </label>
                    <input 
                      type="number"
                      value={editingTemplate?.delay_minutos || 0}
                      onChange={e => setEditingTemplate({ ...editingTemplate, delay_minutos: parseInt(e.target.value) })}
                      className="w-full bg-slate-900/50 border border-slate-800 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-[#00d2ff]/50"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-slate-500 uppercase tracking-widest pl-1">
                      Unidade Alvo
                    </label>
                    <select 
                      value={editingTemplate?.unidade_id || ""}
                      onChange={e => setEditingTemplate({ ...editingTemplate, unidade_id: e.target.value ? parseInt(e.target.value) : null })}
                      className="w-full bg-slate-900/50 border border-slate-800 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-[#00d2ff]/50 appearance-none"
                    >
                      <option value="">Global (Todas)</option>
                      {unidades.map(u => <option key={u.id} value={u.id}>{u.nome}</option>)}
                    </select>
                  </div>
                </div>

                <div className="pt-4 flex gap-4">
                  <button 
                    onClick={() => setShowModal(false)}
                    className="flex-1 px-6 py-4 bg-slate-800/40 hover:bg-slate-800/60 text-slate-400 font-bold rounded-2xl transition-all"
                  >
                    Descartar
                  </button>
                  <button 
                    onClick={handleSaveTemplate}
                    disabled={saving}
                    className="flex-1 px-6 py-4 bg-gradient-to-r from-[#00d2ff] to-[#3a7bd5] text-white font-bold rounded-2xl shadow-lg shadow-blue-500/20 hover:opacity-90 transition-all flex items-center justify-center gap-2"
                  >
                    {saving ? <RefreshCw className="w-5 h-5 animate-spin" /> : <CheckCircle2 className="w-5 h-5" />}
                    {editingTemplate?.id ? 'Salvar Alterações' : 'Criar Template'}
                  </button>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
