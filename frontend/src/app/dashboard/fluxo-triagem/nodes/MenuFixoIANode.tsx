"use client";
import React from "react";
import { NodeProps, Handle, Position } from "@xyflow/react";
import { NODE_CONFIG, NODE_BASE_CLASS } from "./nodeStyles";
import { NodeTextarea } from "./BaseNode";

interface Opcao { id: string; titulo: string; handle: string }

export default function MenuFixoIANode(props: NodeProps) {
  const { selected } = props;
  const cfg = NODE_CONFIG["menuFixoIA"];
  const data = (props.data || {}) as Record<string, unknown>;
  const onChange = props.data?.onChange as ((patch: Record<string, unknown>) => void) | undefined;

  const opcoes: Opcao[] = Array.isArray(data.opcoes) ? (data.opcoes as Opcao[]) : [];
  const tipo = (data.tipo as string) || "list";

  const setOpcao = (idx: number, field: keyof Opcao, val: string) => {
    const next = [...opcoes];
    next[idx] = { ...next[idx], [field]: val };
    onChange?.({ opcoes: next });
  };

  const addOpcao = () => {
    onChange?.({ opcoes: [...opcoes, { id: String(Date.now()), titulo: "", handle: `h${Date.now()}` }] });
  };

  const removeOpcao = (idx: number) => {
    onChange?.({ opcoes: opcoes.filter((_, i) => i !== idx) });
  };

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
        <span className="text-base">✨</span>
        <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: cfg.headerText }}>
          Menu Fixo + IA Responde
        </span>
      </div>

      <div className="p-3 space-y-2">
        {/* Tipo */}
        <div className="flex gap-1.5">
          {(["list", "button"] as const).map((t) => (
            <button key={t} type="button" onClick={() => onChange?.({ tipo: t })}
              className={`nodrag flex-1 py-1 rounded-lg text-[9px] font-black uppercase tracking-wider border transition-all ${
                tipo === t ? "bg-purple-500/20 text-purple-300 border-purple-500/60" : "bg-black/20 text-slate-600 border-white/5"
              }`}>
              {t === "list" ? "📋 Lista" : "🔘 Botões"}
            </button>
          ))}
        </div>

        {/* Menu fields */}
        <div className="space-y-1">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Título</p>
          <input className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] placeholder-slate-700 focus:outline-none focus:border-white/20"
            value={(data.titulo as string) || ""} onChange={(e) => onChange?.({ titulo: e.target.value })} placeholder="Ex: Como posso ajudar?" />
        </div>
        <div className="space-y-1">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Mensagem</p>
          <textarea rows={2} className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] placeholder-slate-700 focus:outline-none focus:border-white/20 resize-none"
            value={(data.texto as string) || ""} onChange={(e) => onChange?.({ texto: e.target.value })} placeholder="Ex: Olá {{nome}}! Sobre o que você precisa?" />
        </div>
        <div className="space-y-1">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Rodapé</p>
          <input className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] placeholder-slate-700 focus:outline-none focus:border-white/20"
            value={(data.rodape as string) || ""} onChange={(e) => onChange?.({ rodape: e.target.value })} placeholder="Ex: Escolha uma opção" />
        </div>
        {tipo === "list" && (
          <div className="space-y-1">
            <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Texto do botão</p>
            <input className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] placeholder-slate-700 focus:outline-none focus:border-white/20"
              value={(data.botao as string) || ""} onChange={(e) => onChange?.({ botao: e.target.value })} placeholder="Ex: Ver opções" />
          </div>
        )}

        {/* Instrução da IA */}
        <NodeTextarea
          label="Instrução da IA ao Responder"
          value={(data.instrucaoIA as string) || ""}
          onChange={(v) => onChange?.({ instrucaoIA: v })}
          placeholder="Ex: Responda de forma calorosa sobre {{last_choice_label}}, focando nos benefícios."
          rows={2}
        />

        {/* Opções com handles */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Opções ({opcoes.length})</p>
            <button type="button" onClick={addOpcao}
              className="nodrag text-[9px] text-purple-400 hover:text-purple-300 font-bold border border-purple-500/20 px-2 py-0.5 rounded-md">
              + Adicionar
            </button>
          </div>

          <div className="space-y-1.5 max-h-[160px] overflow-y-auto pr-1 nodrag">
            {opcoes.map((op, idx) => (
              <div key={op.handle} className="relative flex gap-1.5 items-center bg-black/30 rounded-lg p-1.5 border border-white/5">
                <span className="text-[9px] text-purple-400 font-black w-4">{idx + 1}</span>
                <input
                  className="nodrag flex-1 bg-transparent text-[11px] text-white placeholder-slate-700 focus:outline-none"
                  value={op.titulo}
                  onChange={(e) => setOpcao(idx, "titulo", e.target.value)}
                  placeholder="Título da opção"
                />
                <button type="button" onClick={() => removeOpcao(idx)}
                  className="nodrag text-slate-700 hover:text-red-400 text-[10px]">✕</button>
                <Handle
                  type="source"
                  position={Position.Right}
                  id={op.handle}
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
        </div>

        {tipo === "button" && opcoes.length > 3 && (
          <p className="text-[9px] text-red-400 font-bold">⚠️ Máx. 3 botões no WhatsApp</p>
        )}
        <p className="text-[9px] text-purple-900">
          Envia menu fixo → usuário escolhe → IA gera resposta personalizada → roteia pelo handle.
        </p>
      </div>
    </div>
  );
}
