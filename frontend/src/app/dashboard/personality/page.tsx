"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { Brain, Save, Loader2, CheckCircle2, ArrowLeft, MessageSquare, Mic2, Sparkles, Smile, Target, Cpu, Thermometer, Hash, Send, User, Bot, PlayCircle, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

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
    nome_ia: "",
    personalidade: "",
    instrucoes_base: "",
    tom_voz: "Profissional",
    model_name: "openai/gpt-4o",
    temperature: 0.7,
    max_tokens: 1000,
    ativo: false
  });

  // Playground State
  const [testMessage, setTestMessage] = useState("");
  const [playHistory, setPlayHistory] = useState<{ role: string; content: string }[]>([]);
  const [testLoading, setTestLoading] = useState(false);

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
      await axios.post("/api-backend/management/personality", personality, getConfig());
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (error) {
      console.error("Erro ao salvar personalidade:", error);
      alert("Erro ao salvar alterações.");
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    if (!testMessage.trim()) return;
    setTestLoading(true);
    const newHistory = [...playHistory, { role: "user", content: testMessage }];
    setPlayHistory(newHistory);
    setTestMessage("");
    
    // Simulação de resposta IA para o playground (visto que não temos endpoint de chat direto no playground real do back ainda)
    // Em um sistema real, isso chamaria um endpoint que usa as configs atuais sem salvar.
    setTimeout(() => {
      setPlayHistory([...newHistory, { role: "bot", content: "Isso é um simulador de comportamento. Salve as configurações para que seu agente responda com as novas diretrizes no Chatwoot/WhatsApp." }]);
      setTestLoading(false);
    }, 1000);
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
      <div className="max-w-7xl mx-auto">
        {/* Unitary Header Structure - Standardized */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-16">
          <div className="flex items-center gap-5">
            <a href="/dashboard" className="p-3.5 bg-white/5 hover:bg-primary/10 rounded-2xl transition-all border border-white/10 hover:border-primary/30 group">
              <ArrowLeft className="w-5 h-5 group-hover:text-primary transition-colors" />
            </a>
            <div>
              <h1 className="text-4xl font-black flex items-center gap-3">
                <Brain className="w-10 h-10 text-primary neon-glow" />
                <span className="text-gradient">Inteligência Neural</span>
              </h1>
              <p className="text-gray-400 mt-1 font-medium italic opacity-80">Arquitetura de comportamento e controle fino do motor de IA.</p>
            </div>
          </div>
          <button
            onClick={handleSave}
            disabled={saving}
            className="bg-primary hover:bg-primary/90 disabled:bg-primary/50 text-black px-12 py-5 rounded-[2rem] font-black uppercase tracking-widest text-sm flex items-center justify-center gap-3 transition-all shadow-[0_0_30px_rgba(0,210,255,0.3)] hover:scale-[1.02] active:scale-[0.98]"
          >
            {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : success ? <CheckCircle2 className="w-5 h-5" /> : <Save className="w-5 h-5" />}
            {saving ? "Deploying..." : success ? "Estratégia Ativa" : "Salvar Configurações"}
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* Main Column */}
          <div className="lg:col-span-8 space-y-8">
            <motion.div 
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              className="glass rounded-[3rem] p-10 relative overflow-hidden group border-white/5"
            >
              <div className="absolute top-0 right-0 w-64 h-64 bg-primary/5 blur-[100px] rounded-full -mr-20 -mt-20 group-hover:bg-primary/10 transition-colors" />
              
              <h3 className="text-xl font-black flex items-center gap-4 mb-10">
                <Sparkles className="w-7 h-7 text-primary" />
                DNASYSTEM: Instruções Centrais
              </h3>
              
              <div className="space-y-10">
                <div>
                  <label className="block text-[10px] font-black text-gray-500 uppercase tracking-[0.2em] mb-4 ml-1 flex items-center gap-2">
                    <Target className="w-4 h-4 text-primary" /> Objetivo Estratégico
                  </label>
                  <textarea
                    rows={3}
                    value={personality.personalidade}
                    onChange={(e) => setPersonality({ ...personality, personalidade: e.target.value })}
                    className="w-full bg-slate-900/40 border border-white/10 rounded-2xl px-6 py-5 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all resize-none text-lg font-bold leading-relaxed"
                    placeholder="Defina o propósito vital desta IA..."
                  />
                </div>

                <div>
                  <label className="block text-[10px] font-black text-gray-500 uppercase tracking-[0.2em] mb-4 ml-1 flex items-center gap-2">
                    <MessageSquare className="w-4 h-4 text-primary" /> Cérebro Cognitivo (Prompts de Base)
                  </label>
                  <textarea
                    rows={10}
                    value={personality.instrucoes_base}
                    onChange={(e) => setPersonality({ ...personality, instrucoes_base: e.target.value })}
                    className="w-full bg-slate-900/40 border border-white/10 rounded-3xl px-6 py-5 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all resize-none font-mono text-sm leading-relaxed text-blue-100/70 custom-scrollbar"
                    placeholder="Diretrizes técnicas, limites éticos e fluxos de conversa..."
                  />
                  <div className="mt-4 p-5 bg-primary/5 border border-primary/10 rounded-[1.5rem] flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0 animate-pulse">
                        <Sparkles className="w-5 h-5 text-primary" />
                    </div>
                    <p className="text-[10px] text-gray-400 font-bold leading-relaxed uppercase tracking-wider">
                      Otimize seu prompt: Use [VARIAVEIS] para dados dinâmicos das unidades.
                    </p>
                  </div>
                </div>
              </div>
            </motion.div>

            {/* AI Playground */}
            <motion.div 
               initial={{ opacity: 0, y: 20 }}
               animate={{ opacity: 1, y: 0 }}
               className="glass rounded-[3rem] p-10 border-white/5 shadow-2xl"
            >
               <h3 className="text-xl font-black flex items-center gap-4 mb-8">
                  <PlayCircle className="w-7 h-7 text-primary" />
                  Neural Playground
                  <span className="text-[10px] font-black bg-primary/10 text-primary px-3 py-1 rounded-full ml-auto uppercase tracking-widest">Simulação Ativa</span>
               </h3>

               <div className="bg-slate-950/60 rounded-3xl p-6 min-h-[300px] mb-8 border border-white/5 relative overflow-hidden flex flex-col gap-4">
                  {playHistory.length === 0 ? (
                    <div className="flex-1 flex flex-col items-center justify-center text-center opacity-30">
                       <Bot className="w-16 h-16 mb-4" />
                       <p className="text-sm font-bold">Teste o comportamento da IA agora.</p>
                       <p className="text-[10px] uppercase">A resposta mudará conforme você ajusta os parâmetros.</p>
                    </div>
                  ) : (
                    playHistory.map((m, i) => (
                      <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                         <div className={`max-w-[80%] p-4 rounded-2xl text-sm ${m.role === 'user' ? 'bg-primary text-black font-bold' : 'bg-white/5 text-gray-300 border border-white/5'}`}>
                            {m.content}
                         </div>
                      </div>
                    ))
                  )}
                  {testLoading && <div className="text-xs text-primary animate-pulse">Neural está processando...</div>}
               </div>

               <div className="relative">
                  <input 
                    type="text"
                    value={testMessage}
                    onChange={(e) => setTestMessage(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && runTest()}
                    placeholder="Digite para testar o cérebro..."
                    className="w-full bg-white/5 border border-white/10 rounded-2xl px-6 py-5 pr-20 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-medium"
                  />
                  <button 
                    onClick={runTest}
                    className="absolute right-3 top-1/2 -translate-y-1/2 p-3 bg-primary text-black hover:bg-primary/90 rounded-xl transition-all"
                  >
                    <Send className="w-5 h-5" />
                  </button>
               </div>
            </motion.div>
          </div>

          {/* Sidebar Column */}
          <div className="lg:col-span-4 space-y-8">
            {/* Core Engine Selector */}
            <motion.div 
               initial={{ opacity: 0, x: 20 }}
               animate={{ opacity: 1, x: 0 }}
               className="glass rounded-[3rem] p-10 blue-tint border-primary/20"
            >
               <h3 className="text-xl font-black flex items-center gap-4 mb-8 uppercase tracking-tighter">
                  <Cpu className="w-6 h-6 text-primary" />
                  AI Control Center
               </h3>

               <div className="space-y-10">
                  <div>
                    <label className="block text-[10px] font-black text-gray-500 uppercase tracking-widest mb-4 ml-1">Motor (Core Engine Selection)</label>
                    <div className="grid grid-cols-1 gap-2">
                       {[
                         { id: "openai/gpt-4o", label: "GPT-4o (Elite Performance)", speed: "Fast", icon: Sparkles },
                         { id: "anthropic/claude-3.5-sonnet", label: "Claude 3.5 (Creative)", speed: "Deep", icon: Brain },
                         { id: "google/gemini-2.0-flash", label: "Gemini 2.0 (Fast & Multi)", speed: "Turbo", icon: Zap },
                       ].map((m) => (
                         <button
                           key={m.id}
                           type="button"
                           onClick={() => setPersonality({...personality, model_name: m.id})}
                           className={`w-full flex items-center justify-between p-4 rounded-2xl border transition-all ${
                             personality.model_name === m.id 
                               ? "bg-primary/20 border-primary text-primary" 
                               : "bg-black/20 border-white/5 text-gray-500 hover:text-white"
                           }`}
                         >
                            <div className="flex items-center gap-3">
                               <m.icon className="w-4 h-4" />
                               <div className="text-left">
                                  <p className="text-xs font-black uppercase tracking-tight">{m.label.split('(')[0]}</p>
                                  <p className="text-[9px] opacity-60">{m.label.split('(')[1]}</p>
                               </div>
                            </div>
                            <span className="text-[9px] font-black px-2 py-0.5 rounded-full bg-white/5 uppercase opacity-50">{m.speed}</span>
                         </button>
                       ))}
                    </div>
                  </div>

                  <div className="space-y-6">
                    <div className="flex justify-between items-center text-[10px] font-black uppercase tracking-widest text-gray-500">
                       <span className="flex items-center gap-2"><Thermometer className="w-3 h-3" /> Temperatura (Criatividade)</span>
                       <span className="text-primary">{personality.temperature}</span>
                    </div>
                    <input 
                      type="range" min="0" max="1" step="0.1" 
                      value={personality.temperature}
                      onChange={(e) => setPersonality({...personality, temperature: parseFloat(e.target.value)})}
                      className="w-full accent-primary h-1.5 bg-white/5 rounded-full appearance-none cursor-pointer"
                    />
                    <div className="flex justify-between text-[9px] text-gray-600 font-bold uppercase tracking-widest">
                       <span>Preciso</span>
                       <span>Criativo</span>
                    </div>
                  </div>

                  <div className="space-y-6">
                    <div className="flex justify-between items-center text-[10px] font-black uppercase tracking-widest text-gray-500">
                       <span className="flex items-center gap-2"><Hash className="w-3 h-3" /> Max Tokens (Tamanho Resposta)</span>
                       <span className="text-primary">{personality.max_tokens}</span>
                    </div>
                    <input 
                      type="range" min="100" max="4000" step="100" 
                      value={personality.max_tokens}
                      onChange={(e) => setPersonality({...personality, max_tokens: parseInt(e.target.value)})}
                      className="w-full accent-primary h-1.5 bg-white/5 rounded-full appearance-none cursor-pointer"
                    />
                  </div>
               </div>
            </motion.div>

            <motion.div 
               initial={{ opacity: 0, scale: 0.95 }}
               animate={{ opacity: 1, scale: 1 }}
               className="glass rounded-[3rem] p-10"
            >
               <h3 className="text-xl font-black flex items-center gap-4 mb-8">
                <Mic2 className="w-6 h-6 text-primary" />
                Personalidade & Voz
               </h3>

               <div className="space-y-8">
                 <div>
                   <label className="block text-[10px] font-black text-gray-500 uppercase tracking-widest mb-4 ml-1">Nome de Exibição da IA</label>
                   <input
                     type="text"
                     value={personality.nome_ia}
                     onChange={(e) => setPersonality({ ...personality, nome_ia: e.target.value })}
                     className="w-full bg-black/40 border border-white/10 rounded-2xl px-6 py-4 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-bold"
                     placeholder="Ex: Clara"
                   />
                 </div>

                 <div>
                    <label className="block text-[10px] font-black text-gray-500 uppercase tracking-widest mb-4 ml-1">Ajuste Emocional</label>
                    <div className="grid grid-cols-1 gap-3">
                      {["Profissional", "Amigável", "Entusiasta"].map((tom) => (
                        <button
                          key={tom}
                          type="button"
                          onClick={() => setPersonality({ ...personality, tom_voz: tom })}
                          className={`flex items-center justify-between px-6 py-5 rounded-[1.8rem] border transition-all text-xs font-black uppercase tracking-widest ${
                            personality.tom_voz === tom 
                              ? "bg-primary/20 border-primary text-primary" 
                              : "bg-black/20 border-white/5 text-gray-500 hover:text-white"
                          }`}
                        >
                          {tom}
                          {personality.tom_voz === tom && <CheckCircle2 className="w-4 h-4 shadow-xl" />}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="pt-6 border-t border-white/10 flex items-center justify-between">
                    <div>
                      <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Atendimento Inteligente</p>
                      <p className="text-[9px] text-primary font-black uppercase tracking-widest">{personality.ativo ? "Online" : "Pausado"}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setPersonality({ ...personality, ativo: !personality.ativo })}
                      className={`relative inline-flex h-8 w-14 items-center rounded-full transition-all ${
                        personality.ativo ? "bg-primary" : "bg-gray-800"
                      }`}
                    >
                      <span className={`inline-block h-6 w-6 transform rounded-full bg-white transition-all shadow-2xl ${
                        personality.ativo ? "translate-x-7" : "translate-x-1"
                      }`} />
                    </button>
                  </div>
               </div>
            </motion.div>
          </div>
        </div>
      </div>
      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar { width: 5px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0, 242, 255, 0.1); border-radius: 10px; }
      `}</style>
    </div>
  );
}
