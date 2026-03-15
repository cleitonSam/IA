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
    setSuccess(false);
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
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-mesh text-white p-6 md:p-12">
      <div className="max-w-6xl mx-auto">
        {/* Unitary Header Structure - Standardized */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-8 mb-16">
          <div className="flex items-center gap-5">
            <a href="/dashboard" className="p-3.5 bg-white/5 hover:bg-primary/10 rounded-2xl transition-all border border-white/10 hover:border-primary/30 group">
              <ArrowLeft className="w-5 h-5 group-hover:text-primary transition-colors" />
            </a>
            <div>
              <h1 className="text-4xl font-black flex items-center gap-3">
                <Building2 className="w-10 h-10 text-primary neon-glow" />
                <span className="text-gradient">Gestão de Unidades</span>
              </h1>
              <p className="text-gray-400 mt-1 font-medium italic opacity-80">Configure os pontos de atendimento e filiais da sua operação digital.</p>
            </div>
          </div>
          
          <button
            onClick={() => handleOpenModal()}
            className="bg-primary hover:bg-primary/90 text-black px-10 py-5 rounded-[2rem] font-black uppercase tracking-widest text-sm flex items-center justify-center gap-3 transition-all hover:scale-[1.02] active:scale-[0.98] shadow-[0_0_30px_rgba(0,242,255,0.3)]"
          >
            <Plus className="w-6 h-6" />
            Nova Unidade
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {units.length === 0 ? (
            <div className="col-span-full text-center py-40 glass rounded-[3rem] border-dashed border-white/10">
              <div className="w-24 h-24 bg-white/5 rounded-full flex items-center justify-center mx-auto mb-8">
                <Building2 className="w-12 h-12 text-gray-700" />
              </div>
              <p className="text-gray-500 font-black uppercase tracking-[0.2em]">Sem filiais cadastradas</p>
              <p className="text-gray-600 text-sm mt-2">Adicione sua primeira unidade para começar a operar.</p>
            </div>
          ) : (
            units.map((unit, i) => (
              <motion.div
                layout
                key={unit.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="glass rounded-[2.5rem] p-8 hover:border-primary/40 transition-all group relative overflow-hidden"
              >
                <div className="absolute top-0 right-0 p-6 opacity-0 group-hover:opacity-100 transition-opacity flex gap-2">
                  <button
                    onClick={() => handleOpenModal(unit)}
                    className="p-3 bg-white/10 hover:bg-primary hover:text-black rounded-xl text-gray-400 transition-all shadow-lg"
                  >
                    <Pencil className="w-5 h-5" />
                  </button>
                  <button
                    onClick={() => handleDelete(unit.id)}
                    className="p-3 bg-white/10 hover:bg-red-500 hover:text-white rounded-xl text-gray-400 transition-all shadow-lg"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                </div>

                <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center text-primary mb-8 group-hover:scale-110 transition-transform neon-border">
                  <Building2 className="w-8 h-8" />
                </div>

                <h3 className="text-2xl font-black mb-1 group-hover:text-primary transition-colors uppercase tracking-tight">{unit.nome}</h3>
                <p className="text-[10px] font-black text-gray-500 mb-8 uppercase tracking-[0.2em]">{unit.nome_abreviado || "Unidade Digital"}</p>
                
                <div className="space-y-4 pt-8 border-t border-white/5 bg-gradient-to-b from-transparent to-white/[0.02] -mx-8 px-8 pb-4">
                  <div className="flex items-center gap-4 text-xs font-medium text-gray-400">
                    <div className="p-2.5 rounded-xl bg-white/5"><MapPin className="w-4 h-4 text-primary/50" /></div>
                    <span className="line-clamp-1">{unit.endereco ? `${unit.endereco}, ${unit.numero}` : `${unit.cidade}, ${unit.estado}`}</span>
                  </div>
                  {unit.whatsapp && (
                    <div className="flex items-center gap-4 text-xs font-medium text-gray-400">
                      <div className="p-2.5 rounded-xl bg-white/5"><Phone className="w-4 h-4 text-primary/50" /></div>
                      <span className="font-bold tracking-wider">{unit.whatsapp}</span>
                    </div>
                  )}
                  {unit.site && (
                    <div className="flex items-center gap-4 text-[10px] font-black uppercase tracking-widest text-primary/70 hover:text-primary transition-colors cursor-pointer group/link">
                      <div className="p-2.5 rounded-xl bg-primary/5 group-hover/link:bg-primary/10"><Globe className="w-4 h-4" /></div>
                      <span className="line-clamp-1">{unit.site.replace('https://', '')}</span>
                    </div>
                  )}
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
              className="bg-[#0a0a0a] border border-white/10 rounded-[2.5rem] w-full max-w-3xl overflow-hidden relative shadow-2xl flex flex-col max-h-[90vh]"
            >
              <form onSubmit={handleSave} className="flex flex-col h-full">
                <div className="p-10 border-b border-white/5 flex items-center justify-between bg-white/[0.01]">
                  <div>
                    <h2 className="text-3xl font-black flex items-center gap-4">
                      {editingUnit ? <Pencil className="w-8 h-8 text-primary" /> : <Plus className="w-8 h-8 text-primary" />}
                      {editingUnit ? "Editar Unidade" : "Nova Unidade"}
                    </h2>
                    <p className="text-gray-500 mt-2 text-sm font-medium">Configure os parâmetros técnicos e de contato desta filial.</p>
                  </div>
                  <button type="button" onClick={() => setIsModalOpen(false)} className="p-3 hover:bg-white/10 rounded-2xl transition-all border border-white/5">
                    <X className="w-6 h-6" />
                  </button>
                </div>

                <div className="p-10 space-y-10 overflow-y-auto custom-scrollbar blue-tint">
                  <div className="space-y-8">
                    <h4 className="text-[10px] font-black text-primary uppercase tracking-[0.3em] flex items-center gap-3">
                      <span className="w-8 h-[1px] bg-primary/30"></span> Identidade Operacional
                    </h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                      <div className="space-y-3">
                        <label className="text-[10px] font-black text-gray-500 ml-1 uppercase tracking-widest">Nome oficial *</label>
                        <input
                          type="text"
                          required
                          value={formData.nome}
                          onChange={(e) => setFormData({ ...formData, nome: e.target.value })}
                          className="w-full bg-black/40 border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-bold"
                          placeholder="Ex: Fluxo Tatuapé"
                        />
                      </div>
                      <div className="space-y-3">
                        <label className="text-[10px] font-black text-gray-500 ml-1 uppercase tracking-widest">Nome exibição (Curto)</label>
                        <input
                          type="text"
                          value={formData.nome_abreviado}
                          onChange={(e) => setFormData({ ...formData, nome_abreviado: e.target.value })}
                          className="w-full bg-black/40 border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-bold"
                          placeholder="Ex: Tatuapé"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="space-y-8">
                    <h4 className="text-[10px] font-black text-primary uppercase tracking-[0.3em] flex items-center gap-3">
                      <span className="w-8 h-[1px] bg-primary/30"></span> Geolocalização Neural
                    </h4>
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                      <div className="md:col-span-3 space-y-3">
                        <label className="text-[10px] font-black text-gray-500 ml-1 uppercase tracking-widest">Logradouro / Endereço</label>
                        <input
                          type="text"
                          value={formData.endereco}
                          onChange={(e) => setFormData({ ...formData, endereco: e.target.value })}
                          className="w-full bg-black/40 border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-bold"
                        />
                      </div>
                      <div className="space-y-3">
                        <label className="text-[10px] font-black text-gray-500 ml-1 uppercase tracking-widest">Nº</label>
                        <input
                          type="text"
                          value={formData.numero}
                          onChange={(e) => setFormData({ ...formData, numero: e.target.value })}
                          className="w-full bg-black/40 border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-bold text-center"
                        />
                      </div>
                      <div className="md:col-span-2 space-y-3">
                        <label className="text-[10px] font-black text-gray-500 ml-1 uppercase tracking-widest">Bairro</label>
                        <input
                          type="text"
                          value={formData.bairro}
                          onChange={(e) => setFormData({ ...formData, bairro: e.target.value })}
                          className="w-full bg-black/40 border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-bold"
                        />
                      </div>
                      <div className="space-y-3">
                        <label className="text-[10px] font-black text-gray-500 ml-1 uppercase tracking-widest">Cidade</label>
                        <input
                          type="text"
                          value={formData.cidade}
                          onChange={(e) => setFormData({ ...formData, cidade: e.target.value })}
                          className="w-full bg-black/40 border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-bold"
                        />
                      </div>
                      <div className="space-y-3">
                        <label className="text-[10px] font-black text-gray-500 ml-1 uppercase tracking-widest">Estado (UF)</label>
                        <input
                          type="text"
                          value={formData.estado}
                          onChange={(e) => setFormData({ ...formData, estado: e.target.value })}
                          className="w-full bg-black/40 border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-black text-center"
                          placeholder="SP"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="space-y-8 pb-4">
                    <h4 className="text-[10px] font-black text-primary uppercase tracking-[0.3em] flex items-center gap-3">
                      <span className="w-8 h-[1px] bg-primary/30"></span> Canais Digitais & Conversão
                    </h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                      <div className="space-y-3">
                        <label className="text-[10px] font-black text-gray-500 ml-1 uppercase tracking-widest">WhatsApp Business</label>
                        <div className="relative">
                          <Phone className="absolute left-6 top-1/2 -translate-y-1/2 w-4 h-4 text-primary/40" />
                          <input
                            type="text"
                            value={formData.whatsapp}
                            onChange={(e) => setFormData({ ...formData, whatsapp: e.target.value })}
                            className="w-full bg-black/40 border border-white/10 rounded-2xl pl-16 pr-6 py-4 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-bold tracking-widest"
                            placeholder="(11) 9..."
                          />
                        </div>
                      </div>
                      <div className="space-y-3">
                        <label className="text-[10px] font-black text-gray-500 ml-1 uppercase tracking-widest">Instagram @user</label>
                        <div className="relative">
                          <Instagram className="absolute left-6 top-1/2 -translate-y-1/2 w-4 h-4 text-primary/40" />
                          <input
                            type="text"
                            value={formData.instagram}
                            onChange={(e) => setFormData({ ...formData, instagram: e.target.value })}
                            className="w-full bg-black/40 border border-white/10 rounded-2xl pl-16 pr-6 py-4 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-bold"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="p-10 bg-white/[0.01] border-t border-white/5 flex justify-end gap-6">
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="px-8 py-5 rounded-2xl font-black uppercase tracking-widest text-[10px] text-gray-500 hover:text-white hover:bg-white/5 transition-all"
                  >
                    Descartar
                  </button>
                  <button
                    type="submit"
                    disabled={saving}
                    className="bg-primary hover:bg-primary/90 disabled:bg-primary/50 text-black px-12 py-5 rounded-[2rem] font-black uppercase tracking-widest text-xs flex items-center gap-3 transition-all shadow-[0_0_30px_rgba(0,242,255,0.3)] hover:scale-[1.02] active:scale-[0.98]"
                  >
                    {saving ? (
                      <Loader2 className="w-5 h-5 animate-spin" />
                    ) : success ? (
                      <CheckCircle2 className="w-5 h-5" />
                    ) : (
                      <Save className="w-5 h-5" />
                    )}
                    {saving ? "Protocolando..." : success ? "Dados Sincronizados" : "Efetivar Unidade"}
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
        .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0, 242, 255, 0.1); border-radius: 10px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(0, 242, 255, 0.2); }
      `}</style>
    </div>
  );
}
