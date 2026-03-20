"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeTextarea } from "./BaseNode";

export default function SendTextNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="sendText" {...props}>
      <NodeTextarea
        label="Mensagem"
        value={data.texto || ""}
        onChange={(v) => onChange?.({ texto: v })}
        placeholder="Ex: Olá, {{nome}}! Como posso ajudar?"
        rows={3}
      />
      <p className="text-[9px] text-slate-600">
        Use <span className="text-slate-400">{"{{variavel}}"}</span> para dados dinâmicos
      </p>
    </BaseNode>
  );
}
