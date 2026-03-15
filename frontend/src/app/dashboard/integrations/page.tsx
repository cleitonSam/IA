"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { Network, Loader2, Save, CheckCircle2, ArrowLeft, MessageSquare, Zap, Hash } from "lucide-react";
import { motion } from "framer-motion";

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
      <div className="min-h-screen bg-[#050505] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#050505] text-white p-6 md:p-12">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-4 mb-10">
          <a href="/dashboard" className="p-3 hover:bg-white/5 rounded-2xl transition-all border border-white/5">
            <ArrowLeft className="w-5 h-5" />
          </a>
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-3">
              <Network className="w-8 h-8 text-blue-500" />
              Ecossistema de Integrações
            </h1>
            <p className="text-gray-400 mt-1">Conecte seus canais de atendimento e sistemas de gestão.</p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex p-1.5 bg-white/[0.03] border border-white/10 rounded-2xl mb-10 max-w-2xl">
          {[
            { id: "chatwoot", label: "Chatwoot", icon: MessageSquare },
            { id: "evo", label: "EVO W12", icon: Zap },
            { id: "uzap", label: "UazAPI", icon: Hash }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-2 py-3.5 rounded-xl font-black uppercase tracking-widest text-[10px] transition-all ${
                activeTab === tab.id 
                  ? "bg-blue-600 text-white shadow-xl shadow-blue-600/20" 
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              <tab.icon className="w-4 h-4" /> {tab.label}
            </button>
          ))}
        </div>

        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-white/[0.03] border border-white/10 rounded-[2.5rem] p-10 backdrop-blur-3xl shadow-2xl relative overflow-hidden"
        >
          {/* Decorative background intensity */}
          <div className="absolute -top-24 -right-24 w-48 h-48 bg-blue-600/10 blur-[100px] pointer-events-none" />
          
          <form onSubmit={handleSave} className="space-y-8 relative z-10">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xl font-bold flex items-center gap-3 text-blue-400">
                Configurações do {activeTab.toUpperCase()}
              </h3>
              <div className="flex items-center gap-3 bg-white/5 px-4 py-2 rounded-xl border border-white/5 shadow-inner">
                 <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">Status</span>
                 <button
                    type="button"
                    onClick={toggleAtivo}
                    className={`relative inline-flex h-5 w-10 items-center rounded-full transition-colors focus:outline-none ${
                        currentConfig.ativo ? "bg-emerald-500" : "bg-gray-700"
                    }`}
                  >
                    <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                        currentConfig.ativo ? "translate-x-6" : "translate-x-1"
                    }`} />
                  </button>
              </div>
            </div>

            {activeTab === "chatwoot" && (
              <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                  <div className="space-y-3">
                    <label className="block text-xs font-black text-gray-500 uppercase tracking-widest ml-1">Instância URL</label>
                    <input
                      type="text"
                      value={currentConfig.config.url || ""}
                      onChange={(e) => updateConfigField("url", e.target.value)}
                      placeholder="https://chat.suaempresa.com"
                      className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all font-medium"
                    />
                  </div>
                  <div className="space-y-3">
                    <label className="block text-xs font-black text-gray-500 uppercase tracking-widest ml-1">ID da Conta</label>
                    <input
                      type="text"
                      value={currentConfig.config.account_id || ""}
                      onChange={(e) => updateConfigField("account_id", e.target.value)}
                      placeholder="Ex: 1"
                      className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all font-medium"
                    />
                  </div>
                </div>
                <div className="space-y-3">
                  <label className="block text-xs font-black text-gray-500 uppercase tracking-widest ml-1">Token de Acesso</label>
                  <input
                    type="password"
                    value={currentConfig.config.access_token || ""}
                    onChange={(e) => updateConfigField("access_token", e.target.value)}
                    placeholder="Seu access token privado"
                    className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all font-mono"
                  />
                </div>
              </div>
            )}

            {activeTab === "evo" && (
              <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2">
                <div className="space-y-3">
                  <label className="block text-xs font-black text-gray-500 uppercase tracking-widest ml-1">Subdomínio (DNS)</label>
                  <input
                    type="text"
                    value={currentConfig.config.dns || ""}
                    onChange={(e) => updateConfigField("dns", e.target.value)}
                    placeholder="Ex: academiaxyz"
                    className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all font-medium"
                  />
                  <p className="text-[10px] text-gray-600 ml-1 italic">Utilizado para identificar sua unidade no sistema EVO.</p>
                </div>
                <div className="space-y-3">
                  <label className="block text-xs font-black text-gray-500 uppercase tracking-widest ml-1">Chave Secreta da API</label>
                  <input
                    type="password"
                    value={currentConfig.config.secret_key || ""}
                    onChange={(e) => updateConfigField("secret_key", e.target.value)}
                    placeholder="Sua secret key da W12"
                    className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all font-mono"
                  />
                </div>
              </div>
            )}

            {activeTab === "uzap" && (
              <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2">
                <div className="space-y-3">
                  <label className="block text-xs font-black text-gray-500 uppercase tracking-widest ml-1">API Endpoint</label>
                  <input
                    type="text"
                    value={currentConfig.config.api_url || ""}
                    onChange={(e) => updateConfigField("api_url", e.target.value)}
                    placeholder="https://uazapi.com.br/api/v1"
                    className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all font-medium"
                  />
                </div>
                <div className="space-y-3">
                  <label className="block text-xs font-black text-gray-500 uppercase tracking-widest ml-1">Chave da Instância</label>
                  <input
                    type="password"
                    value={currentConfig.config.token || ""}
                    onChange={(e) => updateConfigField("token", e.target.value)}
                    placeholder="Token de autorização"
                    className="w-full bg-white/[0.03] border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all font-mono"
                  />
                </div>
              </div>
            )}

            <div className="pt-10 border-t border-white/5 flex justify-end">
              <button
                type="submit"
                disabled={saving}
                className="bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 text-white px-12 py-5 rounded-2xl font-black uppercase tracking-widest text-[10px] flex items-center gap-3 transition-all hover:scale-[1.02] active:scale-[0.98] shadow-2xl shadow-blue-600/20"
              >
                {saving ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : success ? (
                  <CheckCircle2 className="w-5 h-5 text-emerald-300" />
                ) : (
                  <Save className="w-5 h-5" />
                )}
                {success ? "Configuração Ativada" : "Salvar Integração"}
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </div>
  );
}
