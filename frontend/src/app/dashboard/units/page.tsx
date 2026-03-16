"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import {
  Building2, Plus, Pencil, Trash2, Save, X, Loader2,
  CheckCircle2, MapPin, Phone, Globe, Instagram, Clock,
  Dumbbell, CreditCard, Shield, Sparkles, Layers,
  ListChecks, HeartHandshake, Eye, Settings2, Info, ImagePlus, Upload, Video
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

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
  foto_grade?: string;
  link_tour_virtual?: string;
}

type TabType = "identity" | "location" | "contact" | "operation" | "extra";

const emptyForm = {
  nome: "", nome_abreviado: "", cidade: "", bairro: "", estado: "",
  endereco: "", numero: "", telefone_principal: "", whatsapp: "",
  site: "", instagram: "", link_matricula: "", horarios: "", modalidades: "",
  planos: {}, formas_pagamento: {}, convenios: {}, infraestrutura: {}, servicos: {}, palavras_chave: [],
  foto_grade: "",
  link_tour_virtual: "",
};

export default function UnitsPage() {
  const [units, setUnits] = useState<Unit[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingUnit, setEditingUnit] = useState<Unit | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>("identity");
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [loadingUnit, setLoadingUnit] = useState(false);
  const [formData, setFormData] = useState<any>(emptyForm);

  const getConfig = () => ({
    headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }
  });

  useEffect(() => { fetchUnits(); }, []);

  const fetchUnits = async () => {
    setLoading(true);
    try {
      const res = await axios.get("/api-backend/dashboard/unidades", getConfig());
      setUnits(res.data);
    } catch (e) {
      console.error("Erro ao carregar unidades:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenModal = async (unit: Unit | null = null) => {
    setActiveTab("identity");
    if (unit) {
      setEditingUnit(unit);
      setLoadingUnit(true);
      setIsModalOpen(true);
      try {
        // Fetch full unit details from backend (includes all fields)
        const res = await axios.get(`/api-backend/dashboard/unidades/${unit.id}`, getConfig());
        const data = res.data;
        setFormData({
          nome: data.nome || "",
          nome_abreviado: data.nome_abreviado || "",
          cidade: data.cidade || "",
          bairro: data.bairro || "",
          estado: data.estado || "",
          endereco: data.endereco || "",
          numero: data.numero || "",
          telefone_principal: data.telefone_principal || "",
          whatsapp: data.whatsapp || "",
          site: data.site || "",
          instagram: data.instagram || "",
          link_matricula: data.link_matricula || "",
          horarios: data.horarios || "",
          modalidades: data.modalidades || "",
          planos: data.planos || {},
          formas_pagamento: data.formas_pagamento || {},
          convenios: data.convenios || {},
          infraestrutura: data.infraestrutura || {},
          servicos: data.servicos || {},
          palavras_chave: data.palavras_chave || [],
          foto_grade: data.foto_grade || "",
          link_tour_virtual: data.link_tour_virtual || "",
        });
      } catch (e) {
        console.error("Erro ao carregar dados da unidade:", e);
        // Fallback to list data
        setFormData({ ...emptyForm, nome: unit.nome, nome_abreviado: unit.nome_abreviado || "" });
      } finally {
        setLoadingUnit(false);
      }
    } else {
      setEditingUnit(null);
      setFormData(emptyForm);
      setIsModalOpen(true);
    }
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
      setTimeout(() => { setSuccess(false); setIsModalOpen(false); fetchUnits(); }, 1500);
    } catch (e) {
      console.error("Erro ao salvar:", e);
      alert("Erro ao salvar alterações.");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Desativar esta unidade?")) return;
    try {
      await axios.delete(`/api-backend/dashboard/unidades/${id}`, getConfig());
      fetchUnits();
      } catch (e) { alert("Erro ao desativar unidade."); }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>, fieldName: "foto_grade" | "link_tour_virtual") => {
    const file = e.target.files?.[0];
    if (!file) return;

    const formDataUpload = new FormData();
    formDataUpload.append("file", file);

    try {
      const res = await axios.post("/api-backend/dashboard/unidades/upload", formDataUpload, {
        headers: {
          ...getConfig().headers,
          "Content-Type": "multipart/form-data"
        }
      });
      setFormData({ ...formData, [fieldName]: res.data.url });
    } catch (err) {
      console.error("Erro no upload:", err);
      alert("Falha ao subir arquivo. Verifique o tamanho/formato.");
    }
  };

  const TabBtn = ({ id, label, icon: Icon }: { id: TabType; label: string; icon: any }) => (
    <button
      type="button"
      onClick={() => setActiveTab(id)}
      className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all whitespace-nowrap ${
        activeTab === id
          ? "bg-[#00d2ff]/15 text-[#00d2ff] border border-[#00d2ff]/25"
          : "text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent"
      }`}
    >
      <Icon className="w-4 h-4" />
      {label}
    </button>
  );

  const Field = ({ label, icon: Icon, children }: { label: string; icon?: any; children: React.ReactNode }) => (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-[11px] font-bold text-slate-500 uppercase tracking-widest ml-1">
        {Icon && <Icon className="w-3.5 h-3.5 text-[#00d2ff]/50" />} {label}
      </label>
      {children}
    </div>
  );

  const inputClass = "w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 focus:bg-slate-900/80 transition-all font-medium text-sm";
  const textareaClass = `${inputClass} resize-none leading-relaxed`;

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      {/* Persistent Sidebar */}
      <DashboardSidebar activePage="units" />

      {/* Main content */}
      <main className="flex-1 min-w-0 overflow-auto">
        {/* Decorative background */}
        <div className="fixed top-0 right-0 w-[600px] h-[400px] bg-[#00d2ff]/3 rounded-full blur-[120px] pointer-events-none" />

        <div className="relative z-10 p-8 lg:p-10 max-w-7xl mx-auto">
          {/* Header */}
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 mb-12">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-1.5 h-5 bg-[#00d2ff] rounded-full" />
                <span className="text-[10px] font-black text-[#00d2ff] uppercase tracking-[0.4em]">Fluxo Digital & Tech</span>
              </div>
              <h1 className="text-4xl font-black tracking-tight">
                <span style={{ background: "linear-gradient(135deg, #fff 0%, #00d2ff 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                  Gestão de Unidades
                </span>
              </h1>
              <p className="text-slate-500 mt-2 font-medium italic text-sm max-w-lg">
                Configure pontos de atendimento, horários, modalidades e canais digitais das suas filiais.
              </p>
            </div>

            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.97 }}
              onClick={() => handleOpenModal()}
              className="flex items-center gap-3 bg-[#00d2ff] text-black px-8 py-4 rounded-2xl font-black uppercase tracking-widest text-sm shadow-[0_0_25px_rgba(0,210,255,0.3)] hover:shadow-[0_0_40px_rgba(0,210,255,0.4)] transition-all min-w-[200px] justify-center"
            >
              <Plus className="w-5 h-5" />
              Nova Unidade
            </motion.button>
          </div>

          {/* Units Grid */}
          {loading ? (
            <div className="flex items-center justify-center py-40">
              <div className="flex flex-col items-center gap-5">
                <div className="relative w-16 h-16">
                  <div className="absolute inset-0 rounded-full border-2 border-[#00d2ff]/10 animate-ping" />
                  <div className="absolute inset-0 rounded-full border-2 border-t-[#00d2ff] animate-spin" />
                  <Building2 className="absolute inset-0 m-auto w-7 h-7 text-[#00d2ff]" />
                </div>
                <p className="text-slate-500 text-sm font-medium tracking-widest animate-pulse uppercase">Carregando filiais...</p>
              </div>
            </div>
          ) : units.length === 0 ? (
            <div className="text-center py-40 rounded-[3rem] border border-dashed border-white/5 bg-white/[0.01]">
              <div className="w-20 h-20 bg-[#00d2ff]/5 rounded-3xl flex items-center justify-center mx-auto mb-6 border border-[#00d2ff]/10">
                <Building2 className="w-10 h-10 text-[#00d2ff]/30" />
              </div>
              <p className="text-slate-400 font-black uppercase tracking-widest">Sem unidades ativas</p>
              <p className="text-slate-600 text-sm mt-2">Adicione sua primeira unidade para começar a operar.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              <AnimatePresence mode="popLayout">
                {units.map((unit, i) => (
                  <motion.div
                    layout
                    key={unit.id}
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05 }}
                    className="relative bg-slate-900/50 border border-white/5 hover:border-[#00d2ff]/25 rounded-3xl overflow-hidden group transition-all duration-400"
                    style={{ backdropFilter: "blur(20px)" }}
                  >
                    {/* Glow top border on hover */}
                    <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-[#00d2ff]/0 to-transparent group-hover:via-[#00d2ff]/30 transition-all duration-500" />

                    <div className="p-6">
                      <div className="flex justify-between items-start mb-6">
                        <div className="w-12 h-12 rounded-2xl bg-[#00d2ff]/10 border border-[#00d2ff]/20 flex items-center justify-center text-[#00d2ff] group-hover:scale-110 transition-transform duration-400">
                          <Building2 className="w-6 h-6" />
                        </div>
                        <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => handleOpenModal(unit)}
                            className="p-2.5 bg-white/5 hover:bg-[#00d2ff]/15 rounded-xl text-slate-400 hover:text-[#00d2ff] transition-all border border-white/5 hover:border-[#00d2ff]/20"
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleDelete(unit.id)}
                            className="p-2.5 bg-white/5 hover:bg-red-500/15 rounded-xl text-slate-400 hover:text-red-400 transition-all border border-white/5 hover:border-red-500/20"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>

                      <h3 className="text-xl font-black group-hover:text-[#00d2ff] transition-colors uppercase tracking-tight leading-tight mb-1">
                        {unit.nome}
                      </h3>
                      <div className="flex items-center gap-2 mb-5">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#00d2ff] shadow-[0_0_6px_#00d2ff]" />
                        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.25em]">
                          {unit.nome_abreviado || "Unidade"}
                        </p>
                      </div>

                      <div className="space-y-3 pt-5 border-t border-white/5">
                        {(unit.cidade || unit.estado) && (
                          <div className="flex items-center gap-3 text-xs text-slate-400">
                            <MapPin className="w-3.5 h-3.5 text-[#00d2ff]/40 shrink-0" />
                            <span className="truncate">{[unit.bairro, unit.cidade, unit.estado].filter(Boolean).join(", ")}</span>
                          </div>
                        )}
                        {unit.whatsapp && (
                          <div className="flex items-center gap-3 text-xs text-slate-400">
                            <Phone className="w-3.5 h-3.5 text-[#00d2ff]/40 shrink-0" />
                            <span className="font-bold tracking-wider">{unit.whatsapp}</span>
                          </div>
                        )}
                        {unit.instagram && (
                          <div className="flex items-center gap-3 text-xs text-slate-400">
                            <Instagram className="w-3.5 h-3.5 text-[#00d2ff]/40 shrink-0" />
                            <span>@{unit.instagram}</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <button
                      onClick={() => handleOpenModal(unit)}
                      className="w-full px-6 py-4 bg-white/[0.02] hover:bg-[#00d2ff]/5 border-t border-white/5 text-[10px] font-black uppercase tracking-[0.25em] text-slate-500 hover:text-[#00d2ff] transition-all flex items-center justify-center gap-2 group/btn"
                    >
                      <Eye className="w-4 h-4" />
                      Editar Configurações
                    </button>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
      </main>

      {/* Modal */}
      <AnimatePresence>
        {isModalOpen && (
          <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 bg-[#020617]/90 backdrop-blur-2xl"
              onClick={() => setIsModalOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 20 }}
              className="bg-[#080f1e] border border-white/10 rounded-[2.5rem] w-full max-w-4xl overflow-hidden relative shadow-2xl flex flex-col"
              style={{ maxHeight: "90vh" }}
            >
              {/* Modal Header */}
              <div className="px-10 py-8 border-b border-white/5 flex items-center justify-between bg-slate-900/30 relative flex-shrink-0">
                <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-[#00d2ff]/30 to-transparent" />
                <div className="flex items-center gap-5">
                  <div className="w-14 h-14 rounded-2xl bg-[#00d2ff]/10 flex items-center justify-center border border-[#00d2ff]/20">
                    {editingUnit ? <Settings2 className="w-7 h-7 text-[#00d2ff]" /> : <Plus className="w-7 h-7 text-[#00d2ff]" />}
                  </div>
                  <div>
                    <h2 className="text-2xl font-black tracking-tight">
                      {editingUnit ? "Editar Unidade" : "Nova Unidade"}
                    </h2>
                    <p className="text-slate-500 text-sm mt-0.5">
                      {editingUnit ? editingUnit.nome : "Configure os dados da sua nova filial"}
                    </p>
                  </div>
                </div>
                <motion.button
                  whileHover={{ rotate: 90 }}
                  onClick={() => setIsModalOpen(false)}
                  className="p-3 hover:bg-white/5 rounded-2xl transition-all border border-white/5 text-slate-500 hover:text-white"
                >
                  <X className="w-6 h-6" />
                </motion.button>
              </div>

              {/* Tabs */}
              <div className="px-10 py-4 border-b border-white/5 bg-slate-900/10 flex gap-3 overflow-x-auto no-scrollbar flex-shrink-0">
                <TabBtn id="identity" label="Identidade" icon={Building2} />
                <TabBtn id="location" label="Localização" icon={MapPin} />
                <TabBtn id="contact" label="Digital" icon={Globe} />
                <TabBtn id="operation" label="Operação" icon={Clock} />
                <TabBtn id="extra" label="Dados Ricos" icon={ListChecks} />
              </div>

              {/* Modal Body */}
              <div className="flex-1 overflow-y-auto p-10 custom-scrollbar">
                {loadingUnit ? (
                  <div className="flex items-center justify-center py-20">
                    <div className="flex flex-col items-center gap-4">
                      <Loader2 className="w-8 h-8 text-[#00d2ff] animate-spin" />
                      <p className="text-slate-500 text-sm">Carregando dados da unidade...</p>
                    </div>
                  </div>
                ) : (
                  <form id="unitForm" onSubmit={handleSave} className="space-y-8">
                    {/* TAB: IDENTITY */}
                    {activeTab === "identity" && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <Field label="Nome Oficial *" icon={Info}>
                          <input required type="text" value={formData.nome}
                            onChange={e => setFormData({ ...formData, nome: e.target.value })}
                            className={inputClass} placeholder="Ex: Red Fitness – Mandaqui" />
                        </Field>
                        <Field label="Nome Curto / Exibição" icon={Layers}>
                          <input type="text" value={formData.nome_abreviado}
                            onChange={e => setFormData({ ...formData, nome_abreviado: e.target.value })}
                            className={inputClass} placeholder="Ex: Mandaqui" />
                        </Field>
                      </div>
                    )}

                    {/* TAB: LOCATION */}
                    {activeTab === "location" && (
                      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                        <div className="md:col-span-3">
                          <Field label="Logradouro / Rua">
                            <input type="text" value={formData.endereco}
                              onChange={e => setFormData({ ...formData, endereco: e.target.value })}
                              className={inputClass} />
                          </Field>
                        </div>
                        <Field label="Nº">
                          <input type="text" value={formData.numero}
                            onChange={e => setFormData({ ...formData, numero: e.target.value })}
                            className={`${inputClass} text-center`} />
                        </Field>
                        <div className="md:col-span-2">
                          <Field label="Bairro">
                            <input type="text" value={formData.bairro}
                              onChange={e => setFormData({ ...formData, bairro: e.target.value })}
                              className={inputClass} />
                          </Field>
                        </div>
                        <Field label="Cidade">
                          <input type="text" value={formData.cidade}
                            onChange={e => setFormData({ ...formData, cidade: e.target.value })}
                            className={inputClass} />
                        </Field>
                        <Field label="UF">
                          <input type="text" maxLength={2} value={formData.estado}
                            onChange={e => setFormData({ ...formData, estado: e.target.value.toUpperCase() })}
                            className={`${inputClass} text-center uppercase`} placeholder="SP" />
                        </Field>
                      </div>
                    )}

                    {/* TAB: CONTACT */}
                    {activeTab === "contact" && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <Field label="WhatsApp Business" icon={Phone}>
                          <div className="relative">
                            <Phone className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-[#00d2ff]/40" />
                            <input type="text" value={formData.whatsapp}
                              onChange={e => setFormData({ ...formData, whatsapp: e.target.value })}
                              className={`${inputClass} pl-12`} placeholder="(11) 9..." />
                          </div>
                        </Field>
                        <Field label="Instagram @usuario" icon={Instagram}>
                          <div className="relative">
                            <Instagram className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-[#00d2ff]/40" />
                            <input type="text" value={formData.instagram}
                              onChange={e => setFormData({ ...formData, instagram: e.target.value })}
                              className={`${inputClass} pl-12`} placeholder="redfitness" />
                          </div>
                        </Field>
                        <Field label="Website (URL)" icon={Globe}>
                          <div className="relative">
                            <Globe className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-[#00d2ff]/40" />
                            <input type="text" value={formData.site}
                              onChange={e => setFormData({ ...formData, site: e.target.value })}
                              className={`${inputClass} pl-12`} placeholder="https://..." />
                          </div>
                        </Field>
                        <Field label="Link de Matrícula / LP" icon={Sparkles}>
                          <div className="relative">
                            <Sparkles className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-[#00d2ff]/40" />
                            <input type="text" value={formData.link_matricula}
                              onChange={e => setFormData({ ...formData, link_matricula: e.target.value })}
                              className={`${inputClass} pl-12`} placeholder="https://..." />
                          </div>
                        </Field>
                      </div>
                    )}

                    {/* TAB: OPERATION */}
                    {activeTab === "operation" && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <Field label="Horários de Funcionamento" icon={Clock}>
                          <textarea rows={7} value={formData.horarios}
                            onChange={e => setFormData({ ...formData, horarios: e.target.value })}
                            className={textareaClass}
                            placeholder={"Seg-Sex: 06h às 23h\nSáb: 09h às 17h\nDom: 09h às 13h"} />
                        </Field>
                        <Field label="Modalidades & Especialidades" icon={Dumbbell}>
                          <textarea rows={7} value={formData.modalidades}
                            onChange={e => setFormData({ ...formData, modalidades: e.target.value })}
                            className={textareaClass}
                            placeholder="Musculação, CrossFit, Pilates, Lutas..." />
                        </Field>

                        <div className="md:col-span-2">
                          <Field label="Grade de Aulas / Horários (Imagem)" icon={ImagePlus}>
                            <div className="flex flex-col md:flex-row gap-6 items-start">
                              <div className="flex-1 w-full">
                                <label className="flex flex-col items-center justify-center w-full h-44 bg-slate-900/40 border-2 border-dashed border-white/5 hover:border-[#00d2ff]/30 rounded-[2rem] cursor-pointer transition-all hover:bg-slate-900/60 overflow-hidden group">
                                  <div className="flex flex-col items-center justify-center pt-5 pb-6">
                                    <div className="w-12 h-12 rounded-2xl bg-[#00d2ff]/10 flex items-center justify-center mb-3 group-hover:scale-110 transition-transform">
                                      <Upload className="w-6 h-6 text-[#00d2ff]" />
                                    </div>
                                    <p className="text-xs font-bold text-slate-400 uppercase tracking-widest">Clique para subir imagem</p>
                                    <p className="text-[10px] text-slate-600 mt-1 uppercase tracking-wider">PNG, JPG ou WEBP (Max 5MB)</p>
                                  </div>
                                  <input type="file" className="hidden" accept="image/*" onChange={e => handleFileUpload(e, "foto_grade")} />
                                </label>
                              </div>
                              
                              {formData.foto_grade && (
                                <div className="w-44 h-44 rounded-[2rem] overflow-hidden border border-[#00d2ff]/20 bg-slate-900 relative group/preview">
                                  <img 
                                    src={formData.foto_grade} 
                                    alt="Preview Grade" 
                                    className="w-full h-full object-cover transition-transform duration-500 group-hover/preview:scale-110" 
                                  />
                                  <button
                                    type="button"
                                    onClick={() => setFormData({ ...formData, foto_grade: "" })}
                                    className="absolute top-3 right-3 p-2 bg-black/60 backdrop-blur-md rounded-xl text-white opacity-0 group-hover/preview:opacity-100 transition-opacity border border-white/10 hover:bg-red-500/80"
                                  >
                                    <Trash2 className="w-4 h-4" />
                                  </button>
                                  <div className="absolute inset-x-0 bottom-0 p-2 bg-gradient-to-t from-black/80 to-transparent">
                                    <p className="text-[9px] text-center font-black text-white/70 uppercase tracking-tighter">Preview Ativo</p>
                                  </div>
                                </div>
                              )}
                            </div>
                          </Field>
                        </div>

                        <div className="md:col-span-2">
                          <Field label="Tour Virtual (Vídeo / Link)" icon={Video}>
                            <div className="flex flex-col md:flex-row gap-6 items-start">
                              <div className="flex-1 w-full flex flex-col gap-4">
                                <div className="relative">
                                  <Video className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-[#00d2ff]/40" />
                                  <input type="text" value={formData.link_tour_virtual}
                                    onChange={e => setFormData({ ...formData, link_tour_virtual: e.target.value })}
                                    className={`${inputClass} pl-12`} placeholder="Cole o link do vídeo (YouTube, Vimeo ou upload direto)" />
                                </div>
                                <label className="flex flex-col items-center justify-center w-full h-24 bg-slate-900/40 border-2 border-dashed border-white/5 hover:border-[#00d2ff]/30 rounded-[1.5rem] cursor-pointer transition-all hover:bg-slate-900/60 overflow-hidden group">
                                  <div className="flex flex-col items-center justify-center py-2">
                                    <div className="w-8 h-8 rounded-xl bg-[#00d2ff]/10 flex items-center justify-center mb-1 group-hover:scale-110 transition-transform">
                                      <Upload className="w-4 h-4 text-[#00d2ff]" />
                                    </div>
                                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Ou suba um vídeo curto</p>
                                    <p className="text-[9px] text-slate-600 mt-0.5 uppercase tracking-wider">MP4 ou MOV (Max 20MB)</p>
                                  </div>
                                  <input type="file" className="hidden" accept="video/*" onChange={e => handleFileUpload(e, "link_tour_virtual")} />
                                </label>
                              </div>
                              
                              {formData.link_tour_virtual && (
                                <div className="w-44 h-44 rounded-[2rem] overflow-hidden border border-[#00d2ff]/20 bg-slate-900 relative group/preview">
                                  <div className="w-full h-full flex items-center justify-center bg-black/40">
                                    <Video className="w-12 h-12 text-[#00d2ff]/40" />
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => setFormData({ ...formData, link_tour_virtual: "" })}
                                    className="absolute top-3 right-3 p-2 bg-black/60 backdrop-blur-md rounded-xl text-white opacity-0 group-hover/preview:opacity-100 transition-opacity border border-white/10 hover:bg-red-500/80"
                                  >
                                    <Trash2 className="w-4 h-4" />
                                  </button>
                                  <div className="absolute inset-x-0 bottom-0 p-2 bg-gradient-to-t from-black/80 to-transparent">
                                    <p className="text-[9px] text-center font-black text-white/70 uppercase tracking-tighter overflow-hidden text-ellipsis whitespace-nowrap px-2">
                                      {formData.link_tour_virtual}
                                    </p>
                                  </div>
                                </div>
                              )}
                            </div>
                          </Field>
                        </div>
                      </div>
                    )}

                    {/* TAB: EXTRA */}
                    {activeTab === "extra" && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <Field label="Planos & Preços (JSON)" icon={ListChecks}>
                          <textarea rows={6} className={`${textareaClass} font-mono text-xs text-[#00d2ff]/80`}
                            value={typeof formData.planos === "object" ? JSON.stringify(formData.planos, null, 2) : formData.planos}
                            onChange={e => { try { setFormData({ ...formData, planos: JSON.parse(e.target.value) }); } catch { setFormData({ ...formData, planos: e.target.value }); } }}
                            placeholder={'{"Basico": 99.90, "Premium": 159.90}'}
                          />
                        </Field>
                        <Field label="Formas de Pagamento" icon={CreditCard}>
                          <textarea rows={6} className={`${textareaClass} font-mono text-xs text-[#00d2ff]/80`}
                            value={typeof formData.formas_pagamento === "object" ? JSON.stringify(formData.formas_pagamento, null, 2) : formData.formas_pagamento}
                            onChange={e => { try { setFormData({ ...formData, formas_pagamento: JSON.parse(e.target.value) }); } catch { setFormData({ ...formData, formas_pagamento: e.target.value }); } }}
                            placeholder={'{"Cartão": true, "Pix": true}'}
                          />
                        </Field>
                        <Field label="Infraestrutura" icon={Shield}>
                          <textarea rows={6} className={`${textareaClass} font-mono text-xs text-[#00d2ff]/80`}
                            value={typeof formData.infraestrutura === "object" ? JSON.stringify(formData.infraestrutura, null, 2) : formData.infraestrutura}
                            onChange={e => { try { setFormData({ ...formData, infraestrutura: JSON.parse(e.target.value) }); } catch { setFormData({ ...formData, infraestrutura: e.target.value }); } }}
                          />
                        </Field>
                        <Field label="Convênios Parceiros" icon={HeartHandshake}>
                          <textarea rows={6} className={`${textareaClass} font-mono text-xs text-[#00d2ff]/80`}
                            value={typeof formData.convenios === "object" ? JSON.stringify(formData.convenios, null, 2) : formData.convenios}
                            onChange={e => { try { setFormData({ ...formData, convenios: JSON.parse(e.target.value) }); } catch { setFormData({ ...formData, convenios: e.target.value }); } }}
                          />
                        </Field>
                      </div>
                    )}
                  </form>
                )}
              </div>

              {/* Footer */}
              <div className="px-10 py-7 bg-slate-900/30 border-t border-white/5 flex justify-end gap-4 flex-shrink-0">
                <button type="button" onClick={() => setIsModalOpen(false)}
                  className="px-8 py-4 rounded-2xl font-bold text-sm text-slate-500 hover:text-white hover:bg-white/5 transition-all uppercase tracking-wider">
                  Cancelar
                </button>
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  form="unitForm"
                  type="submit"
                  disabled={saving || loadingUnit}
                  className="bg-[#00d2ff] text-black px-12 py-4 rounded-2xl font-black uppercase tracking-widest text-sm flex items-center gap-3 transition-all shadow-[0_0_25px_rgba(0,210,255,0.25)] disabled:opacity-50"
                >
                  {saving ? <><Loader2 className="w-5 h-5 animate-spin" /> Salvando...</>
                    : success ? <><CheckCircle2 className="w-5 h-5" /> Salvo!</>
                    : <><Save className="w-5 h-5" /> Salvar Unidade</>}
                </motion.button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      <style jsx global>{`
        .no-scrollbar::-webkit-scrollbar { display: none; }
        .no-scrollbar { scrollbar-width: none; }
        .custom-scrollbar::-webkit-scrollbar { width: 5px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0,210,255,0.12); border-radius: 10px; }
      `}</style>
    </div>
  );
}
