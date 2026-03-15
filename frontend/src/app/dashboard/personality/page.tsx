"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { Brain, Save, Loader2, CheckCircle2, MessageSquare, Sparkles, Target, Cpu, Thermometer, Hash, Send, Bot, PlayCircle, Zap, Mic2 } from "lucide-react";
import { motion } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

interface Personality {
  nome_ia: string;
  personalidade: string;
  instrucoes_base: string;
  tom_voz: string;
  model_name: string;
  temperature: number;
  max_tokens: number;
  ativo: boolean;
}

export default function PersonalityPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [personality, setPersonality] = useState<Personality>({
    nome_ia: "", personalidade: "", instrucoes_base: "", tom_voz: "Profissional",
    model_name: "openai/gpt-4o", temperature: 0.7, max_tokens: 1000, ativo: false
  });
  const [testMessage, setTestMessage] = useState("");
  const [playHistory, setPlayHistory] = useState<{ role: string; content: string }[]>([]);
  const [testLoading, setTestLoading] = useState(false);

  const getConfig = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } });

  useEffect(() => {
    axios.get("/api-backend/management/personality", getConfig())
      .then(r => setPersonality(r.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await axios.post("/api-backend/management/personality", personality, getConfig());
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch { alert("Erro ao salvar alterações."); }
    finally { setSaving(false); }
  };

  const runTest = async () => {
    if (!testMessage.trim()) return;
    setTestLoading(true);
    const newHistory = [...playHistory, { role: "user", content: testMessage }];
    setPlayHistory(newHistory);
    setTestMessage("");
    setTimeout(() => {
      setPlayHistory([...newHistory, { role: "bot", content: "Isso é um simulador. Salve as configurações para que seu agente responda com as novas diretrizes no WhatsApp/Chatwoot." }]);
      setTestLoading(false);
    }, 1000);
  };

  const inputClass = "w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 transition-all font-medium text-sm";

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="personality" />
      <main className="flex-1 min-w-0 overflow-auto">
        <div className="fixed top-0 right-0 w-[500px] h-[400px] bg-[#00d2ff]/3 rounded-full blur-[120px] pointer-events-none" />
        <div className="relative z-10 p-8 lg:p-10 max-w-7xl mx-auto pb-20">
          {/* Header */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-1.5 h-5 bg-[#00d2ff] rounded-full" />
                <span className="text-[10px] font-black text-[#00d2ff] uppercase tracking-[0.4em]">Fluxo Digital & Tech</span>
              </div>
              <h1 className="text-4xl font-black tracking-tight" style={{ background: "linear-gradient(135deg,#fff 0%,#00d2ff 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                Inteligência Neural
              </h1>
              <p className="text-slate-500 mt-2 text-sm italic">Arquitetura de comportamento e controle fino do motor de IA.</p>
            </div>
            <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }} onClick={handleSave} disabled={saving}
              className="bg-[#00d2ff] text-black px-10 py-4 rounded-2xl font-black uppercase tracking-widest text-sm flex items-center gap-3 shadow-[0_0_25px_rgba(0,210,255,0.3)] disabled:opacity-50">
              {saving ? <><Loader2 className="w-5 h-5 animate-spin" />Deploying...</>
                : success ? <><CheckCircle2 className="w-5 h-5" />Estratégia Ativa</>
                : <><Save className="w-5 h-5" />Salvar Configurações</>}
            </motion.button>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-40"><Loader2 className="w-8 h-8 text-[#00d2ff] animate-spin" /></div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
              {/* Main Column */}
              <div className="lg:col-span-8 space-y-8">
                <form onSubmit={handleSave} className="bg-slate-900/50 border border-white/5 rounded-3xl p-8 hover:border-[#00d2ff]/15 transition-all">
                  <h3 className="text-xl font-black flex items-center gap-3 mb-8">
                    <Sparkles className="w-6 h-6 text-[#00d2ff]" /> DNASYSTEM: Instruções Centrais
                  </h3>
                  <div className="space-y-8">
                    <div>
                      <label className="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-3 flex items-center gap-2">
                        <Target className="w-3.5 h-3.5 text-[#00d2ff]/50" /> Objetivo Estratégico
                      </label>
                      <textarea rows={3} value={personality.personalidade}
                        onChange={e => setPersonality({ ...personality, personalidade: e.target.value })}
                        className={`${inputClass} resize-none`} placeholder="Defina o propósito vital desta IA..." />
                    </div>
                    <div>
                      <label className="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-3 flex items-center gap-2">
                        <MessageSquare className="w-3.5 h-3.5 text-[#00d2ff]/50" /> Cérebro Cognitivo (Prompts de Base)
                      </label>
                      <textarea rows={10} value={personality.instrucoes_base}
                        onChange={e => setPersonality({ ...personality, instrucoes_base: e.target.value })}
                        className={`${inputClass} resize-none font-mono text-xs text-[#00d2ff]/80 leading-relaxed`}
                        placeholder="Diretrizes técnicas, limites éticos e fluxos de conversa..." />
                      <div className="mt-3 p-4 bg-[#00d2ff]/5 border border-[#00d2ff]/10 rounded-2xl flex items-center gap-3">
                        <Sparkles className="w-4 h-4 text-[#00d2ff] animate-pulse flex-shrink-0" />
                        <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">
                          Use [VARIAVEIS] para dados dinâmicos das unidades.
                        </p>
                      </div>
                    </div>
                  </div>
                </form>

                {/* Playground */}
                <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-8">
                  <h3 className="text-xl font-black flex items-center gap-3 mb-6">
                    <PlayCircle className="w-6 h-6 text-[#00d2ff]" /> Neural Playground
                    <span className="text-[10px] font-black bg-[#00d2ff]/10 text-[#00d2ff] px-3 py-1 rounded-full ml-auto uppercase tracking-widest">Simulação</span>
                  </h3>
                  <div className="bg-slate-950/60 rounded-2xl p-5 min-h-[250px] mb-5 border border-white/5 flex flex-col gap-3">
                    {playHistory.length === 0 ? (
                      <div className="flex-1 flex flex-col items-center justify-center text-center opacity-30">
                        <Bot className="w-12 h-12 mb-3" />
                        <p className="text-sm font-bold">Teste o comportamento da IA.</p>
                      </div>
                    ) : playHistory.map((m, i) => (
                      <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                        <div className={`max-w-[80%] p-3.5 rounded-2xl text-sm ${m.role === "user" ? "bg-[#00d2ff] text-black font-bold" : "bg-white/5 text-slate-300 border border-white/5"}`}>
                          {m.content}
                        </div>
                      </div>
                    ))}
                    {testLoading && <div className="text-xs text-[#00d2ff] animate-pulse">Neural processando...</div>}
                  </div>
                  <div className="relative">
                    <input type="text" value={testMessage} onChange={e => setTestMessage(e.target.value)}
                      onKeyDown={e => e.key === "Enter" && runTest()}
                      placeholder="Digite para testar o cérebro..."
                      className={`${inputClass} pr-16`} />
                    <button onClick={runTest} className="absolute right-3 top-1/2 -translate-y-1/2 p-3 bg-[#00d2ff] text-black rounded-xl hover:bg-[#00d2ff]/90 transition-all">
                      <Send className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>

              {/* Sidebar Column */}
              <div className="lg:col-span-4 space-y-6">
                {/* Engine */}
                <div className="bg-[#00d2ff]/5 border border-[#00d2ff]/20 rounded-3xl p-7">
                  <h3 className="text-lg font-black flex items-center gap-3 mb-7">
                    <Cpu className="w-5 h-5 text-[#00d2ff]" /> AI Control Center
                  </h3>
                  <div className="space-y-6">
                    <div>
                      <label className="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-3">Motor (Core Engine)</label>
                      <div className="grid grid-cols-1 gap-2">
                        {[
                          { id: "openai/gpt-4o", label: "GPT-4o", sub: "Elite Performance" },
                          { id: "anthropic/claude-3.5-sonnet", label: "Claude 3.5", sub: "Creative Deep" },
                          { id: "google/gemini-2.0-flash", label: "Gemini 2.0", sub: "Fast & Multi" },
                        ].map(m => (
                          <button key={m.id} type="button" onClick={() => setPersonality({ ...personality, model_name: m.id })}
                            className={`w-full flex items-center justify-between p-3.5 rounded-2xl border transition-all text-left ${personality.model_name === m.id ? "bg-[#00d2ff]/20 border-[#00d2ff] text-[#00d2ff]" : "bg-black/20 border-white/5 text-slate-500 hover:text-white"}`}>
                            <div>
                              <p className="text-xs font-black uppercase">{m.label}</p>
                              <p className="text-[9px] opacity-60">{m.sub}</p>
                            </div>
                            {personality.model_name === m.id && <CheckCircle2 className="w-4 h-4" />}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div>
                      <div className="flex justify-between text-[10px] font-black uppercase tracking-widest text-slate-500 mb-2">
                        <span className="flex items-center gap-1.5"><Thermometer className="w-3 h-3" />Temperatura</span>
                        <span className="text-[#00d2ff]">{personality.temperature}</span>
                      </div>
                      <input type="range" min="0" max="1" step="0.1" value={personality.temperature}
                        onChange={e => setPersonality({ ...personality, temperature: parseFloat(e.target.value) })}
                        className="w-full accent-[#00d2ff] h-1.5 bg-white/5 rounded-full appearance-none cursor-pointer" />
                      <div className="flex justify-between text-[9px] text-slate-600 mt-1">
                        <span>Preciso</span><span>Criativo</span>
                      </div>
                    </div>

                    <div>
                      <div className="flex justify-between text-[10px] font-black uppercase tracking-widest text-slate-500 mb-2">
                        <span className="flex items-center gap-1.5"><Hash className="w-3 h-3" />Max Tokens</span>
                        <span className="text-[#00d2ff]">{personality.max_tokens}</span>
                      </div>
                      <input type="range" min="100" max="4000" step="100" value={personality.max_tokens}
                        onChange={e => setPersonality({ ...personality, max_tokens: parseInt(e.target.value) })}
                        className="w-full accent-[#00d2ff] h-1.5 bg-white/5 rounded-full appearance-none cursor-pointer" />
                    </div>
                  </div>
                </div>

                {/* Personality */}
                <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-7">
                  <h3 className="text-lg font-black flex items-center gap-3 mb-7">
                    <Mic2 className="w-5 h-5 text-[#00d2ff]" /> Personalidade & Voz
                  </h3>
                  <div className="space-y-6">
                    <div>
                      <label className="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-2">Nome da IA</label>
                      <input type="text" value={personality.nome_ia} onChange={e => setPersonality({ ...personality, nome_ia: e.target.value })}
                        className={inputClass} placeholder="Ex: Clara" />
                    </div>
                    <div>
                      <label className="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-3">Ajuste Emocional</label>
                      <div className="grid grid-cols-1 gap-2">
                        {["Profissional", "Amigável", "Entusiasta"].map(tom => (
                          <button key={tom} type="button" onClick={() => setPersonality({ ...personality, tom_voz: tom })}
                            className={`px-4 py-3 rounded-2xl border font-black uppercase tracking-widest text-xs transition-all flex items-center justify-between ${personality.tom_voz === tom ? "bg-[#00d2ff]/20 border-[#00d2ff] text-[#00d2ff]" : "bg-black/20 border-white/5 text-slate-500 hover:text-white"}`}>
                            {tom}
                            {personality.tom_voz === tom && <CheckCircle2 className="w-4 h-4" />}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="pt-5 border-t border-white/5 flex items-center justify-between">
                      <div>
                        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Atendimento</p>
                        <p className="text-[9px] text-[#00d2ff] font-black uppercase">{personality.ativo ? "Online" : "Pausado"}</p>
                      </div>
                      <button type="button" onClick={() => setPersonality({ ...personality, ativo: !personality.ativo })}
                        className={`relative inline-flex h-7 w-12 items-center rounded-full transition-all ${personality.ativo ? "bg-[#00d2ff]" : "bg-slate-700"}`}>
                        <span className={`inline-block h-5 w-5 transform rounded-full bg-white transition-all shadow ${personality.ativo ? "translate-x-6" : "translate-x-1"}`} />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
