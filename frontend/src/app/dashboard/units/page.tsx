"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { 
  Building2, Plus, Pencil, Trash2, Save, X, Loader2, ArrowLeft, 
  CheckCircle2, MapPin, Phone, Globe, Instagram, Clock, 
  Dumbbell, CreditCard, Shield, Settings2, Info, Layout, 
  Sparkles, Layers, ListChecks, HeartHandshake, Eye
} from "lucide-react";
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
  horarios?: string;
  modalidades?: string;
  planos?: any;
  formas_pagamento?: any;
  convenios?: any;
  infraestrutura?: any;
  servicos?: any;
  palavras_chave?: string[];
}

type TabType = "identity" | "location" | "contact" | "operation" | "extra";

export default function UnitsPage() {
  const [units, setUnits] = useState<Unit[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingUnit, setEditingUnit] = useState<Unit | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>("identity");
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);

  const [formData, setFormData] = useState<any>({
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
    horarios: "",
    modalidades: "",
    planos: {},
    formas_pagamento: {},
    convenios: {},
    infraestrutura: {},
    servicos: {},
    palavras_chave: [],
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
        horarios: unit.horarios || "",
        modalidades: unit.modalidades || "",
        planos: unit.planos || {},
        formas_pagamento: unit.formas_pagamento || {},
        convenios: unit.convenios || {},
        infraestrutura: unit.infraestrutura || {},
        servicos: unit.servicos || {},
        palavras_chave: unit.palavras_chave || [],
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
        horarios: "",
        modalidades: "",
        planos: {},
        formas_pagamento: {},
        convenios: {},
        infraestrutura: {},
        servicos: {},
        palavras_chave: [],
      });
    }
    setActiveTab("identity");
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

  const TabButton = ({ id, label, icon: Icon }: { id: TabType, label: string, icon: any }) => (
    <button
      type="button"
      onClick={() => setActiveTab(id)}
      className={`flex items-center gap-2 px-4 py-3 rounded-xl text-xs font-bold uppercase tracking-wider transition-all duration-300 ${
        activeTab === id 
          ? "bg-primary/20 text-primary border border-primary/30 shadow-[0_0_15px_rgba(0,210,255,0.1)]" 
          : "text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent"
      }`}
    >
      <Icon className="w-4 h-4" />
      {label}
    </button>
  );

  if (loading) {
    return (
      <div className="min-h-screen bg-[#020617] flex items-center justify-center">
        <div className="flex flex-col items-center gap-6">
          <div className="relative w-20 h-20">
            <div className="absolute inset-0 rounded-full border-2 border-primary/10 animate-ping" />
            <div className="absolute inset-0 rounded-full border-2 border-t-primary animate-spin" />
            <Building2 className="absolute inset-0 m-auto w-8 h-8 text-primary neon-glow" />
          </div>
          <p className="text-primary/60 font-medium tracking-[0.2em] uppercase animate-pulse">Sincronizando Filiais...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-mesh text-slate-100 p-6 md:p-12 relative overflow-hidden">
      {/* Decorative background elements */}
      <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/5 rounded-full blur-[120px] -mr-64 -mt-64" />
      <div className="absolute bottom-0 left-0 w-[500px] h-[500px] bg-primary/5 rounded-full blur-[120px] -ml-64 -mb-64" />

      <div className="max-w-7xl mx-auto relative z-10">
        {/* Header Section */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-8 mb-16">
          <div className="flex items-center gap-6">
            <motion.a 
              href="/dashboard" 
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className="p-4 bg-slate-900/50 hover:bg-primary/10 rounded-2xl transition-all border border-white/5 hover:border-primary/20 group backdrop-blur-xl"
            >
              <ArrowLeft className="w-5 h-5 group-hover:text-primary transition-colors text-slate-400" />
            </motion.a>
            <div>
              <div className="flex items-center gap-3 mb-2">
                <div className="w-1.5 h-6 bg-primary rounded-full" />
                <span className="text-[10px] font-black text-primary uppercase tracking-[0.4em]">Fluxo Digital & Tech</span>
              </div>
              <h1 className="text-5xl font-black tracking-tight">
                <span className="text-gradient">Gestão de Unidades</span>
              </h1>
              <p className="text-slate-500 mt-2 font-medium max-w-xl italic">
                Centralize o controle operacional e informações estratégicas de todas as suas unidades em uma interface premium.
              </p>
            </div>
          </div>
          
          <motion.button
            whileHover={{ scale: 1.02, boxShadow: "0 0 30px rgba(0,210,255,0.3)" }}
            whileTap={{ scale: 0.98 }}
            onClick={() => handleOpenModal()}
            className="bg-primary text-black px-10 py-5 rounded-2xl font-black uppercase tracking-widest text-sm flex items-center justify-center gap-3 transition-all min-w-[240px]"
          >
            <Plus className="w-6 h-6" />
            Nova Unidade
          </motion.button>
        </div>

        {/* Units Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-8">
          <AnimatePresence mode="popLayout">
            {units.length === 0 ? (
              <motion.div 
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="col-span-full text-center py-40 glass rounded-[3rem] border border-white/5"
              >
                <div className="w-24 h-24 bg-primary/5 rounded-3xl flex items-center justify-center mx-auto mb-8 border border-primary/10">
                  <Building2 className="w-12 h-12 text-primary/40" />
                </div>
                <p className="text-slate-400 font-black uppercase tracking-[0.25em] text-lg">Sem unidades ativas</p>
                <p className="text-slate-600 text-sm mt-3 max-w-sm mx-auto">Sua operação ainda não possui filiais cadastradas. Comece adicionando sua unidade principal.</p>
              </motion.div>
            ) : (
              units.map((unit, i) => (
                <motion.div
                  layout
                  key={unit.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className="glass-card rounded-[2.5rem] p-4 group relative overflow-hidden flex flex-col h-full bg-slate-900/40 border border-white/5 hover:border-primary/30 transition-all duration-500"
                >
                  <div className="p-4 flex-1">
                    <div className="flex justify-between items-start mb-8">
                      <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary group-hover:scale-110 transition-transform duration-500 shadow-[0_0_15px_rgba(0,210,255,0.1)]">
                        <Building2 className="w-7 h-7" />
                      </div>
                      
                      <div className="flex gap-2">
                        <motion.button
                          whileHover={{ scale: 1.1 }}
                          whileTap={{ scale: 0.9 }}
                          onClick={() => handleOpenModal(unit)}
                          className="p-3 bg-white/5 hover:bg-primary/20 rounded-xl text-slate-400 hover:text-primary transition-all border border-white/5 hover:border-primary/20"
                        >
                          <Pencil className="w-5 h-5" />
                        </motion.button>
                        <motion.button
                          whileHover={{ scale: 1.1 }}
                          whileTap={{ scale: 0.9 }}
                          onClick={() => handleDelete(unit.id)}
                          className="p-3 bg-white/5 hover:bg-red-500/20 rounded-xl text-slate-400 hover:text-red-500 transition-all border border-white/5 hover:border-red-500/20"
                        >
                          <Trash2 className="w-5 h-5" />
                        </motion.button>
                      </div>
                    </div>

                    <h3 className="text-2xl font-black mb-1 group-hover:text-primary transition-colors uppercase tracking-tight leading-tight">{unit.nome}</h3>
                    <div className="flex items-center gap-2 mb-8">
                      <span className="w-2 h-2 rounded-full bg-primary animate-pulse shadow-[0_0_8px_#00d2ff]" />
                      <p className="text-[10px] font-black text-slate-500 uppercase tracking-[0.3em]">{unit.nome_abreviado || "Unidade Fluxo Digital"}</p>
                    </div>
                    
                    <div className="space-y-4 pt-6 mt-auto border-t border-white/5">
                      <div className="flex items-center gap-4 text-xs font-medium text-slate-400">
                        <div className="p-2.5 rounded-xl bg-slate-800/50 border border-white/5"><MapPin className="w-4 h-4 text-primary/50" /></div>
                        <span className="line-clamp-1">{unit.endereco ? `${unit.endereco}, ${unit.numero}` : `${unit.cidade}, ${unit.estado}`}</span>
                      </div>
                      
                      <div className="grid grid-cols-2 gap-3">
                        {unit.whatsapp && (
                          <div className="flex items-center gap-3 text-[10px] font-bold text-slate-400 p-3 rounded-2xl bg-white/5 border border-white/5">
                            <Phone className="w-4 h-4 text-primary/40 shrink-0" />
                            <span className="truncate">{unit.whatsapp}</span>
                          </div>
                        )}
                        {unit.instagram && (
                          <div className="flex items-center gap-3 text-[10px] font-bold text-slate-400 p-3 rounded-2xl bg-white/5 border border-white/5">
                            <Instagram className="w-4 h-4 text-primary/40 shrink-0" />
                            <span className="truncate">{unit.instagram}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 p-4 pt-0">
                    <motion.button
                      whileHover={{ x: 5 }}
                      onClick={() => handleOpenModal(unit)}
                      className="w-full bg-slate-800/80 hover:bg-primary/10 border border-white/5 hover:border-primary/30 rounded-2xl py-4 text-[10px] font-black uppercase tracking-[0.2em] text-slate-400 hover:text-primary transition-all flex items-center justify-center gap-3 group/btn"
                    >
                      <Eye className="w-4 h-4" />
                      Ver todos os dados
                      <Plus className="w-4 h-4 opacity-0 group-hover/btn:opacity-100 transition-opacity" />
                    </motion.button>
                  </div>
                </motion.div>
              ))
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Modern Sectioned Modal */}
      <AnimatePresence>
        {isModalOpen && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 bg-[#020617]/95 backdrop-blur-2xl"
              onClick={() => setIsModalOpen(false)}
            />
            
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 30 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 30 }}
              className="bg-slate-950 border border-white/10 rounded-[3rem] w-full max-w-5xl overflow-hidden relative shadow-[0_0_100px_rgba(0,0,0,0.5)] flex flex-col max-h-[90vh]"
            >
              {/* Modal Header */}
              <div className="px-12 py-10 border-b border-white/5 flex items-center justify-between bg-slate-900/40 relative">
                <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-primary-500/50 to-transparent" />
                <div className="flex items-center gap-6">
                  <div className="w-20 h-20 rounded-3xl bg-primary/10 flex items-center justify-center border border-primary/20 shadow-neon-primary-sm">
                    {editingUnit ? <Settings2 className="w-10 h-10 text-primary" /> : <Plus className="w-10 h-10 text-primary" />}
                  </div>
                  <div>
                    <div className="flex items-center gap-3 mb-1">
                      <Sparkles className="w-4 h-4 text-primary animate-pulse" />
                      <h2 className="text-3xl font-black tracking-tight">
                        {editingUnit ? "Configuração de Unidade" : "Nova Unidade do Fluxo"}
                      </h2>
                    </div>
                    <p className="text-slate-500 text-sm font-medium">Sincronize os dados técnicos, operacionais e de marketing da sua filial.</p>
                  </div>
                </div>
                <motion.button 
                  whileHover={{ rotate: 90, scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                  type="button" 
                  onClick={() => setIsModalOpen(false)} 
                  className="p-4 hover:bg-white/5 rounded-2xl transition-all border border-white/5 text-slate-500 hover:text-white"
                >
                  <X className="w-8 h-8" />
                </motion.button>
              </div>

              {/* Modal Tabs Navigation */}
              <div className="px-12 py-4 bg-slate-900/20 border-b border-white/5 flex gap-4 overflow-x-auto no-scrollbar">
                <TabButton id="identity" label="Identidade" icon={Building2} />
                <TabButton id="location" label="Localização" icon={MapPin} />
                <TabButton id="contact" label="Digital & Social" icon={Globe} />
                <TabButton id="operation" label="Operação" icon={Clock} />
                <TabButton id="extra" label="Conteúdo Rico" icon={Layout} />
              </div>

              {/* Modal Content */}
              <div className="flex-1 overflow-y-auto p-12 custom-scrollbar relative">
                <form id="unitForm" onSubmit={handleSave} className="space-y-12">
                  
                  {/* TAB: IDENTITY */}
                  {activeTab === "identity" && (
                    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-10">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
                        <div className="space-y-4">
                          <label className="flex items-center gap-2 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1">
                            <Info className="w-3.5 h-3.5 text-primary/60" /> Nome Oficial da Unidade
                          </label>
                          <input
                            type="text"
                            required
                            value={formData.nome || ""}
                            onChange={(e) => setFormData({ ...formData, nome: e.target.value })}
                            className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-2xl px-8 py-5 focus:outline-none focus:border-primary/50 transition-all font-black text-lg"
                            placeholder="Ex: Red Fitness Tatuapé"
                          />
                        </div>
                        <div className="space-y-4">
                          <label className="flex items-center gap-2 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1">
                            <Layers className="w-3.5 h-3.5 text-primary/60" /> Nome Curto / Exibição
                          </label>
                          <input
                            type="text"
                            value={formData.nome_abreviado || ""}
                            onChange={(e) => setFormData({ ...formData, nome_abreviado: e.target.value })}
                            className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-2xl px-8 py-5 focus:outline-none focus:border-primary/50 transition-all font-bold"
                            placeholder="Ex: Tatuapé"
                          />
                        </div>
                      </div>
                      <div className="bg-primary/5 border border-primary/10 rounded-3xl p-8 flex items-start gap-6">
                        <div className="p-3 bg-primary/10 rounded-2xl"><Sparkles className="w-6 h-6 text-primary" /></div>
                        <div>
                          <h4 className="font-bold text-slate-200 mb-1">Dica de Identidade</h4>
                          <p className="text-sm text-slate-500 leading-relaxed">
                            O nome oficial será usado em contratos e comunicações formais da IA. O nome curto é ideal para layouts compactos no painel principal.
                          </p>
                        </div>
                      </div>
                    </motion.div>
                  )}

                  {/* TAB: LOCATION */}
                  {activeTab === "location" && (
                    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-10">
                      <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
                        <div className="md:col-span-3 space-y-4">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1">Logradouro / Avenida / Rua</label>
                          <input
                            type="text"
                            value={formData.endereco || ""}
                            onChange={(e) => setFormData({ ...formData, endereco: e.target.value })}
                            className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-2xl px-8 py-5 focus:outline-none focus:border-primary/50 transition-all font-bold"
                          />
                        </div>
                        <div className="space-y-4">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1 text-center block">Número</label>
                          <input
                            type="text"
                            value={formData.numero || ""}
                            onChange={(e) => setFormData({ ...formData, numero: e.target.value })}
                            className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-2xl px-8 py-5 focus:outline-none focus:border-primary/50 transition-all font-black text-center"
                          />
                        </div>
                        <div className="md:col-span-2 space-y-4">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1">Bairro</label>
                          <input
                            type="text"
                            value={formData.bairro || ""}
                            onChange={(e) => setFormData({ ...formData, bairro: e.target.value })}
                            className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-2xl px-8 py-5 focus:outline-none focus:border-primary/50 transition-all font-bold"
                          />
                        </div>
                        <div className="space-y-4">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1">Cidade</label>
                          <input
                            type="text"
                            value={formData.cidade || ""}
                            onChange={(e) => setFormData({ ...formData, cidade: e.target.value })}
                            className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-2xl px-8 py-5 focus:outline-none focus:border-primary/50 transition-all font-bold"
                          />
                        </div>
                        <div className="space-y-4">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1 text-center block">UF</label>
                          <input
                            type="text"
                            maxLength={2}
                            value={formData.estado || ""}
                            onChange={(e) => setFormData({ ...formData, estado: e.target.toUpperCase() })}
                            className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-2xl px-8 py-5 focus:outline-none focus:border-primary/50 transition-all font-black text-center uppercase"
                            placeholder="SP"
                          />
                        </div>
                      </div>
                    </motion.div>
                  )}

                  {/* TAB: CONTACT */}
                  {activeTab === "contact" && (
                    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-8">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <div className="space-y-4">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1">WhatsApp de Atendimento</label>
                          <div className="relative group">
                            <Phone className="absolute left-6 top-1/2 -translate-y-1/2 w-5 h-5 text-primary/50 group-focus-within:text-primary transition-colors" />
                            <input
                              type="text"
                              value={formData.whatsapp || ""}
                              onChange={(e) => setFormData({ ...formData, whatsapp: e.target.value })}
                              className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-2xl pl-16 pr-8 py-5 focus:outline-none focus:border-primary/50 transition-all font-black tracking-widest"
                              placeholder="(00) 00000-0000"
                            />
                          </div>
                        </div>
                        <div className="space-y-4">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1">Instagram (@usuario)</label>
                          <div className="relative group">
                            <Instagram className="absolute left-6 top-1/2 -translate-y-1/2 w-5 h-5 text-primary/50 group-focus-within:text-primary transition-colors" />
                            <input
                              type="text"
                              value={formData.instagram || ""}
                              onChange={(e) => setFormData({ ...formData, instagram: e.target.value })}
                              className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-2xl pl-16 pr-8 py-5 focus:outline-none focus:border-primary/50 transition-all font-bold"
                              placeholder="redfitness_oficial"
                            />
                          </div>
                        </div>
                        <div className="space-y-4">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1">Website Oficial (URL)</label>
                          <div className="relative group">
                            <Globe className="absolute left-6 top-1/2 -translate-y-1/2 w-5 h-5 text-primary/50 group-focus-within:text-primary transition-colors" />
                            <input
                              type="text"
                              value={formData.site || ""}
                              onChange={(e) => setFormData({ ...formData, site: e.target.value })}
                              className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-2xl pl-16 pr-8 py-5 focus:outline-none focus:border-primary/50 transition-all font-bold"
                              placeholder="https://suaempresa.com.br"
                            />
                          </div>
                        </div>
                        <div className="space-y-4">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1">Link Direto para Matrícula/LP</label>
                          <div className="relative group">
                            <Sparkles className="absolute left-6 top-1/2 -translate-y-1/2 w-5 h-5 text-primary/50 group-focus-within:text-primary transition-colors" />
                            <input
                              type="text"
                              value={formData.link_matricula || ""}
                              onChange={(e) => setFormData({ ...formData, link_matricula: e.target.value })}
                              className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-2xl pl-16 pr-8 py-5 focus:outline-none focus:border-primary/50 transition-all font-bold"
                              placeholder="https://linkdetransformacao.com"
                            />
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}

                  {/* TAB: OPERATION */}
                  {activeTab === "operation" && (
                    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-10">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
                        <div className="space-y-4">
                          <label className="flex items-center gap-2 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1">
                            <Clock className="w-4 h-4 text-primary/60" /> Cronograma de Funcionamento
                          </label>
                          <textarea
                            value={formData.horarios || ""}
                            onChange={(e) => setFormData({ ...formData, horarios: e.target.value })}
                            rows={6}
                            className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-[2rem] px-8 py-6 focus:outline-none focus:border-primary/50 transition-all font-medium text-sm leading-relaxed custom-scrollbar"
                            placeholder="Seg-Sex: 06h às 23h&#10;Sáb: 09h às 17h&#10;Dom: 09h às 13h"
                          />
                        </div>
                        <div className="space-y-4">
                          <label className="flex items-center gap-2 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-1">
                            <Dumbbell className="w-4 h-4 text-primary/60" /> Modalidades & Especialidades
                          </label>
                          <textarea
                            value={formData.modalidades || ""}
                            onChange={(e) => setFormData({ ...formData, modalidades: e.target.value })}
                            rows={6}
                            className="elite-input w-full bg-slate-900/50 border border-white/10 rounded-[2rem] px-8 py-6 focus:outline-none focus:border-primary/50 transition-all font-medium text-sm leading-relaxed custom-scrollbar"
                            placeholder="Musculação, CrossFit, Pilates, Lutas, Natação..."
                          />
                        </div>
                      </div>
                    </motion.div>
                  )}

                  {/* TAB: EXTRA */}
                  {activeTab === "extra" && (
                    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-12 pb-10">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
                        <div className="space-y-6">
                          <div className="flex items-center gap-4 text-primary mb-4">
                            <ListChecks className="w-6 h-6" />
                            <h4 className="font-black uppercase tracking-widest text-sm">Planos & Preços (JSON)</h4>
                          </div>
                          <textarea
                            value={typeof formData.planos === 'object' ? JSON.stringify(formData.planos, null, 2) : formData.planos}
                            onChange={(e) => {
                              try { setFormData({ ...formData, planos: JSON.parse(e.target.value) }); }
                              catch { setFormData({ ...formData, planos: e.target.value }); }
                            }}
                            rows={6}
                            className="elite-input w-full bg-slate-900/30 border border-white/5 rounded-3xl px-6 py-4 font-mono text-xs text-primary/80 custom-scrollbar"
                            placeholder='{ "Basico": 99.90 }'
                          />
                        </div>

                        <div className="space-y-6">
                          <div className="flex items-center gap-4 text-primary mb-4">
                            <CreditCard className="w-6 h-6" />
                            <h4 className="font-black uppercase tracking-widest text-sm">Pagamento & Convênios</h4>
                          </div>
                          <textarea
                            value={typeof formData.formas_pagamento === 'object' ? JSON.stringify(formData.formas_pagamento, null, 2) : formData.formas_pagamento}
                            onChange={(e) => {
                              try { setFormData({ ...formData, formas_pagamento: JSON.parse(e.target.value) }); }
                              catch { setFormData({ ...formData, formas_pagamento: e.target.value }); }
                            }}
                            rows={6}
                            className="elite-input w-full bg-slate-900/30 border border-white/5 rounded-3xl px-6 py-4 font-mono text-xs text-primary/80 custom-scrollbar"
                            placeholder='{ "Cartão": true }'
                          />
                        </div>

                        <div className="space-y-6">
                          <div className="flex items-center gap-4 text-primary mb-4">
                            <Shield className="w-6 h-6" />
                            <h4 className="font-black uppercase tracking-widest text-sm">Infraestrutura & Serviços</h4>
                          </div>
                          <textarea
                            value={typeof formData.infraestrutura === 'object' ? JSON.stringify(formData.infraestrutura, null, 2) : formData.infraestrutura}
                            onChange={(e) => {
                              try { setFormData({ ...formData, infraestrutura: JSON.parse(e.target.value) }); }
                              catch { setFormData({ ...formData, infraestrutura: e.target.value }); }
                            }}
                            rows={6}
                            className="elite-input w-full bg-slate-900/30 border border-white/5 rounded-3xl px-6 py-4 font-mono text-xs text-primary/80 custom-scrollbar"
                          />
                        </div>

                        <div className="space-y-6">
                          <div className="flex items-center gap-4 text-primary mb-4">
                            <HeartHandshake className="w-6 h-6" />
                            <h4 className="font-black uppercase tracking-widest text-sm">Convênios Parceiros</h4>
                          </div>
                          <textarea
                            value={typeof formData.convenios === 'object' ? JSON.stringify(formData.convenios, null, 2) : formData.convenios}
                            onChange={(e) => {
                              try { setFormData({ ...formData, convenios: JSON.parse(e.target.value) }); }
                              catch { setFormData({ ...formData, convenios: e.target.value }); }
                            }}
                            rows={6}
                            className="elite-input w-full bg-slate-900/30 border border-white/5 rounded-3xl px-6 py-4 font-mono text-xs text-primary/80 custom-scrollbar"
                          />
                        </div>
                      </div>
                    </motion.div>
                  )}
                </form>
              </div>

              {/* Modal Footer Controls */}
              <div className="px-12 py-10 bg-slate-900/50 border-t border-white/5 flex flex-col md:flex-row items-center justify-between gap-6">
                <div className="flex items-center gap-6">
                   <div className="hidden lg:flex flex-col">
                      <span className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Status da Sincronização</span>
                      <span className="text-xs font-bold text-primary/80 flex items-center gap-2">
                         <CheckCircle2 className="w-3.5 h-3.5" /> Servidor Ativo
                      </span>
                   </div>
                </div>

                <div className="flex items-center gap-6 w-full md:w-auto">
                  <motion.button
                    whileHover={{ backgroundColor: "rgba(255,255,255,0.05)" }}
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="flex-1 md:flex-none px-10 py-5 rounded-2xl font-black uppercase tracking-widest text-xs text-slate-500 hover:text-white transition-all"
                  >
                    Descartar
                  </motion.button>
                  <motion.button
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    form="unitForm"
                    type="submit"
                    disabled={saving}
                    className="flex-1 md:flex-none bg-primary text-black px-14 py-5 rounded-2xl font-black uppercase tracking-widest text-xs flex items-center justify-center gap-3 transition-all shadow-neon-primary disabled:opacity-50"
                  >
                    {saving ? (
                      <>
                        <Loader2 className="w-5 h-5 animate-spin" />
                        Sincronizando...
                      </>
                    ) : success ? (
                      <>
                        <CheckCircle2 className="w-5 h-5" />
                        Sucesso
                      </>
                    ) : (
                      <>
                        <Save className="w-5 h-5" />
                        Salvar Configuração
                      </>
                    )}
                  </motion.button>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      <style jsx global>{`
        .text-gradient {
          background: linear-gradient(135deg, #fff 0%, #00d2ff 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }
        .bg-mesh {
          background-color: #020617;
          background-image: 
            radial-gradient(at 0% 0%, rgba(0, 210, 255, 0.05) 0px, transparent 50%),
            radial-gradient(at 100% 100%, rgba(0, 210, 255, 0.05) 0px, transparent 50%);
        }
        .neon-glow {
          filter: drop-shadow(0 0 10px rgba(0, 210, 255, 0.5));
        }
        .neon-border {
          box-shadow: 0 0 15px rgba(0, 210, 255, 0.1);
        }
        .shadow-neon-primary {
          box-shadow: 0 0 30px rgba(0, 210, 255, 0.2);
        }
        .shadow-neon-primary-sm {
          box-shadow: 0 0 15px rgba(0, 210, 255, 0.15);
        }
        .glass-card {
          backdrop-filter: blur(20px);
          box-shadow: 0 20px 40px rgba(0,0,0,0.2);
        }
        .elite-input {
          outline: none !important;
        }
        .custom-scrollbar::-webkit-scrollbar { width: 6px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0, 210, 255, 0.1); border-radius: 10px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(0, 210, 255, 0.2); }
        .no-scrollbar::-webkit-scrollbar { display: none; }
        .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
      `}</style>
    </div>
  );
}
