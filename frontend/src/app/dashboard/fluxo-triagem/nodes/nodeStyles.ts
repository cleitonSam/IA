/**
 * Configurações visuais centralizadas para os nós do editor de fluxo.
 * Cada tipo de nó tem uma cor de borda, ícone e cor do header.
 */

export type NodeTypeName =
  | "start" | "end" | "loop"
  | "sendText" | "sendMenu" | "sendImage" | "sendAudio"
  | "aiRespond" | "aiClassify" | "aiSentiment" | "aiQualify" | "aiExtract"
  | "switch" | "condition" | "delay" | "waitInput"
  | "humanTransfer" | "webhook";

export const NODE_CONFIG: Record<NodeTypeName, {
  label: string;
  icon: string;
  border: string;
  headerBg: string;
  headerText: string;
  category: "control" | "send" | "ai" | "logic" | "system";
}> = {
  start:         { label: "Início",          icon: "▶",  border: "#22c55e", headerBg: "#14532d",  headerText: "#86efac", category: "control" },
  end:           { label: "Fim",             icon: "⏹",  border: "#ef4444", headerBg: "#7f1d1d",  headerText: "#fca5a5", category: "control" },
  loop:          { label: "Loop",            icon: "🔁", border: "#f97316", headerBg: "#7c2d12",  headerText: "#fdba74", category: "control" },
  sendText:      { label: "Enviar Texto",    icon: "💬", border: "#94a3b8", headerBg: "#1e293b",  headerText: "#e2e8f0", category: "send"    },
  sendMenu:      { label: "Enviar Menu",     icon: "📋", border: "#3b82f6", headerBg: "#1e3a5f",  headerText: "#93c5fd", category: "send"    },
  sendImage:     { label: "Enviar Imagem",   icon: "🖼", border: "#6366f1", headerBg: "#312e81",  headerText: "#a5b4fc", category: "send"    },
  sendAudio:     { label: "Enviar Áudio",    icon: "🔊", border: "#a855f7", headerBg: "#4a044e",  headerText: "#d8b4fe", category: "send"    },
  aiRespond:     { label: "IA: Resposta",    icon: "🤖", border: "#06b6d4", headerBg: "#164e63",  headerText: "#67e8f9", category: "ai"      },
  aiClassify:    { label: "IA: Classificar", icon: "🏷", border: "#60a5fa", headerBg: "#1e3a5f",  headerText: "#bfdbfe", category: "ai"      },
  aiSentiment:   { label: "IA: Sentimento",  icon: "😊", border: "#f472b6", headerBg: "#500724",  headerText: "#fbcfe8", category: "ai"      },
  aiQualify:     { label: "IA: Qualificar",  icon: "📝", border: "#2dd4bf", headerBg: "#134e4a",  headerText: "#99f6e4", category: "ai"      },
  aiExtract:     { label: "IA: Extrair",     icon: "🔍", border: "#facc15", headerBg: "#713f12",  headerText: "#fef08a", category: "ai"      },
  switch:        { label: "Switch",          icon: "⚡", border: "#a78bfa", headerBg: "#2e1065",  headerText: "#ddd6fe", category: "logic"   },
  condition:     { label: "Condição",        icon: "❓", border: "#f59e0b", headerBg: "#78350f",  headerText: "#fde68a", category: "logic"   },
  delay:         { label: "Delay",           icon: "⏱", border: "#64748b", headerBg: "#1e293b",  headerText: "#94a3b8", category: "logic"   },
  waitInput:     { label: "Aguardar Input",  icon: "⌨", border: "#78716c", headerBg: "#292524",  headerText: "#d6d3d1", category: "logic"   },
  humanTransfer: { label: "Transferir",      icon: "👤", border: "#f97316", headerBg: "#431407",  headerText: "#fed7aa", category: "system"  },
  webhook:       { label: "Webhook",         icon: "🌐", border: "#84cc16", headerBg: "#1a2e05",  headerText: "#bef264", category: "system"  },
};

export const CATEGORY_LABELS: Record<string, string> = {
  control: "Controle",
  send:    "Envios",
  ai:      "Inteligência IA",
  logic:   "Lógica",
  system:  "Sistema",
};

/** Base CSS classes reutilizadas por todos os nós. */
export const NODE_BASE_CLASS = "min-w-[220px] max-w-[280px] rounded-2xl overflow-hidden shadow-xl text-xs font-medium";
