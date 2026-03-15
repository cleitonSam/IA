"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";
import { motion } from "framer-motion";
import {
  Building2, Mail, Plus, Send, LogOut, LayoutDashboard,
  Loader2, CheckCircle, AlertCircle, ChevronRight, Users
} from "lucide-react";

export default function AdminPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [empresas, setEmpresas] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // Criar empresa
  const [novaEmpresa, setNovaEmpresa] = useState({ nome: "", cnpj: "", telefone: "" });
  const [criandoEmpresa, setCriandoEmpresa] = useState(false);
  const [msgEmpresa, setMsgEmpresa] = useState<{ ok: boolean; text: string } | null>(null);

  // Enviar convite
  const [convite, setConvite] = useState({ email: "", empresa_id: "" });
  const [enviandoConvite, setEnviandoConvite] = useState(false);
  const [msgConvite, setMsgConvite] = useState<{ ok: boolean; text: string } | null>(null);

  const getConfig = () => ({
    headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
  });

  const fetchData = async () => {
    try {
      const meRes = await axios.get("/api-backend/auth/me", getConfig());
      if (meRes.data.perfil !== "admin_master") {
        router.push("/dashboard");
        return;
      }
      setUser(meRes.data);
    } catch {
      router.push("/login");
      return;
    }

    try {
      const empRes = await axios.get("/api-backend/auth/empresas", getConfig());
      setEmpresas(empRes.data);
    } catch (err: any) {
      setMsgEmpresa({ ok: false, text: err.response?.data?.detail || "Erro ao carregar empresas." });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const handleCriarEmpresa = async (e: React.FormEvent) => {
    e.preventDefault();
    setCriandoEmpresa(true);
    setMsgEmpresa(null);
    try {
      await axios.post("/api-backend/auth/create-empresa", novaEmpresa, getConfig());
      setMsgEmpresa({ ok: true, text: `Empresa "${novaEmpresa.nome}" criada com sucesso!` });
      setNovaEmpresa({ nome: "", cnpj: "", telefone: "" });
      await fetchData();
    } catch (err: any) {
      setMsgEmpresa({ ok: false, text: err.response?.data?.detail || "Erro ao criar empresa." });
    } finally {
      setCriandoEmpresa(false);
    }
  };

  const handleEnviarConvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!convite.empresa_id) {
      setMsgConvite({ ok: false, text: "Selecione uma empresa." });
      return;
    }
    setEnviandoConvite(true);
    setMsgConvite(null);
    try {
      await axios.post(
        "/api-backend/auth/invite",
        { email: convite.email, empresa_id: Number(convite.empresa_id) },
        getConfig()
      );
      setMsgConvite({ ok: true, text: `Convite enviado para ${convite.email}!` });
      setConvite({ email: "", empresa_id: "" });
    } catch (err: any) {
      setMsgConvite({ ok: false, text: err.response?.data?.detail || "Erro ao enviar convite." });
    } finally {
      setEnviandoConvite(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-mesh flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-mesh text-white flex">
      {/* Sidebar */}
      <aside className="w-64 border-r border-white/5 bg-black/20 backdrop-blur-xl hidden lg:flex flex-col p-6">
        <div className="mb-10 flex items-center gap-3">
          <div className="w-10 h-10 bg-primary rounded-xl flex items-center justify-center shadow-neon-primary">
            <Building2 className="w-6 h-6 text-white" />
          </div>
          <span className="font-bold text-xl tracking-tight">Antigravity IA</span>
        </div>
        <nav className="flex-1 space-y-2">
          <a href="/dashboard" className="flex items-center gap-3 px-4 py-3 rounded-xl text-gray-400 hover:bg-white/5 transition-all">
            <LayoutDashboard className="w-5 h-5" />
            <span className="font-medium">Dashboard</span>
          </a>
          <a href="/admin" className="flex items-center gap-3 px-4 py-3 rounded-xl bg-primary/10 text-primary border border-primary/20 transition-all">
            <Building2 className="w-5 h-5" />
            <span className="font-medium">Painel de Gestão</span>
          </a>
        </nav>
        <div className="pt-6 border-t border-white/5">
          <div className="text-xs text-gray-500 mb-3 px-1">{user?.nome}</div>
          <button
            onClick={() => { localStorage.removeItem("token"); router.push("/login"); }}
            className="flex items-center gap-3 px-4 py-3 rounded-xl text-accent hover:bg-accent/10 transition-all w-full"
          >
            <LogOut className="w-5 h-5" />
            <span className="font-medium">Sair</span>
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 p-8 lg:p-12 overflow-y-auto">
        <h1 className="text-3xl font-bold mb-2">Painel de Gestão</h1>
        <p className="text-gray-400 mb-10 text-sm">Gerencie empresas e convites de acesso.</p>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">

          {/* Criar empresa */}
          <div className="glass-morphism p-8 rounded-2xl">
            <h2 className="text-xl font-bold mb-6 flex items-center gap-2">
              <Plus className="w-5 h-5 text-primary" />
              Nova Empresa
            </h2>
            <form onSubmit={handleCriarEmpresa} className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-1 block">Nome *</label>
                <input
                  type="text"
                  value={novaEmpresa.nome}
                  onChange={(e) => setNovaEmpresa({ ...novaEmpresa, nome: e.target.value })}
                  placeholder="Academia XYZ"
                  className="w-full bg-white/5 border border-white/10 rounded-xl py-3 px-4 focus:outline-none focus:ring-2 focus:ring-primary/50 text-white placeholder:text-gray-600"
                  required
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-1 block">CNPJ</label>
                <input
                  type="text"
                  value={novaEmpresa.cnpj}
                  onChange={(e) => setNovaEmpresa({ ...novaEmpresa, cnpj: e.target.value })}
                  placeholder="00.000.000/0001-00"
                  className="w-full bg-white/5 border border-white/10 rounded-xl py-3 px-4 focus:outline-none focus:ring-2 focus:ring-primary/50 text-white placeholder:text-gray-600"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-1 block">Telefone</label>
                <input
                  type="text"
                  value={novaEmpresa.telefone}
                  onChange={(e) => setNovaEmpresa({ ...novaEmpresa, telefone: e.target.value })}
                  placeholder="(11) 99999-9999"
                  className="w-full bg-white/5 border border-white/10 rounded-xl py-3 px-4 focus:outline-none focus:ring-2 focus:ring-primary/50 text-white placeholder:text-gray-600"
                />
              </div>
              {msgEmpresa && (
                <div className={`flex items-center gap-2 text-sm p-3 rounded-lg ${msgEmpresa.ok ? "bg-green-500/10 text-green-400" : "bg-accent/10 text-accent"}`}>
                  {msgEmpresa.ok ? <CheckCircle className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
                  {msgEmpresa.text}
                </div>
              )}
              <button
                type="submit"
                disabled={criandoEmpresa}
                className="w-full bg-primary hover:bg-primary/80 text-white font-bold py-3 px-6 rounded-xl flex items-center justify-center gap-2 transition-all disabled:opacity-50"
              >
                {criandoEmpresa ? <Loader2 className="w-5 h-5 animate-spin" /> : <><Plus className="w-5 h-5" /> Criar Empresa</>}
              </button>
            </form>
          </div>

          {/* Enviar convite */}
          <div className="glass-morphism p-8 rounded-2xl">
            <h2 className="text-xl font-bold mb-6 flex items-center gap-2">
              <Send className="w-5 h-5 text-secondary" />
              Enviar Convite
            </h2>
            <form onSubmit={handleEnviarConvite} className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-1 block">Empresa *</label>
                <select
                  value={convite.empresa_id}
                  onChange={(e) => setConvite({ ...convite, empresa_id: e.target.value })}
                  className="w-full bg-white/5 border border-white/10 rounded-xl py-3 px-4 focus:outline-none focus:ring-2 focus:ring-primary/50 text-white"
                  required
                >
                  <option value="" className="bg-[#020617]">Selecione a empresa...</option>
                  {empresas.map((emp) => (
                    <option key={emp.id} value={emp.id} className="bg-[#020617]">
                      {emp.nome}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-1 block">E-mail do convidado *</label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
                  <input
                    type="email"
                    value={convite.email}
                    onChange={(e) => setConvite({ ...convite, email: e.target.value })}
                    placeholder="gestor@academia.com"
                    className="w-full bg-white/5 border border-white/10 rounded-xl py-3 pl-11 pr-4 focus:outline-none focus:ring-2 focus:ring-primary/50 text-white placeholder:text-gray-600"
                    required
                  />
                </div>
              </div>
              {msgConvite && (
                <div className={`flex items-center gap-2 text-sm p-3 rounded-lg ${msgConvite.ok ? "bg-green-500/10 text-green-400" : "bg-accent/10 text-accent"}`}>
                  {msgConvite.ok ? <CheckCircle className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
                  {msgConvite.text}
                </div>
              )}
              <button
                type="submit"
                disabled={enviandoConvite || empresas.length === 0}
                className="w-full bg-secondary hover:bg-secondary/80 text-white font-bold py-3 px-6 rounded-xl flex items-center justify-center gap-2 transition-all disabled:opacity-50"
              >
                {enviandoConvite ? <Loader2 className="w-5 h-5 animate-spin" /> : <><Send className="w-5 h-5" /> Enviar Convite</>}
              </button>
              {empresas.length === 0 && (
                <p className="text-xs text-gray-500 text-center">Crie uma empresa primeiro para poder enviar convites.</p>
              )}
            </form>
          </div>
        </div>

        {/* Lista de empresas */}
        {empresas.length > 0 && (
          <div className="glass-morphism p-8 rounded-2xl mt-8">
            <h2 className="text-xl font-bold mb-6 flex items-center gap-2">
              <Users className="w-5 h-5 text-primary" />
              Empresas Cadastradas ({empresas.length})
            </h2>
            <div className="space-y-3">
              {empresas.map((emp) => (
                <motion.div
                  key={emp.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex items-center justify-between p-4 rounded-xl bg-white/5 border border-white/5 hover:border-primary/20 transition-all"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 bg-primary/10 rounded-lg flex items-center justify-center font-bold text-primary">
                      {emp.nome?.charAt(0)}
                    </div>
                    <div>
                      <p className="font-bold text-sm">{emp.nome}</p>
                      <p className="text-xs text-gray-500">{emp.cnpj || "CNPJ não informado"} · ID: {emp.id}</p>
                    </div>
                  </div>
                  <span className={`text-xs font-bold px-3 py-1 rounded-full ${emp.status === "active" ? "bg-green-500/10 text-green-400" : "bg-gray-500/10 text-gray-400"}`}>
                    {emp.status === "active" ? "Ativo" : emp.status}
                  </span>
                </motion.div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
