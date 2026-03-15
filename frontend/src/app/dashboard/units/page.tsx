"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { Building2, Plus, Pencil, Trash2, Save, X, Loader2, ArrowLeft, CheckCircle2, MapPin, Phone, Globe, Instagram, Link as LinkIcon } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface Unit {
  id: number;
  nome: string;
  nome_abreviado?: string;
  cidade?: string;
  bairro?: string;
  estado?: string;
  endereco?: string;
  numero?: string;
  telefone_principal?: string;
  whatsapp?: string;
  site?: string;
  instagram?: string;
  link_matricula?: string;
  slug: string;
}

export default function UnitsPage() {
  const [units, setUnits] = useState<Unit[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingUnit, setEditingUnit] = useState<Unit | null>(null);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);

  const [formData, setFormData] = useState({
    nome: "",
    nome_abreviado: "",
    cidade: "",
    bairro: "",
    estado: "",
    endereco: "",
    numero: "",
    telefone_principal: "",
    whatsapp: "",
    site: "",
    instagram: "",
    link_matricula: "",
  });

  const getConfig = () => ({
    headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }
  });

  useEffect(() => {
    fetchUnits();
  }, []);

  const fetchUnits = async () => {
    try {
      const response = await axios.get("/api-backend/dashboard/unidades", getConfig());
      setUnits(response.data);
    } catch (error) {
      console.error("Erro ao carregar unidades:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenModal = (unit: Unit | null = null) => {
    if (unit) {
      setEditingUnit(unit);
      setFormData({
        nome: unit.nome || "",
        nome_abreviado: unit.nome_abreviado || "",
        cidade: unit.cidade || "",
        bairro: unit.bairro || "",
        estado: unit.estado || "",
        endereco: unit.endereco || "",
        numero: unit.numero || "",
        telefone_principal: unit.telefone_principal || "",
        whatsapp: unit.whatsapp || "",
        site: unit.site || "",
        instagram: unit.instagram || "",
        link_matricula: unit.link_matricula || "",
      });
    } else {
      setEditingUnit(null);
      setFormData({
        nome: "",
        nome_abreviado: "",
        cidade: "",
        bairro: "",
        estado: "",
        endereco: "",
        numero: "",
        telefone_principal: "",
        whatsapp: "",
        site: "",
        instagram: "",
        link_matricula: "",
      });
    }
    setIsModalOpen(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editingUnit) {
        await axios.put(`/api-backend/dashboard/unidades/${editingUnit.id}`, formData, getConfig());
      } else {
        await axios.post("/api-backend/dashboard/unidades", formData, getConfig());
      }
      setSuccess(true);
      setTimeout(() => {
        setSuccess(false);
        setIsModalOpen(false);
        fetchUnits();
      }, 1500);
    } catch (error) {
      console.error("Erro ao salvar unidade:", error);
      alert("Erro ao salvar alterações.");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Tem certeza que deseja desativar esta unidade?")) return;
    try {
      await axios.delete(`/api-backend/dashboard/unidades/${id}`, getConfig());
      fetchUnits();
    } catch (error) {
      console.error("Erro ao excluir:", error);
      alert("Erro ao excluir unidade.");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black text-white p-6 md:p-12">
      <div className="max-w-6xl mx-auto">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
          <div className="flex items-center gap-4">
            <a href="/dashboard" className="p-3 hover:bg-white/5 rounded-2xl transition-all border border-white/5">
              <ArrowLeft className="w-5 h-5" />
            </a>
            <div>
              <h1 className="text-3xl font-bold flex items-center gap-3">
                <Building2 className="w-8 h-8 text-blue-500" />
                Gestão de Unidades
              </h1>
              <p className="text-gray-400 mt-1">Configure as filiais e pontos de atendimento da sua empresa.</p>
            </div>
          </div>
          
          <button
            onClick={() => handleOpenModal()}
            className="bg-blue-600 hover:bg-blue-500 text-white px-8 py-4 rounded-2xl font-bold flex items-center gap-2 transition-all hover:scale-[1.02] active:scale-[0.98] shadow-xl shadow-blue-500/20"
          >
            <Plus className="w-5 h-5" />
            Nova Unidade
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {units.length === 0 ? (
            <div className="col-span-full text-center py-32 bg-white/[0.02] border border-dashed border-white/10 rounded-3xl">
              <Building2 className="w-16 h-16 text-gray-700 mx-auto mb-4" />
              <p className="text-gray-500 font-medium">Nenhuma unidade cadastrada.</p>
              <p className="text-gray-600 text-sm mt-1">Comece adicionando sua primeira filial.</p>
            </div>
          ) : (
            units.map((unit, i) => (
              <motion.div
                layout
                key={unit.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="bg-white/[0.03] border border-white/10 rounded-3xl p-7 hover:bg-white/[0.06] hover:border-blue-500/30 transition-all group relative overflow-hidden"
              >
                <div className="absolute top-0 right-0 p-4 opacity-0 group-hover:opacity-100 transition-opacity flex gap-2">
                  <button
                    onClick={() => handleOpenModal(unit)}
                    className="p-2.5 bg-white/10 hover:bg-blue-500 hover:text-white rounded-xl text-gray-400 transition-all"
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDelete(unit.id)}
                    className="p-2.5 bg-white/10 hover:bg-red-500 hover:text-white rounded-xl text-gray-400 transition-all"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                <div className="w-14 h-14 rounded-2xl bg-blue-500/10 flex items-center justify-center text-blue-500 mb-6 group-hover:scale-110 transition-transform">
                  <Building2 className="w-7 h-7" />
                </div>

                <h3 className="text-xl font-bold mb-1 group-hover:text-blue-400 transition-colors uppercase tracking-tight">{unit.nome}</h3>
                <p className="text-xs font-bold text-gray-600 mb-6 uppercase tracking-widest">{unit.nome_abreviado || "Unidade"}</p>
                
                <div className="space-y-4 pt-6 border-t border-white/5">
                  <div className="flex items-center gap-3 text-sm text-gray-400">
                    <div className="p-2 rounded-lg bg-white/5"><MapPin className="w-4 h-4 text-blue-500/50" /></div>
                    <span className="line-clamp-1">{unit.endereco ? `${unit.endereco}, ${unit.numero}` : `${unit.cidade}, ${unit.estado}`}</span>
                  </div>
                  {unit.whatsapp && (
                    <div className="flex items-center gap-3 text-sm text-gray-400">
                      <div className="p-2 rounded-lg bg-white/5"><Phone className="w-4 h-4 text-blue-500/50" /></div>
                      <span>{unit.whatsapp}</span>
                    </div>
                  )}
                  {unit.site && (
                    <div className="flex items-center gap-3 text-sm text-blue-400/80 hover:text-blue-400 transition-colors cursor-pointer">
                      <div className="p-2 rounded-lg bg-blue-500/5"><Globe className="w-4 h-4" /></div>
                      <span className="line-clamp-1 text-xs font-bold">{unit.site.replace('https://', '')}</span>
                    </div>
                  )}
                </div>
              </motion.div>
            ))
          )}
        </div>
      </div>

      {/* Modal */}
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
              initial={{ opacity: 0, scale: 0.9, y: 30 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 30 }}
              className="bg-[#0a0a0a] border border-white/10 rounded-[2.5rem] w-full max-w-3xl overflow-hidden relative shadow-2xl flex flex-col max-h-[90vh]"
            >
              <form onSubmit={handleSave} className="flex flex-col h-full">
                <div className="p-10 border-b border-white/5 flex items-center justify-between bg-white/[0.02]">
                  <div>
                    <h2 className="text-3xl font-bold flex items-center gap-4">
                      {editingUnit ? <Pencil className="w-8 h-8 text-blue-500" /> : <Plus className="w-8 h-8 text-blue-500" />}
                      {editingUnit ? "Editar Unidade" : "Nova Unidade"}
                    </h2>
                    <p className="text-gray-500 mt-2 text-sm">Preencha os dados abaixo para configurar sua unidade.</p>
                  </div>
                  <button type="button" onClick={() => setIsModalOpen(false)} className="p-3 hover:bg-white/10 rounded-2xl transition-all border border-white/5">
                    <X className="w-6 h-6" />
                  </button>
                </div>

                <div className="p-10 space-y-8 overflow-y-auto custom-scrollbar">
                  <div className="space-y-6">
                    <h4 className="text-[10px] font-black text-blue-500 uppercase tracking-[0.2em]">Informações Básicas</h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="space-y-2">
                        <label className="text-xs font-bold text-gray-500 ml-1 uppercase">Nome oficial *</label>
                        <input
                          type="text"
                          required
                          value={formData.nome}
                          onChange={(e) => setFormData({ ...formData, nome: e.target.value })}
                          className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                          placeholder="Ex: Red Fitness Tatuapé"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-bold text-gray-500 ml-1 uppercase">Nome exibição (Curto)</label>
                        <input
                          type="text"
                          value={formData.nome_abreviado}
                          onChange={(e) => setFormData({ ...formData, nome_abreviado: e.target.value })}
                          className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                          placeholder="Ex: Tatuapé"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="space-y-6">
                    <h4 className="text-[10px] font-black text-blue-500 uppercase tracking-[0.2em]">Localização</h4>
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                      <div className="md:col-span-3 space-y-2">
                        <label className="text-xs font-bold text-gray-500 ml-1 uppercase">Logradouro</label>
                        <input
                          type="text"
                          value={formData.endereco}
                          onChange={(e) => setFormData({ ...formData, endereco: e.target.value })}
                          className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                          placeholder="Ex: Av. Álvaro Ramos"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-bold text-gray-500 ml-1 uppercase">Nº</label>
                        <input
                          type="text"
                          value={formData.numero}
                          onChange={(e) => setFormData({ ...formData, numero: e.target.value })}
                          className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                          placeholder="123"
                        />
                      </div>
                      <div className="md:col-span-2 space-y-2">
                        <label className="text-xs font-bold text-gray-500 ml-1 uppercase">Bairro</label>
                        <input
                          type="text"
                          value={formData.bairro}
                          onChange={(e) => setFormData({ ...formData, bairro: e.target.value })}
                          className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-bold text-gray-500 ml-1 uppercase">Cidade</label>
                        <input
                          type="text"
                          value={formData.cidade}
                          onChange={(e) => setFormData({ ...formData, cidade: e.target.value })}
                          className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-bold text-gray-500 ml-1 uppercase">UF</label>
                        <input
                          type="text"
                          value={formData.estado}
                          onChange={(e) => setFormData({ ...formData, estado: e.target.value })}
                          className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                          placeholder="SP"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="space-y-6">
                    <h4 className="text-[10px] font-black text-blue-500 uppercase tracking-[0.2em]">Contato & Digital</h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="space-y-2">
                        <label className="text-xs font-bold text-gray-500 ml-1 uppercase">WhatsApp Principal</label>
                        <div className="relative">
                          <Phone className="absolute left-5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
                          <input
                            type="text"
                            value={formData.whatsapp}
                            onChange={(e) => setFormData({ ...formData, whatsapp: e.target.value })}
                            className="w-full bg-white/[0.03] border border-white/10 rounded-2xl pl-14 pr-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                            placeholder="(11) 99999-9999"
                          />
                        </div>
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-bold text-gray-500 ml-1 uppercase">Instagram @</label>
                        <div className="relative">
                          <Instagram className="absolute left-5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
                          <input
                            type="text"
                            value={formData.instagram}
                            onChange={(e) => setFormData({ ...formData, instagram: e.target.value })}
                            className="w-full bg-white/[0.03] border border-white/10 rounded-2xl pl-14 pr-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                          />
                        </div>
                      </div>
                      <div className="md:col-span-2 space-y-2">
                        <label className="text-xs font-bold text-gray-500 ml-1 uppercase">Link para Vendas / Matrícula</label>
                        <div className="relative">
                          <LinkIcon className="absolute left-5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
                          <input
                            type="text"
                            value={formData.link_matricula}
                            onChange={(e) => setFormData({ ...formData, link_matricula: e.target.value })}
                            className="w-full bg-white/[0.03] border border-white/10 rounded-2xl pl-14 pr-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                            placeholder="https://..."
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="p-10 bg-white/[0.02] border-t border-white/5 flex justify-end gap-5">
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="px-8 py-4 rounded-2xl font-bold text-gray-500 hover:text-white hover:bg-white/5 transition-all"
                  >
                    Descartar
                  </button>
                  <button
                    type="submit"
                    disabled={saving}
                    className="bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 text-white px-12 py-4 rounded-2xl font-bold flex items-center gap-2 transition-all shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-[0.98]"
                  >
                    {saving ? (
                      <Loader2 className="w-5 h-5 animate-spin" />
                    ) : success ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-300" />
                    ) : (
                      <Save className="w-5 h-5" />
                    )}
                    {saving ? "Processando..." : success ? "Salvamento Concluído!" : "Confirmar Unidade"}
                  </button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
      
      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar { width: 6px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.05); border-radius: 10px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.1); }
      `}</style>
    </div>
  );
}
