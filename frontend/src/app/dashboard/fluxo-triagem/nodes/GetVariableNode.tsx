"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput } from "./BaseNode";

export default function GetVariableNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="getVariable" {...props}>
      <NodeInput
        label="Variável a Consultar"
        value={data.chave || ""}
        onChange={(v) => onChange?.({ chave: v })}
        placeholder="ex: saldo"
      />
      <p className="text-[9px] text-blue-800 mt-1">
        Apenas para visualização no fluxo ou debug.
      </p>
    </BaseNode>
  );
}
