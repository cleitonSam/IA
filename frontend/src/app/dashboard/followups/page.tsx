"use client";

import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  Send, Plus, Pencil, Trash2, ChevronLeft, ChevronRight,
  Flame, Thermometer, Snowflake, Clock, CheckCircle2,
  XCircle, AlertCircle, Building2, RefreshCw, X, Eye,
  ToggleLeft, ToggleRight, Zap
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import DashboardSidebar from "@/components/DashboardSidebar";

// ─── Types ──────────────────────────────────────────────────────────────────

interface FollowupTemplate {
  id: number;
  nome: string;
  mensagem: string;
  delay_minutos: number;
  ordem: number;
  tipo: string;
  ativo: boolean;
  unidade_id: number | null;
  unidade_nome: string | null;
}

interface FollowupHistoryItem {
  id: number;
  status: string;
  mensagem: string;
  agendado_para: string;
  enviado_em: string | null;
  erro_log: string | null;
  ordem: number;
  contato_nome: string;
  contato_fone: string;
  score_lead: number;
  unidade_nome: string | null;
  template_nome: string | null;
}

interface Stats {
  pendentes: number;
  enviados_hoje: number;
  cancelados_hoje: number;
  erros: number;
}

interface Unidade {
  id: number;
  nome: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const getToken = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
});

function formatDelay(minutos: number): string {
  if (minutos < 60) return `${minutos}min`;
  if (minutos < 1440) return `${Math.round(minutos / 60)}h`;
  const dias = Math.round(minutos / 1440);
  return `${dias} dia${dias > 1 ? "s" : ""}`;
}

function tempBadge(minutos: number) {
  if (minutos < 120)
    return { label: "Quente", icon: Flame, cls: "text-orange-400 bg-orange-500/10 border-orange-500/20" };
  if (minutos < 1440)
    return { label: "Morno", icon: Thermometer, cls: "text-amber-400 bg-amber-500/10 border-amber-500/20" };
  return { label: "Frio", icon: Snowflake, cls: "text-sky-400 bg-sky-500/10 border-sky-500/20" };
}

function scoreBadge(score: number) {
  if (score >= 4) return { label: "Quente", cls: "text-orange-400 bg-orange-500/10" };
  if (score >= 2) return { label: "Morno", cls: "text-amber-400 bg-amber-500/10" };
  return { label: "Frio", cls: "text-sky-400 bg-sky-500/10" };
}

const statusStyle: Record<string, string> = {
  pendente:  "bg-amber-500/15 text-amber-400 border border-amber-500/20",
  enviado:   "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20",
  cancelado: "bg-slate-500/15 text-slate-400 border border-slate-500/20",
  erro:      "bg-red-500/15 text-red-400 border border-red-500/20",
};

const statusIcon: Record<string, React.ElementType> = {
  pendente:  Clock,
  enviado:   CheckCircle2,
  cancelado: XCircle,
  erro:      AlertCircle,
};

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

// ─── Modal de template ────────────────────────────────────────────────────────

interface TemplateModalProps {
  open: boolean;
  initial: Partial<FollowupTemplate> | null;
  unidades: Unidade[];
  onClose: () => void;
  onSave: (data: Partial<FollowupTemplate>) => Promise<void>;
}

