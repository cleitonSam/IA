"use client";

import React, { useEffect, useState } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import { Tag, Loader2, RefreshCw, Users, X } from "lucide-react";
import DashboardSidebar from "@/components/DashboardSidebar";

type CwLabel = { id: number; title: string; description: string; color: string; show_on_sidebar: boolean };
type CwContact = { id: number; name: string; phone_number: string; email: string; thumbnail: string };

export default function EtiquetasPage() {
  const [labels, setLabels] = useState<CwLabel[]>([]);
  const [labelsLoading, setLabelsLoading] = useState(false);
  const [labelsErro, setLabelsErro] = useState<string | null>(null);
  const [selectedLabel, setSelectedLabel] = useState<CwLabel | null>(null);
  const [labelContacts, setLabelContacts] = useState<CwContact[]>([]);
  const [labelContactsLoading, setLabelContactsLoading] = useState(false);
  const [labelContactsTotal, setLabelContactsTotal] = useState(0);

  const getToken = () => ({ headers: { Authorization: `Bearer ${typeof window !== "undefined" ? localStorage.getItem("token") : ""}` } });

  const fetchLabels = () => {
    setLabelsLoading(true);
    setLabelsErro(null);
    axios.get("/api-backend/management/chatwoot/labels", getToken())
      .then(r => {
        if (r.data?.erro) setLabelsErro(r.data.erro);
        setLabels(Array.isArray(r.data?.labels) ? r.data.labels : []);
      })
      .catch(e => setLabelsErro(e?.response?.data?.detail || "Falha ao carregar etiquetas"))
      .finally(() => setLabelsLoading(false));
  };

  const openLabelContacts = (label: CwLabel) => {
    setSelectedLabel(label);
    setLabelContacts([]);
    setLabelContactsTotal(0);
    setLabelContactsLoading(true);
    axios.get(`/api-backend/management/chatwoot/labels/${encodeURIComponent(label.title)}/contacts`, getToken())
      .then(r => {
        setLabelContacts(Array.isArray(r.data?.contacts) ? r.data.contacts : []);
        setLabelContactsTotal(r.data?.total || 0);
      })
      .catch(() => {})
      .finally(() => setLabelContactsLoading(false));
  };

  useEffect(() => { fetchLabels(); }, []);

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="etiquetas" />
      <main className="flex-1 min-w-0 overflow-auto">
        <div className="fixed top-0 right-0 w-[500px] h-[400px] bg-amber-400/3 rounded-full blur-[120px] pointer-events-none" />
        <div className="relative z-10 p-8 lg:p-10 max-w-6xl mx-auto pb-20">

          <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-1.5 h-5 bg-amber-400 rounded-full" />
                <span className="text-[10px] font-black text-amber-400 uppercase tracking-[0.4em]">Chatwoot</span>
              </div>
              <h1 className="text-4xl font-black tracking-tight" style={{ background: "linear-gradient(135deg,#fff 0%,#fbbf24 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                Etiquetas
              </h1>
              <p className="text-slate-500 mt-2 text-sm italic max-w-2xl">
                Todas as etiquetas configuradas no Chatwoot. Clique numa etiqueta pra ver os contatos vinculados.
              </p>
            </div>
            <button onClick={fetchLabels} disabled={labelsLoading}
              className="flex items-center gap-2 px-5 py-3 rounded-2xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-sm font-semibold transition-all disabled:opacity-50">
              {labelsLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
              Atualizar
            </button>
          </div>

          {labelsErro && (
            <div className="mb-6 px-5 py-4 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
              ⚠️ {labelsErro}
            </div>
          )}

          {labelsLoading ? (
            <div className="flex items-center justify-center py-24">
              <Loader2 className="w-7 h-7 text-amber-400 animate-spin" />
            </div>
          ) : labels.length === 0 ? (
            <div className="text-center py-24 rounded-3xl border border-dashed border-white/5 bg-white/[0.01]">
              <Tag className="w-10 h-10 text-slate-600 mx-auto mb-4" />
              <p className="text-slate-400 font-bold">Nenhuma etiqueta encontrada.</p>
              <p className="text-slate-600 text-sm mt-1">Crie etiquetas direto no Chatwoot, ou aguarde o bot aplicar quando identificar alunos.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {labels.map((label, i) => (
                <motion.button
                  key={label.id}
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  onClick={() => openLabelContacts(label)}
                  className="group text-left bg-slate-900/50 border border-white/5 hover:border-amber-400/30 rounded-2xl p-5 transition-all duration-200 cursor-pointer"
                >
                  <div className="flex items-start gap-3">
                    <span
                      className="w-3 h-3 rounded-full mt-1.5 flex-shrink-0 ring-2 ring-white/10"
                      style={{ backgroundColor: label.color || "#10b981" }}
                    />
                    <div className="flex-1 min-w-0">
                      <p className="font-mono text-sm font-black text-white truncate group-hover:text-amber-400 transition-colors">
                        {label.title}
                      </p>
                      {label.description && (
                        <p className="text-[10px] text-slate-500 mt-1 line-clamp-2">{label.description}</p>
                      )}
                      <div className="flex items-center gap-2 mt-3 pt-3 border-t border-white/5">
                        <Users className="w-3 h-3 text-slate-600" />
                        <span className="text-[10px] font-black uppercase tracking-widest text-slate-500 group-hover:text-amber-400 transition-colors">
                          Ver contatos
                        </span>
                      </div>
                    </div>
                  </div>
                </motion.button>
              ))}
            </div>
          )}

          <div className="mt-8 p-5 bg-amber-400/5 border border-amber-400/10 rounded-2xl flex items-start gap-4">
            <div className="w-10 h-10 rounded-xl bg-amber-400/10 flex items-center justify-center flex-shrink-0">
              <Tag className="w-5 h-5 text-amber-400" />
            </div>
            <p className="text-[11px] font-black uppercase tracking-widest text-slate-400 italic leading-relaxed">
              Etiquetas com prefixo <span className="text-amber-400 not-italic font-mono normal-case">aluno-{"{slug}"}</span> são aplicadas automaticamente
              quando o bot identifica que o telefone do contato é aluno em uma das franqueadas.
            </p>
          </div>
        </div>
      </main>

      {/* Modal Contatos */}
      <AnimatePresence>
        {selectedLabel && (
          <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="absolute inset-0 bg-[#020617]/90 backdrop-blur-2xl"
              onClick={() => setSelectedLabel(null)} />
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 20 }}
              className="bg-[#080f1e] border border-white/10 rounded-[2.5rem] w-full max-w-2xl overflow-hidden relative shadow-2xl"
            >
              <div className="px-8 py-6 border-b border-white/5 flex items-center justify-between bg-slate-900/30">
                <div className="flex items-center gap-3">
                  <span className="w-4 h-4 rounded-full ring-2 ring-white/10"
                        style={{ backgroundColor: selectedLabel.color || "#10b981" }} />
                  <div>
                    <h2 className="text-base font-black tracking-tight font-mono">{selectedLabel.title}</h2>
                    <p className="text-slate-500 text-[10px] mt-0.5 font-bold uppercase tracking-widest">
                      {labelContactsTotal} contato{labelContactsTotal !== 1 ? "s" : ""}
                    </p>
                  </div>
                </div>
                <motion.button whileHover={{ rotate: 90 }} onClick={() => setSelectedLabel(null)}
                  className="p-3 hover:bg-white/5 rounded-2xl transition-all border border-white/5 text-slate-500 hover:text-white">
                  <X className="w-5 h-5" />
                </motion.button>
              </div>

              <div className="p-6 max-h-[70vh] overflow-y-auto">
                {labelContactsLoading ? (
                  <div className="flex items-center justify-center py-16">
                    <Loader2 className="w-7 h-7 text-amber-400 animate-spin" />
                  </div>
                ) : labelContacts.length === 0 ? (
                  <div className="text-center py-16">
                    <Users className="w-10 h-10 text-slate-600 mx-auto mb-3" />
                    <p className="text-slate-400 text-sm">Nenhum contato com essa etiqueta.</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {labelContacts.map(c => (
                      <div key={c.id} className="flex items-center gap-4 p-4 rounded-2xl bg-slate-900/40 border border-white/5 hover:border-amber-400/20 transition-colors">
                        {c.thumbnail ? (
                          <img src={c.thumbnail} alt={c.name} className="w-10 h-10 rounded-full object-cover" />
                        ) : (
                          <div className="w-10 h-10 rounded-full bg-amber-400/10 border border-amber-400/20 flex items-center justify-center text-amber-400 font-black text-sm uppercase">
                            {(c.name || c.phone_number || "?").charAt(0)}
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="font-semibold text-sm text-white truncate">{c.name || "Sem nome"}</p>
                          <div className="flex items-center gap-3 text-[11px] text-slate-500 mt-0.5 font-mono">
                            {c.phone_number && <span>{c.phone_number}</span>}
                            {c.email && <span className="truncate">{c.email}</span>}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
