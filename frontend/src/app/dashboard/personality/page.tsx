"use client";

import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import {
  Brain, Plus, Pencil, Trash2, Save, X, Loader2, CheckCircle2,
  Sparkles, Target, Cpu, Thermometer, Send, Bot, PlayCircle,
  Mic2, MessageSquare, Eye, Clock, TrendingUp, ShieldAlert, ListChecks
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

type DiaKey = "segunda" | "terca" | "quarta" | "quinta" | "sexta" | "sabado" | "domingo";

interface Periodo {
  inicio: string;
  fim: string;
}

interface HorarioAtendimento {
  tipo: "dia_todo" | "horario_especifico";
  dias: Record<DiaKey, Periodo[]>;
}

const DIAS_SEMANA: { key: DiaKey; label: string }[] = [
  { key: "segunda", label: "Segunda-feira" },
  { key: "terca",   label: "Terça-feira"   },
  { key: "quarta",  label: "Quarta-feira"  },
  { key: "quinta",  label: "Quinta-feira"  },
  { key: "sexta",   label: "Sexta-feira"   },
  { key: "sabado",  label: "Sábado"        },
  { key: "domingo", label: "Domingo"       },
];

const HORARIO_DEFAULT: HorarioAtendimento = {
  tipo: "horario_especifico",
  dias: {
    segunda: [{ inicio: "08:00", fim: "18:00" }],
    terca:   [{ inicio: "08:00", fim: "18:00" }],
    quarta:  [{ inicio: "08:00", fim: "18:00" }],
    quinta:  [{ inicio: "08:00", fim: "18:00" }],
    sexta:   [{ inicio: "08:00", fim: "18:00" }],
    sabado:  [],
    domingo: [],
  },
};

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
  horario_atendimento_ia: HorarioAtendimento | null;
  menu_triagem: Record<string, unknown> | null;
  idioma: string;
  objetivos_venda: string;
  metas_comerciais: string;
  script_vendas: string;
  scripts_objecoes: string;
  frases_fechamento: string;
  diferenciais: string;
  posicionamento: string;
  publico_alvo: string;
  restricoes: string;
  linguagem_proibida: string;
  contexto_empresa: string;
  contexto_extra: string;
  abordagem_proativa: string;
  exemplos: string;
  palavras_proibidas: string;
  despedida_personalizada: string;
  regras_formatacao: string;
  regras_seguranca: string;
  emoji_tipo: string;
  emoji_cor: string;
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
  horario_atendimento_ia: null as HorarioAtendimento | null,
  menu_triagem: null as Record<string, unknown> | null,
  idioma: "Português do Brasil",
  objetivos_venda: "",
  metas_comerciais: "",
  script_vendas: "",
  scripts_objecoes: "",
  frases_fechamento: "",
  diferenciais: "",
  posicionamento: "",
  publico_alvo: "",
  restricoes: "",
  linguagem_proibida: "",
  contexto_empresa: "",
  contexto_extra: "",
  abordagem_proativa: "",
  exemplos: "",
  palavras_proibidas: "",
  despedida_personalizada: "",
  regras_formatacao: "",
  regras_seguranca: "",
  emoji_tipo: "Moderno",
  emoji_cor: "Multicolorido",
};

const MODELS = [
  { id: "openai/gpt-4o", label: "GPT-4o", sub: "Elite Performance" },
  { id: "openai/gpt-4.1-mini", label: "GPT-4.1 Mini", sub: "Fast & Efficient" },
  { id: "google/gemini-2.0-flash-001", label: "Gemini 2.0 Flash", sub: "Fast & Multi" },
  { id: "google/gemini-2.5-flash", label: "Gemini 2.5 Flash", sub: "Latest & Fast" },
  { id: "google/gemini-2.5-pro", label: "Gemini 2.5 Pro", sub: "Most Capable" },
];

const TONES = ["Profissional", "Amigável", "Entusiasta"];

const EMOJI_CATEGORIES = [
  { label: "Rostos", emojis: ["😊", "😇", "🙂", "😉", "😍", "😎", "🤓", "🧐", "🥳", "🤖"] },
  { label: "Símbolos", emojis: ["✨", "💎", "🔥", "🚀", "💡", "✅", "💙", "⭐", "🎉", "📢"] },
  { label: "Negócios", emojis: ["💼", "📈", "💰", "🤝", "📅", "✉️", "📱", "🏢", "🏆", "🎯"] },
];

