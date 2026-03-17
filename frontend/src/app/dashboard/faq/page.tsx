"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { HelpCircle, Plus, Trash2, Edit2, Loader2, Save, X, CheckCircle2, Globe, Building2, Brain } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

interface FAQItem {
  id?: number;
  pergunta: string;
  resposta: string;
  unidade_id: number | null;
  todas_unidades: boolean;
  prioridade: number;
  ativo: boolean;
}

interface Unidade { id: number; nome: string; }

const emptyFaq: FAQItem = { pergunta: "", resposta: "", unidade_id: null, todas_unidades: true, prioridade: 0, ativo: true };

export default function FAQPage() {
  const [faqs, setFaqs] = useState<FAQItem[]>([]);
  const [unidades, setUnidades] = useState<Unidade[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingFaq, setEditingFaq] = useState<FAQItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [formData, setFormData] = useState<FAQItem>(emptyFaq);

  const getConfig = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } });

  useEffect(() => {
    Promise.all([
      axios.get("/api-backend/management/faq", getConfig()),
      axios.get("/api-backend/dashboard/unidades", getConfig())
    ]).then(([faqRes, unitRes]) => { setFaqs(faqRes.data); setUnidades(unitRes.data); })
      .catch(console.error).finally(() => setLoading(false));
  }, []);

  const fetchData = async () => {
    const [faqRes] = await Promise.all([axios.get("/api-backend/management/faq", getConfig())]);
    setFaqs(faqRes.data);
  };

  const handleOpenModal = (faq: FAQItem | null = null) => {
    setEditingFaq(faq);
    setFormData(faq ? { ...faq } : emptyFaq);
    setIsModalOpen(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editingFaq?.id) {
        await axios.put(`/api-backend/management/faq/${editingFaq.id}`, formData, getConfig());
      } else {
        await axios.post("/api-backend/management/faq", formData, getConfig());
      }
      setSuccess(true);
      setTimeout(() => { setSuccess(false); setIsModalOpen(false); fetchData(); }, 1000);
    } catch { alert("Erro ao salvar FAQ."); }
    finally { setSaving(false); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Excluir esta pergunta?")) return;
    await axios.delete(`/api-backend/management/faq/${id}`, getConfig()).catch(() => alert("Erro ao excluir."));
    fetchData();
  };

  const inputClass = "w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 transition-all font-medium text-sm";

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="faq" />
      <main className="flex-1 min-w-0 overflow-auto">
        <div className="fixed top-0 right-0 w-[500px] h-[400px] bg-[#00d2ff]/3 rounded-full blur-[120px] pointer-events-none" />
        <div className="relative z-10 p-8 lg:p-10 max-w-6xl mx-auto pb-20">
          {/* Header */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-1.5 h-5 bg-[#00d2ff] rounded-full" />
                <span className="text-[10px] font-black text-[#00d2ff] uppercase tracking-[0.4em]">Fluxo Digital & Tech</span>
              </div>
              <h1 className="text-4xl font-black tracking-tight" style={{ background: "linear-gradient(135deg,#fff 0%,#00d2ff 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                Base de Conhecimento
              </h1>
              <p className="text-slate-500 mt-2 text-sm italic">Treine o cérebro do seu agente com dados específicos da operação.</p>
            </div>
            <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }} onClick={() => handleOpenModal()}
              className="flex items-center gap-3 bg-[#00d2ff] text-black px-8 py-4 rounded-2xl font-black uppercase tracking-widest text-sm shadow-[0_0_25px_rgba(0,210,255,0.3)]">
              <Plus className="w-5 h-5" /> Novo Registro
            </motion.button>
          </div>

          {/* List - Compact Table Layout */}
          {loading ? (
            <div className="flex items-center justify-center py-40"><Loader2 className="w-8 h-8 text-[#00d2ff] animate-spin" /></div>
          ) : faqs.length === 0 ? (
            <div className="text-center py-40 rounded-[3rem] border border-dashed border-white/5">
              <Brain className="w-16 h-16 text-slate-700 mx-auto mb-6" />
              <p className="text-slate-400 font-black uppercase tracking-widest">Cérebro vazio</p>
              <p className="text-slate-600 text-sm mt-2">Adicione perguntas e respostas para começar.</p>
            </div>
          ) : (
            <div className="bg-slate-900/40 border border-white/5 rounded-[2rem] overflow-hidden backdrop-blur-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-white/5 bg-white/[0.02]">
                      <th className="px-8 py-5 text-[10px] font-black uppercase tracking-widest text-slate-500 w-[100px]">Âmbito</th>
                      <th className="px-8 py-5 text-[10px] font-black uppercase tracking-widest text-slate-500">Conhecimento (Pergunta & Resposta)</th>
                      <th className="px-8 py-5 text-[10px] font-black uppercase tracking-widest text-slate-500 w-[80px] text-center">Prio</th>
                      <th className="px-8 py-5 text-[10px] font-black uppercase tracking-widest text-slate-500 w-[120px] text-right">Ações</th>
                    </tr>
                  </thead>
                  <tbody>
                    <AnimatePresence mode="popLayout">
                      {[...faqs].reverse().map((faq, i) => (
                        <motion.tr 
                          key={faq.id} 
                          initial={{ opacity: 0, y: 10 }} 
                          animate={{ opacity: 1, y: 0 }} 
                          transition={{ delay: i * 0.03 }}
                          className="border-b border-white/5 hover:bg-white/[0.02] group transition-colors"
                        >
                          <td className="px-8 py-6 vertical-top">
                            {faq.todas_unidades ? (
                              <div className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-tighter bg-[#00d2ff]/10 text-[#00d2ff] px-2.5 py-1 rounded-lg border border-[#00d2ff]/20 w-fit">
                                <Globe className="w-3 h-3" /> Global
                              </div>
                            ) : (
                              <div className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-tighter bg-indigo-500/10 text-indigo-400 px-2.5 py-1 rounded-lg border border-indigo-500/20 w-fit">
                                <Building2 className="w-3 h-3" /> Unidade
                              </div>
                            )}
                          </td>
                          <td className="px-8 py-6">
                            <div className="max-w-2xl">
                              <h3 className="text-sm font-bold text-white group-hover:text-[#00d2ff] transition-colors mb-1.5 line-clamp-1">
                                {faq.pergunta}
                              </h3>
                              <p className="text-xs text-slate-500 line-clamp-2 leading-relaxed italic">
                                "{faq.resposta}"
                              </p>
                            </div>
                          </td>
                          <td className="px-8 py-6 text-center">
                            <span className="text-[10px] font-black text-slate-600 bg-white/5 px-2.5 py-1 rounded-lg border border-white/5">
                              {faq.prioridade}
                            </span>
                          </td>
                          <td className="px-8 py-6">
                            <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button 
                                onClick={() => handleOpenModal(faq)} 
                                className="p-2 bg-white/5 hover:bg-[#00d2ff]/20 text-slate-500 hover:text-[#00d2ff] rounded-xl transition-all border border-white/5 hover:border-[#00d2ff]/30"
                                title="Editar"
                              >
                                <Edit2 className="w-4 h-4" />
                              </button>
                              <button 
                                onClick={() => handleDelete(faq.id!)} 
                                className="p-2 bg-white/5 hover:bg-red-500/20 text-slate-500 hover:text-red-400 rounded-xl transition-all border border-white/5 hover:border-red-500/30"
                                title="Excluir"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </td>
                        </motion.tr>
                      ))}
                    </AnimatePresence>
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Modal */}
      <AnimatePresence>
        {isModalOpen && (
          <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="absolute inset-0 bg-[#020617]/90 backdrop-blur-2xl" onClick={() => setIsModalOpen(false)} />
            <motion.div initial={{ opacity: 0, scale: 0.96, y: 16 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96 }}
              className="bg-[#080f1e] border border-white/10 rounded-[2.5rem] w-full max-w-2xl overflow-hidden relative shadow-2xl flex flex-col">
              <div className="px-10 py-8 border-b border-white/5 flex items-center justify-between bg-slate-900/30 flex-shrink-0">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-2xl bg-[#00d2ff]/10 flex items-center justify-center border border-[#00d2ff]/20">
                    {editingFaq ? <Edit2 className="w-6 h-6 text-[#00d2ff]" /> : <Plus className="w-6 h-6 text-[#00d2ff]" />}
                  </div>
                  <div>
                    <h2 className="text-xl font-black">{editingFaq ? "Editar Conhecimento" : "Novo Conhecimento"}</h2>
                    <p className="text-slate-500 text-sm mt-0.5">Defina como a IA responde esta dúvida.</p>
                  </div>
                </div>
                <button onClick={() => setIsModalOpen(false)} className="p-3 hover:bg-white/5 rounded-2xl transition-all border border-white/5 text-slate-500">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <form onSubmit={handleSave} className="p-10 space-y-7 overflow-y-auto">
                <div className="space-y-2">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Pergunta do Usuário</label>
                  <input required type="text" value={formData.pergunta} onChange={e => setFormData({ ...formData, pergunta: e.target.value })}
                    placeholder="Ex: Quais são os horários?" className={inputClass} />
                </div>
                <div className="space-y-2">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Resposta da IA</label>
                  <textarea required rows={5} value={formData.resposta} onChange={e => setFormData({ ...formData, resposta: e.target.value })}
                    placeholder="Escreva a resposta detalhada..." className={`${inputClass} resize-none leading-relaxed`} />
                </div>
                <div className="grid grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Abrangência</label>
                    <div className="flex p-1.5 bg-slate-900/50 border border-white/8 rounded-2xl">
                      {["Global", "Unidade"].map(opt => (
                        <button key={opt} type="button" onClick={() => setFormData({ ...formData, todas_unidades: opt === "Global", unidade_id: null })}
                          className={`flex-1 py-3 text-[10px] font-black uppercase tracking-widest rounded-xl transition-all ${(opt === "Global") === formData.todas_unidades ? "bg-[#00d2ff] text-black" : "text-slate-500 hover:text-white"}`}>
                          {opt}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Prioridade</label>
                    <input type="number" value={formData.prioridade} onChange={e => setFormData({ ...formData, prioridade: parseInt(e.target.value) })}
                      className={`${inputClass} text-center`} min="0" max="100" />
                  </div>
                </div>
                {!formData.todas_unidades && (
                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Selecionar Unidade</label>
                    <select required value={formData.unidade_id || ""} onChange={e => setFormData({ ...formData, unidade_id: parseInt(e.target.value) })}
                      className={`${inputClass} cursor-pointer`}>
                      <option value="">Selecione...</option>
                      {unidades.map(u => <option key={u.id} value={u.id}>{u.nome}</option>)}
                    </select>
                  </div>
                )}
                <div className="flex gap-4 pt-2">
                  <button type="button" onClick={() => setIsModalOpen(false)} className="flex-1 py-4 rounded-2xl font-bold text-sm text-slate-500 hover:text-white hover:bg-white/5 transition-all uppercase tracking-wider">
                    Cancelar
                  </button>
                  <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }} type="submit" disabled={saving}
                    className="flex-[2] bg-[#00d2ff] text-black py-4 rounded-2xl font-black uppercase tracking-widest text-sm flex items-center justify-center gap-3 disabled:opacity-50">
                    {saving ? <><Loader2 className="w-5 h-5 animate-spin" />Salvando...</>
                      : success ? <><CheckCircle2 className="w-5 h-5" />Salvo!</>
                      : <><Save className="w-5 h-5" />{editingFaq ? "Salvar Alterações" : "Ativar Conhecimento"}</>}
                  </motion.button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
