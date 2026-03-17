"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import {
  Brain, Plus, Pencil, Trash2, Save, X, Loader2, CheckCircle2,
  Sparkles, Target, Cpu, Thermometer, Hash, Send, Bot, PlayCircle,
  Mic2, MessageSquare, Eye, Zap, Activity
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

interface Personality {
  id: number;
  nome_ia: string;
  personalidade: string;
  instrucoes_base: string;
  tom_voz: string;
  model_name: string;
  temperature: number;
  max_tokens: number;
  ativo: boolean;
  usar_emoji: boolean;
}

const emptyForm = {
  nome_ia: "",
  personalidade: "",
  instrucoes_base: "",
  tom_voz: "Profissional",
  model_name: "openai/gpt-4o",
  temperature: 0.7,
  max_tokens: 1000,
  ativo: false,
  usar_emoji: true,
};

const MODELS = [
  { id: "openai/gpt-4o", label: "GPT-4o", sub: "Elite Performance" },
  { id: "openai/gpt-4.1-mini", label: "GPT-4.1 Mini", sub: "Fast & Efficient" },
  { id: "google/gemini-2.0-flash-001", label: "Gemini 2.0 Flash", sub: "Fast & Multi" },
  { id: "google/gemini-2.5-flash", label: "Gemini 2.5 Flash", sub: "Latest & Fast" },
  { id: "google/gemini-2.5-pro", label: "Gemini 2.5 Pro", sub: "Most Capable" },
];

const TONES = ["Profissional", "Amigável", "Entusiasta"];

