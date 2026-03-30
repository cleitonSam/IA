"use client";
import React from "react";
import { NodeProps, Handle, Position } from "@xyflow/react";
import { NODE_CONFIG, NODE_BASE_CLASS } from "./nodeStyles";

export default function GoToMenuNode({ selected }: NodeProps) {
  const cfg = NODE_CONFIG["goToMenu"];
  return (
    <div
      className={NODE_BASE_CLASS}
      style={{
        border: selected ? `2px solid ${cfg.border}` : `1px solid ${cfg.border}55`,
        background: "#0f172a",
        boxShadow: selected ? `0 0 20px ${cfg.border}55` : `0 4px 20px rgba(0,0,0,0.5)`,
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: cfg.border, width: 10, height: 10, border: `2px solid ${cfg.border}`, boxShadow: `0 0 6px ${cfg.border}` }}
      />
      <div className="flex items-center gap-2 px-3 py-2.5" style={{ background: cfg.headerBg }}>
        <span className="text-lg">↩️</span>
        <div>
          <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: cfg.headerText }}>
            Voltar ao Menu
          </p>
          <p className="text-[9px] mt-0.5" style={{ color: cfg.headerText, opacity: 0.6 }}>
            Reinicia o fluxo do início
          </p>
        </div>
      </div>
    </div>
  );
}
