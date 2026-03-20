"use client";

import React, { useState, useCallback, useEffect, useRef } from "react";
import axios from "axios";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  Connection,
  Edge,
  Node,
  MarkerType,
  BackgroundVariant,
  Panel,
  ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion, AnimatePresence } from "framer-motion";
import {
  Save, Loader2, CheckCircle2, Trash2, GitBranch, AlertCircle, X
} from "lucide-react";
import DashboardSidebar from "@/components/DashboardSidebar";
import { nodeTypes } from "./nodes";
import { NODE_CONFIG, CATEGORY_LABELS, NodeTypeName } from "./nodes/nodeStyles";

// ─────────────────────────────────────────────────────────────
// Tipagem
// ─────────────────────────────────────────────────────────────
type FlowData = {
  ativo: boolean;
  nodes: Node[];
  edges: Edge[];
};

// ─────────────────────────────────────────────────────────────
// Nó inicial padrão (só Start)
// ─────────────────────────────────────────────────────────────
const DEFAULT_NODES: Node[] = [
  {
    id: "start-1",
    type: "start",
    position: { x: 100, y: 200 },
    data: {},
  },
];

const DEFAULT_EDGES: Edge[] = [];

// ─────────────────────────────────────────────────────────────
// Categoria de nós para a paleta
// ─────────────────────────────────────────────────────────────
type CategoryKey = "control" | "send" | "ai" | "logic" | "system";

const PALETTE_ORDER: CategoryKey[] = ["control", "send", "ai", "logic", "system"];

// ─────────────────────────────────────────────────────────────
// Edge style global
// ─────────────────────────────────────────────────────────────
const EDGE_STYLE: Partial<Edge> = {
  markerEnd: { type: MarkerType.ArrowClosed, color: "#00d2ff" },
  style: { stroke: "#00d2ff55", strokeWidth: 2 },
  animated: false,
};

