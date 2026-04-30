"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import {
  Building2, Plus, Pencil, Trash2, Save, X, Loader2,
  CheckCircle2, MapPin, Phone, Globe, Instagram, Clock,
  Dumbbell, CreditCard, Shield, Sparkles, Layers,
  ListChecks, HeartHandshake, Eye, Settings2, Info, ImagePlus, Upload, Video, Wand2
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";
import { ErrorBoundary } from "@/components/ErrorBoundary";

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
  // [PROMO-01]
  promo_ativa?: boolean;
  promo_nome?: string;
  promo_chamada?: string;
  promo_emoji?: string;
  promo_cor?: string;
  promo_validade_fim?: string | null;
}

type TabType = "identity" | "location" | "contact" | "operation" | "extra" | "promo";

// ─── Componentes de UI definidos FORA do componente principal ──────────────
// IMPORTANTE: definir dentro do componente causa remontagem a cada render,
// fazendo o input perder o foco a cada tecla digitada.

const Field = ({ label, icon: Icon, children }: { label: string; icon?: any; children: React.ReactNode }) => (
  <div className="space-y-3">
    <label className="flex items-center gap-2 text-[11px] font-bold text-slate-500 uppercase tracking-widest ml-1">
      {Icon && <Icon className="w-3.5 h-3.5 text-[#00d2ff]/50" />} {label}
    </label>
    {children}
  </div>
);

