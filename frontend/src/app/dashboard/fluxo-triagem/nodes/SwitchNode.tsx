"use client";
import React from "react";
import { NodeProps, Handle, Position } from "@xyflow/react";
import { NODE_CONFIG, NODE_BASE_CLASS } from "./nodeStyles";

interface Condition { handle: string; label: string; value: string }

export default function SwitchNode(props: NodeProps) {
  const { selected } = props;
  const cfg = NODE_CONFIG["switch"];
  const data = (props.data || {}) as Record<string, unknown>;
  const onChange = props.data?.onChange as ((patch: Record<string, unknown>) => void) | undefined;

  const conditions: Condition[] = Array.isArray(data.conditions)
    ? (data.conditions as Condition[])
    : [];

  const addCond = () => {
    onChange?.({ conditions: [...conditions, { handle: `h${Date.now()}`, label: "", value: "" }] });
  };

  const removeCond = (idx: number) => {
    onChange?.({ conditions: conditions.filter((_, i) => i !== idx) });
  };

  const setCond = (idx: number, field: keyof Condition, val: string) => {
    const next = [...conditions];
    next[idx] = { ...next[idx], [field]: val };
    onChange?.({ conditions: next });
  };

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
        <span className="text-base">⚡</span>
        <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: cfg.headerText }}>
          Switch — Seleção de Menu
        </span>
      </div>

      <div className="p-3 space-y-2">
        {/* Cabeçalho */}
        <div className="flex items-center justify-between">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Condições</p>
          <button type="button" onClick={addCond}
            className="nodrag text-[9px] text-purple-400 hover:text-purple-300 font-bold border border-purple-500/20 px-2 py-0.5 rounded-md">
            + Adicionar
          </button>
        </div>

        {/* Inputs com scroll — SEM handles aqui */}
        <div className="space-y-1.5 max-h-[180px] overflow-y-auto nodrag">
          {conditions.map((cond, idx) => (
            <div key={cond.handle} className="flex gap-1.5 items-start bg-black/30 rounded-lg p-1.5 border border-white/5">
              <div className="flex-1 space-y-1 min-w-0">
                <input
                  className="nodrag w-full bg-transparent text-[11px] text-white placeholder-slate-700 focus:outline-none border-b border-white/5 pb-0.5"
                  value={cond.label}
                  onChange={(e) => setCond(idx, "label", e.target.value)}
                  placeholder="Label (ex: Suporte)"
                />
                <input
                  className="nodrag w-full bg-transparent text-[10px] text-slate-500 placeholder-slate-700 focus:outline-none"
                  value={cond.value}
                  onChange={(e) => setCond(idx, "value", e.target.value)}
                  placeholder="Valor (ex: 1)"
                />
              </div>
              <button type="button" onClick={() => removeCond(idx)}
                className="nodrag text-slate-700 hover:text-red-400 text-[10px] mt-0.5 flex-shrink-0">✕</button>
            </div>
          ))}
        </div>

        {/* Saídas — fora do scroll, handles funcionam normalmente */}
        {conditions.length > 0 && (
          <div className="space-y-1 pt-1 border-t border-white/5">
            <p className="text-[9px] font-black text-slate-600 uppercase tracking-widest">Saídas</p>
            {conditions.map((cond) => (
              <div key={cond.handle} className="relative flex items-center bg-black/20 rounded-lg px-2 py-1.5 border border-white/5">
                <div className="w-1.5 h-1.5 rounded-full mr-2 flex-shrink-0" style={{ background: cfg.border }} />
                <span className="text-[10px] font-bold flex-1 truncate" style={{ color: cfg.headerText }}>
                  {cond.label || "—"}
                </span>
                <Handle
                  type="source"
                  position={Position.Right}
                  id={cond.handle}
                  style={{
                    background: cfg.border,
                    width: 10,
                    height: 10,
                    border: `2px solid ${cfg.border}`,
                    boxShadow: `0 0 6px ${cfg.border}`,
                    right: -12,
                    top: "50%",
                    transform: "translateY(-50%)",
                    position: "absolute",
                  }}
                />
              </div>
            ))}
          </div>
        )}

        <p className="text-[9px] text-purple-900">
          Ramifica de acordo com a opção de menu selecionada pelo usuário.
        </p>
      </div>
    </div>
  );
}
