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
        <div className="flex items-center gap-4 mb-8">
          <a href="/dashboard" className="p-2 hover:bg-white/5 rounded-full transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </a>
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-3">
              <Network className="w-8 h-8 text-blue-500" />
              Integrações
            </h1>
            <p className="text-gray-400 mt-1">Conecte seu Dashboard com serviços externos.</p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex p-1 bg-white/5 border border-white/10 rounded-2xl mb-8">
          <button
            onClick={() => setActiveTab("chatwoot")}
            className={`flex-1 flex items-center justify-center gap-2 py-4 rounded-xl font-bold transition-all ${
              activeTab === "chatwoot" ? "bg-white/10 text-white shadow-lg" : "text-gray-500 hover:text-white"
            }`}
          >
            <MessageSquare className="w-5 h-5" /> Chatwoot
          </button>
          <button
            onClick={() => setActiveTab("evo")}
            className={`flex-1 flex items-center justify-center gap-2 py-4 rounded-xl font-bold transition-all ${
              activeTab === "evo" ? "bg-white/10 text-white shadow-lg" : "text-gray-500 hover:text-white"
            }`}
          >
            <Zap className="w-5 h-5" /> EVO
          </button>
          <button
            onClick={() => setActiveTab("uzap")}
            className={`flex-1 flex items-center justify-center gap-2 py-4 rounded-xl font-bold transition-all ${
              activeTab === "uzap" ? "bg-white/10 text-white shadow-lg" : "text-gray-500 hover:text-white"
            }`}
          >
            <Hash className="w-5 h-5" /> UazAPI
          </button>
        </div>

        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-white/5 border border-white/10 rounded-2xl p-8 backdrop-blur-xl"
        >
          <form onSubmit={handleSave} className="space-y-6">
            {activeTab === "chatwoot" && (
              <div className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-2">URL do Chatwoot</label>
                    <input
                      type="text"
                      value={currentConfig.config.url || ""}
                      onChange={(e) => updateConfigField("url", e.target.value)}
                      placeholder="https://chat.suaempresa.com"
                      className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-2">ID da Conta</label>
                    <input
                      type="text"
                      value={currentConfig.config.account_id || ""}
                      onChange={(e) => updateConfigField("account_id", e.target.value)}
                      placeholder="1"
                      className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">Access Token</label>
                  <input
                    type="password"
                    value={currentConfig.config.access_token || ""}
                    onChange={(e) => updateConfigField("access_token", e.target.value)}
                    placeholder="Seu token secreto"
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                  />
                </div>
              </div>
            )}

            {activeTab === "evo" && (
              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">DNS (Account Subdomain)</label>
                  <input
                    type="text"
                    value={currentConfig.config.dns || ""}
                    onChange={(e) => updateConfigField("dns", e.target.value)}
                    placeholder="ex: academiaxyz"
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">Secret Key</label>
                  <input
                    type="password"
                    value={currentConfig.config.secret_key || ""}
                    onChange={(e) => updateConfigField("secret_key", e.target.value)}
                    placeholder="Chave secreta da API EVO"
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">API URL (Opcional)</label>
                  <input
                    type="text"
                    value={currentConfig.config.api_url || ""}
                    onChange={(e) => updateConfigField("api_url", e.target.value)}
                    placeholder="https://evo-integracao-api.w12app.com.br/api/v2"
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                  />
                </div>
              </div>
            )}

            {activeTab === "uzap" && (
              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">Instância / API URL</label>
                  <input
                    type="text"
                    value={currentConfig.config.api_url || ""}
                    onChange={(e) => updateConfigField("api_url", e.target.value)}
                    placeholder="https://uazapi.com.br/api/v1"
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">Token da Instância</label>
                  <input
                    type="password"
                    value={currentConfig.config.token || ""}
                    onChange={(e) => updateConfigField("token", e.target.value)}
                    placeholder="Seu token da UazAPI"
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                  />
                </div>
              </div>
            )}

            <div className="flex items-center justify-between pt-6 border-t border-white/10">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={toggleAtivo}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                    currentConfig.ativo ? "bg-blue-600" : "bg-gray-700"
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      currentConfig.ativo ? "translate-x-6" : "translate-x-1"
                    }`}
                  />
                </button>
                <span className="text-sm font-medium text-gray-400">Integração Ativa</span>
              </div>

              <button
                type="submit"
                disabled={saving}
                className="bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 text-white px-10 py-4 rounded-xl font-bold flex items-center gap-2 transition-all hover:scale-[1.02] active:scale-[0.98]"
              >
                {saving ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : success ? (
                  <CheckCircle2 className="w-5 h-5" />
                ) : (
                  <Save className="w-5 h-5" />
                )}
                {success ? "Salvo" : "Salvar Configuração"}
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </div>
  );
}
