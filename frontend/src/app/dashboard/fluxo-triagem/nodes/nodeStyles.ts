/**
 * Configurações visuais centralizadas para os nós do editor de fluxo.
 * Cada tipo de nó tem uma cor de borda, ícone e cor do header.
 */

export type NodeTypeName =
  | "start" | "end" | "loop"
  | "sendText" | "sendMenu" | "sendImage" | "sendAudio" | "sendMedia"
  | "aiRespond" | "aiClassify" | "aiSentiment" | "aiQualify" | "aiExtract" | "aiMenu"
  | "switch" | "condition" | "delay" | "waitInput" | "setVariable" | "getVariable"
  | "humanTransfer" | "webhook" | "generateProtocol"
  | "search" | "redis" | "sourceFilter";

export const NODE_CONFIG: Record<NodeTypeName, {
  label: string;
  icon: string;
  border: string;
  headerBg: string;
  headerText: string;
  category: "control" | "send" | "ai" | "logic" | "system";
}> = {
  start:         { label: "Início",          icon: "▶",  border: "#22c55e", headerBg: "#064e3b",  headerText: "#86efac", category: "control" },
  end:           { label: "Fim",             icon: "⏹",  border: "#ef4444", headerBg: "#450a0a",  headerText: "#fca5a5", category: "control" },
  loop:          { label: "Loop",            icon: "🔁", border: "#f97316", headerBg: "#431407",  headerText: "#fdba74", category: "control" },
  sendText:      { label: "Enviar Texto",    icon: "💬", border: "#3b82f6", headerBg: "#172554",  headerText: "#93c5fd", category: "send"    },
  sendMenu:      { label: "Enviar Menu",     icon: "📋", border: "#0ea5e9", headerBg: "#082f49",  headerText: "#7dd3fc", category: "send"    },
  sendImage:     { label: "Enviar Imagem",   icon: "🖼", border: "#6366f1", headerBg: "#1e1b4b",  headerText: "#a5b4fc", category: "send"    },
  sendAudio:     { label: "Enviar Áudio",    icon: "🔊", border: "#a855f7", headerBg: "#3b0764",  headerText: "#d8b4fe", category: "send"    },
  sendMedia:     { label: "Enviar Mídia",    icon: "🎞️", border: "#f43f5e", headerBg: "#4c0519",  headerText: "#fecdd3", category: "send"    },
  aiRespond:     { label: "IA: Resposta",    icon: "🤖", border: "#06b6d4", headerBg: "#083344",  headerText: "#67e8f9", category: "ai"      },
  aiClassify:    { label: "IA: Classificar", icon: "🏷", border: "#22d3ee", headerBg: "#0e7490",  headerText: "#cffafe", category: "ai"      },
  aiSentiment:   { label: "IA: Sentimento",  icon: "😊", border: "#f472b6", headerBg: "#700733",  headerText: "#fbcfe8", category: "ai"      },
  aiQualify:     { label: "IA: Qualificar",  icon: "📝", border: "#10b981", headerBg: "#064e3b",  headerText: "#a7f3d0", category: "ai"      },
  aiExtract:     { label: "IA: Extrair",     icon: "🔍", border: "#fbbf24", headerBg: "#78350f",  headerText: "#fef3c7", category: "ai"      },
  aiMenu:        { label: "IA: Menu",        icon: "🪄", border: "#06b6d4", headerBg: "#164e63",  headerText: "#67e8f9", category: "ai"      },
  search:        { label: "Busca IA",        icon: "🔎", border: "#2dd4bf", headerBg: "#134e4a",  headerText: "#99f6e4", category: "ai"      },
  switch:        { label: "Switch",          icon: "⚡", border: "#8b5cf6", headerBg: "#2e1065",  headerText: "#ddd6fe", category: "logic"   },
  condition:     { label: "Condição",        icon: "❓", border: "#f59e0b", headerBg: "#7c2d12",  headerText: "#fde68a", category: "logic"   },
  delay:         { label: "Delay",           icon: "⏱", border: "#64748b", headerBg: "#1e293b",  headerText: "#cbd5e1", category: "logic"   },
  waitInput:     { label: "Aguardar Input",  icon: "⌨", border: "#71717a", headerBg: "#27272a",  headerText: "#d4d4d8", category: "logic"   },
  setVariable:   { label: "Definir Var",     icon: "📥", border: "#3b82f6", headerBg: "#1e3a8a",  headerText: "#bfdbfe", category: "logic"   },
  getVariable:   { label: "Obter Var",       icon: "📤", border: "#3b82f6", headerBg: "#1e3a8a",  headerText: "#bfdbfe", category: "logic"   },
  redis:         { label: "Redis (DB)",      icon: "💾", border: "#ef4444", headerBg: "#7f1d1d",  headerText: "#fecaca", category: "system"  },
  sourceFilter:  { label: "Filtro Origem",   icon: "🛂", border: "#84cc16", headerBg: "#365314",  headerText: "#d9f99d", category: "system"  },
  humanTransfer: { label: "Transferir",      icon: "👤", border: "#f97316", headerBg: "#7c2d12",  headerText: "#ffedd5", category: "system"  },
  webhook:       { label: "Webhook",         icon: "🌐", border: "#10b981", headerBg: "#064e3b",  headerText: "#d1fae5", category: "system"  },
  generateProtocol: { label: "Protocolo",    icon: "🔢", border: "#2dd4bf", headerBg: "#134e4a",  headerText: "#ccfbf1", category: "system"  },
};

export const CATEGORY_LABELS: Record<string, string> = {
  control: "Controle",
  send:    "Envios",
  ai:      "Inteligência IA",
  logic:   "Lógica",
  system:  "Sistema",
};

/** Base CSS classes reutilizadas por todos os nós. */
export const NODE_BASE_CLASS = "min-w-[220px] max-w-[280px] rounded-2xl overflow-hidden shadow-[0_10px_30px_rgba(0,0,0,0.5)] border-2 text-xs font-medium transition-all hover:shadow-[0_10px_40px_rgba(0,0,0,0.7)] hover:scale-[1.01]";
