"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { 
  Building2, Plus, Pencil, Trash2, Save, X, Loader2, 
  ArrowLeft, CheckCircle2, MapPin, Phone, Globe, Instagram, 
  Link as LinkIcon, Brain, HelpCircle, Network, Settings, 
  Search, MessageSquare, ChevronRight, History as HistoryIcon
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

// --- Types ---
interface Unit {
  id: number;
  nome: string;
  nome_abreviado?: string;
  cidade?: string;
  bairro?: string;
  estado?: string;
  endereco?: string;
  numero?: string;
  telefone_principal?: string;
  whatsapp?: string;
  site?: string;
  instagram?: string;
  link_matricula?: string;
  slug: string;
}

interface Personality {
  nome_ia: string;
  personalidade: string;
  instrucoes_base: string;
  tom_voz: string;
  ativo: boolean;
}

interface FAQ {
  id: number;
  pergunta: string;
  resposta: string;
  unidade_id: number | null;
  todas_unidades: boolean;
  prioridade: number;
}

interface Integration {
  id: number;
  tipo: string;
  config: any;
  ativo: boolean;
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState("units");
  const [loading, setLoading] = useState(true);

  // --- Units State ---
  const [units, setUnits] = useState<Unit[]>([]);
  const [isUnitModalOpen, setIsUnitModalOpen] = useState(false);
  const [editingUnit, setEditingUnit] = useState<Unit | null>(null);
  const [unitFormData, setUnitFormData] = useState({
    nome: "", nome_abreviado: "", cidade: "", bairro: "", estado: "",
    endereco: "", numero: "", telefone_principal: "", whatsapp: "",
    site: "", instagram: "", link_matricula: "",
  });

  // --- Personality State ---
  const [personality, setPersonality] = useState<Personality>({
    nome_ia: "", personalidade: "", instrucoes_base: "", tom_voz: "Profissional", ativo: true
  });

  // --- FAQ State ---
  const [faqs, setFaqs] = useState<FAQ[]>([]);
  const [isFaqModalOpen, setIsFaqModalOpen] = useState(false);
  const [editingFaq, setEditingFaq] = useState<any>(null);
  const [faqFormData, setFaqFormData] = useState({
    pergunta: "", resposta: "", unidade_id: "", todas_unidades: true, prioridade: 0
  });

