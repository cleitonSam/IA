"use client";
import React from "react";
import { Handle, Position, NodeProps } from "@xyflow/react";
import { NODE_CONFIG, NODE_BASE_CLASS, NodeTypeName } from "./nodeStyles";

interface BaseNodeProps extends NodeProps {
  nodeType: NodeTypeName;
  children?: React.ReactNode;
  /** Handles de saída customizados (ex: switch com múltiplos handles) */
  customOutputHandles?: Array<{ id: string; label: string; top?: number }>;
  /** Se false, não renderiza o handle padrão de saída */
  defaultOutputHandle?: boolean;
  /** Se false, não renderiza o handle padrão de entrada */
  defaultInputHandle?: boolean;
}

export default function BaseNode({
  nodeType,
  children,
  customOutputHandles,
  defaultOutputHandle = true,
  defaultInputHandle = true,
  selected,
}: BaseNodeProps) {
  const cfg = NODE_CONFIG[nodeType];
  if (!cfg) return null;

  const borderStyle = selected
    ? `2px solid ${cfg.border}`
    : `1px solid ${cfg.border}55`;

  return (
    <div
      className={NODE_BASE_CLASS}
      style={{
        border: borderStyle,
        background: "#0f172a",
        boxShadow: selected
          ? `0 0 20px ${cfg.border}55`
          : `0 4px 20px rgba(0,0,0,0.5)`,
        transition: "all 0.2s ease",
      }}
    >
      {/* Handle de entrada */}
      {defaultInputHandle && (
        <Handle
          type="target"
          position={Position.Left}
          style={{
            background: cfg.border,
            width: 10,
            height: 10,
            border: `2px solid ${cfg.border}`,
            boxShadow: `0 0 6px ${cfg.border}`,
          }}
        />
      )}

      {/* Header */}
      <div
        className="flex items-center gap-2 px-3 py-2"
        style={{ background: cfg.headerBg }}
      >
        <span className="text-base leading-none">{cfg.icon}</span>
        <span
          className="text-[10px] font-black uppercase tracking-widest"
          style={{ color: cfg.headerText }}
        >
          {cfg.label}
        </span>
      </div>

      {/* Body */}
      {children && (
        <div className="p-3 space-y-2">{children}</div>
      )}

      {/* Handles de saída customizados (ex: Switch, Condition, AISentiment) */}
      {customOutputHandles ? (
        customOutputHandles.map((h, i) => (
          <div key={h.id}>
            <Handle
              type="source"
              position={Position.Right}
              id={h.id}
              style={{
                background: cfg.border,
                width: 10,
                height: 10,
                border: `2px solid ${cfg.border}`,
                boxShadow: `0 0 6px ${cfg.border}`,
                top: h.top ?? `${(i + 1) * (100 / (customOutputHandles.length + 1))}%`,
                right: -5,
              }}
            />
            <div
              className="absolute text-[9px] font-bold"
              style={{
                color: cfg.border,
                right: 14,
                top: `calc(${h.top ?? ((i + 1) * (100 / (customOutputHandles.length + 1)))}% - 6px)`,
              }}
            >
              {h.label}
            </div>
          </div>
        ))
      ) : defaultOutputHandle ? (
        <Handle
          type="source"
          position={Position.Right}
          style={{
            background: cfg.border,
            width: 10,
            height: 10,
            border: `2px solid ${cfg.border}`,
            boxShadow: `0 0 6px ${cfg.border}`,
          }}
        />
      ) : null}
    </div>
  );
}

/** Campo de input reutilizável para os nós */
export function NodeInput({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: "text" | "number" | "url";
}) {
  return (
    <div className="space-y-1">
      {label && (
        <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">
          {label}
        </p>
      )}
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] placeholder-slate-700 focus:outline-none focus:border-white/20"
      />
    </div>
  );
}

/** Textarea reutilizável */
export function NodeTextarea({
  label,
  value,
  onChange,
  placeholder,
  rows = 3,
}: {
  label?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <div className="space-y-1">
      {label && (
        <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">
          {label}
        </p>
      )}
      <textarea
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] placeholder-slate-700 focus:outline-none focus:border-white/20 resize-none"
      />
    </div>
  );
}
