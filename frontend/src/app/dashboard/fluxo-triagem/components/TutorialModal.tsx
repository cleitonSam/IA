"use client";
import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, ChevronRight, ChevronLeft, BookOpen } from "lucide-react";

interface TutorialBlock {
  type: string;
  icon: string;
  color: string;
  name: string;
  tagline: string;
  what: string;
  how: string[];
  example: string;
  tips?: string[];
}

const BLOCKS: TutorialBlock[] = [
  {
    type: "start",
    icon: "🚀",
    color: "#22c55e",
    name: "Início",
    tagline: "Ponto de entrada de toda conversa",
    what: "É o primeiro bloco do fluxo. Toda conversa começa aqui automaticamente quando o cliente manda a primeira mensagem.",
    how: [
      "Coloque sempre um único nó Início no fluxo.",
      "Conecte a saída dele ao próximo bloco (normalmente um Enviar Texto de boas-vindas ou um Menu).",
    ],
    example: "Início → Enviar Texto (\"Olá! Como posso ajudar?\") → Menu",
  },
  {
    type: "end",
    icon: "🏁",
    color: "#ef4444",
    name: "Fim",
    tagline: "Encerra o fluxo e limpa a sessão",
    what: "Finaliza o atendimento e apaga o estado da conversa. O próximo contato do cliente reinicia tudo do zero.",
    how: [
      "Use após concluir o atendimento ou após transferir para humano.",
      "Não é obrigatório — o fluxo também encerra se chegar a um nó sem saída.",
    ],
    example: "IA Responde → Fim",
  },
  {
    type: "sendText",
    icon: "💬",
    color: "#3b82f6",
    name: "Enviar Texto",
    tagline: "Manda uma mensagem de texto simples",
    what: "Envia uma mensagem estática para o cliente. Suporta variáveis de sessão no texto.",
    how: [
      "Digite o texto no campo. Use {{nome}}, {{protocolo}}, {{last_choice_label}} para inserir variáveis.",
      "Conecte a saída ao próximo bloco.",
    ],
    example: "\"Olá {{nome}}, seu protocolo é {{protocolo}}. Em breve te atendemos!\"",
    tips: ["Variáveis são preenchidas automaticamente com os dados salvos na sessão."],
  },
  {
    type: "sendMenu",
    icon: "📋",
    color: "#f97316",
    name: "Enviar Menu",
    tagline: "Lista ou botões de opções para o cliente",
    what: "Manda um menu interativo (lista ou botões). O fluxo pausa e aguarda a resposta do cliente.",
    how: [
      "Escolha o tipo: Lista (até 10 opções) ou Botões (máx. 3 no WhatsApp).",
      "Adicione as opções com título e, opcionalmente, descrição.",
      "Conecte a saída do menu ao próximo bloco (normalmente um Switch).",
    ],
    example: "Menu \"Como posso ajudar?\" → Opções: [Planos, Aulas, Falar com consultor]",
    tips: [
      "Após o menu, use o bloco Switch para rotear por cada opção.",
      "O Switch deve ter labels iguais aos títulos das opções.",
    ],
  },
  {
    type: "switch",
    icon: "🔀",
    color: "#f59e0b",
    name: "Switch (Roteador)",
    tagline: "Direciona o fluxo pelo que o cliente escolheu",
    what: "Compara a seleção do cliente com as condições cadastradas e roteia para o caminho correto.",
    how: [
      "Adicione uma condição para cada opção do menu.",
      "No campo 'Label', coloque o mesmo texto do título da opção no menu.",
      "No campo 'Value', coloque o número da opção (1, 2, 3...).",
      "Conecte cada saída (handle) ao bloco correspondente.",
    ],
    example: "Switch: [Label=Planos, Value=1] → IA Responde sobre planos | [Label=Aulas, Value=2] → IA Responde sobre aulas",
    tips: [
      "Se nenhuma condição bater, vai para a saída 1 (fallback).",
      "O label deve corresponder EXATAMENTE ao título da opção no menu.",
    ],
  },
  {
    type: "aiRespond",
    icon: "🤖",
    color: "#a855f7",
    name: "IA Responde",
    tagline: "A IA gera uma resposta personalizada",
    what: "Usa o modelo de IA configurado para gerar uma resposta baseada na instrução e no histórico da conversa.",
    how: [
      "Escreva a instrução no campo. Use {{last_choice_label}} para referenciar a escolha do cliente.",
      "A IA usa o contexto da conversa automaticamente.",
    ],
    example: "\"Responda de forma entusiasta sobre {{last_choice_label}}, destacando os benefícios.\"",
    tips: [
      "Seja específico na instrução — quanto mais detalhada, melhor a resposta.",
      "Use {{nome}} para personalizar o tom.",
    ],
  },
  {
    type: "aiClassify",
    icon: "🏷️",
    color: "#ec4899",
    name: "IA Classifica",
    tagline: "A IA categoriza a mensagem e roteia",
    what: "A IA lê a mensagem do cliente e decide em qual categoria ela se encaixa, roteando para o handle correspondente.",
    how: [
      "Defina as categorias (ex: 'elogio', 'reclamação', 'dúvida').",
      "Cada categoria tem um handle de saída.",
      "Conecte cada handle ao fluxo adequado.",
    ],
    example: "Mensagem → IA Classifica [elogio→Agradece | reclamação→Abre protocolo | dúvida→IA Responde]",
  },
  {
    type: "menuFixoIA",
    icon: "✨",
    color: "#a855f7",
    name: "Menu Fixo + IA",
    tagline: "Menu com opções + IA responde à escolha",
    what: "Envia um menu com opções que você define. Quando o cliente escolhe, a IA gera uma resposta personalizada para aquela opção e roteia pelo handle dela.",
    how: [
      "Defina título, texto e rodapé do menu.",
      "Adicione as opções — cada uma gera um handle de saída.",
      "Escreva a instrução da IA que será usada ao responder à escolha (use {{last_choice_label}}).",
      "Conecte cada handle ao próximo passo.",
    ],
    example: "Menu [Musculação, Pilates, Spinning] → IA: \"Fale sobre {{last_choice_label}} na nossa academia com entusiasmo\"",
    tips: ["Combina a praticidade do menu fixo com a personalização da IA."],
  },
  {
    type: "aiMenuDinamicoIA",
    icon: "🧠",
    color: "#ec4899",
    name: "IA: Menu Dinâmico + Resposta",
    tagline: "IA gera o menu E responde à seleção",
    what: "A IA cria o menu dinamicamente baseado na mensagem do cliente. Depois, quando o cliente escolhe, a IA gera uma resposta contextual.",
    how: [
      "Escreva a instrução para gerar o menu (ex: 'Gere 3 opções sobre serviços de academia').",
      "Defina quantas opções o menu terá (2 a 5).",
      "Escreva a instrução para a IA responder após a escolha.",
      "Conecte as saídas posicionais (Opção 1, 2, 3...) aos próximos blocos.",
    ],
    example: "IA gera menu contextual → cliente escolhe Opção 2 → IA responde → vai para handle h2",
    tips: [
      "As saídas são por POSIÇÃO (1ª opção → h1, 2ª → h2), não por texto.",
      "Ideal para fluxos dinâmicos onde o menu varia por cliente.",
    ],
  },
  {
    type: "businessHours",
    icon: "🕐",
    color: "#0ea5e9",
    name: "Horário Comercial",
    tagline: "Roteia baseado no horário do dia",
    what: "Verifica se o momento atual está dentro do horário de funcionamento configurado e roteia para 'Aberto' ou 'Fechado'.",
    how: [
      "Marque os dias e horários de funcionamento.",
      "Defina o fuso horário (padrão: America/Sao_Paulo).",
      "Conecte a saída verde (Aberto) ao fluxo normal.",
      "Conecte a saída vermelha (Fechado) a uma mensagem de horário de funcionamento.",
    ],
    example: "Início → Horário Comercial → [Aberto: Menu principal | Fechado: 'Retornaremos às 8h']",
  },
  {
    type: "waitInput",
    icon: "⌨️",
    color: "#06b6d4",
    name: "Aguardar Resposta",
    tagline: "Faz uma pergunta e salva a resposta",
    what: "Envia uma pergunta ao cliente e aguarda a resposta. Salva o que o cliente digitou numa variável de sessão.",
    how: [
      "Escreva a pergunta no campo.",
      "Defina o nome da variável onde a resposta será salva (ex: 'nome', 'email').",
      "Após a resposta, o fluxo continua automaticamente.",
    ],
    example: "\"Qual o seu nome?\" → salva em {{nome}} → \"Prazer, {{nome}}!\"",
    tips: ["Use variáveis coletadas em mensagens subsequentes com {{nome_variavel}}."],
  },
  {
    type: "setVariable",
    icon: "📦",
    color: "#64748b",
    name: "Definir Variável",
    tagline: "Salva um valor fixo numa variável",
    what: "Define o valor de uma variável de sessão sem precisar de input do usuário.",
    how: [
      "Defina o nome da variável.",
      "Defina o valor (pode ser texto fixo ou outra variável como {{last_choice_label}}).",
    ],
    example: "setVariable: plano = 'mensal' → IA Responde sobre o plano {{plano}}",
  },
  {
    type: "humanTransfer",
    icon: "👤",
    color: "#f59e0b",
    name: "Transferir para Humano",
    tagline: "Pausa a IA e chama atendente",
    what: "Para a automação e abre a conversa para um atendente humano. Opcionalmente envia uma mensagem de transição.",
    how: [
      "Escreva a mensagem enviada ao cliente antes de transferir (opcional).",
      "Após este bloco, a IA fica pausada até o atendente reativar.",
    ],
    example: "\"Vou te conectar com nosso especialista. Aguarde um instante! 😊\"",
  },
  {
    type: "webhook",
    icon: "🔗",
    color: "#6366f1",
    name: "Webhook",
    tagline: "Chama uma URL externa com os dados da sessão",
    what: "Faz uma requisição HTTP para uma URL externa, enviando as variáveis da sessão. Pode salvar a resposta em variáveis.",
    how: [
      "Coloque a URL do endpoint.",
      "Escolha o método (GET ou POST).",
      "Defina o nome da variável onde salvar a resposta da API (opcional).",
    ],
    example: "POST https://meucrm.com/lead → salva retorno em {{crm_id}}",
    tips: ["Use para integrar com CRMs, ERPs, agendamentos, etc."],
  },
  {
    type: "delay",
    icon: "⏳",
    color: "#64748b",
    name: "Delay",
    tagline: "Aguarda alguns segundos antes de continuar",
    what: "Insere uma pausa no fluxo. Útil para simular digitação humana ou espaçar mensagens.",
    how: [
      "Defina quantos segundos aguardar (1 a 30).",
      "Conecte à entrada e saída normalmente.",
    ],
    example: "Enviar Texto → Delay (2s) → Enviar Menu",
  },
  {
    type: "generateProtocol",
    icon: "🎫",
    color: "#64748b",
    name: "Gerar Protocolo",
    tagline: "Cria um número de protocolo aleatório",
    what: "Gera automaticamente um número de protocolo de 6 dígitos e salva em {{protocolo}}.",
    how: [
      "Basta conectar o bloco no fluxo — sem configuração.",
      "Use {{protocolo}} em mensagens posteriores.",
    ],
    example: "Gerar Protocolo → Enviar Texto: \"Seu protocolo é {{protocolo}}\"",
  },
  {
    type: "condition",
    icon: "❓",
    color: "#06b6d4",
    name: "Condição (Regex)",
    tagline: "Testa a mensagem com expressão regular",
    what: "Verifica se a mensagem do cliente bate com um padrão regex e roteia para 'Sim' ou 'Não'.",
    how: [
      "Escreva o padrão regex no campo (ex: 'sim|s|yes' para detectar confirmação).",
      "Conecte a saída verde (Sim) e vermelha (Não) aos próximos blocos.",
    ],
    example: "Condition: 'sim|s|yes' → [Sim: confirmar | Não: perguntar de novo]",
  },
];

