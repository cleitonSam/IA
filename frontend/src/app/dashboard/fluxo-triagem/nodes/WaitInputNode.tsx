"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput, NodeTextarea } from "./BaseNode";

export default function WaitInputNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="waitInput" {...props}>
      <NodeTextarea
        label="Mensagem de prompt (opcional)"
        value={data.prompt || ""}
        onChange={(v) => onChange?.({ prompt: v })}
        placeholder="Ex: Por favor, me informe seu nome completo:"
        rows={2}
      />
      <NodeInput
        label="Salvar resposta em variável"
        value={data.variavel || ""}
        onChange={(v) => onChange?.({ variavel: v })}
        placeholder="Ex: nome_cliente"
      />
      <p className="text-[9px] text-slate-600">
        O fluxo pausa e aguarda a próxima mensagem do usuário.
      </p>
    </BaseNode>
  );
}