const TabBtn = ({
  id, label, icon: Icon, activeTab, setActiveTab
}: {
  id: TabType; label: string; icon: any;
  activeTab: TabType; setActiveTab: (t: TabType) => void;
}) => (
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

const emptyForm: any = {
  nome: "", nome_abreviado: "", cidade: "", bairro: "", estado: "",
  endereco: "", numero: "", telefone_principal: "", whatsapp: "",
  site: "", instagram: "", link_matricula: "", horarios: "", modalidades: "",
  planos: {}, formas_pagamento: {}, convenios: {}, infraestrutura: {}, servicos: {}, palavras_chave: [],
  foto_grade: "",
  link_tour_virtual: "",
  // [PROMO-01] Campos de promocao
  promo_ativa: false,
  promo_nome: "",
  promo_chamada: "",
  promo_desconto: null,
  promo_desconto_tipo: "percentual",
  promo_brinde: "",
  promo_validade_inicio: "",
  promo_validade_fim: "",
  promo_cor: "#ff3366",
  promo_emoji: "🔥",
  promo_observacoes: "",
};

// [BLINDAGEM] Coerce qualquer valor pra um JSON object/array seguro
// Casos cobertos: null, undefined, "", "{}", "[]", "{\"k\":1}", objeto direto, array direto
function safeParseJson<T = any>(value: any, fallback: T): T {
  if (value == null) return fallback;
  if (typeof value === "object") return value as T;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return fallback;
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed == null) return fallback;
      return parsed as T;
    } catch {
      return fallback;
    }
  }
  return fallback;
}

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
  const [extractingGrade, setExtractingGrade] = useState(false);
  const [uploadingField, setUploadingField] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);

  const getConfig = () => ({
    headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }
  });

  useEffect(() => { fetchUnits(); }, []);

  const fetchUnits = async () => {
    setLoading(true);
    try {
      const res = await axios.get("/api-backend/dashboard/unidades", getConfig());
      setUnits(Array.isArray(res.data) ? res.data : res.data?.data || []);
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
          planos: safeParseJson(data.planos, {}),
          formas_pagamento: safeParseJson(data.formas_pagamento, {}),
          convenios: safeParseJson(data.convenios, {}),
          infraestrutura: safeParseJson(data.infraestrutura, {}),
          servicos: safeParseJson(data.servicos, {}),
          palavras_chave: safeParseJson(data.palavras_chave, []),
          foto_grade: data.foto_grade || "",
          link_tour_virtual: data.link_tour_virtual || "",
          // [PROMO-01] Carrega campos de promocao
          promo_ativa: !!data.promo_ativa,
          promo_nome: data.promo_nome || "",
          promo_chamada: data.promo_chamada || "",
          promo_desconto: data.promo_desconto ?? null,
          promo_desconto_tipo: data.promo_desconto_tipo || "percentual",
          promo_brinde: data.promo_brinde || "",
          promo_validade_inicio: (data.promo_validade_inicio || "").toString().slice(0, 10),
          promo_validade_fim: (data.promo_validade_fim || "").toString().slice(0, 10),
          promo_cor: data.promo_cor || "#ff3366",
          promo_emoji: data.promo_emoji || "🔥",
          promo_observacoes: data.promo_observacoes || "",
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
      // [BLINDAGEM] Normaliza JSON antes de enviar — se user digitou string invalida no
      // textarea, mandamos {} em vez de string crua (backend espera dict/list).
      const payload = {
        ...formData,
        planos: safeParseJson(formData.planos, {}),
        formas_pagamento: safeParseJson(formData.formas_pagamento, {}),
        convenios: safeParseJson(formData.convenios, {}),
        infraestrutura: safeParseJson(formData.infraestrutura, {}),
        servicos: safeParseJson(formData.servicos, {}),
        palavras_chave: safeParseJson(formData.palavras_chave, []),
      };
      if (editingUnit) {
        await axios.put(`/api-backend/dashboard/unidades/${editingUnit.id}`, payload, getConfig());
      } else {
        await axios.post("/api-backend/dashboard/unidades", payload, getConfig());
      }
      setSuccess(true);
      setTimeout(() => { setSuccess(false); setIsModalOpen(false); fetchUnits(); }, 1500);
    } catch (err: any) {
      console.error("[unidades] Erro ao salvar:", err);
      const detalhe = err?.response?.data?.detail || err?.message || "Erro desconhecido";
      alert("Erro ao salvar alterações:\n\n" + detalhe);
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

    // Validação client-side
    const isVideo = file.type.startsWith("video/");
    const isImage = file.type.startsWith("image/");
    const maxSize = isVideo ? 100 * 1024 * 1024 : 10 * 1024 * 1024; // 100MB vídeo, 10MB imagem

    if (!isImage && !isVideo) {
      alert(`Formato não suportado: ${file.type || "desconhecido"}.\n\nFormatos aceitos:\n• Imagens: JPG, PNG, WebP\n• Vídeos: MP4, MOV`);
      return;
    }
    if (fieldName === "foto_grade" && isVideo) {
      alert("A foto da grade deve ser uma imagem (JPG, PNG).");
      return;
    }
    if (file.size > maxSize) {
      const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
      const limitMB = isVideo ? 100 : 10;
      alert(`Arquivo muito grande (${sizeMB}MB).\nO limite é ${limitMB}MB.`);
      return;
    }

    setUploadingField(fieldName);
    setUploadProgress(0);

    const formDataUpload = new FormData();
    formDataUpload.append("file", file);

    try {
      // IMPORTANTE: NÃO definir Content-Type manualmente para multipart/form-data.
      // O axios detecta FormData e adiciona automaticamente o header com o boundary correto.
      // Definir manualmente remove o boundary e quebra o parse no backend.
      const res = await axios.post("/api-backend/dashboard/unidades/upload", formDataUpload, {
        headers: {
          ...getConfig().headers,
          // Content-Type é setado automaticamente pelo axios com o boundary correto
        },
        timeout: 300000, // 5 min para vídeos grandes
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            const pct = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setUploadProgress(pct);
          }
        }
      });
      setFormData((prev: any) => ({ ...prev, [fieldName]: res.data.url }));
    } catch (err: any) {
      console.error("Erro no upload:", err);
      const detail = err?.response?.data?.detail;
      alert(detail || "Falha ao subir arquivo. Verifique o tamanho/formato e tente novamente.");
    } finally {
      setUploadingField(null);
      setUploadProgress(0);
    }
  };

  const handleExtrairGrade = async () => {
    if (!formData.foto_grade) return;
    setExtractingGrade(true);
    try {
      const res = await axios.post("/api-backend/dashboard/unidades/extrair-grade", {
        image_url: formData.foto_grade
      }, getConfig());

      if (res.data.success && res.data.modalidades) {
        setFormData((prev: any) => ({ ...prev, modalidades: res.data.modalidades }));
        // Scroll para o campo modalidades para o admin visualizar
        setTimeout(() => {
          const el = document.getElementById("modalidades-textarea");
          if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 300);
      } else {
        alert("Não foi possível extrair modalidades da imagem.");
      }
    } catch (err: any) {
      console.error("Erro na extração:", err);
      const msg = err?.response?.data?.detail || "Erro ao extrair modalidades da imagem.";
      alert(msg);
    } finally {
      setExtractingGrade(false);
    }
  };

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
                      <div className="flex items-center gap-2 mb-5 flex-wrap">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#00d2ff] shadow-[0_0_6px_#00d2ff]" />
                        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.25em]">
                          {unit.nome_abreviado || "Unidade"}
                        </p>
                        {/* [PROMO-01] Badge de promo ativa */}
                        {unit.promo_ativa && (
                          <span
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold text-white shadow-[0_0_10px_rgba(255,51,102,0.35)]"
                            style={{ backgroundColor: unit.promo_cor || "#ff3366" }}
                            title={unit.promo_chamada || ""}
                          >
                            <span className="text-xs leading-none">{unit.promo_emoji || "🔥"}</span>
                            {unit.promo_nome || "Promo"}
                          </span>
                        )}
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
                        {unit.convenios && typeof unit.convenios === "object" && (
                          <div className="flex flex-wrap gap-1.5 pt-1">
                            {unit.convenios.gympass_wellhub && unit.convenios.gympass_wellhub !== "Não aceita" && (
                              <span className="px-2.5 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px] font-bold uppercase tracking-wider">
                                GP {unit.convenios.gympass_wellhub}
                              </span>
                            )}
                            {unit.convenios.totalpass && unit.convenios.totalpass !== "Não aceita" && (
                              <span className="px-2.5 py-1 rounded-lg bg-violet-500/10 border border-violet-500/20 text-violet-400 text-[10px] font-bold uppercase tracking-wider">
                                TP {unit.convenios.totalpass}
                              </span>
                            )}
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
          <ErrorBoundary
            fallback={
              <div className="fixed inset-0 z-[200] flex items-center justify-center p-8 bg-[#020617]/95 backdrop-blur-xl">
                <div className="max-w-md text-center space-y-4 bg-slate-900 border border-red-500/30 rounded-3xl p-8">
                  <h3 className="text-xl font-black text-red-400">Erro no editor da unidade</h3>
                  <p className="text-sm text-slate-400">Ocorreu um erro inesperado neste modal. Os dados na lista NÃO foram afetados.</p>
                  <p className="text-[10px] text-slate-500 italic">Abra o Console do navegador (F12) para ver o erro detalhado e me passe.</p>
                  <button
                    onClick={() => { setIsModalOpen(false); window.location.reload(); }}
                    className="px-6 py-3 bg-cyan-600 hover:bg-cyan-500 rounded-2xl font-bold text-sm">
                    Fechar e recarregar
                  </button>
                </div>
              </div>
            }
          >
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
                <TabBtn id="identity" label="Identidade" icon={Building2} activeTab={activeTab} setActiveTab={setActiveTab} />
                <TabBtn id="location" label="Localização" icon={MapPin} activeTab={activeTab} setActiveTab={setActiveTab} />
                <TabBtn id="contact" label="Digital" icon={Globe} activeTab={activeTab} setActiveTab={setActiveTab} />
                <TabBtn id="operation" label="Operação" icon={Clock} activeTab={activeTab} setActiveTab={setActiveTab} />
                <TabBtn id="extra" label="Dados Ricos" icon={ListChecks} activeTab={activeTab} setActiveTab={setActiveTab} />
                <TabBtn id="promo" label="Promo" icon={Sparkles} activeTab={activeTab} setActiveTab={setActiveTab} />
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
                            onChange={e => setFormData((prev: any) => ({ ...prev, nome: e.target.value }))}
                            className={inputClass} placeholder="Ex: Sua Marca – Centro" />
                        </Field>
                        <Field label="Nome Curto / Exibição" icon={Layers}>
                          <input type="text" value={formData.nome_abreviado}
                            onChange={e => setFormData((prev: any) => ({ ...prev, nome_abreviado: e.target.value }))}
                            className={inputClass} placeholder="Ex: Centro" />
                        </Field>
                      </div>
                    )}

                    {/* TAB: LOCATION */}
                    {activeTab === "location" && (
                      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                        <div className="md:col-span-3">
                          <Field label="Logradouro / Rua">
                            <input type="text" value={formData.endereco}
                              onChange={e => setFormData((prev: any) => ({ ...prev, endereco: e.target.value }))}
                              className={inputClass} />
                          </Field>
                        </div>
                        <Field label="Nº">
                          <input type="text" value={formData.numero}
                            onChange={e => setFormData((prev: any) => ({ ...prev, numero: e.target.value }))}
                            className={`${inputClass} text-center`} />
                        </Field>
                        <div className="md:col-span-2">
                          <Field label="Bairro">
                            <input type="text" value={formData.bairro}
                              onChange={e => setFormData((prev: any) => ({ ...prev, bairro: e.target.value }))}
                              className={inputClass} />
                          </Field>
                        </div>
                        <Field label="Cidade">
                          <input type="text" value={formData.cidade}
                            onChange={e => setFormData((prev: any) => ({ ...prev, cidade: e.target.value }))}
                            className={inputClass} />
                        </Field>
                        <Field label="UF">
                          <input type="text" maxLength={2} value={formData.estado}
                            onChange={e => setFormData((prev: any) => ({ ...prev, estado: e.target.value.toUpperCase() }))}
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
                              onChange={e => setFormData((prev: any) => ({ ...prev, whatsapp: e.target.value }))}
                              className={`${inputClass} pl-12`} placeholder="(11) 9..." />
                          </div>
                        </Field>
                        <Field label="Instagram @usuario" icon={Instagram}>
                          <div className="relative">
                            <Instagram className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-[#00d2ff]/40" />
                            <input type="text" value={formData.instagram}
                              onChange={e => setFormData((prev: any) => ({ ...prev, instagram: e.target.value }))}
                              className={`${inputClass} pl-12`} placeholder="suamarca" />
                          </div>
                        </Field>
                        <Field label="Website (URL)" icon={Globe}>
                          <div className="relative">
                            <Globe className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-[#00d2ff]/40" />
                            <input type="text" value={formData.site}
                              onChange={e => setFormData((prev: any) => ({ ...prev, site: e.target.value }))}
                              className={`${inputClass} pl-12`} placeholder="https://..." />
                          </div>
                        </Field>
                        <Field label="Link de Matrícula / LP" icon={Sparkles}>
                          <div className="relative">
                            <Sparkles className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-[#00d2ff]/40" />
                            <input type="text" value={formData.link_matricula}
                              onChange={e => setFormData((prev: any) => ({ ...prev, link_matricula: e.target.value }))}
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
                            onChange={e => setFormData((prev: any) => ({ ...prev, horarios: e.target.value }))}
                            className={textareaClass}
                            placeholder={"Seg-Sex: 06h às 23h\nSáb: 09h às 17h\nDom: 09h às 13h"} />
                        </Field>
                        <Field label="Modalidades & Especialidades" icon={Dumbbell}>
                          <textarea id="modalidades-textarea" rows={7} value={formData.modalidades}
                            onChange={e => setFormData((prev: any) => ({ ...prev, modalidades: e.target.value }))}
                            className={textareaClass}
                            placeholder="Musculação, CrossFit, Pilates, Lutas..." />
                        </Field>

                        <div className="md:col-span-2">
                          <Field label="Grade de Aulas / Horários (Imagem)" icon={ImagePlus}>
                            <div className="flex flex-col md:flex-row gap-6 items-start">
                              <div className="flex-1 w-full">
                                <label className={`flex flex-col items-center justify-center w-full h-44 bg-slate-900/40 border-2 border-dashed ${uploadingField === "foto_grade" ? "border-[#00d2ff]/50 animate-pulse" : "border-white/5 hover:border-[#00d2ff]/30"} rounded-[2rem] ${uploadingField === "foto_grade" ? "cursor-wait pointer-events-none" : "cursor-pointer"} transition-all hover:bg-slate-900/60 overflow-hidden group`}>
                                  {uploadingField === "foto_grade" ? (
                                    <div className="flex flex-col items-center justify-center pt-5 pb-6 w-full px-6">
                                      <Loader2 className="w-10 h-10 text-[#00d2ff] animate-spin mb-3" />
                                      <p className="text-xs font-bold text-[#00d2ff] uppercase tracking-widest mb-2">Enviando imagem...</p>
                                      <div className="w-full max-w-[180px] bg-slate-800 rounded-full h-2 overflow-hidden">
                                        <div className="h-full bg-gradient-to-r from-[#00d2ff] to-[#a855f7] rounded-full transition-all duration-300 ease-out" style={{ width: `${uploadProgress}%` }} />
                                      </div>
                                      <p className="text-[10px] text-[#00d2ff]/70 mt-1.5 font-mono">{uploadProgress}%</p>
                                    </div>
                                  ) : (
                                    <div className="flex flex-col items-center justify-center pt-5 pb-6">
                                      <div className="w-12 h-12 rounded-2xl bg-[#00d2ff]/10 flex items-center justify-center mb-3 group-hover:scale-110 transition-transform">
                                        <Upload className="w-6 h-6 text-[#00d2ff]" />
                                      </div>
                                      <p className="text-xs font-bold text-slate-400 uppercase tracking-widest">Clique para subir imagem</p>
                                      <p className="text-[10px] text-slate-600 mt-1 uppercase tracking-wider">PNG, JPG ou WEBP (Max 5MB)</p>
                                    </div>
                                  )}
                                  <input type="file" className="hidden" accept="image/*" onChange={e => handleFileUpload(e, "foto_grade")} disabled={!!uploadingField} />
                                </label>
                              </div>

                              {formData.foto_grade && (
                                <div className="flex flex-col items-center gap-3">
                                  <div className="w-44 h-44 rounded-[2rem] overflow-hidden border border-[#00d2ff]/20 bg-slate-900 relative group/preview">
                                    <img
                                      src={formData.foto_grade}
                                      alt="Preview Grade"
                                      className="w-full h-full object-cover transition-transform duration-500 group-hover/preview:scale-110"
                                    />
                                    <button
                                      type="button"
                                      onClick={() => setFormData((prev: any) => ({ ...prev, foto_grade: "" }))}
                                      className="absolute top-3 right-3 p-2 bg-black/60 backdrop-blur-md rounded-xl text-white opacity-0 group-hover/preview:opacity-100 transition-opacity border border-white/10 hover:bg-red-500/80"
                                    >
                                      <Trash2 className="w-4 h-4" />
                                    </button>
                                    <div className="absolute inset-x-0 bottom-0 p-2 bg-gradient-to-t from-black/80 to-transparent">
                                      <p className="text-[9px] text-center font-black text-white/70 uppercase tracking-tighter">Preview Ativo</p>
                                    </div>
                                  </div>
                                  <button
                                    type="button"
                                    onClick={handleExtrairGrade}
                                    disabled={extractingGrade}
                                    className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-[11px] font-bold uppercase tracking-wider transition-all bg-gradient-to-r from-[#00d2ff]/20 to-[#a855f7]/20 hover:from-[#00d2ff]/30 hover:to-[#a855f7]/30 text-white border border-[#00d2ff]/30 hover:border-[#a855f7]/40 disabled:opacity-50 disabled:cursor-not-allowed"
                                    title="Usa IA para ler a imagem da grade e preencher automaticamente o campo Modalidades & Especialidades"
                                  >
                                    {extractingGrade ? (
                                      <>
                                        <Loader2 className="w-4 h-4 animate-spin" />
                                        Extraindo...
                                      </>
                                    ) : (
                                      <>
                                        <Wand2 className="w-4 h-4" />
                                        Extrair Modalidades com IA
                                      </>
                                    )}
                                  </button>
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
                                    onChange={e => setFormData((prev: any) => ({ ...prev, link_tour_virtual: e.target.value }))}
                                    className={`${inputClass} pl-12`} placeholder="Cole o link do vídeo (YouTube, Vimeo ou upload direto)" />
                                </div>
                                <label className={`flex flex-col items-center justify-center w-full ${uploadingField === "link_tour_virtual" ? "h-28" : "h-24"} bg-slate-900/40 border-2 border-dashed ${uploadingField === "link_tour_virtual" ? "border-[#00d2ff]/50 animate-pulse" : "border-white/5 hover:border-[#00d2ff]/30"} rounded-[1.5rem] ${uploadingField === "link_tour_virtual" ? "cursor-wait pointer-events-none" : "cursor-pointer"} transition-all hover:bg-slate-900/60 overflow-hidden group`}>
                                  {uploadingField === "link_tour_virtual" ? (
                                    <div className="flex flex-col items-center justify-center py-2 w-full px-6">
                                      <Loader2 className="w-7 h-7 text-[#00d2ff] animate-spin mb-2" />
                                      <p className="text-[10px] font-bold text-[#00d2ff] uppercase tracking-widest mb-1.5">Enviando vídeo...</p>
                                      <div className="w-full max-w-[240px] bg-slate-800 rounded-full h-2 overflow-hidden">
                                        <div className="h-full bg-gradient-to-r from-[#00d2ff] to-[#a855f7] rounded-full transition-all duration-300 ease-out" style={{ width: `${uploadProgress}%` }} />
                                      </div>
                                      <p className="text-[10px] text-[#00d2ff]/70 mt-1 font-mono">{uploadProgress}%</p>
                                    </div>
                                  ) : (
                                    <div className="flex flex-col items-center justify-center py-2">
                                      <div className="w-8 h-8 rounded-xl bg-[#00d2ff]/10 flex items-center justify-center mb-1 group-hover:scale-110 transition-transform">
                                        <Upload className="w-4 h-4 text-[#00d2ff]" />
                                      </div>
                                      <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Ou suba um vídeo curto</p>
                                      <p className="text-[9px] text-slate-600 mt-0.5 uppercase tracking-wider">MP4 ou MOV (Max 100MB)</p>
                                    </div>
                                  )}
                                  <input type="file" className="hidden" accept="video/*" onChange={e => handleFileUpload(e, "link_tour_virtual")} disabled={!!uploadingField} />
                                </label>
                              </div>

                              {formData.link_tour_virtual && (
                                <div className="w-44 h-44 rounded-[2rem] overflow-hidden border border-[#00d2ff]/20 bg-slate-900 relative group/preview">
                                  <div className="w-full h-full flex items-center justify-center bg-black/40">
                                    <Video className="w-12 h-12 text-[#00d2ff]/40" />
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => setFormData((prev: any) => ({ ...prev, link_tour_virtual: "" }))}
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
                            value={formData.planos == null ? "" : (typeof formData.planos === "object" ? JSON.stringify(formData.planos, null, 2) : String(formData.planos))}
                            onChange={e => { const v = e.target.value; if (!v.trim()) { setFormData((prev: any) => ({ ...prev, planos: {} })); return; } try { setFormData((prev: any) => ({ ...prev, planos: JSON.parse(v) })); } catch { setFormData((prev: any) => ({ ...prev, planos: v })); } }}
                            placeholder={'{"Basico": 99.90, "Premium": 159.90}'}
                          />
                        </Field>
                        <Field label="Formas de Pagamento" icon={CreditCard}>
                          <textarea rows={6} className={`${textareaClass} font-mono text-xs text-[#00d2ff]/80`}
                            value={formData.formas_pagamento == null ? "" : (typeof formData.formas_pagamento === "object" ? JSON.stringify(formData.formas_pagamento, null, 2) : String(formData.formas_pagamento))}
                            onChange={e => { const v = e.target.value; if (!v.trim()) { setFormData((prev: any) => ({ ...prev, formas_pagamento: {} })); return; } try { setFormData((prev: any) => ({ ...prev, formas_pagamento: JSON.parse(v) })); } catch { setFormData((prev: any) => ({ ...prev, formas_pagamento: v })); } }}
                            placeholder={'{"Cartão": true, "Pix": true}'}
                          />
                        </Field>
                        <Field label="Infraestrutura" icon={Shield}>
                          <textarea rows={6} className={`${textareaClass} font-mono text-xs text-[#00d2ff]/80`}
                            value={formData.infraestrutura == null ? "" : (typeof formData.infraestrutura === "object" ? JSON.stringify(formData.infraestrutura, null, 2) : String(formData.infraestrutura))}
                            onChange={e => { const v = e.target.value; if (!v.trim()) { setFormData((prev: any) => ({ ...prev, infraestrutura: {} })); return; } try { setFormData((prev: any) => ({ ...prev, infraestrutura: JSON.parse(v) })); } catch { setFormData((prev: any) => ({ ...prev, infraestrutura: v })); } }}
                          />
                        </Field>
                        <Field label="Convênios Parceiros" icon={HeartHandshake}>
                          <div className="space-y-4">
                            <div className="grid grid-cols-2 gap-4">
                              <div className="space-y-2">
                                <label className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Gympass / Wellhub</label>
                                <select
                                  value={(formData.convenios as any)?.gympass_wellhub || "Não aceita"}
                                  onChange={e => {
                                    const val = e.target.value;
                                    setFormData((p: any) => ({
                                      ...p,
                                      convenios: { ...(typeof p.convenios === "object" && p.convenios !== null ? p.convenios : {}), gympass_wellhub: val }
                                    }));
                                  }}
                                  className={inputClass}
                                >
                                  {["Não aceita","Basic","Basic+","Silver","Gold","Gold+","Platinum","Diamond","Black"].map(o => (
                                    <option key={o} value={o}>{o}</option>
                                  ))}
                                </select>
                              </div>
                              <div className="space-y-2">
                                <label className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Totalpass</label>
                                <select
                                  value={(formData.convenios as any)?.totalpass || "Não aceita"}
                                  onChange={e => {
                                    const val = e.target.value;
                                    setFormData((p: any) => ({
                                      ...p,
                                      convenios: { ...(typeof p.convenios === "object" && p.convenios !== null ? p.convenios : {}), totalpass: val }
                                    }));
                                  }}
                                  className={inputClass}
                                >
                                  {["Não aceita","TP1","TP1+","TP2","TP2+","TP3","TP3+"].map(o => (
                                    <option key={o} value={o}>{o}</option>
                                  ))}
                                </select>
                              </div>
                            </div>
                            <div className="space-y-2">
                              <label className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Outros convênios (Sesc, Sesi…)</label>
                              <input
                                type="text"
                                placeholder="Ex: Sesc, Sesi, Convênio Empresa XYZ"
                                value={(formData.convenios as any)?.outros || ""}
                                onChange={e => {
                                  const val = e.target.value;
                                  setFormData((p: any) => ({
                                    ...p,
                                    convenios: { ...(typeof p.convenios === "object" && p.convenios !== null ? p.convenios : {}), outros: val }
                                  }));
                                }}
                                className={inputClass}
                              />
                            </div>
                          </div>
                        </Field>
                      </div>
                    )}

                    {/* TAB: PROMO */}
                    {activeTab === "promo" && (
                      <div className="space-y-6">
                        {/* Toggle ativo */}
                        <div className="flex items-center justify-between gap-4 p-4 rounded-xl bg-slate-900/40 border border-white/5">
                          <div className="flex items-center gap-3 min-w-0">
                            <span className="text-2xl flex-shrink-0">{formData.promo_emoji || "🔥"}</span>
                            <div className="min-w-0">
                              <div className="text-sm font-bold text-white">Promoção ativa</div>
                              <div className="text-[11px] text-slate-500 mt-0.5">A IA usa estrategicamente no chat — desconto, urgência, brinde</div>
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => setFormData((p: any) => ({ ...p, promo_ativa: !p.promo_ativa }))}
                            className={`relative w-12 h-6 rounded-full transition-all flex-shrink-0 ${formData.promo_ativa ? "bg-emerald-500" : "bg-slate-700"}`}
                          >
                            <div className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-all ${formData.promo_ativa ? "left-6" : "left-0.5"}`} />
                          </button>
                        </div>

                        {formData.promo_ativa && (
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {/* Nome da promo */}
                            <Field label="Nome da Promo" icon={Sparkles}>
                              <input
                                type="text"
                                placeholder="Ex: Black April 2026"
                                value={formData.promo_nome || ""}
                                onChange={e => setFormData((p: any) => ({ ...p, promo_nome: e.target.value }))}
                                className={inputClass}
                                maxLength={100}
                              />
                            </Field>

                            {/* Emoji */}
                            <Field label="Emoji do Badge" icon={Sparkles}>
                              <div className="flex gap-2 items-center">
                                <input
                                  type="text"
                                  placeholder="🔥"
                                  value={formData.promo_emoji || ""}
                                  onChange={e => setFormData((p: any) => ({ ...p, promo_emoji: e.target.value }))}
                                  className={`${inputClass} text-center text-2xl w-20`}
                                  maxLength={4}
                                />
                                <div className="flex gap-1 flex-wrap">
                                  {["🔥","💥","⚡","🎯","💎","🎁","⭐","🚀"].map(em => (
                                    <button key={em} type="button"
                                      onClick={() => setFormData((p: any) => ({ ...p, promo_emoji: em }))}
                                      className="w-9 h-9 rounded-lg bg-slate-800 hover:bg-slate-700 text-xl flex items-center justify-center transition-all"
                                    >{em}</button>
                                  ))}
                                </div>
                              </div>
                            </Field>

                            {/* Chamada */}
                            <Field label="Chamada Principal (frase de impacto)" icon={Sparkles}>
                              <input
                                type="text"
                                placeholder="Ex: 3 meses pelo preço de 1!"
                                value={formData.promo_chamada || ""}
                                onChange={e => setFormData((p: any) => ({ ...p, promo_chamada: e.target.value }))}
                                className={inputClass}
                              />
                            </Field>

                            {/* Cor do Badge */}
                            <Field label="Cor do Badge" icon={Sparkles}>
                              <div className="flex gap-2 items-center">
                                <input
                                  type="color"
                                  value={formData.promo_cor || "#ff3366"}
                                  onChange={e => setFormData((p: any) => ({ ...p, promo_cor: e.target.value }))}
                                  className="w-14 h-10 rounded-lg cursor-pointer border-0"
                                />
                                <input
                                  type="text"
                                  placeholder="#ff3366"
                                  value={formData.promo_cor || ""}
                                  onChange={e => setFormData((p: any) => ({ ...p, promo_cor: e.target.value }))}
                                  className={`${inputClass} font-mono text-xs`}
                                />
                              </div>
                            </Field>

                            {/* Desconto */}
                            <Field label="Valor do Desconto" icon={CreditCard}>
                              <input
                                type="number"
                                step="0.01"
                                placeholder="60"
                                value={formData.promo_desconto ?? ""}
                                onChange={e => setFormData((p: any) => ({ ...p, promo_desconto: e.target.value ? parseFloat(e.target.value) : null }))}
                                className={inputClass}
                              />
                            </Field>

                            {/* Tipo de desconto */}
                            <Field label="Tipo do Desconto" icon={CreditCard}>
                              <select
                                value={formData.promo_desconto_tipo || "percentual"}
                                onChange={e => setFormData((p: any) => ({ ...p, promo_desconto_tipo: e.target.value }))}
                                className={inputClass}
                              >
                                <option value="percentual">% (percentual)</option>
                                <option value="reais">R$ (reais)</option>
                              </select>
                            </Field>

                            {/* Brinde */}
                            <div className="md:col-span-2">
                              <Field label="Brinde / Bônus" icon={Sparkles}>
                                <input
                                  type="text"
                                  placeholder="Ex: Camiseta + 1 avaliação física grátis"
                                  value={formData.promo_brinde || ""}
                                  onChange={e => setFormData((p: any) => ({ ...p, promo_brinde: e.target.value }))}
                                  className={inputClass}
                                />
                              </Field>
                            </div>

                            {/* Validade início */}
                            <Field label="Válido a partir de" icon={Clock}>
                              <input
                                type="date"
                                value={formData.promo_validade_inicio || ""}
                                onChange={e => setFormData((p: any) => ({ ...p, promo_validade_inicio: e.target.value }))}
                                className={inputClass}
                              />
                            </Field>

                            {/* Validade fim */}
                            <Field label="Válido até" icon={Clock}>
                              <input
                                type="date"
                                value={formData.promo_validade_fim || ""}
                                onChange={e => setFormData((p: any) => ({ ...p, promo_validade_fim: e.target.value }))}
                                className={inputClass}
                              />
                            </Field>

                            {/* Observações */}
                            <div className="md:col-span-2">
                              <Field label="Observações Extras (a IA usa pra argumentar)" icon={Info}>
                                <textarea
                                  rows={3}
                                  placeholder="Ex: válido pra novos alunos, sem fidelidade no primeiro mês, matrícula até dia 30..."
                                  value={formData.promo_observacoes || ""}
                                  onChange={e => setFormData((p: any) => ({ ...p, promo_observacoes: e.target.value }))}
                                  className={textareaClass}
                                />
                              </Field>
                            </div>

                            {/* Preview */}
                            <div className="md:col-span-2 mt-4">
                              <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-widest mb-3">Preview do Badge</label>
                              <div
                                className="inline-flex items-center gap-3 px-5 py-3 rounded-2xl text-white font-bold shadow-lg"
                                style={{ backgroundColor: formData.promo_cor || "#ff3366" }}
                              >
                                <span className="text-2xl">{formData.promo_emoji || "🔥"}</span>
                                <div>
                                  <div className="text-sm">{formData.promo_nome || "Nome da Promo"}</div>
                                  <div className="text-xs opacity-90">{formData.promo_chamada || "Chamada principal aqui"}</div>
                                </div>
                              </div>
                            </div>
                          </div>
                        )}
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
          </ErrorBoundary>
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
