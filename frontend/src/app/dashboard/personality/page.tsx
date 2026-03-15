"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { Brain, Save, Loader2, CheckCircle2, ArrowLeft } from "lucide-react";
import { motion } from "framer-motion";

interface PersonalityData {
  nome_ia: string;
  objetivo_geral: string;
  instrucoes_comportamento: string;
  tom_de_voz: string;
  ativo: boolean;
}

export default function PersonalityPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [data, setData] = useState<PersonalityData>({
    nome_ia: "",
    objetivo_geral: "",
    instrucoes_comportamento: "",
    tom_de_voz: "Profissional",
    ativo: false,
  });

  useEffect(() => {
    fetchPersonality();
  }, []);

  const fetchPersonality = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await axios.get("/api-backend/management/personality", {
        headers: { Authorization: `Bearer ${token}` }
      });
      setData(response.data);
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
      const token = localStorage.getItem("token");
      await axios.put("/api-backend/management/personality", data, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (error) {
      console.error("Erro ao salvar:", error);
      alert("Erro ao salvar alterações.");
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
              <Brain className="w-8 h-8 text-blue-500" />
              Personalidade da IA
            </h1>
            <p className="text-gray-400 mt-1">Configure como sua IA deve se comportar e interagir com os clientes.</p>
          </div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-white/5 border border-white/10 rounded-2xl p-8 backdrop-blur-xl"
        >
          <form onSubmit={handleSave} className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-2">Nome da IA</label>
                <input
                  type="text"
                  value={data.nome_ia}
                  onChange={(e) => setData({ ...data, nome_ia: e.target.value })}
                  placeholder="Ex: Assistente Digital"
                  className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-2">Tom de Voz</label>
                <select
                  value={data.tom_de_voz}
                  onChange={(e) => setData({ ...data, tom_de_voz: e.target.value })}
                  className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
                >
                  <option value="Profissional">Profissional & Cortês</option>
                  <option value="Amigável">Amigável & Descontraído</option>
                  <option value="Entusiasta">Entusiasta & Motivador</option>
                  <option value="Direto">Direto & Eficiente</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-2">Objetivo Geral</label>
              <textarea
                value={data.objetivo_geral}
                onChange={(e) => setData({ ...data, objetivo_geral: e.target.value })}
                rows={3}
                placeholder="Qual o principal objetivo da IA? Ex: Tirar dúvidas sobre planos e converter agendamentos."
                className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all resize-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-2">Instruções de Comportamento</label>
              <textarea
                value={data.instrucoes_comportamento}
                onChange={(e) => setData({ ...data, instrucoes_comportamento: e.target.value })}
                rows={6}
                placeholder="Detalhe o comportamento. Ex: Seja prestativo, não use termos técnicos complexos, sempre finalize com uma pergunta."
                className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all resize-none"
              />
            </div>

            <div className="flex items-center justify-between pt-4">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setData({ ...data, ativo: !data.ativo })}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                    data.ativo ? "bg-blue-600" : "bg-gray-700"
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      data.ativo ? "translate-x-6" : "translate-x-1"
                    }`}
                  />
                </button>
                <span className="text-sm font-medium text-gray-400">IA Ativa para Clientes</span>
              </div>

              <button
                type="submit"
                disabled={saving}
                className="bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 text-white px-8 py-3 rounded-xl font-bold flex items-center gap-2 transition-all hover:scale-[1.02] active:scale-[0.98]"
              >
                {saving ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Salvando...
                  </>
                ) : success ? (
                  <>
                    <CheckCircle2 className="w-5 h-5" />
                    Salvo com Sucesso
                  </>
                ) : (
                  <>
                    <Save className="w-5 h-5" />
                    Salvar Alterações
                  </>
                )}
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </div>
  );
}
