"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeTextarea } from "./BaseNode";

export default function RemoveLabelNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  const labelsStr = Array.isArray(data.labels) ? data.labels.join(", ") : (data.labels || "");
  return (
    <BaseNode nodeType="removeLabel" {...props}>
      <NodeTextarea
        label="Labels a remover"
        value={labelsStr}
        onChange={(v) => onChange?.({ labels: v.split(",").map(s => s.trim()).filter(Boolean) })}
        placeholder="Lead-Frio, Pendente"
        rows={2}
      />
    </BaseNode>
  );
}
