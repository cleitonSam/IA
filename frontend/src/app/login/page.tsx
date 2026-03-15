"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Lock, Mail, ArrowRight, Loader2 } from "lucide-react";
import axios from "axios";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      // Usando o backend API que criamos
      const formData = new FormData();
      formData.append("username", email);
      formData.append("password", password);

      const response = await axios.post(`/api-backend/auth/login`, formData);
      const { access_token } = response.data;

      localStorage.setItem("token", access_token);

      // Redireciona admin_master direto para o painel de gestão
      const meRes = await axios.get("/api-backend/auth/me", {
        headers: { Authorization: `Bearer ${access_token}` },
      });
      if (meRes.data.perfil === "admin_master" || meRes.data.email === "ti@fluxodigitaltech.com.br") {
        router.push("/admin");
      } else {
        router.push("/dashboard");
      }
    } catch (err: any) {
      console.error(err);
      setError("E-mail ou senha incorretos. Tente novamente.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4 bg-mesh">
      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-md"
      >
        <div className="glass-morphism p-8 rounded-2xl shadow-neon-primary relative overflow-hidden">
          {/* Decorative background element */}
          <div className="absolute -top-24 -right-24 w-48 h-48 bg-primary opacity-10 rounded-full blur-3xl animate-pulse"></div>
          
          <div className="mb-8 text-center">
            <h1 className="text-4xl font-bold text-gradient mb-2 tracking-tight">Fluxo Digital & Tech</h1>
            <p className="text-gray-400 text-sm">Inteligência Tecnológica & Gestão Digital</p>
          </div>

          <form onSubmit={handleLogin} className="space-y-6">
            <div className="space-y-2">
              <label className="text-xs font-semibold text-gray-300 uppercase tracking-widest ml-1">E-mail</label>
              <div className="relative group">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 transition-colors group-focus-within:text-primary" />
                <input 
                  type="email" 
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="seu@parceiro.com"
                  className="w-full bg-white/5 border border-white/10 rounded-xl py-3 pl-11 pr-4 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all text-white placeholder:text-gray-600"
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-semibold text-gray-300 uppercase tracking-widest ml-1">Senha</label>
              <div className="relative group">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 transition-colors group-focus-within:text-primary" />
                <input 
                  type="password" 
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
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
              className="w-full bg-primary hover:bg-primary/80 text-white font-bold py-3 px-6 rounded-xl flex items-center justify-center gap-2 transition-all transform hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed group"
            >
              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <>
                  Entrar no Centro de Comando
                  <ArrowRight className="w-5 h-5 transition-transform group-hover:translate-x-1" />
                </>
              )}
            </button>
          </form>

          <div className="mt-8 pt-6 border-t border-white/5 text-center px-4">
            <p className="text-gray-500 text-xs leading-relaxed">
              Bem-vindo ao futuro da gestão. Seu sucesso começa aqui.
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
