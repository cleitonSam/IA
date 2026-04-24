"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeTextarea } from "./BaseNode";

export default function AddLabelNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  const labelsStr = Array.isArray(data.labels) ? data.labels.join(", ") : (data.labels || "");
  return (
    <BaseNode nodeType="addLabel" {...props}>
      <NodeTextarea
        label="Labels (separadas por virgula)"
        value={labelsStr}
        onChange={(v) => onChange?.({ labels: v.split(",").map(s => s.trim()).filter(Boolean) })}
        placeholder="VIP, Lead-Quente, {{origem}}"
        rows={2}
      />
      <p className="text-[9px] text-slate-600">Adiciona tags no contato (visivel no painel UazAPI).</p>
    </BaseNode>
  );
}
