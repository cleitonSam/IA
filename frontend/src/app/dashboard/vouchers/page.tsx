"use client";

import React, { useEffect, useState } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import {
  Ticket, Loader2, RefreshCw, Calendar, Tag as TagIcon, Percent,
  CheckCircle2, AlertCircle, Building2, Search, X,
} from "lucide-react";
import DashboardSidebar from "@/components/DashboardSidebar";

type VoucherDesconto = {
  tipo?: string;
  valor?: number;
  meses?: number | null;
};
type PlanoDetalhe = {
  id_externo: number;
  nome: string;
  valor: number | null;
  unidade_nome: string | null;
};
type Voucher = {
  id: number;
  nome: string;
  tipo: string;
  limited: boolean;
  available: number;
  used: number;
  expira_em: string | null;
  id_memberships: number[];
  site_disponivel: boolean;
  desconto: VoucherDesconto | null;
  tipo_desconto: string | null;
  planos_detalhe?: PlanoDetalhe[];
  planos_nomes?: string[];
  valido_para?: string;
  ativo_local?: boolean;  // toggle local (independente do status EVO)
};

export default function VouchersPage() {
  const [loading, setLoading] = useState(false);
  const [vouchers, setVouchers] = useState<Voucher[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [filtroStatus, setFiltroStatus] = useState<"ativos" | "inativos" | "todos">("ativos");
  const [busca, setBusca] = useState("");
  const [testModal, setTestModal] = useState<{ open: boolean; voucher: Voucher | null }>({ open: false, voucher: null });
  const [testIdMembership, setTestIdMembership] = useState<string>("");
  const [testResult, setTestResult] = useState<any>(null);
  const [testing, setTesting] = useState(false);

  const getToken = () => ({ headers: { Authorization: `Bearer ${typeof window !== "undefined" ? localStorage.getItem("token") : ""}` } });

  const fetchVouchers = () => {
    setLoading(true);
    setErro(null);
    // Pra Inativos/Todos buscamos com only_valid=false e filtramos no client
    const onlyValidParam = filtroStatus === "ativos";
    axios.get(`/api-backend/management/franqueada/vouchers?only_valid=${onlyValidParam}&take=200`, getToken())
      .then(r => setVouchers(Array.isArray(r.data?.vouchers) ? r.data.vouchers : []))
      .catch(e => setErro(e?.response?.data?.detail || "Falha ao carregar vouchers"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchVouchers(); }, [filtroStatus]);

  const toggleAtivoLocal = async (v: Voucher) => {
    const novoAtivo = !(v.ativo_local !== false); // default true
    try {
      await axios.put(
        `/api-backend/management/franqueada/voucher/${v.id}/toggle?ativo=${novoAtivo}`,
        {}, getToken()
      );
      // Atualiza localmente sem refetch
      setVouchers(prev => prev.map(x =>
        x.id === v.id ? { ...x, ativo_local: novoAtivo } : x
      ));
    } catch (e: any) {
      alert("Erro ao alterar voucher: " + (e?.response?.data?.detail || "?"));
    }
  };

  const testarVoucher = async () => {
    if (!testModal.voucher || !testIdMembership) return;
    setTesting(true);
    setTestResult(null);
    try {
      const r = await axios.post(
        `/api-backend/management/franqueada/voucher-verify?voucher=${encodeURIComponent(testModal.voucher.nome)}&id_membership=${testIdMembership}`,
        {}, getToken()
      );
      setTestResult(r.data);
    } catch (e: any) {
      setTestResult({ erro: e?.response?.data?.detail || "Erro" });
    } finally { setTesting(false); }
  };

  // Determina se voucher está ATIVO (não vencido, com vagas, dentro do prazo)
  const isVoucherAtivo = (v: Voucher): boolean => {
    if (v.expira_em) {
      try {
        const exp = new Date(v.expira_em);
        if (exp < new Date()) return false;
      } catch {}
    }
    if (v.limited && (v.available || 0) <= 0) return false;
    return true;
  };

  const vouchersFiltrados = vouchers.filter(v => {
    // Filtro de status
    const ativo = isVoucherAtivo(v);
    if (filtroStatus === "ativos" && !ativo) return false;
    if (filtroStatus === "inativos" && ativo) return false;

    // Filtro de busca
    if (!busca.trim()) return true;
    const q = busca.toLowerCase();
    return (
      v.nome?.toLowerCase().includes(q) ||
      (v.planos_nomes || []).some(p => p.toLowerCase().includes(q))
    );
  });

  const totalAtivos = vouchers.filter(isVoucherAtivo).length;
  const totalInativos = vouchers.filter(v => !isVoucherAtivo(v)).length;

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="vouchers" />
      <main className="flex-1 min-w-0 overflow-auto">
        <div className="fixed top-0 right-0 w-[500px] h-[400px] bg-purple-500/3 rounded-full blur-[120px] pointer-events-none" />
        <div className="relative z-10 p-8 lg:p-10 max-w-7xl mx-auto pb-20">

          {/* Header */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-1.5 h-5 bg-purple-500 rounded-full" />
                <span className="text-[10px] font-black text-purple-400 uppercase tracking-[0.4em]">EVO Franqueada</span>
              </div>
              <h1 className="text-4xl font-black tracking-tight" style={{ background: "linear-gradient(135deg,#fff 0%,#a855f7 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                Vouchers de Desconto
              </h1>
              <p className="text-slate-500 mt-2 text-sm italic max-w-2xl">
                Cupons cadastrados na EVO. A IA usa estes dados pra ofertar desconto estratégico ao cliente
                quando a Personalidade IA tem <span className="text-purple-400 not-italic">Usar Vouchers</span> ativado.
              </p>
            </div>
            <div className="flex gap-2 flex-wrap">
              {/* Filtro tri-state — Ativos / Inativos / Todos */}
              <div className="inline-flex bg-slate-900/60 border border-white/8 rounded-2xl p-1">
                <button onClick={() => setFiltroStatus("ativos")}
                  className={`px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all flex items-center gap-1.5 ${
                    filtroStatus === "ativos" ? "bg-emerald-400/15 text-emerald-400 shadow-inner" : "text-slate-500 hover:text-white"
                  }`}>
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Ativos {filtroStatus === "ativos" && totalAtivos > 0 && <span className="text-[9px] opacity-70">({totalAtivos})</span>}
                </button>
                <button onClick={() => setFiltroStatus("inativos")}
                  className={`px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all flex items-center gap-1.5 ${
                    filtroStatus === "inativos" ? "bg-amber-400/15 text-amber-400 shadow-inner" : "text-slate-500 hover:text-white"
                  }`}>
                  <AlertCircle className="w-3.5 h-3.5" />
                  Inativos {filtroStatus === "inativos" && totalInativos > 0 && <span className="text-[9px] opacity-70">({totalInativos})</span>}
                </button>
                <button onClick={() => setFiltroStatus("todos")}
                  className={`px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
                    filtroStatus === "todos" ? "bg-purple-400/15 text-purple-400 shadow-inner" : "text-slate-500 hover:text-white"
                  }`}>
                  Todos
                </button>
              </div>
              <button onClick={fetchVouchers} disabled={loading}
                className="flex items-center gap-2 px-5 py-3 rounded-2xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-sm font-semibold transition-all disabled:opacity-50">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                Atualizar
              </button>
            </div>
          </div>

          {/* Search */}
          <div className="mb-6 relative max-w-md">
            <Search className="w-4 h-4 absolute left-4 top-1/2 -translate-y-1/2 text-slate-600" />
            <input
              type="text"
              value={busca}
              onChange={e => setBusca(e.target.value)}
              placeholder="Buscar por nome do voucher ou plano..."
              className="w-full pl-12 pr-4 py-3 bg-slate-900/60 border border-white/8 rounded-2xl text-white placeholder-slate-600 focus:outline-none focus:border-purple-400/40 text-sm"
            />
          </div>

          {erro && (
            <div className="mb-6 px-5 py-4 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
              ⚠️ {erro}
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-24">
              <Loader2 className="w-7 h-7 text-purple-400 animate-spin" />
            </div>
          ) : vouchersFiltrados.length === 0 ? (
            <div className="text-center py-24 rounded-3xl border border-dashed border-white/5 bg-white/[0.01]">
              <Ticket className="w-10 h-10 text-slate-600 mx-auto mb-4" />
              <p className="text-slate-400 font-bold">{busca ? "Nenhum voucher para essa busca." : "Nenhum voucher disponível."}</p>
              {!busca && <p className="text-slate-600 text-sm mt-2">Cadastre vouchers no painel da EVO. Eles aparecem aqui automaticamente.</p>}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
              {vouchersFiltrados.map((v, i) => {
                const desc = v.desconto;
                const isPercentage = desc?.tipo === "percentage";
                const ativo = isVoucherAtivo(v);
                return (
                  <motion.div
                    key={v.id}
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.03 }}
                    className={`bg-slate-900/50 border rounded-3xl overflow-hidden transition-all ${
                      v.ativo_local === false
                        ? "border-slate-700/50 opacity-50 hover:opacity-90"
                        : ativo
                          ? "border-white/5 hover:border-purple-400/30"
                          : "border-amber-400/10 opacity-70 hover:opacity-100"
                    }`}
                  >
                    <div className="p-6">
                      {/* Header card */}
                      <div className="flex items-start justify-between mb-4">
                        <div className="flex items-center gap-3">
                          <div className={`w-12 h-12 rounded-2xl flex items-center justify-center ${
                            ativo ? "bg-purple-400/10 border border-purple-400/20" : "bg-amber-400/10 border border-amber-400/20"
                          }`}>
                            <Ticket className={`w-6 h-6 ${ativo ? "text-purple-400" : "text-amber-400"}`} />
                          </div>
                          <div>
                            <h3 className="font-black text-base font-mono leading-tight">{v.nome}</h3>
                            <p className="text-[10px] text-slate-500 mt-0.5 uppercase tracking-widest">ID: {v.id} · {v.tipo}</p>
                          </div>
                        </div>
                        <div className="flex flex-col items-end gap-1.5">
                          {/* Status EVO (vencido/disponivel) */}
                          {ativo ? (
                            <span className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-widest text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 px-2.5 py-1 rounded-full">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" /> Válido
                            </span>
                          ) : (
                            <span className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-widest text-amber-400 bg-amber-400/10 border border-amber-400/20 px-2.5 py-1 rounded-full">
                              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> Vencido
                            </span>
                          )}
                          {/* Toggle ativo LOCAL (controle do admin) */}
                          <button type="button" onClick={() => toggleAtivoLocal(v)}
                            title={v.ativo_local !== false ? "Clique pra IA NÃO usar este voucher" : "Clique pra IA voltar a usar este voucher"}
                            className={`flex items-center gap-1.5 text-[9px] font-black uppercase tracking-widest px-2.5 py-1 rounded-full border transition-all ${
                              v.ativo_local !== false
                                ? "text-purple-400 bg-purple-400/10 border-purple-400/20 hover:bg-purple-400/20"
                                : "text-slate-500 bg-slate-700/40 border-slate-600/30 hover:bg-slate-700/60"
                            }`}>
                            <span className={`relative inline-flex h-3 w-5 items-center rounded-full transition-all ${v.ativo_local !== false ? "bg-purple-400" : "bg-slate-600"}`}>
                              <span className={`inline-block h-2 w-2 transform rounded-full bg-white transition-all ${v.ativo_local !== false ? "translate-x-2.5" : "translate-x-0.5"}`} />
                            </span>
                            {v.ativo_local !== false ? "IA Usa" : "IA Ignora"}
                          </button>
                        </div>
                      </div>

                      {/* Desconto destaque */}
                      {desc?.valor && (
                        <div className="bg-gradient-to-br from-purple-500/15 to-fuchsia-500/10 border border-purple-400/20 rounded-2xl p-4 mb-4">
                          <p className="text-[10px] font-black uppercase tracking-widest text-purple-400 mb-1">Desconto</p>
                          <p className="text-3xl font-black text-white">
                            {isPercentage ? `${desc.valor}%` : `R$${desc.valor}`}
                            <span className="text-sm text-slate-400 font-medium ml-2">
                              {isPercentage ? "off" : "off"}
                              {desc.meses ? ` · ${desc.meses} mês${desc.meses > 1 ? "es" : ""}` : ""}
                            </span>
                          </p>
                        </div>
                      )}

                      {/* Planos aplicáveis */}
                      <div className="space-y-2 mb-4">
                        <p className="text-[10px] font-black uppercase tracking-widest text-slate-500">Aplicável em</p>
                        {v.id_memberships?.length === 0 ? (
                          <span className="inline-flex items-center gap-1.5 text-[10px] font-black uppercase tracking-widest text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 px-2.5 py-1.5 rounded-full">
                            ✨ Todos os planos
                          </span>
                        ) : v.planos_detalhe && v.planos_detalhe.length > 0 ? (
                          <div className="flex flex-wrap gap-1.5">
                            {v.planos_detalhe.map(p => (
                              <span key={p.id_externo} className="inline-flex items-center gap-1 text-[10px] font-bold text-cyan-400 bg-cyan-400/10 border border-cyan-400/20 px-2.5 py-1.5 rounded-full">
                                <TagIcon className="w-3 h-3" /> {p.nome}
                                {p.unidade_nome && <span className="text-slate-500">· {p.unidade_nome}</span>}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <p className="text-[11px] text-amber-400 italic">⚠️ Planos id {v.id_memberships?.join(", ")} (não cadastrados no painel local)</p>
                        )}
                      </div>

                      {/* Footer info */}
                      <div className="pt-4 border-t border-white/5 grid grid-cols-2 gap-3 text-[11px]">
                        <div className="flex items-center gap-2 text-slate-500">
                          <Calendar className="w-3 h-3 text-purple-400/50" />
                          <span>{v.expira_em || "Sem prazo"}</span>
                        </div>
                        <div className="flex items-center gap-2 text-slate-500">
                          {v.limited
                            ? <span className="text-amber-400">{v.available}/{(v.available || 0) + (v.used || 0)} restantes</span>
                            : <span>♾️ Ilimitado</span>}
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={() => { setTestModal({ open: true, voucher: v }); setTestIdMembership(""); setTestResult(null); }}
                      className="w-full px-6 py-3 bg-white/[0.02] hover:bg-purple-400/10 border-t border-white/5 text-[10px] font-black uppercase tracking-[0.25em] text-slate-500 hover:text-purple-400 transition-all flex items-center justify-center gap-2"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Testar aplicabilidade
                    </button>
                  </motion.div>
                );
              })}
            </div>
          )}

          {/* Footer info */}
          <div className="mt-8 p-5 bg-purple-400/5 border border-purple-400/10 rounded-2xl flex items-start gap-4">
            <div className="w-10 h-10 rounded-xl bg-purple-400/10 flex items-center justify-center flex-shrink-0">
              <Percent className="w-5 h-5 text-purple-400" />
            </div>
            <div className="text-[11px] font-black uppercase tracking-widest text-slate-400 italic leading-relaxed space-y-2">
              <p>
                <span className="text-purple-400 not-italic normal-case font-semibold">Como a IA usa os vouchers:</span> ela só
                oferta quando o cliente reclama do valor, demonstra hesitação ou pede desconto explícito.
                Não oferta em saudações ou pra alunos já ativos.
              </p>
              <p>
                <span className="text-purple-400 not-italic normal-case font-semibold">Pra ativar:</span> vai em
                <a href="/dashboard/personality" className="text-cyan-400 underline hover:text-cyan-300 not-italic normal-case ml-1">Personalidade IA</a>
                {" "}e liga o toggle <span className="text-purple-400 not-italic normal-case">Usar Vouchers</span>.
              </p>
            </div>
          </div>
        </div>
      </main>

      {/* Modal de teste */}
      <AnimatePresence>
        {testModal.open && testModal.voucher && (
          <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="absolute inset-0 bg-[#020617]/90 backdrop-blur-2xl"
              onClick={() => setTestModal({ open: false, voucher: null })} />
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 20 }}
              className="bg-[#080f1e] border border-white/10 rounded-[2.5rem] w-full max-w-lg overflow-hidden relative shadow-2xl"
            >
              <div className="px-8 py-6 border-b border-white/5 flex items-center justify-between bg-slate-900/30">
                <div className="flex items-center gap-3">
                  <Ticket className="w-5 h-5 text-purple-400" />
                  <h2 className="font-black tracking-tight">Testar voucher <span className="font-mono text-purple-400">{testModal.voucher.nome}</span></h2>
                </div>
                <button onClick={() => setTestModal({ open: false, voucher: null })}
                  className="p-2 hover:bg-white/5 rounded-2xl text-slate-500 hover:text-white">
                  <X className="w-5 h-5" />
                </button>
              </div>
              <div className="p-8 space-y-5">
                <p className="text-xs text-slate-500 italic">
                  Passa o ID externo do plano (idMembership da EVO) pra testar se o voucher é aplicável.
                </p>
                {testModal.voucher.planos_detalhe && testModal.voucher.planos_detalhe.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {testModal.voucher.planos_detalhe.map(p => (
                      <button key={p.id_externo}
                        onClick={() => setTestIdMembership(String(p.id_externo))}
                        className="text-[10px] px-3 py-2 rounded-xl bg-cyan-400/10 border border-cyan-400/20 text-cyan-400 hover:bg-cyan-400/20 font-bold">
                        {p.nome} (id {p.id_externo})
                      </button>
                    ))}
                  </div>
                )}
                <input type="number" value={testIdMembership}
                  onChange={e => setTestIdMembership(e.target.value)}
                  placeholder="510"
                  className="w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white font-mono"
                />
                <button onClick={testarVoucher} disabled={testing || !testIdMembership}
                  className="w-full bg-purple-500 text-white px-6 py-3 rounded-2xl font-black uppercase tracking-widest text-sm flex items-center justify-center gap-2 disabled:opacity-40">
                  {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                  Validar voucher
                </button>
                {testResult && (
                  <pre className="p-4 rounded-xl bg-black/40 border border-white/5 text-[11px] font-mono text-slate-300 overflow-auto whitespace-pre-wrap break-all max-h-80">
                    {JSON.stringify(testResult, null, 2)}
                  </pre>
                )}
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
