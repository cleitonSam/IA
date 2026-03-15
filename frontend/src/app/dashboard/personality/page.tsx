"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { Brain, Save, Loader2, CheckCircle2, ArrowLeft, MessageSquare, Mic2, Sparkles, Smile, Target } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface Personality {
  nome_ia: string;
  personalidade: string;
  instrucoes_base: string;
  tom_voz: string;
  ativo: boolean;
}

export default function PersonalityPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [personality, setPersonality] = useState<Personality>({
    nome_ia: "",
    personalidade: "",
    instrucoes_base: "",
    tom_voz: "Profissional",
    ativo: false
  });

  const getConfig = () => ({
    headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }
  });

  useEffect(() => {
    fetchPersonality();
  }, []);

  const fetchPersonality = async () => {
    try {
      const response = await axios.get("/api-backend/management/personality", getConfig());
      setPersonality(response.data);
    } catch (error) {
      console.error("Erro ao buscar personalidade:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSuccess(false);
    try {
      await axios.put("/api-backend/management/personality", personality, getConfig());
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (error) {
      console.error("Erro ao salvar personalidade:", error);
      alert("Erro ao salvar alterações.");
    } finally {
      setSaving(false);
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
    <div className="min-h-screen bg-[#050505] text-white p-6 md:p-12">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-10">
          <a href="/dashboard" className="p-3 hover:bg-white/5 rounded-2xl transition-all border border-white/5">
            <ArrowLeft className="w-5 h-5" />
          </a>
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-3">
              <Brain className="w-8 h-8 text-blue-500" />
              Estratégia Neural da IA
            </h1>
            <p className="text-gray-400 mt-1">Modele o comportamento e a lógica de interação do seu agente Fluxo.</p>
          </div>
        </div>

        <form onSubmit={handleSave} className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Main Configs */}
          <div className="lg:col-span-2 space-y-6">
            <motion.div 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-white/[0.03] border border-white/10 rounded-3xl p-8 backdrop-blur-xl"
            >
              <h3 className="text-lg font-bold flex items-center gap-2 mb-6">
                <Sparkles className="w-5 h-5 text-blue-400" />
                Instruções Centrais
              </h3>
              
              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2 flex items-center gap-2">
                    <Target className="w-4 h-4" /> Objetivo Geral
                  </label>
                  <textarea
                    rows={4}
                    value={personality.personalidade}
                    onChange={(e) => setPersonality({ ...personality, personalidade: e.target.value })}
                    className="w-full bg-black/40 border border-white/10 rounded-2xl px-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all resize-none"
                    placeholder="Qual o principal objetivo da IA? Ex: Vendas diretas, suporte técnico, agendamentos..."
                  />
                  <p className="text-[10px] text-gray-500 mt-2 px-1">Este objetivo orienta todas as decisões que a IA toma durante a conversa.</p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2 flex items-center gap-2">
                    <MessageSquare className="w-4 h-4" /> Comportamento & Regras
                  </label>
                  <textarea
                    rows={10}
                    value={personality.instrucoes_base}
                    onChange={(e) => setPersonality({ ...personality, instrucoes_base: e.target.value })}
                    className="w-full bg-black/40 border border-white/10 rounded-2xl px-5 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all resize-none font-mono text-sm"
                    placeholder="Diretrizes específicas. Ex: - Foco em conversão tecnológica - Linguagem moderna e direta - Coletar leads qualificados..."
                  />
                  <p className="text-[10px] text-gray-500 mt-2 px-1">Defina diretrizes rígidas, restrições e o estilo de interação desejado.</p>
                </div>
              </div>
            </motion.div>
          </div>

          {/* Sidebar Configs */}
          <div className="space-y-6">
            <motion.div 
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              className="bg-white/5 border border-white/10 rounded-3xl p-8 backdrop-blur-xl"
            >
              <h3 className="text-lg font-bold flex items-center gap-2 mb-6">
                <Mic2 className="w-5 h-5 text-blue-400" />
                Voz & Identidade
              </h3>

              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">Nome da IA</label>
                  <input
                    type="text"
                    value={personality.nome_ia}
                    onChange={(e) => setPersonality({ ...personality, nome_ia: e.target.value })}
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                    placeholder="Ex: Fluxo IA, Assistente Tech..."
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2 flex items-center gap-2">
                    <Smile className="w-4 h-4" /> Tom de Voz
                  </label>
                  <div className="grid grid-cols-1 gap-2">
                    {["Profissional", "Amigável", "Descontraído", "Entusiasta"].map((tom) => (
                      <button
                        key={tom}
                        type="button"
                        onClick={() => setPersonality({ ...personality, tom_voz: tom })}
                        className={`flex items-center justify-between px-4 py-3 rounded-xl border transition-all text-sm font-medium ${
                          personality.tom_voz === tom 
                            ? "bg-blue-600/20 border-blue-500 text-blue-100 shadow-lg shadow-blue-500/10" 
                            : "bg-black/20 border-white/5 text-gray-500 hover:text-gray-300 hover:border-white/10"
                        }`}
                      >
                        {tom}
                        {personality.tom_voz === tom && <CheckCircle2 className="w-4 h-4" />}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="pt-4 border-t border-white/5">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-bold">IA Ativa</p>
                      <p className="text-[10px] text-gray-500">Habilita/Desabilita respostas automáticas</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setPersonality({ ...personality, ativo: !personality.ativo })}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                        personality.ativo ? "bg-blue-600" : "bg-gray-700"
                      }`}
                    >
                      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        personality.ativo ? "translate-x-6" : "translate-x-1"
                      }`} />
                    </button>
                  </div>
                </div>
              </div>
            </motion.div>

            <button
              type="submit"
              disabled={saving}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 text-white py-4 rounded-2xl font-bold flex items-center justify-center gap-2 transition-all shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-[0.98]"
            >
              {saving ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : success ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-300" />
              ) : (
                <Save className="w-5 h-5" />
              )}
              {saving ? "Salvando..." : success ? "Sucesso!" : "Salvar Configuração"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
