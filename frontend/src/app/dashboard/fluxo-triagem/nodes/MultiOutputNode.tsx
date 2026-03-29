"use client";
import React from "react";
import { Handle, Position } from "@xyflow/react";
import { NODE_CONFIG, NODE_BASE_CLASS, type NodeTypeName } from "./nodeStyles";

interface OutputItem {
  id: string;
  label: string;
}

interface MultiOutputNodeProps {
  nodeType: NodeTypeName;
  title: string;
  icon?: string;
  selected: boolean;
  outputs: OutputItem[];
  children: React.ReactNode;
  description?: string;
}

/**
 * Reusable wrapper for nodes with multiple output handles (Switch, AIClassify, MenuFixoIA, etc.).
 *
 * Renders:
 * - Input handle (left)
 * - Header with icon + title + color from nodeStyles
 * - Children (node-specific content)
 * - Output handles section with positioned handles (right: -12)
 * - Optional description footer
 *
 * Usage:
 *   <MultiOutputNode nodeType="switch" title="Switch" selected={selected} outputs={conditions}>
 *     <div>...node-specific inputs...</div>
 *   </MultiOutputNode>
 */
export default function MultiOutputNode({
  nodeType,
  title,
  icon,
  selected,
  outputs,
  children,
  description,
}: MultiOutputNodeProps) {
  const cfg = NODE_CONFIG[nodeType];
  const displayIcon = icon || cfg.icon;

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
      {/* Input handle */}
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

      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2" style={{ background: cfg.headerBg }}>
        <span className="text-base">{displayIcon}</span>
        <span
          className="text-[10px] font-black uppercase tracking-widest"
          style={{ color: cfg.headerText }}
        >
          {title}
        </span>
      </div>

      {/* Content */}
      <div className="p-3 space-y-2">
        {children}

        {/* Output handles */}
        {outputs.length > 0 && (
          <div className="space-y-1 pt-1 border-t border-white/5">
            <p className="text-[9px] font-black text-slate-600 uppercase tracking-widest">
              Saídas
            </p>
            {outputs.map((output) => (
              <div
                key={output.id}
                className="relative flex items-center bg-black/20 rounded-lg px-2 py-1.5 border border-white/5"
              >
                <div
                  className="w-1.5 h-1.5 rounded-full mr-2 flex-shrink-0"
                  style={{ background: cfg.border }}
                />
                <span
                  className="text-[10px] font-bold flex-1 truncate"
                  style={{ color: cfg.headerText }}
                >
                  {output.label || "—"}
                </span>
                <Handle
                  type="source"
                  position={Position.Right}
                  id={output.id}
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

        {/* Description */}
        {description && (
          <p className="text-[9px]" style={{ color: `${cfg.border}66` }}>
            {description}
          </p>
        )}
      </div>
    </div>
  );
}