// ─────────────────────────────────────────────────────────────
// Componente principal
// ─────────────────────────────────────────────────────────────
export default function FluxoTriagemPage() {
  const [nodes, setNodes, onNodesChange] = useNodesState(DEFAULT_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState(DEFAULT_EDGES);

  const [ativo, setAtivo] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [isDraggingOver, setIsDraggingOver] = useState(false);

  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);

  // ─── onChange para nós (atualiza data inline) ───
  const attachOnChange = useCallback(
    (node: Node): Node => {
      return {
        ...node,
        data: {
          ...node.data,
          onChange: (patch: Record<string, unknown>) => {
            setNodes((nds) =>
              nds.map((n) => (n.id === node.id ? { ...n, data: { ...n.data, ...patch } } : n))
            );
          },
        },
      };
    },
    [setNodes]
  );

  // ─── Auth ───
  const getConfig = () => ({
    headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
  });

  // ─── Carregar fluxo ───
  useEffect(() => {
    axios
      .get("/api-backend/management/fluxo-triagem", getConfig())
      .then((res) => {
        const d: FlowData = res.data;
        if (d.nodes && d.nodes.length > 0) {
          // Reconecta onChange para cada nó carregado
          setNodes(d.nodes.map((n) => attachOnChange(n)));
          setEdges(d.edges || []);
          setAtivo(d.ativo ?? false);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [attachOnChange, setEdges, setNodes]);

  // ─── Salvar fluxo ───
  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      // Remove função onChange antes de serializar
      const cleanNodes = nodes.map((n) => {
      const { onChange: _, ...rest } = n.data as Record<string, unknown>;
      return { ...n, data: rest };
    });
    await axios.post(
        "/api-backend/management/fluxo-triagem",
        { ativo, nodes: cleanNodes, edges },
        getConfig()
      );
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch {
      setError("Erro ao salvar o fluxo. Tente novamente.");
    } finally {
      setSaving(false);
    }
  };


  // ─── Conectar nós ───
  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((eds) =>
        addEdge(
          {
            ...params,
            ...EDGE_STYLE,
            id: `e-${params.source}-${params.sourceHandle || "out"}-${params.target}`,
          },
          eds
        )
      );
    },
    [setEdges]
  );

  // ─── Drop de nó do painel ───
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setIsDraggingOver(true);
  }, []);

  const onDragLeave = useCallback(() => {
    setIsDraggingOver(false);
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDraggingOver(false);
      const type = e.dataTransfer.getData("application/reactflow") as NodeTypeName;
      if (!type || !reactFlowInstance) return;

      const bounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!bounds) return;

      const position = reactFlowInstance.screenToFlowPosition({
        x: e.clientX - bounds.left,
        y: e.clientY - bounds.top,
      });

      const newId = `${type}-${Date.now()}`;
      const newNode: Node = attachOnChange({
        id: newId,
        type,
        position,
        data: getDefaultData(type),
      });
      setNodes((nds) => [...nds, newNode]);
    },
    [reactFlowInstance, attachOnChange, setNodes]
  );

  // ─── Seleção de nó ───
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // ─── Deletar nó selecionado ───
  const deleteSelectedNode = () => {
    if (!selectedNode) return;
    setNodes((nds) => nds.filter((n) => n.id !== selectedNode.id));
    setEdges((eds) =>
      eds.filter(
        (e) => e.source !== selectedNode.id && e.target !== selectedNode.id
      )
    );
    setSelectedNode(null);
  };

  // ─── Limpar canvas ───
  const clearCanvas = () => {
    setNodes([attachOnChange(DEFAULT_NODES[0])]);
    setEdges([]);
    setSelectedNode(null);
  };

  // ─── Grupos de nós para a paleta ───
  const paletteGroups = PALETTE_ORDER.map((cat) => ({
    category: cat,
    label: CATEGORY_LABELS[cat],
    nodes: Object.entries(NODE_CONFIG)
      .filter(([, cfg]) => cfg.category === cat)
      .map(([type, cfg]) => ({ type: type as NodeTypeName, ...cfg })),
  }));

  if (loading) {
    return (
      <div className="min-h-screen bg-[#020617] text-white flex">
        <DashboardSidebar activePage="fluxo-triagem" />
        <main className="flex-1 flex items-center justify-center">
          <div className="relative w-16 h-16">
            <div className="absolute inset-0 rounded-full border-2 border-[#00d2ff]/10 animate-ping" />
            <div className="absolute inset-0 rounded-full border-2 border-t-[#00d2ff] animate-spin" />
            <GitBranch className="absolute inset-0 m-auto w-7 h-7 text-[#00d2ff]" />
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#020617] text-white flex overflow-hidden">
      <DashboardSidebar activePage="fluxo-triagem" />

      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">

        {/* ── Topbar ── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 bg-[#020617]/40 backdrop-blur-xl z-20 shrink-0">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-3">
              <div className="w-2 h-6 bg-linear-to-b from-[#00d2ff] to-[#3b82f6] rounded-full shadow-[0_0_10px_rgba(0,210,255,0.5)]" />
              <div>
                <h1
                  className="text-2xl font-black tracking-tighter"
                  style={{
                    background: "linear-gradient(135deg,#fff 0%,#00d2ff 100%)",
                    WebkitBackgroundClip: "text",
                    WebkitTextFillColor: "transparent",
                  }}
                >
                  FlowForge AI
                </h1>
                <p className="text-[10px] text-slate-500 font-bold uppercase tracking-[0.2em] -mt-1">
                  Visual Logic Engine • {nodes.length} nodes
                </p>
              </div>
            </div>

            {/* Toggle ativo */}
            <div className="flex items-center gap-3 bg-white/5 border border-white/10 rounded-2xl px-4 py-2 backdrop-blur-md shadow-inner">
              <button
                type="button"
                onClick={() => setAtivo((v) => !v)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-all duration-300 ${
                  ativo ? "bg-gradient-to-r from-[#00d2ff] to-[#3b82f6]" : "bg-slate-800"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-lg transition-all duration-300 ${
                    ativo ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
              <span
                className={`text-[11px] font-black uppercase tracking-widest ${
                  ativo ? "text-[#00d2ff] drop-shadow-[0_0_8px_rgba(0,210,255,0.5)]" : "text-slate-500"
                }`}
              >
                {ativo ? "Ativo" : "Pausado"}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {error && (
              <motion.div 
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-2 px-4 py-2 bg-red-500/10 border border-red-500/20 rounded-2xl text-[11px] text-red-400 font-bold"
              >
                <AlertCircle className="w-4 h-4" />
                {error}
              </motion.div>
            )}

            <button
              type="button"
              onClick={clearCanvas}
              className="flex items-center gap-2 px-4 py-2 rounded-2xl text-[11px] font-bold uppercase tracking-widest text-slate-400 hover:text-white border border-white/5 hover:bg-white/5 transition-all"
            >
              <Trash2 className="w-4 h-4" />
              Limpar
            </button>

            <motion.button
              whileHover={{ scale: 1.05, boxShadow: "0 0 30px rgba(0,210,255,0.4)" }}
              whileTap={{ scale: 0.95 }}
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 bg-linear-to-r from-[#00d2ff] to-[#3b82f6] text-black px-6 py-2.5 rounded-2xl font-black uppercase tracking-widest text-[11px] shadow-[0_0_20px_rgba(0,210,255,0.3)] disabled:opacity-50"
            >
              {saving ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Salvando</>
              ) : saved ? (
                <><CheckCircle2 className="w-4 h-4" /> Salvo!</>
              ) : (
                <><Save className="w-4 h-4" /> Publicar</>
              )}
            </motion.button>
          </div>
        </div>

        {/* ── Layout principal ── */}
        <div className="flex flex-1 overflow-hidden">

          {/* ── Paleta de nós (esquerda) ── */}
          <div className="w-56 shrink-0 bg-[#020617]/50 border-r border-white/5 overflow-y-auto py-6 px-3 space-y-6 backdrop-blur-md">
            {paletteGroups.map((group) => (
              <div key={group.category} className="space-y-3">
                <p className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] px-2">
                  {group.label}
                </p>
                <div className="space-y-2">
                  {group.nodes.map(({ type, icon, label, border, headerBg }) => (
                    <motion.div
                      key={type}
                      whileHover={{ scale: 1.03, x: 4 }}
                      whileTap={{ scale: 0.97 }}
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData("application/reactflow", type);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      className="group flex items-center gap-3 px-3 py-2.5 rounded-2xl border cursor-grab active:cursor-grabbing transition-all shadow-sm hover:shadow-md"
                      style={{
                        borderColor: `${border}30`,
                        background: `linear-gradient(135deg, ${headerBg}44, ${headerBg}22)`,
                      }}
                    >
                      <span className="text-lg group-hover:scale-110 transition-transform">{icon}</span>
                      <span className="text-[11px] font-bold text-white/70 group-hover:text-white transition-colors">
                        {label}
                      </span>
                    </motion.div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* ── Canvas ReactFlow ── */}
          <div
            ref={reactFlowWrapper}
            className="flex-1 relative"
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            style={{ background: "#020617" }}
          >
            {/* Overlay de drag */}
            <AnimatePresence>
              {isDraggingOver && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="absolute inset-0 z-10 pointer-events-none"
                  style={{
                    border: "2px dashed #00d2ff55",
                    background: "rgba(0,210,255,0.03)",
                  }}
                />
              )}
            </AnimatePresence>

            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={onNodeClick}
              onPaneClick={onPaneClick}
              onInit={setReactFlowInstance}
              nodeTypes={nodeTypes}
              defaultEdgeOptions={EDGE_STYLE as Edge}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              deleteKeyCode="Delete"
              style={{ background: "transparent" }}
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={1}
                color="#1e293b"
              />
              <Controls
                style={{
                  background: "#0f172a",
                  border: "1px solid rgba(255,255,255,0.05)",
                  borderRadius: "12px",
                }}
              />
              <MiniMap
                style={{
                  background: "#0f172a",
                  border: "1px solid rgba(255,255,255,0.05)",
                  borderRadius: "12px",
                }}
                nodeColor={(n) => {
                  const cfg = NODE_CONFIG[n.type as NodeTypeName];
                  return cfg?.border || "#334155";
                }}
                maskColor="rgba(2,6,23,0.7)"
              />

              {/* Canvas vazio — instrução */}
              {nodes.length === 1 && edges.length === 0 && (
                <Panel position="top-center">
                  <div className="mt-8 text-center">
                    <p className="text-[11px] text-slate-600 font-medium">
                      Arraste nós da paleta esquerda para o canvas e conecte-os para criar seu fluxo.
                    </p>
                  </div>
                </Panel>
              )}
            </ReactFlow>
          </div>

          {/* ── Painel de propriedades (direita) ── */}
          <AnimatePresence>
            {selectedNode && (
              <motion.div
                initial={{ x: 280, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                exit={{ x: 280, opacity: 0 }}
                transition={{ type: "spring", stiffness: 400, damping: 35 }}
                className="w-64 shrink-0 bg-[#0a1628] border-l border-white/5 flex flex-col overflow-hidden"
              >
                {/* Header do painel */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
                  <div className="flex items-center gap-2">
                    <span className="text-base">
                      {NODE_CONFIG[selectedNode.type as NodeTypeName]?.icon || "⬜"}
                    </span>
                    <div>
                      <p className="text-[10px] font-black text-white uppercase tracking-wider">
                        {NODE_CONFIG[selectedNode.type as NodeTypeName]?.label || selectedNode.type}
                      </p>
                      <p className="text-[9px] text-slate-600 font-mono">{selectedNode.id}</p>
                    </div>
                  </div>
                  <div className="flex gap-1">
                    <button
                      type="button"
                      onClick={deleteSelectedNode}
                      className="p-1.5 rounded-lg text-slate-600 hover:text-red-400 hover:bg-red-500/10 transition-all"
                      title="Deletar nó"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedNode(null)}
                      className="p-1.5 rounded-lg text-slate-600 hover:text-white transition-all"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Conteúdo: o próprio nó renderizado no painel */}
                <div className="flex-1 overflow-y-auto p-4">
                  <div className="space-y-3">
                    {/* ID do nó */}
                    <div>
                      <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-1">ID do Nó</p>
                      <p className="text-[10px] text-slate-400 font-mono bg-black/30 px-2 py-1 rounded-lg">
                        {selectedNode.id}
                      </p>
                    </div>

                    {/* Os campos do nó já aparecem inline no canvas.
                        Aqui mostramos apenas informações complementares. */}
                    <div className="p-3 bg-[#00d2ff]/5 border border-[#00d2ff]/10 rounded-xl">
                      <p className="text-[9px] text-slate-500 leading-relaxed">
                        Edite os campos do nó diretamente no canvas. Clique e arraste para reposicionar.
                      </p>
                    </div>

                    {/* Ações */}
                    <div>
                      <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">Ações</p>
                      <button
                        type="button"
                        onClick={deleteSelectedNode}
                        className="w-full flex items-center gap-2 justify-center px-3 py-2 rounded-xl text-[10px] font-black text-red-400 border border-red-500/20 hover:bg-red-500/10 transition-all uppercase tracking-wider"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        Deletar nó
                      </button>
                    </div>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Data padrão por tipo de nó
// ─────────────────────────────────────────────────────────────
function getDefaultData(type: NodeTypeName): Record<string, unknown> {
  const defaults: Record<NodeTypeName, Record<string, unknown>> = {
    start:         {},
    end:           {},
    loop:          { target_node_id: "" },
    sendText:      { texto: "" },
    sendMenu:      {
      tipo: "list", titulo: "Atendimento", texto: "Olá! Como posso ajudar?",
      rodape: "Escolha uma opção", botao: "Ver opções",
      opcoes: [
        { id: "1", titulo: "Suporte" },
        { id: "2", titulo: "Vendas" },
      ],
    },
    sendImage:     { url: "", caption: "" },
    sendAudio:     { url: "" },
    sendMedia:     { type: "image", url: "", caption: "" },
    aiRespond:     { prompt_extra: "" },
    aiClassify:    { conditions: [], variavel: "intencao" },
    aiSentiment:   { variavel: "sentimento" },
    aiQualify:     { perguntas: ["Qual é o seu nome?"], variaveis: ["nome_lead"] },
    aiExtract:     { campos: [{ label: "nome", variavel: "nome_cliente" }] },
    switch:        {
      conditions: [
        { handle: "h1", label: "Opção 1", value: "1" },
        { handle: "h2", label: "Opção 2", value: "2" },
      ],
    },
    condition:     { pattern: "" },
    delay:         { seconds: 2 },
    waitInput:     { prompt: "", variavel: "resposta_usuario" },
    humanTransfer: { mensagem: "Transferindo para um atendente humano. Aguarde! 👤" },
    webhook:       { url: "", method: "POST", body: { phone: "{{phone}}" } },
    aiMenu:        { instrucao: "Gere um menu com base na dúvida do cliente.", botao: "Ver opções", rodape: "Panobianco" },
    setVariable:   { chave: "", valor: "" },
    getVariable:   { chave: "" },
    generateProtocol: { variavel: "protocolo" },
    search:        { termo: "{{mensagem}}", variavel: "v_busca" },
    redis:         { operacao: "set", chave: "", valor: "" },
    sourceFilter:  {},
  };
  return defaults[type] || {};
}
