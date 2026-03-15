"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { HelpCircle, Plus, Trash2, Edit2, Loader2, Save, X, CheckCircle2, ArrowLeft, Globe, Building2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface FAQItem {
  id?: number;
  pergunta: string;
  resposta: string;
  unidade_id: number | null;
  todas_unidades: boolean;
  prioridade: number;
  ativo: boolean;
}

interface Unidade {
  id: number;
  nome: string;
}

export default function FAQPage() {
  const [faqs, setFaqs] = useState<FAQItem[]>([]);
  const [unidades, setUnidades] = useState<Unidade[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingFaq, setEditingFaq] = useState<FAQItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);

  // Form State
  const [formData, setFormData] = useState<FAQItem>({
    pergunta: "",
    resposta: "",
    unidade_id: null,
    todas_unidades: true,
    prioridade: 0,
    ativo: true,
  });

  const getConfig = () => {
    const token = localStorage.getItem("token");
    return { headers: { Authorization: `Bearer ${token}` } };
  };

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [faqRes, unitRes] = await Promise.all([
        axios.get("/api-backend/management/faq", getConfig()),
        axios.get("/api-backend/dashboard/unidades", getConfig()),
      ]);
      setFaqs(faqRes.data);
      setUnidades(unitRes.data);
    } catch (error) {
      console.error("Erro ao carregar dados:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenModal = (faq: FAQItem | null = null) => {
    if (faq) {
      setEditingFaq(faq);
      setFormData(faq);
    } else {
      setEditingFaq(null);
      setFormData({
        pergunta: "",
        resposta: "",
        unidade_id: null,
        todas_unidades: true,
        prioridade: 0,
        ativo: true,
      });
    }
    setIsModalOpen(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSuccess(false);
    try {
      if (editingFaq) {
        await axios.put(`/api-backend/management/faq/${editingFaq.id}`, formData, getConfig());
      } else {
        await axios.post("/api-backend/management/faq", formData, getConfig());
      }
      setSuccess(true);
      setTimeout(() => {
        setSuccess(false);
        setIsModalOpen(false);
        fetchData();
      }, 1000);
    } catch (error) {
      alert("Erro ao salvar FAQ");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Tem certeza que deseja excluir esta pergunta?")) return;
    try {
      await axios.delete(`/api-backend/management/faq/${id}`, getConfig());
      fetchData();
    } catch (error) {
      alert("Erro ao excluir");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#050505] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#050505] text-white p-6 md:p-12">
      <div className="max-w-5xl mx-auto">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
          <div className="flex items-center gap-4">
            <a href="/dashboard" className="p-3 hover:bg-white/5 rounded-2xl transition-all border border-white/5">
              <ArrowLeft className="w-5 h-5" />
            </a>
            <div>
              <h1 className="text-3xl font-bold flex items-center gap-3">
                <HelpCircle className="w-8 h-8 text-blue-500" />
                Base de Conhecimento Neural
              </h1>
              <p className="text-gray-400 mt-1">Ensine sua IA a responder perguntas frequentes com precisão.</p>
            </div>
          </div>
          <button
            onClick={() => handleOpenModal()}
            className="bg-blue-600 hover:bg-blue-500 text-white px-8 py-4 rounded-2xl font-bold flex items-center justify-center gap-2 transition-all hover:scale-[1.02] active:scale-[0.98] shadow-xl shadow-blue-500/20"
          >
            <Plus className="w-5 h-5" />
            Nova Pergunta
          </button>
        </div>

        <div className="grid grid-cols-1 gap-4">
          {faqs.length === 0 ? (
            <div className="text-center py-32 bg-white/[0.02] border border-dashed border-white/10 rounded-[2.5rem]">
              <HelpCircle className="w-16 h-16 text-gray-700 mx-auto mb-4" />
              <p className="text-gray-500 font-medium">Nenhuma pergunta cadastrada ainda.</p>
            </div>
          ) : (
            faqs.reverse().map((faq, i) => (
              <motion.div
                layout
                key={faq.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
                className="bg-white/[0.03] border border-white/10 rounded-3xl p-7 flex flex-col md:flex-row gap-8 md:items-center justify-between group hover:bg-white/[0.06] hover:border-blue-500/30 transition-all"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-4">
                    {faq.todas_unidades ? (
                      <span className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest bg-emerald-500/10 text-emerald-400 px-3 py-1 rounded-lg">
                        <Globe className="w-3 h-3" /> Conhecimento Global
                      </span>
                    ) : (
                      <span className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest bg-violet-500/10 text-violet-400 px-3 py-1 rounded-lg">
                        <Building2 className="w-3 h-3" /> Unidade Específica
                      </span>
                    )}
                    <span className="text-[10px] font-black uppercase tracking-widest bg-white/5 text-gray-500 px-3 py-1 rounded-lg">
                      Prioridade {faq.prioridade}
                    </span>
                  </div>
                  <h3 className="text-xl font-bold text-white mb-3 group-hover:text-blue-400 transition-colors">{faq.pergunta}</h3>
                  <div className="bg-black/20 rounded-2xl p-5 border border-white/5">
                    <p className="text-gray-400 text-sm leading-relaxed">{faq.resposta}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => handleOpenModal(faq)}
                    className="p-4 bg-white/5 hover:bg-blue-500 hover:text-white rounded-2xl text-gray-500 transition-all shadow-lg"
                  >
                    <Edit2 className="w-5 h-5" />
                  </button>
                  <button
                    onClick={() => handleDelete(faq.id!)}
                    className="p-4 bg-white/5 hover:bg-red-500 hover:text-white rounded-2xl text-gray-500 transition-all shadow-lg"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                </div>
              </motion.div>
            ))
          )}
        </div>
      </div>

      {/* Modal - CRUD */}
      <AnimatePresence>
        {isModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 bg-black/90 backdrop-blur-xl"
              onClick={() => setIsModalOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="bg-[#0a0a0a] border border-white/10 rounded-[2.5rem] w-full max-w-2xl overflow-hidden relative shadow-2xl"
            >
              <div className="p-10 border-b border-white/5 flex items-center justify-between bg-white/[0.02]">
                <div>
                  <h2 className="text-2xl font-bold flex items-center gap-3">
                    {editingFaq ? <Edit2 className="w-6 h-6 text-blue-500" /> : <Plus className="w-6 h-6 text-blue-500" />}
                    {editingFaq ? "Editar Conhecimento" : "Novo Conhecimento"}
                  </h2>
                  <p className="text-sm text-gray-500 mt-1">Defina como a IA deve responder essa dúvida.</p>
                </div>
                <button onClick={() => setIsModalOpen(false)} className="p-3 hover:bg-white/10 rounded-2xl border border-white/5 transition-all">
                  <X className="w-6 h-6" />
                </button>
              </div>

              <form onSubmit={handleSave} className="p-10 space-y-8">
                <div className="space-y-6">
                  <div>
                    <label className="block text-xs font-black text-gray-500 uppercase tracking-widest mb-3 ml-1">Pergunta do Usuário</label>
                    <input
                      required
                      type="text"
                      value={formData.pergunta}
                      onChange={(e) => setFormData({ ...formData, pergunta: e.target.value })}
                      placeholder="Ex: Quais os horários de funcionamento?"
                      className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all font-medium"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-black text-gray-500 uppercase tracking-widest mb-3 ml-1">Resposta da Neural IA</label>
                    <textarea
                      required
                      value={formData.resposta}
                      onChange={(e) => setFormData({ ...formData, resposta: e.target.value })}
                      rows={5}
                      placeholder="Escreva a resposta detalhada..."
                      className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all resize-none leading-relaxed"
                    />
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    <div className="space-y-3">
                      <label className="block text-xs font-black text-gray-500 uppercase tracking-widest ml-1">Abrangência</label>
                      <div className="flex p-1.5 bg-white/[0.03] border border-white/10 rounded-2xl">
                        <button
                          type="button"
                          onClick={() => setFormData({ ...formData, todas_unidades: true, unidade_id: null })}
                          className={`flex-1 py-3 text-[10px] font-black uppercase tracking-widest rounded-xl transition-all ${
                            formData.todas_unidades ? "bg-blue-600 text-white shadow-lg" : "text-gray-500 hover:text-white"
                          }`}
                        >
                          Global
                        </button>
                        <button
                          type="button"
                          onClick={() => setFormData({ ...formData, todas_unidades: false })}
                          className={`flex-1 py-3 text-[10px] font-black uppercase tracking-widest rounded-xl transition-all ${
                            !formData.todas_unidades ? "bg-blue-600 text-white shadow-lg" : "text-gray-500 hover:text-white"
                          }`}
                        >
                          Unidade
                        </button>
                      </div>
                    </div>

                    {!formData.todas_unidades && (
                      <div className="space-y-3">
                        <label className="block text-xs font-black text-gray-500 uppercase tracking-widest ml-1">Unidade</label>
                        <select
                          required={!formData.todas_unidades}
                          value={formData.unidade_id || ""}
                          onChange={(e) => setFormData({ ...formData, unidade_id: parseInt(e.target.value) })}
                          className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-3.5 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all font-bold text-sm"
                        >
                          <option value="">Selecione...</option>
                          {unidades.map((u) => (
                            <option key={u.id} value={u.id}>
                              {u.nome}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}

                    <div className="space-y-3">
                      <label className="block text-xs font-black text-gray-500 uppercase tracking-widest ml-1">Prioridade (0-100)</label>
                      <input
                        type="number"
                        value={formData.prioridade}
                        onChange={(e) => setFormData({ ...formData, prioridade: parseInt(e.target.value) })}
                        className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-3.5 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all font-bold text-sm"
                      />
                    </div>
                  </div>
                </div>

                <div className="pt-6 flex gap-4">
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="flex-1 bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white px-6 py-5 rounded-2xl font-black uppercase tracking-widest text-[10px] transition-all"
                  >
                    Descartar
                  </button>
                  <button
                    type="submit"
                    disabled={saving}
                    className="flex-[2] bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 text-white px-6 py-5 rounded-2xl font-black uppercase tracking-widest text-[10px] flex items-center justify-center gap-3 transition-all hover:scale-[1.02] active:scale-[0.98] shadow-xl shadow-blue-500/20"
                  >
                    {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : success ? <CheckCircle2 className="w-5 h-5 text-emerald-300" /> : <Save className="w-5 h-5" />}
                    {editingFaq ? "Salvar Alterações" : "Ativar Conhecimento"}
                  </button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
