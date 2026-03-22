"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput, NodeTextarea } from "./BaseNode";

interface MenuOpcao { id: string; titulo: string }

export default function SendMenuNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, unknown>;
  const onChange = props.data?.onChange as ((patch: Record<string, unknown>) => void) | undefined;
  const opcoes: MenuOpcao[] = Array.isArray(data.opcoes) ? (data.opcoes as MenuOpcao[]) : [];
  const tipo = (data.tipo as string) || "list";

  const setOpcao = (idx: number, field: keyof MenuOpcao, val: string) => {
    const next = [...opcoes];
    next[idx] = { ...next[idx], [field]: val };
    onChange?.({ opcoes: next });
  };

  const addOpcao = () => {
    onChange?.({ opcoes: [...opcoes, { id: String(Date.now()), titulo: "" }] });
  };

  const removeOpcao = (idx: number) => {
    onChange?.({ opcoes: opcoes.filter((_, i) => i !== idx) });
  };

  return (
    <BaseNode nodeType="sendMenu" {...props}>
      {/* Tipo */}
      <div className="flex gap-1.5">
        {(["list", "button"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => onChange?.({ tipo: t })}
            className={`nodrag flex-1 py-1 rounded-lg text-[9px] font-black uppercase tracking-wider border transition-all ${
              tipo === t ? "bg-blue-500/20 text-blue-300 border-blue-500/60" : "bg-black/20 text-slate-600 border-white/5"
            }`}
          >
            {t === "list" ? "📋 Lista" : "🔘 Botões"}
          </button>
        ))}
      </div>

      <NodeInput
        label="Título"
        value={(data.titulo as string) || ""}
        onChange={(v) => onChange?.({ titulo: v })}
        placeholder="Ex: Atendimento"
      />
      <NodeTextarea
        label="Mensagem"
        value={(data.texto as string) || ""}
        onChange={(v) => onChange?.({ texto: v })}
        placeholder="Ex: Olá, {{nome}}! Como posso ajudar?"
        rows={2}
      />
      <NodeInput
        label="Rodapé"
        value={(data.rodape as string) || ""}
        onChange={(v) => onChange?.({ rodape: v })}
        placeholder="Ex: Escolha uma opção"
      />
      {tipo === "list" && (
        <NodeInput
          label="Texto do botão"
          value={(data.botao as string) || ""}
          onChange={(v) => onChange?.({ botao: v })}
          placeholder="Ex: Ver opções"
        />
      )}

      {/* Opções */}
      <div className="space-y-1.5 mt-1">
        <div className="flex items-center justify-between">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">
            Opções ({opcoes.length})
          </p>
          <button
            type="button"
            onClick={addOpcao}
            className="nodrag text-[9px] text-blue-400 hover:text-blue-300 font-bold border border-blue-500/20 hover:border-blue-500/40 px-2 py-0.5 rounded-md"
          >
            + Adicionar
          </button>
        </div>
        <div className="space-y-1.5 max-h-[160px] overflow-y-auto pr-1 nodrag">
          {opcoes.map((op, idx) => (
            <div key={op.id} className="flex gap-1.5 items-center bg-black/30 rounded-lg p-1.5 border border-white/5">
              <span className="text-[9px] text-blue-400 font-black w-4">{idx + 1}</span>
              <input
                className="nodrag flex-1 bg-transparent text-[11px] text-white placeholder-slate-700 focus:outline-none"
                value={op.titulo}
                onChange={(e) => setOpcao(idx, "titulo", e.target.value)}
                placeholder="Título da opção"
              />
              <button type="button" onClick={() => removeOpcao(idx)} className="nodrag text-slate-700 hover:text-red-400 text-[10px] transition-colors">✕</button>
            </div>
          ))}
        </div>
      </div>

      {tipo === "button" && opcoes.length > 3 && (
        <p className="text-[9px] text-red-400 font-bold">⚠️ Máx. 3 botões no WhatsApp</p>
      )}
    </BaseNode>
  );
}
