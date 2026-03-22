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
  Save, Loader2, CheckCircle2, Trash2, GitBranch, AlertCircle, X, Copy, LayoutTemplate, BookOpen, Power
} from "lucide-react";
import DashboardSidebar from "@/components/DashboardSidebar";
import { nodeTypes } from "./nodes";
import { NODE_CONFIG, CATEGORY_LABELS, NodeTypeName } from "./nodes/nodeStyles";
import TemplatesModal from "./components/TemplatesModal";
import TutorialModal from "./components/TutorialModal";

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
  animated: true,
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
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [paletteSearch, setPaletteSearch] = useState("");
  const [showTemplates, setShowTemplates] = useState(false);
  const [showTutorial, setShowTutorial] = useState(false);

  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);
  const justDroppedRef = useRef(false);
  const clipboardRef = useRef<Node | null>(null);
  const hoverLeaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
      // Sinaliza que acabamos de soltar — próximo click não abre painel
      justDroppedRef.current = true;
      setTimeout(() => { justDroppedRef.current = false; }, 300);
    },
    [reactFlowInstance, attachOnChange, setNodes]
  );

  // ─── Seleção de nó ───
  const onNodeClick = useCallback((e: React.MouseEvent, node: Node) => {
    if (justDroppedRef.current) return;
    const tag = (e.target as HTMLElement).tagName;
    if (["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(tag)) return;
    setSelectedNode((prev) => (prev?.id === node.id ? null : node));
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // ─── Hover no nó (com delay no leave para não sumir ao mover para toolbar) ───
  const onNodeMouseEnter = useCallback((_: React.MouseEvent, node: Node) => {
    if (hoverLeaveTimer.current) clearTimeout(hoverLeaveTimer.current);
    setHoveredNodeId(node.id);
  }, []);
  const onNodeMouseLeave = useCallback(() => {
    hoverLeaveTimer.current = setTimeout(() => setHoveredNodeId(null), 180);
  }, []);

  // ─── Duplicar nó ───
  const duplicateNode = useCallback((nodeId: string) => {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const newId = `${node.type}-${Date.now()}`;
    const { onChange: _, onDelete: __, onDuplicate: ___, ...cleanData } = node.data as Record<string, unknown>;
    const newNode = attachOnChange({
      ...node,
      id: newId,
      position: { x: node.position.x + 40, y: node.position.y + 40 },
      data: cleanData,
      selected: false,
    });
    setNodes((nds) => [...nds, newNode]);
  }, [nodes, attachOnChange, setNodes]);

  // ─── Ctrl+C / Ctrl+V ───
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (document.activeElement as HTMLElement)?.tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      if ((e.ctrlKey || e.metaKey) && e.key === "c") {
        const target = selectedNode || (hoveredNodeId ? nodes.find((n) => n.id === hoveredNodeId) || null : null);
        if (target) clipboardRef.current = target;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "v") {
        const node = clipboardRef.current;
        if (!node) return;
        const newId = `${node.type}-${Date.now()}`;
        const { onChange: _, onDelete: __, onDuplicate: ___, ...cleanData } = node.data as Record<string, unknown>;
        const newNode = attachOnChange({
          ...node,
          id: newId,
          position: { x: node.position.x + 40, y: node.position.y + 40 },
          data: cleanData,
          selected: false,
        });
        setNodes((nds) => [...nds, newNode]);
        clipboardRef.current = { ...newNode, position: { x: newNode.position.x + 40, y: newNode.position.y + 40 } };
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectedNode, hoveredNodeId, nodes, attachOnChange, setNodes]);


  // ─── Limpar canvas ───
  const clearCanvas = () => {
    setNodes([attachOnChange(DEFAULT_NODES[0])]);
    setEdges([]);
    setSelectedNode(null);
  };

  // ─── Grupos de nós para a paleta (com filtro de busca) ───
  const searchLower = paletteSearch.toLowerCase();
  const paletteGroups = PALETTE_ORDER.map((cat) => ({
    category: cat,
    label: CATEGORY_LABELS[cat],
    nodes: Object.entries(NODE_CONFIG)
      .filter(([, cfg]) => cfg.category === cat)
      .filter(([type, cfg]) =>
        !searchLower ||
        cfg.label.toLowerCase().includes(searchLower) ||
        type.toLowerCase().includes(searchLower)
      )
      .map(([type, cfg]) => ({ type: type as NodeTypeName, ...cfg })),
  })).filter((g) => g.nodes.length > 0);

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
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/5 bg-[#020617]/60 backdrop-blur-xl z-20 shrink-0 gap-3">
          {/* Logo + stats */}
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-1.5 h-5 rounded-full flex-shrink-0" style={{ background: "linear-gradient(to bottom,#00d2ff,#3b82f6)", boxShadow: "0 0 8px #00d2ff88" }} />
            <div className="min-w-0">
              <h1 className="text-sm font-black tracking-tight leading-none" style={{ background: "linear-gradient(135deg,#fff 0%,#00d2ff 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                FlowForge AI
              </h1>
              <p className="text-[9px] text-slate-600 font-bold uppercase tracking-widest mt-0.5">{nodes.length} nós · {edges.length} conexões</p>
            </div>
          </div>

          {/* Centro: Toggle + ações secundárias */}
          <div className="flex items-center gap-1.5 flex-1 justify-center">
            {/* Toggle Ativo/Pausado */}
            <button
              type="button"
              onClick={() => setAtivo((v) => !v)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border text-[10px] font-black uppercase tracking-widest transition-all ${
                ativo
                  ? "border-[#00d2ff]/40 bg-[#00d2ff]/10 text-[#00d2ff]"
                  : "border-white/10 bg-white/3 text-slate-500 hover:text-slate-300"
              }`}
            >
              <Power className="w-3 h-3" />
              {ativo ? "Ativo" : "Pausado"}
            </button>

            <div className="w-px h-5 bg-white/8 mx-1" />

            <button
              type="button"
              onClick={() => setShowTemplates(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[10px] font-bold text-slate-400 hover:text-white border border-white/5 hover:bg-white/5 transition-all"
            >
              <LayoutTemplate className="w-3.5 h-3.5" />
              Templates
            </button>

            <button
              type="button"
              onClick={() => setShowTutorial(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[10px] font-bold text-[#00d2ff]/80 hover:text-[#00d2ff] border border-[#00d2ff]/15 hover:bg-[#00d2ff]/8 transition-all"
            >
              <BookOpen className="w-3.5 h-3.5" />
              Tutorial
            </button>

            <button
              type="button"
              onClick={clearCanvas}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[10px] font-bold text-slate-500 hover:text-red-400 border border-white/5 hover:border-red-500/20 hover:bg-red-500/5 transition-all"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Limpar
            </button>
          </div>

          {/* Direita: erro + salvar */}
          <div className="flex items-center gap-2">
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/10 border border-red-500/20 rounded-xl text-[10px] text-red-400 font-bold"
              >
                <AlertCircle className="w-3 h-3" />
                {error}
              </motion.div>
            )}

            <motion.button
              whileHover={{ scale: 1.04, boxShadow: "0 0 24px rgba(0,210,255,0.35)" }}
              whileTap={{ scale: 0.96 }}
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 px-5 py-2 rounded-xl font-black uppercase tracking-widest text-[10px] text-black disabled:opacity-50 shadow-[0_0_16px_rgba(0,210,255,0.25)]"
              style={{ background: "linear-gradient(135deg,#00d2ff,#3b82f6)" }}
            >
              {saving ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Salvando</> : saved ? <><CheckCircle2 className="w-3.5 h-3.5" /> Salvo!</> : <><Save className="w-3.5 h-3.5" /> Publicar</>}
            </motion.button>
          </div>
        </div>

        {/* ── Layout principal ── */}
        <div className="flex flex-1 overflow-hidden">

          {/* ── Paleta de nós (esquerda) ── */}
          <div className="w-56 shrink-0 bg-[#020617]/50 border-r border-white/5 flex flex-col backdrop-blur-md">
            {/* Busca */}
            <div className="px-3 pt-4 pb-2 border-b border-white/5">
              <div className="relative">
                <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-600 text-[11px]">🔍</span>
                <input
                  type="text"
                  value={paletteSearch}
                  onChange={(e) => setPaletteSearch(e.target.value)}
                  placeholder="Buscar nó..."
                  className="w-full bg-black/40 border border-white/8 rounded-xl pl-7 pr-2 py-1.5 text-white text-[11px] placeholder-slate-700 focus:outline-none focus:border-white/20"
                />
              </div>
            </div>
            <div className="flex-1 overflow-y-auto py-4 px-3 space-y-5">
            {paletteGroups.map((group) => (
              <div key={group.category} className="space-y-3">
                <p className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] px-2">
                  {group.label}
                </p>
                <div className="space-y-2">
                  {group.nodes.map(({ type, icon, label, border, headerBg }) => (
                    <div
                      key={type}
                      draggable
                      onDragStart={(e: React.DragEvent) => {
                        e.dataTransfer.setData("application/reactflow", type);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      className="group flex items-center gap-3 px-3 py-2.5 rounded-2xl border cursor-grab active:cursor-grabbing transition-all shadow-sm hover:shadow-md hover:scale-[1.03] hover:translate-x-1"
                      style={{
                        borderColor: `${border}30`,
                        background: `linear-gradient(135deg, ${headerBg}44, ${headerBg}22)`,
                      }}
                    >
                      <span className="text-lg group-hover:scale-110 transition-transform">{icon}</span>
                      <span className="text-[11px] font-bold text-white/70 group-hover:text-white transition-colors">
                        {label}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            </div>
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
              onNodeMouseEnter={onNodeMouseEnter}
              onNodeMouseLeave={onNodeMouseLeave}
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

              {/* Toolbar flutuante: aparece ao passar o mouse sobre um nó */}
              {hoveredNodeId && reactFlowInstance && (() => {
                const node = nodes.find((n) => n.id === hoveredNodeId);
                if (!node) return null;
                const cfg = NODE_CONFIG[node.type as NodeTypeName];
                const w = (node.measured as { width?: number })?.width || 240;
                const screenPos = reactFlowInstance.flowToScreenPosition({ x: node.position.x + w / 2, y: node.position.y });
                const bounds = reactFlowWrapper.current?.getBoundingClientRect();
                if (!bounds) return null;
                const left = screenPos.x - bounds.left;
                const top = screenPos.y - bounds.top - 40;
                return (
                  <div
                    style={{ position: "absolute", left, top, transform: "translateX(-50%)", zIndex: 100, pointerEvents: "all" }}
                    onMouseEnter={() => { if (hoverLeaveTimer.current) clearTimeout(hoverLeaveTimer.current); setHoveredNodeId(hoveredNodeId); }}
                    onMouseLeave={() => { hoverLeaveTimer.current = setTimeout(() => setHoveredNodeId(null), 180); }}
                    className="flex items-center gap-1 px-2 py-1 rounded-xl border border-white/10 bg-[#0a1628]/95 backdrop-blur-md shadow-2xl"
                  >
                    <div className="w-2 h-2 rounded-full mr-1 flex-shrink-0" style={{ background: cfg?.border || "#888" }} />
                    <span className="text-[9px] font-black text-slate-400 uppercase tracking-widest mr-2 max-w-[80px] truncate">
                      {cfg?.label || node.type}
                    </span>
                    <div className="w-px h-3 bg-white/10" />
                    <button
                      type="button"
                      onClick={() => duplicateNode(hoveredNodeId)}
                      className="p-1 rounded-lg text-slate-400 hover:text-[#00d2ff] hover:bg-[#00d2ff]/10 transition-all"
                      title="Duplicar (Ctrl+C → Ctrl+V)"
                    >
                      <Copy className="w-3 h-3" />
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setNodes((nds) => nds.filter((n) => n.id !== hoveredNodeId));
                        setEdges((eds) => eds.filter((e) => e.source !== hoveredNodeId && e.target !== hoveredNodeId));
                        if (selectedNode?.id === hoveredNodeId) setSelectedNode(null);
                        setHoveredNodeId(null);
                      }}
                      className="p-1 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-all"
                      title="Excluir (Delete)"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                );
              })()}
            </ReactFlow>
          </div>

        </div>
      </main>

      {/* ── Modal de Templates ── */}
      <TemplatesModal
        open={showTemplates}
        onClose={() => setShowTemplates(false)}
        currentFlow={{ ativo, nodes: nodes.map((n) => { const { onChange: _, ...rest } = n.data as Record<string, unknown>; return { ...n, data: rest }; }), edges }}
        onLoadTemplate={(flowData) => {
          if (flowData.nodes && flowData.nodes.length > 0) {
            setNodes((flowData.nodes as Node[]).map((n) => attachOnChange(n as Node)));
            setEdges((flowData.edges as Edge[]) || []);
            setAtivo(flowData.ativo ?? false);
          }
        }}
      />

      {/* ── Modal de Tutorial ── */}
      <TutorialModal open={showTutorial} onClose={() => setShowTutorial(false)} />
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
    menuFixoIA:    {
      tipo: "list", titulo: "Como posso ajudar?", texto: "Olá! Selecione uma das opções abaixo 👇",
      rodape: "Escolha uma opção", botao: "Ver opções",
      instrucaoIA: "Responda de forma acolhedora e detalhada sobre {{last_choice_label}}.",
      opcoes: [
        { id: "1", titulo: "Planos e Preços", handle: "h1" },
        { id: "2", titulo: "Agendar Visita", handle: "h2" },
      ],
    },
    aiMenuDinamicoIA: {
      instrucaoMenu: "Gere um menu com opções relevantes baseado na mensagem do usuário.",
      instrucaoResposta: "O usuário escolheu {{last_choice_label}}. Responda com entusiasmo e forneça informações detalhadas.",
      opcoes_count: 3, botao: "Ver opções", rodape: "Powered by IA",
    },
    businessHours: {
      fusoHorario: "America/Sao_Paulo",
      horarios: {
        "0": { ativo: true, inicio: "08:00", fim: "18:00" },
        "1": { ativo: true, inicio: "08:00", fim: "18:00" },
        "2": { ativo: true, inicio: "08:00", fim: "18:00" },
        "3": { ativo: true, inicio: "08:00", fim: "18:00" },
        "4": { ativo: true, inicio: "08:00", fim: "18:00" },
        "5": { ativo: true, inicio: "08:00", fim: "13:00" },
        "6": { ativo: false, inicio: "00:00", fim: "00:00" },
      },
    },
    setVariable:   { chave: "", valor: "" },
    getVariable:   { chave: "" },
    generateProtocol: { variavel: "protocolo" },
    search:        { termo: "{{mensagem}}", variavel: "v_busca" },
    redis:         { operacao: "set", chave: "", valor: "" },
    sourceFilter:  {},
  };
  return defaults[type] || {};
}
