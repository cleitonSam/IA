"use client";
import React from "react";
import { NodeProps, Handle, Position } from "@xyflow/react";
import { NODE_CONFIG, NODE_BASE_CLASS } from "./nodeStyles";

interface Condition { handle: string; label: string }

export default function AIClassifyNode(props: NodeProps) {
  const { selected } = props;
  const data = (props.data || {}) as Record<string, unknown>;
  const onChange = props.data?.onChange as ((patch: Record<string, unknown>) => void) | undefined;
  const cfg = NODE_CONFIG["aiClassify"];

  const conditions: Condition[] = Array.isArray(data.conditions)
    ? (data.conditions as Condition[])
    : [];
  const varName = (data.variavel as string) || "intencao";

  const addCondition = () => {
    const newHandle = `h${Date.now()}`;
    onChange?.({ conditions: [...conditions, { handle: newHandle, label: "" }] });
  };

  const removeCondition = (idx: number) => {
    onChange?.({ conditions: conditions.filter((_, i) => i !== idx) });
  };

  const setLabel = (idx: number, label: string) => {
    const next = [...conditions];
    next[idx] = { ...next[idx], label };
    onChange?.({ conditions: next });
  };

  const handleCount = conditions.length;

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
        <span className="text-base">🏷</span>
        <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: cfg.headerText }}>
          IA: Classificar
        </span>
      </div>

      <div className="p-3 space-y-2">
        <div className="space-y-1">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Salvar em variável</p>
          <input
            className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] placeholder-slate-700 focus:outline-none focus:border-white/20"
            value={varName}
            onChange={(e) => onChange?.({ variavel: e.target.value })}
            placeholder="intencao"
          />
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">
              Categorias ({conditions.length})
            </p>
            <button type="button" onClick={addCondition}
              className="nodrag text-[9px] text-blue-400 hover:text-blue-300 font-bold border border-blue-500/20 px-2 py-0.5 rounded-md">
              + Adicionar
            </button>
          </div>

          {conditions.map((cond, idx) => (
            <div key={cond.handle} className="relative flex gap-1.5 items-center bg-black/30 rounded-lg p-1.5 border border-white/5">
              <input
                className="nodrag flex-1 bg-transparent text-[11px] text-white placeholder-slate-700 focus:outline-none"
                value={cond.label}
                onChange={(e) => setLabel(idx, e.target.value)}
                placeholder={`Ex: Suporte, Vendas...`}
              />
              <button type="button" onClick={() => removeCondition(idx)}
                className="nodrag text-slate-700 hover:text-red-400 text-[10px]">✕</button>
              {/* Handle de saída por categoria */}
              <Handle
                type="source"
                position={Position.Right}
                id={cond.handle}
                style={{
                  background: cfg.border,
                  width: 8,
                  height: 8,
                  border: `2px solid ${cfg.border}`,
                  boxShadow: `0 0 4px ${cfg.border}`,
                  right: -12,
                  top: "50%",
                }}
              />
            </div>
          ))}
        </div>
        <p className="text-[9px] text-blue-900">
          A IA escolhe a categoria que melhor descreve a mensagem e ramifica automaticamente.
        </p>
      </div>
    </div>
  );
}
