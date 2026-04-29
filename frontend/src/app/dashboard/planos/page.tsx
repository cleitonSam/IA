"use client";

import React, { useState, useEffect } from "react";
import {
  CreditCard, Plus, Trash2, Edit2, Loader2, Save, X,
  CheckCircle2, RefreshCw, ToggleLeft, ToggleRight, Link
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";
import { apiGet, apiPost, apiPut, apiDelete, ApiException } from "@/lib/api";
import type { Plano, Unidade } from "@/types";

const emptyPlano: Plano = {
  nome: "", valor: null, valor_promocional: null, meses_promocionais: null,
  descricao: "", diferenciais: "", link_venda: "",
  unidade_id: null, ativo: true, ordem: 0,
};

export default function PlanosPage() {
  const [planos, setPlanos] = useState<Plano[]>([]);
  const [unidades, setUnidades] = useState<Unidade[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingPlano, setEditingPlano] = useState<Plano | null>(null);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [syncMsg, setSyncMsg] = useState<{ text: string; type: "success" | "error" } | null>(null);
  const [formData, setFormData] = useState<Plano>(emptyPlano);
  const [filterUnidade, setFilterUnidade] = useState<number | "all">("all");

  const fetchData = async () => {
    const [planosData, unitData] = await Promise.all([
      apiGet<Plano[]>("/management/planos"),
      apiGet<Unidade[] | { data: Unidade[] }>("/dashboard/unidades"),
    ]);
    setPlanos(planosData);
    setUnidades(Array.isArray(unitData) ? unitData : (unitData as { data: Unidade[] }).data ?? []);
  };

  useEffect(() => {
    fetchData().catch(console.error).finally(() => setLoading(false));
  }, []);

  const handleOpenModal = (plano: Plano | null = null) => {
    setEditingPlano(plano);
    setFormData(plano ? { ...plano } : emptyPlano);
    setSaveError(null);
    setSuccess(false);
    setIsModalOpen(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveError(null);
    // Validacao visivel (em vez do popup HTML5 que some no scroll)
    if (!formData.nome || !String(formData.nome).trim()) {
      setSaveError("⚠️ Preencha o NOME do plano antes de salvar.");
      return;
    }
    setSaving(true);
    try {
      if (editingPlano?.id) {
        await apiPut(`/management/planos/${editingPlano.id}`, formData);
      } else {
        await apiPost("/management/planos", formData);
      }
      setSuccess(true);
      setTimeout(() => { setSuccess(false); setIsModalOpen(false); fetchData(); }, 900);
    } catch (e) {
      const msg = e instanceof ApiException ? e.message : (e instanceof Error ? e.message : "Erro ao salvar plano.");
      setSaveError(msg);
      console.error("[planos] erro ao salvar:", e);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Excluir este plano?")) return;
    try {
      await apiDelete(`/management/planos/${id}`);
      fetchData();
    } catch (e) {
      alert(e instanceof ApiException ? e.message : "Erro ao excluir.");
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const res = await apiPost<{ sincronizados: number }>("/management/planos/sync");
      setSyncMsg({ text: `✅ ${res.sincronizados} plano(s) sincronizado(s) do Evo`, type: "success" });
      fetchData();
    } catch (e) {
      setSyncMsg({ text: e instanceof ApiException ? e.message : "Erro ao sincronizar.", type: "error" });
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncMsg(null), 4000);
    }
  };

  const filteredPlanos = filterUnidade === "all"
    ? planos
    : planos.filter(p => p.unidade_id === filterUnidade || (filterUnidade === 0 && !p.unidade_id));

  const inputClass = "w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-3.5 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 transition-all font-medium text-sm";
  const labelClass = "block text-xs font-semibold text-slate-400 mb-1.5 uppercase tracking-wider";

  const fmtValor = (v: number | null) =>
    v != null ? `R$ ${v.toFixed(2).replace(".", ",")}` : "—";

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="planos" />

      <main className="flex-1 min-w-0 overflow-auto">
        <div className="p-6 md:p-8 max-w-6xl mx-auto space-y-6">

          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-[#00d2ff]/20 to-[#7b2ff7]/20 flex items-center justify-center">
                <CreditCard className="w-5 h-5 text-[#00d2ff]" />
              </div>
              <div>
                <h1 className="text-2xl font-bold">Planos</h1>
                <p className="text-slate-500 text-sm">Gerencie os planos enviados pela IA nas conversas</p>
              </div>
            </div>
            <div className="flex gap-2 flex-wrap">
              <button
                onClick={handleSync}
                disabled={syncing}
                className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-sm font-medium transition-all disabled:opacity-50"
              >
                {syncing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                Sincronizar Evo
              </button>
              <button
                onClick={() => handleOpenModal()}
                className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-[#00d2ff]/80 to-[#7b2ff7]/80 hover:from-[#00d2ff] hover:to-[#7b2ff7] text-white text-sm font-semibold transition-all"
              >
                <Plus className="w-4 h-4" />
                Novo Plano
              </button>
            </div>
          </div>

          {/* Sync feedback */}
          <AnimatePresence>
            {syncMsg && (
              <motion.div
                initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                className={`px-5 py-3 rounded-2xl border text-sm ${syncMsg.type === "error" ? "bg-red-500/10 border-red-500/20 text-red-400" : "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"}`}
              >
                {syncMsg.text}
              </motion.div>
            )}
          </AnimatePresence>

          {/* Filter by unit */}
          {unidades.length > 0 && (
            <div className="flex gap-2 flex-wrap">
              <button
                onClick={() => setFilterUnidade("all")}
                className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${filterUnidade === "all" ? "bg-[#00d2ff]/20 text-[#00d2ff] border border-[#00d2ff]/30" : "bg-slate-800 text-slate-400 hover:text-white border border-transparent"}`}
              >
                Todos
              </button>
              <button
                onClick={() => setFilterUnidade(0)}
                className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${filterUnidade === 0 ? "bg-[#00d2ff]/20 text-[#00d2ff] border border-[#00d2ff]/30" : "bg-slate-800 text-slate-400 hover:text-white border border-transparent"}`}
              >
                Global
              </button>
              {unidades.map(u => (
                <button
                  key={u.id}
                  onClick={() => setFilterUnidade(u.id)}
                  className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${filterUnidade === u.id ? "bg-[#00d2ff]/20 text-[#00d2ff] border border-[#00d2ff]/30" : "bg-slate-800 text-slate-400 hover:text-white border border-transparent"}`}
                >
                  {u.nome}
                </button>
              ))}
            </div>
          )}

          {/* Content */}
          {loading ? (
            <div className="flex items-center justify-center py-24">
              <Loader2 className="w-8 h-8 animate-spin text-[#00d2ff]" />
            </div>
          ) : filteredPlanos.length === 0 ? (
            <div className="text-center py-24 text-slate-500">
              <CreditCard className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p className="text-lg">Nenhum plano cadastrado</p>
              <p className="text-sm mt-1">Crie manualmente ou sincronize do Evo</p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filteredPlanos.map(plano => (
                <motion.div
                  key={plano.id}
                  layout
                  initial={{ opacity: 0, scale: 0.96 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className={`relative bg-slate-900/60 border rounded-3xl p-5 flex flex-col gap-3 transition-all ${plano.ativo ? "border-white/8 hover:border-[#00d2ff]/20" : "border-white/4 opacity-50"}`}
                >
                  {/* Badge unidade */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1">
                      <span className="text-xs font-semibold text-[#00d2ff]/70 uppercase tracking-wider">
                        {plano.unidade_nome || "Global"}
                      </span>
                      <h3 className="text-base font-bold mt-0.5 leading-tight">{plano.nome}</h3>
                    </div>
                    <div className="flex gap-1 shrink-0">
                      <button
                        onClick={() => handleOpenModal(plano)}
                        className="p-2 rounded-xl hover:bg-white/8 text-slate-400 hover:text-white transition-all"
                      >
                        <Edit2 className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => plano.id && handleDelete(plano.id)}
                        className="p-2 rounded-xl hover:bg-red-500/10 text-slate-400 hover:text-red-400 transition-all"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* Valores */}
                  <div className="flex items-end gap-3">
                    <div>
                      <span className="text-2xl font-extrabold text-white">{fmtValor(plano.valor)}</span>
                      <span className="text-xs text-slate-500 ml-1">/mês</span>
                    </div>
                    {plano.valor_promocional && (
                      <div className="text-xs text-emerald-400 font-semibold bg-emerald-500/10 px-2 py-1 rounded-lg">
                        Promo {fmtValor(plano.valor_promocional)} × {plano.meses_promocionais}m
                      </div>
                    )}
                  </div>

                  {/* Diferenciais */}
                  {plano.diferenciais && (
                    <p className="text-xs text-slate-500 line-clamp-2">{plano.diferenciais}</p>
                  )}

                  {/* Link + ativo */}
                  <div className="flex items-center justify-between mt-auto pt-2 border-t border-white/5">
                    {plano.link_venda ? (
                      <a
                        href={plano.link_venda} target="_blank" rel="noopener noreferrer"
                        className="flex items-center gap-1 text-xs text-[#00d2ff]/70 hover:text-[#00d2ff] transition-colors"
                      >
                        <Link className="w-3 h-3" /> Ver link
                      </a>
                    ) : (
                      <span className="text-xs text-slate-600 italic">Sem link</span>
                    )}
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${plano.ativo ? "bg-emerald-500/10 text-emerald-400" : "bg-slate-700 text-slate-500"}`}>
                      {plano.ativo ? "Ativo" : "Inativo"}
                    </span>
                  </div>

                  {plano.id_externo && (
                    <span className="absolute top-3 right-3 text-[10px] text-slate-600 font-mono">EVO</span>
                  )}
                </motion.div>
              ))}
            </div>
          )}
        </div>
      </main>

      {/* Modal */}
      <AnimatePresence>
        {isModalOpen && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
            onClick={e => { if (e.target === e.currentTarget) setIsModalOpen(false); }}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              className="w-full max-w-xl bg-[#0a0f1e] border border-white/8 rounded-3xl p-6 shadow-2xl max-h-[90vh] overflow-y-auto"
            >
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-bold">
                  {editingPlano?.id ? "Editar Plano" : "Novo Plano"}
                </h2>
                <button onClick={() => setIsModalOpen(false)} className="p-2 rounded-xl hover:bg-white/8 text-slate-400 hover:text-white">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <form onSubmit={handleSave} className="space-y-4">
                {/* Nome */}
                <div>
                  <label className={labelClass}>Nome do Plano *</label>
                  <input
                    required
                    className={inputClass}
                    placeholder="Ex: Plano Básico, Premium Anual..."
                    value={formData.nome}
                    onChange={e => setFormData(p => ({ ...p, nome: e.target.value }))}
                  />
                </div>

                {/* Valores */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelClass}>Valor (R$)</label>
                    <input
                      type="number" step="0.01" min="0"
                      className={inputClass}
                      placeholder="99.90"
                      value={formData.valor ?? ""}
                      onChange={e => setFormData(p => ({ ...p, valor: e.target.value ? parseFloat(e.target.value) : null }))}
                    />
                  </div>
                  <div>
                    <label className={labelClass}>Valor Promo (R$)</label>
                    <input
                      type="number" step="0.01" min="0"
                      className={inputClass}
                      placeholder="79.90"
                      value={formData.valor_promocional ?? ""}
                      onChange={e => setFormData(p => ({ ...p, valor_promocional: e.target.value ? parseFloat(e.target.value) : null }))}
                    />
                  </div>
                </div>

                {/* Meses promo + Ordem */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelClass}>Meses Promoção</label>
                    <input
                      type="number" min="1"
                      className={inputClass}
                      placeholder="3"
                      value={formData.meses_promocionais ?? ""}
                      onChange={e => setFormData(p => ({ ...p, meses_promocionais: e.target.value ? parseInt(e.target.value) : null }))}
                    />
                  </div>
                  <div>
                    <label className={labelClass}>Ordem</label>
                    <input
                      type="number" min="0"
                      className={inputClass}
                      placeholder="0"
                      value={formData.ordem}
                      onChange={e => setFormData(p => ({ ...p, ordem: parseInt(e.target.value) || 0 }))}
                    />
                  </div>
                </div>

                {/* Unidade */}
                <div>
                  <label className={labelClass}>Unidade (deixe vazio para global)</label>
                  <select
                    className={inputClass + " appearance-none"}
                    value={formData.unidade_id ?? ""}
                    onChange={e => setFormData(p => ({ ...p, unidade_id: e.target.value ? parseInt(e.target.value) : null }))}
                  >
                    <option value="">Global (todas as unidades)</option>
                    {unidades.map(u => (
                      <option key={u.id} value={u.id}>{u.nome}</option>
                    ))}
                  </select>
                </div>

                {/* Link venda */}
                <div>
                  <label className={labelClass}>Link de Venda</label>
                  <input
                    type="url"
                    className={inputClass}
                    placeholder="https://..."
                    value={formData.link_venda}
                    onChange={e => setFormData(p => ({ ...p, link_venda: e.target.value }))}
                  />
                </div>

                {/* Diferenciais */}
                <div>
                  <label className={labelClass}>Diferenciais (separe por vírgula)</label>
                  <input
                    className={inputClass}
                    placeholder="musculação, cardio, piscina, spinning..."
                    value={formData.diferenciais}
                    onChange={e => setFormData(p => ({ ...p, diferenciais: e.target.value }))}
                  />
                </div>

                {/* Descrição */}
                <div>
                  <label className={labelClass}>Descrição</label>
                  <textarea
                    rows={3}
                    className={inputClass + " resize-none"}
                    placeholder="Descrição do plano para a IA usar nas conversas..."
                    value={formData.descricao}
                    onChange={e => setFormData(p => ({ ...p, descricao: e.target.value }))}
                  />
                </div>

                {/* Ativo toggle */}
                <div className="flex items-center justify-between px-4 py-3 bg-slate-900/40 rounded-2xl border border-white/6">
                  <span className="text-sm font-medium">Plano ativo</span>
                  <button
                    type="button"
                    onClick={() => setFormData(p => ({ ...p, ativo: !p.ativo }))}
                    className="transition-colors"
                  >
                    {formData.ativo
                      ? <ToggleRight className="w-8 h-8 text-[#00d2ff]" />
                      : <ToggleLeft className="w-8 h-8 text-slate-500" />
                    }
                  </button>
                </div>

                {saveError && (
                  <motion.div
                    initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
                    className="sticky bottom-16 px-4 py-3 rounded-2xl bg-red-500/15 border border-red-500/30 text-red-300 text-sm font-semibold shadow-lg shadow-red-500/10 flex items-start gap-2"
                  >
                    <span className="text-base leading-none mt-0.5">⚠️</span>
                    <span className="flex-1 break-words">{saveError}</span>
                  </motion.div>
                )}
                {/* Botão salvar */}
                <button
                  type="submit"
                  disabled={saving || success}
                  className="w-full py-3.5 rounded-2xl bg-gradient-to-r from-[#00d2ff]/80 to-[#7b2ff7]/80 hover:from-[#00d2ff] hover:to-[#7b2ff7] font-semibold text-white transition-all disabled:opacity-70 flex items-center justify-center gap-2"
                >
                  {success ? (
                    <><CheckCircle2 className="w-4 h-4" /> Salvo!</>
                  ) : saving ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Salvando...</>
                  ) : (
                    <><Save className="w-4 h-4" /> Salvar Plano</>
                  )}
                </button>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
