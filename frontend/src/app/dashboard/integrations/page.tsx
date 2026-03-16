"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import {
  Network, Loader2, Save, CheckCircle2, MessageSquare, Zap, Hash,
  Globe, Link, ShieldCheck, Building2, Pencil, X, Plus,
  CheckCircle, XCircle, Settings2,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

interface Integration { id?: number; tipo: string; config: any; ativo: boolean; }
interface EvoUnit {
  unidade_id: number;
  unidade_nome: string;
  config: { dns: string; secret_key: string; idBranch?: string };
  ativo: boolean;
  configurado: boolean;
}

export default function IntegrationsPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [activeTab, setActiveTab] = useState("chatwoot");
  const [integrations, setIntegrations] = useState<Record<string, Integration>>({});
  const [isAdminMaster, setIsAdminMaster] = useState(false);
  const [chatwootAiActive, setChatwootAiActive] = useState(true);
  const [togglingAi, setTogglingAi] = useState(false);

  // EVO per-unit state
  const [evoUnits, setEvoUnits] = useState<EvoUnit[]>([]);
  const [evoLoading, setEvoLoading] = useState(false);
  const [evoModal, setEvoModal] = useState<{ open: boolean; unit: EvoUnit | null }>({ open: false, unit: null });
  const [evoForm, setEvoForm] = useState({ dns: "", secret_key: "", idBranch: "", ativo: false });
  const [evoSaving, setEvoSaving] = useState(false);
  const [evoSuccess, setEvoSuccess] = useState(false);

  const getToken = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } });

  // 1. Verifica perfil e carrega integrações
  useEffect(() => {
    axios.get("/api-backend/auth/me", getToken()).then(r => {
      if (r.data.perfil === "admin_master") {
        setIsAdminMaster(true);
        setLoading(false);
        return;
      }
      // admin normal → carrega integrações da sua empresa
      axios.get("/api-backend/management/integrations", getToken())
        .then(res => {
          const mapped = res.data.reduce((acc: any, item: any) => {
            acc[item.tipo] = { ...item, config: typeof item.config === "string" ? JSON.parse(item.config) : item.config };
            return acc;
          }, {});
          setIntegrations(mapped);
          return axios.get("/api-backend/management/integrations/chatwoot/ai-status", getToken())
            .then((statusRes) => setChatwootAiActive(Boolean(statusRes.data?.ai_active)))
            .catch(() => setChatwootAiActive(true));
        }).catch(console.error).finally(() => setLoading(false));
    }).catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (activeTab !== "evo" || isAdminMaster) return;
    setEvoLoading(true);
    axios.get("/api-backend/management/integrations/evo/units", getToken())
      .then(r => setEvoUnits(r.data))
      .catch(console.error)
      .finally(() => setEvoLoading(false));
  }, [activeTab, isAdminMaster]);

  const currentConfig = integrations[activeTab] || {
    tipo: activeTab,
    config: activeTab === "chatwoot" ? { url: "", access_token: "", account_id: "" }
      : { api_url: "", token: "" },
    ativo: false,
  };

  const updateField = (field: string, value: any) => setIntegrations({
    ...integrations,
    [activeTab]: { ...currentConfig, config: { ...currentConfig.config, [field]: value } }
  });
  const toggleAtivo = () => setIntegrations({ ...integrations, [activeTab]: { ...currentConfig, ativo: !currentConfig.ativo } });

  const toggleChatwootAI = async () => {
    if (activeTab !== "chatwoot") return;
    const next = !chatwootAiActive;
    setTogglingAi(true);
    try {
      await axios.put(
        "/api-backend/management/integrations/chatwoot/ai-status",
        { ai_active: next },
        getToken()
      );
      setChatwootAiActive(next);
    } catch {
      alert("Erro ao alterar status da IA no Chatwoot.");
    } finally {
      setTogglingAi(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await axios.put(`/api-backend/management/integrations/${activeTab}`, currentConfig, getToken());
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch { alert("Erro ao salvar integração."); }
    finally { setSaving(false); }
  };

  const openEvoModal = (unit: EvoUnit) => {
    setEvoForm({ 
      dns: unit.config.dns || "", 
      secret_key: unit.config.secret_key || "", 
      idBranch: unit.config.idBranch || "",
      ativo: unit.ativo 
    });
    setEvoModal({ open: true, unit });
    setEvoSuccess(false);
  };

  const handleEvoSave = async () => {
    if (!evoModal.unit) return;
    setEvoSaving(true);
    try {
      await axios.put(
        `/api-backend/management/integrations/evo/unit/${evoModal.unit.unidade_id}`,
        { 
          config: { 
            dns: evoForm.dns, 
            secret_key: evoForm.secret_key,
            idBranch: evoForm.idBranch 
          }, 
          ativo: evoForm.ativo 
        },
        getToken()
      );
      setEvoSuccess(true);
      setEvoUnits(prev => prev.map(u =>
        u.unidade_id === evoModal.unit!.unidade_id
          ? { ...u, config: { dns: evoForm.dns, secret_key: evoForm.secret_key, idBranch: evoForm.idBranch }, ativo: evoForm.ativo, configurado: !!evoForm.dns }
          : u
      ));
      
      // Auto-trigger sync after save
      handleEvoSync(evoModal.unit.unidade_id);
      
      setTimeout(() => { setEvoSuccess(false); setEvoModal({ open: false, unit: null }); }, 1400);
    } catch { alert("Erro ao salvar configuração EVO da unidade."); }
    finally { setEvoSaving(false); }
  };

  const [syncingId, setSyncingId] = useState<number | null>(null);
  const handleEvoSync = async (unidadeId: number) => {
    setSyncingId(unidadeId);
    try {
      const res = await axios.post(`/api-backend/management/integrations/evo/sync/${unidadeId}`, {}, getToken());
      alert(`Sincronização concluída! ${res.data.count} planos atualizados.`);
    } catch {
      alert("Erro ao sincronizar planos. Verifique a configuração.");
    } finally {
      setSyncingId(null);
    }
  };

  const inputClass = "w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 transition-all font-medium text-sm";
  const tabs = [
    { id: "chatwoot", label: "Chatwoot", icon: MessageSquare },
    { id: "evo", label: "EVO W12", icon: Zap },
    { id: "uzap", label: "UazAPI", icon: Hash },
  ];

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="integrations" />
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
                Fluxo Conect
              </h1>
              <p className="text-slate-500 mt-2 text-sm italic">Gerencie as pontes entre seus canais de atendimento e o EVO.</p>
            </div>
            {!isAdminMaster && activeTab !== "evo" && (
              <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
                onClick={handleSave} disabled={saving}
                className="bg-[#00d2ff] text-black px-10 py-4 rounded-2xl font-black uppercase tracking-widest text-sm flex items-center gap-3 shadow-[0_0_25px_rgba(0,210,255,0.3)] disabled:opacity-50">
                {saving ? <><Loader2 className="w-5 h-5 animate-spin" />Salvando...</>
                  : success ? <><CheckCircle2 className="w-5 h-5" />Sincronizado!</>
                  : <><Save className="w-5 h-5" />Salvar Configuração</>}
              </motion.button>
            )}
          </div>

          {/* Tabs */}
          <div className="flex flex-wrap gap-3 mb-8">
            {tabs.map(tab => (
              <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2.5 px-5 py-3 rounded-2xl font-black uppercase tracking-widest text-[11px] border transition-all ${activeTab === tab.id ? "bg-[#00d2ff]/15 text-[#00d2ff] border-[#00d2ff]/25" : "text-slate-500 border-white/5 hover:text-white hover:bg-white/5"}`}>
                <tab.icon className="w-4 h-4" /> {tab.label}
                {tab.id === "evo" && evoUnits.filter(u => u.configurado && u.ativo).length > 0 && (
                  <span className="bg-emerald-500 text-black text-[8px] font-black px-1.5 py-0.5 rounded-full ml-1">
                    {evoUnits.filter(u => u.configurado && u.ativo).length}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* admin_master não tem acesso a esta página */}
          {isAdminMaster ? (
            <div className="flex flex-col items-center justify-center py-32 rounded-3xl border border-dashed border-white/5 bg-white/[0.01]">
              <Network className="w-12 h-12 text-slate-700 mb-4" />
              <p className="text-slate-400 font-bold">Acesso restrito</p>
              <p className="text-slate-600 text-sm mt-1 text-center max-w-xs">
                As integrações são gerenciadas pelo administrador de cada empresa.
              </p>
            </div>
          ) : loading ? (
            <div className="flex items-center justify-center py-40"><Loader2 className="w-8 h-8 text-[#00d2ff] animate-spin" /></div>
          ) : (
            <AnimatePresence mode="wait">

              {/* ── EVO: grid por unidade ── */}
              {activeTab === "evo" && (
                <motion.div key="evo" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}>
                  <div className="flex items-center justify-between mb-6">
                    <div>
                      <h3 className="text-xl font-black uppercase flex items-center gap-3">
                        <Zap className="w-5 h-5 text-[#00d2ff]" /> EVO W12 — Por Unidade
                      </h3>
                      <p className="text-xs text-slate-500 mt-1">Cada unidade tem seu próprio subdomínio e chave secreta EVO.</p>
                    </div>
                  </div>

                  {evoLoading ? (
                    <div className="flex items-center justify-center py-24">
                      <Loader2 className="w-7 h-7 text-[#00d2ff] animate-spin" />
                    </div>
                  ) : evoUnits.length === 0 ? (
                    <div className="text-center py-24 rounded-3xl border border-dashed border-white/5 bg-white/[0.01]">
                      <Building2 className="w-10 h-10 text-slate-600 mx-auto mb-4" />
                      <p className="text-slate-400 font-bold">Nenhuma unidade ativa encontrada.</p>
                      <p className="text-slate-600 text-sm mt-1">Cadastre unidades no painel de Unidades primeiro.</p>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
                      {evoUnits.map((unit, i) => (
                        <motion.div
                          key={unit.unidade_id}
                          initial={{ opacity: 0, y: 16 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: i * 0.05 }}
                          className="bg-slate-900/50 border border-white/5 hover:border-[#00d2ff]/20 rounded-3xl overflow-hidden group transition-all duration-300"
                        >
                          <div className="p-6">
                            {/* Header do card */}
                            <div className="flex items-start justify-between mb-4">
                              <div className="w-12 h-12 rounded-2xl bg-[#00d2ff]/10 border border-[#00d2ff]/20 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
                                <Zap className="w-6 h-6 text-[#00d2ff]" />
                              </div>
                              {unit.configurado ? (
                                unit.ativo
                                  ? <span className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-widest text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 px-2.5 py-1.5 rounded-full">
                                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" /> Ativo
                                    </span>
                                  : <span className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-widest text-amber-400 bg-amber-400/10 border border-amber-400/20 px-2.5 py-1.5 rounded-full">
                                      <span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> Pausado
                                    </span>
                              ) : (
                                <span className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-widest text-slate-500 bg-white/5 border border-white/5 px-2.5 py-1.5 rounded-full">
                                  <span className="w-1.5 h-1.5 rounded-full bg-slate-600" /> Não configurado
                                </span>
                              )}
                            </div>

                            {/* Nome da unidade */}
                            <h3 className="text-base font-black uppercase tracking-tight group-hover:text-[#00d2ff] transition-colors mb-1 leading-tight">
                              {unit.unidade_nome}
                            </h3>

                            {/* Detalhes */}
                            <div className="mt-4 space-y-2 pt-4 border-t border-white/5">
                              <div className="flex items-center gap-2 text-xs text-slate-500">
                                <Globe className="w-3.5 h-3.5 text-[#00d2ff]/40 shrink-0" />
                                {unit.config.dns
                                  ? <span className="font-mono text-slate-300">{unit.config.dns}.w12app.com.br</span>
                                  : <span className="italic text-slate-600">Subdomínio não definido</span>
                                }
                              </div>
                              <div className="flex items-center gap-2 text-xs text-slate-500">
                                <ShieldCheck className="w-3.5 h-3.5 text-[#00d2ff]/40 shrink-0" />
                                {unit.config.secret_key
                                  ? <span className="font-mono">{"•".repeat(12)}</span>
                                  : <span className="italic text-slate-600">Chave não definida</span>
                                }
                              </div>
                            </div>
                          </div>

                          {/* Botão de editar */}
                          <button
                            onClick={() => openEvoModal(unit)}
                            className="w-full px-6 py-4 bg-white/[0.02] hover:bg-[#00d2ff]/5 border-t border-white/5 text-[10px] font-black uppercase tracking-[0.25em] text-slate-500 hover:text-[#00d2ff] transition-all flex items-center justify-center gap-2"
                          >
                            <Settings2 className="w-4 h-4" />
                            {unit.configurado ? "Editar Configuração" : "Configurar Agora"}
                          </button>
                        </motion.div>
                      ))}
                    </div>
                  )}

                  {/* Info card */}
                  <div className="mt-8 p-5 bg-[#00d2ff]/5 border border-[#00d2ff]/10 rounded-2xl flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-[#00d2ff]/10 flex items-center justify-center animate-pulse flex-shrink-0">
                      <Zap className="w-5 h-5 text-[#00d2ff]" />
                    </div>
                    <p className="text-[11px] font-black uppercase tracking-widest text-slate-400 italic">
                      Cada unidade usa seu próprio subdomínio EVO. O bot roteia automaticamente para o CRM correto.
                    </p>
                  </div>
                </motion.div>
              )}

              {/* ── Chatwoot & UazAPI: form único ── */}
              {activeTab !== "evo" && (
                <motion.div key={activeTab} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}
                  className="bg-slate-900/50 border border-white/5 rounded-3xl p-10 hover:border-[#00d2ff]/15 transition-all relative overflow-hidden">
                  <div className="absolute -top-20 -right-20 w-60 h-60 bg-[#00d2ff]/5 blur-[100px] rounded-full pointer-events-none" />

                  <form onSubmit={handleSave} className="space-y-10 relative z-10">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-5">
                      <div>
                        <h3 className="text-xl font-black uppercase">
                          {tabs.find(t => t.id === activeTab)?.label}
                        </h3>
                        <p className="text-xs text-slate-500 font-bold uppercase tracking-widest mt-1">Gateway de Comunicação</p>
                      </div>
                      <div className="flex items-center gap-4 bg-slate-900/60 px-5 py-3 rounded-2xl border border-white/5">
                        <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">Integração Ativa</span>
                        <button type="button" onClick={toggleAtivo}
                          className={`relative inline-flex h-7 w-12 items-center rounded-full transition-all ${currentConfig.ativo ? "bg-[#00d2ff]" : "bg-slate-700"}`}>
                          <span className={`inline-block h-5 w-5 transform rounded-full bg-white transition-all shadow ${currentConfig.ativo ? "translate-x-6" : "translate-x-1"}`} />
                        </button>
                      </div>
                    </div>

                    {activeTab === "chatwoot" && (
                      <>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <div className="space-y-3">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-1.5"><Globe className="w-3 h-3 text-[#00d2ff]" />URL Host</label>
                          <input type="text" value={currentConfig.config.url || ""} onChange={e => updateField("url", e.target.value)} className={inputClass} placeholder="https://chat.seusite.com.br" />
                        </div>
                        <div className="space-y-3">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-1.5"><Hash className="w-3 h-3 text-[#00d2ff]" />Account ID</label>
                          <input type="text" value={currentConfig.config.account_id || ""} onChange={e => updateField("account_id", e.target.value)} className={inputClass} placeholder="Ex: 5" />
                        </div>
                        <div className="md:col-span-2 space-y-3">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-1.5"><ShieldCheck className="w-3 h-3 text-[#00d2ff]" />Private Access Token</label>
                          <input type="password" value={currentConfig.config.access_token || ""} onChange={e => updateField("access_token", e.target.value)} className={`${inputClass} font-mono`} placeholder="••••••••••••••••••••••" />
                        </div>
                      </div>

                      <div className="md:col-span-2 flex items-center justify-between bg-slate-900/60 px-5 py-4 rounded-2xl border border-white/5">
                        <div>
                          <p className="text-[10px] font-black uppercase tracking-widest text-slate-400">IA no Chatwoot</p>
                          <p className={`text-[10px] font-black uppercase mt-1 ${chatwootAiActive ? "text-emerald-400" : "text-amber-400"}`}>
                            {chatwootAiActive ? "● Ativada" : "⏸ Pausada"}
                          </p>
                        </div>
                        <button type="button" onClick={toggleChatwootAI} disabled={togglingAi}
                          className={`relative inline-flex h-7 w-12 items-center rounded-full transition-all disabled:opacity-60 ${chatwootAiActive ? "bg-[#00d2ff]" : "bg-slate-700"}`}>
                          <span className={`inline-block h-5 w-5 transform rounded-full bg-white transition-all shadow ${chatwootAiActive ? "translate-x-6" : "translate-x-1"}`} />
                        </button>
                      </div>
                      </>
                    )}

                    {activeTab === "uzap" && (
                      <div className="grid grid-cols-1 gap-8">
                        <div className="space-y-3">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Endpoint API</label>
                          <input type="text" value={currentConfig.config.api_url || ""} onChange={e => updateField("api_url", e.target.value)} className={inputClass} placeholder="https://api.uazapi.com/v1" />
                        </div>
                        <div className="space-y-3">
                          <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Instance Secure Token</label>
                          <input type="password" value={currentConfig.config.token || ""} onChange={e => updateField("token", e.target.value)} className={`${inputClass} font-mono`} placeholder="Token UazAPI" />
                        </div>
                      </div>
                    )}

                    <div className="p-5 bg-[#00d2ff]/5 border border-[#00d2ff]/10 rounded-2xl flex items-center gap-4">
                      <div className="w-10 h-10 rounded-xl bg-[#00d2ff]/10 flex items-center justify-center animate-pulse flex-shrink-0">
                        <Zap className="w-5 h-5 text-[#00d2ff]" />
                      </div>
                      <p className="text-[11px] font-black uppercase tracking-widest text-slate-400 italic">
                        Conexão Segura: Tokens criptografados end-to-end e validados via Circuit Breaker em tempo real.
                      </p>
                    </div>
                  </form>
                </motion.div>
              )}

            </AnimatePresence>
          )}
        </div>
      </main>

      {/* ── Modal EVO por Unidade ── */}
      <AnimatePresence>
        {evoModal.open && evoModal.unit && (
          <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="absolute inset-0 bg-[#020617]/90 backdrop-blur-2xl"
              onClick={() => setEvoModal({ open: false, unit: null })} />
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 20 }}
              className="bg-[#080f1e] border border-white/10 rounded-[2.5rem] w-full max-w-lg overflow-hidden relative shadow-2xl"
            >
              {/* Modal header */}
              <div className="px-8 py-7 border-b border-white/5 flex items-center justify-between bg-slate-900/30 relative">
                <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-[#00d2ff]/30 to-transparent" />
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-2xl bg-[#00d2ff]/10 flex items-center justify-center border border-[#00d2ff]/20">
                    <Zap className="w-6 h-6 text-[#00d2ff]" />
                  </div>
                  <div>
                    <h2 className="text-lg font-black tracking-tight">EVO W12</h2>
                    <p className="text-slate-500 text-xs mt-0.5 font-bold uppercase tracking-widest">
                      {evoModal.unit.unidade_nome}
                    </p>
                  </div>
                </div>
                <motion.button whileHover={{ rotate: 90 }} onClick={() => setEvoModal({ open: false, unit: null })}
                  className="p-3 hover:bg-white/5 rounded-2xl transition-all border border-white/5 text-slate-500 hover:text-white">
                  <X className="w-5 h-5" />
                </motion.button>
              </div>

              {/* Modal body */}
              <div className="p-8 space-y-6">
                {/* Toggle ativo */}
                <div className="flex items-center justify-between bg-slate-900/50 border border-white/5 rounded-2xl px-5 py-4">
                  <div>
                    <p className="text-[10px] font-black uppercase tracking-widest text-slate-400">Integração Ativa</p>
                    <p className={`text-[9px] font-black uppercase mt-0.5 ${evoForm.ativo ? "text-emerald-400" : "text-slate-600"}`}>
                      {evoForm.ativo ? "● Online" : "○ Pausada"}
                    </p>
                  </div>
                  <button type="button" onClick={() => setEvoForm({ ...evoForm, ativo: !evoForm.ativo })}
                    className={`relative inline-flex h-7 w-12 items-center rounded-full transition-all ${evoForm.ativo ? "bg-[#00d2ff]" : "bg-slate-700"}`}>
                    <span className={`inline-block h-5 w-5 transform rounded-full bg-white transition-all shadow ${evoForm.ativo ? "translate-x-6" : "translate-x-1"}`} />
                  </button>
                </div>

                {/* Botão de Sync Manual no Modal */}
                {evoModal.unit.configurado && (
                  <button 
                    type="button" 
                    onClick={() => handleEvoSync(evoModal.unit!.unidade_id)}
                    disabled={syncingId !== null}
                    className="w-full py-4 bg-[#00d2ff]/5 border border-[#00d2ff]/20 rounded-2xl text-[10px] font-black uppercase tracking-widest text-[#00d2ff] hover:bg-[#00d2ff]/10 transition-all flex items-center justify-center gap-3 disabled:opacity-50"
                  >
                    {syncingId === evoModal.unit.unidade_id 
                      ? <><Loader2 className="w-4 h-4 animate-spin" /> Sincronizando...</>
                      : <><Zap className="w-4 h-4" /> Forçar Sincronização de Planos</>
                    }
                  </button>
                )}

                {/* DNS */}
                <div className="space-y-3">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-1.5">
                    <Globe className="w-3 h-3 text-[#00d2ff]" /> Subdomínio (DNS)
                  </label>
                  <div className="relative">
                    <input
                      type="text"
                      value={evoForm.dns}
                      onChange={e => setEvoForm({ ...evoForm, dns: e.target.value })}
                      className="w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 transition-all font-medium text-sm pr-40"
                      placeholder="minha-unidade"
                    />
                    <span className="absolute right-4 top-1/2 -translate-y-1/2 text-[10px] text-slate-500 font-mono">.w12app.com.br</span>
                  </div>
                  {evoForm.dns && (
                    <p className="text-[10px] text-[#00d2ff]/60 font-mono pl-1">
                      → {evoForm.dns}.w12app.com.br
                    </p>
                  )}
                </div>

                {/* Secret Key */}
                <div className="space-y-3">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-1.5">
                    <ShieldCheck className="w-3 h-3 text-[#00d2ff]" /> EVO Secret Key
                  </label>
                  <input
                    type="password"
                    value={evoForm.secret_key}
                    onChange={e => setEvoForm({ ...evoForm, secret_key: e.target.value })}
                    className="w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 transition-all font-mono text-sm"
                    placeholder="••••••••••••••••••"
                  />
                </div>

                {/* idBranch */}
                <div className="space-y-3">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-1.5">
                    <Building2 className="w-3 h-3 text-[#00d2ff]" /> ID Branch (Evo)
                  </label>
                  <input
                    type="text"
                    value={evoForm.idBranch}
                    onChange={e => setEvoForm({ ...evoForm, idBranch: e.target.value })}
                    className="w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 transition-all font-medium text-sm"
                    placeholder="Ex: 1"
                  />
                  <p className="text-[9px] text-slate-600 pl-1 uppercase tracking-tight">Obrigatório para contas Multiunidade.</p>
                </div>
              </div>

              {/* Modal footer */}
              <div className="px-8 py-6 bg-slate-900/30 border-t border-white/5 flex justify-end gap-3">
                <button type="button" onClick={() => setEvoModal({ open: false, unit: null })}
                  className="px-6 py-3 rounded-2xl font-bold text-sm text-slate-500 hover:text-white hover:bg-white/5 transition-all uppercase tracking-wider">
                  Cancelar
                </button>
                <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                  type="button" disabled={evoSaving} onClick={handleEvoSave}
                  className="bg-[#00d2ff] text-black px-10 py-3 rounded-2xl font-black uppercase tracking-widest text-sm flex items-center gap-2 shadow-[0_0_20px_rgba(0,210,255,0.25)] disabled:opacity-50">
                  {evoSaving
                    ? <><Loader2 className="w-4 h-4 animate-spin" /> Salvando...</>
                    : evoSuccess
                    ? <><CheckCircle2 className="w-4 h-4" /> Salvo!</>
                    : <><Save className="w-4 h-4" /> Salvar</>}
                </motion.button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar { width: 5px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0,210,255,0.12); border-radius: 10px; }
      `}</style>
    </div>
  );
}
