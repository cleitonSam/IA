/**
 * Configurações visuais centralizadas para os nós do editor de fluxo.
 * Cada tipo de nó tem uma cor de borda, ícone e cor do header.
 */

export type NodeTypeName =
  | "start" | "end" | "loop" | "goToMenu"
  | "sendText" | "sendMenu" | "sendImage" | "sendAudio" | "sendMedia"
  | "sendLocation" | "sendContact" | "sendPoll" | "setPresence"
  | "sendReaction" | "editMessage" | "deleteMessage"
  | "addLabel" | "removeLabel"
  | "httpRequest"
  | "aiRespond" | "aiClassify" | "aiSentiment" | "aiQualify" | "aiExtract" | "aiMenu"
  | "menuFixoIA" | "aiMenuDinamicoIA"
  | "switch" | "condition" | "delay" | "waitInput" | "setVariable" | "getVariable"
  | "businessHours"
  | "humanTransfer" | "transferTeam" | "webhook" | "generateProtocol"
  | "search" | "redis" | "sourceFilter"
  | "delayHuman" | "abTestSplit" | "formValidation" | "stickyNote";

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
  goToMenu:      { label: "Voltar ao Menu",  icon: "↩",  border: "#34d399", headerBg: "#064e3b",  headerText: "#6ee7b7", category: "control" },
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
  aiMenu:           { label: "IA: Menu",              icon: "🪄", border: "#06b6d4", headerBg: "#164e63",  headerText: "#67e8f9", category: "ai"      },
  menuFixoIA:       { label: "Menu Fixo + IA",        icon: "✨", border: "#a855f7", headerBg: "#3b0764",  headerText: "#e9d5ff", category: "ai"      },
  aiMenuDinamicoIA: { label: "IA: Menu Dinâmico + IA", icon: "🧠", border: "#ec4899", headerBg: "#500724",  headerText: "#fbcfe8", category: "ai"      },
  search:           { label: "Busca IA",              icon: "🔎", border: "#2dd4bf", headerBg: "#134e4a",  headerText: "#99f6e4", category: "ai"      },
  switch:           { label: "Switch",                icon: "⚡", border: "#8b5cf6", headerBg: "#2e1065",  headerText: "#ddd6fe", category: "logic"   },
  condition:     { label: "Condição",        icon: "❓", border: "#f59e0b", headerBg: "#7c2d12",  headerText: "#fde68a", category: "logic"   },
  delay:         { label: "Delay",           icon: "⏱", border: "#64748b", headerBg: "#1e293b",  headerText: "#cbd5e1", category: "logic"   },
  waitInput:     { label: "Aguardar Input",   icon: "⌨", border: "#71717a", headerBg: "#27272a",  headerText: "#d4d4d8", category: "logic"   },
  setVariable:   { label: "Definir Var",      icon: "📥", border: "#3b82f6", headerBg: "#1e3a8a",  headerText: "#bfdbfe", category: "logic"   },
  getVariable:   { label: "Obter Var",        icon: "📤", border: "#3b82f6", headerBg: "#1e3a8a",  headerText: "#bfdbfe", category: "logic"   },
  businessHours: { label: "Horário Comercial", icon: "🕐", border: "#0ea5e9", headerBg: "#082f49",  headerText: "#7dd3fc", category: "logic"   },
  redis:         { label: "Redis (DB)",      icon: "💾", border: "#ef4444", headerBg: "#7f1d1d",  headerText: "#fecaca", category: "system"  },
  sourceFilter:  { label: "Filtro Origem",   icon: "🛂", border: "#84cc16", headerBg: "#365314",  headerText: "#d9f99d", category: "system"  },
  humanTransfer: { label: "Transferir Humano", icon: "👤", border: "#f97316", headerBg: "#7c2d12",  headerText: "#ffedd5", category: "system"  },
  transferTeam:  { label: "Transferir Time",  icon: "🏢", border: "#38bdf8", headerBg: "#0c4a6e",  headerText: "#7dd3fc", category: "system"  },
  webhook:       { label: "Webhook",         icon: "🌐", border: "#10b981", headerBg: "#064e3b",  headerText: "#d1fae5", category: "system"  },
  sendLocation:  { label: "Enviar Local",    icon: "📍", border: "#06b6d4", headerBg: "#0c4a6e",  headerText: "#a5f3fc", category: "send"    },
  sendContact:   { label: "Enviar Contato",  icon: "👤", border: "#818cf8", headerBg: "#1e1b4b",  headerText: "#c7d2fe", category: "send"    },
  sendPoll:      { label: "Enviar Enquete",  icon: "📊", border: "#fbbf24", headerBg: "#78350f",  headerText: "#fde68a", category: "send"    },
  setPresence:   { label: "Digitando...",    icon: "⏳", border: "#94a3b8", headerBg: "#1e293b",  headerText: "#cbd5e1", category: "send"    },
  sendReaction:  { label: "Reacao (Emoji)",  icon: "👍", border: "#fb923c", headerBg: "#7c2d12",  headerText: "#fed7aa", category: "send"    },
  editMessage:   { label: "Editar Mensagem", icon: "✏️", border: "#facc15", headerBg: "#713f12",  headerText: "#fef9c3", category: "send"    },
  deleteMessage: { label: "Apagar Mensagem", icon: "🗑",  border: "#ef4444", headerBg: "#7f1d1d",  headerText: "#fecaca", category: "send"    },
  addLabel:      { label: "Adicionar Tag",   icon: "🏷",  border: "#14b8a6", headerBg: "#134e4a",  headerText: "#ccfbf1", category: "system"  },
  removeLabel:   { label: "Remover Tag",     icon: "🚫", border: "#f43f5e", headerBg: "#4c0519",  headerText: "#fecdd3", category: "system"  },
  httpRequest:   { label: "HTTP Request",    icon: "🌐", border: "#10b981", headerBg: "#064e3b",  headerText: "#d1fae5", category: "system"  },
  delayHuman:    { label: "Delay Humano",    icon: "⏳", border: "#78716c", headerBg: "#292524",  headerText: "#e7e5e4", category: "logic"   },
  abTestSplit:   { label: "A/B Test",        icon: "🧪", border: "#c084fc", headerBg: "#3b0764",  headerText: "#e9d5ff", category: "logic"   },
  formValidation:{ label: "Validar Campo",   icon: "✅", border: "#059669", headerBg: "#064e3b",  headerText: "#bbf7d0", category: "logic"   },
  stickyNote:    { label: "Nota (Sticky)",   icon: "📝", border: "#fbbf24", headerBg: "#78350f",  headerText: "#fef3c7", category: "system"  },
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
