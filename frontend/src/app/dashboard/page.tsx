"use client";

import { useEffect, useState } from "react";
import axios from "axios";
import { 
  TrendingUp, 
  Users, 
  MessageSquare, 
  Clock, 
  Target, 
  ArrowUpRight,
  ChevronRight,
  LayoutDashboard,
  Settings,
  LogOut,
  Bell
} from "lucide-react";
import { motion } from "framer-motion";

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<any>(null);
  const [conversations, setConversations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [initialLoading, setInitialLoading] = useState(true);
  const [user, setUser] = useState<any>(null);
  const [unidades, setUnidades] = useState<any[]>([]);
  const [selectedUnidadeId, setSelectedUnidadeId] = useState<number | null>(null);

  useEffect(() => {
    const fetchUnidadesAndUser = async () => {
      const token = localStorage.getItem("token");
      if (!token) {
        window.location.href = "/login";
        return;
      }

      try {
        const config = { headers: { Authorization: `Bearer ${token}` } };

        const [userRes, unitsRes] = await Promise.all([
          axios.get(`/api-backend/auth/me`, config),
          axios.get(`/api-backend/dashboard/unidades`, config)
        ]);

        setUser(userRes.data);
        setUnidades(unitsRes.data);
        
        if (unitsRes.data.length > 0) {
          setSelectedUnidadeId(unitsRes.data[0].id);
        }
      } catch (err) {
        console.error("Erro ao carregar dados iniciais:", err);
      } finally {
        setInitialLoading(false);
      }
    };

    fetchUnidadesAndUser();
  }, []);

  useEffect(() => {
    if (!selectedUnidadeId) return;

    const fetchDashboardData = async () => {
      setLoading(true);
      const token = localStorage.getItem("token");
      try {
        const config = { headers: { Authorization: `Bearer ${token}` } };

        const [metricsRes, convLogRes] = await Promise.all([
          axios.get(`/api-backend/dashboard/metrics?unidade_id=${selectedUnidadeId}`, config),
          axios.get(`/api-backend/dashboard/conversations?unidade_id=${selectedUnidadeId}&limit=5`, config)
        ]);

        setMetrics(metricsRes.data.metrics);
        setConversations(convLogRes.data);
      } catch (err) {
        console.error("Erro ao carregar métricas da unidade:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, [selectedUnidadeId]);

  if (initialLoading) {
    return (
      <div className="min-h-screen bg-mesh flex items-center justify-center">
        <div className="relative">
          <div className="w-16 h-16 border-4 border-primary/20 border-t-primary rounded-full animate-spin"></div>
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-2 h-2 bg-primary rounded-full animate-ping"></div>
          </div>
        </div>
      </div>
    );
  }

  if (!initialLoading && unidades.length === 0) {
    return (
      <div className="min-h-screen bg-mesh flex items-center justify-center p-4">
        <div className="glass-morphism p-10 rounded-2xl text-center max-w-md w-full">
          <div className="w-16 h-16 bg-primary/10 rounded-2xl flex items-center justify-center mx-auto mb-6">
            <LayoutDashboard className="w-8 h-8 text-primary" />
          </div>
          <h2 className="text-2xl font-bold text-white mb-3">Nenhuma unidade cadastrada</h2>
          <p className="text-gray-400 mb-8 text-sm leading-relaxed">
            Para visualizar o dashboard, você precisa ter pelo menos uma unidade ativa.
            {user?.perfil === "admin_master" && " Acesse o painel de gestão para criar empresas e enviar convites."}
          </p>
          {user?.perfil === "admin_master" ? (
            <a
              href="/admin"
              className="inline-flex items-center gap-2 bg-primary hover:bg-primary/80 text-white font-bold py-3 px-6 rounded-xl transition-all"
            >
              <Settings className="w-5 h-5" />
              Painel de Gestão
            </a>
          ) : (
            <p className="text-gray-500 text-xs">Aguarde o administrador cadastrar uma unidade.</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-mesh text-white flex">
      {/* Sidebar - Sleek and Glassy */}
      <aside className="w-64 border-r border-white/5 bg-black/20 backdrop-blur-xl hidden lg:flex flex-col p-6">
        <div className="mb-10 flex items-center gap-3">
          <div className="w-10 h-10 bg-primary rounded-xl flex items-center justify-center shadow-neon-primary">
            <LayoutDashboard className="w-6 h-6 text-white" />
          </div>
          <span className="font-bold text-xl tracking-tight">Antigravity IA</span>
        </div>

        <nav className="flex-1 space-y-2">
          <a href="#" className="flex items-center gap-3 px-4 py-3 rounded-xl bg-primary/10 text-primary border border-primary/20 transition-all">
            <LayoutDashboard className="w-5 h-5" />
            <span className="font-medium">Dashboard</span>
          </a>
          <a href="#" className="flex items-center gap-3 px-4 py-3 rounded-xl text-gray-400 hover:bg-white/5 transition-all">
            <Users className="w-5 h-5" />
            <span className="font-medium">Leads Qualificados</span>
          </a>
          <a href="#" className="flex items-center gap-3 px-4 py-3 rounded-xl text-gray-400 hover:bg-white/5 transition-all">
            <MessageSquare className="w-5 h-5" />
            <span className="font-medium">Conversas</span>
          </a>
          {user?.perfil === "admin_master" && (
            <a href="/admin" className="flex items-center gap-3 px-4 py-3 rounded-xl text-gray-400 hover:bg-white/5 transition-all">
              <Settings className="w-5 h-5" />
              <span className="font-medium">Painel de Gestão</span>
            </a>
          )}
        </nav>

        <div className="pt-6 border-t border-white/5">
          <button 
            onClick={() => { localStorage.removeItem("token"); window.location.href = "/login"; }}
            className="flex items-center gap-3 px-4 py-3 rounded-xl text-accent hover:bg-accent/10 transition-all w-full"
          >
            <LogOut className="w-5 h-5" />
            <span className="font-medium">Sair</span>
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 p-8 lg:p-12 overflow-y-auto">
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
          <div>
            <h2 className="text-3xl font-bold mb-2">Bem-vindo, {user?.nome?.split(' ')[0]} 👋</h2>
            <p className="text-gray-400">Aqui está o que aconteceu no seu funil hoje.</p>
          </div>
          <div className="flex items-center gap-4">
            {/* Unit Selector */}
            {unidades.length > 1 && (
              <div className="relative group mr-4">
                <select 
                  value={selectedUnidadeId || ""} 
                  onChange={(e) => setSelectedUnidadeId(Number(e.target.value))}
                  className="appearance-none glass pl-4 pr-10 py-2.5 rounded-xl text-sm font-bold focus:outline-none focus:ring-2 focus:ring-primary/50 cursor-pointer bg-transparent hover:bg-white/5 transition-all"
                >
                  {unidades.map((u) => (
                    <option key={u.id} value={u.id} className="bg-[#020617] text-white">
                      {u.nome}
                    </option>
                  ))}
                </select>
                <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-gray-400 group-hover:text-primary transition-colors">
                  <ChevronRight className="w-4 h-4 rotate-90" />
                </div>
              </div>
            )}
            
            <button className="glass p-3 rounded-xl relative hover:bg-white/10 transition-all">
              <Bell className="w-6 h-6 text-gray-400" />
              <span className="absolute top-3 right-3 w-2 h-2 bg-accent rounded-full border-2 border-background"></span>
            </button>
            <div className="flex items-center gap-3 pl-4 border-l border-white/10">
              <div className="text-right hidden sm:block">
                <p className="text-sm font-bold">{user?.nome}</p>
                <p className="text-xs text-primary bg-primary/10 px-2 py-0.5 rounded-full inline-block mt-1">{user?.perfil === 'admin_master' ? 'Gestor Master' : user?.perfil}</p>
              </div>
              <div className="w-12 h-12 bg-gradient-to-tr from-primary to-secondary rounded-xl flex items-center justify-center font-bold text-white shadow-lg">
                {user?.nome?.charAt(0)}
              </div>
            </div>
          </div>
        </header>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
          <StatCard 
            title="Total de Conversas" 
            value={metrics?.total_conversas || 0} 
            icon={<MessageSquare className="w-6 h-6" />}
            trend="+12%"
            color="primary"
          />
          <StatCard 
            title="Leads Qualificados" 
            value={metrics?.leads_qualificados || 0} 
            icon={<Target className="w-6 h-6" />}
            trend="+5%"
            color="secondary"
          />
          <StatCard 
            title="Tempo Médio Resposta" 
            value={`${metrics?.tempo_medio_resposta || 0}s`} 
            icon={<Clock className="w-6 h-6" />}
            trend="-20%"
            color="accent"
          />
          <StatCard 
            title="Taxa de Conversão" 
            value={`${metrics?.taxa_conversao || 0}%`} 
            icon={<TrendingUp className="w-6 h-6" />}
            trend="+2.1%"
            color="primary"
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Funnel Neural Preview */}
          <div className="lg:col-span-2 glass-morphism p-8 rounded-2xl relative overflow-hidden">
             <div className="flex items-center justify-between mb-8">
                <h3 className="text-xl font-bold flex items-center gap-2">
                   <Target className="w-5 h-5 text-primary" />
                   Funil Neural de Vendas
                </h3>
                <span className="text-xs text-gray-500 uppercase tracking-widest font-bold">Tempo Real</span>
             </div>
             
             <div className="space-y-6">
                <FunnelStep label="Contatos Iniciais" count={metrics?.total_conversas || 0} percentage={100} color="primary" />
                <FunnelStep label="Interesse Detectado" count={metrics?.leads_qualificados || 0} percentage={Math.min(100, ((metrics?.leads_qualificados || 0) / (metrics?.total_conversas || 1)) * 100)} color="secondary" />
                <FunnelStep label="Link de Venda Enviado" count={metrics?.total_links_enviados || 0} percentage={Math.min(100, ((metrics?.total_links_enviados || 0) / (metrics?.total_conversas || 1)) * 100)} color="primary" />
                <FunnelStep label="Matrículas Finalizadas" count={metrics?.total_matriculas || 0} percentage={Math.min(100, ((metrics?.total_matriculas || 0) / (metrics?.total_conversas || 1)) * 100)} color="accent" />
             </div>
          </div>

          {/* Recent Conversations */}
          <div className="glass-morphism p-8 rounded-2xl">
            <h3 className="text-xl font-bold mb-6 flex items-center gap-2">
              <Users className="w-5 h-5 text-secondary" />
              Oportunidades
            </h3>
            <div className="space-y-4">
              {conversations.map((conv: any) => (
                <div key={conv.conversation_id} className="group flex items-center justify-between p-4 rounded-xl hover:bg-white/5 transition-all border border-transparent hover:border-white/10">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 bg-white/10 rounded-lg flex items-center justify-center font-bold text-gray-300 group-hover:text-primary transition-colors">
                      {conv.contato_nome?.charAt(0) || "U"}
                    </div>
                    <div>
                      <p className="font-bold text-sm">{conv.contato_nome || "Anônimo"}</p>
                      <p className="text-xs text-gray-500">{conv.contato_fone}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="flex items-center gap-1 text-primary mb-1">
                      <Target className="w-3 h-3" />
                      <span className="text-xs font-bold">{conv.score_lead}/5</span>
                    </div>
                    {conv.intencao_de_compra && (
                      <span className="text-[10px] bg-accent/20 text-accent px-2 py-0.5 rounded-full font-bold animate-pulse">QUENTE</span>
                    )}
                  </div>
                </div>
              ))}
              <button className="w-full mt-4 py-3 rounded-xl border border-white/5 hover:bg-white/5 text-gray-500 text-sm font-bold flex items-center justify-center gap-2 transition-all">
                Ver todos os leads
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function StatCard({ title, value, icon, trend, color }: any) {
  const colorMap: any = {
    primary: "text-primary bg-primary/10 border-primary/20",
    secondary: "text-secondary bg-secondary/10 border-secondary/20",
    accent: "text-accent bg-accent/10 border-accent/20",
  };

  return (
    <motion.div 
      whileHover={{ y: -5 }}
      className="glass p-6 rounded-2xl border border-white/5"
    >
      <div className="flex items-center justify-between mb-4">
        <div className={`p-3 rounded-xl ${colorMap[color]}`}>
          {icon}
        </div>
        <div className="flex items-center gap-1 text-xs font-bold text-emerald-400 bg-emerald-400/10 px-2 py-1 rounded-full">
          <ArrowUpRight className="w-3 h-3" />
          {trend}
        </div>
      </div>
      <h3 className="text-gray-400 text-sm font-medium mb-1">{title}</h3>
      <p className="text-3xl font-bold tracking-tight">{value}</p>
    </motion.div>
  );
}

function FunnelStep({ label, count, percentage, color }: any) {
  const colorMap: any = {
    primary: "bg-primary shadow-[0_0_10px_rgba(6,182,212,0.5)]",
    secondary: "bg-secondary shadow-[0_0_10px_rgba(139,92,246,0.5)]",
    accent: "bg-accent shadow-[0_0_10px_rgba(244,63,94,0.5)]",
  };

  return (
    <div className="relative">
      <div className="flex justify-between items-center mb-2">
        <span className="text-sm font-bold text-gray-300">{label}</span>
        <span className="text-xs font-bold text-gray-500">{count} leads ({Math.round(percentage)}%)</span>
      </div>
      <div className="h-4 bg-white/5 rounded-full overflow-hidden border border-white/10">
        <motion.div 
          initial={{ width: 0 }}
          animate={{ width: `${percentage}%` }}
          transition={{ duration: 1, delay: 0.2 }}
          className={`h-full rounded-full ${colorMap[color]}`}
        />
      </div>
    </div>
  );
}
