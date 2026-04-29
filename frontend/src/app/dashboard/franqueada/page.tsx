"use client";

import React, { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import {
  UserCheck, Loader2, Save, CheckCircle2, Globe, ShieldCheck,
  Eye, EyeOff, Search,
} from "lucide-react";
import DashboardSidebar from "@/components/DashboardSidebar";

export default function FranqueadaPage() {
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ dns: "", secret_key: "", ativo: false });
  const [configurado, setConfigurado] = useState(false);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testPhone, setTestPhone] = useState("");
  const [testResult, setTestResult] = useState<any>(null);

  const getToken = () => ({
    headers: { Authorization: `Bearer ${typeof window !== "undefined" ? localStorage.getItem("token") : ""}` },
  });

  useEffect(() => {
    setLoading(true);
    axios.get("/api-backend/management/integrations/evo-franqueada/global", getToken())
      .then(r => {
        const cfg = r.data?.config || {};
        setForm({
          dns: cfg.dns || "",
          secret_key: cfg.secret_key || "",
          ativo: !!r.data?.ativo,
        });
        setConfigurado(!!r.data?.configurado);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await axios.put(
        "/api-backend/management/integrations/evo-franqueada/global",
        { config: { dns: form.dns.trim(), secret_key: form.secret_key.trim() }, ativo: form.ativo },
        getToken()
      );
      setSuccess(true);
      setConfigurado(!!(form.dns && form.secret_key));
      setTimeout(() => setSuccess(false), 1500);
    } catch (e: any) {
      alert("Erro ao salvar: " + (e?.response?.data?.detail || e?.message || "desconhecido"));
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!testPhone.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const r = await axios.get(
        `/api-backend/management/evo/verificar-membro-global?telefone=${encodeURIComponent(testPhone.trim())}`,
        getToken()
      );
      setTestResult(r.data);
    } catch (e: any) {
      setTestResult({ erro: e?.response?.data?.detail || "Falha na requisição" });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#020617] text-white flex">
      <DashboardSidebar activePage="franqueada" />
      <main className="flex-1 min-w-0 overflow-auto">
        <div className="fixed top-0 right-0 w-[500px] h-[400px] bg-emerald-400/3 rounded-full blur-[120px] pointer-events-none" />
        <div className="relative z-10 p-8 lg:p-10 max-w-3xl mx-auto pb-20">

          {/* Header */}
          <div className="mb-12">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-1.5 h-5 bg-emerald-400 rounded-full" />
              <span className="text-[10px] font-black text-emerald-400 uppercase tracking-[0.4em]">EVO Franqueada</span>
            </div>
            <h1 className="text-4xl font-black tracking-tight" style={{ background: "linear-gradient(135deg,#fff 0%,#10b981 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
              Franqueada (Verificar Aluno)
            </h1>
            <p className="text-slate-500 mt-2 text-sm italic max-w-2xl">
              UMA credencial EVO única que serve TODAS as unidades. Usada SOMENTE pra consultar
              <code className="text-emerald-400/80 not-italic font-mono mx-1">GET /members?phone=X</code>
              e identificar se o telefone do contato é aluno. Não puxa planos, não agenda — escopo restrito a leitura.
            </p>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-24">
              <Loader2 className="w-7 h-7 text-emerald-400 animate-spin" />
            </div>
          ) : (
            <div className="space-y-6">

              {/* Status card */}
              <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-6 flex items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-2xl bg-emerald-400/10 border border-emerald-400/20 flex items-center justify-center">
                    <UserCheck className="w-6 h-6 text-emerald-400" />
                  </div>
                  <div>
                    <p className="text-[10px] font-black uppercase tracking-widest text-slate-400">Status</p>
                    <p className={`text-sm font-black mt-1 ${
                      form.ativo && configurado ? "text-emerald-400"
                      : configurado ? "text-amber-400"
                      : "text-slate-500"
                    }`}>
                      {form.ativo && configurado ? "● Online — pronto pra consultar"
                       : configurado ? "○ Configurado mas pausado"
                       : "○ Não configurado"}
                    </p>
                  </div>
                </div>
                <button type="button" onClick={() => setForm({ ...form, ativo: !form.ativo })}
                  className={`relative inline-flex h-7 w-12 items-center rounded-full transition-all ${form.ativo ? "bg-emerald-400" : "bg-slate-700"}`}>
                  <span className={`inline-block h-5 w-5 transform rounded-full bg-white transition-all shadow ${form.ativo ? "translate-x-6" : "translate-x-1"}`} />
                </button>
              </div>

              {/* Credencial */}
              <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-8 space-y-6">
                <h3 className="text-xs font-black uppercase tracking-widest text-slate-400 mb-2">
                  Credencial EVO
                </h3>

                <div className="space-y-3">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-1.5">
                    <Globe className="w-3 h-3 text-emerald-400" /> Subdomínio (DNS)
                  </label>
                  <div className="relative">
                    <input type="text" value={form.dns}
                      onChange={e => setForm({ ...form, dns: e.target.value })}
                      className="w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-emerald-400/40 transition-all font-medium text-sm pr-44"
                      placeholder="goodbe" />
                    <span className="absolute right-4 top-1/2 -translate-y-1/2 text-[10px] text-slate-500 font-mono">.w12app.com.br</span>
                  </div>
                  {form.dns && (
                    <p className="text-[10px] text-emerald-400/70 font-mono pl-1">→ {form.dns}.w12app.com.br</p>
                  )}
                </div>

                <div className="space-y-3">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-1.5">
                    <ShieldCheck className="w-3 h-3 text-emerald-400" /> Secret Key
                  </label>
                  <div className="relative">
                    <input
                      type={showSecret ? "text" : "password"}
                      value={form.secret_key}
                      onChange={e => setForm({ ...form, secret_key: e.target.value })}
                      className="w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-4 text-white placeholder-slate-600 focus:outline-none focus:border-emerald-400/40 transition-all font-mono text-sm pr-14"
                      placeholder="••••••••••••••••••" />
                    <button type="button" onClick={() => setShowSecret(s => !s)}
                      className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white transition-colors p-1">
                      {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <p className="text-[10px] text-slate-600 italic pl-1">
                    GUID da EVO. Esta cred só faz GET /members?phone=X — sem permissão pra outras operações.
                  </p>
                </div>

                <motion.button whileHover={{ scale: 1.01 }} whileTap={{ scale: 0.98 }}
                  type="button" disabled={saving} onClick={handleSave}
                  className="w-full bg-emerald-400 text-black px-8 py-4 rounded-2xl font-black uppercase tracking-widest text-sm flex items-center justify-center gap-2 shadow-[0_0_20px_rgba(16,185,129,0.3)] disabled:opacity-50">
                  {saving ? <><Loader2 className="w-5 h-5 animate-spin" />Salvando</>
                    : success ? <><CheckCircle2 className="w-5 h-5" />Salvo!</>
                    : <><Save className="w-5 h-5" />Salvar Credencial</>}
                </motion.button>
              </div>

              {/* Bloco de teste */}
              <div className="bg-slate-900/50 border border-white/5 rounded-3xl p-8 space-y-4">
                <div className="flex items-center gap-3 mb-2">
                  <Search className="w-5 h-5 text-emerald-400" />
                  <h3 className="text-xs font-black uppercase tracking-widest text-slate-400">
                    Testar (verificar se telefone é aluno)
                  </h3>
                </div>
                <p className="text-xs text-slate-500 italic">
                  Cole um telefone real e clique em Testar. Se a cred estiver certa, retorna os dados do membro na EVO.
                </p>
                <div className="flex gap-2">
                  <input type="text" value={testPhone}
                    onChange={e => setTestPhone(e.target.value)}
                    className="flex-1 bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-3.5 text-white placeholder-slate-600 focus:outline-none focus:border-emerald-400/40 transition-all font-mono text-sm"
                    placeholder="11976804555" />
                  <button type="button" disabled={testing || !testPhone.trim()} onClick={handleTest}
                    className="px-6 py-3.5 bg-emerald-400/10 border border-emerald-400/20 rounded-2xl text-[10px] font-black uppercase tracking-widest text-emerald-400 hover:bg-emerald-400/15 transition-all disabled:opacity-40 flex items-center gap-2">
                    {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                    {testing ? "..." : "Testar"}
                  </button>
                </div>
                {testResult && (
                  <pre className="mt-3 p-4 rounded-xl bg-black/40 border border-white/5 text-[11px] font-mono text-slate-300 overflow-auto whitespace-pre-wrap break-all max-h-80">
                    {JSON.stringify(testResult, null, 2)}
                  </pre>
                )}
              </div>

              {/* Como funciona */}
              <div className="p-5 bg-emerald-400/5 border border-emerald-400/10 rounded-2xl flex items-start gap-4">
                <div className="w-10 h-10 rounded-xl bg-emerald-400/10 flex items-center justify-center flex-shrink-0">
                  <UserCheck className="w-5 h-5 text-emerald-400" />
                </div>
                <div className="text-[11px] font-black uppercase tracking-widest text-slate-400 italic leading-relaxed space-y-2">
                  <p>
                    <span className="text-emerald-400 not-italic normal-case font-semibold">Como funciona:</span> quando
                    um cliente novo manda mensagem, o bot consulta a EVO usando esta credencial para verificar
                    se o telefone do contato é aluno.
                  </p>
                  <p>
                    Se for, aplica a etiqueta <span className="text-emerald-400 not-italic font-mono normal-case">aluno-{"{slug-da-unidade}"}</span> no
                    contato do Chatwoot — visível em <a href="/dashboard/etiquetas" className="text-amber-400 not-italic normal-case underline hover:text-amber-300">Etiquetas</a>.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