function TemplateModal({ open, initial, unidades, onClose, onSave }: TemplateModalProps) {
  const [nome, setNome] = useState("");
  const [mensagem, setMensagem] = useState("");
  const [delayVal, setDelayVal] = useState(60);
  const [delayUnit, setDelayUnit] = useState<"minutos"|"horas"|"dias">("horas");
  const [ordem, setOrdem] = useState(1);
  const [ativo, setAtivo] = useState(true);
  const [unidadeId, setUnidadeId] = useState<number | "">("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setNome(initial.nome || "");
      setMensagem(initial.mensagem || "");
      const raw = initial.delay_minutos || 60;
      if (raw % 1440 === 0) { setDelayVal(raw / 1440); setDelayUnit("dias"); }
      else if (raw % 60 === 0) { setDelayVal(raw / 60); setDelayUnit("horas"); }
      else { setDelayVal(raw); setDelayUnit("minutos"); }
      setOrdem(initial.ordem || 1);
      setAtivo(initial.ativo ?? true);
      setUnidadeId(initial.unidade_id ?? "");
    } else {
      setNome(""); setMensagem(""); setDelayVal(2); setDelayUnit("horas");
      setOrdem(1); setAtivo(true); setUnidadeId("");
    }
  }, [open, initial]);

  function toMinutos() {
    if (delayUnit === "dias") return delayVal * 1440;
    if (delayUnit === "horas") return delayVal * 60;
    return delayVal;
  }

  async function handleSave() {
    if (!nome.trim() || !mensagem.trim()) return;
    setSaving(true);
    try {
      await onSave({
        nome: nome.trim(),
        mensagem: mensagem.trim(),
        delay_minutos: toMinutos(),
        ordem,
        ativo,
        unidade_id: unidadeId === "" ? null : Number(unidadeId),
      });
      onClose();
    } finally {
      setSaving(false);
    }
  }

  const temp = tempBadge(toMinutos());
  const TempIcon = temp.icon;

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 16 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 16 }}
            transition={{ duration: 0.18 }}
            className="relative w-full max-w-lg bg-slate-900 border border-white/10 rounded-2xl p-6 shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-white font-semibold text-lg">
                {initial?.id ? "Editar Template" : "Novo Template"}
              </h3>
              <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              {/* Nome */}
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">Nome do template</label>
                <input
                  value={nome} onChange={e => setNome(e.target.value)}
                  placeholder="Ex: Lembrete inicial, Oferta especial..."
                  className="w-full bg-slate-800 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-[#00d2ff]/50"
                />
              </div>

              {/* Mensagem */}
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">
                  Mensagem template
                  <span className="ml-2 text-slate-600">— use <code className="text-[#00d2ff]/80">{"{{nome}}"}</code> e <code className="text-[#00d2ff]/80">{"{{unidade}}"}</code></span>
                </label>
                <textarea
                  value={mensagem} onChange={e => setMensagem(e.target.value)}
                  rows={4}
                  placeholder={"Oi {{nome}}! 👋 Vimos que você se interessou pela academia {{unidade}}..."}
                  className="w-full bg-slate-800 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-[#00d2ff]/50 resize-none"
                />
                <p className="text-xs text-slate-600 mt-1">A IA reescreve a mensagem em tom natural adaptado ao perfil do lead.</p>
              </div>

              {/* Delay */}
              <div>
                <label className="block text-xs text-slate-400 mb-1.5 flex items-center gap-1.5">
                  Enviar após
                  <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${temp.cls}`}>
                    <TempIcon className="w-3 h-3" /> {temp.label}
                  </span>
                </label>
                <div className="flex gap-2">
                  <input
                    type="number" min={1} value={delayVal} onChange={e => setDelayVal(Number(e.target.value))}
                    className="w-24 bg-slate-800 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white focus:outline-none focus:border-[#00d2ff]/50"
                  />
                  <select
                    value={delayUnit} onChange={e => setDelayUnit(e.target.value as any)}
                    className="flex-1 bg-slate-800 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white focus:outline-none focus:border-[#00d2ff]/50"
                  >
                    <option value="minutos">minutos</option>
                    <option value="horas">horas</option>
                    <option value="dias">dias</option>
                  </select>
                </div>
              </div>

              {/* Ordem + Unidade */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1.5">Posição na sequência</label>
                  <input
                    type="number" min={1} value={ordem} onChange={e => setOrdem(Number(e.target.value))}
                    className="w-full bg-slate-800 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white focus:outline-none focus:border-[#00d2ff]/50"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1.5">Unidade (global se vazio)</label>
                  <select
                    value={unidadeId} onChange={e => setUnidadeId(e.target.value === "" ? "" : Number(e.target.value))}
                    className="w-full bg-slate-800 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white focus:outline-none focus:border-[#00d2ff]/50"
                  >
                    <option value="">Todas as unidades</option>
                    {unidades.map(u => <option key={u.id} value={u.id}>{u.nome}</option>)}
                  </select>
                </div>
              </div>

              {/* Ativo */}
              <div className="flex items-center justify-between bg-slate-800/60 rounded-lg px-3 py-2.5">
                <span className="text-sm text-slate-300">Ativar template</span>
                <button onClick={() => setAtivo(!ativo)} className="transition-colors">
                  {ativo
                    ? <ToggleRight className="w-6 h-6 text-[#00d2ff]" />
                    : <ToggleLeft className="w-6 h-6 text-slate-600" />}
                </button>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={onClose} className="flex-1 py-2.5 rounded-xl border border-white/10 text-slate-400 text-sm hover:text-white transition-colors">
                Cancelar
              </button>
              <button
                onClick={handleSave} disabled={saving || !nome.trim() || !mensagem.trim()}
                className="flex-1 py-2.5 rounded-xl bg-[#00d2ff] text-slate-950 font-semibold text-sm hover:bg-[#00d2ff]/90 transition-colors disabled:opacity-50"
              >
                {saving ? "Salvando..." : "Salvar"}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ─── Página principal ─────────────────────────────────────────────────────────

export default function FollowupsPage() {
  const [activeTab, setActiveTab] = useState<"sequencia" | "historico">("sequencia");

  // Templates
  const [templates, setTemplates] = useState<FollowupTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editTemplate, setEditTemplate] = useState<FollowupTemplate | null>(null);

  // History
  const [history, setHistory] = useState<FollowupHistoryItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [stats, setStats] = useState<Stats>({ pendentes: 0, enviados_hoje: 0, cancelados_hoje: 0, erros: 0 });
  const [filterStatus, setFilterStatus] = useState("");
  const [filterUnidade, setFilterUnidade] = useState<number | "">("");
  const [offset, setOffset] = useState(0);
  const [expandedMsg, setExpandedMsg] = useState<FollowupHistoryItem | null>(null);
  const limit = 20;

  // Shared
  const [unidades, setUnidades] = useState<Unidade[]>([]);

  // ── Load on mount ──
  useEffect(() => {
    axios.get("/api-backend/dashboard/unidades", getToken()).then(r => setUnidades(r.data)).catch(() => {});
    loadTemplates();
  }, []);

  useEffect(() => {
    if (activeTab === "historico") {
      loadStats();
      loadHistory();
    }
  }, [activeTab, filterStatus, filterUnidade, offset]);

  // ── Templates CRUD ──
  async function loadTemplates() {
    setLoadingTemplates(true);
    try {
      const r = await axios.get("/api-backend/management/followup/templates", getToken());
      setTemplates(r.data);
    } catch { /* silent */ } finally {
      setLoadingTemplates(false);
    }
  }

  async function saveTemplate(data: Partial<FollowupTemplate>) {
    if (editTemplate?.id) {
      await axios.put(`/api-backend/management/followup/templates/${editTemplate.id}`, data, getToken());
    } else {
      await axios.post("/api-backend/management/followup/templates", data, getToken());
    }
    await loadTemplates();
  }

  async function toggleAtivo(t: FollowupTemplate) {
    await axios.put(`/api-backend/management/followup/templates/${t.id}`, { ativo: !t.ativo }, getToken());
    setTemplates(prev => prev.map(x => x.id === t.id ? { ...x, ativo: !x.ativo } : x));
  }

  async function deleteTemplate(id: number) {
    if (!confirm("Remover este template? Follow-ups pendentes serão cancelados.")) return;
    await axios.delete(`/api-backend/management/followup/templates/${id}`, getToken());
    setTemplates(prev => prev.filter(t => t.id !== id));
  }

  // ── History ──
  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (filterStatus) params.set("status", filterStatus);
      if (filterUnidade) params.set("unidade_id", String(filterUnidade));
      const r = await axios.get(`/api-backend/management/followup/history?${params}`, getToken());
      setHistory(r.data);
    } catch { /* silent */ } finally {
      setLoadingHistory(false);
    }
  }, [filterStatus, filterUnidade, offset]);

  async function loadStats() {
    try {
      const r = await axios.get("/api-backend/management/followup/stats", getToken());
      setStats(r.data);
    } catch { /* silent */ }
  }

  function openCreate() { setEditTemplate(null); setModalOpen(true); }
  function openEdit(t: FollowupTemplate) { setEditTemplate(t); setModalOpen(true); }

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-screen bg-slate-950 text-white overflow-hidden">
      <DashboardSidebar activePage="followups" />

      <div className="flex-1 flex flex-col overflow-hidden lg:ml-64">
        {/* Header */}
        <header className="flex-shrink-0 border-b border-white/5 bg-slate-950/80 backdrop-blur-md px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-[#00d2ff]/10 border border-[#00d2ff]/20 flex items-center justify-center">
                <Send className="w-4 h-4 text-[#00d2ff]" />
              </div>
              <div>
                <h1 className="text-lg font-semibold text-white leading-none">Follow-ups</h1>
                <p className="text-xs text-slate-500 mt-0.5">Sequências automáticas com IA adaptativa por temperatura de lead</p>
              </div>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 mt-4 bg-slate-900/50 rounded-lg p-1 w-fit">
            {([["sequencia", "Sequência", Zap], ["historico", "Histórico", Clock]] as const).map(([id, label, Icon]) => (
              <button
                key={id}
                onClick={() => { setActiveTab(id); setOffset(0); }}
                className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-all ${
                  activeTab === id
                    ? "bg-[#00d2ff] text-slate-950"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                <Icon className="w-3.5 h-3.5" /> {label}
              </button>
            ))}
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-6">

          {/* ── ABA SEQUÊNCIA ── */}
          {activeTab === "sequencia" && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-white font-semibold">Sequência de mensagens</h2>
                  <p className="text-xs text-slate-500 mt-0.5">
                    A IA adapta cada mensagem ao perfil do lead (temperatura) antes de enviar.
                  </p>
                </div>
                <button
                  onClick={openCreate}
                  className="flex items-center gap-2 px-4 py-2 bg-[#00d2ff] text-slate-950 rounded-xl text-sm font-semibold hover:bg-[#00d2ff]/90 transition-colors"
                >
                  <Plus className="w-4 h-4" /> Novo template
                </button>
              </div>

              {loadingTemplates ? (
                <div className="flex items-center justify-center py-20">
                  <RefreshCw className="w-5 h-5 text-slate-600 animate-spin" />
                </div>
              ) : templates.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-20 text-center">
                  <div className="w-14 h-14 rounded-2xl bg-slate-800/60 border border-white/5 flex items-center justify-center mb-4">
                    <Send className="w-6 h-6 text-slate-600" />
                  </div>
                  <p className="text-slate-400 font-medium">Nenhum template ainda</p>
                  <p className="text-slate-600 text-sm mt-1">Crie o primeiro passo da sequência automática</p>
                  <button onClick={openCreate} className="mt-4 flex items-center gap-2 px-4 py-2 bg-slate-800 border border-white/10 rounded-xl text-sm text-slate-300 hover:border-[#00d2ff]/30 hover:text-white transition-colors">
                    <Plus className="w-4 h-4" /> Criar template
                  </button>
                </div>
              ) : (
                <div className="max-w-2xl mx-auto">
                  {templates.map((t, idx) => {
                    const temp = tempBadge(t.delay_minutos);
                    const TempIcon = temp.icon;
                    return (
                      <div key={t.id} className="relative">
                        {/* Connector line */}
                        {idx < templates.length - 1 && (
                          <div className="absolute left-6 top-full h-6 w-px border-l-2 border-dashed border-white/10 z-0" />
                        )}
                        <motion.div
                          layout
                          className={`relative z-10 mb-6 rounded-2xl border p-5 transition-colors ${
                            t.ativo
                              ? "bg-slate-900/70 border-white/8 hover:border-white/15"
                              : "bg-slate-950/50 border-white/5 opacity-60"
                          }`}
                        >
                          {/* Step number bubble */}
                          <div className="absolute -left-3 top-5 w-6 h-6 rounded-full bg-slate-800 border border-white/10 flex items-center justify-center text-xs text-slate-400 font-bold">
                            {t.ordem}
                          </div>

                          <div className="flex items-start gap-3 pl-4">
                            <div className="flex-1 min-w-0">
                              <div className="flex flex-wrap items-center gap-2 mb-2">
                                <span className="text-white font-medium text-sm">{t.nome || "Sem nome"}</span>
                                <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${temp.cls}`}>
                                  <TempIcon className="w-3 h-3" /> {temp.label}
                                </span>
                                {t.unidade_nome && (
                                  <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20">
                                    <Building2 className="w-3 h-3" /> {t.unidade_nome}
                                  </span>
                                )}
                                {!t.unidade_id && (
                                  <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700/40 text-slate-500 border border-white/5">
                                    Global
                                  </span>
                                )}
                              </div>
                              <p className="text-xs text-slate-500 mb-2 flex items-center gap-1.5">
                                <Clock className="w-3 h-3" />
                                Enviado após <span className="text-slate-300 font-medium">{formatDelay(t.delay_minutos)}</span> do início da conversa
                              </p>
                              <p className="text-sm text-slate-400 leading-relaxed line-clamp-2 font-mono bg-slate-800/40 rounded-lg px-3 py-2 border border-white/5">
                                {t.mensagem}
                              </p>
                            </div>

                            {/* Actions */}
                            <div className="flex flex-col items-center gap-2 ml-2 flex-shrink-0">
                              <button onClick={() => toggleAtivo(t)} className="transition-colors" title={t.ativo ? "Desativar" : "Ativar"}>
                                {t.ativo
                                  ? <ToggleRight className="w-5 h-5 text-[#00d2ff]" />
                                  : <ToggleLeft className="w-5 h-5 text-slate-600" />}
                              </button>
                              <button onClick={() => openEdit(t)} className="text-slate-600 hover:text-[#00d2ff] transition-colors" title="Editar">
                                <Pencil className="w-4 h-4" />
                              </button>
                              <button onClick={() => deleteTemplate(t.id)} className="text-slate-600 hover:text-red-400 transition-colors" title="Remover">
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </div>
                        </motion.div>
                      </div>
                    );
                  })}
                </div>
              )}
            </motion.div>
          )}

          {/* ── ABA HISTÓRICO ── */}
          {activeTab === "historico" && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
              {/* Stats strip */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                {[
                  { label: "Enviados hoje", value: stats.enviados_hoje, icon: CheckCircle2, cls: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/20" },
                  { label: "Pendentes", value: stats.pendentes, icon: Clock, cls: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" },
                  { label: "Cancelados hoje", value: stats.cancelados_hoje, icon: XCircle, cls: "text-slate-400", bg: "bg-slate-500/10 border-slate-500/20" },
                  { label: "Com erro", value: stats.erros, icon: AlertCircle, cls: "text-red-400", bg: "bg-red-500/10 border-red-500/20" },
                ].map(s => {
                  const Icon = s.icon;
                  return (
                    <div key={s.label} className={`rounded-xl border p-4 ${s.bg}`}>
                      <div className="flex items-center gap-2 mb-1">
                        <Icon className={`w-4 h-4 ${s.cls}`} />
                        <span className="text-xs text-slate-400">{s.label}</span>
                      </div>
                      <p className={`text-2xl font-bold ${s.cls}`}>{s.value}</p>
                    </div>
                  );
                })}
              </div>

              {/* Filters */}
              <div className="flex flex-wrap gap-3 mb-5">
                <select
                  value={filterStatus}
                  onChange={e => { setFilterStatus(e.target.value); setOffset(0); }}
                  className="bg-slate-900 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-[#00d2ff]/50"
                >
                  <option value="">Todos os status</option>
                  <option value="pendente">Pendente</option>
                  <option value="enviado">Enviado</option>
                  <option value="cancelado">Cancelado</option>
                  <option value="erro">Erro</option>
                </select>
                <select
                  value={filterUnidade}
                  onChange={e => { setFilterUnidade(e.target.value === "" ? "" : Number(e.target.value)); setOffset(0); }}
                  className="bg-slate-900 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-[#00d2ff]/50"
                >
                  <option value="">Todas as unidades</option>
                  {unidades.map(u => <option key={u.id} value={u.id}>{u.nome}</option>)}
                </select>
                <button onClick={() => { loadStats(); loadHistory(); }} className="flex items-center gap-2 px-3 py-2 bg-slate-800 border border-white/10 rounded-lg text-sm text-slate-400 hover:text-white transition-colors">
                  <RefreshCw className="w-3.5 h-3.5" /> Atualizar
                </button>
              </div>

              {/* Table */}
              {loadingHistory ? (
                <div className="flex items-center justify-center py-20">
                  <RefreshCw className="w-5 h-5 text-slate-600 animate-spin" />
                </div>
              ) : history.length === 0 ? (
                <div className="text-center py-20 text-slate-600">Nenhum follow-up encontrado com esses filtros.</div>
              ) : (
                <>
                  <div className="rounded-xl border border-white/5 overflow-hidden">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-white/5 bg-slate-900/60">
                          <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Contato</th>
                          <th className="text-left text-xs text-slate-500 font-medium px-4 py-3 hidden md:table-cell">Unidade</th>
                          <th className="text-left text-xs text-slate-500 font-medium px-4 py-3 hidden lg:table-cell">Lead</th>
                          <th className="text-left text-xs text-slate-500 font-medium px-4 py-3 hidden lg:table-cell">Template</th>
                          <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Agendado</th>
                          <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Status</th>
                          <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Msg IA</th>
                        </tr>
                      </thead>
                      <tbody>
                        {history.map((h, i) => {
                          const StatusIcon = statusIcon[h.status] || Clock;
                          const sb = scoreBadge(h.score_lead || 0);
                          return (
                            <tr key={h.id} className={`border-b border-white/5 hover:bg-white/2 transition-colors ${i % 2 === 0 ? "" : "bg-slate-900/20"}`}>
                              <td className="px-4 py-3">
                                <p className="text-white font-medium text-xs">{h.contato_nome || "—"}</p>
                                <p className="text-slate-500 text-xs">{h.contato_fone || ""}</p>
                              </td>
                              <td className="px-4 py-3 hidden md:table-cell">
                                <span className="text-slate-400 text-xs">{h.unidade_nome || "—"}</span>
                              </td>
                              <td className="px-4 py-3 hidden lg:table-cell">
                                <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${sb.cls}`}>
                                  {sb.label}
                                </span>
                              </td>
                              <td className="px-4 py-3 hidden lg:table-cell">
                                <span className="text-slate-400 text-xs">{h.template_nome || "—"}</span>
                              </td>
                              <td className="px-4 py-3">
                                <span className="text-slate-400 text-xs whitespace-nowrap">{fmtDate(h.agendado_para)}</span>
                                {h.enviado_em && <p className="text-slate-600 text-xs">✓ {fmtDate(h.enviado_em)}</p>}
                              </td>
                              <td className="px-4 py-3">
                                <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${statusStyle[h.status] || ""}`}>
                                  <StatusIcon className="w-3 h-3" />
                                  {h.status}
                                </span>
                                {h.erro_log && <p className="text-red-400/70 text-xs mt-0.5 truncate max-w-[120px]" title={h.erro_log}>{h.erro_log}</p>}
                              </td>
                              <td className="px-4 py-3">
                                <button
                                  onClick={() => setExpandedMsg(h)}
                                  className="text-slate-600 hover:text-[#00d2ff] transition-colors"
                                  title="Ver mensagem enviada pela IA"
                                >
                                  <Eye className="w-4 h-4" />
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* Pagination */}
                  <div className="flex items-center justify-between mt-4">
                    <span className="text-xs text-slate-500">Mostrando {offset + 1}–{offset + history.length}</span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setOffset(Math.max(0, offset - limit))}
                        disabled={offset === 0}
                        className="flex items-center gap-1 px-3 py-1.5 bg-slate-800 border border-white/10 rounded-lg text-xs text-slate-400 hover:text-white disabled:opacity-40 transition-colors"
                      >
                        <ChevronLeft className="w-3.5 h-3.5" /> Anterior
                      </button>
                      <button
                        onClick={() => setOffset(offset + limit)}
                        disabled={history.length < limit}
                        className="flex items-center gap-1 px-3 py-1.5 bg-slate-800 border border-white/10 rounded-lg text-xs text-slate-400 hover:text-white disabled:opacity-40 transition-colors"
                      >
                        Próximo <ChevronRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </>
              )}
            </motion.div>
          )}
        </main>
      </div>

      {/* Template Modal */}
      <TemplateModal
        open={modalOpen}
        initial={editTemplate}
        unidades={unidades}
        onClose={() => setModalOpen(false)}
        onSave={saveTemplate}
      />

      {/* Message Preview Modal */}
      <AnimatePresence>
        {expandedMsg && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
            onClick={() => setExpandedMsg(null)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }}
              className="relative w-full max-w-md bg-slate-900 border border-white/10 rounded-2xl p-6 shadow-2xl"
              onClick={e => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-white font-semibold text-sm">Mensagem enviada pela IA</h3>
                  <p className="text-xs text-slate-500">Para {expandedMsg.contato_nome} • {fmtDate(expandedMsg.enviado_em)}</p>
                </div>
                <button onClick={() => setExpandedMsg(null)} className="text-slate-500 hover:text-white">
                  <X className="w-5 h-5" />
                </button>
              </div>
              <div className="bg-slate-800/60 border border-white/5 rounded-xl p-4">
                <p className="text-slate-200 text-sm leading-relaxed whitespace-pre-wrap">{expandedMsg.mensagem}</p>
              </div>
              <p className="text-xs text-slate-600 mt-3 flex items-center gap-1">
                <Zap className="w-3 h-3 text-[#00d2ff]" />
                Reescrita pela IA com base no template + temperatura do lead
              </p>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
