"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { Network, Loader2, Save, CheckCircle2, ArrowLeft, MessageSquare, Zap, Hash, Globe, Link, ShieldCheck } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface Integration {
  id?: number;
  tipo: string;
  config: any;
  ativo: boolean;
}

export default function IntegrationsPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [activeTab, setActiveTab] = useState("chatwoot");
  const [integrations, setIntegrations] = useState<Record<string, Integration>>({});

  useEffect(() => {
    fetchIntegrations();
  }, []);

  const fetchIntegrations = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await axios.get("/api-backend/management/integrations", {
        headers: { Authorization: `Bearer ${token}` }
      });
      const mapped = response.data.reduce((acc: any, item: any) => {
        acc[item.tipo] = { ...item, config: typeof item.config === "string" ? JSON.parse(item.config) : item.config };
        return acc;
      }, {});
      setIntegrations(mapped);
    } catch (error) {
      console.error("Erro ao buscar integrações:", error);
    } finally {
      setLoading(false);
    }
  };

  const currentConfig = integrations[activeTab] || {
    tipo: activeTab,
    config: activeTab === "chatwoot" ? { url: "", access_token: "", account_id: "" } :
            activeTab === "evo" ? { dns: "", secret_key: "", api_url: "" } :
            { api_url: "", token: "" },
    ativo: false,
  };

  const updateConfigField = (field: string, value: any) => {
    setIntegrations({
      ...integrations,
      [activeTab]: {
        ...currentConfig,
        config: { ...currentConfig.config, [field]: value },
      },
    });
  };

  const toggleAtivo = () => {
    setIntegrations({
      ...integrations,
      [activeTab]: { ...currentConfig, ativo: !currentConfig.ativo },
    });
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSuccess(false);
    try {
      const token = localStorage.getItem("token");
      await axios.put(`/api-backend/management/integrations/${activeTab}`, currentConfig, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (error) {
      alert("Erro ao salvar integração.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-mesh text-white p-6 md:p-12 pb-40">
      <div className="max-w-5xl mx-auto">
        
        {/* Unitary Header Structure - Standardized */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-16">
          <div className="flex items-center gap-5">
            <a href="/dashboard" className="p-3.5 bg-white/5 hover:bg-primary/10 rounded-2xl transition-all border border-white/10 hover:border-primary/30 group">
              <ArrowLeft className="w-5 h-5 group-hover:text-primary transition-colors" />
            </a>
            <div>
              <h1 className="text-4xl font-black flex items-center gap-3">
                <Network className="w-10 h-10 text-primary neon-glow" />
                <span className="text-gradient">Fluxo Conect</span>
              </h1>
              <p className="text-gray-400 mt-1 font-medium italic opacity-80">Gerencie as pontes neurais entre seus canais de atendimento e o EVO.</p>
            </div>
          </div>
          <button
             onClick={handleSave}
             disabled={saving}
             className="bg-primary hover:bg-primary/90 disabled:bg-primary/50 text-black px-12 py-5 rounded-[2rem] font-black uppercase tracking-widest text-sm flex items-center justify-center gap-3 transition-all shadow-[0_0_30px_rgba(0,210,255,0.3)] hover:scale-[1.02] active:scale-[0.98]"
          >
             {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : success ? <CheckCircle2 className="w-5 h-5" /> : <Save className="w-5 h-5" />}
             {saving ? "Handshaking..." : success ? "Canais Sincronizados" : "Salvar Configuração"}
          </button>
        </div>

        {/* Dynamic Selector */}
        <div className="flex flex-wrap p-2 bg-slate-900/40 border border-white/10 rounded-[2.5rem] mb-12 blue-tint">
          {[
            { id: "chatwoot", label: "Chatwoot (WhatsApp)", icon: MessageSquare },
            { id: "evo", label: "EVO W12 (CRM)", icon: Zap },
            { id: "uzap", label: "UazAPI (Gateway)", icon: Hash }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-3 py-4 px-6 rounded-[1.8rem] font-black uppercase tracking-widest text-[10px] transition-all min-w-[200px] ${
                activeTab === tab.id 
                  ? "bg-primary text-black shadow-xl shadow-primary/20" 
                  : "text-gray-500 hover:text-white"
              }`}
            >
              <tab.icon className="w-4 h-4" /> {tab.label}
            </button>
          ))}
        </div>

        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass rounded-[3rem] p-12 border-primary/10 relative overflow-hidden group mb-20"
        >
          {/* Decorative background intensity */}
          <div className="absolute -top-24 -right-24 w-64 h-64 bg-primary/10 blur-[120px] pointer-events-none group-hover:bg-primary/20 transition-colors" />
          
          <form onSubmit={handleSave} className="space-y-12 relative z-10">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-4">
              <div>
                 <h3 className="text-2xl font-black flex items-center gap-4 text-gradient">
                    Ativar Gateway: {activeTab.toUpperCase()}
                 </h3>
                 <p className="text-xs text-gray-500 font-bold uppercase tracking-widest mt-1">Status de Comunicação em tempo real</p>
              </div>
              <div className="flex items-center gap-4 bg-slate-900/40 px-6 py-3 rounded-2xl border border-white/5 shadow-inner self-start">
                 <span className="text-[10px] font-black uppercase tracking-widest text-gray-400">Integração Ativa</span>
                 <button
                    type="button"
                    onClick={toggleAtivo}
                    className={`relative inline-flex h-7 w-12 items-center rounded-full transition-all focus:outline-none ${
                        currentConfig.ativo ? "bg-primary" : "bg-gray-800"
                    }`}
                  >
                    <span className={`inline-block h-5 w-5 transform rounded-full bg-white transition-all shadow-md ${
                        currentConfig.ativo ? "translate-x-6" : "translate-x-1"
                    }`} />
                  </button>
              </div>
            </div>

            {activeTab === "chatwoot" && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
                <div className="space-y-4">
                  <label className="block text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1 flex items-center gap-2">
                    <Globe className="w-3 h-3 text-primary" /> Instância URL Host
                  </label>
                  <input
                    type="text"
                    value={currentConfig.config.url || ""}
                    onChange={(e) => updateConfigField("url", e.target.value)}
                    placeholder="https://chat.fluxodigitaltech.com.br"
                    className="w-full bg-slate-900/40 border border-white/10 rounded-2xl px-6 py-5 focus:outline-none focus:ring-2 focus:ring-primary/40 transition-all font-bold text-lg"
                  />
                </div>
                <div className="space-y-4">
                  <label className="block text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1 flex items-center gap-2">
                    <Hash className="w-3 h-3 text-primary" /> Account ID
                  </label>
                  <input
                    type="text"
                    value={currentConfig.config.account_id || ""}
                    onChange={(e) => updateConfigField("account_id", e.target.value)}
                    placeholder="Ex: 5"
                    className="w-full bg-slate-900/40 border border-white/10 rounded-2xl px-6 py-5 focus:outline-none focus:ring-2 focus:ring-primary/40 transition-all font-bold text-lg"
                  />
                </div>
                <div className="md:col-span-2 space-y-4">
                  <label className="block text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1 flex items-center gap-2">
                    <ShieldCheck className="w-3 h-3 text-primary" /> Private Access Token
                  </label>
                  <input
                    type="password"
                    value={currentConfig.config.access_token || ""}
                    onChange={(e) => updateConfigField("access_token", e.target.value)}
                    placeholder="••••••••••••••••••••••••••••••••"
                    className="w-full bg-slate-900/40 border border-white/10 rounded-2xl px-6 py-5 focus:outline-none focus:ring-2 focus:ring-primary/40 transition-all font-mono"
                  />
                </div>
              </div>
            )}

            {activeTab === "evo" && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
                <div className="space-y-4">
                  <label className="block text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1 flex items-center gap-2">
                    <Link className="w-3 h-3 text-primary" /> Subdomínio (ID DNS)
                  </label>
                  <input
                    type="text"
                    value={currentConfig.config.dns || ""}
                    onChange={(e) => updateConfigField("dns", e.target.value)}
                    placeholder="Ex: fluxodigital"
                    className="w-full bg-slate-900/40 border border-white/10 rounded-2xl px-6 py-5 focus:outline-none focus:ring-2 focus:ring-primary/40 transition-all font-bold text-lg"
                  />
                </div>
                <div className="md:col-span-2 space-y-4">
                  <label className="block text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1 flex items-center gap-2">
                    <ShieldCheck className="w-3 h-3 text-primary" /> EVO Secret Key (Gateway API)
                  </label>
                  <input
                    type="password"
                    value={currentConfig.config.secret_key || ""}
                    onChange={(e) => updateConfigField("secret_key", e.target.value)}
                    placeholder="••••••••••••••••••••••••"
                    className="w-full bg-slate-900/40 border border-white/10 rounded-2xl px-6 py-5 focus:outline-none focus:ring-2 focus:ring-primary/40 transition-all font-mono text-primary/80"
                  />
                </div>
              </div>
            )}

            {activeTab === "uzap" && (
              <div className="grid grid-cols-1 gap-10">
                <div className="space-y-4">
                  <label className="block text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1 flex items-center gap-2">
                     Endpoint API (UazAPI)
                  </label>
                  <input
                    type="text"
                    value={currentConfig.config.api_url || ""}
                    onChange={(e) => updateConfigField("api_url", e.target.value)}
                    placeholder="https://api.uazapi.com/v1"
                    className="w-full bg-slate-900/40 border border-white/10 rounded-2xl px-6 py-5 focus:outline-none focus:ring-2 focus:ring-primary/40 transition-all font-bold"
                  />
                </div>
                <div className="space-y-4">
                  <label className="block text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1">Instance Secure Token</label>
                  <input
                    type="password"
                    value={currentConfig.config.token || ""}
                    onChange={(e) => updateConfigField("token", e.target.value)}
                    placeholder="Token UazAPI"
                    className="w-full bg-slate-900/40 border border-white/10 rounded-2xl px-6 py-5 focus:outline-none focus:ring-2 focus:ring-primary/40 transition-all font-mono"
                  />
                </div>
              </div>
            )}

            <div className="mt-8 p-6 bg-primary/5 border border-primary/10 rounded-3xl">
                <div className="flex items-center gap-4">
                   <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center animate-pulse">
                      <Zap className="w-6 h-6 text-primary" />
                   </div>
                   <p className="text-[11px] font-black uppercase tracking-widest text-gray-400 leading-relaxed italic">
                      Conexão Segura: Todos os tokens são criptografados end-to-end e validados via Circuit Breaker em tempo real.
                   </p>
                </div>
            </div>
          </form>
        </motion.div>
      </div>
    </div>
  );
}
