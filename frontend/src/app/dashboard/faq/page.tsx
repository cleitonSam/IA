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

  // Form State
  const [formData, setFormData] = useState<FAQItem>({
    pergunta: "",
    resposta: "",
    unidade_id: null,
    todas_unidades: true,
    prioridade: 0,
    ativo: true,
  });

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const token = localStorage.getItem("token");
      const config = { headers: { Authorization: `Bearer ${token}` } };
      const [faqRes, unitRes] = await Promise.all([
        axios.get("/api-backend/management/faq", config),
        axios.get("/api-backend/dashboard/unidades", config),
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
    try {
      const token = localStorage.getItem("token");
      const config = { headers: { Authorization: `Bearer ${token}` } };
      if (editingFaq) {
        await axios.put(`/api-backend/management/faq/${editingFaq.id}`, formData, config);
      } else {
        await axios.post("/api-backend/management/faq", formData, config);
      }
      setIsModalOpen(false);
      fetchData();
    } catch (error) {
      alert("Erro ao salvar FAQ");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Tem certeza que deseja excluir esta pergunta?")) return;
    try {
      const token = localStorage.getItem("token");
      await axios.delete(`/api-backend/management/faq/${id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
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
            <a href="/dashboard" className="p-2 hover:bg-white/5 rounded-full transition-colors">
              <ArrowLeft className="w-5 h-5" />
            </a>
            <div>
              <h1 className="text-3xl font-bold flex items-center gap-3">
                <HelpCircle className="w-8 h-8 text-blue-500" />
                Central de FAQ
              </h1>
              <p className="text-gray-400 mt-1">Gerencie a base de conhecimento da sua IA.</p>
            </div>
          </div>
          <button
            onClick={() => handleOpenModal()}
            className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-3 rounded-xl font-bold flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
          >
            <Plus className="w-5 h-5" />
            Adicionar Pergunta
          </button>
        </div>

        <div className="grid grid-cols-1 gap-4">
          {faqs.length === 0 ? (
            <div className="text-center py-20 bg-white/5 border border-dashed border-white/10 rounded-2xl">
              <HelpCircle className="w-12 h-12 text-gray-600 mx-auto mb-4" />
              <p className="text-gray-400">Nenhuma pergunta cadastrada ainda.</p>
            </div>
          ) : (
            faqs.map((faq) => (
              <motion.div
                layout
                key={faq.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="bg-white/5 border border-white/10 rounded-2xl p-6 flex flex-col md:flex-row gap-6 md:items-center justify-between"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-2">
                    {faq.todas_unidades ? (
                      <span className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider bg-blue-500/10 text-blue-400 px-2 py-0.5 rounded-full">
                        <Globe className="w-3 h-3" /> Todas as Unidades
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider bg-purple-500/10 text-purple-400 px-2 py-0.5 rounded-full">
                        <Building2 className="w-3 h-3" /> Unidade Específica
                      </span>
                    )}
                    <span className="text-[10px] font-bold uppercase tracking-wider bg-white/5 text-gray-400 px-2 py-0.5 rounded-full">
                      Prioridade {faq.prioridade}
                    </span>
                  </div>
                  <h3 className="text-lg font-semibold text-white mb-2">{faq.pergunta}</h3>
                  <p className="text-gray-400 text-sm line-clamp-2">{faq.resposta}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleOpenModal(faq)}
                    className="p-3 hover:bg-white/5 text-gray-400 hover:text-white rounded-xl transition-all"
                  >
                    <Edit2 className="w-5 h-5" />
                  </button>
                  <button
                    onClick={() => handleDelete(faq.id!)}
                    className="p-3 hover:bg-red-500/10 text-gray-400 hover:text-red-500 rounded-xl transition-all"
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
              className="absolute inset-0 bg-black/80 backdrop-blur-sm"
              onClick={() => setIsModalOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="bg-[#111] border border-white/10 rounded-2xl w-full max-w-2xl overflow-hidden relative"
            >
              <div className="p-6 border-b border-white/10 flex items-center justify-between">
                <h2 className="text-xl font-bold">{editingFaq ? "Editar Pergunta" : "Nova Pergunta"}</h2>
                <button onClick={() => setIsModalOpen(false)} className="p-2 hover:bg-white/5 rounded-full transition-colors">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <form onSubmit={handleSave} className="p-6 space-y-6">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">Pergunta</label>
                  <input
                    required
                    type="text"
                    value={formData.pergunta}
                    onChange={(e) => setFormData({ ...formData, pergunta: e.target.value })}
                    placeholder="Ex: Quais os horários de funcionamento?"
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">Resposta</label>
                  <textarea
                    required
                    value={formData.resposta}
                    onChange={(e) => setFormData({ ...formData, resposta: e.target.value })}
                    rows={4}
                    placeholder="Escreva a resposta que a IA deve fornecer..."
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all resize-none"
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-2">Abrangência</label>
                    <div className="flex p-1 bg-black/40 border border-white/10 rounded-xl">
                      <button
                        type="button"
                        onClick={() => setFormData({ ...formData, todas_unidades: true, unidade_id: null })}
                        className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all ${
                          formData.todas_unidades ? "bg-blue-600 text-white shadow-lg" : "text-gray-500 hover:text-white"
                        }`}
                      >
                        Global
                      </button>
                      <button
                        type="button"
                        onClick={() => setFormData({ ...formData, todas_unidades: false })}
                        className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all ${
                          !formData.todas_unidades ? "bg-blue-600 text-white shadow-lg" : "text-gray-500 hover:text-white"
                        }`}
                      >
                        Unidade
                      </button>
                    </div>
                  </div>

                  {!formData.todas_unidades && (
                    <div>
                      <label className="block text-sm font-medium text-gray-400 mb-2">Selecionar Unidade</label>
                      <select
                        required={!formData.todas_unidades}
                        value={formData.unidade_id || ""}
                        onChange={(e) => setFormData({ ...formData, unidade_id: parseInt(e.target.value) })}
                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
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

                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-2">Prioridade (0-100)</label>
                    <input
                      type="number"
                      value={formData.prioridade}
                      onChange={(e) => setFormData({ ...formData, prioridade: parseInt(e.target.value) })}
                      className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                    />
                  </div>
                </div>

                <div className="pt-4 flex gap-3">
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="flex-1 bg-white/5 hover:bg-white/10 text-white px-6 py-4 rounded-xl font-bold transition-all"
                  >
                    Cancelar
                  </button>
                  <button
                    type="submit"
                    disabled={saving}
                    className="flex-[2] bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 text-white px-6 py-4 rounded-xl font-bold flex items-center justify-center gap-2 transition-all hover:scale-[1.01] active:scale-[0.99]"
                  >
                    {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
                    {editingFaq ? "Salvar Alterações" : "Criar FAQ"}
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