  // --- Integrations State ---
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [integrationConfigs, setIntegrationConfigs] = useState<any>({
    chatwoot: { url: "", token: "", account_id: "", inbox_id: "" },
    evo: { url: "", apikey: "", instance: "" },
    uazapi: { url: "", token: "", instance: "" }
  });

  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);

  const getConfig = () => ({
    headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }
  });

  useEffect(() => {
    fetchAllData();
  }, []);

  const fetchAllData = async () => {
    setLoading(true);
    try {
      const [unitsRes, personalityRes, faqRes, integrationsRes] = await Promise.all([
        axios.get("/api-backend/dashboard/unidades", getConfig()),
        axios.get("/api-backend/management/personality", getConfig()),
        axios.get("/api-backend/management/faq", getConfig()),
        axios.get("/api-backend/management/integrations", getConfig())
      ]);
      setUnits(unitsRes.data);
      setPersonality(personalityRes.data);
      setFaqs(faqRes.data);
      
      const ints = integrationsRes.data;
      setIntegrations(ints);
      const newConfigs = { ...integrationConfigs };
      ints.forEach((i: any) => {
        if (newConfigs[i.tipo]) newConfigs[i.tipo] = i.config;
      });
      setIntegrationConfigs(newConfigs);
    } catch (error) {
      console.error("Erro ao carregar dados:", error);
    } finally {
      setLoading(false);
    }
  };

  // --- Handlers: Units ---
  const handleOpenUnitModal = async (unit: Unit | null = null) => {
    if (unit) {
      setEditingUnit(unit);
      // Fetch full unit data to pre-fill all form fields
      try {
        const res = await axios.get(`/api-backend/dashboard/unidades/${unit.id}`, getConfig());
        const u = res.data;
        setUnitFormData({
          nome: u.nome || "", nome_abreviado: u.nome_abreviado || "",
          cidade: u.cidade || "", bairro: u.bairro || "", estado: u.estado || "",
          endereco: u.endereco || "", numero: u.numero || "",
          telefone_principal: u.telefone_principal || "", whatsapp: u.whatsapp || "",
          site: u.site || "", instagram: u.instagram || "", link_matricula: u.link_matricula || "",
        });
      } catch {
        // Fallback to what we already have from the list
        setUnitFormData({
          nome: unit.nome, nome_abreviado: unit.nome_abreviado || "",
          cidade: unit.cidade || "", bairro: unit.bairro || "", estado: unit.estado || "",
          endereco: unit.endereco || "", numero: unit.numero || "",
          telefone_principal: unit.telefone_principal || "", whatsapp: unit.whatsapp || "",
          site: unit.site || "", instagram: unit.instagram || "", link_matricula: unit.link_matricula || "",
        });
      }
    } else {
      setEditingUnit(null);
      setUnitFormData({
        nome: "", nome_abreviado: "", cidade: "", bairro: "", estado: "",
        endereco: "", numero: "", telefone_principal: "", whatsapp: "",
        site: "", instagram: "", link_matricula: "",
      });
    }
    setIsUnitModalOpen(true);
  };

  const handleSaveUnit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editingUnit) {
        await axios.put(`/api-backend/dashboard/unidades/${editingUnit.id}`, unitFormData, getConfig());
      } else {
        await axios.post("/api-backend/dashboard/unidades", unitFormData, getConfig());
      }
      setSuccess(true);
      setTimeout(() => { setSuccess(false); setIsUnitModalOpen(false); fetchAllData(); }, 1000);
    } catch (error) { console.error(error); alert("Erro ao salvar unidade"); } finally { setSaving(false); }
  };

  // --- Handlers: Personality ---
  const handleSavePersonality = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await axios.put("/api-backend/management/personality", personality, getConfig());
      setSuccess(true);
      setTimeout(() => setSuccess(false), 2000);
    } catch (error) { alert("Erro ao salvar personalidade"); } finally { setSaving(false); }
  };

  // --- Handlers: FAQ ---
  const handleSaveFaq = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = { ...faqFormData, unidade_id: faqFormData.unidade_id ? Number(faqFormData.unidade_id) : null };
      if (editingFaq) {
        await axios.put(`/api-backend/management/faq/${editingFaq.id}`, payload, getConfig());
      } else {
        await axios.post("/api-backend/management/faq", payload, getConfig());
      }
      setSuccess(true);
      setTimeout(() => { setSuccess(false); setIsFaqModalOpen(false); fetchAllData(); }, 1000);
    } catch (error) { alert("Erro ao salvar FAQ"); } finally { setSaving(false); }
  };

  // --- Handlers: Integrations ---
  const handleSaveIntegration = async (tipo: string) => {
    setSaving(true);
    try {
      await axios.put(`/api-backend/management/integrations/${tipo}`, { config: integrationConfigs[tipo], ativo: true }, getConfig());
      setSuccess(true);
      setTimeout(() => setSuccess(false), 2000);
      fetchAllData();
    } catch (error) { alert("Erro ao salvar integração"); } finally { setSaving(false); }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  const tabs = [
    { id: "units", label: "Unidades", icon: Building2 },
    { id: "personality", label: "Personalidade IA", icon: Brain },
    { id: "faq", label: "FAQ", icon: HelpCircle },
    { id: "integrations", label: "Integrações", icon: Network },
  ];

  return (
    <div className="min-h-screen bg-background text-white p-4 md:p-12">
      <div className="max-w-6xl mx-auto">
        <div className="mb-12 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <a href="/dashboard" className="p-2 hover:bg-white/5 rounded-full transition-colors">
              <ArrowLeft className="w-5 h-5" />
            </a>
            <div>
              <h1 className="text-3xl font-bold flex items-center gap-3">
                <Settings className="w-8 h-8 text-primary" />
                Central de Gestão
              </h1>
              <p className="text-gray-400 mt-1">Configure todos os aspectos da sua inteligência e operação.</p>
            </div>
          </div>
        </div>

        {/* Tabs Navigation */}
        <div className="flex flex-wrap gap-2 mb-8 bg-white/5 p-1.5 rounded-2xl w-fit">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-6 py-3 rounded-xl font-bold transition-all ${
                activeTab === tab.id 
                ? "bg-primary text-black shadow-lg shadow-primary/20" 
                : "text-gray-400 hover:text-white hover:bg-white/5"
              }`}
            >
              <tab.icon className="w-5 h-5" />
              {tab.label}
            </button>
          ))}
        </div>

        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="min-h-[60vh]"
        >
          {/* --- Tab: Units --- */}
          {activeTab === "units" && (
            <div className="space-y-6">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-xl font-bold">Unidades Cadastradas ({units.length})</h2>
                <button
                  onClick={() => handleOpenUnitModal()}
                  className="bg-primary hover:bg-primary/90 text-black px-6 py-2.5 rounded-xl font-bold flex items-center gap-2 transition-all"
                >
                  <Plus className="w-5 h-5" /> Nova Unidade
                </button>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {units.length === 0 ? (
                  <div className="col-span-full py-20 text-center bg-white/5 border border-dashed border-white/10 rounded-2xl">
                    <Building2 className="w-12 h-12 text-gray-700 mx-auto mb-4" />
                    <p className="text-gray-500">Nenhuma unidade encontrada. Comece cadastrando a primeira!</p>
                  </div>
                ) : (
                  units.map((u) => (
                    <div className="bg-slate-900/40 border border-white/10 p-6 rounded-2xl hover:border-primary/30 transition-all group">
                      <div className="flex justify-between mb-4">
                        <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                          <Building2 className="w-5 h-5" />
                        </div>
                        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button onClick={() => handleOpenUnitModal(u)} className="p-2 hover:bg-white/10 rounded-lg"><Pencil className="w-4 h-4" /></button>
                          <button onClick={() => axios.delete(`/api-backend/dashboard/unidades/${u.id}`, getConfig()).then(fetchAllData)} className="p-2 hover:bg-red-500/10 rounded-lg text-red-500"><Trash2 className="w-4 h-4" /></button>
                        </div>
                      </div>
                      <h3 className="font-bold text-lg mb-1">{u.nome}</h3>
                      <p className="text-sm text-gray-400 flex items-center gap-2"><MapPin className="w-3.5 h-3.5" /> {u.cidade || "Cidade não inf."}, {u.estado || "UF"}</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* --- Tab: Personality --- */}
          {activeTab === "personality" && (
            <form onSubmit={handleSavePersonality} className="bg-white/5 border border-white/10 p-8 rounded-3xl space-y-8 max-w-4xl">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div className="space-y-6">
                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-2">Nome da IA</label>
                    <input
                      type="text"
                      value={personality.nome_ia}
                      onChange={(e) => setPersonality({ ...personality, nome_ia: e.target.value })}
                      className="w-full bg-slate-950/40 border border-white/10 rounded-xl px-4 py-3 focus:ring-2 focus:ring-primary"
                      placeholder="Ex: Maya"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-2">Tom de Voz</label>
                    <select
                      value={personality.tom_voz}
                      onChange={(e) => setPersonality({ ...personality, tom_voz: e.target.value })}
                      className="w-full bg-slate-950/40 border border-white/10 rounded-xl px-4 py-3 focus:ring-2 focus:ring-primary"
                    >
                      <option value="Profissional">Profissional</option>
                      <option value="Amigável">Amigável</option>
                      <option value="Descontraído">Descontraído</option>
                      <option value="Entusiasta">Entusiasta</option>
                    </select>
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">Objetivo Geral</label>
                  <textarea
                    rows={5}
                    value={personality.personalidade}
                    onChange={(e) => setPersonality({ ...personality, personalidade: e.target.value })}
                    className="w-full bg-slate-950/40 border border-white/10 rounded-xl px-4 py-3 focus:ring-2 focus:ring-primary"
                    placeholder="Qual o principal objetivo da IA nas conversas?"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-2">Instruções de Comportamento</label>
                <textarea
                  rows={8}
                  value={personality.instrucoes_base}
                  onChange={(e) => setPersonality({ ...personality, instrucoes_base: e.target.value })}
                  className="w-full bg-slate-950/40 border border-white/10 rounded-xl px-4 py-3 focus:ring-2 focus:ring-primary"
                  placeholder="Instruções detalhadas de como a IA deve agir e o que evitar..."
                />
              </div>
              <div className="flex justify-end">
                <button type="submit" disabled={saving} className="bg-primary hover:bg-primary/90 text-black px-10 py-3 rounded-xl font-bold flex items-center gap-2">
                  {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : success ? <CheckCircle2 className="w-5 h-5" /> : <Save className="w-5 h-5" />}
                  Salvar Alterações
                </button>
              </div>
            </form>
          )}

          {/* --- Tab: FAQ --- */}
          {activeTab === "faq" && (
            <div className="space-y-6">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-xl font-bold">Perguntas Frequentes ({faqs.length})</h2>
                <button
                  onClick={() => { setEditingFaq(null); setFaqFormData({ pergunta: "", resposta: "", unidade_id: "", todas_unidades: true, prioridade: 0 }); setIsFaqModalOpen(true); }}
                  className="bg-primary hover:bg-primary/90 text-black px-6 py-2.5 rounded-xl font-bold flex items-center gap-2"
                >
                  <Plus className="w-5 h-5" /> Nova Pergunta
                </button>
              </div>
              <div className="space-y-4">
                {faqs.map((f) => (
                  <div key={f.id} className="bg-white/5 border border-white/10 p-6 rounded-2xl flex justify-between items-center group">
                    <div className="flex-1 pr-8">
                      <h4 className="font-bold mb-1">{f.pergunta}</h4>
                      <p className="text-sm text-gray-400 line-clamp-1">{f.resposta}</p>
                      <div className="mt-2 flex gap-2">
                        <span className="text-[10px] uppercase font-bold px-2 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
                          {f.todas_unidades ? "Global" : "Unidade Específica"}
                        </span>
                      </div>
                    </div>
                    <div className="flex gap-2">
                       <button onClick={() => { setEditingFaq(f); setFaqFormData({ pergunta: f.pergunta, resposta: f.resposta, unidade_id: f.unidade_id?.toString() || "", todas_unidades: f.todas_unidades, prioridade: f.prioridade }); setIsFaqModalOpen(true); }} className="p-2 hover:bg-white/10 rounded-lg text-gray-400"><Pencil className="w-4 h-4" /></button>
                       <button onClick={() => axios.delete(`/api-backend/management/faq/${f.id}`, getConfig()).then(fetchAllData)} className="p-2 hover:bg-red-500/10 rounded-lg text-red-500"><Trash2 className="w-4 h-4" /></button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* --- Tab: Integrations --- */}
          {activeTab === "integrations" && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
              {/* Chatwoot */}
              <div className="bg-white/5 border border-white/10 p-8 rounded-3xl space-y-6">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-12 h-12 rounded-2xl bg-orange-500/10 flex items-center justify-center text-orange-500">
                    <MessageSquare className="w-6 h-6" />
                  </div>
                  <h3 className="text-xl font-bold">Chatwoot</h3>
                </div>
                <div className="space-y-4">
                  <input placeholder="URL" value={integrationConfigs.chatwoot.url} onChange={e => setIntegrationConfigs({ ...integrationConfigs, chatwoot: { ...integrationConfigs.chatwoot, url: e.target.value }})} className="w-full bg-slate-950/40 border border-white/10 rounded-xl px-4 py-3" />
                  <input placeholder="API Token" type="password" value={integrationConfigs.chatwoot.token} onChange={e => setIntegrationConfigs({ ...integrationConfigs, chatwoot: { ...integrationConfigs.chatwoot, token: e.target.value }})} className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3" />
                  <input placeholder="Account ID" value={integrationConfigs.chatwoot.account_id} onChange={e => setIntegrationConfigs({ ...integrationConfigs, chatwoot: { ...integrationConfigs.chatwoot, account_id: e.target.value }})} className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3" />
                </div>
                <button onClick={() => handleSaveIntegration('chatwoot')} className="w-full bg-white/5 hover:bg-white/10 py-3 rounded-xl font-bold">Salvar Chatwoot</button>
              </div>

              {/* EVO */}
              <div className="bg-white/5 border border-white/10 p-8 rounded-3xl space-y-6">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-12 h-12 rounded-2xl bg-green-500/10 flex items-center justify-center text-green-500">
                    <HistoryIcon className="w-6 h-6" />
                  </div>
                  <h3 className="text-xl font-bold">Evolution API</h3>
                </div>
                <div className="space-y-4">
                  <input placeholder="URL" value={integrationConfigs.evo.url} onChange={e => setIntegrationConfigs({ ...integrationConfigs, evo: { ...integrationConfigs.evo, url: e.target.value }})} className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3" />
                  <input placeholder="API Key" type="password" value={integrationConfigs.evo.apikey} onChange={e => setIntegrationConfigs({ ...integrationConfigs, evo: { ...integrationConfigs.evo, apikey: e.target.value }})} className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3" />
                  <input placeholder="Instance" value={integrationConfigs.evo.instance} onChange={e => setIntegrationConfigs({ ...integrationConfigs, evo: { ...integrationConfigs.evo, instance: e.target.value }})} className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3" />
                </div>
                <button onClick={() => handleSaveIntegration('evo')} className="w-full bg-white/5 hover:bg-white/10 py-3 rounded-xl font-bold">Salvar Evolution</button>
              </div>

              {/* UazAPI */}
              <div className="bg-white/5 border border-white/10 p-8 rounded-3xl space-y-6">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-12 h-12 rounded-2xl bg-blue-500/10 flex items-center justify-center text-blue-500">
                    <Network className="w-6 h-6" />
                  </div>
                  <h3 className="text-xl font-bold">UazAPI</h3>
                </div>
                <div className="space-y-4">
                  <input placeholder="URL" value={integrationConfigs.uazapi.url} onChange={e => setIntegrationConfigs({ ...integrationConfigs, uazapi: { ...integrationConfigs.uazapi, url: e.target.value }})} className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3" />
                  <input placeholder="Token" type="password" value={integrationConfigs.uazapi.token} onChange={e => setIntegrationConfigs({ ...integrationConfigs, uazapi: { ...integrationConfigs.uazapi, token: e.target.value }})} className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3" />
                  <input placeholder="Instance" value={integrationConfigs.uazapi.instance} onChange={e => setIntegrationConfigs({ ...integrationConfigs, uazapi: { ...integrationConfigs.uazapi, instance: e.target.value }})} className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3" />
                </div>
                <button onClick={() => handleSaveIntegration('uazapi')} className="w-full bg-white/5 hover:bg-white/10 py-3 rounded-xl font-bold">Salvar UazAPI</button>
              </div>
            </div>
          )}
        </motion.div>
      </div>

      {/* --- Modals: Copied logic from previous pages for brevity & stability --- */}
      <AnimatePresence>
        {isUnitModalOpen && (
           <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
             <div className="absolute inset-0 bg-background/80 backdrop-blur-md" onClick={() => setIsUnitModalOpen(false)} />
             <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="bg-slate-950 border border-white/10 rounded-3xl w-full max-w-2xl relative p-8 max-h-[90vh] overflow-y-auto">
               <form onSubmit={handleSaveUnit}>
                 <h2 className="text-2xl font-bold mb-6">{editingUnit ? "Editar Unidade" : "Nova Unidade"}</h2>
                 <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                    <div className="col-span-2">
                      <label className="block text-xs text-gray-400 mb-1">Nome *</label>
                      <input required placeholder="Ex: Red Fitness – Centro" value={unitFormData.nome} onChange={e => setUnitFormData({...unitFormData, nome: e.target.value})} className="w-full bg-slate-950/40 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">Nome Abreviado</label>
                      <input placeholder="Ex: RF Centro" value={unitFormData.nome_abreviado} onChange={e => setUnitFormData({...unitFormData, nome_abreviado: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">Cidade</label>
                      <input placeholder="Ex: São Paulo" value={unitFormData.cidade} onChange={e => setUnitFormData({...unitFormData, cidade: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">Bairro</label>
                      <input placeholder="Ex: Vila Mariana" value={unitFormData.bairro} onChange={e => setUnitFormData({...unitFormData, bairro: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">Estado (UF)</label>
                      <input placeholder="SP" maxLength={2} value={unitFormData.estado} onChange={e => setUnitFormData({...unitFormData, estado: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">Endereço</label>
                      <input placeholder="Rua, Av..." value={unitFormData.endereco} onChange={e => setUnitFormData({...unitFormData, endereco: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">Número</label>
                      <input placeholder="123" value={unitFormData.numero} onChange={e => setUnitFormData({...unitFormData, numero: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">Telefone Principal</label>
                      <input placeholder="(11) 99999-0000" value={unitFormData.telefone_principal} onChange={e => setUnitFormData({...unitFormData, telefone_principal: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">WhatsApp</label>
                      <input placeholder="(11) 99999-0000" value={unitFormData.whatsapp} onChange={e => setUnitFormData({...unitFormData, whatsapp: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">Site</label>
                      <input placeholder="https://..." value={unitFormData.site} onChange={e => setUnitFormData({...unitFormData, site: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">Instagram</label>
                      <input placeholder="@usuario" value={unitFormData.instagram} onChange={e => setUnitFormData({...unitFormData, instagram: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                    <div className="col-span-2">
                      <label className="block text-xs text-gray-400 mb-1">Link de Matrícula</label>
                      <input placeholder="https://..." value={unitFormData.link_matricula} onChange={e => setUnitFormData({...unitFormData, link_matricula: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    </div>
                 </div>
                 <div className="flex justify-end gap-4">
                    <button type="button" onClick={() => setIsUnitModalOpen(false)} className="px-6 py-2 text-gray-400">Cancelar</button>
                    <button type="submit" disabled={saving} className="bg-blue-600 hover:bg-blue-500 px-8 py-2 rounded-xl font-bold flex items-center gap-2">
                      {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                      Salvar
                    </button>
                 </div>
               </form>
             </motion.div>
           </div>
        )}

        {isFaqModalOpen && (
           <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
             <div className="absolute inset-0 bg-background/80 backdrop-blur-md" onClick={() => setIsFaqModalOpen(false)} />
             <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="bg-slate-950 border border-white/10 rounded-3xl w-full max-w-2xl relative p-8">
               <form onSubmit={handleSaveFaq}>
                 <h2 className="text-2xl font-bold mb-8">{editingFaq ? "Editar Pergunta" : "Nova Pergunta"}</h2>
                 <div className="space-y-6 mb-8">
                    <input required placeholder="Pergunta *" value={faqFormData.pergunta} onChange={e => setFaqFormData({...faqFormData, pergunta: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    <textarea required placeholder="Resposta *" rows={4} value={faqFormData.resposta} onChange={e => setFaqFormData({...faqFormData, resposta: e.target.value})} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3" />
                    <div className="flex items-center gap-4">
                       <label className="flex items-center gap-2 cursor-pointer">
                          <input type="checkbox" checked={faqFormData.todas_unidades} onChange={e => setFaqFormData({...faqFormData, todas_unidades: e.target.checked})} />
                          <span className="text-sm font-bold">Disponível em todas as unidades</span>
                       </label>
                    </div>
                 </div>
                 <div className="flex justify-end gap-4">
                    <button type="button" onClick={() => setIsFaqModalOpen(false)} className="px-6 py-2 text-gray-400">Cancelar</button>
                    <button type="submit" className="bg-blue-600 px-8 py-2 rounded-xl font-bold">Salvar</button>
                 </div>
               </form>
             </motion.div>
           </div>
        )}
      </AnimatePresence>
    </div>
  );
}
