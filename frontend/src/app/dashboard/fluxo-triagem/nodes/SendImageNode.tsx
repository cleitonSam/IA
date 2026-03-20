"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput, NodeTextarea } from "./BaseNode";

export default function SendImageNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="sendImage" {...props}>
      <NodeInput
        label="URL da imagem"
        value={data.url || ""}
        onChange={(v) => onChange?.({ url: v })}
        placeholder="https://exemplo.com/imagem.jpg"
        type="url"
      />
      <NodeTextarea
        label="Legenda (opcional)"
        value={data.caption || ""}
        onChange={(v) => onChange?.({ caption: v })}
        placeholder="Ex: Confira nosso catálogo! 🌟"
        rows={2}
      />
    </BaseNode>
  );
}
