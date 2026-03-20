"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput, NodeTextarea } from "./BaseNode";

export default function AIMenuNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="aiMenu" {...props}>
      <NodeTextarea
        label="Instrução para a IA"
        value={data.instrucao || ""}
        onChange={(v) => onChange?.({ instrucao: v })}
        placeholder="Ex: Gere um menu com 3 opções de planos."
        rows={3}
      />
      <div className="grid grid-cols-2 gap-2 mt-2">
        <NodeInput
          label="Texto Botão"
          value={data.botao || ""}
          onChange={(v) => onChange?.({ botao: v })}
          placeholder="Ver opções"
        />
        <NodeInput
          label="Rodapé"
          value={data.rodape || ""}
          onChange={(v) => onChange?.({ rodape: v })}
          placeholder="Panobianco"
        />
      </div>
      <p className="text-[9px] text-cyan-800 mt-1">
        A IA gerará o título, texto e opções do menu dinamicamente.
      </p>
    </BaseNode>
  );
}
