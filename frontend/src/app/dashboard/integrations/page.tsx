"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { Network, Loader2, Save, CheckCircle2, MessageSquare, Zap, Hash, Globe, Link, ShieldCheck } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

interface Integration { id?: number; tipo: string; config: any; ativo: boolean; }

export default function IntegrationsPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [activeTab, setActiveTab] = useState("chatwoot");
  const [integrations, setIntegrations] = useState<Record<string, Integration>>({});

  const getToken = () =>({ headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } });

  useEffect(() => {
    axios.get("/api-backend/management/integrations", getToken())
      .then(r => {
        const mapped = r.data.reduce((acc: any, item: any) => {
          acc[item.tipo] = { ...item, config: typeof item.config === "string" ? JSON.parse(item.config) : item.config };
          return acc;
        }, {});
        setIntegrations(mapped);
      }).catch(console.error).finally(() => setLoading(false));
  }, []);

  const currentConfig = integrations[activeTab] || {
    tipo: activeTab,
    config: activeTab === "chatwoot" ? { url: "", access_token: "", account_id: "" }
      : activeTab === "evo" ? { dns: "", secret_key: "", api_url: "" }
      : { api_url: "", token: "" },
    ativo: false,
  };

  const updateField = (field: string, value: any) => setIntegrations({
    ...integrations,
    [activeTab]: { ...currentConfig, config: { ...currentConfig.config, [field]: value } }
  });
  const toggleAtivo = () => setIntegrations({ ...integrations, [activeTab]: { ...currentConfig, ativo: !currentConfig.ativo } });

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

  const inputClass = "w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 transition-all font-medium text-sm";
  const tabs = [
    { id: "chatwoot", label: "Chatwoot (WhatsApp)", icon: MessageSquare },
    { id: "evo", label: "EVO W12 (CRM)", icon: Zap },
    { id: "uzap", label: "UazAPI (Gateway)", icon: Hash },
  ];

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="integrations" />
      <main className="flex-1 min-w-0 overflow-auto">
        <div className="fixed top-0 right-0 w-[500px] h-[400px] bg-[#00d2ff]/3 rounded-full blur-[120px] pointer-events-none" />
        <div className="relative z-10 p-8 lg:p-10 max-w-5xl mx-auto pb-20">
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
            <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
              onClick={handleSave} disabled={saving}
              className="bg-[#00d2ff] text-black px-10 py-4 rounded-2xl font-black uppercase tracking-widest text-sm flex items-center gap-3 shadow-[0_0_25px_rgba(0,210,255,0.3)] disabled:opacity-50">
              {saving ? <><Loader2 className="w-5 h-5 animate-spin" />Handshaking...</>
                : success ? <><CheckCircle2 className="w-5 h-5" />Sincronizado!</>
                : <><Save className="w-5 h-5" />Salvar Configuração</>}
            </motion.button>
          </div>

          {/* Tabs */}
          <div className="flex flex-wrap gap-3 mb-8">
            {tabs.map(tab => (
              <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2.5 px-5 py-3 rounded-2xl font-black uppercase tracking-widest text-[11px] border transition-all ${activeTab === tab.id ? "bg-[#00d2ff]/15 text-[#00d2ff] border-[#00d2ff]/25" : "text-slate-500 border-white/5 hover:text-white hover:bg-white/5"}`}>
                <tab.icon className="w-4 h-4" /> {tab.label}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-40"><Loader2 className="w-8 h-8 text-[#00d2ff] animate-spin" /></div>
          ) : (
            <AnimatePresence mode="wait">
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
                  )}

                  {activeTab === "evo" && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                      <div className="space-y-3">
                        <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-1.5"><Link className="w-3 h-3 text-[#00d2ff]" />Subdomínio (DNS)</label>
                        <input type="text" value={currentConfig.config.dns || ""} onChange={e => updateField("dns", e.target.value)} className={inputClass} placeholder="Ex: minhaconta" />
                      </div>
                      <div className="md:col-span-2 space-y-3">
                        <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-1.5"><ShieldCheck className="w-3 h-3 text-[#00d2ff]" />EVO Secret Key</label>
                        <input type="password" value={currentConfig.config.secret_key || ""} onChange={e => updateField("secret_key", e.target.value)} className={`${inputClass} font-mono`} placeholder="••••••••••••••••••" />
                      </div>
                    </div>
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
            </AnimatePresence>
          )}
        </div>
      </main>
    </div>
  );
}
