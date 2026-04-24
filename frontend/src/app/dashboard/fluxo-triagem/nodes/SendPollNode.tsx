"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeTextarea } from "./BaseNode";

export default function SendPollNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  const opcoes: string[] = Array.isArray(data.opcoes) ? data.opcoes : [];
  const updateOpcao = (i: number, v: string) => {
    const next = [...opcoes];
    next[i] = v;
    onChange?.({ opcoes: next });
  };
  const addOpcao = () => onChange?.({ opcoes: [...opcoes, ""] });
  const removeOpcao = (i: number) => onChange?.({ opcoes: opcoes.filter((_, idx) => idx !== i) });

  return (
    <BaseNode nodeType="sendPoll" {...props}>
      <div className="space-y-1.5">
        <NodeTextarea
          label="Pergunta"
          value={data.pergunta || ""}
          onChange={(v) => onChange?.({ pergunta: v })}
          placeholder="Qual sua opcao preferida?"
          rows={2}
        />
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
          <input
            type="checkbox"
            checked={!!data.multi_select}
            onChange={(e) => onChange?.({ multi_select: e.target.checked })}
          />
          Permitir multipla escolha
        </label>
        <div className="space-y-1">
          {opcoes.map((o, i) => (
            <div key={i} className="flex gap-1">
              <input
                type="text"
                placeholder={`Opcao ${i + 1}`}
                className="flex-1 text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
                value={o}
                onChange={(e) => updateOpcao(i, e.target.value)}
              />
              <button
                onClick={() => removeOpcao(i)}
                className="text-[10px] text-red-400 hover:text-red-300 px-1"
              >✕</button>
            </div>
          ))}
          <button
            onClick={addOpcao}
            className="text-[10px] text-sky-400 hover:text-sky-300"
          >+ adicionar opcao</button>
        </div>
      </div>
    </BaseNode>
  );
}
