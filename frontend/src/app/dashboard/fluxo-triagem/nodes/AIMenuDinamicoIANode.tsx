"use client";
import React from "react";
import { NodeProps, Handle, Position } from "@xyflow/react";
import { NODE_CONFIG, NODE_BASE_CLASS } from "./nodeStyles";
import { NodeTextarea, NodeInput } from "./BaseNode";

export default function AIMenuDinamicoIANode(props: NodeProps) {
  const { selected } = props;
  const cfg = NODE_CONFIG["aiMenuDinamicoIA"];
  const data = (props.data || {}) as Record<string, unknown>;
  const onChange = props.data?.onChange as ((patch: Record<string, unknown>) => void) | undefined;

  const opcoesCount = Math.max(2, Math.min(5, Number(data.opcoes_count) || 3));

  // Gera handles posicionais h1..hN
  const handles = Array.from({ length: opcoesCount }, (_, i) => ({
    id: `h${i + 1}`,
    label: `Opção ${i + 1}`,
  }));

  return (
    <div
      className={NODE_BASE_CLASS}
      style={{
        border: selected ? `2px solid ${cfg.border}` : `1px solid ${cfg.border}55`,
        background: "#0f172a",
        boxShadow: selected ? `0 0 20px ${cfg.border}55` : `0 4px 20px rgba(0,0,0,0.5)`,
        position: "relative",
      }}
    >
      <Handle type="target" position={Position.Left}
        style={{ background: cfg.border, width: 10, height: 10, border: `2px solid ${cfg.border}`, boxShadow: `0 0 6px ${cfg.border}` }} />

      <div className="flex items-center gap-2 px-3 py-2" style={{ background: cfg.headerBg }}>
        <span className="text-base">🧠</span>
        <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: cfg.headerText }}>
          IA: Menu Dinâmico + Resposta
        </span>
      </div>

      <div className="p-3 space-y-2">
        {/* Instrução para gerar o menu */}
        <NodeTextarea
          label="Instrução: Gerar Menu"
          value={(data.instrucaoMenu as string) || ""}
          onChange={(v) => onChange?.({ instrucaoMenu: v })}
          placeholder="Ex: Gere um menu com opções relevantes sobre academia baseado na mensagem do usuário."
          rows={2}
        />

        {/* Instrução para responder após seleção */}
        <NodeTextarea
          label="Instrução: Responder à Seleção"
          value={(data.instrucaoResposta as string) || ""}
          onChange={(v) => onChange?.({ instrucaoResposta: v })}
          placeholder="Ex: O usuário escolheu {{last_choice_label}}. Responda com entusiasmo e forneça detalhes."
          rows={2}
        />

        {/* Número de opções */}
        <div className="space-y-1">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Número de Opções</p>
          <div className="flex gap-1.5">
            {[2, 3, 4, 5].map((n) => (
              <button key={n} type="button"
                onClick={() => onChange?.({ opcoes_count: n })}
                className={`nodrag flex-1 py-1 rounded-lg text-[10px] font-black border transition-all ${
                  opcoesCount === n
                    ? "bg-pink-500/20 text-pink-300 border-pink-500/60"
                    : "bg-black/20 text-slate-600 border-white/5"
                }`}>
                {n}
              </button>
            ))}
          </div>
        </div>

        {/* Configuração visual do menu */}
        <NodeInput
          label="Texto do Botão"
          value={(data.botao as string) || ""}
          onChange={(v) => onChange?.({ botao: v })}
          placeholder="Ex: Ver opções"
        />
        <NodeInput
          label="Rodapé"
          value={(data.rodape as string) || ""}
          onChange={(v) => onChange?.({ rodape: v })}
          placeholder="Ex: Powered by IA"
        />

        {/* Handles posicionais */}
        <div className="space-y-1">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Saídas por Posição</p>
          {handles.map((h, i) => (
            <div key={h.id} className="relative flex items-center bg-black/30 rounded-lg px-2 py-1 border border-white/5">
              <span className="text-[10px] text-pink-400 font-bold flex-1">{h.label}</span>
              <Handle
                type="source"
                position={Position.Right}
                id={h.id}
                style={{
                  background: cfg.border,
                  width: 8,
                  height: 8,
                  border: `2px solid ${cfg.border}`,
                  boxShadow: `0 0 4px ${cfg.border}`,
                  right: -12,
                  top: "50%",
                }}
              />
            </div>
          ))}
        </div>

        <p className="text-[9px] text-pink-900">
          IA gera menu contextual → usuário escolhe → IA responde → roteia por posição.
        </p>
      </div>
    </div>
  );
}
