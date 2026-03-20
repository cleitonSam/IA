"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeTextarea } from "./BaseNode";

export default function HumanTransferNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="humanTransfer" {...props} defaultOutputHandle={false}>
      <NodeTextarea
        label="Mensagem de transferência"
        value={data.mensagem || ""}
        onChange={(v) => onChange?.({ mensagem: v })}
        placeholder="Ex: Transferindo para um atendente. Aguarde! 👤"
        rows={2}
      />
      <p className="text-[9px] text-orange-700 font-bold">
        ⚠️ A IA será pausada para este contato por 24h. Para reativar, use o painel de conversas.
      </p>
    </BaseNode>
  );
}
