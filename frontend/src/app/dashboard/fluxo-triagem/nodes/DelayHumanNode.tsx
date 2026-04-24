"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode from "./BaseNode";

export default function DelayHumanNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  return (
    <BaseNode nodeType="delayHuman" {...props}>
      <div className="space-y-1.5">
        <div className="flex gap-1 items-center">
          <label className="text-[10px] text-slate-400">Min (s)</label>
          <input
            type="number" step="0.5" min={0.5} max={20}
            className="flex-1 text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
            value={data.min_seconds ?? 2}
            onChange={(e) => onChange?.({ min_seconds: parseFloat(e.target.value) || 2 })}
          />
        </div>
        <div className="flex gap-1 items-center">
          <label className="text-[10px] text-slate-400">Max (s)</label>
          <input
            type="number" step="0.5" min={0.5} max={30}
            className="flex-1 text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
            value={data.max_seconds ?? 5}
            onChange={(e) => onChange?.({ max_seconds: parseFloat(e.target.value) || 5 })}
          />
        </div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
          <input
            type="checkbox"
            checked={data.show_typing !== false}
            onChange={(e) => onChange?.({ show_typing: e.target.checked })}
          />
          Mostrar "digitando..."
        </label>
        <p className="text-[9px] text-slate-600">Delay aleatório (simula humano).</p>
      </div>
    </BaseNode>
  );
}
