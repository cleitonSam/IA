"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeTextarea } from "./BaseNode";

export default function SendLocationNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  return (
    <BaseNode nodeType="sendLocation" {...props}>
      <div className="space-y-1.5">
        <input
          type="text"
          placeholder="Latitude (ex: -23.5505)"
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.latitude || ""}
          onChange={(e) => onChange?.({ latitude: e.target.value })}
        />
        <input
          type="text"
          placeholder="Longitude (ex: -46.6333)"
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.longitude || ""}
          onChange={(e) => onChange?.({ longitude: e.target.value })}
        />
        <input
          type="text"
          placeholder="Nome do local"
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.name || ""}
          onChange={(e) => onChange?.({ name: e.target.value })}
        />
        <NodeTextarea
          label="Endereço"
          value={data.address || ""}
          onChange={(v) => onChange?.({ address: v })}
          placeholder="Ex: Av. Paulista, 1000 — São Paulo"
          rows={2}
        />
      </div>
    </BaseNode>
  );
}
