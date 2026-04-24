"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode from "./BaseNode";

export default function SetPresenceNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  return (
    <BaseNode nodeType="setPresence" {...props}>
      <div className="space-y-1.5">
        <label className="block text-[10px] text-slate-400">Estado</label>
        <select
          value={data.estado || "composing"}
          onChange={(e) => onChange?.({ estado: e.target.value })}
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
        >
          <option value="composing">Digitando...</option>
          <option value="recording">Gravando audio...</option>
          <option value="paused">Parado</option>
          <option value="available">Online</option>
          <option value="unavailable">Offline</option>
        </select>
        <label className="block text-[10px] text-slate-400 mt-2">Duracao (ms)</label>
        <input
          type="number"
          min={500}
          max={30000}
          value={data.duracao_ms || 2000}
          onChange={(e) => onChange?.({ duracao_ms: parseInt(e.target.value) || 2000 })}
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
        />
        <p className="text-[9px] text-slate-600">Mostra "Digitando..." para o cliente.</p>
      </div>
    </BaseNode>
  );
}
