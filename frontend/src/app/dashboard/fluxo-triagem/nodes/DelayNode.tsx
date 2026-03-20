"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode from "./BaseNode";

export default function DelayNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string | number>;
  const onChange = props.data?.onChange as ((patch: Record<string, string | number>) => void) | undefined;
  const seconds = Number(data.seconds) || 2;

  return (
    <BaseNode nodeType="delay" {...props}>
      <div className="space-y-1">
        <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Aguardar (segundos)</p>
        <input
          type="number"
          min={1}
          max={15}
          className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] focus:outline-none focus:border-white/20"
          value={seconds}
          onChange={(e) => onChange?.({ seconds: Number(e.target.value) })}
        />
        <p className="text-[9px] text-slate-600">Máximo: 15 segundos. Útil para simular digitação.</p>
      </div>
    </BaseNode>
  );
}
