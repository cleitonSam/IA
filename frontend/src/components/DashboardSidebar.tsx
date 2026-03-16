"use client";

import { useState, useEffect } from "react";
import {
  LayoutDashboard, Building2, Brain, HelpCircle, Network,
  Settings, LogOut, Zap, BarChart3, MessageSquare, Menu, X, Send
} from "lucide-react";

interface SidebarProps {
  activePage?: string;
}

const navItemsRaw = [
  { label: "Visão Geral", icon: LayoutDashboard, href: "/dashboard", id: "dashboard" },
  { label: "Insights IA", icon: BarChart3, href: "/dashboard/insights", id: "insights" },
  { label: "Conversas", icon: MessageSquare, href: "/dashboard/conversas", id: "conversas" },
  { label: "Follow-ups", icon: Send, href: "/dashboard/followups", id: "followups" },
  { label: "Unidades", icon: Building2, href: "/dashboard/units", id: "units" },
  { label: "Personalidade IA", icon: Brain, href: "/dashboard/personality", id: "personality" },
  { label: "FAQ Neural", icon: HelpCircle, href: "/dashboard/faq", id: "faq" },
  { label: "Integrações", icon: Network, href: "/dashboard/integrations", id: "integrations" },
];

const navItems = navItemsRaw.filter((item, index, all) => (
  all.findIndex((candidate) => candidate.id === item.id && candidate.href === item.href) === index
));

export default function DashboardSidebar({ activePage = "dashboard" }: SidebarProps) {
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;
    fetch("/api-backend/auth/me", { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(setUser)
      .catch(() => {});
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("token");
    window.location.href = "/login";
  };

  const SidebarContent = () => (
    <div className="flex flex-col h-full">
      {/* Logo */}
      <div className="px-6 py-8 border-b border-white/5">
        <div className="flex items-center gap-3 group cursor-pointer" onClick={() => window.location.href = "/dashboard"}>
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#00d2ff] to-[#0066ff] flex items-center justify-center shadow-lg shadow-[#00d2ff]/20 group-hover:scale-110 transition-transform">
            <Zap className="w-5 h-5 text-black font-black" />
          </div>
          <div>
            <p className="font-black text-lg leading-tight tracking-tighter text-white">
              Fluxo <span className="font-light text-[#00d2ff]/80">Digital & Tech</span>
            </p>
            <p className="text-[10px] text-gray-500 uppercase tracking-[0.2em] font-bold">Elite Platform</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <p className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-gray-600">Principal</p>
        {navItems.map((item) => {
          const isActive = activePage === item.id;
          return (
            <a key={item.href} href={item.href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all group ${isActive
                ? "bg-[#00d2ff]/10 text-[#00d2ff] border border-[#00d2ff]/20"
                : "text-gray-400 hover:text-white hover:bg-white/5"
              }`}>
              <item.icon className={`w-4 h-4 flex-shrink-0 ${isActive ? "text-[#00d2ff]" : "group-hover:text-white"}`} />
              {item.label}
              {isActive && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-[#00d2ff] shadow-[0_0_8px_rgba(0,210,255,0.6)]" />}
            </a>
          );
        })}

        {user?.perfil === "admin_master" && (
          <>
            <p className="px-3 py-2 pt-4 text-[10px] font-bold uppercase tracking-widest text-gray-600">Admin</p>
            <a href="/admin" className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-gray-400 hover:text-white hover:bg-white/5 transition-all group">
              <Settings className="w-4 h-4 flex-shrink-0 group-hover:text-white" />
              Painel Master
            </a>
          </>
        )}
      </nav>

      {/* User Footer */}
      <div className="px-3 py-4 border-t border-white/5">
        {user && (
          <div className="flex items-center gap-3 px-3 py-2.5 rounded-xl mb-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#00d2ff] to-[#0066ff] flex items-center justify-center text-xs font-bold flex-shrink-0 text-black">
              {user?.nome?.charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold truncate text-white">{user?.nome}</p>
              <p className="text-xs text-gray-500 truncate">{user?.email}</p>
            </div>
          </div>
        )}
        <button onClick={handleLogout} className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-gray-400 hover:text-red-400 hover:bg-red-500/10 transition-all">
          <LogOut className="w-4 h-4" />
          Sair
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile toggle */}
      <button
        onClick={() => setOpen(true)}
        className="lg:hidden fixed top-4 left-4 z-50 p-2.5 bg-slate-900 border border-white/10 rounded-xl text-white"
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Mobile overlay */}
      {open && (
        <div className="lg:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm" onClick={() => setOpen(false)} />
      )}

      {/* Mobile drawer */}
      <aside className={`lg:hidden fixed inset-y-0 left-0 z-50 w-64 bg-slate-950 border-r border-white/5 transform transition-transform duration-300 ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <button onClick={() => setOpen(false)} className="absolute top-4 right-4 p-2 hover:bg-white/5 rounded-lg text-gray-400">
          <X className="w-5 h-5" />
        </button>
        <SidebarContent />
      </aside>

      {/* Desktop sidebar — always visible */}
      <aside className="hidden lg:flex flex-col w-64 flex-shrink-0 bg-slate-950 border-r border-white/5 min-h-screen sticky top-0">
        <SidebarContent />
      </aside>
    </>
  );
}
