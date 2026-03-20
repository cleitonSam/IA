"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput, NodeTextarea } from "./BaseNode";

export default function SearchNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode
      nodeType="search"
      {...props}
      customOutputHandles={[
        { id: "found", label: "Encontrado" },
        { id: "not_found", label: "Não Encontrado" },
      ]}
    >
      <NodeTextarea
        label="Termo de Busca"
        value={data.termo || ""}
        onChange={(v) => onChange?.({ termo: v })}
        placeholder="Ex: {{mensagem}} ou texto fixo"
        rows={2}
      />
      <NodeInput
        label="Variável de Saída"
        value={data.variavel || ""}
        onChange={(v) => onChange?.({ variavel: v })}
        placeholder="v_resultado"
      />
      <p className="text-[9px] text-teal-800 mt-1">
        Busca no FAQ/Conhecimento e retorna a resposta se encontrada.
      </p>
    </BaseNode>
  );
}
