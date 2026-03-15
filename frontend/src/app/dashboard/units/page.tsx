"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";
import { Building2, Plus, Pencil, Trash2, Save, X, Loader2, ArrowLeft, CheckCircle2, MapPin, Phone, Globe, Instagram, Link as LinkIcon } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

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

export default function UnitsPage() {
  const [units, setUnits] = useState<Unit[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingUnit, setEditingUnit] = useState<Unit | null>(null);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);

  const [formData, setFormData] = useState({
    nome: "",
    nome_abreviado: "",
    cidade: "",
    bairro: "",
    estado: "",
    endereco: "",
    numero: "",
    telefone_principal: "",
    whatsapp: "",
    site: "",
    instagram: "",
    link_matricula: "",
  });

  const getConfig = () => ({
    headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }
  });

  useEffect(() => {
    fetchUnits();
  }, []);

  const fetchUnits = async () => {
    try {
      const response = await axios.get("/api-backend/dashboard/unidades", getConfig());
      setUnits(response.data);
    } catch (error) {
      console.error("Erro ao carregar unidades:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenModal = (unit: Unit | null = null) => {
    if (unit) {
      setEditingUnit(unit);
      setFormData({
        nome: unit.nome || "",
        nome_abreviado: unit.nome_abreviado || "",
        cidade: unit.cidade || "",
        bairro: unit.bairro || "",
        estado: unit.estado || "",
        endereco: unit.endereco || "",
        numero: unit.numero || "",
        telefone_principal: unit.telefone_principal || "",
        whatsapp: unit.whatsapp || "",
        site: unit.site || "",
        instagram: unit.instagram || "",
        link_matricula: unit.link_matricula || "",
      });
    } else {
      setEditingUnit(null);
      setFormData({
        nome: "",
        nome_abreviado: "",
        cidade: "",
        bairro: "",
        estado: "",
        endereco: "",
        numero: "",
        telefone_principal: "",
        whatsapp: "",
        site: "",
        instagram: "",
        link_matricula: "",
      });
    }
    setIsModalOpen(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editingUnit) {
        await axios.put(`/api-backend/dashboard/unidades/${editingUnit.id}`, formData, getConfig());
      } else {
        await axios.post("/api-backend/dashboard/unidades", formData, getConfig());
      }
      setSuccess(true);
      setTimeout(() => {
        setSuccess(false);
        setIsModalOpen(false);
        fetchUnits();
      }, 1500);
    } catch (error) {
      console.error("Erro ao salvar unidade:", error);
      alert("Erro ao salvar alterações.");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Tem certeza que deseja desativar esta unidade?")) return;
    try {
      await axios.delete(`/api-backend/dashboard/unidades/${id}`, getConfig());
      fetchUnits();
    } catch (error) {
      console.error("Erro ao excluir:", error);
      alert("Erro ao excluir unidade.");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#050505] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#050505] text-white p-6 md:p-12">
      <div className="max-w-6xl mx-auto">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
          <div className="flex items-center gap-4">
            <a href="/dashboard" className="p-2 hover:bg-white/5 rounded-full transition-colors">
              <ArrowLeft className="w-5 h-5" />
            </a>
            <div>
              <h1 className="text-3xl font-bold flex items-center gap-3">
                <Building2 className="w-8 h-8 text-blue-500" />
                Gestão de Unidades
              </h1>
              <p className="text-gray-400 mt-1">Gerencie os endereços e informações de contato de suas unidades.</p>
            </div>
          </div>
          
          <button
            onClick={() => handleOpenModal()}
            className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-3 rounded-xl font-bold flex items-center gap-2 transition-all hover:scale-[1.02] active:scale-[0.98] shadow-lg shadow-blue-500/20"
          >
            <Plus className="w-5 h-5" />
            Nova Unidade
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {units.length === 0 ? (
            <div className="col-span-full text-center py-20 bg-white/5 border border-dashed border-white/10 rounded-2xl">
              <Building2 className="w-12 h-12 text-gray-600 mx-auto mb-4" />
              <p className="text-gray-400">Nenhuma unidade cadastrada.</p>
            </div>
          ) : (
            units.map((unit) => (
              <motion.div
                layout
                key={unit.id}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="bg-white/5 border border-white/10 rounded-2xl p-6 hover:bg-white/10 transition-all group"
              >
                <div className="flex justify-between items-start mb-4">
                  <div className="w-12 h-12 rounded-xl bg-blue-500/10 flex items-center justify-center text-blue-500">
                    <Building2 className="w-6 h-6" />
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleOpenModal(unit)}
                      className="p-2 hover:bg-white/10 rounded-lg text-gray-400 hover:text-white transition-colors"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(unit.id)}
                      className="p-2 hover:bg-red-500/10 rounded-lg text-gray-400 hover:text-red-500 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                <h3 className="text-xl font-bold mb-2">{unit.nome}</h3>
                <div className="space-y-2 text-sm text-gray-400">
                  {unit.cidade && (
                    <p className="flex items-center gap-2">
                      <MapPin className="w-4 h-4 text-blue-500/50" />
                      {unit.cidade}, {unit.estado}
                    </p>
                  )}
                  {unit.whatsapp && (
                    <p className="flex items-center gap-2">
                      <Phone className="w-4 h-4 text-blue-500/50" />
                      {unit.whatsapp}
                    </p>
                  )}
                  {unit.site && (
                    <p className="flex items-center gap-2">
                      <Globe className="w-4 h-4 text-blue-500/50" />
                      {unit.site}
                    </p>
                  )}
                </div>
              </motion.div>
            ))
          )}
        </div>
      </div>

      {/* Modal */}
      <AnimatePresence>
        {isModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 bg-black/80 backdrop-blur-md"
              onClick={() => setIsModalOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 30 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 30 }}
              className="bg-[#111] border border-white/10 rounded-3xl w-full max-w-2xl overflow-hidden relative shadow-2xl"
            >
              <form onSubmit={handleSave}>
                <div className="p-8 border-b border-white/10 flex items-center justify-between">
                  <h2 className="text-2xl font-bold flex items-center gap-3">
                    {editingUnit ? <Pencil className="w-6 h-6 text-blue-500" /> : <Plus className="w-6 h-6 text-blue-500" />}
                    {editingUnit ? "Editar Unidade" : "Nova Unidade"}
                  </h2>
                  <button type="button" onClick={() => setIsModalOpen(false)} className="p-2 hover:bg-white/10 rounded-xl transition-all">
                    <X className="w-6 h-6" />
                  </button>
                </div>

                <div className="p-8 space-y-6 max-h-[60vh] overflow-y-auto">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                      <label className="block text-sm font-medium text-gray-400 mb-2">Nome da Unidade *</label>
                      <input
                        type="text"
                        required
                        value={formData.nome}
                        onChange={(e) => setFormData({ ...formData, nome: e.target.value })}
                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                        placeholder="Ex: Unidade Centro"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-400 mb-2">Nome Abrev.</label>
                      <input
                        type="text"
                        value={formData.nome_abreviado}
                        onChange={(e) => setFormData({ ...formData, nome_abreviado: e.target.value })}
                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                        placeholder="Ex: Centro"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-gray-400 mb-2">Endereço</label>
                      <input
                        type="text"
                        value={formData.endereco}
                        onChange={(e) => setFormData({ ...formData, endereco: e.target.value })}
                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                        placeholder="Rua Exemplo"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-400 mb-2">Número</label>
                      <input
                        type="text"
                        value={formData.numero}
                        onChange={(e) => setFormData({ ...formData, numero: e.target.value })}
                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                        placeholder="123"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div>
                      <label className="block text-sm font-medium text-gray-400 mb-2">Bairro</label>
                      <input
                        type="text"
                        value={formData.bairro}
                        onChange={(e) => setFormData({ ...formData, bairro: e.target.value })}
                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-400 mb-2">Cidade</label>
                      <input
                        type="text"
                        value={formData.cidade}
                        onChange={(e) => setFormData({ ...formData, cidade: e.target.value })}
                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-400 mb-2">Estado</label>
                      <input
                        type="text"
                        value={formData.estado}
                        onChange={(e) => setFormData({ ...formData, estado: e.target.value })}
                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                        placeholder="SP"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                      <label className="block text-sm font-medium text-gray-400 mb-2">WhatsApp</label>
                      <input
                        type="text"
                        value={formData.whatsapp}
                        onChange={(e) => setFormData({ ...formData, whatsapp: e.target.value })}
                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                        placeholder="(11) 99999-9999"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-400 mb-2">Telefone</label>
                      <input
                        type="text"
                        value={formData.telefone_principal}
                        onChange={(e) => setFormData({ ...formData, telefone_principal: e.target.value })}
                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                      />
                    </div>
                  </div>

                  <div className="space-y-4">
                    <h4 className="text-xs font-black text-gray-500 uppercase tracking-widest pt-4">Links & Redes</h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="relative">
                        <Globe className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                        <input
                          type="text"
                          value={formData.site}
                          onChange={(e) => setFormData({ ...formData, site: e.target.value })}
                          className="w-full bg-black/40 border border-white/10 rounded-xl pl-12 pr-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                          placeholder="Site"
                        />
                      </div>
                      <div className="relative">
                        <Instagram className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                        <input
                          type="text"
                          value={formData.instagram}
                          onChange={(e) => setFormData({ ...formData, instagram: e.target.value })}
                          className="w-full bg-black/40 border border-white/10 rounded-xl pl-12 pr-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                          placeholder="Instagram"
                        />
                      </div>
                      <div className="md:col-span-2 relative">
                        <LinkIcon className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                        <input
                          type="text"
                          value={formData.link_matricula}
                          onChange={(e) => setFormData({ ...formData, link_matricula: e.target.value })}
                          className="w-full bg-black/40 border border-white/10 rounded-xl pl-12 pr-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                          placeholder="Link para Matrícula/Venda"
                        />
                      </div>
                    </div>
                  </div>
                </div>

                <div className="p-8 bg-white/[0.02] border-t border-white/10 flex justify-end gap-4">
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="px-8 py-3 rounded-xl font-bold text-gray-400 hover:bg-white/5 transition-all"
                  >
                    Cancelar
                  </button>
                  <button
                    type="submit"
                    disabled={saving}
                    className="bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 text-white px-10 py-3 rounded-xl font-bold flex items-center gap-2 transition-all shadow-lg shadow-blue-500/20"
                  >
                    {saving ? (
                      <Loader2 className="w-5 h-5 animate-spin" />
                    ) : success ? (
                      <CheckCircle2 className="w-5 h-5" />
                    ) : (
                      <Save className="w-5 h-5" />
                    )}
                    {saving ? "Salvando..." : success ? "Sucesso!" : "Salvar Unidade"}
                  </button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
