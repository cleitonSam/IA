"use client";

import { Suspense, useState, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Lock, Mail, User, ArrowRight, Loader2, CheckCircle } from "lucide-react";
import axios from "axios";

function RegisterForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token") || "";

  const [invite, setInvite] = useState<{ email: string; empresa_nome: string } | null>(null);
  const [loadingInvite, setLoadingInvite] = useState(true);
  const [invalidToken, setInvalidToken] = useState(false);

  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [confirmar, setConfirmar] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (!token) {
      setInvalidToken(true);
      setLoadingInvite(false);
      return;
    }
    axios
      .get(`/api-backend/auth/invite/${token}`)
      .then((res) => {
        setInvite(res.data);
        setEmail(res.data.email);
      })
      .catch(() => setInvalidToken(true))
      .finally(() => setLoadingInvite(false));
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (senha !== confirmar) {
      setError("As senhas não coincidem.");
      return;
    }
    if (senha.length < 6) {
      setError("A senha deve ter no mínimo 6 caracteres.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await axios.post("/api-backend/auth/register", { token, nome, email, senha });
      setSuccess(true);
      setTimeout(() => router.push("/login"), 2500);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Erro ao criar conta. Tente novamente.");
    } finally {
      setLoading(false);
    }
  };

  if (loadingInvite) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-mesh">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  if (invalidToken) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4 bg-mesh">
        <div className="glass-morphism p-8 rounded-2xl text-center max-w-md w-full">
          <h1 className="text-2xl font-bold text-accent mb-3">Convite inválido</h1>
          <p className="text-gray-400 mb-6">Este link de convite expirou ou já foi utilizado.</p>
          <button onClick={() => router.push("/login")} className="text-primary underline text-sm">
            Ir para o login
          </button>
        </div>
      </div>
    );
  }

  if (success) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4 bg-mesh">
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="glass-morphism p-8 rounded-2xl text-center max-w-md w-full"
        >
          <CheckCircle className="w-16 h-16 text-green-400 mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-white mb-2">Conta criada!</h1>
          <p className="text-gray-400">Redirecionando para o login...</p>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4 bg-mesh">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-md"
      >
        <div className="glass-morphism p-8 rounded-2xl shadow-neon-primary relative overflow-hidden">
          <div className="absolute -top-24 -right-24 w-48 h-48 bg-primary opacity-10 rounded-full blur-3xl animate-pulse" />

          <div className="mb-6 text-center">
            <h1 className="text-3xl font-bold text-gradient mb-1 tracking-tight">Antigravity IA</h1>
            <p className="text-gray-400 text-sm">
              Criar conta para{" "}
              <span className="text-primary font-semibold">{invite?.empresa_nome}</span>
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1">
              <label className="text-xs font-semibold text-gray-300 uppercase tracking-widest ml-1">
                Nome completo
              </label>
              <div className="relative group">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 transition-colors group-focus-within:text-primary" />
                <input
                  type="text"
                  value={nome}
                  onChange={(e) => setNome(e.target.value)}
                  placeholder="Seu nome"
                  className="w-full bg-white/5 border border-white/10 rounded-xl py-3 pl-11 pr-4 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all text-white placeholder:text-gray-600"
                  required
                />
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-gray-300 uppercase tracking-widest ml-1">
                E-mail
              </label>
              <div className="relative group">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
                <input
                  type="email"
                  value={email}
                  readOnly
                  className="w-full bg-white/5 border border-white/10 rounded-xl py-3 pl-11 pr-4 text-gray-400 cursor-not-allowed"
                />
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-gray-300 uppercase tracking-widest ml-1">
                Senha
              </label>
              <div className="relative group">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 transition-colors group-focus-within:text-primary" />
                <input
                  type="password"
                  value={senha}
                  onChange={(e) => setSenha(e.target.value)}
                  placeholder="Mínimo 6 caracteres"
                  className="w-full bg-white/5 border border-white/10 rounded-xl py-3 pl-11 pr-4 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all text-white placeholder:text-gray-600"
                  required
                />
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-gray-300 uppercase tracking-widest ml-1">
                Confirmar senha
              </label>
              <div className="relative group">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 transition-colors group-focus-within:text-primary" />
                <input
                  type="password"
                  value={confirmar}
                  onChange={(e) => setConfirmar(e.target.value)}
                  placeholder="Repita a senha"
                  className="w-full bg-white/5 border border-white/10 rounded-xl py-3 pl-11 pr-4 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all text-white placeholder:text-gray-600"
                  required
                />
              </div>
            </div>

            {error && (
              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-accent text-sm text-center font-medium bg-accent/10 py-2 rounded-lg"
              >
                {error}
              </motion.p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary hover:bg-primary/80 text-white font-bold py-3 px-6 rounded-xl flex items-center justify-center gap-2 transition-all transform hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed group mt-2"
            >
              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <>
                  Criar minha conta
                  <ArrowRight className="w-5 h-5 transition-transform group-hover:translate-x-1" />
                </>
              )}
            </button>
          </form>
        </div>
      </motion.div>
    </div>
  );
}

export default function RegisterPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-mesh">
          <Loader2 className="w-8 h-8 text-primary animate-spin" />
        </div>
      }
    >
      <RegisterForm />
    </Suspense>
  );
}
