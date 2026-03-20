"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput } from "./BaseNode";

export default function SendMediaNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="sendMedia" {...props}>
      <div className="space-y-3">
        <div>
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-1">Tipo de Mídia</p>
          <select
            value={data.type || "image"}
            onChange={(e) => onChange?.({ type: e.target.value })}
            className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] focus:outline-none"
          >
            <option value="image">Imagem (image)</option>
            <option value="video">Vídeo (video)</option>
            <option value="document">Documento (document)</option>
          </select>
        </div>

        <NodeInput
          label="URL do Arquivo"
          value={data.url || ""}
          onChange={(v) => onChange?.({ url: v })}
          placeholder="https://exemplo.com/arquivo.png"
        />

        {data.type !== "document" && (
          <NodeInput
            label="Legenda (Caption)"
            value={data.caption || ""}
            onChange={(v) => onChange?.({ caption: v })}
            placeholder="Opcional"
          />
        )}
      </div>
      <p className="text-[9px] text-rose-800 mt-1 leading-tight">
        Envia mídia via UazAPI. Certifique-se de que a URL é direta e pública.
      </p>
    </BaseNode>
  );
}