export default function PersonalityPage() {
  const [personalities, setPersonalities] = useState<Personality[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editing, setEditing] = useState<Personality | null>(null);
  const [formData, setFormData] = useState<any>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [playHistory, setPlayHistory] = useState<{ role: string; content: string }[]>([]);
  const [testMessage, setTestMessage] = useState("");
  const [testLoading, setTestLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<"config" | "playground">("config");

  const getConfig = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } });

  useEffect(() => { fetchPersonalities(); }, []);

  const fetchPersonalities = async () => {
    setLoading(true);
    try {
      const res = await axios.get("/api-backend/management/personalities", getConfig());
      setPersonalities(res.data);
    } catch (e) {
      console.error("Erro ao carregar personalidades:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenModal = (p: Personality | null = null) => {
    setActiveTab("config");
    setPlayHistory([]);
    setTestMessage("");
    setSuccess(false);
    if (p) {
      setEditing(p);
      setFormData({
        nome_ia: p.nome_ia || "",
        personalidade: p.personalidade || "",
        instrucoes_base: p.instrucoes_base || "",
        tom_voz: p.tom_voz || "Profissional",
        model_name: p.model_name || "openai/gpt-4o",
        temperature: p.temperature ?? 0.7,
        max_tokens: p.max_tokens ?? 1000,
        ativo: p.ativo ?? false,
        usar_emoji: p.usar_emoji ?? true,
      });
    } else {
      setEditing(null);
      setFormData(emptyForm);
    }
    setIsModalOpen(true);
  };

  const doSave = async () => {
    setSaving(true);
    try {
      if (editing) {
        await axios.put(`/api-backend/management/personalities/${editing.id}`, formData, getConfig());
      } else {
        await axios.post("/api-backend/management/personalities", formData, getConfig());
      }
      setSuccess(true);
      setTimeout(() => { setSuccess(false); setIsModalOpen(false); fetchPersonalities(); }, 1500);
    } catch (e) {
      console.error("Erro ao salvar personalidade:", e);
      alert("Erro ao salvar.");
    } finally {
      setSaving(false);
    }
  };

  const handleSave = (e: React.FormEvent) => { e.preventDefault(); doSave(); };

  const handleDelete = async (id: number) => {
    if (!confirm("Excluir esta personalidade?")) return;
    try {
      await axios.delete(`/api-backend/management/personalities/${id}`, getConfig());
      fetchPersonalities();
    } catch { alert("Erro ao excluir personalidade."); }
  };

  const runTest = async () => {
    if (!testMessage.trim() || testLoading) return;
    setTestLoading(true);
    const newHistory = [...playHistory, { role: "user", content: testMessage }];
    setPlayHistory(newHistory);
    setTestMessage("");
    try {
      const res = await axios.post(
        "/api-backend/management/personalities/playground",
        {
          model_name: formData.model_name,
          instrucoes_base: formData.instrucoes_base,
          personalidade: formData.personalidade,
          tom_voz: formData.tom_voz,
          temperature: formData.temperature,
          max_tokens: formData.max_tokens,
          // envia histórico convertendo "bot" → "assistant" para o backend
          messages: newHistory.map(m => ({
            role: m.role === "bot" ? "assistant" : m.role,
            content: m.content,
          })),
        },
        getConfig()
      );
      setPlayHistory(prev => [...prev, { role: "bot", content: res.data.reply }]);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || "Erro ao conectar com a IA.";
      setPlayHistory(prev => [...prev, { role: "bot", content: `⚠️ ${detail}` }]);
    } finally {
      setTestLoading(false);
    }
  };

  const inputClass = "w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 focus:bg-slate-900/80 transition-all font-medium text-sm";

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="personality" />

      <main className="flex-1 min-w-0 overflow-auto">
        <div className="fixed top-0 right-0 w-[600px] h-[400px] bg-[#00d2ff]/3 rounded-full blur-[120px] pointer-events-none" />

        <div className="relative z-10 p-8 lg:p-10 max-w-7xl mx-auto">
          {/* Header */}
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 mb-12">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-1.5 h-5 bg-[#00d2ff] rounded-full" />
                <span className="text-[10px] font-black text-[#00d2ff] uppercase tracking-[0.4em]">Fluxo Digital & Tech</span>
              </div>
              <h1 className="text-4xl font-black tracking-tight"
                style={{ background: "linear-gradient(135deg,#fff 0%,#00d2ff 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                Inteligência Neural
              </h1>
              <p className="text-slate-500 mt-2 text-sm italic">
                Defina personalidades distintas para cada contexto de atendimento.
              </p>
            </div>

            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.97 }}
              onClick={() => handleOpenModal()}
              className="flex items-center gap-3 bg-[#00d2ff] text-black px-8 py-4 rounded-2xl font-black uppercase tracking-widest text-sm shadow-[0_0_25px_rgba(0,210,255,0.3)] hover:shadow-[0_0_40px_rgba(0,210,255,0.4)] transition-all min-w-[220px] justify-center"
            >
              <Plus className="w-5 h-5" />
              Nova Personalidade
            </motion.button>
          </div>

          {/* Grid */}
          {loading ? (
            <div className="flex items-center justify-center py-40">
              <div className="flex flex-col items-center gap-5">
                <div className="relative w-16 h-16">
                  <div className="absolute inset-0 rounded-full border-2 border-[#00d2ff]/10 animate-ping" />
                  <div className="absolute inset-0 rounded-full border-2 border-t-[#00d2ff] animate-spin" />
                  <Brain className="absolute inset-0 m-auto w-7 h-7 text-[#00d2ff]" />
                </div>
                <p className="text-slate-500 text-sm font-medium tracking-widest animate-pulse uppercase">Carregando personalidades...</p>
              </div>
            </div>
          ) : personalities.length === 0 ? (
            <div className="text-center py-40 rounded-[3rem] border border-dashed border-white/5 bg-white/[0.01]">
              <div className="w-20 h-20 bg-[#00d2ff]/5 rounded-3xl flex items-center justify-center mx-auto mb-6 border border-[#00d2ff]/10">
                <Brain className="w-10 h-10 text-[#00d2ff]/30" />
              </div>
              <p className="text-slate-400 font-black uppercase tracking-widest">Nenhuma personalidade criada</p>
              <p className="text-slate-600 text-sm mt-2">Crie sua primeira personalidade de IA para começar.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              <AnimatePresence mode="popLayout">
                {personalities.map((p, i) => (
                  <motion.div
                    layout
                    key={p.id}
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05 }}
                    className="relative bg-slate-900/50 border border-white/5 hover:border-[#00d2ff]/25 rounded-3xl overflow-hidden group transition-all duration-400"
                    style={{ backdropFilter: "blur(20px)" }}
                  >
                    <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-[#00d2ff]/0 to-transparent group-hover:via-[#00d2ff]/30 transition-all duration-500" />

                    <div className="p-6">
                      <div className="flex justify-between items-start mb-5">
                        <div className="w-12 h-12 rounded-2xl bg-[#00d2ff]/10 border border-[#00d2ff]/20 flex items-center justify-center text-[#00d2ff] group-hover:scale-110 transition-transform duration-400">
                          <Brain className="w-6 h-6" />
                        </div>
                        <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => handleOpenModal(p)}
                            className="p-2.5 bg-white/5 hover:bg-[#00d2ff]/15 rounded-xl text-slate-400 hover:text-[#00d2ff] transition-all border border-white/5 hover:border-[#00d2ff]/20"
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleDelete(p.id)}
                            className="p-2.5 bg-white/5 hover:bg-red-500/15 rounded-xl text-slate-400 hover:text-red-400 transition-all border border-white/5 hover:border-red-500/20"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>

                      <h3 className="text-xl font-black group-hover:text-[#00d2ff] transition-colors uppercase tracking-tight leading-tight mb-1">
                        {p.nome_ia || "Sem nome"}
                      </h3>

                      <div className="flex items-center gap-2 mb-4">
                        <span className={`w-1.5 h-1.5 rounded-full ${p.ativo ? "bg-emerald-400 shadow-[0_0_6px_#34d399]" : "bg-slate-600"}`} />
                        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.25em]">
                          {p.ativo ? "Online" : "Pausada"}
                        </p>
                      </div>

                      <div className="space-y-2.5 pt-4 border-t border-white/5">
                        <div className="flex items-center gap-2.5 text-xs text-slate-400">
                          <Mic2 className="w-3.5 h-3.5 text-[#00d2ff]/40 shrink-0" />
                          <span>{p.tom_voz}</span>
                        </div>
                        <div className="flex items-center gap-2.5 text-xs text-slate-400">
                          <Cpu className="w-3.5 h-3.5 text-[#00d2ff]/40 shrink-0" />
                          <span className="truncate">{MODELS.find(m => m.id === p.model_name)?.label || p.model_name}</span>
                        </div>
                        <div className="flex items-center gap-2.5 text-xs text-slate-400">
                          <Thermometer className="w-3.5 h-3.5 text-[#00d2ff]/40 shrink-0" />
                          <span>Temp: {p.temperature} · Tokens: {p.max_tokens}</span>
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={() => handleOpenModal(p)}
                      className="w-full px-6 py-4 bg-white/[0.02] hover:bg-[#00d2ff]/5 border-t border-white/5 text-[10px] font-black uppercase tracking-[0.25em] text-slate-500 hover:text-[#00d2ff] transition-all flex items-center justify-center gap-2"
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
                    {editing ? <Brain className="w-7 h-7 text-[#00d2ff]" /> : <Plus className="w-7 h-7 text-[#00d2ff]" />}
                  </div>
                  <div>
                    <h2 className="text-2xl font-black tracking-tight">
                      {editing ? "Editar Personalidade" : "Nova Personalidade"}
                    </h2>
                    <p className="text-slate-500 text-sm mt-0.5">
                      {editing ? editing.nome_ia : "Configure a inteligência do seu agente"}
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
              <div className="px-10 py-4 border-b border-white/5 bg-slate-900/10 flex gap-3 flex-shrink-0">
                <button
                  onClick={() => setActiveTab("config")}
                  className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all ${
                    activeTab === "config"
                      ? "bg-[#00d2ff]/15 text-[#00d2ff] border border-[#00d2ff]/25"
                      : "text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent"
                  }`}
                >
                  <Sparkles className="w-4 h-4" /> Configuração
                </button>
                <button
                  onClick={() => setActiveTab("playground")}
                  className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all ${
                    activeTab === "playground"
                      ? "bg-[#00d2ff]/15 text-[#00d2ff] border border-[#00d2ff]/25"
                      : "text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent"
                  }`}
                >
                  <PlayCircle className="w-4 h-4" /> Playground
                </button>
              </div>

              {/* Modal Body */}
              <div className="flex-1 overflow-y-auto custom-scrollbar">
                <form id="personalityForm" onSubmit={handleSave}>
                  {activeTab === "config" && (
                    <div className="p-10">
                      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
                        {/* Left: texts */}
                        <div className="lg:col-span-7 space-y-7">
                          {/* Nome da IA */}
                          <div className="space-y-3">
                            <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-2">
                              <Mic2 className="w-3.5 h-3.5 text-[#00d2ff]/50" /> Nome da IA *
                            </label>
                            <input
                              required
                              type="text"
                              value={formData.nome_ia}
                              onChange={e => setFormData({ ...formData, nome_ia: e.target.value })}
                              className={inputClass}
                              placeholder="Ex: Clara, Atlas, Nova..."
                            />
                          </div>

                          {/* Objetivo */}
                          <div className="space-y-3">
                            <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-2">
                              <Target className="w-3.5 h-3.5 text-[#00d2ff]/50" /> Objetivo Estratégico
                            </label>
                            <textarea
                              rows={3}
                              value={formData.personalidade}
                              onChange={e => setFormData({ ...formData, personalidade: e.target.value })}
                              className={`${inputClass} resize-none`}
                              placeholder="Defina o propósito vital desta IA..."
                            />
                          </div>

                          {/* Instruções */}
                          <div className="space-y-3">
                            <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-2">
                              <MessageSquare className="w-3.5 h-3.5 text-[#00d2ff]/50" /> Cérebro Cognitivo (Instruções Base)
                            </label>
                            <textarea
                              rows={9}
                              value={formData.instrucoes_base}
                              onChange={e => setFormData({ ...formData, instrucoes_base: e.target.value })}
                              className={`${inputClass} resize-none font-mono text-xs text-[#00d2ff]/80 leading-relaxed`}
                              placeholder="Diretrizes técnicas, limites éticos e fluxos de conversa..."
                            />
                            <div className="p-3 bg-[#00d2ff]/5 border border-[#00d2ff]/10 rounded-2xl flex items-center gap-3">
                              <Sparkles className="w-3.5 h-3.5 text-[#00d2ff] animate-pulse flex-shrink-0" />
                              <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">
                                Use [VARIAVEIS] para dados dinâmicos das unidades.
                              </p>
                            </div>
                          </div>
                        </div>

                        {/* Right: controls */}
                        <div className="lg:col-span-5 space-y-6">
                          {/* Engine */}
                          <div className="bg-[#00d2ff]/5 border border-[#00d2ff]/20 rounded-3xl p-6">
                            <h4 className="text-sm font-black flex items-center gap-2 mb-5">
                              <Cpu className="w-4 h-4 text-[#00d2ff]" /> Motor (Core Engine)
                            </h4>
                            <div className="space-y-2">
                              {MODELS.map(m => (
                                <button
                                  key={m.id}
                                  type="button"
                                  onClick={() => setFormData({ ...formData, model_name: m.id })}
                                  className={`w-full flex items-center justify-between p-3.5 rounded-2xl border transition-all text-left ${
                                    formData.model_name === m.id
                                      ? "bg-[#00d2ff]/20 border-[#00d2ff] text-[#00d2ff]"
                                      : "bg-black/20 border-white/5 text-slate-500 hover:text-white"
                                  }`}
                                >
                                  <div>
                                    <p className="text-xs font-black uppercase">{m.label}</p>
                                    <p className="text-[9px] opacity-60">{m.sub}</p>
                                  </div>
                                  {formData.model_name === m.id && <CheckCircle2 className="w-4 h-4" />}
                                </button>
                              ))}
                            </div>
                          </div>

                          {/* Tone */}
                          <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-6">
                            <h4 className="text-sm font-black flex items-center gap-2 mb-5">
                              <Mic2 className="w-4 h-4 text-[#00d2ff]" /> Tom de Voz
                            </h4>
                            <div className="space-y-2">
                              {TONES.map(tom => (
                                <button
                                  key={tom}
                                  type="button"
                                  onClick={() => setFormData({ ...formData, tom_voz: tom })}
                                  className={`w-full px-4 py-3 rounded-2xl border font-black uppercase tracking-widest text-xs transition-all flex items-center justify-between ${
                                    formData.tom_voz === tom
                                      ? "bg-[#00d2ff]/20 border-[#00d2ff] text-[#00d2ff]"
                                      : "bg-black/20 border-white/5 text-slate-500 hover:text-white"
                                  }`}
                                >
                                  {tom}
                                  {formData.tom_voz === tom && <CheckCircle2 className="w-4 h-4" />}
                                </button>
                              ))}
                            </div>
                          </div>

                          {/* Sliders */}
                          <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-6 space-y-5">
                            <div>
                              <div className="flex justify-between text-[10px] font-black uppercase tracking-widest text-slate-500 mb-2">
                                <span className="flex items-center gap-1.5"><Thermometer className="w-3 h-3" />Temperatura</span>
                                <span className="text-[#00d2ff]">{formData.temperature}</span>
                              </div>
                              <input type="range" min="0" max="1" step="0.1" value={formData.temperature}
                                onChange={e => setFormData({ ...formData, temperature: parseFloat(e.target.value) })}
                                className="w-full accent-[#00d2ff] h-1.5 bg-white/5 rounded-full appearance-none cursor-pointer" />
                              <div className="flex justify-between text-[9px] text-slate-600 mt-1">
                                <span>Preciso</span><span>Criativo</span>
                              </div>
                            </div>
                            <div>
                              <div className="flex justify-between text-[10px] font-black uppercase tracking-widest text-slate-500 mb-2">
                                <span className="flex items-center gap-1.5"><Hash className="w-3 h-3" />Max Tokens</span>
                                <span className="text-[#00d2ff]">{formData.max_tokens}</span>
                              </div>
                              <input type="range" min="100" max="4000" step="100" value={formData.max_tokens}
                                onChange={e => setFormData({ ...formData, max_tokens: parseInt(e.target.value) })}
                                className="w-full accent-[#00d2ff] h-1.5 bg-white/5 rounded-full appearance-none cursor-pointer" />
                            </div>
                          </div>

                          {/* Status toggle */}
                          <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-5 flex items-center justify-between">
                            <div>
                              <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Atendimento</p>
                              <p className={`text-[9px] font-black uppercase mt-0.5 ${formData.ativo ? "text-emerald-400" : "text-slate-600"}`}>
                                {formData.ativo ? "● Online" : "○ Pausada"}
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => setFormData({ ...formData, ativo: !formData.ativo })}
                              className={`relative inline-flex h-7 w-12 items-center rounded-full transition-all ${formData.ativo ? "bg-emerald-500" : "bg-slate-700"}`}
                            >
                              <span className={`inline-block h-5 w-5 transform rounded-full bg-white transition-all shadow ${formData.ativo ? "translate-x-6" : "translate-x-1"}`} />
                            </button>
                          </div>

                          {/* Emoji toggle */}
                          <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-5 flex items-center justify-between">
                            <div>
                              <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Emojis nas mensagens</p>
                              <p className={`text-[9px] font-black uppercase mt-0.5 ${formData.usar_emoji ? "text-[#00d2ff]" : "text-slate-600"}`}>
                                {formData.usar_emoji ? "● Ativados" : "○ Desativados"}
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => setFormData({ ...formData, usar_emoji: !formData.usar_emoji })}
                              className={`relative inline-flex h-7 w-12 items-center rounded-full transition-all ${formData.usar_emoji ? "bg-[#00d2ff]" : "bg-slate-700"}`}
                            >
                              <span className={`inline-block h-5 w-5 transform rounded-full bg-white transition-all shadow ${formData.usar_emoji ? "translate-x-6" : "translate-x-1"}`} />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {activeTab === "playground" && (
                    <div className="p-10">
                      <div className="mb-6 p-4 bg-emerald-500/5 border border-emerald-500/20 rounded-2xl flex items-center justify-between gap-3">
                        <div className="flex items-center gap-3">
                          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse flex-shrink-0" />
                          <p className="text-xs text-emerald-300 font-bold">
                            IA real — conversando com <span className="text-white">{MODELS.find(m => m.id === formData.model_name)?.label || formData.model_name}</span>
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setPlayHistory([])}
                          className="text-[10px] text-slate-500 hover:text-white font-bold uppercase tracking-widest transition-colors"
                        >
                          Limpar
                        </button>
                      </div>
                      <div className="bg-slate-950/60 rounded-2xl p-5 min-h-[300px] mb-5 border border-white/5 flex flex-col gap-3">
                        {playHistory.length === 0 ? (
                          <div className="flex-1 flex flex-col items-center justify-center text-center opacity-40 py-12">
                            <Bot className="w-12 h-12 mb-3" />
                            <p className="text-sm font-bold">Converse com a IA agora mesmo.</p>
                            <p className="text-xs mt-1 opacity-70">As configurações desta tela são usadas em tempo real.</p>
                          </div>
                        ) : playHistory.map((m, i) => (
                          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                            <div className={`max-w-[80%] p-3.5 rounded-2xl text-sm ${
                              m.role === "user"
                                ? "bg-[#00d2ff] text-black font-bold"
                                : "bg-white/5 text-slate-300 border border-white/5"
                            }`}>
                              {m.content}
                            </div>
                          </div>
                        ))}
                        {testLoading && (
                          <div className="flex items-center gap-2 text-xs text-[#00d2ff]">
                            <Loader2 className="w-3 h-3 animate-spin" />
                            <span className="animate-pulse">Pensando...</span>
                          </div>
                        )}
                      </div>
                      <div className="relative">
                        <input
                          type="text"
                          value={testMessage}
                          onChange={e => setTestMessage(e.target.value)}
                          onKeyDown={e => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              e.stopPropagation();
                              runTest();
                            }
                          }}
                          placeholder="Digite sua mensagem e pressione Enter..."
                          className={`${inputClass} pr-16`}
                        />
                        <button
                          type="button"
                          onClick={runTest}
                          className="absolute right-3 top-1/2 -translate-y-1/2 p-3 bg-[#00d2ff] text-black rounded-xl hover:bg-[#00d2ff]/90 transition-all"
                        >
                          <Send className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  )}
                </form>
              </div>

              {/* Footer */}
              <div className="px-10 py-7 bg-slate-900/30 border-t border-white/5 flex justify-end gap-4 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-8 py-4 rounded-2xl font-bold text-sm text-slate-500 hover:text-white hover:bg-white/5 transition-all uppercase tracking-wider"
                >
                  Cancelar
                </button>
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  type="button"
                  disabled={saving}
                  onClick={doSave}
                  className="bg-[#00d2ff] text-black px-12 py-4 rounded-2xl font-black uppercase tracking-widest text-sm flex items-center gap-3 transition-all shadow-[0_0_25px_rgba(0,210,255,0.25)] disabled:opacity-50"
                >
                  {saving
                    ? <><Loader2 className="w-5 h-5 animate-spin" /> Salvando...</>
                    : success
                    ? <><CheckCircle2 className="w-5 h-5" /> Salvo!</>
                    : <><Save className="w-5 h-5" /> Salvar Personalidade</>}
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