export default function PersonalityPage() {
  const [personalities, setPersonalities] = useState<Personality[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editing, setEditing] = useState<Personality | null>(null);
  const [formData, setFormData] = useState<Personality | typeof emptyForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [playHistory, setPlayHistory] = useState<{ role: string; content: string }[]>([]);
  const [testMessage, setTestMessage] = useState("");
  const [testLoading, setTestLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<"config" | "playground">("config");
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);

  const getConfig = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } });

  const fetchPersonalities = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get("/api-backend/management/personalities", getConfig());
      setPersonalities(res.data);
    } catch (e) {
      console.error("Erro ao carregar personalidades:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPersonalities();
  }, [fetchPersonalities]);

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
        horario_atendimento_ia: p.horario_atendimento_ia ?? null,
        menu_triagem: p.menu_triagem ?? null,
        idioma: p.idioma || "Português do Brasil",
        objetivos_venda: p.objetivos_venda || "",
        metas_comerciais: p.metas_comerciais || "",
        script_vendas: p.script_vendas || "",
        scripts_objecoes: p.scripts_objecoes || "",
        frases_fechamento: p.frases_fechamento || "",
        diferenciais: p.diferenciais || "",
        posicionamento: p.posicionamento || "",
        publico_alvo: p.publico_alvo || "",
        restricoes: p.restricoes || "",
        linguagem_proibida: p.linguagem_proibida || "",
        contexto_empresa: p.contexto_empresa || "",
        contexto_extra: p.contexto_extra || "",
        abordagem_proativa: p.abordagem_proativa || "",
        exemplos: p.exemplos || "",
        palavras_proibidas: p.palavras_proibidas || "",
        despedida_personalizada: p.despedida_personalizada || "",
        regras_formatacao: p.regras_formatacao || "",
        regras_seguranca: p.regras_seguranca || "",
        emoji_tipo: p.emoji_tipo || "Moderno",
        emoji_cor: p.emoji_cor || "Multicolorido",
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
      // Filtrar campos para evitar erro 422 (Pydantic não aceita id no body)
      const { id, ...payload } = formData as any;
      console.log("Salvando personalidade:", payload);

      if (editing) {
        await axios.put(`/api-backend/management/personalities/${editing.id}`, payload, getConfig());
      } else {
        await axios.post("/api-backend/management/personalities", payload, getConfig());
      }
      setSuccess(true);
      setTimeout(() => { setSuccess(false); setIsModalOpen(false); fetchPersonalities(); }, 1500);
    } catch (e) {
      console.error("Erro ao salvar personalidade:", e);
      alert("Erro ao salvar. Verifique se todos os campos obrigatórios estão preenchidos.");
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
    } catch (err: unknown) {
      let detail = "Erro ao conectar com a IA.";
      if (axios.isAxiosError(err)) {
        detail = err.response?.data?.detail || detail;
      }
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
                          </div>

                          {/* --- ESTRATÉGIA DE VENDAS --- */}
                          <div className="p-8 bg-slate-900/40 border border-white/5 rounded-4xl space-y-6">
                            <h4 className="text-xs font-black text-[#00d2ff] uppercase tracking-widest flex items-center gap-2 mb-2">
                              <TrendingUp className="w-4 h-4" /> Estratégia de Vendas & Conversão
                            </h4>
                            
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                              <div className="space-y-2">
                                <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Idioma</label>
                                <input type="text" value={formData.idioma} onChange={e => setFormData({...formData, idioma: e.target.value})} className={inputClass} placeholder="Português do Brasil" />
                              </div>
                              <div className="space-y-2">
                                <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Metas Comerciais</label>
                                <input type="text" value={formData.metas_comerciais} onChange={e => setFormData({...formData, metas_comerciais: e.target.value})} className={inputClass} placeholder="Agendamentos, vendas..." />
                              </div>
                            </div>

                            <div className="space-y-2">
                              <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Objetivos de Venda</label>
                              <textarea rows={2} value={formData.objetivos_venda} onChange={e => setFormData({...formData, objetivos_venda: e.target.value})} className={`${inputClass} resize-none`} placeholder="Qual o foco principal da venda?" />
                            </div>

                            <div className="space-y-2">
                              <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Script de Vendas Principal</label>
                              <textarea rows={4} value={formData.script_vendas} onChange={e => setFormData({...formData, script_vendas: e.target.value})} className={`${inputClass} resize-none`} placeholder="Passo a passo da abordagem comercial..." />
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                              <div className="space-y-2">
                                <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Scripts de Objeções</label>
                                <textarea rows={3} value={formData.scripts_objecoes} onChange={e => setFormData({...formData, scripts_objecoes: e.target.value})} className={`${inputClass} resize-none`} placeholder="Como contornar 'está caro', 'vou ver com meu marido'..." />
                              </div>
                              <div className="space-y-2">
                                <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Frases de Fechamento</label>
                                <textarea rows={3} value={formData.frases_fechamento} onChange={e => setFormData({...formData, frases_fechamento: e.target.value})} className={`${inputClass} resize-none`} placeholder="Chamadas para ação (CTA) poderosas..." />
                              </div>
                            </div>
 
                            <div className="space-y-2">
                              <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Abordagem Proativa (Follow-ups/Ofertas)</label>
                              <textarea rows={2} value={formData.abordagem_proativa} onChange={e => setFormData({...formData, abordagem_proativa: e.target.value})} className={`${inputClass} resize-none`} placeholder="Ex: Sempre ofereça uma aula experimental gratuita se o cliente demonstrar interesse..." />
                            </div>
                          </div>

                          {/* --- BRANDING & PÚBLICO --- */}
                          <div className="p-8 bg-slate-900/40 border border-white/5 rounded-4xl space-y-6">
                            <h4 className="text-xs font-black text-[#00d2ff] uppercase tracking-widest flex items-center gap-2 mb-2">
                              <Bot className="w-4 h-4" /> Branding & Posicionamento
                            </h4>
                            
                            <div className="space-y-2">
                              <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Diferenciais da Unidade/Empresa</label>
                              <textarea rows={3} value={formData.diferenciais} onChange={e => setFormData({...formData, diferenciais: e.target.value})} className={`${inputClass} resize-none`} placeholder="Piscina aquecida, vestiário premium, professores especializados..." />
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                              <div className="space-y-2">
                                <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Posicionamento da Marca</label>
                                <input type="text" value={formData.posicionamento} onChange={e => setFormData({...formData, posicionamento: e.target.value})} className={inputClass} placeholder="Líder em preço baixo, Boutique premium..." />
                              </div>
                              <div className="space-y-2">
                                <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Público-Alvo Ideal</label>
                                <input type="text" value={formData.publico_alvo} onChange={e => setFormData({...formData, publico_alvo: e.target.value})} className={inputClass} placeholder="Mulheres 20-40 anos, Atletas de alta performance..." />
                              </div>
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

                          {/* Alma & Estética (Emojis & Cores) - Estilo WhatsApp */}
                          <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-6 space-y-6 shadow-xl shadow-black/20 overflow-visible">
                            <h4 className="text-sm font-black flex items-center gap-2">
                              <Sparkles className="w-4 h-4 text-[#00d2ff]" /> Alma & Estética (Visual)
                            </h4>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                              {/* Lado Esquerdo: Seletores */}
                              <div className="space-y-6">
                                <div className="space-y-3 relative">
                                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Emoji Principal / Estilo</label>
                                  <div className="flex items-center gap-3">
                                    <button
                                      type="button"
                                      onClick={() => setShowEmojiPicker(!showEmojiPicker)}
                                      className="w-14 h-14 rounded-2xl bg-black/40 border border-white/10 flex items-center justify-center text-3xl hover:bg-black/60 transition-all shadow-inner"
                                    >
                                      {formData.emoji_tipo || "✨"}
                                    </button>
                                    <div className="text-[10px] text-slate-500 font-medium leading-tight">
                                      Clique para abrir o <br/>seletor de emojis
                                    </div>
                                  </div>

                                  <AnimatePresence>
                                    {showEmojiPicker && (
                                      <motion.div
                                        initial={{ opacity: 0, y: 10, scale: 0.95 }}
                                        animate={{ opacity: 1, y: 0, scale: 1 }}
                                        exit={{ opacity: 0, y: 10, scale: 0.95 }}
                                        className="absolute z-50 top-full mt-3 left-0 w-64 bg-slate-900 border border-white/10 rounded-3xl p-4 shadow-2xl backdrop-blur-xl"
                                      >
                                        <div className="flex items-center justify-between mb-3 border-b border-white/5 pb-2">
                                          <span className="text-[10px] font-black text-[#00d2ff] uppercase">Escolha um Emoji</span>
                                          <button type="button" onClick={() => setShowEmojiPicker(false)}><X className="w-3 h-3" /></button>
                                        </div>
                                        <div className="space-y-4 max-h-60 overflow-y-auto pr-1 custom-scrollbar">
                                          {EMOJI_CATEGORIES.map(cat => (
                                            <div key={cat.label}>
                                              <p className="text-[9px] font-black text-slate-600 uppercase mb-2 tracking-tighter">{cat.label}</p>
                                              <div className="grid grid-cols-5 gap-2">
                                                {cat.emojis.map(e => (
                                                  <button
                                                    key={e}
                                                    type="button"
                                                    onClick={() => {
                                                      setFormData({ ...formData, emoji_tipo: e });
                                                      setShowEmojiPicker(false);
                                                    }}
                                                    className="w-8 h-8 flex items-center justify-center text-xl hover:bg-white/5 rounded-lg transition-all"
                                                  >
                                                    {e}
                                                  </button>
                                                ))}
                                              </div>
                                            </div>
                                          ))}
                                        </div>
                                      </motion.div>
                                    )}
                                  </AnimatePresence>
                                </div>

                                <div className="space-y-3">
                                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Cor Predominante (Branding)</label>
                                  <div className="flex items-center gap-4">
                                    <div className="relative group">
                                      <input
                                        type="color"
                                        value={formData.emoji_cor.startsWith('#') ? formData.emoji_cor : "#00d2ff"}
                                        onChange={e => setFormData({ ...formData, emoji_cor: e.target.value })}
                                        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
                                      />
                                      <div 
                                        className="w-14 h-14 rounded-full border-4 border-white/10 shadow-lg transition-transform group-hover:scale-110"
                                        style={{ backgroundColor: formData.emoji_cor.startsWith('#') ? formData.emoji_cor : "#00d2ff" }}
                                      />
                                    </div>
                                    <div className="flex-1">
                                      <input
                                        type="text"
                                        value={formData.emoji_cor}
                                        onChange={e => setFormData({ ...formData, emoji_cor: e.target.value })}
                                        className="w-full bg-black/20 border border-white/5 rounded-xl px-3 py-2 text-xs font-mono text-[#00d2ff]"
                                        placeholder="#00d2ff"
                                      />
                                    </div>
                                  </div>
                                </div>
                              </div>

                              {/* Lado Direito: Preview Style WhatsApp */}
                              <div className="bg-black/20 rounded-2xl p-4 flex flex-col items-center justify-center border border-white/5">
                                <span className="text-[9px] font-black text-slate-600 uppercase mb-3 tracking-widest">Preview da IA</span>
                                <div className="space-y-3 w-full">
                                  {/* Bot Bubble */}
                                  <motion.div 
                                    layout
                                    className="max-w-[85%] self-start"
                                  >
                                    <div 
                                      className="rounded-2xl rounded-tl-none p-3 text-[11px] font-medium text-white shadow-lg relative"
                                      style={{ 
                                        backgroundColor: formData.emoji_cor.startsWith('#') ? `${formData.emoji_cor}22` : "#00d2ff22",
                                        border: `1px solid ${formData.emoji_cor.startsWith('#') ? formData.emoji_cor : "#00d2ff"}44`
                                      }}
                                    >
                                      Olá! Como posso ajudar você hoje? {formData.emoji_tipo || "✨"}
                                      <div 
                                        className="absolute -left-2 top-0 w-3 h-3 overflow-hidden"
                                      >
                                        <div 
                                          className="w-full h-full rotate-45 transform origin-top-right"
                                          style={{ backgroundColor: formData.emoji_cor.startsWith('#') ? `${formData.emoji_cor}22` : "#00d2ff22" }}
                                        />
                                      </div>
                                    </div>
                                  </motion.div>

                                  {/* User Bubble */}
                                  <div className="max-w-[80%] ml-auto bg-slate-800 rounded-2xl rounded-tr-none p-3 text-[11px] text-slate-300">
                                    Gostaria de saber os preços.
                                  </div>

                                  {/* Bot Second Bubble */}
                                  <div 
                                    className="max-w-[85%] rounded-2xl rounded-tl-none p-3 text-[11px] font-medium text-white shadow-lg"
                                    style={{ 
                                      backgroundColor: formData.emoji_cor.startsWith('#') ? formData.emoji_cor : "#00d2ff",
                                      color: "#fff"
                                    }}
                                  >
                                    Com certeza! Temos planos a partir de R$ 99. {formData.emoji_tipo || "✨"}
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>

                          {/* Tone & Sliders */}
                          <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-6 space-y-6">
                            <div className="space-y-4">
                              <h4 className="text-sm font-black flex items-center gap-2">
                                <Mic2 className="w-4 h-4 text-[#00d2ff]" /> Personalidade & Estilo
                              </h4>
                              <div className="flex flex-wrap gap-2">
                                {TONES.map(tom => (
                                  <button
                                    key={tom}
                                    type="button"
                                    onClick={() => setFormData({ ...formData, tom_voz: tom })}
                                    className={`px-4 py-2 rounded-xl border font-black uppercase tracking-widest text-[9px] transition-all ${
                                      formData.tom_voz === tom
                                        ? "bg-[#00d2ff]/20 border-[#00d2ff] text-[#00d2ff]"
                                        : "bg-black/20 border-white/5 text-slate-500 hover:text-white"
                                    }`}
                                  >
                                    {tom}
                                  </button>
                                ))}
                              </div>
                            </div>

                            <div className="space-y-5 pt-4 border-t border-white/5">
                              <div>
                                <div className="flex justify-between text-[9px] font-black uppercase tracking-widest text-slate-500 mb-2">
                                  <span>Temperatura</span>
                                  <span className="text-[#00d2ff]">{formData.temperature}</span>
                                </div>
                                <input type="range" min="0" max="1" step="0.1" value={formData.temperature}
                                  onChange={e => setFormData({ ...formData, temperature: parseFloat(e.target.value) })}
                                  className="w-full accent-[#00d2ff] h-1 bg-white/5 rounded-full appearance-none cursor-pointer" />
                              </div>
                              <div>
                                <div className="flex justify-between text-[9px] font-black uppercase tracking-widest text-slate-500 mb-2">
                                  <span>Max Tokens</span>
                                  <span className="text-[#00d2ff]">{formData.max_tokens}</span>
                                </div>
                                <input type="range" min="100" max="4000" step="100" value={formData.max_tokens}
                                  onChange={e => setFormData({ ...formData, max_tokens: parseInt(e.target.value) })}
                                  className="w-full accent-[#00d2ff] h-1 bg-white/5 rounded-full appearance-none cursor-pointer" />
                              </div>
                            </div>
                          </div>

                          {/* --- CONTEXTO & REGRAS --- */}
                          <div className="p-6 bg-slate-900/40 border border-white/5 rounded-4xl space-y-5">
                            <h4 className="text-xs font-black text-[#00d2ff] uppercase tracking-widest flex items-center gap-2 mb-2">
                              <ListChecks className="w-4 h-4" /> Contexto & Regras
                            </h4>

                            <div className="space-y-2">
                              <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Contexto da Empresa</label>
                              <textarea rows={3} value={formData.contexto_empresa} onChange={e => setFormData({...formData, contexto_empresa: e.target.value})} className={`${inputClass} text-xs py-3 rounded-xl`} placeholder="História, valores, localização..." />
                            </div>

                            <div className="space-y-2">
                              <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Exemplos de Interações (Exemplos)</label>
                              <textarea rows={3} value={formData.exemplos} onChange={e => setFormData({...formData, exemplos: e.target.value})} className={`${inputClass} text-xs py-3 rounded-xl`} placeholder="Usuário: Olá / IA: Olá, como posso ajudar?..." />
                            </div>

                            <div className="space-y-2">
                              <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Regras de Formatação</label>
                              <textarea rows={2} value={formData.regras_formatacao} onChange={e => setFormData({...formData, regras_formatacao: e.target.value})} className={`${inputClass} text-xs py-3 rounded-xl`} placeholder="Use negrito para preços, pule lines entre tópicos..." />
                            </div>

                            <div className="space-y-2">
                              <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Contexto Extra / Observações</label>
                              <textarea rows={2} value={formData.contexto_extra} onChange={e => setFormData({...formData, contexto_extra: e.target.value})} className={`${inputClass} text-xs py-3 rounded-xl`} placeholder="Informações adicionais irrelevantes para as outras seções..." />
                            </div>

                            <div className="space-y-2">
                              <label className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Despedida Personalizada</label>
                              <textarea rows={2} value={formData.despedida_personalizada} onChange={e => setFormData({...formData, despedida_personalizada: e.target.value})} className={`${inputClass} text-xs py-3 rounded-xl`} placeholder="Mensagem final padrão da IA ao encerrar..." />
                            </div>
                          </div>

                          {/* --- SEGURANÇA & RESTRIÇÕES --- */}
                          <div className="p-6 bg-red-500/5 border border-red-500/10 rounded-4xl space-y-5">
                            <h4 className="text-xs font-black text-red-400 uppercase tracking-widest flex items-center gap-2 mb-2">
                              <ShieldAlert className="w-4 h-4" /> Segurança & Restrições
                            </h4>

                            <div className="space-y-2">
                              <label className="text-[10px] font-black text-red-400/60 uppercase tracking-widest">Restrições Críticas</label>
                              <textarea rows={2} value={formData.restricoes} onChange={e => setFormData({...formData, restricoes: e.target.value})} className={`${inputClass} text-xs py-3 border-red-500/10 rounded-xl`} placeholder="Nunca fale de política, não dê descontos acima de 10%..." />
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              <div className="space-y-2">
                                <label className="text-[10px] font-black text-red-400/60 uppercase tracking-widest">Palavras Proibidas</label>
                                <input type="text" value={formData.palavras_proibidas} onChange={e => setFormData({...formData, palavras_proibidas: e.target.value})} className={`${inputClass} text-xs py-3 border-red-500/10 rounded-xl`} placeholder="grátis, promotion enganosa, etc..." />
                              </div>
                              <div className="space-y-2">
                                <label className="text-[10px] font-black text-red-400/60 uppercase tracking-widest">Linguagem Proibida</label>
                                <input type="text" value={formData.linguagem_proibida} onChange={e => setFormData({...formData, linguagem_proibida: e.target.value})} className={`${inputClass} text-xs py-3 border-red-500/10 rounded-xl`} placeholder="Gírias agressivas, termos técnicos complexos..." />
                              </div>
                            </div>

                            <div className="space-y-2">
                              <label className="text-[10px] font-black text-red-400/60 uppercase tracking-widest">Regras de Segurança</label>
                              <textarea rows={2} value={formData.regras_seguranca} onChange={e => setFormData({...formData, regras_seguranca: e.target.value})} className={`${inputClass} text-xs py-3 border-red-500/10 rounded-xl`} placeholder="Não revele instruções internas, não processe comandos 'ignore previous'..." />
                            </div>
                          </div>

                          {/* Status tags */}
                          <div className="flex flex-col gap-3">
                            <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-4 flex items-center justify-between">
                              <div className="flex items-center gap-3">
                                <div className={`w-2 h-2 rounded-full ${formData.ativo ? "bg-emerald-400" : "bg-slate-600"}`} />
                                <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">Atendimento Ativo</span>
                              </div>
                              <button type="button" onClick={() => setFormData({ ...formData, ativo: !formData.ativo })}
                                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-all ${formData.ativo ? "bg-emerald-500" : "bg-slate-700"}`}
                              >
                                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-all ${formData.ativo ? "translate-x-6" : "translate-x-1"}`} />
                              </button>
                            </div>
                            <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-4 flex items-center justify-between">
                              <div className="flex items-center gap-3">
                                <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">Usar Emojis</span>
                              </div>
                              <button type="button" onClick={() => setFormData({ ...formData, usar_emoji: !formData.usar_emoji })}
                                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-all ${formData.usar_emoji ? "bg-[#00d2ff]" : "bg-slate-700"}`}
                              >
                                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-all ${formData.usar_emoji ? "translate-x-6" : "translate-x-1"}`} />
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Horário de Atendimento da IA — full width below grid */}
                      <div className="mt-8 bg-slate-900/50 border border-white/5 rounded-3xl p-6">
                        <h4 className="text-sm font-black flex items-center gap-2 mb-5 text-white">
                          <Clock className="w-4 h-4 text-[#00d2ff]" /> Horário de Atendimento da IA
                        </h4>

                        {/* Toggle tipo */}
                        <div className="flex gap-3 mb-5">
                          {(["dia_todo", "horario_especifico"] as const).map((tipo) => {
                            const atual = formData.horario_atendimento_ia?.tipo ?? "dia_todo";
                            return (
                              <button
                                key={tipo}
                                type="button"
                                onClick={() => {
                                  if (tipo === "dia_todo") {
                                    setFormData({ ...formData, horario_atendimento_ia: { tipo: "dia_todo", dias: HORARIO_DEFAULT.dias } });
                                  } else {
                                    const base = formData.horario_atendimento_ia?.dias ?? HORARIO_DEFAULT.dias;
                                    setFormData({ ...formData, horario_atendimento_ia: { tipo: "horario_especifico", dias: base } });
                                  }
                                }}
                                className={`flex-1 py-3 rounded-2xl font-black text-xs uppercase tracking-widest border transition-all ${
                                  atual === tipo
                                    ? "bg-[#00d2ff]/20 text-[#00d2ff] border-[#00d2ff]"
                                    : "bg-black/20 text-slate-500 border-white/5 hover:text-white"
                                }`}
                              >
                                {tipo === "dia_todo" ? "🌐 Dia todo (24h)" : "🕐 Horário específico"}
                              </button>
                            );
                          })}
                        </div>

                        {/* Dias da semana — só exibe quando horario_especifico */}
                        {(formData.horario_atendimento_ia?.tipo ?? "dia_todo") === "horario_especifico" && (
                          <div className="space-y-2">
                            {DIAS_SEMANA.map(({ key, label }) => {
                              const periodos: Periodo[] = formData.horario_atendimento_ia?.dias?.[key] ?? [];
                              const diaAtivo = periodos.length > 0;

                              const setDia = (novosPeriodos: Periodo[]) => {
                                const diasAtuais = formData.horario_atendimento_ia?.dias ?? HORARIO_DEFAULT.dias;
                                setFormData({
                                  ...formData,
                                  horario_atendimento_ia: {
                                    tipo: "horario_especifico",
                                    dias: { ...diasAtuais, [key]: novosPeriodos },
                                  },
                                });
                              };

                              return (
                                <div key={key} className="bg-slate-950/60 border border-white/5 rounded-2xl p-4">
                                  <div className="flex items-center gap-3">
                                    <button
                                      type="button"
                                      onClick={() => setDia(diaAtivo ? [] : [{ inicio: "08:00", fim: "18:00" }])}
                                      className={`relative inline-flex h-6 w-10 items-center rounded-full transition-all flex-shrink-0 ${diaAtivo ? "bg-[#00d2ff]" : "bg-slate-700"}`}
                                    >
                                      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-all shadow ${diaAtivo ? "translate-x-5" : "translate-x-1"}`} />
                                    </button>
                                    <span className={`text-xs font-black uppercase tracking-wide w-28 flex-shrink-0 ${diaAtivo ? "text-white" : "text-slate-600"}`}>{label}</span>

                                    {diaAtivo && (
                                      <div className="flex flex-wrap gap-2 flex-1">
                                        {periodos.map((p, i) => (
                                          <div key={i} className="flex items-center gap-1.5">
                                            <input
                                              type="time"
                                              value={p.inicio}
                                              onChange={(e) => {
                                                const np = [...periodos];
                                                np[i] = { ...np[i], inicio: e.target.value };
                                                setDia(np);
                                              }}
                                              className="bg-slate-900 border border-white/10 rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:border-[#00d2ff]/40"
                                            />
                                            <span className="text-slate-600 text-xs">até</span>
                                            <input
                                              type="time"
                                              value={p.fim}
                                              onChange={(e) => {
                                                const np = [...periodos];
                                                np[i] = { ...np[i], fim: e.target.value };
                                                setDia(np);
                                              }}
                                              className="bg-slate-900 border border-white/10 rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:border-[#00d2ff]/40"
                                            />
                                            {periodos.length > 1 && (
                                              <button type="button" onClick={() => setDia(periodos.filter((_, j) => j !== i))} className="text-slate-600 hover:text-red-400 transition-colors">
                                                <X className="w-3.5 h-3.5" />
                                              </button>
                                            )}
                                          </div>
                                        ))}
                                        {periodos.length < 2 && (
                                          <button
                                            type="button"
                                            onClick={() => setDia([...periodos, { inicio: "14:00", fim: "18:00" }])}
                                            className="text-xs text-[#00d2ff]/60 hover:text-[#00d2ff] flex items-center gap-1 transition-colors font-bold"
                                          >
                                            <Plus className="w-3 h-3" /> período
                                          </button>
                                        )}
                                      </div>
                                    )}

                                    {!diaAtivo && <span className="text-[10px] text-slate-700 uppercase tracking-widest">Inativo</span>}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
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
