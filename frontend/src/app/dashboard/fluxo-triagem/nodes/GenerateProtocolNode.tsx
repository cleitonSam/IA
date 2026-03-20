"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput } from "./BaseNode";

export default function GenerateProtocolNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="generateProtocol" {...props}>
      <NodeInput
        label="Salvar na Variável"
        value={data.variavel || ""}
        onChange={(v) => onChange?.({ variavel: v })}
        placeholder="padrão: protocolo"
      />
      <p className="text-[9px] text-emerald-800 mt-1">
        Gera um número aleatório de 6 dígitos.
      </p>
    </BaseNode>
  );
}
