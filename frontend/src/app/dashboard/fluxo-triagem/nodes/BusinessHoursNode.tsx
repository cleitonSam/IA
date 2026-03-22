"use client";
import React from "react";
import { NodeProps, Handle, Position } from "@xyflow/react";
import { NODE_CONFIG, NODE_BASE_CLASS } from "./nodeStyles";

export default function BusinessHoursNode(props: NodeProps) {
  const { selected } = props;
  const cfg = NODE_CONFIG["businessHours"];

  return (
    <div
      className={NODE_BASE_CLASS}
      style={{
        border: selected ? `2px solid ${cfg.border}` : `1px solid ${cfg.border}55`,
        background: "#0f172a",
        boxShadow: selected ? `0 0 20px ${cfg.border}55` : `0 4px 20px rgba(0,0,0,0.5)`,
        position: "relative",
        minWidth: 220,
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: cfg.border, width: 10, height: 10, border: `2px solid ${cfg.border}`, boxShadow: `0 0 6px ${cfg.border}` }}
      />

      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2" style={{ background: cfg.headerBg }}>
        <span className="text-base">🕐</span>
        <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: cfg.headerText }}>
          Horário Comercial
        </span>
      </div>

      {/* Body */}
      <div className="p-3 space-y-2">
        <p className="text-[10px] text-slate-400 leading-relaxed">
          Roteia baseado no horário configurado em{" "}
          <span className="text-sky-400 font-bold">Configurações → Personalidade</span>.
        </p>

        {/* Handles aberto / fechado */}
        <div className="space-y-1.5 mt-1">
          <div className="relative flex items-center bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-2 py-1.5">
            <span className="text-[10px] text-emerald-400 font-bold flex-1">✅ Aberto</span>
            <Handle
              type="source"
              position={Position.Right}
              id="aberto"
              style={{ background: "#22c55e", width: 10, height: 10, border: "2px solid #22c55e", boxShadow: "0 0 6px #22c55e", right: -12, top: "50%" }}
            />
          </div>
          <div className="relative flex items-center bg-red-500/10 border border-red-500/20 rounded-lg px-2 py-1.5">
            <span className="text-[10px] text-red-400 font-bold flex-1">🔴 Fechado</span>
            <Handle
              type="source"
              position={Position.Right}
              id="fechado"
              style={{ background: "#ef4444", width: 10, height: 10, border: "2px solid #ef4444", boxShadow: "0 0 6px #ef4444", right: -12, top: "50%" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
