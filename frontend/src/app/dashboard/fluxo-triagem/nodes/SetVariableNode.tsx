"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput } from "./BaseNode";

export default function SetVariableNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="setVariable" {...props}>
      <NodeInput
        label="Nome da Variável"
        value={data.chave || ""}
        onChange={(v) => onChange?.({ chave: v })}
        placeholder="ex: nome_usuario"
      />
      <NodeInput
        label="Valor"
        value={data.valor || ""}
        onChange={(v) => onChange?.({ valor: v })}
        placeholder="pode usar {{protocolo}}"
      />
    </BaseNode>
  );
}
