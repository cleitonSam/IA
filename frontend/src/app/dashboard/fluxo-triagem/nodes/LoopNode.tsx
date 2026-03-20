"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput } from "./BaseNode";

export default function LoopNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="loop" {...props}>
      <NodeInput
        label="Voltar para nó ID"
        value={data.target_node_id || ""}
        onChange={(v) => onChange?.({ target_node_id: v })}
        placeholder="ID do nó destino"
      />
      <p className="text-[9px] text-orange-700 mt-1">
        Máximo de 3 tentativas. Após isso segue para o próximo nó.
      </p>
    </BaseNode>
  );
}
