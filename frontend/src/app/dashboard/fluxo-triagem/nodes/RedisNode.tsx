"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput } from "./BaseNode";

export default function RedisNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="redis" {...props}>
      <div className="space-y-3">
        <div>
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-1">Operação</p>
          <select
            value={data.operacao || "set"}
            onChange={(e) => onChange?.({ operacao: e.target.value })}
            className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] focus:outline-none"
          >
            <option value="set">SET (Salvar)</option>
            <option value="get">GET (Recuperar)</option>
            <option value="del">DEL (Deletar)</option>
          </select>
        </div>

        <NodeInput
          label="Chave (Key)"
          value={data.chave || ""}
          onChange={(v) => onChange?.({ chave: v })}
          placeholder="ex: user:{{phone}}"
        />

        {data.operacao === "set" && (
          <NodeInput
            label="Valor (Value)"
            value={data.valor || ""}
            onChange={(v) => onChange?.({ valor: v })}
            placeholder="Pode usar {{var}}"
          />
        )}

        {data.operacao === "get" && (
          <NodeInput
            label="Salvar em Variável"
            value={data.variavel_destino || ""}
            onChange={(v) => onChange?.({ variavel_destino: v })}
            placeholder="v_recuperada"
          />
        )}
      </div>
    </BaseNode>
  );
}
