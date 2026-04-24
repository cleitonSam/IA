"use client";
import React, { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import axios from "axios";
import { X, Save, Trash2, Loader2 } from "lucide-react";
import { TEMPLATES_FLUXO } from "../templates";

interface FlowTemplate {
  id: number;
  nome: string;
  categoria: string;
  descricao: string | null;
  publico: boolean;
  proprio: boolean;
  created_at: string;
  flow_data: { ativo: boolean; nodes: unknown[]; edges: unknown[] };
}

interface SaveTemplateForm {
  nome: string;
  categoria: string;
  descricao: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  currentFlow: { ativo: boolean; nodes: unknown[]; edges: unknown[] };
  onLoadTemplate: (flowData: { ativo: boolean; nodes: unknown[]; edges: unknown[] }) => void;
}

const CATEGORIAS = [
  { key: "todos", label: "Todos" },
  { key: "geral", label: "Geral" },
  { key: "academia", label: "Academia" },
  { key: "restaurante", label: "Restaurante" },
  { key: "clinica", label: "Clínica" },
  { key: "ecommerce", label: "E-commerce" },
];

const CATEGORY_COLORS: Record<string, string> = {
  academia: "#22c55e",
  restaurante: "#f97316",
  clinica: "#06b6d4",
  ecommerce: "#a855f7",
  geral: "#3b82f6",
};

export default function TemplatesModal({ open, onClose, currentFlow, onLoadTemplate }: Props) {
  const [templates, setTemplates] = useState<FlowTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("todos");
  const [showSaveForm, setShowSaveForm] = useState(false);
  const [saveForm, setSaveForm] = useState<SaveTemplateForm>({ nome: "", categoria: "geral", descricao: "" });
  const [saving, setSaving] = useState(false);
  const [confirmLoad, setConfirmLoad] = useState<FlowTemplate | null>(null);

  const getConfig = () => ({
    headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
  });

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    try {
      let list: FlowTemplate[] = [];
      try {
        const res = await axios.get("/api-backend/management/flow-templates", getConfig());
        list = res.data;
      } catch (e) {
        console.warn("Templates remotos nao acessiveis", e);
      }
      // Mescla templates built-in (sempre disponiveis, nao podem ser deletados)
      const builtin: FlowTemplate[] = TEMPLATES_FLUXO.map((t, i) => ({
        id: -1000 - i,
        nome: t.nome + " (built-in)",
        categoria: t.nome.toLowerCase().includes("academia") ? "academia"
          : t.nome.toLowerCase().includes("clinica") ? "clinica"
          : t.nome.toLowerCase().includes("imobili") ? "geral"
          : t.nome.toLowerCase().includes("ecommerce") || t.nome.toLowerCase().includes("e-commerce") ? "ecommerce"
          : "geral",
        descricao: t.descricao,
        publico: true,
        proprio: false,
        created_at: new Date().toISOString(),
        flow_data: { ativo: t.ativo, nodes: t.nodes, edges: t.edges },
      }));
      setTemplates([...builtin, ...list]);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) fetchTemplates();
  }, [open, fetchTemplates]);

  const handleSaveTemplate = async () => {
    if (!saveForm.nome.trim()) return;
    setSaving(true);
    try {
      await axios.post("/api-backend/management/flow-templates", {
        nome: saveForm.nome,
        categoria: saveForm.categoria,
        descricao: saveForm.descricao || null,
        flow_data: currentFlow,
        publico: false,
      }, getConfig());
      setShowSaveForm(false);
      setSaveForm({ nome: "", categoria: "geral", descricao: "" });
      await fetchTemplates();
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteTemplate = async (id: number) => {
    if (id < 0) {
      alert("Templates built-in nao podem ser deletados.");
      return;
    }
    try {
      await axios.delete(`/api-backend/management/flow-templates/${id}`, getConfig());
      setTemplates((t) => t.filter((tpl) => tpl.id !== id));
    } catch (e) {
      console.error(e);
    }
  };

  const handleLoadTemplate = (tpl: FlowTemplate) => {
    if (confirmLoad?.id === tpl.id) {
      onLoadTemplate(tpl.flow_data);
      setConfirmLoad(null);
      onClose();
    } else {
      setConfirmLoad(tpl);
    }
  };

  const filtered = tab === "todos" ? templates : templates.filter((t) => t.categoria === tab);

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
        onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      >
        <motion.div
          initial={{ scale: 0.95, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.95, opacity: 0 }}
          transition={{ type: "spring", stiffness: 400, damping: 35 }}
          className="bg-[#0a1628] border border-white/10 rounded-2xl w-full max-w-3xl max-h-[85vh] flex flex-col overflow-hidden shadow-2xl"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
            <div>
              <h2 className="text-base font-black text-white">Templates de Fluxo</h2>
              <p className="text-[10px] text-slate-500">Carregue um template pronto ou salve seu fluxo atual</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowSaveForm(!showSaveForm)}
                className="flex items-center gap-2 px-4 py-2 bg-[#00d2ff]/10 border border-[#00d2ff]/20 text-[#00d2ff] text-[11px] font-black uppercase tracking-widest rounded-xl hover:bg-[#00d2ff]/20 transition-all"
              >
                <Save className="w-3.5 h-3.5" />
                Salvar como Template
              </button>
              <button type="button" onClick={onClose}
                className="p-2 rounded-xl text-slate-600 hover:text-white hover:bg-white/5 transition-all">
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Formulário de salvar */}
          <AnimatePresence>
            {showSaveForm && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="border-b border-white/5 overflow-hidden"
              >
                <div className="px-6 py-4 bg-[#00d2ff]/5 space-y-3">
                  <p className="text-[10px] font-black text-[#00d2ff] uppercase tracking-widest">Salvar fluxo atual como template</p>
                  <div className="flex gap-3">
                    <input
                      type="text"
                      className="flex-1 bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-white text-[12px] placeholder-slate-600 focus:outline-none focus:border-white/20"
                      placeholder="Nome do template..."
                      value={saveForm.nome}
                      onChange={(e) => setSaveForm((f) => ({ ...f, nome: e.target.value }))}
                    />
                    <select
                      className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-white text-[12px] focus:outline-none focus:border-white/20"
                      value={saveForm.categoria}
                      onChange={(e) => setSaveForm((f) => ({ ...f, categoria: e.target.value }))}
                    >
                      {CATEGORIAS.filter((c) => c.key !== "todos").map((c) => (
                        <option key={c.key} value={c.key}>{c.label}</option>
                      ))}
                    </select>
                  </div>
                  <input
                    type="text"
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-white text-[12px] placeholder-slate-600 focus:outline-none focus:border-white/20"
                    placeholder="Descrição breve (opcional)..."
                    value={saveForm.descricao}
                    onChange={(e) => setSaveForm((f) => ({ ...f, descricao: e.target.value }))}
                  />
                  <div className="flex justify-end gap-2">
                    <button type="button" onClick={() => setShowSaveForm(false)}
                      className="px-4 py-2 rounded-xl text-[11px] font-bold text-slate-400 hover:text-white transition-all">
                      Cancelar
                    </button>
                    <button type="button" onClick={handleSaveTemplate} disabled={!saveForm.nome.trim() || saving}
                      className="flex items-center gap-2 px-4 py-2 bg-[#00d2ff] text-black text-[11px] font-black uppercase tracking-wider rounded-xl disabled:opacity-50 hover:bg-[#00d2ff]/90 transition-all">
                      {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                      Salvar
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Tabs */}
          <div className="flex gap-1 px-6 py-3 border-b border-white/5 overflow-x-auto shrink-0">
            {CATEGORIAS.map((cat) => (
              <button key={cat.key} type="button" onClick={() => setTab(cat.key)}
                className={`px-3 py-1.5 rounded-lg text-[11px] font-bold whitespace-nowrap transition-all ${
                  tab === cat.key
                    ? "bg-white/10 text-white border border-white/20"
                    : "text-slate-500 hover:text-white hover:bg-white/5"
                }`}>
                {cat.label}
              </button>
            ))}
          </div>

          {/* Lista de templates */}
          <div className="flex-1 overflow-y-auto p-6">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 text-[#00d2ff] animate-spin" />
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-center py-12">
                <p className="text-slate-600 text-sm">Nenhum template encontrado.</p>
                <p className="text-slate-700 text-[11px] mt-1">Salve seu fluxo atual como template clicando em "Salvar como Template".</p>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                {filtered.map((tpl) => {
                  const color = CATEGORY_COLORS[tpl.categoria] || "#3b82f6";
                  const isConfirming = confirmLoad?.id === tpl.id;
                  return (
                    <div key={tpl.id}
                      className="group relative bg-black/30 border border-white/8 rounded-2xl p-4 hover:border-white/15 transition-all"
                      style={{ boxShadow: isConfirming ? `0 0 15px ${color}44` : undefined }}
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <div className="w-2 h-2 rounded-full" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />
                          <span className="text-[9px] font-black uppercase tracking-widest" style={{ color }}>
                            {tpl.categoria}
                          </span>
                          {tpl.publico && (
                            <span className="text-[8px] font-bold text-slate-600 border border-slate-700 rounded px-1">público</span>
                          )}
                        </div>
                        {tpl.proprio && (
                          <button type="button" onClick={() => handleDeleteTemplate(tpl.id)}
                            className="opacity-0 group-hover:opacity-100 p-1 rounded text-slate-600 hover:text-red-400 transition-all">
                            <Trash2 className="w-3 h-3" />
                          </button>
                        )}
                      </div>

                      <h3 className="text-[12px] font-black text-white mb-1">{tpl.nome}</h3>
                      {tpl.descricao && (
                        <p className="text-[10px] text-slate-500 mb-3 line-clamp-2">{tpl.descricao}</p>
                      )}

                      <div className="flex items-center justify-between">
                        <span className="text-[9px] text-slate-700">
                          {(tpl.flow_data?.nodes?.length || 0)} nós · {(tpl.flow_data?.edges?.length || 0)} conexões
                        </span>
                        <button type="button" onClick={() => handleLoadTemplate(tpl)}
                          className={`px-3 py-1.5 rounded-lg text-[10px] font-black transition-all ${
                            isConfirming
                              ? "bg-amber-500 text-black"
                              : "bg-white/10 text-white hover:bg-white/20"
                          }`}>
                          {isConfirming ? "⚠️ Confirmar?" : "Usar Template"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
