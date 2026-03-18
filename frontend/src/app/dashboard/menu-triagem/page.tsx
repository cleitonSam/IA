"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import {
  LayoutList, Save, Loader2, CheckCircle2, Plus, X, Zap, AlertCircle
} from "lucide-react";
import { motion } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

type MenuOpcao = { id: string; titulo: string; descricao: string };

interface MenuTriagem {
  ativo: boolean;
  tipo: "list" | "button";
  titulo: string;
  texto: string;
  rodape: string;
  botao: string;
  opcoes: MenuOpcao[];
}

const MENU_DEFAULT: MenuTriagem = {
  ativo: false,
  tipo: "list",
  titulo: "Atendimento",
  texto: "Olá! Como posso ajudar você hoje?",
  rodape: "Escolha uma das opções abaixo",
  botao: "Ver opções",
  opcoes: [
    { id: "1", titulo: "Suporte", descricao: "Dúvidas e problemas técnicos" },
    { id: "2", titulo: "Vendas", descricao: "Quero saber mais sobre produtos" },
  ],
};

export default function MenuTriagemPage() {
  const [config, setConfig] = useState<MenuTriagem>(MENU_DEFAULT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);

  const getConfig = () => ({
    headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
  });

  useEffect(() => {
    axios
      .get("/api-backend/management/personality", getConfig())
      .then((res) => {
        const menu = res.data?.menu_triagem;
        if (menu && typeof menu === "object") {
          setConfig({ ...MENU_DEFAULT, ...menu });
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await axios.post(
        "/api-backend/management/personality",
        { menu_triagem: config },
        getConfig()
      );
      setSuccess(true);
      setTimeout(() => setSuccess(false), 2500);
    } catch {
      alert("Erro ao salvar configuração do menu.");
    } finally {
      setSaving(false);
    }
  };

  const setOpcao = (idx: number, field: keyof MenuOpcao, value: string) => {
    const opcoes = [...config.opcoes];
    opcoes[idx] = { ...opcoes[idx], [field]: value };
    setConfig({ ...config, opcoes });
  };

  const addOpcao = () => {
    setConfig({
      ...config,
      opcoes: [...config.opcoes, { id: String(Date.now()), titulo: "", descricao: "" }],
    });
  };

  const removeOpcao = (idx: number) => {
    setConfig({ ...config, opcoes: config.opcoes.filter((_, i) => i !== idx) });
  };

  const inputClass =
    "w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 focus:bg-slate-900/80 transition-all font-medium text-sm";

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="menu-triagem" />

      <main className="flex-1 min-w-0 overflow-auto">
        <div className="fixed top-0 right-0 w-[600px] h-[400px] bg-[#00d2ff]/3 rounded-full blur-[120px] pointer-events-none" />

        <div className="relative z-10 p-8 lg:p-10 max-w-4xl mx-auto">
          {/* Header */}
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 mb-10">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-1.5 h-5 bg-[#00d2ff] rounded-full" />
                <span className="text-[10px] font-black text-[#00d2ff] uppercase tracking-[0.4em]">
                  Fluxo Digital & Tech
                </span>
              </div>
              <h1
                className="text-4xl font-black tracking-tight"
                style={{
                  background: "linear-gradient(135deg,#fff 0%,#00d2ff 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                }}
              >
                Menu de Triagem
              </h1>
              <p className="text-slate-500 mt-2 text-sm italic">
                Configure o menu interativo enviado automaticamente no WhatsApp.
              </p>
            </div>

            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.97 }}
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-3 bg-[#00d2ff] text-black px-8 py-4 rounded-2xl font-black uppercase tracking-widest text-sm shadow-[0_0_25px_rgba(0,210,255,0.3)] hover:shadow-[0_0_40px_rgba(0,210,255,0.4)] transition-all min-w-[200px] justify-center disabled:opacity-60"
            >
              {saving ? (
                <><Loader2 className="w-5 h-5 animate-spin" /> Salvando...</>
              ) : success ? (
                <><CheckCircle2 className="w-5 h-5" /> Salvo!</>
              ) : (
                <><Save className="w-5 h-5" /> Salvar</>
              )}
            </motion.button>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-40">
              <div className="relative w-16 h-16">
                <div className="absolute inset-0 rounded-full border-2 border-[#00d2ff]/10 animate-ping" />
                <div className="absolute inset-0 rounded-full border-2 border-t-[#00d2ff] animate-spin" />
                <LayoutList className="absolute inset-0 m-auto w-7 h-7 text-[#00d2ff]" />
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Ativar/Desativar */}
              <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-6 flex items-center justify-between">
                <div>
                  <p className="font-black uppercase tracking-wide text-sm">Status do Menu</p>
                  <p className={`text-[11px] font-bold uppercase mt-1 ${config.ativo ? "text-[#00d2ff]" : "text-slate-500"}`}>
                    {config.ativo ? "● Menu ativo — será enviado automaticamente" : "○ Menu inativo — não será enviado"}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setConfig({ ...config, ativo: !config.ativo })}
                  className={`relative inline-flex h-8 w-14 items-center rounded-full transition-all ${config.ativo ? "bg-[#00d2ff]" : "bg-slate-700"}`}
                >
                  <span
                    className={`inline-block h-6 w-6 transform rounded-full bg-white transition-all shadow ${config.ativo ? "translate-x-7" : "translate-x-1"}`}
                  />
                </button>
              </div>

              {/* Aviso */}
              <div className="p-4 bg-amber-500/5 border border-amber-500/15 rounded-2xl flex items-start gap-3">
                <Zap className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-slate-400 font-medium leading-relaxed">
                  O menu é enviado na <strong className="text-white">primeira mensagem</strong> do contato. O TTL é renovado a cada mensagem — após <strong className="text-white">1h de inatividade</strong>, o menu será reenviado automaticamente. Se um atendente humano assumir a conversa, o menu <strong className="text-white">não será enviado</strong>.
                </p>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Coluna Esquerda */}
                <div className="space-y-5">
                  {/* Tipo */}
                  <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-6">
                    <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-4 flex items-center gap-2">
                      <LayoutList className="w-3.5 h-3.5 text-[#00d2ff]/50" /> Tipo de Menu
                    </p>
                    <div className="flex gap-3">
                      {(["list", "button"] as const).map((t) => (
                        <button
                          key={t}
                          type="button"
                          onClick={() => setConfig({ ...config, tipo: t })}
                          className={`flex-1 py-3 rounded-2xl text-xs font-black uppercase tracking-widest border transition-all ${
                            config.tipo === t
                              ? "bg-[#00d2ff]/20 text-[#00d2ff] border-[#00d2ff]"
                              : "bg-black/20 text-slate-500 border-white/5 hover:text-white"
                          }`}
                        >
                          {t === "list" ? "📋 Lista" : "🔘 Botões"}
                        </button>
                      ))}
                    </div>
                    <p className="text-[10px] text-slate-600 mt-3 italic">
                      {config.tipo === "list"
                        ? "Lista expansível com título, descrição e botão para abrir."
                        : "Botões de resposta rápida (máx. 3 botões no WhatsApp)."}
                    </p>
                  </div>

                  {/* Campos do menu */}
                  <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-6 space-y-4">
                    <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-2">
                      <AlertCircle className="w-3.5 h-3.5 text-[#00d2ff]/50" /> Conteúdo da Mensagem
                    </p>

                    <div className="space-y-1.5">
                      <label className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Título</label>
                      <input
                        type="text"
                        value={config.titulo}
                        onChange={(e) => setConfig({ ...config, titulo: e.target.value })}
                        className={inputClass}
                        placeholder="Ex: Atendimento"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Mensagem</label>
                      <textarea
                        rows={3}
                        value={config.texto}
                        onChange={(e) => setConfig({ ...config, texto: e.target.value })}
                        className={`${inputClass} resize-none`}
                        placeholder="Ex: Olá! Como posso ajudar você hoje?"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Rodapé</label>
                      <input
                        type="text"
                        value={config.rodape}
                        onChange={(e) => setConfig({ ...config, rodape: e.target.value })}
                        className={inputClass}
                        placeholder="Ex: Escolha uma opção abaixo"
                      />
                    </div>

                    {config.tipo === "list" && (
                      <div className="space-y-1.5">
                        <label className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                          Texto do botão
                        </label>
                        <input
                          type="text"
                          value={config.botao}
                          onChange={(e) => setConfig({ ...config, botao: e.target.value })}
                          className={inputClass}
                          placeholder="Ex: Ver opções"
                        />
                      </div>
                    )}
                  </div>
                </div>

                {/* Coluna Direita — Opções */}
                <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-6">
                  <div className="flex items-center justify-between mb-5">
                    <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-2">
                      <Plus className="w-3.5 h-3.5 text-[#00d2ff]/50" /> Opções ({config.opcoes.length})
                    </p>
                    <button
                      type="button"
                      onClick={addOpcao}
                      className="text-[10px] text-[#00d2ff]/70 hover:text-[#00d2ff] flex items-center gap-1.5 border border-[#00d2ff]/20 hover:border-[#00d2ff]/40 px-3 py-1.5 rounded-xl transition-all font-bold uppercase tracking-wider"
                    >
                      <Plus className="w-3 h-3" /> Adicionar
                    </button>
                  </div>

                  <div className="space-y-3">
                    {config.opcoes.map((opcao, idx) => (
                      <motion.div
                        key={opcao.id}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="flex gap-2 items-start bg-black/30 rounded-2xl border border-white/5 p-4"
                      >
                        <div className="w-6 h-6 rounded-lg bg-[#00d2ff]/10 border border-[#00d2ff]/20 flex items-center justify-center text-[10px] font-black text-[#00d2ff] flex-shrink-0 mt-0.5">
                          {idx + 1}
                        </div>
                        <div className="flex-1 space-y-2">
                          <input
                            type="text"
                            value={opcao.titulo}
                            onChange={(e) => setOpcao(idx, "titulo", e.target.value)}
                            className="w-full bg-transparent border-b border-white/10 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 pb-1 transition-colors"
                            placeholder="Título da opção"
                          />
                          <input
                            type="text"
                            value={opcao.descricao}
                            onChange={(e) => setOpcao(idx, "descricao", e.target.value)}
                            className="w-full bg-transparent text-xs text-slate-500 placeholder-slate-700 focus:outline-none"
                            placeholder="Descrição (opcional)"
                          />
                        </div>
                        <button
                          type="button"
                          onClick={() => removeOpcao(idx)}
                          className="p-1.5 text-slate-700 hover:text-red-400 transition-colors mt-0.5 flex-shrink-0"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </motion.div>
                    ))}

                    {config.opcoes.length === 0 && (
                      <div className="text-center py-10 text-slate-600">
                        <LayoutList className="w-8 h-8 mx-auto mb-2 opacity-30" />
                        <p className="text-xs font-bold uppercase tracking-widest">Nenhuma opção ainda</p>
                        <p className="text-[10px] mt-1">Clique em &quot;Adicionar&quot; para criar opções.</p>
                      </div>
                    )}
                  </div>

                  {config.tipo === "button" && config.opcoes.length > 3 && (
                    <div className="mt-4 p-3 bg-red-500/5 border border-red-500/20 rounded-2xl flex items-center gap-2">
                      <AlertCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
                      <p className="text-[10px] text-red-400 font-bold uppercase tracking-wider">
                        Tipo &quot;Botões&quot; suporta no máximo 3 opções no WhatsApp.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
