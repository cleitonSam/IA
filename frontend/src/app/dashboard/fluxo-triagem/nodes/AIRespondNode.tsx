"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeTextarea } from "./BaseNode";

export default function AIRespondNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="aiRespond" {...props}>
      <NodeTextarea
        label="Instruções extras (opcional)"
        value={data.prompt_extra || ""}
        onChange={(v) => onChange?.({ prompt_extra: v })}
        placeholder="Ex: Foque em suporte técnico. Seja objetivo."
        rows={3}
      />
      <p className="text-[9px] text-cyan-800">
        A IA usa toda a personalidade configurada + estas instruções para responder.
      </p>
    </BaseNode>
  );
}