const CATEGORIES = [
  { key: "todos", label: "Todos", icon: "📚" },
  { key: "basic", label: "Básico", icon: "⭐" },
  { key: "ia", label: "IA", icon: "🤖" },
  { key: "logic", label: "Lógica", icon: "🔀" },
  { key: "advanced", label: "Avançado", icon: "⚡" },
];

const BLOCK_CATEGORIES: Record<string, string> = {
  start: "basic", end: "basic", sendText: "basic", sendMenu: "basic",
  aiRespond: "ia", aiClassify: "ia", aiSentiment: "ia", aiQualify: "ia",
  aiExtract: "ia", aiMenu: "ia", menuFixoIA: "ia", aiMenuDinamicoIA: "ia",
  switch: "logic", condition: "logic", businessHours: "logic", loop: "logic",
  waitInput: "advanced", setVariable: "advanced", humanTransfer: "advanced",
  webhook: "advanced", delay: "advanced", generateProtocol: "advanced", search: "advanced",
};

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function TutorialModal({ open, onClose }: Props) {
  const [cat, setCat] = useState("todos");
  const [selected, setSelected] = useState<TutorialBlock | null>(null);
  const [step, setStep] = useState(0);

  const filtered = cat === "todos"
    ? BLOCKS
    : BLOCKS.filter((b) => BLOCK_CATEGORIES[b.type] === cat);

  const currentIndex = selected ? filtered.findIndex((b) => b.type === selected.type) : -1;

  const goNext = () => {
    if (currentIndex < filtered.length - 1) setSelected(filtered[currentIndex + 1]);
  };
  const goPrev = () => {
    if (currentIndex > 0) setSelected(filtered[currentIndex - 1]);
  };

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
        onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      >
        <motion.div
          initial={{ scale: 0.95, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.95, opacity: 0 }}
          transition={{ type: "spring", stiffness: 400, damping: 35 }}
          className="bg-[#0a1628] border border-white/10 rounded-2xl w-full max-w-4xl max-h-[88vh] flex flex-col overflow-hidden shadow-2xl"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
            <div className="flex items-center gap-3">
              <BookOpen className="w-5 h-5 text-[#00d2ff]" />
              <div>
                <h2 className="text-base font-black text-white">Tutorial de Blocos</h2>
                <p className="text-[10px] text-slate-500">Aprenda como cada bloco funciona no fluxo</p>
              </div>
            </div>
            <button type="button" onClick={onClose}
              className="p-2 rounded-xl text-slate-600 hover:text-white hover:bg-white/5 transition-all">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Tabs de categoria */}
          <div className="flex gap-1 px-6 py-3 border-b border-white/5 overflow-x-auto shrink-0">
            {CATEGORIES.map((c) => (
              <button key={c.key} type="button"
                onClick={() => { setCat(c.key); setSelected(null); }}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold whitespace-nowrap transition-all ${
                  cat === c.key
                    ? "bg-white/10 text-white border border-white/20"
                    : "text-slate-500 hover:text-white hover:bg-white/5"
                }`}>
                <span>{c.icon}</span> {c.label}
              </button>
            ))}
          </div>

          <div className="flex flex-1 overflow-hidden">
            {/* Lista lateral */}
            <div className="w-52 shrink-0 border-r border-white/5 overflow-y-auto">
              <div className="p-2 space-y-0.5">
                {filtered.map((b) => (
                  <button key={b.type} type="button"
                    onClick={() => setSelected(b)}
                    className={`w-full flex items-center gap-2 px-3 py-2 rounded-xl text-left transition-all ${
                      selected?.type === b.type
                        ? "bg-white/10 text-white"
                        : "text-slate-400 hover:text-white hover:bg-white/5"
                    }`}>
                    <span className="text-base flex-shrink-0">{b.icon}</span>
                    <span className="text-[11px] font-bold truncate">{b.name}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Conteúdo */}
            <div className="flex-1 overflow-y-auto">
              {!selected ? (
                <div className="flex flex-col items-center justify-center h-full gap-4 p-8 text-center">
                  <span className="text-5xl">👈</span>
                  <p className="text-slate-400 text-sm font-bold">Selecione um bloco ao lado</p>
                  <p className="text-slate-600 text-[11px]">Você verá como cada bloco funciona, com exemplos práticos.</p>
                  <div className="grid grid-cols-2 gap-2 mt-4 w-full max-w-sm">
                    {[
                      { icon: "🚀", tip: "Comece com Start → Enviar Texto de boas-vindas" },
                      { icon: "📋", tip: "Use SendMenu + Switch para menus com roteamento" },
                      { icon: "🤖", tip: "IA Responde usa o contexto da conversa automaticamente" },
                      { icon: "🕐", tip: "Horário Comercial roteia fora do expediente para mensagem automática" },
                    ].map((t, i) => (
                      <div key={i} className="bg-black/20 rounded-xl p-3 border border-white/5 text-left">
                        <span className="text-lg">{t.icon}</span>
                        <p className="text-[10px] text-slate-500 mt-1">{t.tip}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="p-6 space-y-5">
                  {/* Header do bloco */}
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-12 h-12 rounded-2xl flex items-center justify-center text-2xl"
                        style={{ background: `${selected.color}22`, border: `1px solid ${selected.color}44` }}>
                        {selected.icon}
                      </div>
                      <div>
                        <h3 className="text-base font-black text-white">{selected.name}</h3>
                        <p className="text-[11px]" style={{ color: selected.color }}>{selected.tagline}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <button type="button" onClick={goPrev} disabled={currentIndex === 0}
                        className="p-1.5 rounded-lg text-slate-600 hover:text-white disabled:opacity-30 transition-all">
                        <ChevronLeft className="w-4 h-4" />
                      </button>
                      <span className="text-[10px] text-slate-600">{currentIndex + 1}/{filtered.length}</span>
                      <button type="button" onClick={goNext} disabled={currentIndex === filtered.length - 1}
                        className="p-1.5 rounded-lg text-slate-600 hover:text-white disabled:opacity-30 transition-all">
                        <ChevronRight className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  {/* O que é */}
                  <div className="space-y-1.5">
                    <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">O que é</p>
                    <p className="text-[12px] text-slate-300 leading-relaxed">{selected.what}</p>
                  </div>

                  {/* Como usar */}
                  <div className="space-y-2">
                    <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Como usar</p>
                    <ol className="space-y-2">
                      {selected.how.map((step, i) => (
                        <li key={i} className="flex items-start gap-2.5">
                          <span className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-black flex-shrink-0 mt-0.5"
                            style={{ background: `${selected.color}33`, color: selected.color }}>
                            {i + 1}
                          </span>
                          <p className="text-[11px] text-slate-400 leading-relaxed">{step}</p>
                        </li>
                      ))}
                    </ol>
                  </div>

                  {/* Exemplo */}
                  <div className="space-y-1.5">
                    <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Exemplo prático</p>
                    <div className="bg-black/40 border rounded-xl p-3" style={{ borderColor: `${selected.color}33` }}>
                      <p className="text-[11px] font-mono leading-relaxed" style={{ color: selected.color }}>
                        {selected.example}
                      </p>
                    </div>
                  </div>

                  {/* Tips */}
                  {selected.tips && selected.tips.length > 0 && (
                    <div className="space-y-1.5">
                      <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Dicas</p>
                      <div className="space-y-1.5">
                        {selected.tips.map((tip, i) => (
                          <div key={i} className="flex items-start gap-2 bg-[#00d2ff]/5 border border-[#00d2ff]/10 rounded-xl px-3 py-2">
                            <span className="text-[#00d2ff] text-[11px] flex-shrink-0 mt-0.5">💡</span>
                            <p className="text-[11px] text-slate-400">{tip}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Fluxos sugeridos */}
                  {(selected.type === "start" || selected.type === "sendMenu" || selected.type === "switch") && (
                    <div className="space-y-1.5">
                      <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Fluxo recomendado</p>
                      <div className="bg-[#00d2ff]/5 border border-[#00d2ff]/10 rounded-xl p-3 space-y-2">
                        {selected.type === "start" && (
                          <div className="flex flex-wrap items-center gap-1 text-[10px]">
                            {["🚀 Início", "→", "💬 Enviar Texto", "→", "📋 Enviar Menu", "→", "🔀 Switch", "→", "🤖 IA Responde"].map((t, i) => (
                              <span key={i} className={t === "→" ? "text-slate-600" : "bg-white/5 px-2 py-0.5 rounded-lg text-white font-bold"}>{t}</span>
                            ))}
                          </div>
                        )}
                        {selected.type === "sendMenu" && (
                          <div className="flex flex-wrap items-center gap-1 text-[10px]">
                            {["📋 Enviar Menu", "→", "🔀 Switch", "→", "[cada opção leva a um bloco diferente]"].map((t, i) => (
                              <span key={i} className={t === "→" ? "text-slate-600" : "bg-white/5 px-2 py-0.5 rounded-lg text-white font-bold"}>{t}</span>
                            ))}
                          </div>
                        )}
                        {selected.type === "switch" && (
                          <div className="space-y-1 text-[10px] text-slate-400">
                            <p>⚠️ O label de cada condição deve ser idêntico ao título da opção no menu.</p>
                            <p>Ex: Menu tem "Planos" → Switch tem Label="Planos", Value="1"</p>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-3 border-t border-white/5 flex items-center justify-between">
            <p className="text-[10px] text-slate-600">{BLOCKS.length} blocos disponíveis no editor</p>
            <button type="button" onClick={onClose}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white text-[11px] font-bold rounded-xl transition-all">
              Fechar Tutorial
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
