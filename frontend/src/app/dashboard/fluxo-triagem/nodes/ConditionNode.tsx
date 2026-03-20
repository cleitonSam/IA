"use client";
import React from "react";
import { NodeProps, Handle, Position } from "@xyflow/react";
import { NODE_CONFIG, NODE_BASE_CLASS } from "./nodeStyles";

const OUTPUTS = [
  { id: "sim",  label: "✅ Sim", color: "#22c55e" },
  { id: "nao",  label: "❌ Não", color: "#ef4444" },
];

export default function ConditionNode(props: NodeProps) {
  const { selected } = props;
  const cfg = NODE_CONFIG["condition"];
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <div
      className={NODE_BASE_CLASS}
      style={{
        border: selected ? `2px solid ${cfg.border}` : `1px solid ${cfg.border}55`,
        background: "#0f172a",
        boxShadow: selected ? `0 0 20px ${cfg.border}55` : `0 4px 20px rgba(0,0,0,0.5)`,
        position: "relative",
      }}
    >
      <Handle type="target" position={Position.Left}
        style={{ background: cfg.border, width: 10, height: 10, border: `2px solid ${cfg.border}`, boxShadow: `0 0 6px ${cfg.border}` }} />

      <div className="flex items-center gap-2 px-3 py-2" style={{ background: cfg.headerBg }}>
        <span className="text-base">❓</span>
        <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: cfg.headerText }}>
          Condição (Regex / Palavra)
        </span>
      </div>

      <div className="p-3 space-y-2">
        <div className="space-y-1">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Padrão (regex ou texto)</p>
          <input
            className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] placeholder-slate-700 focus:outline-none focus:border-white/20"
            value={data.pattern || ""}
            onChange={(e) => onChange?.({ pattern: e.target.value })}
            placeholder="Ex: suporte|ajuda|problema"
          />
        </div>

        <div className="space-y-1.5">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Saídas</p>
          {OUTPUTS.map((out) => (
            <div key={out.id} className="relative flex items-center bg-black/30 rounded-lg px-2 py-1.5 border border-white/5">
              <span className="text-[11px] text-white">{out.label}</span>
              <Handle
                type="source"
                position={Position.Right}
                id={out.id}
                style={{
                  background: out.color,
                  width: 8,
                  height: 8,
                  border: `2px solid ${out.color}`,
                  boxShadow: `0 0 4px ${out.color}`,
                  right: -12,
                  top: "50%",
                }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
